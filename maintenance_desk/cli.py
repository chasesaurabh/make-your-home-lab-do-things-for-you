"""Operator CLI and read-only loopback job board."""
import argparse
from datetime import datetime, timezone
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
    jobs = desk.jobs()
    labels = {"succeeded":"Verified complete", "awaiting_approval":"Waiting for your approval",
              "ready":"Approved; ready to run", "failed":"Stopped; inspect the evidence",
              "needs_reconciliation":"Outcome needs inspection", "cancelled":"Cancelled",
              "queued":"Queued", "inspecting":"Inspecting evidence", "applying":"Applying approved change",
              "verifying":"Checking the outcome"}
    event_labels = {"admitted":"Job received", "claimed":"Worker started", "inspection":"Evidence inspected",
                    "approved":"Exact proposal approved", "intent_persisted":"Operation intent saved",
                    "verifying":"Independent check started", "verified":"Output verified"}
    def stamp(value):
        return datetime.fromtimestamp(value,timezone.utc).strftime("%H:%M:%S UTC")
    for job in desk.jobs():
        proposal = job["proposal"]
        visible = {key: job[key] for key in ("id", "state", "payload", "attempts", "deadline", "approval", "error", "result")}
        visible["proposal"] = proposal
        visible["proposal_digest"] = digest(proposal) if proposal else None
        visible["timeline"] = desk.timeline(job["id"])
        change = ""
        if proposal:
            change = ("<p class='change'>Batch limit <strong>"+str(proposal["before"])+" &rarr; "+
                      str(proposal["value"])+"</strong></p><p>Synthetic worker &middot; target version "+
                      str(proposal["target_version"])+" &middot; approval window ends "+stamp(proposal["expires"])+".</p>")
        outcome = (job["result"] or {}).get("kind")
        explanation = {"effect_verified":"The target receipt, manifest and both output files agree.",
                       "read_only_digest":"The fixture is healthy. No change was needed.",
                       "escalated":"The evidence did not justify an automatic proposal.",
                       "effect_verified_after_cancel":"The effect occurred before cancellation and remains verified."}.get(
                           outcome, "Review the exact proposal before granting permission." if proposal else "The job has not reached a verified outcome.")
        timeline = "".join("<li><time>"+stamp(event["at"])+"</time> "+
                           html.escape(event_labels.get(event["kind"],event["kind"].replace("_"," ")))+"</li>"
                           for event in visible["timeline"][-8:])
        cards.append("<article><span class='eyebrow'>"+html.escape(job["payload"]["case"])+" &middot; "+
                     html.escape(job["payload"]["mode"])+"</span><h2>"+html.escape(labels.get(job["state"],job["state"]))+
                     "</h2><p>"+explanation+"</p>"+change+"<ol>"+timeline+"</ol>"+
                     "<details><summary>Exact proposal, receipt and technical evidence</summary><pre>"+
                     html.escape(json.dumps(visible,indent=2))+"</pre></details></article>")
    verified = sum(job["state"] == "succeeded" for job in jobs)
    waiting = sum(job["state"] == "awaiting_approval" for job in jobs)
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Maintenance Desk</title><style>body{font:16px/1.55 system-ui;max-width:1020px;margin:2.5rem auto;padding:0 1.3rem;background:#f4f3ef;color:#172f3a}"
            "article{background:#fff;border:1px solid #d6dfdf;padding:1.6rem;margin:1.2rem 0;border-radius:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}"
            "h1{font-size:36px;margin-bottom:.2rem}h2{font-size:24px;margin:.3rem 0}.eyebrow{color:#5b6b70;text-transform:uppercase;letter-spacing:.08em;font-size:12px}"
            ".stats{padding:1rem 1.4rem;background:#173e46;color:white;border-radius:10px}.change{font-size:20px}ol{padding-left:1.3rem}"
            "time{color:#63787d;font-size:13px;margin-right:.7rem}summary{cursor:pointer;font-size:14px;color:#365e65}p{margin:.7rem 0}</style>"
            "<header><span class='eyebrow'>Local execution lab</span><h1>Maintenance Desk</h1><p>Give every job a finish line you can check.</p></header>"
            "<div class='stats'>"+str(len(jobs))+" jobs &nbsp; &middot; &nbsp; "+str(verified)+" verified &nbsp; &middot; &nbsp; "+str(waiting)+
            " waiting for approval</div>"+"".join(cards)+
            "<footer><p>Read-only board &middot; Synthetic data only &middot; Times shown in UTC.</p>"
            "<p>Approvals are issued through operator commands. This board has no authentication; keep it on loopback.</p></footer></html>")


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
