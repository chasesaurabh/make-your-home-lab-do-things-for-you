"""Explicit OFFLINE snapshots. Stop every worker and board before calling.

This file copy protocol does not establish atomicity against other processes.
Never restore over an existing installation; restored approvals are revoked.
"""
import hashlib
import json
from pathlib import Path
import shutil

from .contracts import Rejected, canonical
from .engine import Desk


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise Rejected("snapshot requires a new directory outside the data root")
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
    if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        raise Rejected("unknown snapshot format")
    for relative, expected in manifest["files"].items():
        path = source / relative
        if Path(relative).is_absolute() or not path.resolve().is_relative_to(source) or path.is_symlink():
            raise Rejected("snapshot path escape")
        if checksum(path) != expected:
            raise Rejected("snapshot digest mismatch")
    destination.mkdir(parents=True)
    for relative in manifest["files"]:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    desk = Desk(destination)
    try:
        # Restoration changes operating context. Never revive an old pending grant.
        with desk.transaction():
            for job in desk.jobs():
                if job["state"] == "ready":
                    desk.db.execute("UPDATE jobs SET state='awaiting_approval',approval=NULL WHERE id=?", (job["id"],))
                    desk.log(job["id"], "restore_revoked_approval", {})
    finally:
        desk.close()
    return {"files_restored": len(manifest["files"]), "pending_approvals": "revoked"}
