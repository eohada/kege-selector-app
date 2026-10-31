# AI Lab Sprint 7 — frozen synthetic protocol

Frozen on 2026-10-20 before any Sprint 7 generative request. The dataset and this protocol are verified by SHA-256 in `tests/fixtures/ai_lab_sprint7_manifest_v1.json`.

## Scope and budget

- Only local AI Lab synthetic fixtures; no real students, homework, production, or Docker profile changes.
- At most 12 logical generation requests: 8 Homework (four matched AI-only/Hybrid pairs), 2 Course, 2 Lesson. No automatic completion retry or repair call. A provider request counts even if the response fails.
- Exactly one serial request per frozen case. The runner writes a reservation before each request and refuses to reuse a reserved case after interruption. No holdout cases are used.
- A catalogue GET is a prerequisite and not a generative request. If credentials, catalogue, secure Code Judge, or deterministic expectations fail, stop before generating.
- GigaChat-3-Pro with default temperature 0.1, max_tokens 3200 and provider's default top_p where the module does not override it. Actual parameters from every provider response are stored.

## Versions and comparisons

- Homework uses a new saved instruction version containing `SEMANTIC_RELIABILITY_PROMPT_TEXT`; historical v1 remains unchanged. Run each case against the stable Python assignment `ai-lab.python.classify` version 1 and its saved Code Judge test set. The AI-only call does not receive a Judge run ID. Hybrid receives the same code and the verified Judge run ID; hidden tests are removed from the provider payload.
- Course uses `ai-course-analysis.v5`, which clarifies that structural findings are not material text proposals. Lesson uses its current version pinned by the manifest. Previous outputs are immutable.
- Four Homework solutions span an alternative correct algorithm, one partial error, several errors, and a boundary error. The same source and criteria appear in each pair. The deterministic Judge report and frozen expert expectation are compared separately with the model's raw answer and final guarded result.
- Course/Lesson cases refer only to frozen Sprint 6 development/regression inputs. Their frozen SHA-256 is checked; no disclosed holdout is claimed as new evidence.

## Measurement and stopping

- Store request/response audit, payload hash, model version, parameters, full token usage, latency, validator status, final result and technical errors in append-only JSONL. Preserve raw model response. An error before the provider call is a harness failure, not model quality.
- Report AI-only, deterministic Judge and Hybrid separately. Do not attribute a Judge-authoritative score to the model's unaided reasoning. Do not count a structurally valid response as human-verified pedagogical quality.
- Human ratings are entered only by an authenticated administrator in Quality Review. Codex and GigaChat do not populate human ratings. Skipped/NA ratings are excluded from denominators.
- Stop on authentication, quota, rate-limit, certificate or network failure. Do not silently retry a failed generation. A technical interruption may leave unused budget; report actual requests.
