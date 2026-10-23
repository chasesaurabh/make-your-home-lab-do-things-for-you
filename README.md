# Make Your Home Lab Do Things for You
## Build Local AI Agents That Get Things Done — companion code

**Maintenance Desk is a synthetic execution lab.** It persists jobs, reads bounded diagnostics/runbooks/incidents, proposes one disposable setting change, waits for operator approval, applies it and verifies actual output bytes. Jobs and the target use separate databases to expose uncertain external effects.

MIT licensed. The book is in production. The verified published-book link will be added after publication. The finished edition's `book-v1.0.0` tag has not been created.

## Requirements and first run

Use Python 3.12 and Git. The source workflow has no third-party runtime packages. No GPU, model, account, credentials, or real home-lab services are needed for deterministic work. Keep data directories disposable.

```powershell
git clone https://github.com/chasesaurabh/make-your-home-lab-do-things-for-you.git
cd make-your-home-lab-do-things-for-you
python --version
python -m unittest discover -s tests -v
python -m maintenance_desk rehearsal
```

The rehearsal uses a fresh temporary sandbox, displays its synthetic proposal, issues a demonstration-only operator grant, applies the change, reopens the application, checks its receipt and duplicate call, and removes temporary data. Normal jobs always wait for an operator. `python -m maintenance_desk demo` retains the smaller one-database teaching experiment.

## Persistent job walkthrough

```powershell
python -m maintenance_desk --data data/lab submit event-001
python -m maintenance_desk --data data/lab list
```

Replace JOB_ID below with the returned ID. No command placeholder is a secret.

```powershell
python -m maintenance_desk --data data/lab inspect JOB_ID
python -m maintenance_desk --data data/lab show JOB_ID
python -m maintenance_desk --data data/lab board --output data/board.html
```

Review target/version, policy, expiry, evidence digest and exact before/after batch_limit. Print the proposal fingerprint:

```powershell
python -c "from maintenance_desk.engine import Desk; from maintenance_desk.contracts import digest; d=Desk('data/lab'); print(digest(d.get('JOB_ID')['proposal'])); d.close()"
```

Replace PROPOSAL_DIGEST with that value. Approval expires five minutes after proposal creation or at the earlier job deadline.

```powershell
python -m maintenance_desk --data data/lab approve JOB_ID --digest PROPOSAL_DIGEST --actor operator
python -m maintenance_desk --data data/lab apply JOB_ID
python -m maintenance_desk --data data/lab show JOB_ID
```

Success requires a persisted target receipt plus independent manifest/output-byte checks. Reapplying a succeeded job returns its historical result; it does not repeat an effect or prove that nobody changed the target later. Failed or unresolved writes are never silently retried.

Use cancel JOB_ID before an effect or revoke JOB_ID before apply. Cancellation after an effect requests reconciliation and preserves the truth that the effect occurred. Operator names are audit labels, not multiuser authentication. Anyone controlling the OS account and databases controls this lab.

## Local-model triage

Supply a working compatible endpoint and served model ID. The companion does not install, download, or restart model servers. It accepts loopback HTTP only, refuses proxies/redirects, and has no hosted fallback.

```powershell
python -m maintenance_desk --data data/agent submit agent-001 --mode agent
python -m maintenance_desk --data data/agent inspect JOB_ID --endpoint http://localhost:8100/v1 --model YOUR_SERVED_MODEL_ID
```

The model may select named observation tools, finish or escalate. Application code validates the evidence and constructs any bounded proposal. The model cannot grant approval or invoke apply. The loop has five decisions, bounded context/output, a 60-second inspection budget, finite network timeouts and at most one retry per selected transient read failure. Software budgets are not real-time scheduling guarantees.

Tests label scripted providers as stubs. Live-model evaluation is separate. Fixtures and prompts are synthetic; this is not prompt-only evaluation, real incident detection, or a study of household labor savings. Raw responses are retained for synthetic exercises; redesign logging before sensitive use.

