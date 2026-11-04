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

    def test_page_draws_an_icon_and_a_filter_but_no_word_on_the_card(self):
        html = panel_page()
        self.assertIn("passport:", html)
        self.assertIn('a.sponsor_match ? `<span class="tag sponsor ', html)
        self.assertIn("if (S.sp && !a.sponsor_match) return false;", html)
        self.assertNotIn("sponsor</span>", html.split("function card(a)")[1].split("let body")[0])    # icon only, never a label


def panel_page():
    import panel
    return panel.PAGE.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
