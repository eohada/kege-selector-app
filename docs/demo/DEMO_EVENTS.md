# BooStudy Demo Experience — Semantic Events

Events below are collected from `app/demo/routes.py`, `app/demo/service.py`, `demo_engine.js`, `boo_companion.js` and tests.

| Event | Trigger | State change | Idempotent? | Chapter |
|---|---|---|---|---|
| `transition_step` | engine moves scene | requested validated step | no: stale transition returns 409 | all |
| `choice_*` | Chapter 1 answer | history/reaction | completed action semantics | 1 |
| `demo:chapter2:started` | dashboard handoff | chapter 2 mission | yes | 2 |
| `demo:dashboard:program_explored` | program target | discovery action | yes | 2 |
| `demo:dashboard:lesson_explored` | past lesson target | discovery action | yes | 2 |
| `demo:dashboard:assignments_explored` | assignments target | discovery action | yes | 2 |
| `demo:chapter2:module_opened` | course module | history/scene | yes | 2 |
| `demo:chapter2:trial_discovered` | all discovery complete | unlock trial | yes | 2 |
| `demo:trial:opened` | trial card/workspace | trial scene | yes | 3 |
| `demo:chapter3:mode_prompted` | answer/code mode | mode flag | yes | 3 |
| `trial_completed` | correct answer/code | victory | yes | 3 |
| `trial_attempt_failed` | wrong answer | trial retry | recorded in service history | 3 |
| `demo:library:material_opened` | theory material | `library_opened` | yes | 4 |
| `demo:mistakes:review_opened` | reviewed submission | `mistakes_opened` | yes | 5 |
| `demo:mistakes:corrected` | correct retry answer | `mistakes_fixed` | yes | 5 |
| `demo:route:module_opened` | route module | `route_opened` | yes | 6 |
| `demo:wins:analytics_opened` | analytics progress | `wins_opened` | yes | 7 |
| `demo:schedule:week_opened` | week view | `schedule_opened` | yes | 8 |
| `demo:profile:achievements_opened` | achievement target | `profile_opened` | yes | 9 |
| `demo:finale:shown` | finale rendered | session reward flag | yes | 10 |
| `demo:finale:cta_*` | finale CTA click | history/choice | yes by event guard | 10 |
| `demo:branch:*` | permitted detour | history only | yes | 2–9 |

## Legacy/unused or non-canonical names

- `demo:dashboard:explored` and `demo:assignments:opened` remain accepted aliases in the service for compatibility; canonical current events are the more specific dashboard events.
- `demo:trial:algorithm-trace_v2` is a dataset/site-task identifier, not a user event.
- The `demo:branch:*` family is dynamic and should not be mistaken for chapter completion.

## Handler flow

Frontend calls `DemoEngine.completeAction` or answer verification. Backend `demo_event` validates current state, calls `record_demo_action`, optionally calls `update_demo_state`, and returns authoritative state. Duplicate completed semantic events are harmless; invalid actions produce 409 and are visible to browser console/runtime collectors.
