"""Operator CLI and read-only loopback job board."""
import argparse
import html
import http.server
import json
import time
from pathlib import Path

from .contracts import CASES, Rejected, digest
from .engine import Desk
from .provider import LocalProvider


def board(desk):
    cards = []
    for job in desk.jobs():
        proposal = job["proposal"]
        visible = {key: job[key] for key in ("id", "state", "payload", "attempts", "deadline", "approval", "error", "result")}
        visible["proposal"] = proposal
        visible["proposal_digest"] = digest(proposal) if proposal else None
        visible["timeline"] = desk.timeline(job["id"])
        cards.append("<article><h2>"+html.escape(job["state"])+"</h2><pre>"+
                     html.escape(json.dumps(visible, indent=2))+"</pre></article>")
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Maintenance Desk</title><style>body{font:16px system-ui;max-width:950px;margin:2rem auto;padding:0 1rem;background:#f4f3ef;color:#172f3a}"
            "article{background:white;border:1px solid #bec8cc;padding:1rem;margin:1rem 0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
            "h1,h2{line-height:1.2}</style><h1>Maintenance Desk</h1><p>Read-only synthetic job board. Operator commands issue approvals. "
            "This board has no authentication; keep it on loopback and use synthetic data.</p>"+"".join(cards)+"</html>")


def serve(root, port):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            desk = Desk(root)
            try:
                content = board(desk).encode()
            finally:
                desk.close()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass
    with http.server.HTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Read-only synthetic board: http://127.0.0.1:{port}/", flush=True)
        server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Maintenance Desk: synthetic bounded execution lab")
    parser.add_argument("--data", default="data/desk", help="operator-chosen disposable application directory")
    commands = parser.add_subparsers(dest="command", required=True)
    admission = commands.add_parser("submit")
    admission.add_argument("key")
    admission.add_argument("--case", choices=CASES, default="capacity")
    admission.add_argument("--mode", choices=("baseline", "agent"), default="baseline")
    inspection = commands.add_parser("inspect")
    inspection.add_argument("job")
    inspection.add_argument("--endpoint", help="loopback endpoint base including /v1")
    inspection.add_argument("--model")
    approval = commands.add_parser("approve")
    approval.add_argument("job")
    approval.add_argument("--digest", required=True)
    approval.add_argument("--actor", default="operator")
    for name in ("show", "apply", "cancel", "revoke"):
        commands.add_parser(name).add_argument("job")
    tick = commands.add_parser("tick")
    tick.add_argument("schedule")
    tick.add_argument("--period", type=int, default=3600)
    commands.add_parser("recover")
    commands.add_parser("list")
    commands.add_parser("rehearsal")
    work = commands.add_parser("work")
    work.add_argument("--cycles", type=int, default=1, help="bounded worker cycles, 1..100")
    work.add_argument("--interval", type=float, default=1, help="seconds between cycles, 0.1..60")
    work.add_argument("--schedule", help="optional periodic UTC-interval admission")
    work.add_argument("--period", type=int, default=3600)
    work.add_argument("--endpoint")
    work.add_argument("--model")
    exported = commands.add_parser("board")
    exported.add_argument("--output", default="data/board.html")
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=8791)
    for name in ("snapshot", "restore"):
        recovery = commands.add_parser(name)
        recovery.add_argument("directory")
    args = parser.parse_args(argv)
    if args.command == "rehearsal":
        from .rehearsal import run
        run()
        return
    if args.command == "serve":
        serve(args.data, args.port)
        return
    if args.command in ("snapshot", "restore"):
        from .snapshot import snapshot, restore
        try:
            result = (snapshot(args.data, args.directory) if args.command == "snapshot"
                      else restore(args.directory, args.data))
            print(json.dumps(result, indent=2))
        except (Rejected, ValueError, OSError) as error:
            parser.exit(2, "Rejected: "+str(error)+"\n")
        return
    desk = Desk(args.data)
    try:
        if args.command == "submit":
            result = desk.admit(args.key, {"source": "manual", "case": args.case, "mode": args.mode})
        elif args.command == "inspect":
            if args.endpoint and not args.model:
                raise Rejected("--model required with --endpoint")
            provider = LocalProvider(args.endpoint, args.model) if args.endpoint else None
            result = desk.inspect(args.job, provider)
        elif args.command == "approve":
            desk.approve(args.job, args.digest, actor=args.actor)
            result = desk.get(args.job)
        elif args.command == "apply":
            result = desk.apply(args.job)
        elif args.command in ("cancel", "revoke"):
            getattr(desk, args.command)(args.job)
            result = desk.get(args.job)
        elif args.command == "show":
            result = desk.get(args.job)
            result["timeline"] = desk.timeline(args.job)
        elif args.command == "tick":
            result = desk.tick(args.schedule, period=args.period)
        elif args.command == "recover":
            result = desk.recover()
        elif args.command == "list":
            result = desk.jobs()
        elif args.command == "work":
            if not 1 <= args.cycles <= 100 or not 0.1 <= args.interval <= 60:
                raise Rejected("worker cycles/interval outside bounds")
            provider = LocalProvider(args.endpoint, args.model) if args.endpoint and args.model else None
            for cycle in range(args.cycles):
                if args.schedule:
                    desk.tick(args.schedule, period=args.period)
                desk.recover()
                for job in desk.jobs():
                    if job["state"] == "queued":
                        if job["payload"]["mode"] == "agent" and provider is None:
                            continue
                        desk.inspect(job["id"], provider if job["payload"]["mode"] == "agent" else None)
                    elif job["state"] == "ready":
                        desk.apply(job["id"])
                if cycle+1 < args.cycles:
                    time.sleep(args.interval)
            result = desk.jobs()
        else:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(board(desk), encoding="utf-8")
            result = {"board_written": str(path)}
        print(json.dumps(result, indent=2))
    except (Rejected, ValueError, OSError) as error:
        parser.exit(2, "Rejected: "+str(error)+"\n")
    finally:
        desk.close()
