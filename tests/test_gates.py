"""Mechanical gates: leakage, determinism, the formulae, the case-file guard, theme."""
# Tests never reach the network. The documented way to run this project exports
# ANTHROPIC_API_KEY, and several tests drive the full engine through get_llm(), which
# picks Claude whenever credentials are in the environment - so without this the suite
# bills real money and takes minutes. It sits in each module rather than in
# tests/__init__.py because `unittest discover -s tests` imports these as top-level
# modules and never runs the package __init__. Tests that want a model pass a stub.
import os

os.environ["EWS_LLM"] = "fallback"

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

    def test_the_demo_swap_file_changes_only_the_one_invoice(self):
        """demo/invoices_after_payment_demo.csv is a drop-in replacement for
        invoices.csv, so it must hold every row of it and differ in exactly one.

        It drifted once: six buyers added to invoices.csv were never added here, so
        demo step 8 silently dropped their invoices and sent four scores to 0.0. Every
        one of them was Healthy either way, so no other gate noticed.
        """
        base = {r["invoice_id"]: r for r in self._rows(ROOT / "data" / "invoices.csv")}
        swap = {r["invoice_id"]: r
                for r in self._rows(ROOT / "data" / "demo" / "invoices_after_payment_demo.csv")}
        self.assertEqual(set(base), set(swap), "the swap file is not the same invoice set")
        differ = sorted(k for k in swap if base[k] != swap[k])
        self.assertEqual(differ, ["INV001567"], "step 8 must move one invoice and no other")
        self.assertEqual((base["INV001567"]["days_past_due"],
                          swap["INV001567"]["days_past_due"]), ("25", "40"))

    def test_step_8_moves_one_buyer_and_no_other(self):
        """The same guarantee at the level the room actually sees: a score on screen."""
        before = {r["buyer_id"]: r["verdict"]["score"]
                  for r in engine.run(demo_steps=7, llm=FallbackLLM(cache=False))["buyers"]}
        after = {r["buyer_id"]: r["verdict"]["score"]
                 for r in engine.run(demo_steps=7, swap_invoices=True,
                                     llm=FallbackLLM(cache=False))["buyers"]}
        moved = sorted(b for b in before if before[b] != after[b])
        self.assertEqual(moved, ["BUY023"], "only Kessler may move when payment data updates")


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


class ScoringConstants(unittest.TestCase):
    """config.py IS the scoring model. A wrong constant does not crash — it quietly
    changes every score, so each is checked when the module loads."""

    def setUp(self):
        self.saved = {k: getattr(config, k) for k in
                      ("NEWS_HALF_LIFE_DAYS", "NEWS_MAX_AGE_DAYS", "NEWS_FADE_DAYS",
                       "DPD_KNEE", "W_NEWS", "W_PAYMENT", "BAND_WATCH", "BAND_HIGH",
                       "PD_ANCHORS", "PARENT_STEP_DOWN")}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(config, k, v)

    def test_the_shipped_constants_are_consistent(self):
        config._validate()

    def test_each_way_of_breaking_them_is_caught(self):
        for attr, bad, why in [
            ("NEWS_FADE_DAYS", 800, "a fade longer than the horizon discounts fresh news"),
            ("NEWS_HALF_LIFE_DAYS", 0, "divides by zero"),
            ("NEWS_MAX_AGE_DAYS", -10, "scores all news zero"),
            ("DPD_KNEE", 0, "divides by zero"),
            ("W_NEWS", 0.5, "weights no longer sum to 1"),
            ("BAND_HIGH", 20.0, "High Risk below Watch"),
            ("PD_ANCHORS", [(50, 0.5), (10, 0.1)], "anchors out of order"),
            ("PARENT_STEP_DOWN", {5: 2}, "steps onto a severity with no base score"),
        ]:
            setattr(config, attr, bad)
            with self.assertRaises(ValueError, msg=f"{attr}={bad!r} ({why})"):
                config._validate()
            setattr(config, attr, self.saved[attr])

    def test_a_fresh_article_is_worth_full_weight(self):
        self.assertEqual(config.decay(0), 1.0)


