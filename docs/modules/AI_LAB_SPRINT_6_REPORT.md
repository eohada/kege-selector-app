# BooStudy AI Lab — Sprint 6.0 report

**Date:** 20 October 2026  
**Scope:** local AI Lab, synthetic data only. No production database, real submissions, pupil records, Docker Runner profile, GigaChat TLS settings, or unrelated integrations were changed.

## Executive summary

Sprint 6 adds a frozen, hash-checked benchmark workflow, separate append-only expert labels, persistent five-module integration coverage, and stronger chunk/resume and usage checks. A mobile/desktop browser matrix found and fixed a course selector overflow, a QA-widget overlap, and small controls in the shared dashboard shell. The deterministic analytics/practice test adapter was corrected to use the same typed evidence contract as BooStudy.

The engineering checks pass, but the sample does **not** establish pedagogical accuracy. Ten live GigaChat generations used the frozen budget. All four AI Homework answers were correctly withheld for manual review because the generated grade was semantically inconsistent. One of three Course answers failed response validation. No independent human labels have been entered, so score accuracy, criterion accuracy, recommendation quality, and model readiness remain unmeasured.

## Isolation and frozen protocol

- Benchmark dataset: `boostudy-ai-lab-sprint6-synthetic-v1`, version 1; 19 cases: 5 development, 3 regression, 11 holdout.
- Fixture SHA-256: `4cd50031fd9d0390ed8d188e3441d586d6654e7f4034012268d1795e30e2d06a`.
- Protocol SHA-256: `159f7cc60871e0ddaf4f50f0687d49206e5abc56041ea805f6a240d8279001b6`.
- The existing Sprint 3 and Sprint 5 fixtures retain their recorded hashes; they were not edited.
- The live protocol was frozen before generation: GigaChat-3-Pro, temperature 0.1, maximum 3,200 completion tokens, strict JSON schema, one generation per case, no automatic semantic retries, maximum 10 logical generations.
- The benchmark and end-to-end flow use separate file-backed SQLite databases under the operating system temporary directory. The browser preview uses its own synthetic Sprint 5 preview SQLite file. The real GigaChat provider was enabled only for the explicitly budgeted benchmark calls; the preview Course/Lesson provider stayed synthetic.
- AI Lesson Intelligence accepts plain or structured text. No ASR, audio uploads, audio conversion, LiveKit, or speech models were added.

The raw records are append-only. Four initial Homework harness errors with `attempt_count=0` were preserved; after fixing the harness, the four cases were run once through the model. The final artifact therefore contains 14 rows, of which 10 contain actual generation attempts. No historical row was rewritten.

## Live GigaChat results

The real model was `GigaChat-3-Pro:32.4.30.3`. All 10 calls received a provider response and each case used one generation.

| Module | Calls | Validated result | Observed limitation |
|---|---:|---|---|
| AI Homework | 4 | 4 provider responses; all 4 were converted to `manual_review` and had no accepted score | Each response had a null score while claiming checked/insufficient-data reasoning inconsistently. The semantic guard prevented an unsupported grade. |
| AI Course | 3 | 2 succeeded; 1 `invalid_response` | The rejected prerequisite-order response lacked the required observation and correction proposal. |
| AI Lesson Intelligence | 3 | 3 structurally valid | Transcript quality and pedagogical correctness remain unreviewed by a human. |

### Usage and latency

| Measure | Recorded value |
|---|---:|
| Provider prompt tokens | 5,601 |
| Cached prompt tokens | 2,228 |
| Full input including cached tokens | 7,829 |
| Completion tokens | 4,029 |
| Provider `total_tokens` | 9,630 |
| Mean response time | 6.08 s |
| Observed response-time range | 4.34–7.33 s |
| API price estimate | unavailable; no tariff is configured |

The provider reports cached prompt tokens separately: `total_tokens` equals prompt plus completion tokens, while full input for this report is prompt plus cached prompt tokens. These are the recorded provider fields, not reconstructed estimates.

### Model catalogue observation

A direct provider catalogue call returned the GigaChat model list once, including GigaChat-3-Pro, before the live run. The generation runner also verified the selected model against that catalogue. In the local browser preview, the catalogue action timed out twice and the UI kept the status **Не проверено**. This was an API response timeout, not a TLS verification failure; no completion was sent by those catalogue requests. It remains an open integration issue and is not claimed as fixed by this sprint.

## Benchmark and deterministic outcomes

