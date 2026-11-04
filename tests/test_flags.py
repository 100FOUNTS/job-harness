"""Red flags (scripts/flags.py) and follow-up drafts (scripts/followup.py): warnings and drafts only."""
import io
import json
import re
import sys
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_core import ROOT, Base  # noqa: E402

import flags  # noqa: E402
from flags import check, parse_pay  # noqa: E402

VISA = re.compile(r"visa|sponsor|work(ing)? rights|citizen|residen|subclass", re.I)
T = {"ranking": {"min_salary_k": 80}, "tracks": []}
NORMAL = {"title": "Environmental Officer", "company": "Acme Environmental", "salary": "$90,000 - $105,000 + super",
          "description": "Join our Perth team. Visa sponsorship is not available; you must have full working rights. "
                         "Apply via our careers page or email careers@acme.com.au. Interviews on site. 3 years experience."}


def job(**kw):
    return {"title": "Officer", "company": "Acme", "description": "", **kw}


class TestParsePay(unittest.TestCase):
    def test_formats(self):
        p = parse_pay("Salary $85,000 - $95,000 + super")
        self.assertEqual((p["low"], p["high"], p["unit"]), (85000, 95000, "year"))
        self.assertEqual(parse_pay("$90k + super")["high"], 90000)
        self.assertEqual(parse_pay("$85-95k")["low"], 85000)
        h = parse_pay("$45 per hour")
        self.assertEqual((h["unit"], h["raw_high"]), ("hour", 45))
        self.assertEqual(parse_pay("$40 - $50/hr")["raw_high"], 50)
        self.assertEqual(parse_pay("$400/day")["high"], 400 * 260)
        self.assertEqual(parse_pay("$1,500 per week")["high"], 1500 * 52)

    def test_unit_written_first_wins(self):
        self.assertEqual(parse_pay("$85,000 plus super, 8 hours per day")["unit"], "year")

    def test_not_pay(self):
        for t in ("a $2 million budget", "$2m project", "sign-on bonus of $5,000", "manage a $50,000 budget", "no money here",
                  "$500 allowance", "Level 4, 100 St Georges Tce"):
            self.assertIsNone(parse_pay(t), t)

    def test_bare_amount_needs_a_pay_word_unless_it_is_the_salary_field(self):
        self.assertIsNone(parse_pay("worth $85,000"))
        self.assertEqual(parse_pay("salary of $85,000")["high"], 85000)
        self.assertEqual(parse_pay("$85,000", field=True)["high"], 85000)

    def test_minimum_from_targets_or_intake(self):
        mp = flags.minimum_pay
        self.assertEqual(mp({"ranking": {"min_salary_k": 80}}), 80000)
        self.assertEqual(mp({"ranking": {"min_salary": "$75,000"}}), 75000)
        self.assertEqual(mp({}, {"preferences": {"salary_expectation": "$70,000 - $80,000"}}), 70000)
        self.assertEqual(mp({}, {"preferences": {"salary_expectation": "85k"}}), 85000)
        self.assertEqual(mp({}, {"preferences": {"min_salary": 40}}), 40 * 38 * 52)
        self.assertIsNone(mp({}, {"preferences": {"salary_expectation": "negotiable"}}))
        self.assertIsNone(mp({}, {}))


