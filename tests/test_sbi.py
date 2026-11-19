"""The SBI book: real companies, fetched news, an illustrative ledger. All offline."""
import csv
import unittest

from ews.fetch_news import FIELDS, ITEMS_8K, mention_in
from ews.llm import FallbackLLM, keyword_grade, strict_resolve
from ews.loader import ROOT_DATA, Loader

SBI = ROOT_DATA / "sbi"


class Book(unittest.TestCase):
    def test_the_book_is_consistent(self):
        Loader(SBI).validate()

    def test_one_insurer_covers_every_buyer(self):
        lo = Loader(SBI)
        self.assertEqual([c["client_name"] for c in lo.clients()], ["SBI Trade Credit"])
        self.assertEqual({l["buyer_id"] for l in lo.credit_limits()},
                         {b["buyer_id"] for b in lo.buyers()})

    def test_nothing_in_the_ledger_is_seriously_late(self):
        """Illustrative payments must never invent distress at a real company."""
        worst = max(int(i["days_past_due"] or 0) for i in Loader(SBI).invoices())
        self.assertLess(worst, 30)

    def test_every_buyer_is_on_the_news_watchlist(self):
        with (SBI / "news_watchlist.csv").open() as fh:
            watch = {r["buyer_id"]: r for r in csv.DictReader(fh)}
        for b in Loader(SBI).buyers():
            self.assertIn(b["buyer_id"], watch)
            self.assertTrue(watch[b["buyer_id"]]["cik"].isdigit())

    def test_fetched_news_has_the_columns_the_engine_reads(self):
        with (SBI / "news_articles.csv").open() as fh:
            self.assertEqual(tuple(csv.DictReader(fh).fieldnames), FIELDS)


class Resolution(unittest.TestCase):
    def setUp(self):
        self.cands = [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"]}
                      for b in Loader(SBI).buyers()]

    def test_us_legal_names_resolve_from_the_brand(self):
        for mention, want in [("Nvidia", "US001"), ("The Boeing Company", "US007"),
                              ("Ford Motor", "US008"), ("NIKE", "US009")]:
            self.assertEqual(strict_resolve(mention, self.cands)["id"], want, mention)

    def test_a_different_business_on_the_same_brand_is_refused(self):
        self.assertIsNone(strict_resolve("Ford Foundation", self.cands))

    def test_the_mention_is_only_what_the_headline_says(self):
        self.assertEqual(mention_in("Why Intel stock just dropped", ["Intel"]), "Intel")
        self.assertEqual(mention_in("Artificial intelligence spending booms", ["Intel"]), "")
        self.assertEqual(mention_in("Ford Motor reports results", ["Ford Motor", "Ford"]),
                         "Ford Motor")


class Grading(unittest.TestCase):
    def grade(self, text):
        return keyword_grade({"headline": text, "body": ""})

    def test_8k_items_that_mean_distress_grade_as_distress(self):
        self.assertEqual(self.grade(ITEMS_8K["1.03"])["severity"], 5)
        self.assertEqual(self.grade(ITEMS_8K["2.04"])["severity"], 5)
        self.assertEqual(self.grade(ITEMS_8K["4.02"])["severity"], 4)
        self.assertEqual(self.grade(ITEMS_8K["2.05"])["severity"], 2)
        self.assertEqual(self.grade(ITEMS_8K["2.06"])["severity"], 3)

    def test_routine_8k_items_grade_neutral(self):
        for item in ("2.02", "5.07", "7.01", "8.01", "1.01", "2.03"):
            self.assertEqual(self.grade(ITEMS_8K[item])["severity"], 0, item)

    def test_press_language(self):
        self.assertEqual(self.grade("Acme files for Chapter 11 protection")["severity"], 5)
        self.assertEqual(self.grade("Moody's cuts Acme credit rating to junk")["severity"], 4)
        self.assertEqual(self.grade("Boeing to cut 5% of commercial airplane workers")["severity"], 4)
        self.assertEqual(self.grade("Acme announces mass layoffs")["severity"], 4)
        self.assertEqual(self.grade("Nvidia says Jensen Huang won't return as CEO")["severity"], 4)
        self.assertEqual(self.grade("Microsoft offers buyouts to 60,000 employees")["severity"], 2)
        self.assertEqual(self.grade("Analyst downgrades Acme stock to hold")["severity"], 1)
        self.assertEqual(self.grade("Acme names new head of marketing")["severity"], 0)

    def test_fallback_refuses_a_story_that_names_no_covered_company(self):
        art = {"article_id": "X", "headline": "Outages hit banks", "body": "Outages hit banks",
               "mentioned_entity_as_written": ""}
        self.assertEqual(FallbackLLM(cache=False).resolve(art, self.cands())["kind"], "none")

    def cands(self):
        return [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"]}
                for b in Loader(SBI).buyers()]


if __name__ == "__main__":
    unittest.main(verbosity=2)
