# A local service report you can verify

Start the fixture in one terminal from the source archive:

```powershell
python examples/demo_health.py
```

In a second terminal, use the same Python environment and repository directory:

```powershell
New-Item -ItemType Directory -Force data
python -m maintenance_desk.service_watch collect --config configs/demo-services.json --output data/service-report-001 --rounds 3 --interval 1
python -m maintenance_desk.service_watch verify data/service-report-001
```

Open `REPORT.md` for the short result and `observations.json` for status codes,
marker tests, UTC times and durations. The first run should pass all three probes.
Stop the fixture with Ctrl+C, restart it with `--status 503`, and collect into a
different output directory. The status mismatch must appear in the report.
Stop it again and collect a third report: inability to observe a service is a
distinct result, never a healthy state. Existing report directories are refused.

Replace the fixture configuration with your own explicit numeric loopback health
URLs when ready. Configure only endpoints whose GET operation is read-only. The
collector permits up to eight services, checks the expected status plus a required
body marker, refuses redirects, reads at most 16 KiB per response, and never sends
credentials or follows model-provided URLs. It records a body hash rather than
copying the body into the report. It supports 1..12 rounds and 0.1..60-second
intervals between completed rounds. This is a finite observation session, not a
resident monitoring daemon or a calendar scheduler. The socket timeout bounds
idle I/O; it is not a hard wall-clock deadline against a deliberately streaming
server. Use the configured trusted local health endpoints.

The report is deterministic. An LLM does not make a status comparison more
accurate. A passing probe means this exact HTTP check passed at the recorded time;
it says nothing about unobserved disk space, authorization, data correctness or
other dependencies. The module has no restart or repair operation.

Checksums detect later changes to report bytes; they are not signatures proving
who generated the report. Keep the output in a directory you control. The writer
does not overwrite an old report or resume a partial report; preserve a partial
directory for inspection and collect into a new one.
