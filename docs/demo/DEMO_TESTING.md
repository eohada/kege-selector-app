# BooStudy Demo Experience — Testing

## Pytest

Primary suite: `tests/v2/test_demo_experience_v2.py`.

It covers:

- API init and state migration;
- event persistence and idempotency;
- dashboard, analytics and task access;
- programming goal persistence;
- regular students not receiving Experience Layer;
- correct/wrong answer branching;
- separate editable retry submission;
- demo security/isolation and exit;
- monotonic ranking and forged transition rejection;
- enriched dataset topology;
- canonical dashboard and ordinary student routing.

Latest status in this snapshot: **REPORTED/partially confirmed**. The suite is present and contains targeted assertions, but a clean full pytest run was not completed in this snapshot because the local environment has a damaged/variable test runtime history and the working copy is heavily modified.

## Playwright / browser E2E

Important files:

- `tests/e2e/demo-linear-release.spec.ts` — canonical desktop and mobile flow from `/demo` to persisted intro request.
- `tests/e2e/demo-experience-chapter2.spec.ts` — dashboard and Chapter 2 controls.
- `tests/e2e/demo-experience-trial.spec.ts` — trial branches.
- `tests/e2e/demo-experience-library.spec.ts` — theory branch.
- `tests/e2e/demo-experience-finale.spec.ts` — finale/director checks.
- `tests/e2e/demo-experience-guided-controls.spec.ts` — guided controls.
- `tests/e2e/demo-experience-user-journey.spec.ts` and `demo-experience-v5-finale.spec.ts` — earlier journey variants.
- `tests/e2e/release-audit.spec.ts` — wider release audit.

The canonical release test uses desktop and mobile projects, one worker, and checks server/runtime errors, URL transitions, target visibility, final form and no horizontal overflow.

Latest confirmed run in the current local server: both desktop and mobile tests reached the final CTA path, but failed their final `runtimeErrors` assertion because `/demo/api/event` returned repeated 409 responses. Therefore “full E2E passed” is **not CONFIRMED**. Previous reports of 15/15 or similar are **REPORTED**, not evidence for this snapshot.

## Manual QA checklist for resume

- [ ] Chapter 1: three choices, name validation, custom grade select, goal and init.
- [ ] Chapter 2: all three dashboard discoveries and back navigation.
- [ ] Chapter 3 answer mode.
- [ ] Chapter 3 code mode.
- [ ] Wrong answer, first hint, second wrong answer.
- [ ] Correct answer and alternate work-over-errors bridge.
- [ ] Chapter 5 review and retry highlight.
- [ ] Retry answer submit and corrected state.
- [ ] Chapter 6 route.
- [ ] Chapter 7 analytics.
- [ ] Chapter 8 schedule.
- [ ] Chapter 9 profile.
- [ ] Chapter 10 finale and persisted request.
- [ ] refresh recovery at every chapter.
- [ ] Back button and double click.
- [ ] desktop and mobile.
- [ ] ordinary non-demo student without Experience Layer.
- [ ] demo isolation and exit.
