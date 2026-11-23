"""CV JSON: the optional employment `type`, 3-letter months, and the warnings about both (real parser feedback:
"(part-time)" inside a role was read as part of the title; long and bare dates mixed with "Mon YYYY" were penalised)."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pdftext  # noqa: E402
from lint import cv_json_warnings  # noqa: E402

DOCS = ROOT / "templates/docs"
NODE = pdftext.node_ready() and (DOCS / "node_modules/docx").exists() and (DOCS / "node_modules/pdfkit").exists()


def sample_cv():
    cv = json.loads((ROOT / "candidates/example/docs/cv_main.json").read_text(encoding="utf-8"))
    cv["experience"] = [
        {"role": "Assistant Manager", "org": "Corner Cafe, Brisbane", "dates": "September 2020 – March 2021",
         "type": "Part-time", "bullets": ["Ran the roster."]},
        {"role": "Graduate Engineer", "org": "Sample Engineering, Brisbane", "dates": "Jan 2022 - Jan 2023",
         "bullets": ["Designed drainage."]},
    ]
    cv["other_employment"] = [{"role": "Barista", "org": "Cafe Two", "type": "Casual", "bullets": ["Made coffee."]}]
    cv["education"] = [["Bachelor of Engineering (Civil)", "Example University", "2019"],
                       ["Master of Water Engineering", "Example University", "Expected December 2026"]]
    return cv


class TestRoleTypeWarning(unittest.TestCase):
    def roles(self, *roles):
        return cv_json_warnings({"experience": [{"role": r, "org": "X", "bullets": []} for r in roles]})

    def test_type_inside_the_role_is_flagged(self):
        for role in ("Assistant Manager (part-time)", "Barista (Casual)", "Engineer (Full-Time, 3 days)", "Analyst (Contract)",
                     "Admin (temporary)", "Officer (fixed-term)", "Helper (volunteer)", "Student (Internship)",
                     "Barista - Casual", "Engineer, Contract", "Driver | Part time"):
            w = self.roles(role)
            self.assertEqual(len(w), 1, role)
            self.assertIn('"type"', w[0])
            self.assertIn(role, w[0])

    def test_plain_titles_and_the_type_field_are_fine(self):
        self.assertEqual(self.roles("Assistant Manager", "Contract Administrator", "Casual Relief Teacher",
                                    "Volunteer Coordinator", "Engineer (Civil)", "Intern Engineer"), [])
        self.assertEqual(cv_json_warnings({"experience": sample_cv()["experience"]}), [])

    def test_every_entry_section_is_checked(self):
        entry = {"role": "Cook (casual)", "org": "X", "bullets": []}
        cv = {s: [entry] for s in ("experience", "entrepreneurship", "projects", "other_employment")}
        cv["projects"] = ["a one-line project", ["name", "text"], entry]       # other project shapes are skipped
        self.assertEqual(len(cv_json_warnings(cv)), 4)

    def test_odd_input_does_not_crash(self):
        self.assertEqual(cv_json_warnings([]), [])
        self.assertEqual(cv_json_warnings({"experience": "none", "education": None, "projects": "a paragraph"}), [])


class TestEducationDateWarning(unittest.TestCase):
    def edu(self, *dates):
        return cv_json_warnings({"education": [["Degree", "Uni", d] for d in dates]})

    def test_full_month_names_are_flagged(self):
        w = self.edu("Expected December 2026", "September 2020 - March 2021", "Sept 2019")
        self.assertEqual(len(w), 3)
        self.assertIn("Mon YYYY", w[0])

    def test_short_months_bare_years_and_missing_dates_are_fine(self):
        self.assertEqual(self.edu("2019", "Expected Dec 2026", "May 2020", "Mar 2020 - Dec 2021"), [])
        self.assertEqual(cv_json_warnings({"education": [["Degree", "Example University, 2021"]]}), [])


class TestDateOutsideDatesWarning(unittest.TestCase):
    def entry(self, role="Engineer", org="Acme, Perth", dates="Mar 2023 - Present"):
        return cv_json_warnings({"experience": [{"role": role, "org": org, "dates": dates, "bullets": []}]})

    def test_date_in_the_org_is_flagged(self):          # the Affinda case: read as the whole date range
        w = self.entry(org="100 FOUNTS, Perth WA (freelance until Mar 2026)")
        self.assertEqual(len(w), 1)
        self.assertIn("'Mar 2026'", w[0])
        self.assertIn("job's date range", w[0])
        self.assertIn('only in "dates"', w[0])
        self.assertIn("bullet", w[0])
        self.assertIn("split the entry", w[0])

    def test_date_in_the_role_is_flagged(self):
        for role in ("Site Engineer (2019)", "Engineer since March 2019", "Engineer, Sept 2020", "Analyst 2024"):
            w = self.entry(role=role)
            self.assertEqual(len(w), 1, role)
            self.assertIn("inside the role", w[0])

    def test_every_entry_section_is_checked(self):
        e = {"role": "Cook", "org": "X (2021)", "bullets": []}
        cv = {s: [e] for s in ("experience", "entrepreneurship", "projects", "other_employment")}
        self.assertEqual(len(cv_json_warnings(cv)), 4)

    def test_heading_with_a_date_is_flagged(self):
        w = cv_json_warnings({"projects_heading": "Data and AI Projects (Self-Directed Study, 2026)"})
        self.assertEqual(len(w), 1)
        self.assertIn("projects_heading", w[0])
        self.assertIn("'2026'", w[0])
        self.assertEqual(len(cv_json_warnings({"projects_heading": "Projects, Mar 2025"})), 1)

    def test_things_that_only_look_like_dates_are_fine(self):
        for text in ("ISO 14001 Lead Auditor", "Spring Boot 3 Developer", "Plain Org, Perth",
                     "Engineer", "Project Manager (Civil)", "Postgres 15", "Marketing Lead", "Level 1234"):
            self.assertEqual(self.entry(role=text, org=text), [], text)
        self.assertEqual(cv_json_warnings({"projects_heading": "Data and AI Projects"}), [])

    def test_dates_field_and_other_fields_are_not_flagged(self):
        self.assertEqual(self.entry(dates="Mar 2023 - Present"), [])
        cv = {"experience": [{"role": "Engineer", "org": "X", "dates": "2019 - 2021", "bullets": ["Since Mar 2020 led a team."]}],
              "summary": "Engineer since 2015.", "skills": [["Tools", "Excel 2019"]]}
        self.assertEqual(cv_json_warnings(cv), [])

    def test_the_example_candidate_cv_has_no_warnings(self):
        cv = json.loads((ROOT / "candidates/example/docs/cv_main.json").read_text(encoding="utf-8"))
        self.assertEqual(cv_json_warnings(cv), [])


@unittest.skipUnless(NODE, "run `job setup` first")
class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src = cls.tmp / "cv.json"
        cls.src.write_text(json.dumps(sample_cv()), encoding="utf-8")
        cls.docx, cls.pdf = cls.tmp / "cv.docx", cls.tmp / "cv.pdf"
        subprocess.run(["node", str(DOCS / "generar_cv.js"), str(cls.src), str(cls.docx)], check=True, cwd=DOCS, capture_output=True)
        subprocess.run(["node", str(DOCS / "generar_pdf.js"), "cv", str(cls.src), str(cls.pdf)], check=True, cwd=DOCS, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def texts(self):
        from facts import extract_text
        one = lambda t: re.sub(r"[ \t]+", " ", t)          # the PDF reader collapses the double spaces around "|"
        return {"docx": one(extract_text(self.docx)), "pdf": one(pdftext.text(self.pdf))}

    def test_type_follows_the_dates_on_the_org_line(self):
        for kind, t in self.texts().items():
            self.assertIn("Corner Cafe, Brisbane | Sep 2020 - Mar 2021 | Part-time", t, kind)
            self.assertIn("Cafe Two | Casual", t, kind)         # no dates: the type still follows the org

    def test_entry_without_type_is_unchanged(self):
        for kind, t in self.texts().items():
            lines = [l.strip() for l in t.splitlines()]
            self.assertIn("Sample Engineering, Brisbane | Jan 2022 - Jan 2023", lines, kind)

    def test_months_are_abbreviated_and_bare_years_kept(self):
        for kind, t in self.texts().items():
            self.assertIn("Example University | Expected Dec 2026", t, kind)
            self.assertIn("Example University | 2019", t, kind)
            self.assertNotIn("December", t, kind)
            self.assertNotIn("September", t, kind)
            self.assertNotIn("– March", t, kind)

    def test_the_example_cv_still_renders_the_same_line(self):
        out = self.tmp / "ex.docx"
        subprocess.run(["node", str(DOCS / "generar_cv.js"), str(ROOT / "candidates/example/docs/cv_main.json"), str(out)],
                       check=True, cwd=DOCS, capture_output=True)
        from facts import extract_text
        self.assertIn("Example Consulting, Brisbane  |  Feb 2023 - Present", extract_text(out))      # docx keeps both spaces


class TestBuildReportsWarnings(unittest.TestCase):
    def test_build_returns_warnings_and_still_passes(self):
        import docs
        import os
        tmp = Path(tempfile.mkdtemp())
        os.environ["JOB_CANDIDATES_DIR"] = str(tmp)
        try:
            shutil.copytree(ROOT / "templates/candidate", tmp / "ana")
            cv = sample_cv()
            cv["experience"][0].pop("type")
            cv["experience"][0]["role"] = "Assistant Manager (part-time)"
            (tmp / "ana/docs").mkdir(exist_ok=True)
            (tmp / "ana/docs/cv.json").write_text(json.dumps(cv), encoding="utf-8")
            from unittest import mock
            with mock.patch.object(docs, "need_node"), \
                    mock.patch.object(docs.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                    mock.patch.object(docs, "export_pdf", return_value=None), \
                    mock.patch.object(docs, "lint", return_value={"ok": True}), mock.patch.object(docs, "verify", return_value={"ok": True}):
                r = docs.build("ana", Path("docs/cv.json"), "cv", None, None)
            self.assertTrue(r["ok"])
            self.assertEqual(len(r["warnings"]), 2)           # the role and the long education month
            self.assertIn("part-time", r["warnings"][0])
        finally:
            shutil.rmtree(tmp)
            os.environ.pop("JOB_CANDIDATES_DIR", None)


if __name__ == "__main__":
    unittest.main()
