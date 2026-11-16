from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest

from maintenance_desk.contracts import Rejected
from maintenance_desk.service_watch import collect, probe, validate_config, verify_report, write_report


class HealthHandler(BaseHTTPRequestHandler):
    redirected_calls = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/redirected')
            self.end_headers()
            return
        if self.path == '/redirected':
            type(self).redirected_calls += 1
        if self.path == '/slow':
            time.sleep(.2)
        body = b'x' * 17000 if self.path == '/large' else b'{"status":"ready"}'
        self.send_response(503 if self.path == '/unavailable' else 200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class ServiceWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), HealthHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def service(self, path='/health'):
        return {'id': 'demo', 'url': f'http://127.0.0.1:{self.server.server_port}{path}', 'expect_status': 200, 'contains': 'ready'}

    def test_real_http_status_and_body_are_checked(self):
        result = probe(self.service())
        self.assertEqual('pass', result['outcome'])
        self.assertEqual(200, result['http_status'])
        self.assertTrue(result['marker_found'])
        self.assertEqual(64, len(result['body_sha256']))

    def test_503_is_observed_as_failure(self):
        result = probe(self.service('/unavailable'))
        self.assertEqual('mismatch', result['outcome'])
        self.assertEqual(503, result['http_status'])

    def test_missing_body_marker_is_failure_even_with_200(self):
        service = self.service()
        service['contains'] = 'absent-marker'
        self.assertEqual('mismatch', probe(service)['outcome'])

    def test_redirect_is_never_followed(self):
        before = HealthHandler.redirected_calls
        self.assertEqual('observation_failed', probe(self.service('/redirect'))['outcome'])
        self.assertEqual(before, HealthHandler.redirected_calls)

    def test_oversize_body_is_not_reported_healthy(self):
        self.assertEqual('body_too_large', probe(self.service('/large'))['outcome'])

    def test_idle_timeout_is_an_observation_failure(self):
        self.assertEqual('observation_failed', probe(self.service('/slow'), timeout=.03)['outcome'])

    def test_config_rejects_remote_credentials_queries_and_duplicates(self):
        for url in ('http://example.com:80/health', 'http://user:pass@127.0.0.1:8000/', 'http://127.0.0.1:8000/?token=private', 'http://localhost:8000/', 'file:///etc/passwd'):
            with self.subTest(url=url):
                with self.assertRaises(Rejected):
                    validate_config({'schema': 1, 'services': [{**self.service(), 'url': url}]})
        with self.assertRaises(Rejected):
            validate_config({'schema': 1, 'services': [self.service(), self.service()]})

    def test_report_round_trip_and_tamper_detection(self):
        report = collect({'schema': 1, 'services': [self.service()]}, rounds=2, interval=.1)
        self.assertEqual(2, len(report['rounds']))
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'report'
            expected = write_report(report, dest)
            self.assertEqual(expected, verify_report(dest))
            with self.assertRaises(Rejected):
                write_report(report, dest)
            (dest / 'REPORT.md').write_text('changed')
            with self.assertRaises(Rejected):
                verify_report(dest)

    def test_rounds_and_intervals_are_bounded(self):
        config = {'schema': 1, 'services': [self.service()]}
        for rounds, interval in ((0, 1), (13, 1), (1, 0), (1, 61)):
            with self.assertRaises(Rejected):
                collect(config, rounds=rounds, interval=interval)