class TestRules(unittest.TestCase):
    def only(self, j, targets=T, **kw):
        out = check(j, targets, **kw)
        for f in out:
            self.assertIsNone(VISA.search(f), f)
        return out

    def test_normal_ad_has_no_flags_even_if_it_talks_about_visas(self):
        self.assertEqual(self.only(NORMAL), [])
        self.assertEqual(self.only(job(description="Only Australian citizens or permanent residents. No visa sponsorship.")), [])

    def test_pay_below_minimum(self):
        out = self.only(job(salary="$70,000 - $75,000"))
        self.assertEqual(len(out), 1)
        self.assertIn("$75,000", out[0]); self.assertIn("$80,000", out[0])
        self.assertEqual(self.only(job(salary="$70,000 - $85,000")), [])         # the top of the range counts
        self.assertEqual(self.only(job(description="The salary is $60k for this role.")) [0][:9], "Pay tops ")
        self.assertEqual(self.only(job(salary="$60,000"), targets={"tracks": []}), [])   # no minimum known: no flag

    def test_minimum_from_intake(self):
        out = self.only(job(salary="$60,000 - $65,000"), targets={"tracks": []},
                        intake={"preferences": {"salary_expectation": "$75,000"}})
        self.assertIn("below your minimum", out[0])

    def test_hourly_and_minimum_wage(self):
        self.assertEqual(self.only(job(salary="$45 per hour"), targets={}), [])
        out = self.only(job(salary="$20 per hour"), targets={})
        self.assertIn("minimum wage", out[0])
        self.assertIn("minimum wage", self.only(job(description="Pay: $40,000 per annum"), targets={})[0])
        self.assertEqual(self.only(job(description="$40,000 pro rata, part-time"), targets={}), [])
        self.assertIn("minimum wage", self.only(job(description="$120 per day"), targets={})[0])
        self.assertEqual(self.only(job(description="$400/day"), targets={}), [])
        out = self.only(job(salary="$45 per hour"), targets={"ranking": {"min_salary_k": 120}})
        self.assertIn("below your minimum", out[0])

    def test_unpaid_trial_commission_volunteer(self):
        for t in ("This is an unpaid trial for two weeks.", "Unpaid internship, great exposure.", "Start with a trial shift (unpaid).",
                  "Commission only role, uncapped.", "100% commission", "Commission-based only, no base salary."):
            out = self.only(job(description=t))
            self.assertEqual(len(out), 1, t)
            self.assertIn("Unpaid or commission-only", out[0])
        out = self.only(job(title="Coordinator", description="This is a volunteer position with training."))
        self.assertIn("volunteer", out[0])
        self.assertEqual(self.only(job(title="Volunteer Coordinator", description="This is a volunteer position.")), [])
        for t in ("Paid trial shift on Friday.", "Commission on top of a base salary.", "Volunteer experience is a plus.",
                  "You will manage 40 volunteers.", "Paid internship for students."):
            self.assertEqual(self.only(job(description=t)), [], t)

    def test_upfront_fees_and_scams(self):
        for t in ("You will need to pay for training before you start.", "Buy your starter kit ($199).", "A registration fee applies.",
                  "Please send your bank details to get started.", "Interview via WhatsApp only.", "Message us on Telegram to apply.",
                  "Earn $300 per day from home, no experience needed!", "Send resume to jobs.perth@gmail.com",
                  "Email hr_acme@hotmail.com to apply"):
            out = self.only(job(description=t), targets={})
            self.assertEqual(len(out), 1, (t, out))
        for t in ("Our team uses Slack and Teams.", "Apply through the portal; background check paid by us.",
                  "Email careers@acme.com.au", "Earn a competitive salary in a friendly team.", "Work from home two days a week."):
            self.assertEqual(self.only(job(description=t)), [], t)

    def test_hidden_employer_with_vague_pay(self):
        out = self.only(job(company="", description="Our client is a leading firm offering a competitive package."))
        self.assertIn("Employer is hidden", out[0])
        self.assertEqual(self.only(job(company="Confidential", description="Great role.")) [0][:8], "Employer")
        self.assertEqual(self.only(job(company="", description="Our client pays $90,000 - $100,000.")), [])
        self.assertEqual(self.only(job(company="Acme", description="Great role, competitive package.")), [])

    def test_repost_churn(self):
        self.assertEqual(self.only(job(), reposts=3), [])
        self.assertIn("5 times", self.only(job(), reposts=5)[0])

    def test_never_visa_words_whatever_the_ad_says(self):
        nasty = ("Visa sponsorship available. Work rights required. Subclass 482. Pay for training, starter kit, unpaid trial, "
                 "WhatsApp interview, earn $500 per day from home, bob@gmail.com. Citizens only. Our client.")
        out = self.only(job(company="", description=nasty, salary="$10 per hour"))
        self.assertGreaterEqual(len(out), 6)

    def test_deterministic(self):
        j = job(salary="$20 per hour", description="Unpaid trial. Message us on WhatsApp to apply.")
        self.assertEqual(check(j, T), check(dict(j), T))


