"""The daily package's index.html: the ads are untrusted text, so nothing reaches the page unescaped."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import Base  # noqa: E402

EVIL = "https://x.test/a'><script>alert(1)</script>"


class IndexHtmlTests(Base):
    def item(self, **kw):
        return {"n": 1, "key": "seek:1", "title": "<b>Officer</b>", "company": "Acme & <i>Sons</i>", "url": "https://x.test/job?a=1&b=2",
                "fit": 70, "dir": "01_Acme", "platform": "seek",
                "notes": {"role": "<img src=x onerror=alert(1)>", "fits": "f", "watch": "—", "how": "h", "prob": "high"}} | kw

    def build(self, **kw):
        import prepare
        pkg = self.tmp / "pkg"
        pkg.mkdir(exist_ok=True)
        prepare.write_index(pkg, [self.item(**kw)], "ana")
        return (pkg / "index.html").read_text(encoding="utf-8")

    def test_a_quote_in_the_url_cannot_break_out_of_the_href(self):
        page = self.build(url=EVIL)
        self.assertNotIn("<script>", page)
        self.assertEqual(page.count("<a href"), 1)                          # only the folder link: the odd URL is not linked
        page = self.build(url="https://x.test/a?q=1&r=<2>")
        self.assertNotIn("<2>", page)

    def test_urls_that_are_not_http_are_plain_text(self):
        for bad in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>1</script>", "//evil.test/x",
                    " javascript:alert(1)", "", "https://", "https://a b"):
            page = self.build(url=bad)
            self.assertNotIn("javascript:", page.lower().replace("&", ""), bad)
            self.assertNotIn("href='data:", page, bad)
            self.assertEqual(page.count("<a href"), 1, bad)                    # only the folder link
            self.assertIn("Open ad", page)

    def test_http_and_https_urls_are_linked_escaped(self):
        page = self.build()
        self.assertIn("<a href='https://x.test/job?a=1&amp;b=2'>Open ad</a>", page)
        self.assertEqual(self.build(url="http://x.test/y").count("<a href"), 2)

    def test_every_interpolated_value_is_escaped(self):
        page = self.build()
        for raw in ("<b>Officer</b>", "<i>Sons</i>", "<img", "Acme & "):
            self.assertNotIn(raw, page)
        self.assertIn("&lt;b&gt;Officer&lt;/b&gt;", page)
        self.assertIn("Acme &amp; &lt;i&gt;Sons&lt;/i&gt;", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)
        self.assertNotIn("<script", page)

    def test_the_folder_name_cannot_break_the_href(self):
        page = self.build(dir="x' onmouseover='alert(1)")             # no < > : Windows forbids them in folder names
        self.assertNotIn("' onmouseover='", page)
        self.assertIn("href='x&#x27; onmouseover=&#x27;alert(1)/'", page)


if __name__ == "__main__":
    unittest.main()
