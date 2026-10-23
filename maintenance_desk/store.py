"""One-store atomic sandbox; intentionally not an external-action engine."""

import hashlib
import json
import sqlite3


class Rejected(ValueError):
    """The requested transition has no authority or violates a precondition."""


def proposal_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sandbox(
                id INTEGER PRIMARY KEY CHECK(id=1),
                slots INTEGER NOT NULL, version INTEGER NOT NULL);
            INSERT OR IGNORE INTO sandbox VALUES(1,1,0);
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY,
                event_key TEXT NOT NULL UNIQUE,
                proposal TEXT NOT NULL,
                digest TEXT NOT NULL,
                state TEXT NOT NULL,
                approval TEXT,
                receipt TEXT);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def _job(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise Rejected("unknown job")
        return dict(row)

    def target(self):
        return dict(self.db.execute("SELECT slots,version FROM sandbox WHERE id=1").fetchone())

    def submit(self, event_key, slots):
        if not isinstance(event_key, str) or not 1 <= len(event_key) <= 80:
            raise Rejected("bounded nonempty event key required")
        if type(slots) is not int or slots not in (1, 2, 3, 4):
            raise Rejected("only integer worker slots from 1 through 4 are allowed")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute(
                "SELECT * FROM jobs WHERE event_key=?", (event_key,)
            ).fetchone()
            if previous:
                if json.loads(previous["proposal"])["slots"] != slots:
                    raise Rejected("event key reused with different payload")
                self.db.commit()
                return dict(previous)
            target = self.target()
            proposal = json.dumps({
                "target": "synthetic-worker", "slots": slots,
                "before": target["slots"], "version": target["version"],
            }, sort_keys=True, separators=(",", ":"))
            cursor = self.db.execute(
                "INSERT INTO jobs(event_key,proposal,digest,state) VALUES(?,?,?,?)",
                (event_key, proposal, proposal_digest(proposal), "awaiting_approval"),
            )
            self.db.commit()
            return self._job(cursor.lastrowid)
        except Exception:
            self.db.rollback()
            raise

    def approve(self, job_id, digest):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            job = self._job(job_id)
            if job["state"] != "awaiting_approval" or digest != job["digest"]:
                raise Rejected("approval must name the pending exact proposal")
            self.db.execute(
                "UPDATE jobs SET state='ready',approval=? WHERE id=?", (digest, job_id)
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def apply(self, job_id, *, fail_before_commit=False):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            job = self._job(job_id)
            if job["state"] == "succeeded":
                self.db.commit()
                return json.loads(job["receipt"])
            if (job["state"] != "ready" or job["approval"] != job["digest"]
                    or proposal_digest(job["proposal"]) != job["digest"]):
                raise Rejected("exact approval required")
            plan = json.loads(job["proposal"])
            if (set(plan) != {"target", "slots", "before", "version"}
                    or plan["target"] != "synthetic-worker"
                    or type(plan["slots"]) is not int or plan["slots"] not in (1, 2, 3, 4)):
                raise Rejected("proposal outside sandbox policy")
            current = self.target()
            if current != {"slots": plan["before"], "version": plan["version"]}:
                raise Rejected("target changed; create and approve a new proposal")
            self.db.execute(
                "UPDATE sandbox SET slots=?,version=version+1 WHERE id=1", (plan["slots"],)
            )
            observed = self.target()
            if observed != {"slots": plan["slots"], "version": plan["version"] + 1}:
                raise Rejected("verification failed")
            receipt = {"job_id": job_id, "proposal_digest": job["digest"],
                       "verified_target": observed}
            self.db.execute(
                "UPDATE jobs SET state='succeeded',receipt=? WHERE id=?",
                (json.dumps(receipt, sort_keys=True), job_id),
            )
            if fail_before_commit:
                raise RuntimeError("injected failure before local atomic commit")
            self.db.commit()
            return receipt
        except Exception:
            self.db.rollback()
            raise