The frozen local series contains six Analytics/Practice cases and ran with zero model generations. The final deterministic record is `ai_lab_sprint6_deterministic_run_v4.jsonl`; earlier adapter-development runs remain unchanged and are not used as the final deterministic result.

- Analytics counted two distinct confirmed failures as two observations in two assignments, retained `insufficient_data` rather than asserting a diagnosis, and kept unconfirmed holdout evidence out of confirmed totals.
- Duplicate evidence IDs were counted once.
- Practice recommended the existing synthetic assignment `s6-practice-boundary` when supported failures and prerequisites were present.
- Practice suppressed a recommendation when the course prerequisite `python.conditions` was not confirmed and excluded an already completed assignment.

These are deterministic contract and fixture checks, not an independent expert assessment of pedagogical usefulness.

## Reliability, scale, and integration

The targeted Python suite passed **64 tests**. It covers hash-checked splits, failure records, holdout opt-in, expert-review separation, typed evidence adapters, cross-output live-budget protection, chunk retry/resume after app restart, stale lease reclamation, concurrent identical Course requests, late resolution of an earlier Lesson difficulty, and five-module persistence. A separate CLI guard check using an alternate output path also exited with 0 generations at 10/10 budget used, before either catalogue or completion requests.

The five-module file-backed integration test executes the sequence Course → structured transcript → Lesson Intelligence → Analytics → Practice → Homework → updated Analytics. It confirms versioned course context, preserved source IDs, one retained lesson event, source-separated AI Homework evidence, and persistence after opening a fresh app against the same SQLite file. Provider responses in this test are synthetic; the separate live series above exercises GigaChat.

Analytics history scale test inserted and retrieved **1,207** synthetic Homework evidence records in batches of 37, beyond the page-sized UI history. It verified first/last IDs and an explicit bounded limit. This does not constitute a thousand-record Course/Lesson benchmark or a memory/performance stress test for every database backend.

Long transcript tests cover structured segment IDs, optional timestamps and speaker roles, a transcript crossing chunks, and an early difficulty resolved by a later student response. The merged result remains an AI inference marked as a resolution candidate with the later source reference. No long-transcript live generation was added after the frozen budget was exhausted.

## Browser and mobile QA

Playwright checked five module pages at 1440×900, 1366×768, 1024×768, and 390×844: **20 route/viewport combinations, all HTTP 200, zero geometry failures, zero horizontal overflow, and no page or console errors**.

The audit exposed and led to fixes for:

- the floating QA control overlapping the AI Course selector on mobile;
- AI Analytics and Practice profile selectors extending beyond a 390px viewport;
- shared search, profile, AI Homework navigation/tab, and consent-checkbox touch targets below 40px;
- geometry-audit false positives where an associated checkbox label was the real hit area and where a decorative card overflow was mistaken for clipped text.

The final matrix has no touch-target warnings. Remaining warnings are module-local radius-token findings; they do not indicate overflow, overlap, or an undersized interactive target. Desktop and mobile screenshots are saved under `artifacts/visual/ai-lab-sprint6/`.

## Requirement → implementation → test → actual result → limitation

