"""Collect bounded read-only loopback HTTP observations into a new report.

Use only operator-configured health URLs whose GET operation is read-only.
No model chooses URLs or repair actions. A passing probe is not full service health.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from .contracts import Rejected, canonical
from .provider import NoRedirect


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'services'} or type(value['schema']) is not int or value['schema'] != 1:
        raise Rejected('service configuration requires schema 1 and services')
    if not isinstance(value['services'], list) or not 1 <= len(value['services']) <= 8:
        raise Rejected('configure 1..8 services')
    seen = set()
    for service in value['services']:
        if not isinstance(service, dict) or set(service) != {'id', 'url', 'expect_status', 'contains'}:
            raise Rejected('service requires id, url, expect_status and contains')
        name = service['id']
        if not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9-]{0,39}', name) or name in seen:
            raise Rejected('service IDs must be unique short lowercase names')
        seen.add(name)
        if not isinstance(service['url'], str) or len(service['url']) > 256:
            raise Rejected('bounded URL required')
        url = urlsplit(service['url'])
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
            port = url.port
        except (ValueError, TypeError):
            loopback, port = False, None
        if url.scheme != 'http' or not loopback or not port or url.username or url.password or url.query or url.fragment:
            raise Rejected('use numeric loopback HTTP, explicit port, no credentials, query or fragment')
        if type(service['expect_status']) is not int or not 100 <= service['expect_status'] <= 599:
            raise Rejected('expected status must be an HTTP integer')
        if not isinstance(service['contains'], str) or not 1 <= len(service['contains']) <= 128:
            raise Rejected('supply a nonempty expected body marker up to 128 characters')
    return value


def probe(service, *, timeout=2):
    if not 0 < timeout <= 5:
        raise Rejected('probe timeout must be in (0,5] seconds')
    validate_config({'schema': 1, 'services': [service]})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    result = {'id': service['id'], 'url': service['url'], 'expect_status': service['expect_status'],
              'expected_marker': service['contains'], 'outcome': 'unknown'}
    try:
        request = Request(service['url'], headers={'User-Agent': 'maintenance-desk-service-watch/1', 'Accept': 'text/plain,application/json'})
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as error:
            response = error  # HTTP failures still provide measurable status/body.
        with response:
            raw = response.read(16385)
            result['http_status'] = response.status
        if len(raw) > 16384:
            result['outcome'] = 'body_too_large'
        else:
            result.update(body_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest(),
                          marker_found=service['contains'].encode('utf-8') in raw)
            result['outcome'] = ('pass' if result['http_status'] == service['expect_status'] and result['marker_found'] else 'mismatch')
    except (OSError, URLError, Rejected) as error:
        result.update(outcome='observation_failed', error_type=type(error).__name__)
    result['seconds'] = time.monotonic() - started
    return result


def collect(config, *, rounds=1, interval=1, timeout=2):
    validate_config(config)
    if type(rounds) is not int or not 1 <= rounds <= 12 or not 0.1 <= interval <= 60:
        raise Rejected('use 1..12 rounds and interval 0.1..60 seconds')
    report = {'schema': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'config_sha256': hashlib.sha256(canonical(config).encode()).hexdigest(),
              'scope': 'Configured HTTP status and body marker only; no repair and no general health conclusion',
              'rounds': []}
    for index in range(rounds):
        report['rounds'].append({'number': index + 1, 'observed_utc': datetime.now(timezone.utc).isoformat(),
                                'services': [probe(service, timeout=timeout) for service in config['services']]})
        if index + 1 < rounds:
            time.sleep(interval)
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    return report


def write_report(report, destination):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise Rejected('report destination must be a new directory')
    destination.mkdir()  # Parent must already exist; never overwrite prior evidence.
    lines = ['# Local service observations', '', report['scope'], '']
    for round_ in report['rounds']:
        lines.extend([f"## Round {round_['number']}", '', round_['observed_utc'], ''])
        for service in round_['services']:
            lines.append(f"- {service['id']}: {service['outcome']} ({service['seconds']:.3f} seconds)")
        lines.append('')
    outputs = {'observations.json': (canonical(report) + '\n').encode(),
               'REPORT.md': ('\n'.join(lines) + '\n').encode()}
    for name, data in outputs.items():
        with (destination / name).open('xb') as stream:
            stream.write(data)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    with (destination / 'SHA256SUMS.json').open('x', encoding='utf-8') as stream:
        stream.write(canonical(manifest) + '\n')
    verify_report(destination)
    return manifest


def verify_report(directory):
    directory = Path(directory)
    names = {'observations.json', 'REPORT.md', 'SHA256SUMS.json'}
    if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()} != names:
        raise Rejected('report inventory differs')
    if any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        raise Rejected('report files must be ordinary files')
    manifest = json.loads((directory / 'SHA256SUMS.json').read_text())
    if not isinstance(manifest, dict) or set(manifest) != names - {'SHA256SUMS.json'}:
        raise Rejected('report manifest differs')
    for name, expected in manifest.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise Rejected('report bytes differ')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    collect_args = commands.add_parser('collect')
    collect_args.add_argument('--config', type=Path, required=True)
    collect_args.add_argument('--output', type=Path, required=True)
    collect_args.add_argument('--rounds', type=int, default=1)
    collect_args.add_argument('--interval', type=float, default=1)
    collect_args.add_argument('--timeout', type=float, default=2)
    verify_args = commands.add_parser('verify')
    verify_args.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'collect':
        # Check output before contacting any service.
        if args.output.exists() or not args.output.parent.is_dir():
            parser.error('Choose a new output directory under an existing parent')
        config = json.loads(args.config.read_text(encoding='utf-8'))
        report = collect(config, rounds=args.rounds, interval=args.interval, timeout=args.timeout)
        result = write_report(report, args.output)
    else:
        result = verify_report(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
