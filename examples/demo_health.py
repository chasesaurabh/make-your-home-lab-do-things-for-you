"""Disposable loopback health fixture. Ctrl+C stops the service."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18797)
    parser.add_argument('--status', type=int, choices=[200, 503], default=200)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose an unprivileged port')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/health':
                self.send_error(404)
                return
            body = b'{"status":"ready"}\n' if args.status == 200 else b'{"status":"unavailable"}\n'
            self.send_response(args.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    with HTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Disposable health fixture: http://127.0.0.1:{args.port}/health', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
