"""Mechanical gates: leakage, determinism, the formulae, the case-file guard, theme."""
import json
import re
import subprocess
import unittest
from pathlib import Path

from ews import config, run as engine
from ews.casefile import verify
from ews.llm import FallbackLLM, keyword_grade, strict_resolve
from ews.loader import DataError, NEWS_LABEL_COLUMNS, Loader, LeakageError

ROOT = Path(__file__).resolve().parent.parent


class Leakage(unittest.TestCase):
    def test_label_tables_refused_for_engine(self):
        for table in ("ground_truth", "payment_behaviour_monthly"):
            with self.assertRaises(LeakageError):
                Loader().table(table)

    def test_harness_may_read_them(self):
        self.assertTrue(Loader(harness=True).table("ground_truth"))

    def test_gt_columns_stripped_from_news(self):
        for article in Loader(demo_steps=7).news():
            for col in NEWS_LABEL_COLUMNS:
                self.assertNotIn(col, article)

    def test_harness_keeps_gt_columns(self):
        self.assertIn("gt_severity", Loader(harness=True).news()[0])

    def test_no_engine_file_names_the_labels(self):
        hits = subprocess.run(
            ["grep", "-rnI", "--include=*.py", "--include=*.html", "--include=*.css",
             "-e", "ground_truth", "-e", "payment_behaviour_monthly",
             str(ROOT / "ews"), str(ROOT / "dashboard")],
            capture_output=True, text=True).stdout.strip()
        # loader.py names them only to refuse them
        offending = [l for l in hits.splitlines() if "/loader.py:" not in l]
        self.assertEqual(offending, [], f"engine code references the labels:\n{hits}")


