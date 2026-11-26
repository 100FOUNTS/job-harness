"""Visits: employers to walk into, per city, with a map place and a visit funnel. Nothing here touches the network:
geocoding is always mocked."""
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base, ROOT  # noqa: E402

TODAY = datetime.date.today()


def ago(days):
    return (TODAY - datetime.timedelta(days=days)).isoformat()


class VBase(Base):
    def setUp(self):
        super().setUp()
        import sponsors
        import visits
        self.v = visits
        self.patch = unittest.mock.patch.object(sponsors, "DATA", self.tmp / "no-sponsors.json")
        self.patch.start()
        sponsors._index.cache_clear()
        targets = json.loads((self.d / "targets.json").read_text(encoding="utf-8"))
        targets["tracks"] = [{"id": "ops"}, {"id": "env"}, {"id": "data"}]
        (self.d / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
        self.n = 0
        self.geo_dir = self.tmp / "geo-cache"                      # the Nominatim cache and rate-limit state: never ~/.cache
        os.environ["JOB_HARNESS_CACHE_DIR"] = str(self.geo_dir)

    def tearDown(self):
        import sponsors
        os.environ.pop("JOB_HARNESS_CACHE_DIR", None)
        self.patch.stop()
        sponsors._index.cache_clear()
        super().tearDown()

    def ad(self, company, location="Perth WA", verdict="shortlisted", fit=70, track="ops", seen=None, title="Analyst"):
        """One row in jobs.db, with the real schema."""
        from jobdb import connect
        self.n += 1
        key = f"k{self.n}"
        with connect("ana") as con:
            con.execute("INSERT INTO jobs (key, company, title, location, url, platform, verdict, fit, track, last_seen) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (key, company, title, location, f"https://x/{key}", "seek", verdict, fit, track, seen or ago(1)))
        return key

    def track(self, key, status="shortlisted", fit=None, track=None, history=()):
        """A tracker entry for an ad."""
        from tracker import load, save
        apps = load("ana")
        rec = {"key": key, "title": "t", "url": "u", "platform": "seek", "status": status, "date": ago(1),
               "history": [{"date": ago(1), "status": s} for s in history] or [{"date": ago(1), "status": status}]}
        if fit is not None:
            rec["fit"] = fit
        if track:
            rec["track"] = track
        apps.append(rec)
        save("ana", apps)


class TestCity(VBase):
    def test_known_cities_any_case_whole_word(self):
        v = self.v
        self.assertEqual(v.city_of("Perth WA"), "Perth")
        self.assertEqual(v.city_of("Osborne Park, PERTH Western Australia"), "Perth")
        self.assertEqual(v.city_of("greater adelaide area"), "Adelaide")
        self.assertEqual(v.city_of("Gold Coast QLD"), "Gold Coast")
        self.assertEqual(v.city_of("Port Hedland, WA"), "Port Hedland")
        self.assertEqual(v.city_of("Sydney or Melbourne"), "Sydney")      # the first one named

    def test_no_city(self):
        v = self.v
        for loc in ("", None, "Remote", "Western Australia", "Perthshire, Scotland", "Newcastleton"):
            self.assertEqual(v.city_of(loc), "", loc)

    def test_key_ignores_legal_suffix_and_case(self):
        v = self.v
        self.assertEqual(v.key_of("Acme Pty Ltd", "Perth"), v.key_of("ACME", "perth"))
        self.assertTrue(v.key_of("Acme Pty Ltd", "Perth").endswith("|perth"))


class TestCities(VBase):
    def test_cities_counts_only_qualifying_ads_by_ads_desc(self):
        self.ad("Acme Pty Ltd", "Perth WA")
        self.ad("Acme", "Perth WA")
        self.ad("Beta Mining", "Perth WA")
        self.ad("Gamma", "Adelaide SA")
        self.ad("Dropped Co", "Perth WA", verdict="dropped")            # did not qualify
        self.ad("Old Co", "Perth WA", seen=ago(90))                     # outside the window
        self.ad("Remote Co", "Remote")                                 # no city
        k = self.ad("Tracked Co", "Adelaide SA", verdict="dropped")     # in the tracker: qualifies
        self.track(k)
        self.assertEqual(self.v.cities("ana"), [{"city": "Perth", "companies": 2, "ads": 3},
                                                {"city": "Adelaide", "companies": 2, "ads": 2}])

    def test_no_database_means_no_cities(self):
        self.assertEqual(self.v.cities("ana"), [])
        self.assertEqual(self.v.places("ana", "Perth")["companies"], [])


class TestPlaces(VBase):
    def test_groups_by_employer_and_city_with_best_first(self):
        self.ad("Acme Pty Ltd", fit=60, title="Low")
        self.ad("ACME", fit=90, title="High")
        self.ad("Acme", "Adelaide SA", fit=80)
        r = self.v.places("ana", "perth")
        self.assertEqual(r["city"], "perth")
        self.assertEqual(len(r["companies"]), 1)
        c = r["companies"][0]
        self.assertEqual((c["ads"], c["best"], c["avg"]), (2, 90, 75))
        self.assertEqual([j["title"] for j in c["jobs"]], ["High", "Low"])
        self.assertEqual(c["key"], self.v.key_of("Acme", "Perth"))
        self.assertIsNone(c["place"])
        self.assertEqual(c["visit"], {"stage": "todo", "note": "", "contact": "", "updated": "", "history": []})
        self.assertFalse(c["agency"])
        self.assertEqual(set(c["jobs"][0]), {"title", "url", "fit", "track", "seen", "platform", "applied"})
        self.assertEqual(len(self.v.places("ana", "Adelaide")["companies"]), 1)

    def test_ranking_priority_then_best_then_ads(self):
        for _ in range(5):
            self.ad("Busy", fit=50)
        self.ad("Sharp", fit=95)
        self.ad("Middling", fit=50)
        names = [c["company"] for c in self.v.places("ana", "Perth")["companies"]]
        self.assertEqual(names, ["Sharp", "Busy", "Middling"])
        pr = [c["priority"] for c in self.v.places("ana", "Perth")["companies"]]
        self.assertEqual(pr, sorted(pr, reverse=True))

    def test_priority_matches_panel_formula(self):
        from panel import company_priority
        self.ad("Acme", fit=80)
        self.ad("Acme", fit=60)
        self.assertEqual(self.v.places("ana", "Perth")["companies"][0]["priority"], company_priority(2, 70, None, False))

    def test_agency_flag(self):
        self.ad("Hays Recruitment")
        self.ad("Acme")
        by = {c["company"]: c["agency"] for c in self.v.places("ana", "Perth")["companies"]}
        self.assertEqual(by, {"Hays Recruitment": True, "Acme": False})

    def test_tracks_present_follow_targets_order_and_unknown_last(self):
        self.ad("A", track="data")
        self.ad("B", track="ops")
        self.ad("C", track="zzz")
        self.ad("D", track="")
        self.ad("E", "Adelaide SA", track="env")             # other city: not listed
        self.assertEqual(self.v.places("ana", "Perth")["tracks"], ["ops", "data", "zzz"])

    def test_track_filter_recomputes_and_drops_empty_companies(self):
        self.ad("Acme", fit=90, track="ops")
        self.ad("Acme", fit=40, track="env")
        self.ad("Beta", fit=95, track="env")
        r = self.v.places("ana", "Perth", tracks=["ops"])
        self.assertEqual([c["company"] for c in r["companies"]], ["Acme"])
        c = r["companies"][0]
        self.assertEqual((c["ads"], c["best"], c["avg"]), (1, 90, 90))
        self.assertEqual(c["by_track"], {"ops": {"ads": 1, "best": 90}})
        self.assertEqual(r["tracks"], ["ops", "env"])        # the chips do not shrink with the filter
        both = self.v.places("ana", "Perth", tracks=["ops", "env"])
        acme = next(c for c in both["companies"] if c["company"] == "Acme")
        self.assertEqual(acme["by_track"], {"ops": {"ads": 1, "best": 90}, "env": {"ads": 1, "best": 40}})
        self.assertEqual(acme["avg"], 65)

    def test_tracker_overrides_track_and_fit_and_marks_applied(self):
        k1 = self.ad("Acme", fit=50, track="ops")
        self.track(k1, status="applied", fit=88, track="env", history=("shortlisted", "applied"))
        k2 = self.ad("Beta", fit=70)
        self.track(k2, status="shortlisted")
        k3 = self.ad("Gamma", fit=70)
        self.track(k3, status="rejected", history=("shortlisted", "interview", "rejected"))   # it got to an interview
        by = {c["company"]: c for c in self.v.places("ana", "Perth")["companies"]}
        j = by["Acme"]["jobs"][0]
        self.assertEqual((j["fit"], j["track"], j["applied"]), (88, "env", True))
        self.assertFalse(by["Beta"]["jobs"][0]["applied"])
        self.assertTrue(by["Gamma"]["jobs"][0]["applied"])

    def test_dropped_and_old_ads_do_not_count(self):
        self.ad("Acme", verdict="dropped")
        self.ad("Beta", seen=ago(61))
        self.assertEqual(self.v.places("ana", "Perth")["companies"], [])

    def test_funnel_reached_semantics_and_skip(self):
        for n in "ABCDEFG":
            self.ad(n)
        v = self.v
        v.set_stage("ana", "A", "Perth", "visited")
        v.set_stage("ana", "B", "Perth", "received")
        v.set_stage("ana", "C", "Perth", "not_received")
        v.set_stage("ana", "D", "Perth", "interview")
        v.set_stage("ana", "E", "Perth", "offer")
        v.set_stage("ana", "F", "Perth", "skip")
        v.set_stage("ana", "G", "Perth", "visited")
        v.set_stage("ana", "G", "Perth", "received")
        v.set_stage("ana", "G", "Perth", "todo")                   # stepped back: history still says it was reached
        r = v.places("ana", "Perth")
        self.assertEqual(r["funnel"], [["To visit", 6], ["Visited", 6], ["Received", 4], ["Interview", 2], ["Offer", 1]])
        stages = {c["company"]: c["visit"]["stage"] for c in r["companies"]}
        self.assertEqual(stages["F"], "skip")                      # skipped companies stay listed, but are not counted

    def test_missing_counts_companies_without_coordinates(self):
        self.ad("A")
        self.ad("B")
        self.ad("C")
        self.assertEqual(self.v.places("ana", "Perth")["missing"], 3)
        self.v.set_coords("ana", "A", "Perth", -31.95, 115.86)
        with unittest.mock.patch.object(self.v, "geocode", return_value=None):
            self.v.set_address("ana", "B", "Perth", "nowhere")      # address saved without coordinates: still missing
        r = self.v.places("ana", "Perth")
        self.assertEqual(r["missing"], 2)
        by = {c["company"]: c["place"] for c in r["companies"]}
        self.assertEqual(set(by["A"]), {"address", "lat", "lon", "confidence", "zone", "note", "source"})
        self.assertEqual(by["A"]["lat"], -31.95)

    def test_default_city_is_the_one_with_most_ads(self):
        self.ad("A", "Adelaide SA")
        self.ad("B", "Adelaide SA")
        self.ad("C", "Perth WA")
        self.assertEqual(self.v.places("ana", "")["city"], "Adelaide")


class TestVisitRecord(VBase):
    def test_set_stage_validates(self):
        r = self.v.set_stage("ana", "Acme", "Perth", "nope")
        self.assertFalse(r["ok"])
        self.assertIn("stage", r["error"])
        self.assertFalse(self.v.set_stage("ana", "", "Perth", "visited")["ok"])
        self.assertFalse(self.v.set_stage("ana", "Acme", "", "visited")["ok"])
        self.assertFalse((self.d / "visits.json").exists())

    def test_set_stage_keeps_history_and_file_shape(self):
        v = self.v
        r = v.set_stage("ana", "Acme Pty Ltd", "Perth", "visited", note="left it at reception")
        self.assertTrue(r["ok"])
        r = v.set_stage("ana", "acme", "PERTH", "received")
        self.assertEqual(r["visit"]["stage"], "received")
        self.assertEqual([(h["stage"], h["note"]) for h in r["visit"]["history"]],
                         [("visited", "left it at reception"), ("received", "")])
        self.assertTrue(r["visit"]["updated"])
        data = json.loads((self.d / "visits.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(list(data["companies"]), [v.key_of("Acme", "Perth")])
        rec = data["companies"][v.key_of("Acme", "Perth")]
        self.assertEqual((rec["company"], rec["city"]), ("Acme Pty Ltd", "Perth"))

    def test_same_stage_twice_is_not_duplicated_unless_it_has_a_note(self):
        v = self.v
        v.set_stage("ana", "Acme", "Perth", "visited")
        r = v.set_stage("ana", "Acme", "Perth", "visited")
        self.assertEqual(len(r["visit"]["history"]), 1)
        r = v.set_stage("ana", "Acme", "Perth", "visited", note="second visit")
        self.assertEqual(len(r["visit"]["history"]), 2)

    def test_same_employer_in_two_cities_is_two_records(self):
        self.v.set_stage("ana", "Acme", "Perth", "visited")
        self.v.set_stage("ana", "Acme", "Adelaide", "offer")
        data = json.loads((self.d / "visits.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["companies"]), 2)

    def test_set_details_none_leaves_and_caps(self):
        v = self.v
        r = v.set_details("ana", "Acme", "Perth", note="n1", contact="Sam, 0400 000 000")
        self.assertEqual((r["visit"]["note"], r["visit"]["contact"]), ("n1", "Sam, 0400 000 000"))
        r = v.set_details("ana", "Acme", "Perth", note="n2")
        self.assertEqual((r["visit"]["note"], r["visit"]["contact"]), ("n2", "Sam, 0400 000 000"))
        r = v.set_details("ana", "Acme", "Perth", contact="x" * 5000, note="y" * 5000)
        self.assertEqual((len(r["visit"]["note"]), len(r["visit"]["contact"])), (2000, 2000))
        r = v.set_details("ana", "Acme", "Perth", note="")           # empty string clears; None would not
        self.assertEqual(r["visit"]["note"], "")
        self.assertEqual(r["visit"]["stage"], "todo")
        self.assertEqual(r["visit"]["history"], [])                 # details are not a stage change

    def test_details_survive_stage_changes_and_show_in_places(self):
        self.ad("Acme")
        self.v.set_details("ana", "Acme", "Perth", note="ask for Sam")
        self.v.set_stage("ana", "Acme", "Perth", "visited")
        c = self.v.places("ana", "Perth")["companies"][0]
        self.assertEqual((c["visit"]["stage"], c["visit"]["note"]), ("visited", "ask for Sam"))

    def test_corrupt_file_is_set_aside_not_overwritten(self):
        (self.d / "visits.json").write_text("{not json", encoding="utf-8")
        r = self.v.set_stage("ana", "Acme", "Perth", "visited")
        self.assertTrue(r["ok"])
        bad = sorted(self.d.glob("visits.json.bad-*"))
        self.assertEqual([p.read_text(encoding="utf-8") for p in bad], ["{not json"])
        # a second corruption does not overwrite the first backup
        (self.d / "visits.json").write_text("[also not]", encoding="utf-8")
        self.assertTrue(self.v.set_stage("ana", "Beta", "Perth", "visited")["ok"])
        self.assertEqual(sorted(p.read_text(encoding="utf-8") for p in self.d.glob("visits.json.bad-*")),
                         ["[also not]", "{not json"])

    def test_unreadable_file_is_reported_not_renamed(self):
        p = self.d / "visits.json"
        p.write_text('{"version": 1, "companies": {}}', encoding="utf-8")
        with unittest.mock.patch.object(self.v.Path, "read_bytes", side_effect=PermissionError("denied")):
            with self.assertRaises(self.v.StoreError):
                self.v.set_stage("ana", "Acme", "Perth", "visited")
            self.ad("Acme")
            r = self.v.places("ana", "Perth")                      # the page still renders, saying why
            self.assertIn("denied", r["error"])
            self.assertEqual(len(r["companies"]), 1)
        self.assertEqual([x.name for x in self.d.glob("visits.json*")], ["visits.json"])
        self.assertEqual(p.read_text(encoding="utf-8"), '{"version": 1, "companies": {}}')

    def test_malformed_records_are_dropped_or_repaired_and_good_ones_kept(self):
        good = {"company": "Good", "city": "Perth", "stage": "visited", "note": "n", "contact": "", "updated": "u",
                "history": [{"date": "d", "stage": "visited", "note": ""}]}
        (self.d / "visits.json").write_text(json.dumps({"version": 1, "companies": {
            "A|perth": None, "B|perth": "text", "C|perth": [1], "GOOD|perth": good,
            "D|perth": {"company": "D", "stage": "bogus", "history": "not a list", "note": 5},
            "E|perth": {"company": "E", "stage": "visited", "history": [None, 3, {"stage": "bogus"}, {"stage": "visited"}]}}}),
            encoding="utf-8")
        (self.d / "places.json").write_text(json.dumps({"version": 1, "places": {
            "A|perth": None, "GOOD|perth": {"company": "Good", "lat": -31.9, "lon": 115.8, "confidence": "exact"},
            "F|perth": {"company": "F", "lat": "x", "lon": 5, "confidence": "??", "address": 7}}}), encoding="utf-8")
        for name in ("Good", "D", "E", "F"):
            self.ad(name)
        by = {c["company"]: c for c in self.v.places("ana", "Perth")["companies"]}
        self.assertEqual(by["Good"]["visit"]["history"], good["history"])
        self.assertEqual(by["Good"]["place"]["lat"], -31.9)
        self.assertEqual((by["D"]["visit"]["stage"], by["D"]["visit"]["history"], by["D"]["visit"]["note"]), ("todo", [], "5"))
        self.assertEqual([h["stage"] for h in by["E"]["visit"]["history"]], ["visited"])
        self.assertEqual((by["F"]["place"]["lat"], by["F"]["place"]["lon"], by["F"]["place"]["confidence"], by["F"]["place"]["address"]),
                         (None, None, "approx", "7"))
        self.assertEqual(sorted(json.loads((self.d / "visits.json").read_text(encoding="utf-8"))["companies"]),
                         ["D|perth", "E|perth", "GOOD|perth"])
        self.assertTrue(list(self.d.glob("visits.json.bad-*")))      # the original is kept
        self.assertTrue(self.v.set_stage("ana", "D", "Perth", "visited")["ok"])    # writes work on repaired records
        self.assertTrue(self.v.set_details("ana", "E", "Perth", note="x")["ok"])

    def test_valid_json_of_the_wrong_shape_is_set_aside(self):
        for body in ('[]', 'null', '{"companies": []}', '{"companies": null}', '"x"'):
            (self.d / "visits.json").write_text(body, encoding="utf-8")
            self.assertTrue(self.v.set_stage("ana", "Acme", "Perth", "visited")["ok"], body)
        self.assertEqual(len(list(self.d.glob("visits.json.bad-*"))), 5)

    def test_non_utf8_file_is_set_aside(self):
        (self.d / "places.json").write_bytes(b"\xff\xfe{")
        self.assertTrue(self.v.set_coords("ana", "Acme", "Perth", 1, 2)["ok"])
        self.assertEqual(len(list(self.d.glob("places.json.bad-*"))), 1)

    def test_atomic_write_leaves_no_temp_files_and_survives_a_failed_write(self):
        v = self.v
        v.set_stage("ana", "Acme", "Perth", "visited")
        self.assertEqual([p.name for p in self.d.glob("visits.json*")], ["visits.json"])
        before = (self.d / "visits.json").read_text(encoding="utf-8")
        with unittest.mock.patch.object(v.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                v.set_stage("ana", "Beta", "Perth", "visited")
        self.assertEqual((self.d / "visits.json").read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.d.glob("visits.json*")], ["visits.json"])      # temp file cleaned up

    def test_concurrent_writers_lose_nothing(self):
        v = self.v
        def go(i):
            v.set_stage("ana", f"Company {i}", "Perth", "visited")
        ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(json.loads((self.d / "visits.json").read_text(encoding="utf-8"))["companies"]), 12)

    def test_two_processes_writing_different_companies_lose_nothing(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import visits\n"
                "p = sys.argv[2]\n"
                "for i in range(10):\n"
                "    visits.set_stage('ana', f'Proc{p} Co{i}', 'Perth', 'visited')\n"
                "    visits.set_coords('ana', f'Proc{p} Co{i}', 'Perth', -31.9, 115.8)\n")
        env = {**os.environ, "JOB_CANDIDATES_DIR": str(self.tmp)}
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code, str(ROOT / "scripts"), str(n)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for n in range(4)]
        outs = [p.communicate(timeout=120)[0].decode() for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 4, outs)
        self.assertEqual(len(json.loads((self.d / "visits.json").read_text(encoding="utf-8"))["companies"]), 40)
        self.assertEqual(len(json.loads((self.d / "places.json").read_text(encoding="utf-8"))["places"]), 40)
        self.assertTrue((self.d / ".visits.lock").exists())


class TestPlacesWrite(VBase):
    def test_set_address_success(self):
        hit = {"lat": -31.95, "lon": 115.86, "display": "x"}
        with unittest.mock.patch.object(self.v, "geocode", return_value=hit) as g:
            r = self.v.set_address("ana", "Acme", "Perth", "1 St Georges Tce, Perth WA")
        g.assert_called_once_with("1 St Georges Tce, Perth WA, Australia")
        self.assertTrue(r["ok"])
        self.assertEqual((r["place"]["lat"], r["place"]["lon"], r["place"]["source"], r["place"]["confidence"]),
                         (-31.95, 115.86, "manual", "exact"))
        data = json.loads((self.d / "places.json").read_text(encoding="utf-8"))
        rec = data["places"][self.v.key_of("Acme", "Perth")]
        self.assertEqual((data["version"], rec["company"], rec["city"], rec["updated"]), (1, "Acme", "Perth", TODAY.isoformat()))

    def test_set_address_does_not_append_australia_twice(self):
        with unittest.mock.patch.object(self.v, "geocode", return_value={"lat": 1.0, "lon": 2.0, "display": ""}) as g:
            self.v.set_address("ana", "Acme", "Perth", "1 Tce, Perth WA, Australia")
        g.assert_called_once_with("1 Tce, Perth WA, Australia")

    def test_set_address_failure_keeps_the_address_without_coordinates(self):
        with unittest.mock.patch.object(self.v, "geocode", return_value=None):
            r = self.v.set_address("ana", "Acme", "Perth", "Somewhere odd")
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"])
        self.assertEqual((r["place"]["address"], r["place"]["lat"], r["place"]["lon"]), ("Somewhere odd", None, None))
        self.assertFalse(self.v.set_address("ana", "Acme", "Perth", "  ")["ok"])

    def test_set_address_failure_drops_stale_coordinates(self):
        self.v.set_coords("ana", "Acme", "Perth", -31.9, 115.8)
        with unittest.mock.patch.object(self.v, "geocode", return_value=None):
            r = self.v.set_address("ana", "Acme", "Perth", "New address")
        self.assertIsNone(r["place"]["lat"])

    def test_set_coords_validates_ranges(self):
        v = self.v
        self.assertTrue(v.set_coords("ana", "Acme", "Perth", "-31.95", "115.86", address="1 Tce")["ok"])
        for bad in ((91, 0), (-91, 0), (0, 181), (0, -181), ("a", 1), (None, 1), (float("nan"), 1)):
            r = v.set_coords("ana", "Acme", "Perth", *bad)
            self.assertFalse(r["ok"], bad)
            self.assertTrue(r["error"])
        p = v.places("ana", "Perth")      # nothing broke
        self.assertEqual(p["companies"], [])
        rec = json.loads((self.d / "places.json").read_text(encoding="utf-8"))["places"][v.key_of("Acme", "Perth")]
        self.assertEqual((rec["lat"], rec["lon"], rec["address"], rec["source"]), (-31.95, 115.86, "1 Tce", "manual"))

    def test_locate_finds_stores_and_reports_missing(self):
        self.ad("Acme", fit=90)
        self.ad("Beta", fit=80)
        self.ad("Gamma", fit=70)
        self.v.set_coords("ana", "Gamma", "Perth", -31.0, 115.0)        # already located: not looked up

        def fake(q):
            return {"lat": -31.9, "lon": 115.8, "display": q} if q.startswith("Acme") else None
        with unittest.mock.patch.object(self.v, "geocode", side_effect=fake) as g:
            r = self.v.locate("ana", "Perth")
        self.assertEqual(r, {"found": 1, "missing": ["Beta"]})
        self.assertEqual([c.args[0] for c in g.call_args_list], ["Perth, Australia", "Acme, Perth, Australia", "Beta, Perth, Australia"])
        by = {c["company"]: c["place"] for c in self.v.places("ana", "Perth")["companies"]}
        self.assertEqual((by["Acme"]["source"], by["Acme"]["confidence"], by["Acme"]["lat"]), ("nominatim", "approx", -31.9))
        self.assertIsNone(by["Beta"])
        self.assertEqual(by["Gamma"]["source"], "manual")                   # untouched
        self.assertEqual(self.v.places("ana", "Perth")["missing"], 1)

    def test_locate_respects_limit_and_geocodes_a_saved_address_first(self):
        self.ad("Acme", fit=90)
        self.ad("Beta", fit=80)
        with unittest.mock.patch.object(self.v, "geocode", return_value=None) as g:
            self.assertEqual(self.v.locate("ana", "Perth", limit=1), {"found": 0, "missing": ["Acme"]})
        self.assertEqual(g.call_count, 2)                                    # the city centre, then Acme
        with unittest.mock.patch.object(self.v, "geocode", return_value=None):
            self.v.set_address("ana", "Beta", "Perth", "9 Hay St")          # address without coordinates
        with unittest.mock.patch.object(self.v, "geocode", return_value={"lat": 1.0, "lon": 2.0, "display": ""}) as g:
            self.v.locate("ana", "Perth", limit=5)
        self.assertIn(unittest.mock.call("9 Hay St"), g.call_args_list)
        beta = next(c for c in self.v.places("ana", "Perth")["companies"] if c["company"] == "Beta")["place"]
        self.assertEqual((beta["address"], beta["lat"], beta["source"]), ("9 Hay St", 1.0, "manual"))

    def test_locate_rejects_a_match_far_from_the_city(self):
        self.ad("Acme", fit=90)
        self.ad("Beta", fit=80)
        perth, near, far = {"lat": -31.95, "lon": 115.86, "display": "Perth"}, {"lat": -31.90, "lon": 115.80, "display": "1 Tce, Perth"}, \
            {"lat": -34.93, "lon": 138.60, "display": "Adelaide"}

        def fake(q):
            return perth if q == "Perth, Australia" else near if q.startswith("Acme") else far
        with unittest.mock.patch.object(self.v, "geocode", side_effect=fake):
            self.assertEqual(self.v.locate("ana", "Perth"), {"found": 1, "missing": ["Beta"]})
        acme = next(c for c in self.v.places("ana", "Perth")["companies"] if c["company"] == "Acme")["place"]
        self.assertEqual(acme["address"], "1 Tce, Perth")                    # what the map matched, so the person can check it
        self.assertLess(self.v.km(-31.95, 115.86, -34.93, 138.60), 2200)
        self.assertGreater(self.v.km(-31.95, 115.86, -34.93, 138.60), 2000)

    def test_import_places(self):
        f = self.tmp / "offices.json"
        f.write_text(json.dumps([
            {"company": "Acme Pty Ltd", "address": "1 Tce", "lat": -31.9, "lon": 115.8, "zone": "CBD", "note": "n"},
            {"name": "Beta", "address": "2 Rd"},
            {"name": "Gamma", "lat": 500, "lon": 1, "confidence": "approx"},
            {"address": "no name"}, "junk"]), encoding="utf-8")
        self.assertEqual(self.v.import_places("ana", "Perth", f), {"imported": 3})
        pl = json.loads((self.d / "places.json").read_text(encoding="utf-8"))["places"]
        acme = pl[self.v.key_of("Acme", "Perth")]
        self.assertEqual((acme["lat"], acme["zone"], acme["source"], acme["confidence"]), (-31.9, "CBD", "import", "exact"))
        beta = pl[self.v.key_of("Beta", "Perth")]
        self.assertEqual((beta["address"], beta["lat"], beta["lon"], beta["confidence"]), ("2 Rd", None, None, "approx"))
        self.assertIsNone(pl[self.v.key_of("Gamma", "Perth")]["lat"])           # out of range: address only

    def test_import_places_bad_files_do_not_raise(self):
        self.assertEqual(self.v.import_places("ana", "Perth", self.tmp / "missing.json")["imported"], 0)
        bad = self.tmp / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        r = self.v.import_places("ana", "Perth", bad)
        self.assertEqual(r["imported"], 0)
        self.assertIn("error", r)
        bad.write_text("nope", encoding="utf-8")
        self.assertEqual(self.v.import_places("ana", "Perth", bad)["imported"], 0)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestGeocode(VBase):
    def hit(self, lat="-31.95", lon="115.86", name="Perth, WA"):
        return FakeResponse(json.dumps([{"lat": lat, "lon": lon, "display_name": name}]))

    def test_request_shape_and_parsing(self):
        with unittest.mock.patch.object(self.v.urllib.request, "urlopen", return_value=self.hit()) as u:
            r = self.v.geocode("1 St Georges Tce, Perth")
        self.assertEqual(r, {"lat": -31.95, "lon": 115.86, "display": "Perth, WA"})
        req = u.call_args.args[0]
        self.assertTrue(req.full_url.startswith("https://nominatim.openstreetmap.org/search?"))
        for part in ("format=jsonv2", "limit=1", "countrycodes=au", "q=1+St+Georges+Tce%2C+Perth"):
            self.assertIn(part, req.full_url)
        ua = req.get_header("User-agent")
        self.assertTrue(ua.startswith("job-harness/"))
        self.assertIn("github.com/100FOUNTS/job-harness", ua)
        self.assertNotIn("@", ua)
        self.assertEqual(u.call_args.kwargs["timeout"], 10)

    def test_errors_and_empty_answers_are_none(self):
        v = self.v
        for n, mock in enumerate((dict(side_effect=OSError("offline")), dict(return_value=FakeResponse("[]")),
                                  dict(return_value=FakeResponse("<html>")), dict(return_value=FakeResponse('{"a": 1}')),
                                  dict(return_value=FakeResponse('[{"lat": "a", "lon": "b"}]')))):
            with unittest.mock.patch.object(v.time, "sleep"), unittest.mock.patch.object(v.urllib.request, "urlopen", **mock):
                self.assertIsNone(v.geocode(f"x{n}"))
        with unittest.mock.patch.object(v.urllib.request, "urlopen") as u:
            self.assertIsNone(v.geocode("   "))
            u.assert_not_called()

    def test_rate_limiter_waits_between_requests(self):
        v = self.v
        clock = {"t": 100000.0}
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            clock["t"] += s
        with unittest.mock.patch.object(v.time, "time", side_effect=lambda: clock["t"]), \
                unittest.mock.patch.object(v.time, "sleep", side_effect=sleep), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=FakeResponse("[]")):
            v.geocode("a")                  # the first one goes straight out
            self.assertEqual(sleeps, [])
            clock["t"] += 0.4
            v.geocode("b")                  # 0.4 s later: waits the remaining 0.7
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], 0.7)
            clock["t"] += 5
            v.geocode("c")                  # long enough ago: no wait
            self.assertEqual(len(sleeps), 1)

    def test_rate_limiter_counts_failures_too(self):
        v = self.v
        clock = {"t": 100000.0}
        sleeps = []
        with unittest.mock.patch.object(v.time, "time", side_effect=lambda: clock["t"]), \
                unittest.mock.patch.object(v.time, "sleep", side_effect=sleeps.append), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", side_effect=OSError("down")):
            v.geocode("a")
            v.geocode("b")
        self.assertEqual(len(sleeps), 1)

    def test_positive_answers_are_cached_180_days_and_errors_never(self):
        v = self.v
        clock = {"t": 1_000_000.0}
        with unittest.mock.patch.object(v.time, "time", side_effect=lambda: clock["t"]), \
                unittest.mock.patch.object(v.time, "sleep"):
            with unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=self.hit()) as u:
                first = v.geocode("Acme, Perth")
                clock["t"] += 86400 * 179
                self.assertEqual(v.geocode("  ACME,   perth "), first)      # same query up to case and spaces
                self.assertEqual(u.call_count, 1)
                clock["t"] += 86400 * 2                                      # 181 days: expired
                v.geocode("Acme, Perth")
                self.assertEqual(u.call_count, 2)
            with unittest.mock.patch.object(v.urllib.request, "urlopen", side_effect=OSError("down")) as u:
                self.assertIsNone(v.geocode("Offline Co"))
                self.assertIsNone(v.geocode("Offline Co"))
                self.assertEqual(u.call_count, 2)                            # an error is not an answer
            with unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=self.hit()) as u:
                self.assertIsNotNone(v.geocode("Offline Co"))                # so it works once the network is back
                self.assertEqual(u.call_count, 1)

    def test_negative_answers_are_cached_14_days(self):
        v = self.v
        clock = {"t": 1_000_000.0}
        with unittest.mock.patch.object(v.time, "time", side_effect=lambda: clock["t"]), \
                unittest.mock.patch.object(v.time, "sleep"), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=FakeResponse("[]")) as u:
            self.assertIsNone(v.geocode("Nowhere Ltd"))
            clock["t"] += 86400 * 13
            self.assertIsNone(v.geocode("Nowhere Ltd"))
            self.assertEqual(u.call_count, 1)
            clock["t"] += 86400 * 2
            self.assertIsNone(v.geocode("Nowhere Ltd"))
            self.assertEqual(u.call_count, 2)

    def test_cache_is_persistent_and_lives_in_the_configured_folder(self):
        v = self.v
        with unittest.mock.patch.object(v.time, "sleep"), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=self.hit()):
            v.geocode("Acme, Perth")
        self.assertTrue((self.geo_dir / "nominatim.json").exists())
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import urllib.request, visits\n"
                "def boom(*a, **k): raise SystemExit('network used')\n"
                "urllib.request.urlopen = boom\n"
                "print(visits.geocode('acme, perth')['lat'])\n")
        out = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT / "scripts")], capture_output=True, text=True,
                             env={**os.environ, "JOB_HARNESS_CACHE_DIR": str(self.geo_dir)}, timeout=60)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "-31.95"), out.stderr)

    def test_corrupt_cache_file_is_a_cold_cache(self):
        v = self.v
        self.geo_dir.mkdir()
        (self.geo_dir / "nominatim.json").write_text('{"cache": [1], "last": "x"}', encoding="utf-8")
        with unittest.mock.patch.object(v.time, "sleep"), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=self.hit()) as u:
            self.assertIsNotNone(v.geocode("Acme"))
            self.assertEqual(u.call_count, 1)

    def test_unusable_cache_folder_still_geocodes(self):
        v = self.v
        blocker = self.tmp / "file"
        blocker.write_text("x", encoding="utf-8")
        os.environ["JOB_HARNESS_CACHE_DIR"] = str(blocker / "sub")      # cannot be created
        v._mem_geo.clear()
        with unittest.mock.patch.object(v.time, "sleep"), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", return_value=self.hit()) as u:
            self.assertIsNotNone(v.geocode("Acme"))
            self.assertIsNotNone(v.geocode("Acme"))
            self.assertEqual(u.call_count, 1)                            # in-process cache only

    def test_locate_repeated_runs_and_city_centre_do_not_requery(self):
        v = self.v
        self.ad("Acme")
        self.ad("Ghost Co")

        def fake(req, timeout=None):
            q = urllib_q(req)
            if "ghost" in q.lower():
                return FakeResponse("[]")
            return FakeResponse(json.dumps([{"lat": "-31.95", "lon": "115.86", "display_name": q}]))
        with unittest.mock.patch.object(v.time, "sleep"), \
                unittest.mock.patch.object(v.urllib.request, "urlopen", side_effect=fake) as u:
            first = v.locate("ana", "Perth")
            self.assertEqual((first["found"], first["missing"]), (1, ["Ghost Co"]))
            calls = u.call_count
            self.assertEqual(calls, 3)                    # city centre + Acme + Ghost Co
            second = v.locate("ana", "Perth")
            self.assertEqual((second["found"], second["missing"]), (0, ["Ghost Co"]))
            self.assertEqual(u.call_count, calls)         # the centre and the miss come from the cache

    def test_two_processes_share_the_one_request_per_second(self):
        log = self.tmp / "requests.log"
        code = ("import sys, time, urllib.request\n"
                "sys.path.insert(0, sys.argv[1]); import visits\n"
                "class R:\n"
                "    def __enter__(self): return self\n"
                "    def __exit__(self, *a): return False\n"
                "    def read(self): return b'[]'\n"
                "def fake(req, timeout=None):\n"
                "    with open(sys.argv[3], 'a') as f: f.write(repr(time.time()) + '\\n')\n"
                "    return R()\n"
                "urllib.request.urlopen = fake\n"
                "for i in range(2): visits.geocode(f'proc {sys.argv[2]} query {i}')\n")
        env = {**os.environ, "JOB_HARNESS_CACHE_DIR": str(self.geo_dir)}
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code, str(ROOT / "scripts"), str(n), str(log)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for n in range(2)]
        outs = [p.communicate(timeout=120)[0].decode() for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], outs)
        times = sorted(float(t) for t in log.read_text(encoding="utf-8").split())
        self.assertEqual(len(times), 4)
        self.assertTrue(all(b - a >= 1.0 for a, b in zip(times, times[1:])), times)


