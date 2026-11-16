"""Pinned public model artifacts; no authentication or remote code execution."""
import hashlib
import json
from pathlib import Path, PurePosixPath

LOCK=Path(__file__).resolve().parents[1]/"configs/model-artifacts.lock.json"

def profile(name):
    lock=json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("schema")!=1 or name not in lock["profiles"]:
        raise ValueError("Choose a profile from the versioned model lock.")
    return lock,lock["profiles"][name]

def artifact_path(root,name):
    relative=PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe model artifact path.")
    root=Path(root).resolve()
    target=root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Model artifact escapes its destination.")
    return target

def verify_file(path,item):
    if not path.is_file() or path.stat().st_size!=item["bytes"]:
        raise ValueError("Missing artifact or size mismatch: "+item["path"])
    algorithm=item["hash_algorithm"]
    if algorithm not in {"sha256","git_blob_sha1"}:
        raise ValueError("Unsupported artifact hash algorithm.")
    digest=hashlib.sha256() if algorithm=="sha256" else hashlib.sha1()
    if algorithm=="git_blob_sha1":digest.update(f"blob {item['bytes']}\0".encode())
    with path.open("rb") as stream:
        while block:=stream.read(8*1024*1024):digest.update(block)
    if digest.hexdigest()!=item["hash"]:
        raise ValueError("Artifact hash mismatch: "+item["path"])

def verify_directory(root,config):
    for item in config["files"]:
        verify_file(artifact_path(root,item["path"]),item)
    return {"files":len(config["files"]),"bytes":sum(f["bytes"] for f in config["files"]),
            "repository":config["repository"],"revision":config["revision"],"hashes_verified":True}
