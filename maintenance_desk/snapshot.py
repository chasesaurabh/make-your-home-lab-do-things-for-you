"""Explicit OFFLINE snapshots. Stop every worker and board before calling.

This file copy protocol does not establish atomicity against other processes.
Never restore over an existing installation; restored approvals are revoked.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile

from .contracts import Rejected, canonical
from .engine import Desk


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise Rejected("snapshot requires a new directory outside the data root")
    if not (source / "desk.sqlite").is_file() or not (source / "target/target.sqlite").is_file():
        raise Rejected("not a complete application data directory")
    _validate_databases(source)
    desk = Desk(source)
    try:
        if any(job["state"] in ("inspecting", "applying", "verifying") for job in desk.jobs()):
            raise Rejected("resolve active workers before offline snapshot")
    finally:
        desk.close()
    files = {}
    for path in source.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise Rejected("snapshot refuses links")
        if path.is_file():
            if path.name.endswith(("-journal", "-wal", "-shm", ".tmp")):
                raise Rejected("live or incomplete files present; stop and reconcile first")
            relative = path.relative_to(source).as_posix()
            files[relative] = checksum(path)
    if "desk.sqlite" not in files or "target/target.sqlite" not in files:
        raise Rejected("not a complete application data directory")
    destination.mkdir(parents=True)
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        if checksum(target) != files[relative]:
            raise Rejected("source changed during offline snapshot")
    (destination / "snapshot.json").write_text(canonical({"schema": 1, "files": files}), encoding="utf-8")
    return {"files": len(files), "scope": "offline only; other processes must be stopped"}


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise Rejected("restore requires a new data directory")
    manifest = json.loads((source / "snapshot.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "files"} or type(manifest.get("schema")) is not int or manifest["schema"] != 1 or not isinstance(manifest.get("files"), dict):
        raise Rejected("unknown snapshot format")
    if not {"desk.sqlite", "target/target.sqlite"}.issubset(manifest["files"]):
        raise Rejected("snapshot is missing required application databases")
    for relative, expected in manifest["files"].items():
        if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
                or PurePosixPath(relative).as_posix() != relative
                or any(part in ("..", ".") for part in PurePosixPath(relative).parts)
                or relative == "snapshot.json"
                or not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected)):
            raise Rejected("invalid snapshot entry")
        path = source / relative
        if Path(relative).is_absolute() or not path.resolve().is_relative_to(source) or path.is_symlink():
            raise Rejected("snapshot path escape")
        if not path.is_file() or checksum(path) != expected:
            raise Rejected("snapshot digest mismatch")
    actual = set()
    for path in source.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise Rejected("snapshot refuses links")
        if path.is_file() and path.relative_to(source).as_posix() != "snapshot.json":
            actual.add(path.relative_to(source).as_posix())
    if actual != set(manifest["files"]):
        raise Rejected("snapshot inventory is incomplete")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Validate a private copy before publishing the restored directory. Source
    # checks alone cannot detect a changed file between validation and copy.
    with tempfile.TemporaryDirectory(prefix="desk-restore-", dir=destination.parent) as temp:
        staging = Path(temp) / "data"
        staging.mkdir()
        for relative, expected in manifest["files"].items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
            if checksum(target) != expected:
                raise Rejected("snapshot changed during restore")
        _validate_databases(staging)
        desk = Desk(staging)
        try:
            for job in desk.jobs():
                if job["state"] in ("inspecting", "applying", "verifying"):
                    raise Rejected("snapshot contains an active worker")
                if job["intent"] and (job["state"] == "succeeded" or
                        (job["result"] or {}).get("kind") == "effect_verified_after_cancel"):
                    desk.target.verify(job["intent"])
            # Restoration changes operating context. Never revive an old grant.
            with desk.transaction():
                for job in desk.jobs():
                    if job["state"] == "ready":
                        desk.db.execute("UPDATE jobs SET state='awaiting_approval',approval=NULL WHERE id=?", (job["id"],))
                        desk.log(job["id"], "restore_revoked_approval", {})
        finally:
            desk.close()
        if destination.exists():
            raise Rejected("restore destination appeared during validation")
        staging.rename(destination)
    return {"files_restored": len(manifest["files"]), "pending_approvals": "revoked"}


def _validate_databases(root):
    required = {
        "desk.sqlite": {"jobs": {"id", "event_key", "payload", "state", "created", "deadline", "owner", "lease_until", "attempts", "evidence", "trace", "proposal", "approval", "intent", "result", "error", "cancel_requested"},
                        "events": {"seq", "job", "at", "kind", "detail"}},
        "target/target.sqlite": {"config": {"id", "batch_limit", "version"}, "receipts": {"op", "proposal", "receipt"}},
    }
    try:
        for relative, tables in required.items():
            db = sqlite3.connect((root / relative).as_uri() + "?mode=ro", uri=True)
            try:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise Rejected("snapshot database integrity failure")
                for table, columns in tables.items():
                    if {row[1] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                        raise Rejected("snapshot database schema mismatch")
                if relative.endswith("target.sqlite") and db.execute("SELECT count(*) FROM config WHERE id=1").fetchone()[0] != 1:
                    raise Rejected("snapshot target configuration is missing")
            finally:
                db.close()
    except sqlite3.DatabaseError as error:
        raise Rejected("snapshot database is invalid") from error
