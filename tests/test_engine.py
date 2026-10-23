import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from maintenance_desk.cli import board
from maintenance_desk.contracts import POLICY, Rejected, digest, tool
from maintenance_desk.engine import Desk
from maintenance_desk.provider import LocalProvider


class Clock:
    def __init__(self):
        self.now = 1800000000.0
    def __call__(self):
        return self.now


class Scripted:
    def __init__(self, actions):
        self.actions = iter(actions)
    def decide(self, case, observations, remaining):
        return {"tool": next(self.actions), "reason": "synthetic test decision"}, {"usage": None, "elapsed": 0, "retries": 0}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "desk"
        self.clock = Clock()
        self.desk = Desk(self.root, clock=self.clock)

    def tearDown(self):
        self.desk.close()
        self.temp.cleanup()

    def job(self, key="one", case="capacity", mode="baseline", deadline=600):
        return self.desk.admit(key, {"source": "fixture", "case": case, "mode": mode}, deadline_seconds=deadline)

    def ready(self, key="one"):
        job = self.job(key)
        self.desk.inspect(job)
        self.desk.approve(job, digest(self.desk.get(job)["proposal"]))
        return job

    def test_complete_workflow_verifies_actual_outputs(self):
        job = self.ready()
        result = self.desk.apply(job)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["kind"], "effect_verified")
        output = self.root / "target" / ("op-"+job) / "alpha.txt"
        self.assertEqual(output.read_text(), "SYNTHETIC ALPHA\n")
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_duplicate_submit_and_conflicting_payload(self):
        job = self.job()
        self.assertEqual(job, self.job())
        with self.assertRaises(Rejected):
            self.job(case="healthy")
        self.assertEqual(len(self.desk.jobs()), 1)

    def test_queue_capacity_refuses_admission(self):
        self.desk.capacity = 1
        self.job()
        with self.assertRaises(Rejected):
            self.job("two")

    def test_event_shape_and_identifier(self):
        with self.assertRaises(Rejected):
            self.desk.admit("../escape", {"source": "fixture", "case": "capacity", "mode": "baseline"})
        with self.assertRaises(Rejected):
            self.desk.admit("valid", {"source": "fixture", "case": "capacity", "mode": "baseline", "command": "anything"})

    def test_apply_requires_approval(self):
        job = self.job()
        self.desk.inspect(job)
        with self.assertRaises(Rejected):
            self.desk.apply(job)
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_wrong_digest_and_model_actor(self):
        job = self.job()
        self.desk.inspect(job)
        with self.assertRaises(Rejected):
            self.desk.approve(job, "wrong")
        with self.assertRaises(Rejected):
            self.desk.approve(job, digest(self.desk.get(job)["proposal"]), actor="model")

    def test_expiry_and_revocation(self):
        job = self.ready()
        self.desk.revoke(job)
        with self.assertRaises(Rejected):
            self.desk.apply(job)
        self.clock.now += 301
        with self.assertRaises(Rejected):
            self.desk.approve(job, digest(self.desk.get(job)["proposal"]))

    def test_expiry_after_approval_blocks_effect(self):
        job = self.ready()
        self.clock.now += 301
        result = self.desk.apply(job)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_evidence_changed_after_approval(self):
        job = self.ready()
        self.desk.db.execute("UPDATE jobs SET evidence='{}' WHERE id=?", (job,))
        self.assertEqual(self.desk.apply(job)["state"], "failed")
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_duplicate_apply_after_restart_returns_receipt(self):
        job = self.ready()
        original = self.desk.apply(job)["result"]
        self.desk.close()
        self.desk = Desk(self.root, clock=self.clock)
        self.assertEqual(self.desk.apply(job)["result"], original)
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_stale_target_blocks_second_job(self):
        first, second = self.ready(), self.ready("two")
        self.desk.apply(first)
        self.assertEqual(self.desk.apply(second)["state"], "needs_reconciliation")
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_cancel_before_effect(self):
        job = self.ready()
        self.desk.cancel(job)
        with self.assertRaises(Rejected):
            self.desk.apply(job)
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_read_only_healthy_and_escalations(self):
        for case, expected in (("healthy", "succeeded"), ("stale", "failed"),
                               ("conflict", "failed"), ("missing_runbook", "failed")):
            with self.subTest(case=case):
                job = self.job(case, case)
                self.assertEqual(self.desk.inspect(job)["state"], expected)
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_injected_incident_does_not_change_policy(self):
        job = self.job(case="injected")
        result = self.desk.inspect(job)
        self.assertEqual(result["state"], "awaiting_approval")
        self.assertEqual(result["proposal"]["field"], "batch_limit")
        self.assertEqual(result["proposal"]["policy"], POLICY)
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_agent_requires_explicit_provider(self):
        job = self.job(mode="agent")
        with self.assertRaises(Rejected):
            self.desk.inspect(job)

    def test_bounded_scripted_agent_can_select_observations(self):
        job = self.job(mode="agent")
        result = self.desk.inspect(job, Scripted(["read_diagnostic", "find_runbook", "finish"]))
        self.assertEqual(result["state"], "awaiting_approval")
        self.assertEqual(len(result["trace"]), 3)

    def test_agent_repeat_and_missing_evidence_fail(self):
        for index, sequence in enumerate((["read_diagnostic", "read_diagnostic"], ["finish"])):
            job = self.job("agent"+str(index), mode="agent")
            self.assertEqual(self.desk.inspect(job, Scripted(sequence))["state"], "failed")
        self.assertEqual(self.desk.target.snapshot()["version"], 0)

    def test_agent_escalation_respected_after_evidence(self):
        job = self.job(mode="agent")
        result = self.desk.inspect(job, Scripted(["read_diagnostic", "find_runbook", "escalate"]))
        self.assertEqual(result["state"], "failed")
        self.assertIsNone(result["proposal"])

    def test_unknown_tool_and_remote_provider_refused(self):
        with self.assertRaises(Rejected):
            tool("shell", "capacity")
        for endpoint in ("https://example.com/v1", "http://127.0.0.1@evil.example/v1",
                         "http://127.0.0.1/v1?token=x"):
            with self.subTest(endpoint=endpoint), self.assertRaises(Rejected):
                LocalProvider(endpoint, "test")

    def test_deadline_before_claim(self):
        job = self.job(deadline=1)
        self.clock.now += 2
        self.assertEqual(self.desk.inspect(job)["state"], "failed")

    def test_tick_deduplicates_and_skips_missed_periods(self):
        first = self.desk.tick("hourly")
        self.assertEqual(first, self.desk.tick("hourly"))
        self.clock.now += 3600 * 10
        second = self.desk.tick("hourly")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.desk.jobs()), 2)

    def test_second_connection_cannot_claim_live_job(self):
        job = self.job()
        self.desk._claim(job, {"queued"}, "inspecting")
        other = Desk(self.root, clock=self.clock)
        try:
            with self.assertRaises(Rejected):
                other._claim(job, {"queued"}, "inspecting")
        finally:
            other.close()

    def test_expired_read_lease_can_resume(self):
        job = self.job()
        owner = self.desk._claim(job, {"queued"}, "inspecting")
        self.clock.now += 91
        self.desk.recover()
        self.assertEqual(self.desk.get(job)["state"], "queued")
        with self.assertRaises(Rejected):
            self.desk._owned(job, owner)
        self.assertEqual(self.desk.inspect(job)["state"], "awaiting_approval")

    def test_job_board_escapes_untrusted_text(self):
        job = self.job()
        self.desk.db.execute("UPDATE jobs SET error=? WHERE id=?", ("<script>alert(1)</script>", job))
        rendered = board(self.desk)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def crash(self, fault):
        job = self.ready()
        code = ("from maintenance_desk.engine import Desk; "
                f"d=Desk({str(self.root)!r},clock=lambda:1800000000.0); "
                f"d.apply({job!r},fault={fault!r})")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 71 if fault == "before_target_commit" else 72, result.stderr.decode())
        self.clock.now += 91
        return job

    def test_process_crash_after_effect_reconciles_without_reapply(self):
        job = self.crash("after_target_commit")
        self.assertEqual(self.desk.get(job)["state"], "applying")
        self.desk.recover()
        self.assertEqual(self.desk.get(job)["state"], "succeeded")
        self.assertEqual(self.desk.target.snapshot()["version"], 1)
        self.desk.recover()
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_crash_before_target_receipt_stays_unresolved(self):
        job = self.crash("before_target_commit")
        self.desk.recover()
        self.assertEqual(self.desk.get(job)["state"], "needs_reconciliation")
        self.assertEqual(self.desk.target.snapshot()["version"], 0)
        self.assertIsNone(self.desk.target.receipt("op-"+job))

    def test_cancel_after_effect_retains_truth(self):
        job = self.crash("after_target_commit")
        self.desk.cancel(job)
        self.desk.recover()
        result = self.desk.get(job)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["result"]["kind"], "effect_verified_after_cancel")
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_tampered_output_never_becomes_success(self):
        job = self.crash("after_target_commit")
        output = self.root / "target" / ("op-"+job) / "alpha.txt"
        output.write_text("incorrect", encoding="utf-8")
        self.desk.recover()
        self.assertEqual(self.desk.get(job)["state"], "needs_reconciliation")
        self.assertIsNone(self.desk.get(job)["result"])

    def test_receipt_reconciliation_after_deadline_is_observation_only(self):
        job = self.crash("after_target_commit")
        self.clock.now += 1000
        self.desk.recover()
        self.assertEqual(self.desk.get(job)["state"], "succeeded")
        self.assertEqual(self.desk.target.snapshot()["version"], 1)

    def test_two_processes_have_one_claim_winner(self):
        job = self.job()
        code = ("from maintenance_desk.engine import Desk; from maintenance_desk.contracts import Rejected; "
                f"d=Desk({str(self.root)!r},clock=lambda:1800000000.0)\n"
                "try:\n"
                f" d._claim({job!r},{{'queued'}},'inspecting'); print('claimed')\n"
                "except Rejected: print('unavailable')\n"
                "finally: d.close()\n")
        processes=[subprocess.Popen([sys.executable,"-c",code],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        outputs=[process.communicate(timeout=15) for process in processes]
        self.assertTrue(all(process.returncode == 0 for process in processes),outputs)
        self.assertEqual(sorted(out.decode().strip() for out,_ in outputs),["claimed","unavailable"])


if __name__ == "__main__":
    unittest.main()
