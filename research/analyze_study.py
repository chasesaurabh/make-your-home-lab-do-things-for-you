"""Recompute aggregate study results from full rows; never trust summary fields."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maintenance_desk.contracts import digest
from maintenance_desk.evaluate import RUBRIC
from maintenance_desk.inbox import SYSTEM as INBOX_SYSTEM
from maintenance_desk.provider import SYSTEM as ROUTING_SYSTEM


def summarize(path):
    study = json.loads(path.read_text(encoding='utf-8'))
    if not study.get('completed_utc'):
        raise ValueError('Study has not completed: ' + path.name)
    fixtures_all = json.loads((ROOT / 'research/inbox-fixtures.json').read_text())
    expected_fingerprints = {'plan': digest(json.loads((ROOT / 'research/study-plan.json').read_text())),
                             'fixtures': digest(fixtures_all), 'inbox_prompt': digest(INBOX_SYSTEM),
                             'routing_prompt': digest(ROUTING_SYSTEM), 'routing_rubric': digest(RUBRIC)}
    if study['fingerprints'] != expected_fingerprints:
        raise ValueError('Study configuration fingerprint does not match this release')
    cases = {c for c in RUBRIC if c.startswith('holdout-' if study['lane'] == 'holdout' else 'dev-')}
    batches = {f'batch-{i+1}' for i in range(math.ceil(len(fixtures_all[study['lane']])/4))}
    repeats = {r['repeat'] for r in study['rows']}
    if not repeats or repeats != set(range(1, max(repeats)+1)) or max(repeats)>3:
        raise ValueError('Invalid repetition inventory')
    expected_rows = {(task, case, mode, repeat) for task, names in [('maintenance', cases), ('inbox', batches)]
                     for case in names for mode in ('baseline', 'agent') for repeat in repeats}
    actual_rows = [(r['task'], r['case'], r['mode'], r['repeat']) for r in study['rows']]
    if len(actual_rows) != len(expected_rows) or set(actual_rows) != expected_rows:
        raise ValueError('Missing or duplicate study rows')
    for row in study['rows']:
        if row['task']=='maintenance' and row.get('result') and row['result']['expected'] != RUBRIC[row['case']]:
            raise ValueError('Maintenance expectation does not match frozen rubric')
    output = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'profile': study['profile'], 'lane': study['lane'], 'groups': []}
    for task in ('maintenance', 'inbox'):
        for mode in ('baseline', 'agent'):
            rows = [r for r in study['rows'] if r['task'] == task and r['mode'] == mode]
            if not rows:
                raise ValueError('Missing study group')
            times = sorted(r['elapsed_seconds'] for r in rows)
            calls = [call for row in rows for call in row['calls']]
            tokens = [call.get('response', {}).get('usage', {}).get('total_tokens') for call in calls]
            group = {'task': task, 'mode': mode, 'runs': len(rows), 'first_run_seconds': rows[0]['elapsed_seconds'],
                     'p50_seconds': statistics.median(times), 'p95_nearest_rank_seconds': times[math.ceil(.95*len(times))-1],
                     'http_calls': len(calls), 'reported_total_tokens': sum(t for t in tokens if t is not None),
                     'calls_without_usage': sum(t is None for t in tokens), 'harness_errors': sum('error' in r for r in rows)}
            if task == 'maintenance':
                results = [r.get('result', {}) for r in rows]
                correct = [r.get('actual') == r.get('expected') and bool(r) for r in results]
                for result, agrees in zip(results, correct):
                    if result and result['correct_disposition'] != agrees:
                        raise ValueError('Stored maintenance score does not reproduce')
                group.update(correct_outcomes=sum(correct),
                             unauthorized_effects=sum(r.get('target_effect_count', 0) > 0 and r.get('expected') != 'effect_verified' for r in results),
                             false_successes=sum(r.get('job', {}).get('state') == 'succeeded' and not agrees for r, agrees in zip(results, correct)))
            else:
                labels = correct = batches = copies = grounded = 0
                confusion = {actual: {predicted: 0 for predicted in ('action', 'reference', 'uncertain', 'invalid')} for actual in ('action', 'reference', 'uncertain')}
                fixtures = json.loads((Path(__file__).parent / 'inbox-fixtures.json').read_text())[study['lane']]
                for row in rows:
                    batch_index = int(row['case'].split('-')[1]) - 1
                    batch = fixtures[4*batch_index:4*batch_index+4]
                    expected = {f'n{i:02d}': f['label'] for i, f in enumerate(sorted(batch, key=lambda f: f['id']), 1)}
                    result = row.get('result', {})
                    predicted = {item['id']: item['category'] for item in result.get('decisions', [])}
                    texts = {f'n{i:02d}': f['text'] for i, f in enumerate(sorted(batch, key=lambda f: f['id']), 1)}
                    if result:
                        if len(predicted) != len(expected) or set(predicted) != set(expected):
                            raise ValueError('Inbox decision IDs do not reproduce the batch')
                        for item in result['decisions']:
                            if not item['quote'] or item['quote'] not in texts[item['id']]:
                                raise ValueError('Inbox evidence quotation is not grounded')
                            grounded += 1
                    count = sum(predicted.get(key) == value for key, value in expected.items())
                    if result and (result['correct_labels'] != count or result['labels'] != expected):
                        raise ValueError('Stored inbox score does not reproduce')
                    labels += len(expected)
                    correct += count
                    batches += count == len(expected)
                    copies += result.get('verified_copy', False)
                    for key, value in expected.items():
                        confusion[value][predicted.get(key, 'invalid')] += 1
                group.update(note_decisions=labels, correct_labels=correct, exact_batches=batches,
                             verified_copies=copies, grounded_quotes=grounded, confusion=confusion)
            output['groups'].append(group)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Preserve prior summaries; choose a new filename')
    results = [summarize(p) for p in args.files]
    args.output.write_text(json.dumps({'schema': 1, 'results': results}, indent=2)+'\n', encoding='utf-8')
    print(json.dumps([{'profile': r['profile'], 'verified_groups': len(r['groups'])} for r in results]))


if __name__ == '__main__':
    main()
