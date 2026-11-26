"""The visits routes of the panel (GET /api/visits, POST /visit, /visit-details, /visit-address), with scripts/visits.py mocked."""
import json
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_panel_v3 import PanelBase, Server  # noqa: E402

OK = {"ok": True, "visit": {"stage": "visited"}}


class VisitsApiTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.v = types.SimpleNamespace(
            cities=unittest.mock.Mock(return_value=[{"city": "Perth", "companies": 3, "ads": 7}, {"city": "Adelaide", "companies": 1, "ads": 1}]),
            places=unittest.mock.Mock(return_value={"city": "Perth", "tracks": ["software"], "companies": [], "funnel": [], "missing": 0}),
            set_stage=unittest.mock.Mock(return_value=OK),
            set_details=unittest.mock.Mock(return_value={"ok": True, "visit": {}}),
            set_address=unittest.mock.Mock(return_value={"ok": True, "place": {"lat": -31.9}}),
            set_coords=unittest.mock.Mock(return_value={"ok": True, "place": {"lat": -31.9}}),
        )
        p = unittest.mock.patch.dict(sys.modules, {"visits": self.v})
        p.start(); self.addCleanup(p.stop)
        import panel
        self.panel = panel

    def post(self, s, path, body, token=True):
        return s.req("POST", path, {"X-Panel-Token": self.panel.TOKEN} if token else {}, body)

    def test_get_defaults_to_the_first_city_and_adds_the_list(self):
        with Server(self.panel, lan=False) as s:
            code, _, raw = s.req("GET", "/api/visits?slug=ana")
        out = json.loads(raw)
        self.assertEqual(code, 200)
        self.assertEqual(out["city"], "Perth")
        self.assertEqual([c["city"] for c in out["cities"]], ["Perth", "Adelaide"])
        self.v.places.assert_called_once_with("ana", "Perth", None)

    def test_get_with_city_and_tracks(self):
        with Server(self.panel, lan=False) as s:
            s.req("GET", "/api/visits?slug=ana&city=Adelaide&tracks=software,%20data,")
        self.v.places.assert_called_once_with("ana", "Adelaide", ["software", "data"])

    def test_get_without_any_city(self):
        self.v.cities.return_value = []
        with Server(self.panel, lan=False) as s:
            out = json.loads(s.req("GET", "/api/visits?slug=ana")[2])
        self.assertEqual((out["city"], out["companies"], out["cities"]), ("", [], []))
        self.v.places.assert_not_called()

    def test_get_validates_and_never_shows_a_stack_trace(self):
        with Server(self.panel, lan=False) as s:
            code, _, raw = s.req("GET", "/api/visits?slug=ana&city=" + "x" * 81)
            self.assertEqual(code, 400)
            self.assertFalse(json.loads(raw)["ok"])
            self.assertEqual(s.req("GET", "/api/visits?slug=ana&tracks=" + "t" * 61)[0], 400)
            self.v.places.side_effect = RuntimeError("boom /secret/path")
            code, _, raw = s.req("GET", "/api/visits?slug=ana")
            self.assertEqual(code, 500)
            self.assertNotIn(b"secret", raw); self.assertNotIn(b"Traceback", raw)
            self.assertEqual(s.req("GET", "/api/visits?slug=nobody")[0], 404)

    def test_visit_sets_the_stage(self):
        with Server(self.panel, lan=False) as s:
            code, _, raw = self.post(s, "/visit", {"slug": "ana", "company": " Acme Pty ", "city": "Perth", "stage": "visited", "note": "left CV"})
        self.assertEqual((code, json.loads(raw)), (200, OK))
        self.v.set_stage.assert_called_once_with("ana", "Acme Pty", "Perth", "visited", "left CV")

    def test_visit_passes_a_refusal_of_visits_through(self):
        self.v.set_stage.return_value = {"ok": False, "error": "unknown stage"}
        with Server(self.panel, lan=False) as s:
            code, _, raw = self.post(s, "/visit", {"slug": "ana", "company": "A", "city": "Perth", "stage": "nope"})
        self.assertEqual(json.loads(raw), {"ok": False, "error": "unknown stage"})

    def test_bad_input_is_a_json_error(self):
        good = {"slug": "ana", "company": "A", "city": "Perth", "stage": "visited"}
        bad = [good | {"stage": 5}, good | {"stage": None}, good | {"company": ""}, good | {"company": ["x"]}, good | {"city": 3},
               good | {"note": "n" * 2001}, good | {"company": "c" * 201}, {k: v for k, v in good.items() if k != "city"}]
        with Server(self.panel, lan=False) as s:
            for body in bad:
                code, _, raw = self.post(s, "/visit", body)
                self.assertEqual(code, 400, body)
                out = json.loads(raw)
                self.assertFalse(out["ok"]); self.assertTrue(out["error"])
            self.assertEqual(self.post(s, "/visit", [1, 2])[0], 400)         # a JSON list, not an object
        self.v.set_stage.assert_not_called()

    def test_unexpected_failure_hides_the_details(self):
        self.v.set_stage.side_effect = OSError("disk /private/place")
        with Server(self.panel, lan=False) as s:
            code, _, raw = self.post(s, "/visit", {"slug": "ana", "company": "A", "city": "Perth", "stage": "visited"})
        self.assertEqual(code, 500)
        self.assertFalse(json.loads(raw)["ok"])
        self.assertNotIn(b"private", raw); self.assertNotIn(b"Traceback", raw)

    def test_visit_details_none_means_unchanged(self):
        with Server(self.panel, lan=False) as s:
            self.post(s, "/visit-details", {"slug": "ana", "company": "A", "city": "Perth", "contact": "Sam 0400"})
            self.post(s, "/visit-details", {"slug": "ana", "company": "A", "city": "Perth", "note": ""})
            self.assertEqual(self.post(s, "/visit-details", {"slug": "ana", "company": "A", "city": "Perth", "note": 7})[0], 400)
            self.assertEqual(self.post(s, "/visit-details", {"slug": "ana", "company": "A", "city": "Perth", "contact": "c" * 2001})[0], 400)
        self.assertEqual(self.v.set_details.call_args_list, [
            unittest.mock.call("ana", "A", "Perth", note=None, contact="Sam 0400"),
            unittest.mock.call("ana", "A", "Perth", note="", contact=None)])

    def test_visit_address_geocodes_or_takes_coordinates(self):
        base = {"slug": "ana", "company": "A", "city": "Perth"}
        with Server(self.panel, lan=False) as s:
            self.assertEqual(self.post(s, "/visit-address", base | {"address": "1 St Georges Tce"})[0], 200)
            self.v.set_address.assert_called_once_with("ana", "A", "Perth", "1 St Georges Tce")
            self.assertEqual(self.post(s, "/visit-address", base | {"lat": "-31.95", "lon": 115.86, "address": "x"})[0], 200)
            self.v.set_coords.assert_called_once_with("ana", "A", "Perth", -31.95, 115.86, "x")
            for body in (base, base | {"address": ""}, base | {"lat": -31.9}, base | {"lat": 91, "lon": 0}, base | {"lat": 0, "lon": 181},
                         base | {"lat": "abc", "lon": 1}, base | {"lat": True, "lon": 1}, base | {"lat": "nan", "lon": 1},
                         base | {"address": 5}, base | {"address": "a" * 301}):
                self.assertEqual(self.post(s, "/visit-address", body)[0], 400, body)
        self.assertEqual(self.v.set_address.call_count, 1)
        self.assertEqual(self.v.set_coords.call_count, 1)

    def test_posts_keep_the_token_and_the_slug_check(self):
        good = {"slug": "ana", "company": "A", "city": "Perth", "stage": "visited"}
        with Server(self.panel, lan=False) as s:
            for path in ("/visit", "/visit-details", "/visit-address"):
                self.assertEqual(self.post(s, path, good, token=False)[0], 403, path)
            self.assertEqual(self.post(s, "/visit", good | {"slug": "nobody"})[0], 404)
        self.v.set_stage.assert_not_called()


class MapTilesTests(unittest.TestCase):
    def test_osm_tiles_send_a_referer(self):
        """The page sends no Referer (Referrer-Policy: no-referrer) and OSM answers 403 'Access blocked' without one."""
        tpl = (Path(__file__).resolve().parent.parent / "templates" / "panel.html").read_text(encoding="utf-8")
        i = tpl.index("L.tileLayer(")
        call = tpl[i:tpl.index(".addTo(", i)]
        self.assertIn('referrerPolicy: "strict-origin-when-cross-origin"', call)
        self.assertNotIn("{s}.tile.openstreetmap", call)


if __name__ == "__main__":
    unittest.main()
