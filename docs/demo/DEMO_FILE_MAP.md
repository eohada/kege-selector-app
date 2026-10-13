# BooStudy Demo Experience — File Map

## Demo-only

| File | Role | Safe to modify? | Notes |
|---|---|---|---|
| `app/demo/__init__.py` | Demo blueprint | With demo scope | Entry registration |
| `app/demo/routes.py` | Demo routes/API | With tests | Session/security/event contracts |
| `app/demo/service.py` | Demo dataset/state | With migration/data review | Creates temporary domain graph |
| `static/js/demo/demo_engine.js` | state/event engine | With E2E | Monotonic transitions and server sync |
| `static/js/demo/demo_scenario.js` | declarative scenario | With scenario review | 10 chapter definitions |
| `static/js/demo/boo_companion.js` | Experience Layer behavior | With browser QA | Large integration surface |
| `static/js/demo/demo_welcome.js` | Chapter 1 intake | With browser QA | Initializes demo |
| `static/css/demo/demo_companion.css` | Companion/Cinema CSS | With visual QA | Demo visuals |
| `static/css/demo/demo_cinematic_overrides.css` | guided overrides | With visual QA | Avoid global regressions |
| `templates/sandbox/demo_welcome.html` | Chapter 1 | Yes, demo scope | Current welcome shell |
| `templates/sandbox/components/_boo_companion.html` | Experience markup | Yes, demo scope | Included conditionally |
| `static/images/demo/*` | demo illustrations | Preserve | onboarding, library, route, dialogue |
| `tests/e2e/demo-*.spec.ts` | demo browser suites | Preserve | coverage of chapters/branches |
| `tests/v2/test_demo_experience_v2.py` | backend demo suite | Preserve | isolation, events, answers, exit |

## Shared with production platform

| File | Role | Why demo touches it | Risk |
|---|---|---|---|
| `app/task_workspace/service.py` | workspace context/permissions | retry submission must remain editable for demo | can affect real student editability |
| `templates/task_workspace.html` | actual task UI | demo target markers and real workspace | shared UI regression |
| `static/task-workspace/task-workspace.js` | mode switching/submission | real answer/code behavior | shared interaction regression |
| `templates/sandbox/student_dashboard.html` | canonical dashboard | demo targets/data presentation | student dashboard regression |
| `templates/sandbox/lesson_room.html` | lesson room | guided tour target | lesson page regression |
| `templates/sandbox/theory.html` / `theory_article.html` | theory | library chapter target | theory regression |
| `templates/sandbox/student_schedule.html` | schedule | Chapter 8 target | schedule regression |
| `templates/sandbox/profile.html` | profile | Chapter 9 target | profile regression |
| `app/main/routes.py`, `app/theory/routes.py`, `app/lessons/routes.py` | real routes | provide pages used by demo | ordinary platform behavior |
| `app/utils/db_migrations.py` | schema/bootstrap | demo dataset depends on current schema | migration risk |

Before any shared change, run ordinary student tests in addition to demo tests. Do not remove `data-demo-target` markers without updating scenario handlers and E2E.
