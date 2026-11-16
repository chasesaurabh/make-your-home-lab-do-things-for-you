"""Regressions discovered while independently exercising the original release."""
import json
import contextlib
import io
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from maintenance_desk.contracts import Rejected, canonical, digest
from maintenance_desk.engine import Desk
from maintenance_desk.snapshot import checksum, restore, snapshot
from maintenance_desk.cli import main


class RevisionBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 1800000000.0
        self.desk = Desk(self.root / 'desk', clock=lambda: self.now, capacity=1)
        self.payload = {'source': 'fixture', 'case': 'capacity', 'mode': 'baseline'}

    def tearDown(self):
        self.desk.close()
        self.temp.cleanup()

    def test_full_schedule_names_do_not_collide(self):
        self.desk.capacity = 4
        first = self.desk.tick('x' * 40 + 'alpha')
        second = self.desk.tick('x' * 40 + 'beta')
        self.assertNotEqual(first, second)
        self.assertEqual(first, self.desk.tick('x' * 40 + 'alpha'))
        self.now += 3600
        self.assertNotEqual(first, self.desk.tick('x' * 40 + 'alpha'))

    def test_review_prints_digest_without_granting_permission(self):
        job = self.desk.admit('review', self.payload)
        self.desk.inspect(job)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(['--data', str(self.root / 'desk'), 'review', job])
        reviewed = json.loads(output.getvalue())
        self.assertEqual(digest(self.desk.get(job)['proposal']), reviewed['proposal_digest'])
        self.assertIsNone(self.desk.get(job)['approval'])
        self.assertEqual('awaiting_approval', self.desk.get(job)['state'])
        self.assertEqual(0, self.desk.target.snapshot()['version'])

    def test_legacy_short_schedule_identity_is_preserved(self):
        payload = {**self.payload, 'source': 'schedule'}
        old = self.desk.admit(f'daily-3600-{int(self.now // 3600)}', payload)
        self.assertEqual(old, self.desk.tick('daily'))
        with self.assertRaisesRegex(Rejected, 'conflict'):
            self.desk.tick('daily', mode='agent')

    def test_legacy_long_schedule_ambiguity_is_rejected(self):
        self.desk.admit(f'{"x" * 40}-3600-{int(self.now // 3600)}', {**self.payload, 'source': 'schedule'})
        with self.assertRaisesRegex(Rejected, 'ambiguous legacy'):
            self.desk.tick('x' * 40 + 'alpha')

    def test_legacy_exactly_forty_character_name_is_also_ambiguous(self):
        self.desk.admit(f'{"x" * 40}-3600-{int(self.now // 3600)}', {**self.payload, 'source': 'schedule'})
        with self.assertRaisesRegex(Rejected, 'ambiguous legacy'):
            self.desk.tick('x' * 40)

    def test_queued_deadline_releases_capacity(self):
        old = self.desk.admit('old', self.payload, deadline_seconds=1)
        self.now += 1
        new = self.desk.admit('new', self.payload)
        self.assertEqual('failed', self.desk.get(old)['state'])
        self.assertEqual('queued', self.desk.get(new)['state'])
        self.assertEqual(0, self.desk.target.snapshot()['version'])

    def test_expired_approval_or_grant_releases_capacity(self):
        self.desk.capacity = 2
        for key in ('unapproved', 'approved'):
            job = self.desk.admit(key, self.payload)
            self.desk.inspect(job)
            if key == 'approved':
                self.desk.approve(job, digest(self.desk.get(job)['proposal']))
        self.now += 300
        self.desk.admit('next', self.payload)
        for job in self.desk.jobs():
            if job['event_key'] != 'next':
                self.assertEqual('failed', job['state'])
                self.assertIsNone(job['approval'])
        self.assertEqual(0, self.desk.target.snapshot()['version'])

    def test_expiry_does_not_discard_uncertain_intent(self):
        job = self.desk.admit('old', self.payload, deadline_seconds=1)
        self.desk.db.execute("UPDATE jobs SET state='needs_reconciliation',intent=? WHERE id=?", (canonical({'operation_id': 'unresolved'}), job))
        self.now += 2
        with self.assertRaisesRegex(Rejected, 'capacity'):
            self.desk.admit('next', self.payload)
        self.assertEqual('needs_reconciliation', self.desk.get(job)['state'])

    def make_snapshot(self):
        # There are no active workers; SQLite transactions are closed.
        snapshot(self.root / 'desk', self.root / 'snapshot')
        return self.root / 'snapshot', self.root / 'restored'

    def test_empty_snapshot_rejected_without_creating_destination(self):
        src = self.root / 'empty'
        src.mkdir()
        (src / 'snapshot.json').write_text(canonical({'schema': 1, 'files': {}}))
        with self.assertRaisesRegex(Rejected, 'missing required'):
            restore(src, self.root / 'restored')
        self.assertFalse((self.root / 'restored').exists())

    def test_snapshot_of_missing_installation_does_not_initialize_it(self):
        with self.assertRaises(Rejected):
            snapshot(self.root / 'absent', self.root / 'snapshot')
        self.assertFalse((self.root / 'absent').exists())

    def test_extra_nested_manifest_is_not_ignored(self):
        src, dest = self.make_snapshot()
        (src / 'target/snapshot.json').write_text('{}')
        with self.assertRaisesRegex(Rejected, 'inventory'):
            restore(src, dest)
        self.assertFalse(dest.exists())

    def test_valid_hash_does_not_make_wrong_database_schema_valid(self):
        src, dest = self.make_snapshot()
        db = sqlite3.connect(src / 'desk.sqlite')
        db.execute('DROP TABLE events')
        db.commit()
        db.close()
        manifest = json.loads((src / 'snapshot.json').read_text())
        manifest['files']['desk.sqlite'] = checksum(src / 'desk.sqlite')
        (src / 'snapshot.json').write_text(canonical(manifest))
        with self.assertRaisesRegex(Rejected, 'schema'):
            restore(src, dest)
        self.assertFalse(dest.exists())

    def test_copy_time_change_is_rejected_before_installation(self):
        src, dest = self.make_snapshot()
        copy = shutil.copyfile
        def corrupt_copy(source, target):
            result = copy(source, target)
            Path(target).write_bytes(b'changed during copy')
            return result
        with patch('maintenance_desk.snapshot.shutil.copyfile', side_effect=corrupt_copy):
            with self.assertRaisesRegex(Rejected, 'changed during restore'):
                restore(src, dest)
        self.assertFalse(dest.exists())

    def test_restore_of_active_job_is_rejected_atomically(self):
        src, dest = self.make_snapshot()
        db = sqlite3.connect(src / 'desk.sqlite')
        db.execute("INSERT INTO jobs(id,event_key,payload,state,created,deadline) VALUES('test','test','{}','applying',0,1)")
        db.commit()
        db.close()
        manifest = json.loads((src / 'snapshot.json').read_text())
        manifest['files']['desk.sqlite'] = checksum(src / 'desk.sqlite')
        (src / 'snapshot.json').write_text(canonical(manifest))
        with self.assertRaisesRegex(Rejected, 'active worker'):
            restore(src, dest)
        self.assertFalse(dest.exists())

    def test_cancelled_verified_effect_is_validated_on_restore(self):
        job = self.desk.admit('cancel-after-effect', self.payload)
        self.desk.inspect(job)
        self.desk.approve(job, digest(self.desk.get(job)['proposal']))
        original = self.desk.target.apply
        def cancel_after_commit(*args, **kwargs):
            receipt = original(*args, **kwargs)
            self.desk.cancel(job)
            return receipt
        with patch.object(self.desk.target, 'apply', side_effect=cancel_after_commit):
            self.desk.apply(job)
        self.assertEqual('effect_verified_after_cancel', self.desk.get(job)['result']['kind'])
        src, dest = self.make_snapshot()
        artifact = next((src/'target').rglob('*.txt'))
        artifact.write_bytes(b'changed after cancellation')
        manifest = json.loads((src/'snapshot.json').read_text())
        manifest['files'][artifact.relative_to(src).as_posix()] = checksum(artifact)
        (src/'snapshot.json').write_text(canonical(manifest))
        with self.assertRaises(Rejected):
            restore(src, dest)
        self.assertFalse(dest.exists())