class TestStored(Base):
    def add(self, key="seek:1", status="prepared", **kw):
        from tracker import add, set_status
        add("ana", {"key": key, "title": "Environmental Officer", "company": "Acme", "url": f"https://x/{key}",
                    "platform": "seek", "track": "main", **kw})
        set_status("ana", key, status)

    def test_set_flags_writes_and_clears_without_history(self):
        from tracker import load, set_flags
        self.add()
        set_flags("ana", "seek:1", ["Unpaid trial."])
        a = load("ana")[0]
        self.assertEqual(a["red_flags"], ["Unpaid trial."])
        self.assertEqual(len(a["history"]), 2)                                  # no extra history entry
        set_flags("ana", "seek:1", [])
        self.assertNotIn("red_flags", load("ana")[0])
        with self.assertRaises(SystemExit):
            set_flags("ana", "seek:nope", [])

    def test_flags_cli_refresh_uses_jobs_db_and_stores(self):
        from jobdb import record_seen
        from tracker import load
        self.add()
        record_seen("ana", [{"key": "seek:1", "platform": "seek", "title": "Environmental Officer", "company": "Acme",
                             "salary": "$18 per hour", "description": "Unpaid trial first."}], "2026-11-01")
        out = flags.refresh("ana", "seek:1")
        self.assertEqual(len(out["seek:1"]), 1)         # description is stored by triage, the salary field is enough here
        self.assertIn("minimum wage", out["seek:1"][0])
        self.assertEqual(load("ana")[0]["red_flags"], out["seek:1"])
        self.assertEqual(list(flags.refresh("ana")), ["seek:1"])

    def test_repost_count_from_jobs_db(self):
        from jobdb import record_seen
        mk = lambda i: {"key": f"seek:{i}", "platform": "seek", "title": "Support Worker", "company": "Care Co"}
        for i, day in enumerate(["2026-10-01", "2026-10-10", "2026-10-20", "2026-11-01"]):
            record_seen("ana", [mk(i)], day)
        self.assertEqual(flags.repost_count("ana", mk(3)), 4)
        self.assertEqual(flags.repost_count("ana", {"key": "seek:9", "title": "Other", "company": "Care Co"}), 0)
        self.assertIn("4 times", flags.check_job("ana", mk(3), {})[0])
        # four ads inside a week is not churn
        for i in range(10, 14):
            record_seen("ana", [{"key": f"seek:{i}", "platform": "seek", "title": "Cook", "company": "Pub"}], "2026-11-01")
        self.assertEqual(flags.repost_count("ana", {"key": "seek:10", "title": "Cook", "company": "Pub"}), 0)

    def test_check_job_never_raises(self):
        self.assertEqual(flags.check_job("ana", {"title": None, "company": "Acme", "description": None}, {"ranking": "broken"}), [])

    def test_report_lists_flags_and_followups(self):
        import followup
        from tracker import set_flags
        import report
        self.add()
        set_flags("ana", "seek:1", ["Unpaid trial.", "Pay tops out at $50."])
        self.add("seek:2", "applied")
        self._age("seek:2", 12)
        followup.draft("ana", "seek:2")
        md = report.build("ana", date.today().isoformat())
        self.assertIn("Red flags, Acme:** Unpaid trial.; Pay tops out at $50.", md)
        self.assertIn("1 follow-up due: drafts ready in the package", md)

    def _age(self, key, days):
        from tracker import load, save
        apps = load("ana")
        for a in apps:
            if a["key"] == key:
                stamp = (date.today() - timedelta(days=days)).isoformat() + "T09:00:00+08:00"
                a["history"][-1]["date"] = stamp
                a["submitted"] = stamp[:10]
        save("ana", apps)


