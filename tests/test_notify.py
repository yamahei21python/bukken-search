"""notify._deliver のテスト (送信してから記録する規約の保証)。"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import notify


def _mem_con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE notifications("
                "listing_id INTEGER, kind TEXT, message TEXT)")
    return con


class TestDeliver(unittest.TestCase):
    def test_records_only_after_send(self):
        con = _mem_con()
        sent_msgs = []
        sent = notify._deliver([(1, "new", "m1"), (2, "new", "m2")],
                               sender=sent_msgs.append, con=con)
        self.assertEqual(sent, 2)
        self.assertEqual(sent_msgs, ["m1", "m2"])
        rows = con.execute("SELECT listing_id,kind,message FROM notifications"
                           " ORDER BY listing_id").fetchall()
        self.assertEqual(rows, [(1, "new", "m1"), (2, "new", "m2")])

    def test_failure_is_not_recorded(self):
        con = _mem_con()

        def boom(_msg):
            raise RuntimeError("webhook down")

        sent = notify._deliver([(1, "new", "m1")], sender=boom, con=con)
        self.assertEqual(sent, 0)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)

    def test_partial_failure_keeps_successes(self):
        con = _mem_con()
        state = {"n": 0}

        def flaky(_msg):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("first fails")

        sent = notify._deliver([(1, "new", "m1"), (2, "new", "m2")],
                               sender=flaky, con=con)
        self.assertEqual(sent, 1)
        rows = con.execute("SELECT listing_id FROM notifications").fetchall()
        self.assertEqual(rows, [(2,)])


if __name__ == "__main__":
    unittest.main()
