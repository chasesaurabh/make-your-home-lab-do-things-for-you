# Make Your Home Lab Do Things for You

Companion code for **Build Local AI Agents That Get Things Done**, by Saurabh Chase.

Three local projects take a task from input to an outcome you can inspect:

- **Maintenance Desk:** durable synthetic jobs, model-selected observations, exact operator approval, a separate target receipt and crash recovery.
- **Inbox organizer:** classify small text notes, review categories and exact quotations, then create verified copies while preserving originals.
- **Service watcher:** check configured loopback HTTP endpoints and write timestamped reports for passing, mismatched and unavailable observations.

The code is MIT-licensed. Book text, covers, model weights and private production records are separate.

## Get the book

**Make Your Home Lab Do Things for You, second edition**, is available on Amazon:

- [Kindle edition](https://www.amazon.com/dp/B0HS96GM7J)
- [Paperback edition](https://www.amazon.com/dp/B0HS8T4YWT)

## Download the version used by the book

Use the [book-v2.0.0 release](https://github.com/chasesaurabh/make-your-home-lab-do-things-for-you/releases/tag/book-v2.0.0). Download the named source ZIP and `SHA256SUMS.txt` for the complete labs, tests and research. Check the archive hash before extracting it. The wheel contains the application package; use the source archive for examples and research.

Application version: **0.2.0**. First-edition readers retain the unchanged `book-v1.0.0` tag and its printed commit reference. The default branch can evolve; use a named release when following the book.

## First run without a model

Use Python **3.12**. From the extracted source directory:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m maintenance_desk rehearsal
.\.venv\Scripts\python.exe examples/inbox_rehearsal.py
```

The application has no third-party runtime dependencies. On Linux, the virtual environment executable is `.venv/bin/python`. The pinned Dockerfile provides a second test lane:

```powershell
docker build -t maintenance-desk:book-v2 .
docker run --rm --network none maintenance-desk:book-v2
```

Both rehearsals grant only operations on their own temporary synthetic fixtures. Ordinary jobs require a separate review and approval. No GPU, account, credentials or private data are needed for these first exercises. A Windows symlink-creation test may skip when the OS account lacks that privilege; the Linux container exercises that boundary.

To install the application for use outside the checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install .
```

This provides `maintenance-desk`, `inbox-desk` and `service-watch` console commands. Building from source may download the pinned setuptools build dependency; it does not download a model.

## Complete a persistent maintenance job

Use the same Python environment throughout. The following example abbreviates its interpreter as `python`:

```powershell
$JobId = python -m maintenance_desk --data data/lab submit event-001 |
  ConvertFrom-Json
python -m maintenance_desk --data data/lab inspect $JobId
python -m maintenance_desk --data data/lab show $JobId
```

Review the target, before/after value, version, evidence and expiry. Obtain the proposal digest from the reviewed job:

```powershell
$Job = python -m maintenance_desk --data data/lab review $JobId |
  ConvertFrom-Json
```

Review the returned proposal and evidence before issuing these separate commands:

```powershell
python -m maintenance_desk --data data/lab approve $JobId `
  --digest $Job.proposal_digest --actor operator
python -m maintenance_desk --data data/lab apply $JobId
python -m maintenance_desk --data data/lab show $JobId
```

Never grant an operation merely because model text recommends it. The normal maintenance proposal expires after five minutes or at the earlier job deadline. For a fresh proposal, submit a new event key such as `event-002`, then inspect and review it. Reusing an old key returns the old job; it does not renew permission.

The board is read-only and loopback-only:

```powershell
python -m maintenance_desk --data data/lab serve
```

Open `http://127.0.0.1:8791/`. Current state, exact evidence, verified changes and healthy checks are distinct. Cancellation after a possible effect preserves the need to reconcile. A succeeded maintenance call returns its historical receipt; it is not a fresh health check of the target.

## Organize notes and collect service reports

The [inbox contract](docs/inbox-contract.md) explains bounds and review semantics. Run `python -m maintenance_desk.inbox --help` for prepare, review, approve, apply, verify and reconcile commands. Input is one folder of up to twelve UTF-8 text files, eight KiB total. Output is a new job directory with controlled filenames, copies, an index and a receipt. A valid quote does not prove a category is right; operator review matters.

The [service-watch walkthrough](docs/service-watch.md) includes a disposable HTTP fixture and exact commands for success,503 failure and a stopped service. Use only explicitly configured read-only loopback endpoints. A passing configured status/marker check is not a claim that every service function is healthy.

## Add a local model

`examples/fetch_model.py` downloads and verifies the exact artifacts in `configs/model-artifacts.lock.json`. `examples/serve_model.py` starts the pinned vLLM image after verifying those files, checks the served model ID and sends an actual inference probe. See [local model setup](docs/model-setup.md).

Available profiles are2B,9B,27B and122B NVFP4. Disk size is not minimum VRAM. Runtime allocations, cache settings and quantization matter; the larger profiles need substantially more capacity. The runtime image uses NVIDIA GPU access in Docker Linux containers. Weights retain their own licenses and are never included in a code release.

The application accepts an explicit loopback endpoint, bypasses proxies and refuses redirects. There is no hosted fallback. Maintenance inference selects bounded observations; inbox inference proposes categories and grounded quotes. Neither can grant approval, choose arbitrary write paths or issue shell commands.

## Research and limits

Read [observed evidence](EVIDENCE.md), [tested versions](VERSION_MATRIX.md) and the frozen [study plan](research/study-plan.json). The study separates deterministic checks from actual model inference. It retains failed results and measures semantic decisions separately from verified effects. Repeated synthetic fixtures do not establish general incident-detection accuracy or household time savings.

This is a one-operator local system. Operator labels are not authentication. Keep sources, databases and outputs in directories you control. The service watcher is read-only; the organizer makes copies; the maintenance target changes only its disposable synthetic fixture. Offline snapshots require stopped workers and revoke old grants on restore. No production restart, arbitrary shell/SSH execution, credential management or backup of personal files is implemented.

See [security](SECURITY.md), [contributing](CONTRIBUTING.md), the [version manifest](release-manifest.json) and [MIT license](LICENSE).