| Requirement | Implementation | Test | Actual result | Limitation |
|---|---|---|---|---|
| Frozen development/regression/holdout sets | Versioned 19-case fixture and SHA-256 manifest | `python -m scripts.ai_lab_benchmark validate`; hash-drift unit test | 19 cases validated: 5/3/11 across splits; prior fixture hashes intact | Small synthetic dataset; no statistical claim |
| Chunking and recovery | Existing Course/Lesson chunk state strengthened; completed chunks and errors remain in saved operation history | Sprint 6 resilience unit tests for partial progress, restart, stale lease, duplicate concurrent request and cross-chunk resolution | All targeted resilience tests passed; completed progress is reused | No live provider failure injection; no high-volume multi-process soak |
| Usage and provenance | Per-attempt model/version, prompt version/hash, payload hash, parameters, usage, latency, transport and validation status | File-backed integration assertions and frozen live records | All 10 live records contain payload/prompt hashes, model version, settings, usage, and duration | Historic pre-Sprint 6 values are not backfilled |
| Large Analytics history | Keyset-based evidence read independent of the UI history page size | 1,207-row synthetic SQLite history test | Retrieved all 1,207 rows with bounded batching | Course/Lesson scale and production database load were not stress-tested |
| AI Homework semantic checks | Inconsistent score/status responses become `manual_review`; attempt count controls the recorded status text | Service regression test plus four live cases | 4/4 live outputs withheld from automatic scoring; no unsupported score accepted | AI-only run; no matched Code Judge + GigaChat benchmark for these same cases |
| AI Course content checks | Existing source-bound proposal validation and immutable source version | Three live Course cases | 2/3 responses passed structural/content-contract validation; 1 rejected with a specific missing-field reason | No human labels; valid schema does not prove pedagogical correctness |
| AI Lesson text analysis | Structured transcript provenance and cross-chunk merge preserve later resolution | Long transcript and merge tests; three live Lesson cases | All 3 live responses passed structural validation; synthetic resolution test retained the later source ID | Human review and long-transcript live inference remain outstanding |
| Analytics and Practice | Typed evidence adapter and deterministic rules | Six final synthetic cases, zero generations | Duplicate/unconfirmed evidence handled; supported task recommended; missing prerequisites and completed task suppressed | Deterministic oracle coverage is small and does not establish recommendation quality for learners |
| Five-module integration | Real BooStudy module services share stable synthetic course, lesson, skill, task, and evidence identifiers in a file-backed DB | Persistent integration test plus reopen/reload | All five modules and second Analytics pass persisted across app restart | Synthetic provider responses in integration test; no production data |
| Browser/mobile behavior | Added Sprint 6 route/viewport E2E and repaired confirmed shell/module defects | `ai_lab_sprint6.visual.spec.ts` + geometry audit | 20/20 combinations passed; zero geometry FAILs, zero browser errors | Radius-token warnings remain; user-facing Giga catalogue request still times out in preview |
| Independent evaluation | Append-only JSONL labels and module-specific checklist; benchmark metrics exclude unlabeled values | Separate-review join/aggregation tests; score command with empty review file | Review summary reports 0 reviewed and 14 pending rows; no accuracy values are emitted | A human expert still needs to review the 10 actual outputs; four rows are pre-call harness failures |
| Isolation and scope | Temp SQLite for benchmark and file-backed synthetic integration; no Runner/provider security changes | Configuration and route checks plus synthetic browser preview | No production DB or real learner data used; Docker Runner profile and TLS verification untouched | The browser preview uses its existing Sprint 5 synthetic SQLite, not the benchmark artifact DB |

## Sprint 5 → Sprint 6

Sprint 5 established bounded Course/Lesson chunks, resumable history and a 10-case split dataset, with five earlier live calls and incomplete historical usage for some attempts. Sprint 6 adds a single reproducible benchmark runner, a 19-case/11-holdout fixture, explicit expert-label storage, full per-attempt audit fields for the new series, an Analytics history check at 1,207 records, and persistent five-module integration coverage.

The live sample is larger and better audited; **pedagogical accuracy has not been shown to improve** because no independent human labels exist and the Homework outputs remain inconsistent.

## Remaining issues and priorities

- **P0:** none identified in the local synthetic paths exercised here.
- **P1:** browser-triggered GigaChat catalogue requests time out in the preview even though one direct catalogue call and all 10 completion requests succeeded. Diagnose the exact HTTP timeout behavior before declaring model selection reliable.
- **P1:** independent expert labels are pending. Do not publish accuracy, criterion agreement, recommendation quality, or readiness until labels are entered.
- **P1:** the four AI Homework live results require human resolution; all were correctly withheld as `manual_review`.
- **P2:** Course/Lesson thousand-record performance, matched Code Judge vs AI-only vs hybrid comparisons, long-transcript live inference, and API cost remain unmeasured.
- **P2:** module-specific CSS radius-token warnings remain in the visual audit; the shared-shell touch-target, overlap, overflow, and clipping findings were addressed.

**Conclusion:** Sprint 6 delivers quality-measurement and reliability infrastructure, not evidence that BooStudy AI is pedagogically ready for production. Continue only with a new frozen protocol for any additional model calls; the Sprint 6 generation budget is exhausted.

## Main artifacts

- [Frozen protocol](AI_LAB_SPRINT_6_PROTOCOL.md)
- [Demo guide](AI_LAB_SPRINT_6_DEMO.md)
- [Independent review guide](AI_LAB_SPRINT_6_REVIEW.md)
- [Frozen dataset](../../tests/fixtures/ai_lab_sprint6_cases_v1.json)
- [Live run JSONL](artifacts/ai_lab_sprint6_live_run.jsonl)
- [Deterministic run JSONL](artifacts/ai_lab_sprint6_deterministic_run_v4.jsonl)
- [Expert review summary](artifacts/ai_lab_sprint6_expert_review_summary.json)
- [Append-only review labels](artifacts/ai_lab_sprint6_expert_reviews.jsonl)