def urllib_q(req):
    import urllib.parse
    return urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)["q"][0]


class TestCLI(VBase):
    def run_cli(self, *args):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()), \
                unittest.mock.patch.object(sys, "argv", ["visits.py", "ana", *args]):
            try:
                self.v.main()
            except SystemExit as e:
                code = e.code or 0
        return code, buf.getvalue()

    def test_cities_list_set_coords_import(self):
        self.ad("Acme", fit=90)
        self.ad("Beta", "Adelaide SA", fit=80)
        self.ad("Beta", "Adelaide SA", fit=70, track="env")
        code, out = self.run_cli("cities", "--json")
        self.assertEqual((code, json.loads(out)[0]["city"]), (0, "Adelaide"))
        code, out = self.run_cli("cities")
        self.assertIn("Perth", out)
        code, out = self.run_cli("list", "--json")                       # default city: most ads
        self.assertEqual(json.loads(out)["city"], "Adelaide")
        code, out = self.run_cli("list", "--city", "Adelaide", "--track", "env", "--json")
        self.assertEqual(json.loads(out)["companies"][0]["ads"], 1)
        code, out = self.run_cli("list", "--city", "Perth")
        self.assertIn("Acme", out)
        self.assertIn("no location", out)
        code, out = self.run_cli("set", "Acme", "visited", "--city", "Perth", "--note", "hi")
        self.assertEqual((code, json.loads(out)["visit"]["stage"]), (0, "visited"))
        code, out = self.run_cli("set", "Acme", "bogus", "--city", "Perth")
        self.assertNotEqual(code, 0)                                      # argparse rejects it
        code, out = self.run_cli("coords", "Acme", "-31.95", "115.86", "--city", "Perth", "--address", "1 Tce")
        self.assertEqual((code, json.loads(out)["place"]["lat"]), (0, -31.95))
        code, out = self.run_cli("coords", "Acme", "99", "1", "--city", "Perth")
        self.assertEqual(code, 1)
        f = self.tmp / "o.json"
        f.write_text(json.dumps([{"company": "Zed", "lat": 1, "lon": 2}]), encoding="utf-8")
        code, out = self.run_cli("import", str(f), "--city", "Perth")
        self.assertEqual(json.loads(out), {"imported": 1})
        code, out = self.run_cli("list", "--city", "Perth")
        self.assertIn("1 Tce", out)
        self.assertIn("To visit 1, Visited 1", out)

    def test_address_and_locate_use_mocked_geocoder(self):
        self.ad("Acme")
        with unittest.mock.patch.object(self.v, "geocode", return_value={"lat": 1.0, "lon": 2.0, "display": ""}):
            code, out = self.run_cli("address", "Acme", "1 Tce", "--city", "Perth")
            self.assertEqual((code, json.loads(out)["ok"]), (0, True))
            code, out = self.run_cli("locate", "--city", "Perth")
            self.assertEqual(json.loads(out), {"found": 0, "missing": []})
        with unittest.mock.patch.object(self.v, "geocode", return_value=None):
            code, out = self.run_cli("address", "Acme", "2 Tce", "--city", "Perth")
            self.assertEqual(code, 1)

    def test_no_city_without_ads(self):
        code, out = self.run_cli("list")
        self.assertNotEqual(code, 0)

    def test_bin_job_routes_visits(self):
        env = dict(os.environ, JOB_CANDIDATES_DIR=str(self.tmp))
        r = subprocess.run([sys.executable, str(ROOT / "bin/job"), "visits", "ana", "cities", "--json"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, []))
        self.assertIn("job visits", (ROOT / "bin/job").read_text(encoding="utf-8").split('"""')[1])


if __name__ == "__main__":
    unittest.main()