## Events, schedules, worker and board

```powershell
python -m maintenance_desk --data data/lab tick hourly --period 3600
python -m maintenance_desk --data data/lab work --cycles 5 --interval 1
python -m maintenance_desk --data data/lab work --cycles 10 --interval 10 --schedule hourly --period 3600
python -m maintenance_desk --data data/lab recover
python -m maintenance_desk --data data/lab serve --port 8791
```

The worker inspects queued jobs and applies only previously approved ready jobs. It never issues grants. Agent-mode work needs explicit --endpoint and --model on the worker command. Periodic admission uses UTC epoch intervals and latest-bucket-only policy: duplicate ticks produce one job; missed intervals are not replayed. There is no local-wall-clock/DST cron parser. OS-scheduler installation is not bundled.

The board binds 127.0.0.1, serves only /, is read-only, and escapes displayed text. It has no account authentication or mutation endpoints. Keep it off the LAN and use synthetic data. The worker is a bounded teaching runner, not a distributed scheduler. Concurrent claim races may return "job unavailable"; catch that conflict at the caller.

## Recovery and offline snapshots

Tests launch separate processes that exit immediately: 71 before target commit; 72 after target commit. These are internal test switches, not normal CLI actions. An expired write lease enters needs_reconciliation. A matching receipt permits independent verification. Missing receipts, partial artifacts or tampered output remain unresolved. Do not delete artifacts to force a retry; inspect timeline and target first.

Stop all workers and board processes before snapshotting. These offline file copies do not guarantee consistency against concurrent writers. Restore to a new directory; pending grants are revoked.

```powershell
python -m maintenance_desk --data data/lab snapshot data/snapshot-001
python -m maintenance_desk --data data/restored restore data/snapshot-001
python -m maintenance_desk --data data/restored list
```

Use a new snapshot name. A checksum manifest rejects corrupted data. This recovers the synthetic app; it is not backup software for user files. After stopping processes, remove only your chosen disposable data directories. No system service is installed.

## Tests and comparisons

```powershell
docker build -t home-lab-do-things:dev .
docker run --rm --network none home-lab-do-things:dev
python -m maintenance_desk.evaluate --lane development --endpoint http://localhost:8100/v1 --model YOUR_SERVED_MODEL_ID --output data/development-run-001.json
python -m maintenance_desk.evaluate --lane holdout --endpoint http://localhost:8100/v1 --model YOUR_SERVED_MODEL_ID --output data/holdout-run-001.json
```

The Docker base is pinned by digest. Each lane compares deterministic and agent triage on twelve fixed cases in fresh temporary sandboxes. It records dispositions, wrong-success/unauthorized-effect counts, token telemetry, latency, traces and failures. Existing evidence files are never overwritten. The evaluator's automatic grants apply only to its temporary synthetic targets. Holdout fixtures are additional narrow variants, not evidence of generalization to real systems. Freeze prompts/rubric before first holdout and preserve failures.

## Chapter map

| Chapters | Sources |
|---|---|
| 1–4: completion, baseline, persistence | contracts.py, store.py (F0), engine.py |
| 5–8: model, tools, evidence, loop | provider.py, contracts.py |
| 9–12: approval, action, verification | engine.py, target.py, cli.py |
| 13–16: events, leases, recovery | engine.py, snapshot.py, process-crash tests |
| 17–20: timeline, comparison, rehearsal | cli.py, evaluate.py, rehearsal.py |

No shell, SSH, host administration, production restarts, actual backups, user-file transformation, credential management, MCP transport, voice/vision or multiple-agent implementation is included. See [security](SECURITY.md), [contributing](CONTRIBUTING.md), [versions](VERSION_MATRIX.md), [manifest](release-manifest.json), and [MIT license](LICENSE). Manuscript, art, production assets, weights, private logs and personal data stay outside this repository.
