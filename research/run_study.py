"""Real inference on synthetic fixtures; all effects remain in temporary directories.

The harness grants only its own disposable test operations. This is not an
automatic approval mode for a reader's actual notes or maintenance jobs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maintenance_desk.contracts import digest
from maintenance_desk.evaluate import run_case, RUBRIC
from maintenance_desk.inbox import Inbox, SYSTEM as INBOX_SYSTEM
from maintenance_desk.provider import LocalProvider, SYSTEM as ROUTING_SYSTEM


class RecordedResponse:
    def __init__(self, response, record, started):
        self.response, self.record, self.started = response, record, started

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.record['seconds'] = time.monotonic() - self.started
        if args[1]:
            self.record['error'] = type(args[1]).__name__ + ': ' + str(args[1])
        self.response.close()

    def read(self, limit):
        raw = self.response.read(limit)
        self.record['response_bytes'] = len(raw)
        try:
            self.record['response'] = json.loads(raw)
        except ValueError:
            self.record['response_text'] = raw.decode('utf-8', errors='replace')
        return raw


class Recorder:
    def __init__(self, opener):
        self.opener, self.calls = opener, []

    def open(self, request, timeout):
        started = time.monotonic()
        record = {'request': json.loads(request.data), 'timeout': timeout}
        self.calls.append(record)
        try:
            response = self.opener.open(request, timeout=timeout)
            record['http_status'] = response.status
            return RecordedResponse(response, record, started)
        except Exception as error:
            record.update(seconds=time.monotonic()-started, error=type(error).__name__ + ': ' + str(error))
            raise


def inbox_batch(fixtures, provider):
    with tempfile.TemporaryDirectory(prefix='inbox-study-') as temporary:
        root = Path(temporary)
        source, output = root / 'source', root / 'output'
        source.mkdir()
        output.mkdir()
        for item in fixtures:
            (source / (item['id'] + '.txt')).write_text(item['text'], encoding='utf-8', newline='\n')
        inbox = Inbox(root / 'state')
        try:
            current, _ = inbox.prepare(source, output, provider)
            decisions = current['proposal']['decisions']
            labels = {f'n{i:02d}': item['label'] for i, item in enumerate(sorted(fixtures, key=lambda f: f['id']), 1)}
            correct = sum(item['category'] == labels[item['id']] for item in decisions)
            # The controlled experiment operator approves valid proposals only in
            # this new temporary fixture; classification errors still count.
            inbox.approve(current['id'], current['proposal_digest'])
            completed = inbox.apply(current['id'])
            verified = inbox.verify(current['id']) == completed['receipt']
            return {'fixtures': [f['id'] for f in fixtures], 'labels': labels, 'decisions': decisions,
                    'correct_labels': correct, 'total_labels': len(labels),
                    'exact_batch': correct == len(labels), 'grounded_quotes': len(decisions),
                    'verified_copy': verified, 'state': completed['state']}
        finally:
            inbox.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--profile', choices=['2b', '9b', '27b', '122b'], required=True)
    parser.add_argument('--lane', choices=['development', 'holdout'], required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.repeats <= 3:
        parser.error('Use a new evidence file and 1..3 repetitions')
    fixtures = json.loads((ROOT / 'research/inbox-fixtures.json').read_text())
    study = {'schema': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
             'lane': args.lane, 'profile': args.profile, 'model': args.model,
             'environment': {'python': platform.python_version(), 'platform': platform.system(), 'sqlite': sqlite3.sqlite_version},
             'conditions': 'Sequential, isolated model container, warmed after recorded startup probe; first task request retained separately; synthetic inputs and actual disposable effects',
             'fingerprints': {'plan': digest(json.loads((ROOT / 'research/study-plan.json').read_text())),
                              'fixtures': digest(fixtures), 'inbox_prompt': digest(INBOX_SYSTEM),
                              'routing_prompt': digest(ROUTING_SYSTEM), 'routing_rubric': digest(RUBRIC)},
             'rows': []}
    provider = LocalProvider(args.endpoint, args.model, timeout=30)
    recorder = Recorder(provider.opener)
    provider.opener = recorder
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(study, indent=2) + '\n', encoding='utf-8')
    save()
    cases = [c for c in RUBRIC if c.startswith('holdout-' if args.lane == 'holdout' else 'dev-')]
    notes = fixtures[args.lane]
    batches = [notes[i:i+4] for i in range(0, len(notes), 4)]
    for repeat in range(args.repeats):
        for mode in ('baseline', 'agent'):
            for task, name, value in ([('maintenance', case, case) for case in cases] +
                                      [('inbox', f'batch-{i+1}', batch) for i, batch in enumerate(batches)]):
                start_calls, started = len(recorder.calls), time.monotonic()
                row = {'task': task, 'case': name, 'mode': mode, 'repeat': repeat + 1}
                try:
                    row['result'] = (run_case(value, mode, provider) if task == 'maintenance' else
                                     inbox_batch(value, provider if mode == 'agent' else None))
                except Exception as error:
                    row['error'] = type(error).__name__ + ': ' + str(error)
                row.update(elapsed_seconds=time.monotonic() - started, calls=recorder.calls[start_calls:])
                study['rows'].append(row)
                save()
                print(json.dumps({k: row.get(k) for k in ('task', 'case', 'mode', 'repeat', 'error', 'elapsed_seconds')}), flush=True)
    study['completed_utc'] = datetime.now(timezone.utc).isoformat()
    save()


if __name__ == '__main__':
    main()
