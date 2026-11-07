# Tutor Core client contract v1

`app.ai_lab.tutor_core_contract.TutorCoreV1` is the server-side integration facade over the existing Tutor Core. It does not render tasks, submit answers, mutate courses, or create a second scoring engine. Current v1 execution is restricted to the local AI Lab and a verified synthetic SQLite.

## Integration boundary

Each tool is registered by trusted BooStudy server code with a `ClientAdapter`:

- `resolve_event(actor_user_id, subject_id, source_record_id)` reads the authoritative source record and returns a Learning Evidence v2 event. A browser or tool client cannot submit its own “mastered” flag or grade.
- `resolve_skill(skill_id, criterion_id)` resolves the exact stable IDs and returns a title and criterion description. It must return `None` for missing or ambiguous mappings.
- `list_candidates(subject_id, skill_id, criterion_id)` returns only checked Task Bank items. Every item includes a validated answer/checker and provenance: source ID/version, content SHA-256, checker ID/version, `status="verified"`, and exact criterion IDs.

Course, lesson, and assignment context is optional in the Learning Evidence v2 event. If supplied, its existing validator checks its structure. Course recommendations are read-only and delegate to the existing platform Tutor Core, which resolves the assigned individual copy. Applying a course change remains a separate teacher-confirmed operation.

```python
from app.ai_lab.tutor_core_contract import ClientAdapter, TutorCoreV1

core = TutorCoreV1()
core.register_client("zen_trainer", ClientAdapter(
    source_modules=frozenset({"ai_tutor_core"}),
    resolve_event=server_side_attempt_reader,
    resolve_skill=exact_skill_catalog_lookup,
    list_candidates=verified_task_bank_lookup,
))
zen = core.client("zen_trainer")
```

The adapter is server-side code. Do not register adapters from request data.

## Stable v1 surface

The contract identifier is `boostudy.tutor-core-client.v1`; event payloads use Learning Evidence v2. Existing v1 methods and required fields do not change during v1. Additive optional response fields are allowed. Renaming a method, changing a required field or changing decision semantics incompatibly requires a new contract version.

| Client method | Required input | Optional input | Successful result |
|---|---|---|---|
| `profile(actor_user_id: int, subject_id: str)` | Positive actor ID; `platform-student:<positive user id>` | Course/lesson context is not required | Profile card plus normalized event bundle (`event_count`, duplicates, evidence) |
| `record_result(actor_user_id: int, subject_id: str, source_record_id: str)` | Stable source record ID (1–240 chars), resolved by the trusted adapter | Source-specific context is resolved server-side | `event_id`, `stored`, `duplicate`, evidence status |
| `next_practice(actor_user_id: int, subject_id: str, goal: dict)` | Goal description (1–500 chars), exact `skill_id`, exact `criterion_id` | Candidate catalogue and event course context | `action`, candidate or explicit no-material result, evidence and rationale |
| `explain_decision(actor_user_id: int, subject_id: str, goal: dict)` | Same goal as `next_practice` | None | Decision, used/excluded evidence, teacher and student explanations |
| `quiz_specification(actor_user_id: int, subject_id: str, *, skill_id: str, criterion_id: str)` | Exact skill and criterion | `question_count` 1–10 (default 3); `difficulty_range` `[1,5]` (default) | Short-check specification, unused verified candidates and/or authoring shortfall |
| `course_recommendation(actor_user_id: int, subject_id: str)` | Authorized synthetic student | Positive `expected_course_id` | Assigned-copy decision and read-only preview; `course_mutated` is always false |

All methods return a JSON-compatible dictionary containing `contract_version`. They raise `TutorCoreContractError` on invalid or unauthorized calls. Common codes are `safe_local_runtime_required` (503), `invalid_subject` (400), `subject_not_allowed` and `subject_access_denied` (403), and `unknown_client` (403). A source lookup can return `source_event_unavailable` (404); source mismatches or conflicting event IDs return 409. Unknown skills/criteria return 404. Invalid goal, count, range, source ID, or course ID return 400. A missing course projection or course mismatch is a structured `unavailable` / `course_context_mismatch` result rather than an applied change.

