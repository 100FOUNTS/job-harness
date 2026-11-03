"""Track rank_adjust and ranking.deprioritize move the total (0-100) and say so in the reasons."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from prepare import LABELS, score  # noqa: E402

BASE = {"tracks": [{"id": "data", "keywords": {"core": ["python", "gis"], "support": ["sql"]}}],
        "ranking": {"preferred_locations": ["Perth"]}}
JOBS = [
    {"track": "data", "title": "Data Analyst", "location": "Perth WA", "listed": "",
     "description": "Python and SQL reporting."},
    {"track": "data", "title": "GIS Analyst", "location": "Sydney NSW", "listed": "",
     "description": "GIS mapping with python. Minimum 3 years experience."},
    {"track": "data", "title": "Senior Engineer", "location": "Perth", "listed": "", "description": "Nothing relevant."},
]


def with_targets(adjust=None, deprio=None):
    t = copy.deepcopy(BASE)
    if adjust is not None:
        t["tracks"][0]["rank_adjust"] = adjust
    if deprio is not None:
        t["ranking"]["deprioritize"] = deprio
    return t


class TestRankAdjust(unittest.TestCase):
    def test_absent_fields_change_nothing(self):
        for j in JOBS:
            plain = score(j, BASE)
            self.assertEqual(plain, score(j, with_targets(adjust=0)))
            self.assertEqual(plain, score(j, with_targets(deprio={"terms": []})))
            self.assertFalse([w for w in plain[2]["why"] if w.startswith(("track_adjust", "deprioritized"))])

    def test_negative_and_positive_adjust(self):
        j = JOBS[0]
        base = score(j, BASE)[0]
        down, up = score(j, with_targets(adjust=-10)), score(j, with_targets(adjust=5))
        self.assertEqual((down[0], up[0]), (base - 10, base + 5))
        self.assertIn("track_adjust:-10", down[2]["why"])
        self.assertIn("track_adjust:5", up[2]["why"])
        self.assertEqual(down[2]["prob"], score(j, BASE)[2]["prob"])   # odds label untouched

    def test_clamped_to_0_100(self):
        self.assertEqual(score(JOBS[2], with_targets(adjust=-90))[0], 0)
        self.assertEqual(score(JOBS[0], with_targets(adjust=90))[0], 100)

    def test_deprioritize_title_only_and_once(self):
        d = {"terms": ["gis", "mapping"], "points": 6}
        gis = JOBS[1]
        self.assertEqual(score(gis, with_targets(deprio=d))[0], score(gis, BASE)[0] - 6)   # two terms, one deduction
        self.assertIn("deprioritized", score(gis, with_targets(deprio=d))[2]["why"])
        body_only = JOBS[0] | {"description": "GIS mapping everywhere."}                  # term in the ad, not the title
        self.assertEqual(score(body_only, with_targets(deprio=d)), score(body_only, BASE))
        word = JOBS[0] | {"title": "Gisborne Data Analyst"}                                 # word boundary
        self.assertEqual(score(word, with_targets(deprio=d)), score(word, BASE))
        self.assertEqual(score(gis, with_targets(deprio={"terms": ["GIS"]}))[0], score(gis, BASE)[0] - 8)   # default 8, case-insensitive

    def test_labels_exist_in_every_language(self):
        for L in LABELS.values():
            for k in ("track_down", "track_up", "deprioritized"):
                self.assertIn(k, L)

    def test_notes_show_reason(self):
        from prepare import notes_for
        j = JOBS[1] | {"platform": "seek"}
        odds = score(j, with_targets(adjust=-10, deprio={"terms": ["gis"]}))[2]
        w = notes_for(j, [], odds)["watch"]
        self.assertIn("lower priority track (-10)", w)
        self.assertIn("lower-priority list", w)


if __name__ == "__main__":
    unittest.main()
