"""Mechanical gates: leakage, determinism, the formulae, the case-file guard, theme."""
import json
import re
import subprocess
import unittest
from pathlib import Path

from ews import config, run as engine
from ews.casefile import verify
from ews.llm import FallbackLLM, keyword_grade, strict_resolve
from ews.loader import NEWS_LABEL_COLUMNS, Loader, LeakageError

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


class Resolution(unittest.TestCase):
    CANDS = [{"kind": "buyer", "id": "B1", "name": "Arcline Fabricators Limited"},
             {"kind": "buyer", "id": "B2", "name": "Chandra Mills Pvt Ltd"},
             {"kind": "buyer", "id": "B3", "name": "Mahanadi Industries Limited"},
             {"kind": "buyer", "id": "B4", "name": "Udaan Traders Pvt Ltd"},
             {"kind": "parent", "id": "P3", "name": "Northpoint Industrial Holdings Pvt Ltd"}]

    def test_accepts_genuine_variants(self):
        for mention in ("Arcline", "Arcline Inds.", "ARCLINE FABRICATORS LIMITED"):
            self.assertEqual(strict_resolve(mention, self.CANDS)["id"], "B1", mention)

    def test_refuses_decoys(self):
        for mention in ("Arcline Media Pvt Ltd", "Chandra Hospitals Pvt Ltd",
                        "Udaan Logistics Pvt Ltd"):
            self.assertIsNone(strict_resolve(mention, self.CANDS), mention)

    def test_resolves_parent(self):
        got = strict_resolve("Northpoint Industrial Holdings Pvt Ltd", self.CANDS)
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