class TestFollowup(TestStored):
    def test_due_date_logic(self):
        import followup
        for k, status, age in (("seek:1", "applied", 10), ("seek:2", "submitted", 20), ("seek:3", "applied", 9),
                               ("seek:4", "interview", 15), ("seek:5", "rejected", 15), ("seek:6", "prepared", 15),
                               ("seek:7", "applied", 31), ("seek:8", "no-response", 15)):
            self.add(k, status)
            self._age(k, age)
        self.assertEqual(sorted(a["key"] for a in followup.due("ana")), ["seek:1", "seek:2"])
        self.assertEqual(sorted(a["key"] for a in followup.due("ana", days=5)), ["seek:1", "seek:2", "seek:3"])
        later = followup.due("ana", today=date.today() + timedelta(days=3))
        self.assertEqual(sorted(a["key"] for a in later), ["seek:1", "seek:2", "seek:3"])
        self.assertEqual(sorted(a["key"] for a in followup.due("ana", today=date.today() + timedelta(days=12))), ["seek:1", "seek:3"])   # seek:2 is past MAX_DAYS

    def test_a_reply_after_applying_removes_it(self):
        import followup
        from tracker import set_status
        self.add("seek:1", "applied")
        self._age("seek:1", 12)
        self.assertEqual(len(followup.due("ana")), 1)
        set_status("ana", "seek:1", "interview")
        self.assertEqual(followup.due("ana"), [])

    def test_draft_content_and_tracker_field(self):
        import followup
        from tracker import load
        intake = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))
        intake.update(name="Ana Perez", contact={"email": "ana@example.com", "phone": ""})
        (self.d / "intake.json").write_text(json.dumps(intake), encoding="utf-8")
        job_dir = self.tmp / "pkg" / "01_Acme_Env"
        job_dir.mkdir(parents=True)
        letter = job_dir / "Ana_Cover_Letter.pdf"
        letter.write_text("x", encoding="utf-8")
        self.add("seek:1", "applied", fit=80)
        from tracker import set_status
        set_status("ana", "seek:1", "applied", letter=str(letter))
        self._age("seek:1", 12)
        sent = (date.today() - timedelta(days=12))
        p = followup.draft("ana", "seek:1")
        self.assertEqual(p, job_dir / "followup.md")
        text = p.read_text(encoding="utf-8")
        for needle in ("Environmental Officer", "Acme", f"{sent.day} {sent:%B %Y}", "Ana Perez", "ana@example.com", "Draft only"):
            self.assertIn(needle, text)
        self.assertIsNone(VISA.search(text))
        a = load("ana")[0]
        self.assertEqual(a["followup_draft"], str(p))
        self.assertEqual(a["status"], "applied")
        self.assertEqual(len(a["history"]), 3)           # drafting added no history entry (add, applied, applied + letter)
        self.assertEqual(followup.draft_all("ana"), [])  # already has a draft
        p.unlink()
        self.assertEqual(followup.draft_all("ana"), [p])

    def test_draft_leaves_out_a_title_with_a_word_the_person_never_mentions(self):
        import followup
        self.add("seek:1", "applied", )
        from tracker import load, save
        apps = load("ana"); apps[0]["title"] = "Visa Sponsorship Officer"; apps[0]["company"] = "Acme"; save("ana", apps)
        self._age("seek:1", 12)
        with mock.patch("prepare.package_dir", return_value=self.tmp / "pk"):
            text = followup.draft("ana", "seek:1").read_text(encoding="utf-8")
        self.assertIsNone(VISA.search(text))
        self.assertIn("the role", text)

    def test_fallback_folder_and_missing_company(self):
        import followup
        self.add("seek:1", "applied", company="")
        self._age("seek:1", 12)
        with mock.patch("prepare.package_dir", return_value=self.tmp / "pk"):
            p = followup.draft("ana", "seek:1")
        self.assertEqual(p.parent.parent, self.tmp / "pk" / "followups")
        self.assertIn("Hello hiring team,", p.read_text(encoding="utf-8"))

    def test_line_for_status_and_report(self):
        import followup
        self.assertEqual(followup.line("ana"), "")
        for k in ("seek:1", "seek:2", "seek:3"):
            self.add(k, "applied")
            self._age(k, 11)
        self.assertEqual(followup.line("ana"), "3 follow-ups due: drafts come with the next daily run")
        with mock.patch("prepare.package_dir", return_value=self.tmp / "pk"):
            followup.draft("ana", "seek:1")
            self.assertIn("1 draft ready in the package", followup.line("ana"))
            followup.draft_all("ana")
        self.assertEqual(followup.line("ana"), "3 follow-ups due: drafts ready in the package")
        from status import summary
        self.assertEqual(summary("ana")["followups"], followup.line("ana"))

    def test_cli_due_and_draft_never_send(self):
        import followup
        self.add("seek:1", "applied")
        self._age("seek:1", 12)
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["followup.py", "ana", "due"]), redirect_stdout(buf):
            followup.main()
        self.assertEqual(json.loads(buf.getvalue())[0]["key"], "seek:1")
        src = (ROOT / "scripts" / "followup.py").read_text(encoding="utf-8")
        for bad in ("smtplib", "urllib", "subprocess", "socket"):
            self.assertNotIn(bad, src)


