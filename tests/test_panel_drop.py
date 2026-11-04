"""Panel: dropping an ad from the board, the 'Dropped by you' list and Restore (skipped back to prepared)."""
import datetime
import json
import os
import sys
import threading
import unittest
import unittest.mock
import urllib.request

from test_core import Base, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


class TestDroppedByYou(Base):
    def seed(self):
        from tracker import add, load, save, set_status
        for i in range(1, 6):
            add("ana", {"key": f"seek:{i}", "title": f"Role {i}", "company": f"Co {i}", "url": f"u{i}", "platform": "seek", "fit": 50 + i})
        set_status("ana", "seek:1", "skipped", note="from the panel")
        set_status("ana", "seek:2", "skipped", note="too far from home")
        set_status("ana", "seek:3", "skipped", reason="rescued: waiting for its package")      # what the rescue flow writes
        set_status("ana", "seek:4", "skipped", note="from the panel")
        apps = load("ana")
        next(a for a in apps if a["key"] == "seek:4")["history"][-1]["date"] = "2020-01-01T09:00:00"      # long ago
        save("ana", apps)

    def test_list_excludes_rescued_and_old_and_is_newest_first(self):
        import panel
        self.seed()
        with unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
            d = panel.data("ana")
        self.assertEqual(sorted(x["key"] for x in d["dropped_by_you"]), ["seek:1", "seek:2"])
        mine = {x["key"]: x for x in d["dropped_by_you"]}
        self.assertEqual((mine["seek:1"]["note"], mine["seek:2"]["note"]), ("", "too far from home"))
        self.assertEqual(mine["seek:1"]["day"], datetime.date.today().isoformat())
        self.assertEqual(mine["seek:1"]["fit"], 51)
        self.assertEqual([a["key"] for a in d["apps"]], ["seek:5"])                       # dropped ones are off the board
        whens = [x["when"] for x in d["dropped_by_you"]]
        self.assertEqual(whens, sorted(whens, reverse=True))

    def test_rescue_then_user_drop_counts_as_a_drop(self):
        import panel
        from tracker import add, set_status
        add("ana", {"key": "seek:9", "title": "R", "url": "u", "platform": "seek"})
        set_status("ana", "seek:9", "skipped", reason="rescued: waiting for its package")
        set_status("ana", "seek:9", "prepared")
        set_status("ana", "seek:9", "skipped", note="from the panel")
        with unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
            self.assertEqual([x["key"] for x in panel.data("ana")["dropped_by_you"]], ["seek:9"])

    def test_post_status_skipped_then_restore_prepared(self):
        import panel
        from http.server import ThreadingHTTPServer
        from tracker import add, load
        add("ana", {"key": "seek:1", "title": "Role 1", "url": "u", "platform": "seek", "fit": 70})
        from tracker import set_status
        set_status("ana", "seek:1", "prepared")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}"

        def post(status):
            body = json.dumps({"slug": "ana", "key": "seek:1", "status": status, "note": "from the test"}).encode()
            req = urllib.request.Request(url + "/status", data=body, headers={"X-Panel-Token": panel.TOKEN})
            return json.loads(urllib.request.urlopen(req).read())

        try:
            with unittest.mock.patch.dict(os.environ, {"JOB_PACKAGE_DIR": str(self.tmp / "pkgs")}):
                self.assertEqual(post("skipped"), {"ok": True, "status": "skipped"})
                self.assertEqual([a["key"] for a in panel.data("ana")["dropped_by_you"]], ["seek:1"])
                self.assertEqual(panel.data("ana")["apps"], [])
                self.assertEqual(post("prepared"), {"ok": True, "status": "prepared"})      # Restore / Undo
                d = panel.data("ana")
                self.assertEqual(d["dropped_by_you"], [])
                self.assertEqual([(a["key"], a["col"]) for a in d["apps"]], [("seek:1", "todo")])
        finally:
            srv.shutdown(); srv.server_close()
        self.assertEqual([h["status"] for h in load("ana")[0]["history"]][-3:], ["prepared", "skipped", "prepared"])
        self.assertEqual(load("ana")[0]["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
