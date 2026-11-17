"""targets.priority (ordered track ids) replaces rank_adjust; ranking.level_adjust overrides the title-level points."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from prepare import score, track_adjust  # noqa: E402

IDS = ["ai", "data", "software", "analyst", "geo"]


def targets(ids=IDS, **extra):
    t = {"tracks": [{"id": i, "keywords": {"core": ["python"], "support": []}} for i in ids], "ranking": {}}
    t.update(extra)
    return t


def job(track="data", title="Data Analyst"):
    return {"track": track, "title": title, "location": "", "listed": "", "description": "Python."}


class TestPriority(unittest.TestCase):
    def test_five_tracks(self):
        t = targets(priority=IDS)
        self.assertEqual([track_adjust(t, i) for i in IDS], [10, 5, 0, -5, -10])

    def test_four_tracks_round_half_to_even(self):
        t = targets(IDS[:4], priority=IDS[:4])
        self.assertEqual([track_adjust(t, i) for i in IDS[:4]], [8, 2, -2, -8])

    def test_step(self):
        t = targets(priority=IDS, priority_step=2)
        self.assertEqual([track_adjust(t, i) for i in IDS], [4, 2, 0, -2, -4])
        for bad in ("x", None, 2.5, True):
            self.assertEqual(track_adjust(targets(priority=IDS, priority_step=bad), "ai"), 10)

    def test_missing_and_unknown_ids(self):
        t = targets(priority=["geo", "nope", "ai"])           # unknown ignored: 2 listed -> +2.5 / -2.5 (half to even)
        self.assertEqual((track_adjust(t, "geo"), track_adjust(t, "ai")), (2, -2))
        self.assertEqual(track_adjust(t, "data"), -2)          # not listed: lowest value
        self.assertEqual(track_adjust(t, "nope"), -2)
        self.assertEqual(track_adjust(targets(priority=["ai", "ai", "data"]), "data"), -2)   # repeats count once: 2 listed

    def test_overrides_rank_adjust(self):
        t = targets(priority=IDS)
        t["tracks"][0]["rank_adjust"] = -40
        self.assertEqual(track_adjust(t, "ai"), 10)

    def test_no_priority_unchanged(self):
        t = targets()
        t["tracks"][1]["rank_adjust"] = -7
        self.assertEqual([track_adjust(t, i) for i in IDS], [0, -7, 0, 0, 0])
        for p in ([], "ai", None, ["nope"]):
            t2 = copy.deepcopy(t)
            t2["priority"] = p
            self.assertEqual(track_adjust(t2, "data"), -7)
        self.assertEqual(score(job(), t), score(job(), dict(t, priority=[])))

    def test_score_uses_priority_and_reason(self):
        base = score(job(), targets())
        s = score(job(), targets(priority=IDS))               # data is 2nd of 5: +5
        self.assertEqual(s[0], base[0] + 5)
        self.assertIn("track_adjust:5", s[2]["why"])
        s = score(job("geo"), targets(priority=IDS))
        self.assertEqual(s[0], score(job("geo"), targets())[0] - 10)
        self.assertIn("track_adjust:-10", s[2]["why"])
        self.assertFalse([w for w in score(job("software"), targets(priority=IDS))[2]["why"] if w.startswith("track_adjust")])


class TestLevelAdjust(unittest.TestCase):
    def sc(self, title, la=None):
        t = targets()
        if la is not None:
            t["ranking"]["level_adjust"] = la
        return score(job(title=title), t)

    def test_unchanged_without_it(self):
        for title in ("Senior Data Analyst", "Graduate Analyst", "Lead Analyst", "Analyst"):
            self.assertEqual(self.sc(title), self.sc(title, {}))

    def test_override_points(self):
        base = self.sc("Senior Data Analyst")[0]
        self.assertEqual(self.sc("Senior Data Analyst", {"senior": -5})[0], base + 10)   # -15 -> -5
        self.assertEqual(self.sc("Lead Analyst", {"lead": -35})[0], self.sc("Lead Analyst")[0] - 10)
        self.assertEqual(self.sc("Graduate Analyst", {"entry": 10})[0], self.sc("Graduate Analyst")[0] - 8)
        self.assertIn("senior", self.sc("Senior Data Analyst", {"senior": -5})[2]["why"])

    def test_zero_disables_label(self):
        r = self.sc("Senior Data Analyst", {"senior": 0})
        self.assertNotIn("senior", r[2]["why"])
        self.assertEqual(r[0], self.sc("Senior Data Analyst")[0] + 15)

    def test_unknown_and_bad_ignored(self):
        plain = self.sc("Senior Data Analyst")
        for la in ({"wizard": 50}, {"senior": "-5"}, {"senior": None}, {"senior": 2.5}, {"senior": True}, {"senior": False}, "x", [1]):
            self.assertEqual(self.sc("Senior Data Analyst", la), plain, la)


if __name__ == "__main__":
    unittest.main()
