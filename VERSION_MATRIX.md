# Tested versions — book-v2.0.0 / application0.2.0

| Component | Recorded configuration | Scope |
|---|---|---|
| Native Python | CPython3.12.14 | Windows CLI, deterministic and file/report exercises |
| Container | CPython3.12.15; SQLite3.40.1 | Network-disabled tests; study harness |
| Application | home-lab-maintenance-desk0.2.0 | Maintenance, inbox and service-watch entry points |
| Runtime dependencies | Standard library | No third-party application packages |
| Build dependency | setuptools84.2.1 | Pinned source builder |
| Model server | vLLM0.30.0; pinned image digest | Actual structured inference on four profiles |
| GPU | RTX PRO6000 Blackwell97,887MiB;driver582.16 | Sequential study, not minimum requirements |

The supported Python range is>=3.12,<3.13. Source and Linux tests exercise actual local HTTP fixtures and child-process recovery. Native Windows may skip symbolic-link creation when the OS denies that privilege; Linux executes it. Exact final release test counts and acquisition checks are recorded with the release.

The model files/revisions/hashes are in `configs/model-artifacts.lock.json`. Startup uses context4096,one sequence,eager mode and explicit loopback binding. Study requests disable thinking and use temperature0. The122B profile uses NVFP4 weights/FP8 KV cache; the smaller profiles use unquantized weights/automatic KV dtype. Model file sizes do not imply minimum VRAM.

The application is a one-operator local tool. Actor names are labels, not authentication. Inbox output is copy-only with separately reviewed exact grants. Service reports observe configured read-only GET endpoints and perform no repair. Maintenance effects remain synthetic. Offline snapshot/restore covers the maintenance data root and revokes old grants; it is not a backup service for arbitrary personal files.

Final candidate verification: 101 tests pass in network-disabled Linux. Native Windows runs 101 tests with one explicit OS symlink-privilege skip; the Linux lane exercises that case. These include seven study-integrity tests, a bounded-copy check and cancelled-effect restore validation.
