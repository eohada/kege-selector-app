# BooStudy Demo Experience — Git Snapshot

Snapshot date: 2026-10-05.

- Branch: `main`
- HEAD: `9a10944ff3dbe52ad9ff659380ad0e02ab0408f6`
- Working tree: **dirty and heavily modified**.
- HEAD does not fully represent the demo implementation.

> THE DEMO IMPLEMENTATION IS NOT FULLY REPRESENTED BY HEAD COMMIT.

Observed `git diff --stat`: 57 modified tracked files, approximately 4698 insertions and 374 deletions. `git status --short` also reports untracked demo-related directories/files, including `app/demo/`, `static/js/demo/`, `static/css/demo/`, `static/images/demo/`, `templates/sandbox/demo_welcome.html`, `_boo_companion.html`, demo migrations, demo E2E files and `tests/v2/test_demo_experience_v2.py`.

Important modified/untracked demo or shared files to preserve before destructive git operations:

- `app/demo/`
- `app/task_workspace/service.py`
- `static/js/demo/`
- `static/css/demo/`
- `static/images/demo/`
- `templates/sandbox/demo_welcome.html`
- `templates/sandbox/components/_boo_companion.html`
- `templates/task_workspace.html`
- `static/task-workspace/task-workspace.js`
- `templates/sandbox/student_dashboard.html`
- `templates/sandbox/lesson_room.html`
- `templates/sandbox/theory*.html`
- `templates/sandbox/student_schedule.html`
- `templates/sandbox/profile.html`
- `tests/e2e/demo-*.spec.ts`
- `tests/v2/test_demo_experience_v2.py`
- `migrations/versions/20261003_demo_call_request_metadata.py`
- `migrations/versions/20261005_merge_demo_heads.py`
- `docs/demo/`

Migration files directly associated with demo/current schema work:

- `20261003_demo_call_request_metadata.py`
- `20261005_merge_demo_heads.py`

No reset, clean, checkout, rebase, stash, commit or push was performed for this snapshot.
