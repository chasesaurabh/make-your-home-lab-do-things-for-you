from pathlib import Path
import tempfile
import unittest

from maintenance_desk.contracts import Rejected, digest
from maintenance_desk.engine import Desk
from maintenance_desk.snapshot import snapshot, restore


class SnapshotTests(unittest.TestCase):
    def test_offline_restore_preserves_receipt_and_revokes_pending_grant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            desk = Desk(root/"original")
            try:
                first = desk.admit("first", {"source":"fixture","case":"capacity","mode":"baseline"})
                desk.inspect(first)
                desk.approve(first, digest(desk.get(first)["proposal"]))
                desk.apply(first)
                second = desk.admit("second", {"source":"fixture","case":"capacity","mode":"baseline"})
                desk.inspect(second)
                desk.approve(second, digest(desk.get(second)["proposal"]))
            finally:
                desk.close()
            snapshot(root/"original", root/"snapshot")
            restore(root/"snapshot", root/"restored")
            restored = Desk(root/"restored")
            try:
                self.assertEqual(restored.get(first)["state"], "succeeded")
                restored.target.verify(restored.get(first)["intent"])
                self.assertEqual(restored.get(second)["state"], "awaiting_approval")
                self.assertIsNone(restored.get(second)["approval"])
            finally:
                restored.close()

    def test_corrupt_snapshot_cannot_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Desk(root/"original").close()
            snapshot(root/"original", root/"snapshot")
            (root/"snapshot"/"desk.sqlite").write_bytes(b"corrupt")
            with self.assertRaises(Rejected):
                restore(root/"snapshot", root/"restored")
            self.assertFalse((root/"restored").exists())

    def test_snapshot_inside_data_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Desk(root/"original").close()
            with self.assertRaises(Rejected):
                snapshot(root/"original", root/"original"/"nested")
