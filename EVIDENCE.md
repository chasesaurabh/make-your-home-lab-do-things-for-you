# Observed local-model evidence

Measured November 16, 2026 UTC. Four actual inference profiles, synthetic inputs and actual disposable file effects. Twelve distinct maintenance cases and twelve distinct notes, repeated three times. Repetitions are not independent new tasks. Raw requests/responses, failures and scores are retained in `research/results`; no private paths, credentials, book prose or weights are included.

## Maintenance

The deterministic baseline reached 36/36 for every profile. Model-assisted outcomes:

| Profile | Correct /36 | Median seconds | p95 seconds | HTTP calls |
|---|---:|---:|---:|---:|
| 2B | 27/36 | 2.980 | 5.090 | 111 |
| 9B | 36/36 | 2.375 | 4.007 | 102 |
| 27B | 36/36 | 3.123 | 4.381 | 93 |
| 122B | 35/36 | 5.909 | 8.704 | 97 |

## Inbox

| Profile | Correct labels /36 | Exact batches /9 | Median seconds | p95 seconds |
|---|---:|---:|---:|---:|
| 2B | 27/36 | 3/9 | 4.999 | 5.677 |
| 9B | 33/36 | 6/9 | 5.650 | 6.013 |
| 27B | 36/36 | 9/9 | 10.232 | 11.184 |
| 122B | 36/36 | 9/9 | 12.969 | 18.049 |

All model batches supplied 36 grounded quotes and 9 verified copies per profile. Grounded quotations and verified files do not establish correct semantic labels. The no-model staging route assigns everything to uncertain: 9/36 matching labels, 0/9 exact batches, 9/9 verified copies. It is not a competitive semantic classifier.

No unauthorized maintenance effects or false successes were observed under the recorded definitions. The 2B model nevertheless missed 9 outcomes, and 122B unnecessarily escalated one. No failed run is removed. These are finite-suite observations, not general accuracy or safety estimates.

## Recompute

```powershell
python research/analyze_study.py research/results/holdout-2b.json `
  research/results/holdout-9b.json research/results/holdout-27b.json `
  research/results/holdout-122b.json --output my-summary.json
```

Use a new output filename. The verifier rejects incomplete studies, missing/duplicate rows, changed configuration fingerprints, altered expected maintenance outcomes, mismatched stored scores and ungrounded quotes. Seven regression tests exercise these integrity checks. `research/summary.json` is the shipped recomputation, with hashes of each raw file.

For a new inference run, start a pinned profile using `docs/model-setup.md`, then run `research/run_study.py --help`. Use its explicit endpoint, model alias, profile label, holdout lane, three repeats and a new output file. The profile label is not server-identity verification; retain startup artifact checks and actual runtime configuration.

## Conditions and provenance

RTX PRO6000 Blackwell 97,887 MiB, driver 582.16; vLLM 0.30.0 pinned image; Linux Python 3.12.15 / SQLite 3.40.1 harness. One warmed model at a time, one sequence, context 4096, eager execution, temperature 0, thinking disabled. Smaller profiles are unquantized; 122B uses ModelOpt NVFP4 and FP8 KV cache. Memory fractions were 0.18 / 0.35 / 0.73 / 0.88, not minimum-VRAM recommendations.

Timings include temporary workflow work and were collected on a working host. They are not isolated throughput, cold-start measurements or population-tail estimates. p95 is nearest rank: 35th/36 maintenance observations and maximum/9 inbox batches. First task time is retained separately. Electricity, depreciation and dollar cost were not measured.

`research/measurement-source.json` identifies the frozen measurement implementation. Later release changes add review CLI output, evidence analysis, a schedule-key migration edge fix, bounded reads for altered inbox copies and validation of cancelled-but-verified effects during restore; the inference prompts, rubric and task execution in the study remain unchanged. The 122B run used an exact archive of the measurement commit after that unrelated schedule fix was made in the working tree.

Original October development failures and holdout records are retained under `research/legacy`, with root `observed-results.json` and `model-manifest.json` describing that historical configuration. They are not the new model matrix. The maintenance fixtures are published regression cases; the new inbox holdout was reserved from six development notes. Published fixtures are no longer unseen once used for tuning.
