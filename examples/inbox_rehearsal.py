"""Run a disposable copy-only inbox exercise with explicit fixture-only approval."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maintenance_desk.inbox import Inbox
from maintenance_desk.provider import LocalProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint')
    parser.add_argument('--model')
    args = parser.parse_args()
    if bool(args.endpoint) != bool(args.model):
        parser.error('Provide endpoint and model together')
    provider = LocalProvider(args.endpoint, args.model, timeout=30) if args.endpoint else None
    with tempfile.TemporaryDirectory(prefix='inbox-rehearsal-') as temp:
        root = Path(temp)
        source, output = root / 'notes', root / 'output'
        source.mkdir()
        output.mkdir()
        (source / 'first.txt').write_text('Test the spare cable tomorrow; this task is open.\n', encoding='utf-8')
        (source / 'second.txt').write_text('The earlier certificate renewal is complete with no follow-up.\n', encoding='utf-8')
        inbox = Inbox(root / 'state')
        try:
            job, _ = inbox.prepare(source, output, provider)
            print(json.dumps({'fixture_proposal': job['proposal']['decisions']}, indent=2))
            # These are only the two disposable strings above, never user files.
            inbox.approve(job['id'], job['proposal_digest'])
            result = inbox.apply(job['id'])
            assert inbox.verify(job['id']) == result['receipt']
            assert len(list(source.iterdir())) == 2
            print('Fixture copies verified; original notes preserved.')
        finally:
            inbox.close()


if __name__ == '__main__':
    main()
