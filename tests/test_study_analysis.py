"""Corrupted evidence must not silently become a plausible scorecard."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from research.analyze_study import summarize


class StudyAnalysis(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).resolve().parents[1]/'research/results/holdout-2b.json'
        self.data = json.loads(self.source.read_text())

    def rejected(self, mutate, message):
        data = copy.deepcopy(self.data)
        mutate(data)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'changed.json'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,message):
                summarize(path)

    def test_all_four_actual_records_recompute(self):
        for profile, correct in [('2b',27),('9b',36),('27b',36),('122b',35)]:
            result=summarize(self.source.with_name(f'holdout-{profile}.json'))
            group=next(g for g in result['groups'] if g['task']=='maintenance' and g['mode']=='agent')
            self.assertEqual(correct,group['correct_outcomes'])

    def test_missing_row_rejected(self):
        self.rejected(lambda d:d['rows'].pop(), 'Missing or duplicate')

    def test_duplicate_row_rejected(self):
        self.rejected(lambda d:d['rows'].append(d['rows'][0]), 'Missing or duplicate')

    def test_changed_expectation_rejected(self):
        self.rejected(lambda d:d['rows'][0]['result'].update(expected='escalated'), 'frozen rubric')

    def test_changed_score_rejected(self):
        self.rejected(lambda d:d['rows'][0]['result'].update(correct_disposition=False), 'does not reproduce')

    def test_changed_prompt_identity_rejected(self):
        self.rejected(lambda d:d['fingerprints'].update(inbox_prompt='0'*64), 'fingerprint')

    def test_incomplete_study_rejected(self):
        self.rejected(lambda d:d.pop('completed_utc'), 'not completed')
