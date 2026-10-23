import json
import tempfile
import unittest
from pathlib import Path

from maintenance_desk.store import Rejected, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "sandbox.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def job(self, key="event-1", slots=2):
        return self.store.submit(key, slots)

    def test_duplicate_event_has_one_job(self):
        job = self.job()
        self.assertEqual(self.job()["id"], job["id"])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_conflicting_event_cannot_change_target(self):
        self.job()
        with self.assertRaises(Rejected):
            self.job(slots=3)
        self.assertEqual(self.store.target(), {"slots": 1, "version": 0})

    def test_without_approval_cannot_act(self):
        job = self.job()
        with self.assertRaises(Rejected):
            self.store.apply(job["id"])
        self.assertEqual(self.store.target()["version"], 0)

    def test_approval_is_exact(self):
        job = self.job()
        with self.assertRaises(Rejected):
            self.store.approve(job["id"], "wrong-digest")
        self.assertEqual(self.store._job(job["id"])["state"], "awaiting_approval")

    def test_approval_survives_reopen(self):
        job = self.job()
        self.store.approve(job["id"], job["digest"])
        self.store.close()
        self.store = Store(self.path)
        result = self.store.apply(job["id"])
        self.assertEqual(result["verified_target"], {"slots": 2, "version": 1})

    def test_repeated_apply_does_not_repeat_effect(self):
        job = self.job()
        self.store.approve(job["id"], job["digest"])
        receipt = self.store.apply(job["id"])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(receipt, self.store.apply(job["id"]))
        self.assertEqual(self.store.target()["version"], 1)

    def test_stale_target_cannot_act(self):
        first = self.job()
        second = self.job("event-2", 3)
        for job in (first, second):
            self.store.approve(job["id"], job["digest"])
        self.store.apply(first["id"])
        with self.assertRaises(Rejected):
            self.store.apply(second["id"])
        self.assertEqual(self.store.target(), {"slots": 2, "version": 1})

    def test_mutated_proposal_invalidates_approval(self):
        job = self.job()
        self.store.approve(job["id"], job["digest"])
        plan = json.loads(job["proposal"])
        plan["slots"] = 3
        self.store.db.execute("UPDATE jobs SET proposal=? WHERE id=?", (json.dumps(plan), job["id"]))
        self.store.db.commit()
        with self.assertRaises(Rejected):
            self.store.apply(job["id"])
        self.assertEqual(self.store.target()["version"], 0)

    def test_failure_before_commit_has_no_partial_effect(self):
        job = self.job()
        self.store.approve(job["id"], job["digest"])
        with self.assertRaises(RuntimeError):
            self.store.apply(job["id"], fail_before_commit=True)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.target(), {"slots": 1, "version": 0})
        self.assertIsNone(self.store._job(job["id"])["receipt"])
        self.assertEqual(self.store.apply(job["id"])["verified_target"]["version"], 1)

    def test_policy_rejects_boolean_and_out_of_range(self):
        for bad in (True, 0, 5, "2", 2.0):
            with self.subTest(bad=bad), self.assertRaises(Rejected):
                self.job(slots=bad)
        self.assertEqual(self.store.target()["version"], 0)

    def test_unknown_job_rejected(self):
        with self.assertRaises(Rejected):
            self.store.apply(999)


if __name__ == "__main__":
    unittest.main()
