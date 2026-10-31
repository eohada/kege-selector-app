# AI Lab Sprint 6 — frozen evaluation protocol v1

Status: frozen before Sprint 6 live generations.

## Scope and isolation

- Synthetic educational inputs only; no learner submissions, identities, or production database.
- The run uses a dedicated file-backed SQLite database under the operating system temporary directory.
- The existing Sprint 3 and Sprint 5 fixture files and their frozen checks remain unchanged. Sprint 5 holdout cases are never development inputs.
- Local deterministic checks cover all five modules. Live GigaChat calls cover only Homework, Course, and Lesson; Analytics and Practice are deterministic evidence consumers and do not require generation calls.

## Frozen live sample

At most 10 logical GigaChat generations, with no automatic semantic retries:

| Module | Cases | Purpose |
|---|---:|---|
| Homework | 4 | fully correct, alternate correct algorithm, one boundary error, insufficient test evidence |
| Course | 3 | no unsupported finding, explicit prerequisite defect, concrete factual contradiction |
| Lesson | 3 | later resolution of an early difficulty, question without confirmed difficulty, contradictory/incomplete transcript |

The exact live case IDs are `hw-dev-correct-return`, `hw-regression-alternative-loop`, `hw-holdout-boundary-error`, `hw-holdout-insufficient-evidence`, `course-dev-no-finding`, `course-regression-prerequisite-order`, `course-holdout-factual-error`, `lesson-dev-explicit-difficulty`, `lesson-regression-later-resolution`, and `lesson-holdout-question-is-not-difficulty`.

All 19 synthetic cases and their expectations are stored in `tests/fixtures/ai_lab_sprint6_cases_v1.json`; its SHA-256 is recorded in the run manifest before any live call. Eleven cases are marked `holdout` across the five modules. Expectations are fixed in advance. Holdout results are read-only and are not used to change prompts or validators.

## Model and generation settings

- Model alias: `GigaChat-3-Pro`.
- Prompt versions: Homework default saved version 1 with SHA-256 `c756dd761c61d2c3593dc243523d1f3d5fbfb7e7d9c3bc712582d25bebed88db`; Course `ai-course-analysis.v4`; Lesson `lesson-intelligence.v4`. Each output record must store the exact prompt version and source payload hash. A missing version is a failed audit record, not an inferred value.
- Generation settings: `temperature=0.1`, `max_tokens=3200`, `top_p=null`, `response_format=json_schema_strict`. Record the effective settings returned by the provider for every attempt.
- No catalogue request is part of the generation budget. No call is repeated automatically. A failed or invalid response consumes its logical call and remains in the result set.

## Scoring and stop rules

- Expert expectations are authored independently of the model response. Expert scoring is entered separately and remains `pending` until reviewed; pending cases do not count as successes or failures in accuracy metrics.
- Compare AI-only Homework, deterministic Code Judge, and hybrid Homework separately when the existing service supports all three from the same frozen input.
- Course and Lesson are reviewed on content, evidence references, unsupported claims, and stated limitations. Analytics and Practice are measured against deterministic synthetic evidence oracles.
- Stop immediately on any data-scope violation, unexpected real/production database use, secret exposure, TLS/security regression, or persistent-state contamination.
- Stop additional live calls after 10 logical generations, or earlier on quota exhaustion, authorization failure, provider outage, or materially incomplete audit data. Do not retry to improve scores.
- Do not claim statistical significance or production readiness from this sample.

## Required run record

For each executed case, persist the dataset and case IDs, split, exact payload hash, module/prompt version, model/version, effective generation settings, response or transport error, structural validation, technical evidence, input/cached/output/total token counts when provided, elapsed time, and independent expert-review status. Unknown historical usage remains unknown.
