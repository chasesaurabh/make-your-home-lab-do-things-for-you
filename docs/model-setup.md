# Run the pinned local model

Start with the no-model rehearsals in the README. This lane adds real inference using NVIDIA GPU access in Docker Linux containers. Select Python 3.12 and run commands from the extracted source root. Commands below use PowerShell; replace `python` with the explicit virtual-environment interpreter if needed.

## Check the host and retrieve artifacts

```powershell
python --version
docker version
docker info --format '{{.OSType}}'
nvidia-smi
```

Docker must report Linux containers and the host driver must see the GPU. Install/configure Docker and the NVIDIA driver using their current official instructions before proceeding. The helper does not install drivers or configure virtualization. On Windows, Docker Desktop's supported GPU path uses its WSL2 backend. This is a tested NVIDIA runtime recipe, not a native macOS recipe.

The release locks four profiles in `configs/model-artifacts.lock.json`:

| Profile | Artifact repository | Locked files, GiB | Weight format |
|---|---|---:|---|
| 2b | Qwen/Qwen3.5-2B | 4.26 | Unquantized |
| 9b | Qwen/Qwen3.5-9B | 18.00 | Unquantized |
| 27b | Qwen/Qwen3.5-27B | 51.77 | Unquantized |
| 122b | nvidia/Qwen3.5-122B-A10B-NVFP4 | 77.79 | NVFP4 |

These are artifact sizes, not VRAM requirements. Runtime buffers, context, KV cache, free device memory and precision affect startup. The 122B profile is a mixture-of-experts model with different precision; parameter count alone does not predict latency or quality. Read the model licenses separately; weights are not included in this MIT repository.

Choose a new directory on a disk with sufficient free space:

```powershell
$ModelDir = Join-Path $PWD 'models/qwen-2b'
python examples/fetch_model.py 2b --destination $ModelDir
python examples/fetch_model.py 2b --destination $ModelDir --verify-only
$Lock = Get-Content configs/model-artifacts.lock.json -Raw |
  ConvertFrom-Json
docker pull $Lock.runtime_image
```

Downloads use the exact repository revision and verify every locked file's size and hash. Verified existing files are reused. A `.partial` file is retained after interruption: inspect it or choose a new destination, rather than assuming it is valid or deleting unrelated files. No authentication token or remote Python code is required by these helpers. The model download and image pull require Internet access; later inference is local.

Check GPU access inside the pinned image:

```powershell
docker run --rm --gpus all --entrypoint nvidia-smi $Lock.runtime_image
```

## Start, observe, and make a real request

```powershell
python examples/serve_model.py 2b --model-dir $ModelDir `
  --name automation-model-2b --port 18107 `
  --memory-fraction 0.18 --evidence startup-2b.json
```

The recorded study used memory fractions 0.18, 0.35, 0.73 and 0.88 for the four profiles on its recorded device. These fractions reserve a share of total device memory; they are not portable minimum-memory recommendations. On another GPU, inspect available memory and use a suitable fraction that leaves room for other processes. A model that cannot fit should fail rather than silently switch to a hosted service.

The helper checks all files before starting a container, mounts weights read-only, binds only `127.0.0.1`, disables Hub access inside the server, limits context to 4,096 and concurrency to one, and uses eager execution. The 122B profile uses FP8 KV cache and ModelOpt FP4 weights; other profiles use automatic KV dtype. First initialization can take time to load files and compile kernels. A 30-minute observation limit retains the container for diagnosis on failure.

Readiness requires the expected model ID from `/v1/models` and a real chat completion. Check `probe_exact_match` in the saved evidence: a nonempty response is recorded even if it differs from `READY`. The application rehearsal checks a more demanding structured response:

```powershell
python examples/inbox_rehearsal.py `
  --endpoint http://127.0.0.1:18107/v1 --model automation-2b
```

This rehearsal approves copies only in its own temporary fixture. It does not grant approval for a real inbox. Ordinary jobs retain separate review, exact-digest approval, application and verification steps.

## Diagnose and stop

```powershell
docker logs automation-model-2b
Invoke-RestMethod http://127.0.0.1:18107/v1/models
docker stop automation-model-2b
```

If the container exits, inspect logs for driver, allocation or artifact errors. A healthy endpoint with an unexpected model ID is not the requested configuration. The application records malformed responses, timeouts and provider errors without pretending the task succeeded. It has no hosted fallback.

Stopping releases GPU resources and retains logs. The helper refuses an existing name and evidence filename, including stopped containers, so inspect previous runs before deliberately choosing a new name. Run only one profile at a time for comparable observations. Startup evidence includes local paths: keep it private or sanitize it before sharing. Public study records contain synthetic inputs and reviewed configuration instead.

For the measured results, limitations and reproduction commands, see [EVIDENCE.md](../EVIDENCE.md). The frozen artifact lock and recorded runtime, prompts and fixtures are part of the configuration; changing any of them requires a new result record.
