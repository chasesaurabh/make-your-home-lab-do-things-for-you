"""Durable one-host job engine. Separate target writes require reconciliation."""
import contextlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import POLICY, TERMINAL, Rejected, canonical, digest, event_payload, identifier, interpret
from .provider import inspect
from .target import Target


class Desk:
    def __init__(self, root, *, clock=time.time, capacity=128):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise Rejected("symlink data root refused")
        self.clock, self.capacity = clock, capacity
        self.db = sqlite3.connect(self.root / "desk.sqlite", timeout=3, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, deadline REAL NOT NULL,
                owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                evidence TEXT, trace TEXT, proposal TEXT, approval TEXT,
                intent TEXT, result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
                at REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        self.target = Target(self.root / "target")

    def close(self):
        self.target.close()
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def log(self, job, kind, detail):
        self.db.execute("INSERT INTO events(job,at,kind,detail) VALUES(?,?,?,?)",
                        (job, self.clock(), kind, canonical(detail)))

    def get(self, job):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if not row:
            raise Rejected("unknown job")
        data = dict(row)
        for key in ("payload", "evidence", "trace", "proposal", "approval", "intent", "result"):
            data[key] = json.loads(data[key]) if data[key] else None
        return data

    def jobs(self):
        return [self.get(row[0]) for row in self.db.execute("SELECT id FROM jobs ORDER BY created,id")]

    def timeline(self, job):
        self.get(job)
        return [{**dict(row), "detail": json.loads(row["detail"])} for row in self.db.execute(
            "SELECT * FROM events WHERE job=? ORDER BY seq", (job,))]

    def admit(self, key, payload, *, deadline_seconds=600):
        identifier(key)
        event_payload(payload)
        if not 1 <= deadline_seconds <= 86400:
            raise Rejected("deadline outside 1..86400 seconds")
        with self.transaction():
            previous = self.db.execute("SELECT id,payload FROM jobs WHERE event_key=?", (key,)).fetchone()
            if previous:
                if previous["payload"] != canonical(payload):
                    raise Rejected("event key conflict")
                return previous["id"]
            active = self.db.execute("SELECT count(*) FROM jobs WHERE state NOT IN ('succeeded','failed','cancelled')").fetchone()[0]
            if active >= self.capacity:
                raise Rejected("queue capacity reached; admission refused")
            job, now = uuid.uuid4().hex, self.clock()
            self.db.execute("INSERT INTO jobs(id,event_key,payload,state,created,deadline) VALUES(?,?,?,'queued',?,?)",
                            (job, key, canonical(payload), now, now+deadline_seconds))
            self.log(job, "admitted", {"key": key, "payload_digest": digest(payload)})
        return job

    def tick(self, schedule, *, period=3600, case="capacity", mode="baseline"):
        identifier(schedule)
        if type(period) is not int or not 60 <= period <= 604800:
            raise Rejected("period must be integer seconds from 60 through 604800")
        # Explicit latest-bucket policy: no hidden catch-up flood; UTC epoch intervals.
        bucket = int(self.clock() // period)
        return self.admit(f"{schedule[:40]}-{period}-{bucket}",
                          {"source": "schedule", "case": case, "mode": mode})

    def _claim(self, job, expected, next_state):
        owner = uuid.uuid4().hex
        with self.transaction():
            current = self.get(job)
            if current["state"] not in expected:
                raise Rejected("job is not available for this step")
            if self.clock() >= current["deadline"]:
                self.db.execute("UPDATE jobs SET state='failed',error='job deadline exceeded' WHERE id=?", (job,))
                self.log(job, "deadline", {})
                return None
            if current["attempts"] >= 3:
                self.db.execute("UPDATE jobs SET state='failed',error='attempt cap exceeded' WHERE id=?", (job,))
                self.log(job, "attempt_cap", {})
                return None
            self.db.execute("UPDATE jobs SET state=?,owner=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                            (next_state, owner, self.clock()+90, job))
            self.log(job, "claimed", {"owner": owner, "step": next_state})
        return owner

    def _owned(self, job, owner):
        current = self.get(job)
        if current["owner"] != owner or current["state"] in TERMINAL or self.clock() >= current["lease_until"]:
            raise Rejected("worker no longer owns a live lease")
        return current

    def inspect(self, job, provider=None):
        current = self.get(job)
        if current["payload"]["mode"] == "agent" and provider is None:
            raise Rejected("agent mode requires an explicit live or test provider")
        owner = self._claim(job, {"queued"}, "inspecting")
        if not owner:
            return self.get(job)
        try:
            current = self.get(job)
            observations, trace = inspect(current["payload"]["case"], provider,
                                          remaining=min(60, current["deadline"]-self.clock()))
            decision = interpret(observations)
            if trace and trace[-1]["decision"]["tool"] == "escalate":
                decision = "escalate"
            with self.transaction():
                current = self._owned(job, owner)
                if self.clock() >= current["deadline"]:
                    raise TimeoutError("job deadline reached during inspection")
                self.db.execute("UPDATE jobs SET evidence=?,trace=? WHERE id=?",
                                (canonical(observations), canonical(trace), job))
                if decision == "proposal":
                    target = self.target.snapshot()
                    proposal = {"job_id": job, "operation_id": "op-"+job,
                                "target": "synthetic-worker", "field": "batch_limit", "value": 2,
                                "before": target["batch_limit"], "target_version": target["version"],
                                "policy": POLICY, "expires": min(current["deadline"], self.clock()+300),
                                "evidence_digest": digest(observations)}
                    self.db.execute("UPDATE jobs SET state='awaiting_approval',proposal=?,owner=NULL,lease_until=NULL WHERE id=?",
                                    (canonical(proposal), job))
                else:
                    state = "succeeded" if decision == "digest" else "failed"
                    result = {"kind": "read_only_digest" if decision == "digest" else "escalated",
                              "evidence_digest": digest(observations)}
                    self.db.execute("UPDATE jobs SET state=?,result=?,owner=NULL,lease_until=NULL WHERE id=?",
                                    (state, canonical(result), job))
                self.log(job, "inspection", {"decision": decision, "evidence_digest": digest(observations),
                                              "model_calls": len(trace)})
        except Exception as error:
            if hasattr(error, "observations"):
                with self.transaction():
                    if self.get(job)["owner"] == owner:
                        self.db.execute("UPDATE jobs SET evidence=?,trace=? WHERE id=?",
                                        (canonical(error.observations), canonical(error.trace), job))
            self._failure(job, owner, type(error).__name__ + ": " + str(error)[:200])
        return self.get(job)

    def approve(self, job, fingerprint, *, actor="operator"):
        # Actor is an OS-operator audit label, not multiuser authentication.
        identifier(actor)
        if actor in ("agent", "model", "worker"):
            raise Rejected("model/worker cannot issue an operator grant")
        with self.transaction():
            current = self.get(job)
            proposal = current["proposal"]
            if current["state"] != "awaiting_approval" or not proposal or digest(proposal) != fingerprint:
                raise Rejected("approval does not match pending proposal")
            if self.clock() >= min(proposal["expires"], current["deadline"]):
                raise Rejected("approval window expired")
            if self.target.snapshot() != {"batch_limit": proposal["before"], "version": proposal["target_version"]}:
                raise Rejected("target stale; submit a new job")
            approval = {"actor": actor, "at": self.clock(), "digest": fingerprint, "policy": POLICY}
            self.db.execute("UPDATE jobs SET state='ready',approval=? WHERE id=?", (canonical(approval), job))
            self.log(job, "approved", approval)

    def revoke(self, job):
        with self.transaction():
            if self.get(job)["state"] != "ready":
                raise Rejected("only an unstarted approval can be revoked")
            self.db.execute("UPDATE jobs SET state='awaiting_approval',approval=NULL WHERE id=?", (job,))
            self.log(job, "revoked", {})

    def cancel(self, job):
        with self.transaction():
            current = self.get(job)
            if current["state"] in TERMINAL:
                raise Rejected("terminal job cannot be cancelled")
            if current["state"] in ("applying", "verifying", "needs_reconciliation"):
                self.db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job,))
                self.log(job, "cancel_requested", {"warning": "effect may already exist; reconcile first"})
            else:
                self.db.execute("UPDATE jobs SET state='cancelled',approval=NULL,owner=NULL,lease_until=NULL WHERE id=?", (job,))
                self.log(job, "cancelled_before_effect", {})

    def _failure(self, job, owner, message, *, uncertain=False):
        with self.transaction():
            current = self.get(job)
            if current["owner"] != owner or current["state"] in TERMINAL:
                return
            state = "needs_reconciliation" if uncertain else "failed"
            self.db.execute("UPDATE jobs SET state=?,error=?,owner=NULL,lease_until=NULL WHERE id=?", (state, message, job))
            self.log(job, "uncertain" if uncertain else "failed", {"error": message})

    def apply(self, job, *, fault=None):
        if self.get(job)["state"] == "succeeded":
            return self.get(job)
        owner = self._claim(job, {"ready"}, "applying")
        if not owner:
            return self.get(job)
        intent_written = False
        try:
            with self.transaction():
                current = self._owned(job, owner)
                proposal, approval = current["proposal"], current["approval"]
                if not approval or approval["digest"] != digest(proposal) or approval["policy"] != POLICY:
                    raise Rejected("operation grant invalid")
                if self.clock() >= proposal["expires"] or proposal["policy"] != POLICY:
                    raise Rejected("grant expired or policy changed")
                if digest(current["evidence"]) != proposal["evidence_digest"]:
                    raise Rejected("evidence changed after proposal")
                self.db.execute("UPDATE jobs SET intent=? WHERE id=?", (canonical(proposal), job))
                self.log(job, "intent_persisted", {"operation_id": proposal["operation_id"], "digest": digest(proposal)})
            intent_written = True
            self.target.apply(proposal, self.clock(), fault=fault)
            with self.transaction():
                self._owned(job, owner)
                self.db.execute("UPDATE jobs SET state='verifying' WHERE id=?", (job,))
                self.log(job, "verifying", {})
            return self._verify(job, owner)
        except Exception as error:
            self._failure(job, owner, type(error).__name__ + ": " + str(error)[:200], uncertain=intent_written)
        return self.get(job)

    def _verify(self, job, owner):
        try:
            current = self.get(job)
            receipt = self.target.verify(current["intent"])
            with self.transaction():
                current = self._owned(job, owner)
                state = "cancelled" if current["cancel_requested"] else "succeeded"
                result = {"kind": "effect_verified_after_cancel" if current["cancel_requested"] else "effect_verified",
                          "receipt": receipt}
                self.db.execute("UPDATE jobs SET state=?,result=?,error=NULL,owner=NULL,lease_until=NULL WHERE id=?",
                                (state, canonical(result), job))
                self.log(job, "verified", {"state": state, "receipt_digest": digest(receipt)})
        except Exception as error:
            self._failure(job, owner, "verification: " + str(error)[:200], uncertain=True)
        return self.get(job)

    def recover(self):
        """Recover expired workers; never issue a new target effect here."""
        recovered = []
        for job in self.jobs():
            if job["state"] in ("inspecting", "applying", "verifying"):
                if job["lease_until"] and self.clock() < job["lease_until"]:
                    continue
                with self.transaction():
                    current = self.get(job["id"])
                    if current["state"] != job["state"] or (current["lease_until"] and self.clock() < current["lease_until"]):
                        continue
                    state = "needs_reconciliation" if current["intent"] else "queued"
                    self.db.execute("UPDATE jobs SET state=?,owner=NULL,lease_until=NULL WHERE id=?", (state, job["id"]))
                    self.log(job["id"], "lease_expired", {"next": state})
                job = self.get(job["id"])
            if job["state"] == "needs_reconciliation":
                if not job["intent"] or not self.target.receipt(job["intent"]["operation_id"]):
                    with self.transaction():
                        self.log(job["id"], "reconciliation_unresolved", {"action": "operator inspection required; no retry"})
                    recovered.append(self.get(job["id"]))
                    continue
                # A committed target receipt justifies verification, even after grant/deadline expiry.
                owner = uuid.uuid4().hex
                with self.transaction():
                    current = self.get(job["id"])
                    if current["state"] != "needs_reconciliation":
                        continue
                    self.db.execute("UPDATE jobs SET state='verifying',owner=?,lease_until=? WHERE id=?",
                                    (owner, self.clock()+90, job["id"]))
                    self.log(job["id"], "receipt_found", {"operation_id": job["intent"]["operation_id"]})
                recovered.append(self._verify(job["id"], owner))
        return recovered
