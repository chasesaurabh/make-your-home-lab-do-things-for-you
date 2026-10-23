"""Separate disposable target store, operation receipts and synthetic artifacts.

Only the two bundled strings are transformed. This is not a backup program.
"""
import json
import os
from pathlib import Path
import sqlite3

from .contracts import ITEMS, POLICY, Rejected, canonical, digest, identifier


def _write(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise Rejected("symlink artifact refused")
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.is_symlink():
        raise Rejected("symlink temporary refused")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Target:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise Rejected("symlink target refused")
        self.db = sqlite3.connect(self.root / "target.sqlite", timeout=3)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS config(id INTEGER PRIMARY KEY CHECK(id=1),
                batch_limit INTEGER NOT NULL, version INTEGER NOT NULL);
            INSERT OR IGNORE INTO config VALUES(1,1,0);
            CREATE TABLE IF NOT EXISTS receipts(op TEXT PRIMARY KEY, proposal TEXT NOT NULL,
                receipt TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def snapshot(self):
        return dict(self.db.execute("SELECT batch_limit,version FROM config WHERE id=1").fetchone())

    def receipt(self, op):
        row = self.db.execute("SELECT receipt FROM receipts WHERE op=?", (identifier(op),)).fetchone()
        return json.loads(row[0]) if row else None

    def apply(self, proposal, now, *, fault=None):
        expected_keys = {"job_id", "operation_id", "target", "field", "value", "before",
                         "target_version", "policy", "expires", "evidence_digest"}
        if set(proposal) != expected_keys or proposal["policy"] != POLICY:
            raise Rejected("unknown target policy or proposal fields")
        if (proposal["target"] != "synthetic-worker" or proposal["field"] != "batch_limit"
                or type(proposal["value"]) is not int or proposal["value"] not in (1, 2, 3, 4)):
            raise Rejected("effect outside fixed policy")
        op = identifier(proposal["operation_id"])
        fingerprint = digest(proposal)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT * FROM receipts WHERE op=?", (op,)).fetchone()
            if existing:
                if existing["proposal"] != fingerprint:
                    raise Rejected("operation id conflict")
                self.db.commit()
                return json.loads(existing["receipt"])
            if now >= proposal["expires"]:
                raise Rejected("target refused expired operation")
            if self.snapshot() != {"batch_limit": proposal["before"], "version": proposal["target_version"]}:
                raise Rejected("target version changed")
            directory = self.root / op
            if directory.exists():
                raise Rejected("unreceipted artifacts require reconciliation")
            directory.mkdir()
            self.db.execute("UPDATE config SET batch_limit=?,version=version+1 WHERE id=1",
                            (proposal["value"],))
            outputs = {}
            for name, content in list(ITEMS.items())[:proposal["value"]]:
                transformed = content.upper()
                _write(directory / name, transformed)
                outputs[name] = {"input_digest": digest(content), "output_digest": digest(transformed)}
            manifest = {"operation_id": op, "outputs": outputs, "count": len(outputs)}
            _write(directory / "manifest.json", canonical(manifest))
            if fault == "before_target_commit":
                os._exit(71)
            receipt = {"operation_id": op, "proposal_digest": fingerprint,
                       "target": self.snapshot(), "manifest_digest": digest(manifest)}
            self.db.execute("INSERT INTO receipts VALUES(?,?,?)", (op, fingerprint, canonical(receipt)))
            self.db.commit()
            if fault == "after_target_commit":
                os._exit(72)
            return receipt
        except Exception:
            self.db.rollback()
            raise

    def verify(self, proposal):
        """Read persisted receipt and actual bytes independently of apply response."""
        op = identifier(proposal["operation_id"])
        receipt = self.receipt(op)
        if not receipt or receipt["proposal_digest"] != digest(proposal):
            raise Rejected("matching target receipt absent")
        directory = self.root / op
        manifest_path = directory / "manifest.json"
        if directory.is_symlink() or manifest_path.is_symlink():
            raise Rejected("symlink evidence refused")
        if manifest_path.stat().st_size > 8192:
            raise Rejected("oversize manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_outputs = {name: {"input_digest": digest(content), "output_digest": digest(content.upper())}
                            for name, content in ITEMS.items()}
        expected = {"operation_id": op, "outputs": expected_outputs, "count": len(ITEMS)}
        if manifest != expected or digest(manifest) != receipt["manifest_digest"]:
            raise Rejected("rehearsal manifest does not prove complete output")
        for name, content in ITEMS.items():
            path = directory / name
            if path.is_symlink() or path.stat().st_size > 4096:
                raise Rejected("unsafe or oversize output")
            if path.read_bytes() != content.upper().encode():
                raise Rejected("rehearsal output differs from expected bytes")
        if receipt["target"] != {"batch_limit": proposal["value"], "version": proposal["target_version"] + 1}:
            raise Rejected("receipt target mismatch")
        return receipt