class ShippedCacheIsUntrusted(unittest.TestCase):
    """The cache ships with the repo, so an entry can be hand-edited or mangled by a
    merge. A wrong shape must be a miss, not a crashed run."""

    def test_a_malformed_entry_is_ignored_and_the_agent_re_runs(self):
        from ews.agents import definition
        from ews.agents.definition import AgentSpec
        from ews.agents.runtime import Tool, run_agent
        from ews.llm import CACHE_DIR, _Cache, _key

        spec = AgentSpec(name="t", title="T", description="d", tools={"submit_v": "s"},
                         system="s", path=definition.AGENTS_DIR / "t.md", enabled=True,
                         model="m", effort="low", max_turns=3, max_tokens=500,
                         guardrails={"required_before_submit": []})
        key = _key("claude", "agent:t",
                   {"model": "m", "effort": "low", "max_tokens": 500,
                    "guardrails": spec.guardrails, "system": "s", "tools": spec.tools,
                    "task": "go", "data": {}})
        entry = CACHE_DIR / f"{key}.json"

        class Resp:
            def __init__(self, c): self.content, self.stop_reason = c, "tool_use"

        class Block:
            def __init__(self, n, i, c):
                self.type, self.name, self.input, self.id = "tool_use", n, i, c

        try:
            for content in ('"a string"', "[1, 2, 3]", '{"turns": 1}'):
                entry.write_text(content)
                seq = iter([Resp([Block("submit_v", {"v": "recovered"}, "1")])])

                class LLM:
                    name, agentic, api_errors = "claude", True, ()
                    def __init__(self):
                        self.cache, self.calls = _Cache(True), 0
                        self.degraded, self.disabled = 0, False
                    def create(self, **kw): return next(seq)

                out = run_agent(LLM(), spec=spec, task="go", cache_payload={},
                                tools=[Tool("submit_v", {"v": {"type": "string"}},
                                            lambda v: v)])
                self.assertEqual(out["result"], "recovered", content)
                self.assertFalse(out["cached"], content)
        finally:
            entry.unlink(missing_ok=True)


class LoaderWithoutDemoFiles(unittest.TestCase):
    """Range-checking demo_steps must not make demo/ a hard dependency of loading."""

    def _without_demo(self):
        import shutil, tempfile
        from pathlib import Path as P
        d = P(tempfile.mkdtemp()) / "data"
        shutil.copytree(ROOT / "data", d)
        shutil.rmtree(d / "demo")
        return d

    def test_a_dataset_with_no_demo_folder_still_loads(self):
        self.assertTrue(Loader(self._without_demo()).buyers())

    def test_asking_for_demo_steps_without_the_file_says_so(self):
        with self.assertRaises(ValueError) as ctx:
            Loader(self._without_demo(), demo_steps=3)
        self.assertIn("demo_articles_to_add.csv", str(ctx.exception))


