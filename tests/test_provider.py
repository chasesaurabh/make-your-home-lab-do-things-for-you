from contextlib import contextmanager
import http.server
import json
import threading
import unittest

from maintenance_desk.contracts import Rejected
from maintenance_desk.provider import LocalProvider


@contextmanager
def server(responses):
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status, content, headers = responses.pop(0)
            raw = content.encode()
            self.send_response(status)
            self.send_header("Content-Length",str(len(raw)))
            for key,value in headers.items():
                self.send_header(key,value)
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self,*args):
            pass
    with http.server.HTTPServer(("127.0.0.1",0),Handler) as instance:
        thread=threading.Thread(target=instance.serve_forever,daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{instance.server_port}/v1",requests
        finally:
            instance.shutdown()
            thread.join(timeout=3)


def response(decision):
    return json.dumps({"choices":[{"message":{"content":json.dumps(decision)}}],"usage":{"total_tokens":5}})


class ProviderTests(unittest.TestCase):
    def test_used_tool_is_removed_from_schema(self):
        with server([(200,response({"tool":"finish","reason":"enough evidence"}),{})]) as (base,requests):
            decision,_=LocalProvider(base,"synthetic").decide("capacity",{"read_diagnostic":{}},3)
            allowed=requests[0]["response_format"]["json_schema"]["schema"]["properties"]["tool"]["enum"]
            self.assertNotIn("read_diagnostic",allowed)
            self.assertEqual(decision["tool"],"finish")

    def test_transient_503_has_one_retry(self):
        with server([(503,"unavailable",{}),(200,response({"tool":"escalate","reason":"uncertain"}),{})]) as (base,requests):
            _,metrics=LocalProvider(base,"synthetic").decide("capacity",{},3)
            self.assertEqual(len(requests),2)
            self.assertEqual(metrics["retries"],1)

    def test_second_transient_failure_stops(self):
        with server([(503,"unavailable",{}),(503,"still unavailable",{})]) as (base,requests):
            with self.assertRaises(Exception):
                LocalProvider(base,"synthetic").decide("capacity",{},3)
            self.assertEqual(len(requests),2)

    def test_malformed_decision_does_not_retry(self):
        with server([(200,response({"tool":"shell","reason":"unsafe"}),{})]) as (base,requests):
            with self.assertRaises(Rejected):
                LocalProvider(base,"synthetic").decide("capacity",{},3)
            self.assertEqual(len(requests),1)

    def test_redirect_is_refused(self):
        with server([(302,"",{"Location":"https://example.com/"})]) as (base,requests):
            with self.assertRaises(Rejected):
                LocalProvider(base,"synthetic").decide("capacity",{},3)
            self.assertEqual(len(requests),1)

    def test_oversize_result_refused(self):
        with server([(200,"x"*65537,{})]) as (base,requests):
            with self.assertRaises(Rejected):
                LocalProvider(base,"synthetic").decide("capacity",{},3)

    def test_exhausted_deadline_does_not_send(self):
        with server([]) as (base,requests):
            with self.assertRaises(TimeoutError):
                LocalProvider(base,"synthetic").decide("capacity",{},0)
            self.assertEqual(requests,[])
