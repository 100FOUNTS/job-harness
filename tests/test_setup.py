"""PDF reading without Poppler, `job doctor` and `job setup`."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pdftext  # noqa: E402

DOCS = ROOT / "templates/docs"


def job(*args, **env):
    e = {**os.environ, **env}
    return subprocess.run([sys.executable, str(ROOT / "bin/job"), *args], capture_output=True, encoding="utf-8", env=e)


@unittest.skipUnless(pdftext.node_ready() and (DOCS / "node_modules/pdfkit").exists(), "run `job setup` first")
class TestPdfText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / "cv.pdf"
        subprocess.run(["node", str(DOCS / "generar_pdf.js"), "cv", str(ROOT / "candidates/example/docs/cv_main.json"),
                        str(cls.pdf)], check=True, cwd=DOCS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_pages(self):
        self.assertEqual(pdftext.pages(self.pdf), 1)

    def test_text_keeps_headings_and_dates(self):
        t = pdftext.text(self.pdf)
        for want in ("Sam Taylor", "sam.taylor@example.com", "WORK EXPERIENCE", "Feb 2023 - Present"):
            self.assertIn(want, t)
        self.assertTrue(any(l.strip() == "KEY SKILLS" for l in t.splitlines()))

    def test_lines_are_top_down_word_boxes(self):
        (height, lines), = pdftext.lines(self.pdf)
        self.assertAlmostEqual(height, 841.89, places=1)
        self.assertEqual(lines[0][2], "Sam Taylor")
        self.assertTrue(all(t < b for t, b, _ in lines))
        self.assertEqual(lines, sorted(lines))
        self.assertTrue(lines[0][0] < lines[-1][0] < height)

    def test_layout_check_runs_on_the_new_reader(self):
        import lint
        self.assertEqual(lint.layout_issues(self.pdf, "cv"), [])

    def test_unreadable_file_reads_as_empty(self):
        bad = self.tmp / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4")
        for f in (bad, self.tmp / "nope.pdf"):
            self.assertEqual((pdftext.pages(f), pdftext.lines(f), pdftext.text(f)), (0, [], ""))


class TestNoReader(unittest.TestCase):
    def test_no_node_and_no_poppler_says_what_to_do(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            for fn in (pdftext.pages, pdftext.lines, pdftext.text):
                with self.assertRaises(RuntimeError) as c:
                    fn(Path("x.pdf"))
                self.assertIn("job setup", str(c.exception))

    def test_falls_back_to_poppler_when_node_is_missing(self):
        def which(name):
            return "/usr/bin/" + name if name in ("pdftotext", "pdfinfo") else None
        with unittest.mock.patch("shutil.which", side_effect=which), \
                unittest.mock.patch.object(pdftext, "_poppler", return_value="Pages:          3\n") as p:
            self.assertEqual(pdftext.pages(Path("x.pdf")), 3)
            self.assertEqual(p.call_args[0][0][0], "pdfinfo")

    def test_lint_cli_reports_it_in_one_line(self):
        import lint
        with unittest.mock.patch.object(lint, "lint", side_effect=RuntimeError(pdftext.NO_READER)), \
                unittest.mock.patch.object(sys, "argv", ["lint", "ana", "x.pdf"]):
            with self.assertRaises(SystemExit) as c:
                lint.main()
        self.assertIn("job setup", str(c.exception))


class TestDoctor(unittest.TestCase):
    def test_json_keys_are_stable(self):
        r = job("doctor", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        for k in ("node", "docx_module", "pdfkit_module (headless PDF)", "claude_cli", "claude --chrome flag",
                  "launchd schedules", "network: seek search", "pdf_reader", "python_ok", "node_ok"):
            self.assertIn(k, d)

    def test_human_output_ends_with_a_verdict(self):
        import doctor
        ok = {"python": "3.12.0", "python_ok": True, "node": True, "node_major": 22, "node_ok": True, "docx_module": True,
              "pdfkit_module (headless PDF)": True, "pdfjs_module": True, "pdf_reader": "pdf.js",
              "package_dir": "/x", "package_dir_writable": True, "claude_cli": False, "claude --chrome flag": False,
              "playwright (apply/)": False, "network: seek search": False}
        for r, verdict in ((ok, "Ready to prepare applications"),
                            ({**ok, "node": False, "node_major": 0, "node_ok": False, "pdf_reader": None}, "2 things to fix first")):
            with unittest.mock.patch("builtins.print") as pr:
                doctor.show(r)
            out = "\n".join(str(c.args[0]) for c in pr.call_args_list if c.args)
            self.assertEqual(out.strip().splitlines()[-1], verdict)
        self.assertIn("fix:", out)
        self.assertIn("Required", out)
        self.assertIn("Optional", out)

    def test_optional_gaps_do_not_block(self):
        r = job("doctor")
        last = r.stdout.strip().splitlines()[-1]
        self.assertTrue(last == "Ready to prepare applications" or last.endswith("to fix first"), last)


class TestSetup(unittest.TestCase):
    def test_check_changes_nothing(self):
        home = Path(tempfile.mkdtemp())
        try:
            r = job("setup", "--check", HOME=str(home), USERPROFILE=str(home), JOB_PACKAGE_DIR=str(home / "pk"))
            self.assertIn("Required", r.stdout, r.stderr)
            self.assertEqual(list(home.iterdir()), [])
        finally:
            shutil.rmtree(home)

    def test_node_missing_prints_the_install_command_and_stops(self):
        import setup
        with unittest.mock.patch("doctor.node_version", return_value=0), \
                unittest.mock.patch.object(sys, "argv", ["setup"]), \
                unittest.mock.patch("builtins.print") as pr:
            with self.assertRaises(SystemExit) as c:
                setup.main()
        self.assertEqual(c.exception.code, 1)
        out = "\n".join(str(x.args[0]) for x in pr.call_args_list if x.args)
        self.assertIn("Node.js not found", out)
        self.assertTrue(any(w in out for w in ("brew install node", "winget install OpenJS.NodeJS.LTS", "nodejs.org")))


if __name__ == "__main__":
    unittest.main()
