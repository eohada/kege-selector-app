# BooStudy Demo Experience — Architecture

## Backend

| Path | Purpose | Important symbols | Dependencies | Known risks |
|---|---|---|---|---|
| `app/demo/__init__.py` | Blueprint registration | `demo_bp` | Flask | route registration must stay isolated |
| `app/demo/routes.py` | HTTP entry/API | `demo_entry`, `demo_init`, `demo_state`, `demo_director`, `demo_event`, `demo_verify_answer`, `demo_intro_request`, `demo_exit` | Flask session, Flask-Login, models, service | 409 invalid actions are visible as browser errors |
| `app/demo/service.py` | Dataset/state/domain logic | `ensure_demo_user_and_assignment`, `get_demo_state`, `update_demo_state`, `set_demo_scene`, `record_demo_action`, `verify_demo_task_answer` | SQLAlchemy models, session | demo rows are not fully deleted on exit |
| `templates/sandbox/demo_welcome.html` | Chapter 1 cinematic shell | intake scenes, grade select | demo JS, demo CSS | demo-only template |
| `app/task_workspace/service.py` | Resolves workspace permissions/context | `_resolve_submission_task_context` | Submission/Assignment models | shared with production workspace |

`ensure_demo_user_and_assignment` creates or reuses an isolated user with `is_demo_user`, a Student, assignments, submissions, lessons, learning plan, statistics, trajectory and achievements. The main trial and the separate retry submission are connected through state ids such as `submission_id`, `mistake_submission_id` and `mistake_assignment_task_id`.

Answer verification is server-authoritative. `verify_demo_task_answer` writes an Answer, changes submission status, records `trial_completed` or retry correction and advances the session scene.

Security/isolation checks:

- mutations require authenticated demo user plus `demo_state` and `demo_session_id`;
- answer verification checks the submission belongs to current demo Student;
- regular users do not receive Companion markup;
- demo user is blocked from protected admin/billing routes;
- final reward is session-only; the intro lead is marked demo.

## Frontend

- `static/js/demo/demo_engine.js` — local engine, default state, rank monotonicity, server sync, events, exit.
- `static/js/demo/demo_scenario.js` — declarative chapter/step messages and buttons.
- `static/js/demo/boo_companion.js` — Cinema Mode, Companion Mode, target markers, reaction/dialogue, page-specific actions, finale form.
- `static/js/demo/demo_welcome.js` — Chapter 1 intake and `/demo/api/init`.
- `static/css/demo/demo_companion.css` — Experience Layer layout and visual states.
- `static/css/demo/demo_cinematic_overrides.css` — guided/highlight overrides.
- `templates/sandbox/components/_boo_companion.html` — companion, workspace-story and finale markup.
- shared templates (`student_dashboard`, `lesson_room`, `theory`, `task_workspace`, `student_schedule`, `profile`) expose `data-demo-target` markers.

## Event flow

```text
User action
  -> data-demo-target / CTA handler
  -> semantic event or server answer verification
  -> Demo Engine local state
  -> /demo/api/event or /demo/api/state
  -> session state and completed_actions
  -> scenario transition
  -> Experience Layer dialogue/highlight
  -> Boo reaction and next CTA
```

The browser is not authoritative for answer correctness or valid chapter transitions. The server validates allowed actions and `STEP_RANKS` prevents stale state from rewinding the scenario.

## State model

State is held in signed Flask session under `demo_state`; browser local state is managed by Demo Engine and reconciled with server revision/director revision. Important fields:

```json
{
  "version": 5,
  "chapter_id": "chapter_5",
  "step_id": "mistakes_opened",
  "student_name": "Demo",
  "grade": "11",
  "goal": "ege",
  "submission_id": 123,
  "mistake_submission_id": 124,
  "mistake_assignment_task_id": 456,
  "completed_actions": ["demo:library:material_opened"],
  "flags": {"trial_passed": true},
  "director_revision": 3,
  "demo_session_id": "opaque-session-id"
}
```

`STEP_RANKS` currently spans `welcome` through `finale` (24 step ranks) and maps chapters 1–10. `update_demo_state` merges flags/history; `record_demo_action` appends one semantic action and bounded history; repeated completed actions are idempotent in `/demo/api/event`. Invalid action/transition returns 409 without advancing state.

## Demo dataset topology

```text
Demo User (is_demo_user=true)
└── Student
    ├── mentor
    ├── planned and completed Lessons
    ├── main Submission / AssignmentTask
    ├── graded review Submission with teacher comment
    ├── editable retry Submission
    ├── StudentLearningPlan / LearningTrajectory / TrajectoryModule
    ├── GradebookEntry / StudentTaskStatistics
    └── demo-scoped achievements
```

## Experience modes

- Cinema Mode owns high-attention chapter transitions and finale.
- Companion Mode runs on real platform pages, gives a short message and points to one or more target elements.
- Guided objectives add `boo-target-pulse`, a focus hole and scroll/resize tracking. Current code deliberately keeps page scrolling enabled.