Method-specific failures:

| Method | Error/status | Meaning |
|---|---|---|
| `record_result` | `source_event_unavailable` / 404 | Trusted adapter did not find that source attempt |
| `record_result` | `invalid_evidence` / 400, `unverifiable_source` / 400 | Event schema or source/checker/hash provenance is incomplete |
| `record_result` | `source_event_mismatch` / 409 | Source record, subject, module, or requested ID disagree |
| `record_result` | `event_id_conflict` / 409 | Same stable event ID is already stored with different content |
| `next_practice`, `explain_decision` | `invalid_goal` / 400, `unknown_skill_criterion` / 404 | Goal is incomplete or exact mapping is missing/ambiguous |
| `quiz_specification` | `invalid_question_count` / 400, `invalid_difficulty_range` / 400 | Requested short-check constraints are invalid |
| `course_recommendation` | `invalid_course_context` / 400 | Expected course ID is not a positive integer |

No suitable verified exercise is not an exception: practice returns `status="unavailable"`, while a short-check returns a specification and authoring shortfall.

The authenticated server supplies `actor_user_id`; it is not accepted from an untrusted browser payload. The subject must be an active synthetic student in the local allowlist. An actor may access their own student profile or a student they are authorized to access through the platform relationship check. Source adapters must independently resolve the actor's access to the source record. No public HTTP endpoint is introduced by this contract.

## Event shape

Minimum normalized event fields are `contract_version`, `event_id`, `subject_id`, `source_module`, `source_record_id`, `occurred_at`, `evidence_status`, `outcome`, `criteria`, `skill_ids`, `provenance`, and `assistance` (which may be `null`). `assignment` and `course_context` are optional. `attempt_context` is optional and, when known, records:

```json
{
  "attempt_no": 2,
  "material_id": "task-bank:fractions:17",
  "exposure_count": 1,
  "difficulty": 2
}
```

The optional `response` field preserves a trusted source's submitted answer:

```json
{"format": "text", "value": "8/16", "submitted_at": "2026-11-02T12:15:00+03:00"}
```

`value` must be JSON-compatible and no larger than 16 KB. Raw answers are stored only after the trusted server adapter resolves the source record; clients cannot inject them directly. Tools that do not retain answer content may omit it while still providing the verified `outcome` and criterion results.

Every client event requires a source reference, checker/review method, and payload SHA-256; an expert-confirmed result also requires an explicit evaluation revision. Missing assistance remains unknown. Repeated exposure is not treated as an independent success. Unknown exposure or difficulty metadata cannot establish two independent successes or justify raising difficulty.

The source adapter resolves a submitted attempt before it can be recorded. The client sends only its stable source record ID:

```python
zen.record_result(actor_id, "platform-student:123", source_record_id="submission:981")
profile = blitz.profile(actor_id, "platform-student:123")
decision = zen.explain_decision(actor_id, "platform-student:123", goal)
```

Successful event registration returns:

```json
{"contract_version":"boostudy.tutor-core-client.v1","event_id":"zen:attempt:7","stored":true,"duplicate":false,"evidence_status":"technical_confirmed"}
```

The same profile then contains the normalized answer when retained by the source, checker result, assistance metadata, exact skill/criterion, version context, and provenance. The decision separately identifies evidence used and excluded. An insufficient or unverifiable result can mark an item as previously seen while remaining excluded from success/error calculation.

The service stores a validated event under a stable subject/event key. Repeating the same `event_id` and payload returns `duplicate=true`; reusing an ID with different content returns a conflict. Existing module events and client events are merged by the existing Learning Evidence v2 merger. Equal events are counted once; conflicting payloads fail closed.

In the current local safe mode, the event is persisted in the existing `AiLabExperiment` table; no schema migration is required. The `(actor_user_id, request_key)` uniqueness constraint plus conflict recovery makes retries safe across database connections. This is not the production event store.

