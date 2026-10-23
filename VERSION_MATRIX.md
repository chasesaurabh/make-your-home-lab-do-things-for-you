# Tested versions and limits — development 0.1.0

| Component | Observed/tested configuration | Scope |
|---|---|---|
| Windows | Windows 11 Pro 10.0.26300, PowerShell 7.6.5 | Native deterministic/recovery tests and synthetic live evaluation |
| Native Python | CPython 3.12.14; SQLite 3.53.1 | 51 tests, complete temporary rehearsal, separate clean-venv package installation |
| Linux container | Python 3.12.15 slim Bookworm, pinned amd64 manifest in Dockerfile | Network-disabled deterministic suite; final output recorded in book production evidence |
| Runtime dependencies | Python standard library only | No third-party runtime packages |
| Optional package builder | setuptools 84.2.1 pinned in pyproject.toml | PyPI reported zero advisories on October 23, 2026; this is a dated check |
| Local model | Existing vLLM 0.30.0 service, requested nemotron-super-120b-fp4 | Supplied-evidence fixtures only; see model-manifest.json and EVIDENCE.md |
| macOS | Not tested | No native macOS support claim |
| Python outside 3.12 | Not tested | Packaging intentionally requires >=3.12,<3.13 |

The production model's returned alias differs from its configured root. The model manifest records them separately and identifies the cached snapshot and metadata checksums; weights are not redistributed. A different runtime, model/template, fixture or prompt requires new measurements. There is no guarantee of equivalent results on a different endpoint.

Snapshots are offline-only and revoke pending grants on restore. Periods are UTC epoch intervals with latest-bucket-only admission, not calendar/DST scheduling. Local labels are not authentication. The app is a synthetic one-host teaching system, not a production or distributed scheduler.
