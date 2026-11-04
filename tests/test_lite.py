"""The lite pack (lite/): every skill has valid frontmatter and builds into an uploadable zip."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_lite  # noqa: E402

FORBIDDEN = ("hooks/", "bin/job", "job gate", "job sign", "job facts", "job lint", "facts.json", "python")


class TestLite(unittest.TestCase):
    def test_skills_exist(self):
        names = {p.name for p in build_lite.skills()}
        self.assertTrue({"job-tailor-lite", "job-interview-lite", "job-review-lite"} <= names, names)

    def test_frontmatter_valid(self):
        for d in build_lite.skills():
            self.assertEqual(build_lite.problems(d), [], d.name)

    def test_no_cli_references(self):
        """Lite skills run in claude.ai or Cowork: no CLI, hooks, gates or Python."""
        for d in build_lite.skills():
            text = (d / "SKILL.md").read_text(encoding="utf-8").lower()
            for word in FORBIDDEN:
                self.assertNotIn(word, text, f"{d.name} mentions {word}")

    def test_frontmatter_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "My_Skill"
            bad.mkdir()
            (bad / "SKILL.md").write_text("---\nname: My_Skill\ndescription: <b>x</b>\n---\n", encoding="utf-8")
            errs = " ".join(build_lite.problems(bad))
            self.assertIn("lowercase", errs)
            self.assertIn("XML", errs)
            nofm = Path(tmp) / "plain"
            nofm.mkdir()
            (nofm / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
            self.assertTrue(build_lite.problems(nofm))
            reserved = Path(tmp) / "claude-helper"
            reserved.mkdir()
            (reserved / "SKILL.md").write_text("---\nname: claude-helper\ndescription: ok\n---\n", encoding="utf-8")
            self.assertIn("claude", " ".join(build_lite.problems(reserved)))

    def test_zips_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            made = build_lite.build(Path(tmp) / "lite")
            self.assertEqual(len(made), len(build_lite.skills()))
            for z in made:
                with zipfile.ZipFile(z) as zf:
                    self.assertIsNone(zf.testzip())
                    names = zf.namelist()
                    self.assertIn(f"{z.stem}/SKILL.md", names)
                    self.assertTrue(all(n.startswith(z.stem + "/") for n in names), names)
            again = build_lite.build(Path(tmp) / "again")
            self.assertEqual(made[0].read_bytes(), again[0].read_bytes())      # reproducible


if __name__ == "__main__":
    unittest.main()
