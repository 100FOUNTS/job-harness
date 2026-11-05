"""Panel: the visa sponsor icon on board cards (match level from the sponsor lists; for the person's eyes only)."""
import os
import sys
import unittest
import unittest.mock

from test_core import Base, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

LISTED = {"Acme Pty Ltd": {"match": "exact", "names": ["ACME PTY LTD"], "lists": ["Accredited 2025"], "more": 0},
          "Beta": {"match": "likely", "names": ["BETA GROUP PTY LTD"], "lists": ["Accredited 2023"], "more": 0},
          "Gamma Water": {"match": "possible", "names": ["GAMMA WATER SERVICES PTY LTD"], "lists": ["Accredited 2023"], "more": 0}}


class TestSponsorIcon(Base):
    def test_cards_carry_the_match_and_unlisted_companies_carry_none(self):
        import panel
        from tracker import add
        for i, co in enumerate(["Acme Pty Ltd", "Beta", "Gamma Water", "Unlisted Co"], 1):
            add("ana", {"key": f"seek:{i}", "title": f"Role {i}", "company": co, "url": f"u{i}", "platform": "seek", "fit": 60})
        with unittest.mock.patch("sponsors.lookup", side_effect=lambda c: LISTED.get(c)), \
                unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
            d = panel.data("ana")
        got = {a["company"]: (a["sponsor_match"], a["sponsor_name"]) for a in d["apps"]}
        self.assertEqual(got["Acme Pty Ltd"], ("exact", "ACME PTY LTD"))
        self.assertEqual(got["Beta"], ("likely", "BETA GROUP PTY LTD"))
        self.assertEqual(got["Gamma Water"], ("possible", "GAMMA WATER SERVICES PTY LTD"))
        self.assertEqual(got["Unlisted Co"], ("", ""))

    def test_without_sponsor_data_nothing_is_marked(self):
        import panel
        with unittest.mock.patch("sponsors._index", return_value=({}, {})):
            self.assertEqual(panel.sponsor_of("Acme Pty Ltd"), {"sponsor_match": "", "sponsor_name": ""})

    def test_page_shows_a_badge_for_every_level_and_a_filter_with_words(self):
        html = panel_page()
        card = html.split("function card(a)")[1].split("</article>")[0]
        self.assertIn("passport:", html)
        self.assertIn("passportq:", html)                                                  # a question mark for the weakest level
        self.assertIn("const hasSponsor = a => !!SPONSOR_TIP[a.sponsor_match];", html)
        for level in ("exact", "likely", "possible"):
            self.assertIn(f"{level}: \"", html.split("const SPONSOR_TIP = {")[1].split("};")[0])
        self.assertIn("${sponsorBadge(a)}", card)
        self.assertIn("if (S.sp && !hasSponsor(a)) return false;", html)
        self.assertIn("Sponsor lists</button>", html)                                      # the filter explains the badge once
        self.assertIn("if (t.dataset.sp) { toast(t.dataset.sp); return; }", html)          # tap explains it on a phone
        self.assertNotIn("sponsor</span>", card)


def panel_page():
    import panel
    return panel.PAGE.read_text(encoding="utf-8")

class TestApplyRoute(Base):
    def test_cards_carry_how_the_job_is_applied_for(self):
        import panel
        import applyroute
        from jobdb import record_seen
        from tracker import add, set_status
        rows = [("seek:1", "quick", ""), ("lever:a/2", "external", "lever"), ("linkedin:3", "external", "workday"),
                ("linkedin:4", "external", ""), ("seek:5", "", "")]
        record_seen("ana", [{"key": k, "id": k.split(":", 1)[1], "platform": k.split(":")[0], "title": "T", "company": "C", "url": "u",
                             "tracks": [], "bullets": []} for k, *_ in rows], "2026-11-01")
        for k, route, ats in rows:
            add("ana", {"key": k, "title": "Role", "company": "Co", "url": "u", "platform": k.split(":")[0], "fit": 60})
            set_status("ana", k, "prepared")
            if route:
                applyroute.record("ana", k, route, ats)
        with unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
            d = panel.data("ana")
        got = {a["key"]: (a["apply"], a["apply_ats"]) for a in d["apps"]}
        self.assertEqual(got, {"seek:1": ("quick", ""), "lever:a/2": ("open-ats", "lever"), "linkedin:3": ("account-ats", "workday"),
                               "linkedin:4": ("company-site", ""), "seek:5": ("unknown", "")})

    def test_the_page_tags_only_what_is_known(self):
        html = panel_page()
        self.assertIn("const APPLY_TAG", html)
        self.assertIn("a.col === \"todo\" ? applyTag(a)", html)
        self.assertNotIn("unknown:", html.split("const APPLY_TAG")[1].split("function card")[0])
        for gate in ("open", "login", "captcha", "blocked"):                               # what the Apply button led to wins over the class
            self.assertIn(f"{gate}: [", html.split("const GATE_TAG")[1].split("const applyTag")[0])

    def test_cards_carry_the_gate_found_by_the_probe(self):
        import panel
        import applyroute
        from jobdb import record_seen
        from tracker import add, set_status
        record_seen("ana", [{"key": "linkedin:9", "id": "9", "platform": "linkedin", "title": "T", "company": "C", "url": "u",
                             "tracks": [], "bullets": []}], "2026-11-01")
        add("ana", {"key": "linkedin:9", "title": "Role", "company": "Co", "url": "u", "platform": "linkedin", "fit": 60})
        set_status("ana", "linkedin:9", "prepared")
        applyroute.set_url("ana", "linkedin:9", "https://acme.wd3.myworkdayjobs.com/x", "login")
        with unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
            d = panel.data("ana")
        self.assertEqual((d["apps"][0]["apply"], d["apps"][0]["apply_gate"]), ("account-ats", "login"))


if __name__ == "__main__":
    unittest.main()