class TestPrepareWiring(Base):
    def test_package_files_list_the_flags_and_the_tracker_has_them(self):
        import prepare
        from tracker import load
        pkg = self.tmp / "pkg"
        pkg.mkdir()
        items = [{"n": 1, "key": "seek:1", "title": "Officer", "company": "Acme", "url": "https://x", "fit": 70, "dir": "01_Acme",
                  "notes": {"role": "r", "fits": "f", "watch": "—", "how": "h", "prob": "high",
                            "flags": "Unpaid trial.; Pay tops out at $50."}}]
        prepare.write_index(pkg, items, "ana")
        self.assertIn("**Red flags:** Unpaid trial.", (pkg / "SUMMARY.md").read_text(encoding="utf-8"))
        self.assertIn("Red flags: Unpaid trial.", (pkg / "01_Acme" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Red flags: Unpaid trial.", (pkg / "index.html").read_text(encoding="utf-8"))
        items[0]["notes"]["flags"] = ""
        prepare.write_index(pkg, items, "ana")
        self.assertNotIn("Red flags", (pkg / "SUMMARY.md").read_text(encoding="utf-8"))

    def test_prepare_stores_flags_without_changing_the_score(self):
        import prepare
        from common import run_dir, save_json
        from tracker import load
        targets = json.loads((self.d / "targets.json").read_text(encoding="utf-8"))
        targets["tracks"][0].update(title_include=["officer"], keywords={"core": ["gis"], "support": []})
        save_json(self.d / "targets.json", targets)
        (self.d / "docs").mkdir(exist_ok=True)
        save_json(self.d / "docs" / "cover_letter.json", {"paragraphs": {"a": "Hello {{position}}"}})
        save_json(self.d / "docs" / "cv_main.json", {})
        cv = self.d / "docs" / "master" / "Resume.pdf"
        cv.parent.mkdir(parents=True); cv.write_text("pdf", encoding="utf-8")
        targets["tracks"][0]["cv_pdf"] = "docs/master/Resume.pdf"
        save_json(self.d / "targets.json", targets)
        intake = json.loads((self.d / "intake.json").read_text(encoding="utf-8"))
        intake["name"] = "Ana Perez"
        save_json(self.d / "intake.json", intake)
        ad = {"key": "seek:1", "id": "1", "platform": "seek", "title": "GIS Officer", "company": "Acme", "url": "https://x/1",
              "location": "Perth", "track": targets["tracks"][0]["id"], "listed": "", "teaser": "",
              "description": "GIS work. Unpaid trial for two weeks. Message us on WhatsApp to apply."}
        save_json(run_dir("ana") / "shortlist.json", {"shortlist": [ad]})
        with mock.patch.object(prepare, "build", return_value={"ok": True, "pdf": str(self.tmp / "l.pdf"), "problems": []}), \
                mock.patch.object(prepare, "alive", return_value=(None, None)), mock.patch.object(prepare.time, "sleep"), \
                mock.patch.object(prepare, "extract_text", return_value=""), \
                mock.patch.dict("os.environ", {"JOB_PACKAGE_DIR": str(self.tmp / "pk")}):
            with_flags = prepare.prepare("ana", 5)
            plain_score = prepare.score(ad, targets, "ana")[0]
        self.assertEqual(with_flags[0]["fit"], plain_score)
        a = load("ana")[0]
        self.assertEqual(len(a["red_flags"]), 2)
        self.assertIn("Red flags", (self.tmp / "pk" / "ana" / date.today().isoformat() / "SUMMARY.md").read_text(encoding="utf-8"))
        self.assertEqual(a["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