## Zen client — course-free practice

The caller supplies a goal and exact skill/criterion IDs; a course is not required:

```python
zen.next_practice(actor_id, "platform-student:123", {
    "description": "Проверить сложение дробей с разными знаменателями",
    "skill_id": "math.fractions",
    "criterion_id": "add_common_denominator",
})
```

Example response (shortened):

```json
{
  "contract_version": "boostudy.tutor-core-client.v1",
  "status": "recommended",
  "action": "transfer_check",
  "skill_id": "math.fractions",
  "criterion_id": "add_common_denominator",
  "evidence_refs": ["zen:attempt:7"],
  "candidate": {
    "exercise_id": "task-bank:fractions:18",
    "version": 2,
    "source_id": "task-bank:fractions:18",
    "checker_id": "fraction-equivalence-v2",
    "checker_version": "2.0"
  },
  "model_used": false
}
```

Cold start selects only within the supplied verified candidate set and is labeled diagnostic; it does not claim personalization. With no compatible candidate, the response is `status="unavailable"` and explains that material must be selected or authored. It never invents a task.

`zen.explain_decision(actor_id, subject_id, goal)` returns the deterministic decision plus separate used and excluded evidence references, teacher-facing rationale, and a restrained student-facing explanation. Excluded evidence is identified by status or missing exact skill/criterion pairing; unrelated evidence is counted but does not influence the decision. Unknown exposure or difficulty is not treated as an independent success or as evidence for raising difficulty.

## Blitz client — short-check specification

```python
blitz.quiz_specification(
    actor_id, "platform-student:123",
    skill_id="math.fractions", criterion_id="add_common_denominator",
    question_count=3, difficulty_range=(1, 3),
)
```

The response includes the micro-skill, purpose, type/level constraints, scoring rule, existing unused candidates, and outcome branches. If the verified bank has fewer than three candidates, the response reports the shortfall and returns requirements for an author or separate generator. It does not generate or expose a new question.

For example, when two questions exist for a requested three-question check, the response includes:

```json
{
  "contract_version": "boostudy.tutor-core-client.v1",
  "status": "needs_author_or_generator",
  "question_count": 3,
  "existing_candidates": [
    {"exercise_id": "task-bank:logic:17", "version": 1},
    {"exercise_id": "task-bank:logic:19", "version": 2}
  ],
  "authoring_requirements": {
    "additional_questions_needed": 1,
    "generated_question_is_not_verified": true
  },
  "model_used": false
}
```

After a Blitz implementation evaluates an answer, it uses the same trusted `record_result` flow with its source attempt ID; the specification request itself never creates an attempt or changes the learner's history.

## Course client

```python
course.course_recommendation(actor_id, "platform-student:123", expected_course_id=456)
```

This uses the same evidence bundle as the other clients and delegates to the current assigned-copy Tutor Core calculation. A missing, ambiguous, or mismatched course context is returned explicitly. The response is a preview; `course_mutated` is always false. Existing teacher decision routes remain responsible for applying changes.

Example result (shortened):

```json
{
  "contract_version": "boostudy.tutor-core-client.v1",
  "status": "resolved",
  "subject_id": "platform-student:123",
  "course_id": 456,
  "decision": {"action": "maintain_plan", "evidence_refs": ["blitz:attempt:7"]},
  "preview": {"status": "no_change"},
  "evidence_refs": ["blitz:attempt:7"],
  "model_used": false,
  "course_mutated": false
}
```

## Deterministic and AI responsibilities

Event validation, exact skill/criterion resolution, deduplication, candidate eligibility, repeat detection, and next-step selection are deterministic. The v1 facade makes no model calls. Existing Tutor Core may optionally ask GigaChat for constrained explanatory wording in its separate proposal flow; that wording cannot override evidence, scores, or the deterministic action.

Current limits: this adapter and event storage are synthetic-local only; a production event store, authentication transport, and source adapters for future Zen/Blitz products are not included here. New tools must provide a trusted server adapter before they can submit results.
