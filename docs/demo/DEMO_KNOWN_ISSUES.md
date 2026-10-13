# BooStudy Demo Experience — Known Issues

| Issue | Severity | Status/evidence | Impact | Recommended fix | Release blocker |
|---|---|---|---|---|---|
| Multiple Alembic heads (`20261003_demo_call_request_metadata.py`, `20261004_telegram_delivery_contract_indexes.py`) | High | REPORTED; merge file `20261005_merge_demo_heads.py` exists, but migration graph was not independently audited here | deploy/migration ambiguity | run `alembic heads/history` in clean environment and validate single head | Confirm before production |
| Demo rows/users are not deleted by `/demo/api/exit` | Medium | CONFIRMED by service behavior: exit clears session/logout; no cleanup transaction | local DB growth, PII-like demo residue | scheduled cleanup or explicit retention policy | No for local demo; yes for privacy production |
| `DEMO_ACCESS_CODE = 'test'` | High | REPORTED from previous audit; current code snapshot not re-searched for this symbol | unsafe if exposed outside local demo | move to config/secret and disable in production | Yes if route is exposed |
| `/demo/start` rate limiting insufficiency | Medium | REPORTED; current canonical endpoint is `/demo/api/init` | abuse/resource creation | rate-limit all creation paths | Depends on exposure |
| Schedule endpoint `submissions.student_submission_room` | High | REPORTED; not re-proven in this snapshot | Chapter 8 or ordinary schedule can fail | fix query/model reference and add route test | Yes for canonical E2E if reproducible |
| Local pytest/venv instability | Medium | REPORTED and not fully re-run | test verdict unavailable | repair pinned runtime/CI | No runtime, yes for release confidence |
| Mobile E2E not independently confirmed | High | CONFIRMED as “not confirmed”; current combined run failed runtime assertion | responsive regressions may escape | run clean mobile suite and triage failures | Yes for mobile release |
| Large uncommitted worktree | High | CONFIRMED by `git status` | destructive operation can lose implementation | preserve/snapshot/commit intentionally before cleanup | Yes for handoff safety |
| `git diff --check` issue | Low/Medium | REPORTED; targeted demo docs/files pass; global tree not cleanly attributed | noisy diff/CI failure | isolate existing whitespace issue | No if scoped |
| `scripts/25.py` SyntaxWarning | Low | REPORTED; not relevant to demo path | noisy tooling | fix when touching scripts | No |
| Canonical E2E receives 409 `/demo/api/event` responses | High | CONFIRMED in latest desktop/mobile run; journey still reached final CTA but runtime assertion failed | release test is red; stale/late semantic actions are visible errors | make browser handlers await/ignore already-invalid stale transitions or align event graph; add regression test | Yes |
| Retry workspace can be confused with original graded submission URL | High | CONFIRMED conceptually and observed in browser: original `context_id=2500` is read-only; retry uses separate id | learner sees no input if old link is opened | always resolve retry from state and show explicit route context | Yes if canonical CTA can land on original |
| Guided target absent/hidden on retry | High | Previously confirmed; current code now filters visible controls and highlights input+submit, but fresh full manual pass is not confirmed | learner is left without next action | complete browser QA after pause | Yes until confirmed |

Do not silently mark a reported item resolved. Update status only with current code/test evidence.
