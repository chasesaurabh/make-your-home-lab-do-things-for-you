"""Automatic approval here is limited to an explicitly requested temporary demo."""
import json
from pathlib import Path
import tempfile

from .cli import board
from .contracts import digest
from .engine import Desk


def run():
    with tempfile.TemporaryDirectory(prefix="maintenance-desk-rehearsal-") as temporary:
        root = Path(temporary)/"desk"
        desk = Desk(root)
        try:
            job = desk.admit("synthetic-event", {"source":"fixture","case":"capacity","mode":"baseline"})
            desk.inspect(job)
            proposal = desk.get(job)["proposal"]
            print("Exact disposable-demo proposal:", json.dumps(proposal, indent=2))
            desk.approve(job, digest(proposal), actor="demo-operator")
            desk.apply(job)
            receipt = desk.get(job)["result"]
        finally:
            desk.close()
        desk = Desk(root)
        try:
            assert desk.get(job)["state"] == "succeeded"
            assert desk.apply(job)["result"] == receipt
            assert desk.target.snapshot()["version"] == 1
            print(json.dumps({"state": desk.get(job)["state"], "receipt": receipt,
                              "restart_and_duplicate": "verified", "events": len(desk.timeline(job))}, indent=2))
        finally:
            desk.close()