class LiveInput(unittest.TestCase):
    """The sandbox takes input nobody prepared, so every way of getting it wrong
    has to leave the demo standing."""

    def setUp(self):
        import dashboard.server as S
        self.S = S
        S.LIVE.update(articles=[], dpd={}, last=None)
        S._LIVE_CACHE.clear()
        self.addCleanup(lambda: S.LIVE.update(articles=[], dpd={}, last=None))

    def _story(self, **kw):
        base = {"mention": "Oakhurst Components Ltd", "headline": "Wage protest",
                "body": "Staff protested over delayed wages.", "date": "2026-09-20"}
        self.S.add_story({k: [v] for k, v in {**base, **kw}.items()})
        return self.S.LIVE["last"]

    def test_a_genuine_story_moves_the_named_buyer(self):
        moves = self._story()["moves"]
        self.assertEqual([m["buyer_id"] for m in moves], ["BUY019"])
        self.assertTrue(moves[0]["crossed"])

    def test_a_near_miss_name_moves_nothing(self):
        self.assertEqual(self._story(mention="Oakhurst Realty LLP")["moves"], [])

    def test_a_story_the_run_could_not_have_seen_is_refused(self):
        last = self._story(date="2026-12-01")
        self.assertIn("snapshot", last["error"])
        self.assertEqual(self.S.LIVE["articles"], [], "a refused story must not be kept")

    def test_a_rejected_input_leaves_the_previous_state_intact(self):
        self._story()
        self._story(headline="")                      # rejected
        self.assertEqual(len(self.S.LIVE["articles"]), 1)

    def test_the_ledger_lever_crosses_a_band(self):
        self.S.set_dpd({"buyer_id": ["BUY019"], "dpd": ["45"]})
        m = self.S.LIVE["last"]["moves"]
        self.assertEqual((m[0]["buyer_id"], m[0]["to_band"]), ("BUY019", "Watch"))

    def test_the_two_signals_together_reach_a_band_neither_reaches_alone(self):
        """The fusion argument, as a number: at 45 days past due this buyer is Watch on
        payment alone and High Risk once the wage story lands. Payment alone would not
        get there until 57 days - the news is worth twelve days of lead time."""
        self.S.set_dpd({"buyer_id": ["BUY019"], "dpd": ["45"]})
        self.assertEqual(self.S.LIVE["last"]["moves"][0]["to_band"], "Watch")
        self._story()
        self.assertEqual(self.S.LIVE["last"]["moves"][0]["to_band"], "High Risk")

        self.S.LIVE.update(articles=[], dpd={}, last=None)
        self.S.set_dpd({"buyer_id": ["BUY019"], "dpd": ["57"]})
        self.assertEqual(self.S.LIVE["last"]["moves"][0]["to_band"], "High Risk")

    def test_a_bad_dpd_is_refused_not_applied(self):
        self.S.set_dpd({"buyer_id": ["BUY019"], "dpd": ["nope"]})
        self.assertTrue(self.S.LIVE["last"]["error"])
        self.assertEqual(self.S.LIVE["dpd"], {})

    def test_an_out_of_range_dpd_is_refused(self):
        self.S.set_dpd({"buyer_id": ["BUY019"], "dpd": ["9999"]})
        self.assertTrue(self.S.LIVE["last"]["error"])
        self.assertEqual(self.S.LIVE["dpd"], {})

    def test_an_override_does_not_leak_into_the_next_loader(self):
        """table() hands back a cached list; an override must copy before writing."""
        def worst(loader):
            return max(int(i["days_past_due"] or 0) for i in loader.invoices()
                       if i["buyer_id"] == "BUY019" and i["status"] == "Open")
        self.assertEqual(worst(Loader(dpd_overrides={"BUY019": 99})), 99)
        self.assertEqual(worst(Loader()), 25)

    def test_live_input_never_reaches_the_shipped_dataset(self):
        self._story()
        self.assertEqual(len(Loader().news()), 31)

    def test_typed_html_is_escaped_on_the_page(self):
        self._story(mention="<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", self.S.live_page().decode())

    def test_a_buyer_opened_from_the_sandbox_shows_the_sandbox_score(self):
        """Clicking through must not contradict, on the next screen, the number the
        room just watched move."""
        self._story()
        live = self.S.buyer_page("BUY019", "score", live=True).decode()
        scripted = self.S.buyer_page("BUY019", "score", live=False).decode()
        self.assertIn("47.7", live)
        self.assertIn("Live sandbox view", live)
        self.assertNotIn("Live sandbox view", scripted)
        self.assertIn("21.7", scripted)

    def test_skipping_commentary_does_not_move_a_single_score(self):
        from ews.llm import FallbackLLM
        full = {r["buyer_id"]: r["verdict"]["score"]
                for r in engine.run(llm=FallbackLLM(cache=False))["buyers"]}
        quick = {r["buyer_id"]: r["verdict"]["score"]
                 for r in engine.run(llm=FallbackLLM(cache=False), commentary=False)["buyers"]}
        self.assertEqual(full, quick)


class TestsStayOffline(unittest.TestCase):
    """The documented way to run this project exports ANTHROPIC_API_KEY, and several
    tests drive the full engine. Without the guard in tests/__init__.py the suite bills
    real money on the machine of anyone following the README."""

    def test_the_suite_cannot_reach_claude(self):
        from ews.llm import ClaudeLLM, get_llm
        self.assertNotIsInstance(get_llm(cache=False), ClaudeLLM)

    def test_no_test_resolves_its_own_model_from_the_environment(self):
        import os
        self.assertEqual(os.environ.get("EWS_LLM"), "fallback")