class Guards(unittest.TestCase):
    """Boundary conditions that used to pass silently."""

    def test_an_invoice_not_yet_due_cannot_lower_the_score(self):
        self.assertEqual(config.payment_score(-5), 0.0)
        self.assertEqual(config.payment_score(-500), 0.0)

    def test_a_non_finite_score_is_refused_not_reported_healthy(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config.band(bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                config.pd_for(bad)

    def test_fractional_policy_percentages_are_accepted(self):
        from ews.limits import _insured
        got = _insured(1_000_000, {"indemnity_pct": "87.5", "deductible_pct": "10",
                                   "max_liability_eur": "1e12"})
        self.assertAlmostEqual(got, 1_000_000 * 0.875 * 0.9)

    def test_demo_steps_out_of_range_is_refused(self):
        for bad in (-1, -7, 999):
            with self.assertRaises(ValueError, msg=str(bad)):
                Loader(demo_steps=bad)

    def test_a_settled_invoice_with_no_payment_date_names_itself(self):
        from ews.agents.payment import _days_late
        with self.assertRaises(DataError) as ctx:
            _days_late({"invoice_id": "INV1", "payment_date": "", "due_date": "2026-01-01"})
        self.assertIn("INV1", str(ctx.exception))

    def test_the_case_file_guard_does_not_accept_a_rupee_era_scaling(self):
        from ews.casefile import allowed_numbers
        allowed = allowed_numbers({"verdict": {"score": 4_280_000}})
        self.assertIn(4.28, allowed, "millions is a legitimate way to write it")
        self.assertNotIn(42.8, allowed, "lakh is not - it would let a wrong figure through")


class Integrity(unittest.TestCase):
    """The shipped dataset must hold together, and a broken one must say so."""

    def test_the_shipped_dataset_is_consistent(self):
        Loader().validate()

    def _corrupt(self, mutate):
        import csv, shutil, tempfile
        from pathlib import Path as P
        tmp = tempfile.mkdtemp()
        d = P(tmp) / "data"
        shutil.copytree(ROOT / "data", d)
        mutate(d)
        return d

    @staticmethod
    def _rows(p):
        import csv
        return list(csv.DictReader(p.open(newline="")))

    @staticmethod
    def _write(p, rs):
        import csv
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, list(rs[0])); w.writeheader(); w.writerows(rs)

    def test_duplicate_ids_are_caught(self):
        def m(d):
            r = self._rows(d / "buyers.csv"); r.append(dict(r[0])); self._write(d / "buyers.csv", r)
        with self.assertRaises(DataError):
            Loader(self._corrupt(m)).validate()

    def test_a_buyer_on_no_insurers_book_is_caught(self):
        def m(d):
            r = self._rows(d / "credit_limits.csv"); self._write(d / "credit_limits.csv", r[1:])
        with self.assertRaises(DataError):
            Loader(self._corrupt(m)).validate()

    def test_a_reference_to_an_absent_entity_is_caught(self):
        def m(d):
            r = self._rows(d / "buyers.csv"); r[0]["parent_id"] = "PAR99"
            self._write(d / "buyers.csv", r)
        with self.assertRaises(DataError):
            Loader(self._corrupt(m)).validate()

    def test_an_invoice_for_an_unknown_buyer_is_caught(self):
        def m(d):
            r = self._rows(d / "invoices.csv"); r[0]["buyer_id"] = "BUY999"
            self._write(d / "invoices.csv", r)
        with self.assertRaises(DataError):
            Loader(self._corrupt(m)).validate()


class Determinism(unittest.TestCase):
    def test_same_inputs_give_identical_output(self):
        a = json.dumps(engine.run(llm=FallbackLLM(cache=False)), sort_keys=True)
        b = json.dumps(engine.run(llm=FallbackLLM(cache=False)), sort_keys=True)
        self.assertEqual(a, b)


class Formula(unittest.TestCase):
    def test_payment_knees(self):
        self.assertAlmostEqual(config.payment_score(0), 0.0)
        self.assertAlmostEqual(config.payment_score(30), 40.0)
        self.assertAlmostEqual(config.payment_score(60), 100.0)
        self.assertAlmostEqual(config.payment_score(90), 100.0, msg="must cap at 100")

    def test_band_boundaries(self):
        self.assertEqual(config.band(34.9), "Healthy")
        self.assertEqual(config.band(35.0), "Watch")
        self.assertEqual(config.band(59.9), "Watch")
        self.assertEqual(config.band(60.0), "High Risk")

    def test_pd_anchors_and_target(self):
        for score, pd in config.PD_ANCHORS:
            self.assertAlmostEqual(config.pd_for(score), pd, places=6)
        self.assertAlmostEqual(config.PD_TARGET, 0.25, places=6,
                               msg="D6 risk appetite must be PD at score 35")

    def test_news_alone_cannot_leave_healthy(self):
        worst = config.W_NEWS * config.NEWS_BASE[5]
        self.assertLess(worst, config.BAND_WATCH)

    def test_decay_half_life(self):
        self.assertAlmostEqual(config.decay(config.NEWS_HALF_LIFE_DAYS), 0.5)

    def test_news_the_run_could_not_have_seen_scores_zero(self):
        for future in (-1, -30, -365):
            self.assertEqual(config.decay(future), 0.0, f"age {future}")

    def test_news_past_the_relevance_horizon_scores_zero(self):
        for old in (config.NEWS_MAX_AGE_DAYS, config.NEWS_MAX_AGE_DAYS + 1, 4 * 365):
            self.assertEqual(config.decay(old), 0.0, f"age {old}")

    def test_the_horizon_is_a_fade_not_a_cliff(self):
        """No buyer may improve overnight because an article aged out."""
        step = config.W_NEWS * config.NEWS_BASE[5]
        worst = max(abs(step * config.decay(d) - step * config.decay(d + 1))
                    for d in range(0, config.NEWS_MAX_AGE_DAYS))
        self.assertLess(worst, 0.25, "a single day must not move the score materially")

    def test_decay_never_increases_with_age(self):
        vals = [config.decay(d) for d in range(0, config.NEWS_MAX_AGE_DAYS + 10)]
        self.assertEqual(vals, sorted(vals, reverse=True))


class Resolution(unittest.TestCase):
    CANDS = [{"kind": "buyer", "id": "B1", "name": "Arcline Fabrications NV"},
             {"kind": "buyer", "id": "B2", "name": "Marchetti Mills SpA"},
             {"kind": "buyer", "id": "B3", "name": "Rheinfels Industries GmbH"},
             {"kind": "buyer", "id": "B4", "name": "Kessler Traders GmbH"},
             {"kind": "parent", "id": "P3", "name": "Northpoint Industrial Holdings Ltd"}]

    def test_accepts_genuine_variants(self):
        for mention in ("Arcline", "Arcline Inds.", "ARCLINE FABRICATIONS NV"):
            self.assertEqual(strict_resolve(mention, self.CANDS)["id"], "B1", mention)

    def test_refuses_decoys(self):
        for mention in ("Arcline Media BV", "Marchetti Clinics SpA",
                        "Kessler Logistics GmbH"):
            self.assertIsNone(strict_resolve(mention, self.CANDS), mention)

    def test_resolves_parent(self):
        got = strict_resolve("Northpoint Industrial Holdings Ltd", self.CANDS)
        self.assertEqual((got["kind"], got["id"]), ("parent", "P3"))

    def test_grader_matches_dataset_categories(self):
        self.assertEqual(keyword_grade({"headline": "Workers protest over delayed wages",
                                        "body": ""})["severity"], 5)
        self.assertEqual(keyword_grade({"headline": "X appoints new plant head",
                                        "body": ""})["severity"], 0)


class CaseFileGuard(unittest.TestCase):
    FACTS = {"verdict": {"score": 37.3, "payment": {"dpd": 25, "weighted": 21.7}},
             "limits": [{"current_limit": 8800000, "revised_limit": 6200000}]}

    def test_accepts_faithful_text(self):
        good = "Scores 37.3 with the worst invoice 25 days past due; limit 8.8M cut to 6.2M."
        self.assertEqual(verify(good, self.FACTS), [])

    def test_rejects_invented_figures(self):
        self.assertTrue(verify("Exposure is about 12.4M and it is 41 days late.", self.FACTS))


class Theme(unittest.TestCase):
    def test_no_hex_outside_theme_css(self):
        offenders = []
        for path in (ROOT / "dashboard").rglob("*"):
            if path.suffix in {".py", ".html"} and path.is_file():
                for i, line in enumerate(path.read_text().splitlines(), 1):
                    if re.search(r"#[0-9a-fA-F]{6}\b", line):
                        offenders.append(f"{path.name}:{i}")
        self.assertEqual(offenders, [], f"hard-coded colour outside theme.css: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class CacheRobustness(unittest.TestCase):
    """The demo runs from this cache, so it must never be the thing that breaks it."""

    def setUp(self):
        from ews.llm import _Cache, CACHE_DIR
        self.cache, self.dir = _Cache(True), CACHE_DIR
        self.key = "test_cache_robustness"

    def tearDown(self):
        (self.dir / f"{self.key}.json").unlink(missing_ok=True)

    def test_round_trip(self):
        self.cache.put(self.key, {"a": 1})
        self.assertEqual(self.cache.get(self.key), {"a": 1})

    def test_a_truncated_entry_is_a_miss_not_a_crash(self):
        self.cache.put(self.key, {"a": 1})
        (self.dir / f"{self.key}.json").write_text('{"truncated": ')
        self.assertIsNone(self.cache.get(self.key))

    def test_a_corrupt_entry_is_removed_so_it_cannot_recur(self):
        (self.dir / f"{self.key}.json").write_text("not json at all")
        self.cache.get(self.key)
        self.assertFalse((self.dir / f"{self.key}.json").exists())

    def test_writes_leave_no_temp_files_behind(self):
        self.cache.put(self.key, {"a": 1})
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


class AgentDefinitions(unittest.TestCase):
    def test_every_shipped_definition_loads(self):
        from ews.agents import definition
        for name in ("payment", "news", "adjudicator", "casefile"):
            spec = definition.load(name)
            self.assertTrue(spec.system.strip(), f"{name} has no instructions")

    def test_an_agent_with_no_instructions_is_refused(self):
        """It would not fail - it would burn max_turns per item, then fall back."""
        import shutil, tempfile
        from pathlib import Path as P
        from ews.agents import definition
        from ews.agents.definition import DefinitionError
        original = definition.AGENTS_DIR
        tmp = P(tempfile.mkdtemp()) / "agents"
        shutil.copytree(original, tmp)
        try:
            definition.AGENTS_DIR = tmp
            head = (tmp / "news.md").read_text().split("---\n")[1]
            (tmp / "news.md").write_text(f"---\n{head}---\n   \n")
            with self.assertRaises(DefinitionError):
                definition.load("news")
        finally:
            definition.AGENTS_DIR = original


class Escaping(unittest.TestCase):
    def test_breadcrumb_links_escape_their_href(self):
        from dashboard.server import crumbs
        out = crumbs(("Home", '/client/x"><script>alert(1)</script>'), ("Here", None))
        self.assertNotIn("<script>", out)


class Routing(unittest.TestCase):
    """The dashboard's inputs come from a URL bar, so they are untrusted."""

    def _serve(self):
        import threading
        from http.server import HTTPServer
        from dashboard import server
        httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"

    def _get(self, base, path):
        import urllib.error, urllib.request
        try:
            r = urllib.request.urlopen(base + path, timeout=30)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_unknown_entities_and_paths_are_404_not_200(self):
        httpd, base = self._serve()
        try:
            for path in ("/buyer/NOPE", "/client/NOPE", "/nothing-here"):
                self.assertEqual(self._get(base, path)[0], 404, path)
            self.assertEqual(self._get(base, "/")[0], 200)
        finally:
            httpd.shutdown()

    def test_an_unknown_tab_falls_back_instead_of_rendering_the_last_branch(self):
        httpd, base = self._serve()
        try:
            _, body = self._get(base, "/buyer/BUY002?tab=garbage")
            self.assertIn('class="on" href="/buyer/BUY002?tab=case"', body)
        finally:
            httpd.shutdown()

    def test_the_demo_length_is_not_hardcoded(self):
        from dashboard.server import DEMO_STEPS
        self.assertEqual(len(DEMO_STEPS), len(Loader().demo_articles()),
                         "server.py's demo script and the demo CSV have drifted apart")

    def test_the_demo_cannot_be_advanced_past_its_last_step(self):
        httpd, base = self._serve()
        from dashboard.server import DEMO_STEPS, STATE
        try:
            self._get(base, "/demo/reset")
            for _ in range(len(DEMO_STEPS) + 5):
                self._get(base, "/demo/next")
            self.assertEqual(STATE["step"], len(DEMO_STEPS))
            self.assertTrue(STATE["swap"])
        finally:
            self._get(base, "/demo/reset")
            httpd.shutdown()


class Overrides(unittest.TestCase):
    """`--agents news` once applied to ews.run and silently not to the harness, which
    then ran every agent - including the Opus ones - on the default settings."""

    def setUp(self):
        from ews import settings
        self.s = settings
        self.enabled = {n: s["enabled"] for n, s in settings.AGENTS.items()}
        self.budget = settings.MAX_MODEL_CALLS

    def tearDown(self):
        for n, on in self.enabled.items():
            self.s.AGENTS[n]["enabled"] = on
        self.s.MAX_MODEL_CALLS = self.budget

    def test_narrowing_to_one_agent_disables_the_others(self):
        self.s.apply_overrides("news")
        self.assertEqual(self.s.enabled_agents(), ["news"])

    def test_the_budget_can_be_capped(self):
        self.s.apply_overrides(None, 42)
        self.assertEqual(self.s.MAX_MODEL_CALLS, 42)

    def test_an_unknown_agent_is_refused(self):
        with self.assertRaises(self.s.SettingsError):
            self.s.apply_overrides("nope")

    def test_a_bad_budget_is_refused(self):
        with self.assertRaises(self.s.SettingsError):
            self.s.apply_overrides(None, 0)

    def test_env_vars_work_too(self):
        import os
        os.environ["EWS_AGENTS"] = "payment,casefile"
        try:
            self.s.apply_overrides()
            self.assertEqual(self.s.enabled_agents(), ["casefile", "payment"])
        finally:
            del os.environ["EWS_AGENTS"]

    def test_both_entry_points_go_through_the_shared_override(self):
        """Neither CLI may roll its own - that is how they drifted apart."""
        for module in ("ews/run.py", "harness/evaluate.py"):
            src = (ROOT / module).read_text()
            self.assertIn("apply_overrides", src, f"{module} must use the shared override")
            self.assertNotIn('spec["enabled"] = name in wanted', src,
                             f"{module} re-implements agent selection")


class Secrets(unittest.TestCase):
    """A committed API key is unrecoverable — it has to be rotated, not deleted."""

    KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")

    def _tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
        return [ROOT / f for f in out]

    def test_no_api_key_in_any_tracked_file(self):
        offenders = []
        for path in self._tracked():
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            if self.KEY_RE.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"an API key is committed in: {offenders}")

    def test_the_key_file_is_not_inside_the_repo(self):
        for name in (".anthropic-key", ".env", "anthropic.key"):
            self.assertFalse((ROOT / name).exists(), f"{name} must live outside the repo")

    def test_outputs_and_the_venv_are_ignored(self):
        """out/ holds the LLM cache and run JSON; .venv holds the SDK."""
        tracked = {str(p.relative_to(ROOT)) for p in self._tracked()}
        for prefix in ("out/", ".venv/"):
            leaked = [t for t in tracked if t.startswith(prefix)
                      and not t.startswith("out/.llm_cache/")]   # shipped deliberately
            self.assertEqual(leaked, [], f"{prefix} must not be tracked: {leaked}")

    def test_the_shipped_cache_holds_no_secret(self):
        """It ships so a clone runs for free; it must not carry a key with it."""
        import re as _re
        for path in (ROOT / "out" / ".llm_cache").glob("*.json"):
            self.assertIsNone(_re.search(r"sk-ant-[A-Za-z0-9_\-]{20,}", path.read_text()),
                              f"{path.name} contains something key-shaped")


class RunOutputNames(unittest.TestCase):
    """A narrowed run and a full run are different results, not versions of one."""

    def test_the_filename_records_what_produced_the_run(self):
        import subprocess as sp
        out = sp.run(["grep", "-n", "parts.append(result\\[\"llm\"\\])", "ews/run.py"],
                     cwd=ROOT, capture_output=True, text=True)
        self.assertTrue(out.stdout, "the engine name must be part of the output filename")

    def test_a_restricted_claude_run_is_named_apart(self):
        from ews import settings
        before = {n: s["enabled"] for n, s in settings.AGENTS.items()}
        try:
            settings.apply_overrides("news")
            self.assertNotEqual(set(settings.enabled_agents()), set(settings.AGENTS),
                                "a narrowed run must be distinguishable from a full one")
        finally:
            for n, on in before.items():
                settings.AGENTS[n]["enabled"] = on
