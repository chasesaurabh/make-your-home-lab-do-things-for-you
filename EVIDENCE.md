# Observed development evidence

October 23, 2026. These results describe the supplied synthetic cases under one configuration. They are not general model benchmarks, a security certification, real backup tests or household time-savings evidence.

The first development run used a static JSON decision schema. The deterministic path reached the expected disposition in 12/12 cases; the model-assisted path did so in 3/12. Repeated observation requests caused most model failures; one decision violated schema. Application checks refused those requests. The original failed run is retained in the book production evidence.

The revised request explicitly lists remaining observation tools and constrains the JSON schema to that list. On the second development run, both paths reached the expected disposition in 12/12. The model-assisted path used 36 calls and 9,789 reported tokens. The prompt/rubric were then frozen before the first holdout.

On twelve additional holdout variants, both paths reached the expected disposition in 12/12. There were zero observed unauthorized effects and zero false-success outcomes in this fixed suite. Model-assisted triage used 37 calls and 10,210 reported tokens; its median case time was 8.493 seconds and nearest-rank p95 was 11.438 seconds. Baseline median was 0.0705 seconds and p95 0.563 seconds. Twelve observations are a small sample; p95 here is the largest observation, not a population estimate. No run was excluded.

These fixtures did not establish a completion advantage for the model. The deterministic workflow remains the default execution path. The optional bounded agent demonstrates model-selected observations and explanations inside application-owned policy; it does not justify multiple agents or replacing deterministic execution.

The server was existing, warm and shared; requests ran sequentially. Timing includes application/fixture work and was not isolated from other workloads. Dollar cost is unknown; no power or depreciation measurement was made. “No API bill” must not be interpreted as free operation. Tests of scripted providers are separate from real inference.

See observed-results.json for aggregate values, model-manifest.json for service/artifact identity, and evaluate.py for the frozen rubric/evaluator. The additional holdout cases are narrow variants of the same fixtures and remain inspectable; they do not prove out-of-distribution generalization. Synthetic automatic operator grants occur only in new temporary evaluation directories, not in normal jobs.
