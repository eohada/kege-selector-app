# BooStudy Telegram Experience

## Purpose

Telegram is the personal dispatcher of BooStudy events, not a copy of the web application. The bot has one identity and role-aware contexts. Complex work opens the authenticated BooStudy web screen for the concrete entity.

## Architecture

```text
Telegram update
  -> app.telegram.handlers / webhook
  -> app.telegram.application (context + bounded read models)
  -> existing RBAC/data scope + domain models/services
  -> Telegram ViewModel/renderer or Mini App API
```

`app.telegram.application` is deliberately independent of Telegram SDK types. It resolves active context only after checking the real user's roles and builds bounded `TodayView`, `ContextView` and curated `ActionItem` values. Handlers should not add complex SQL or treat callback data as authorization.

## Contexts and identity

There is one official bot. A creator may use `creator` or `teacher` context without a second link. `creator_bot_mode` stores the existing preference; `resolve_active_context()` still validates actual roles. Every future mutation must re-check identity, active context, `has_permission()` and data scope at request time.

Supported public contexts are student, teacher/tutor, parent, admin and creator. Technical roles such as tester/designer/content-maker are not automatically exposed as public UX contexts.

## Home and Action Center

Home is a concise, role-aware summary. `ActionItem` is a curated action, not a raw event stream. Items contain type, priority, title, optional description/timestamp, entity and primary action. Read queries are bounded and use the existing Student, Lesson, Assignment and Submission lifecycle data.

The current application layer provides:

- active context and available-context resolution;
- effective backend timezone;
- student/parent bounded future lessons and assignment summary;
- teacher review count and review action;
- overdue/upcoming assignment actions;
- stable entity IDs for future deep-link rendering.

Mini App read endpoints:

- `POST /tg-app/api/context` — verified identity, active context and available contexts;
- `POST /tg-app/api/context/switch` — creator-only teacher/creator context switch;
- `POST /tg-app/api/home` — bounded role-aware Home read model;
- `POST /tg-app/api/action-center` — curated attention items;
- `POST /tg-app/api/teacher/review-queue` — teacher-scoped submissions awaiting review.
- `POST /tg-app/api/parent/children-summary` — confirmed-child summaries without private work content.
- `POST /tg-app/api/parent/digest` — bounded digest for one confirmed child.
- `POST /tg-app/api/parent/context/switch` — сохраняет выбранного подтверждённого ребёнка без изменения связи.
- `POST /tg-app/api/teacher/students` — bounded mentor-scoped student summaries/search.
- `POST /tg-app/api/operations/problems` — bounded actionable problems for admin/creator context.
- `POST /tg-app/api/operations/users/search` — safe, bounded username/numeric-id search.
- `POST /tg-app/api/operations/summary` — read-only admin/creator operational counts.
- `POST /tg-app/api/student/assignments` — student assignments grouped by canonical lifecycle category.

All endpoints validate Telegram init data first. Review queue is read-only; grading remains in BooStudy web.

Empty sections should be omitted by renderers. Full assignment solving, lesson rooms, grading, files, course editing and high-impact admin actions remain web flows.

## Account linking

Use the existing short-lived one-time deep-link token as the primary flow and the one-time code as fallback. Never link by email, username, name or phone alone. Link/unlink/status/toggle APIs already exist. Tokens must be single-use, expiry checked and absent from plaintext logs.

## Notification taxonomy

Immediate: lesson reminder, imminent deadline, new submission for teacher, checked work, critical operational error and important schedule change.

Digest: daily schedule, review queue and overdue summaries.

Optional: achievements, detailed progress and low-priority activity.

Never: raw internal events, private teacher notes, full answers/files or every click/activity.

Existing `app.telegram.user_notify`, Redis dedupe, quiet-hours and Celery tasks remain the delivery path. New notification kinds must use the same preference and dedupe checks.

## Mini App and deep links

Use the Mini App for schedule, assignments, review queue, student/children lists, compact progress and creator/admin read summaries. Use web deep links for lesson rooms, submissions, grading, course/program/lesson editors, files/canvas, billing mutations, permissions, deletion and impersonation.

Deep links must resolve through application URL helpers and point to the concrete lesson, assignment, submission or student whenever possible. Expired callbacks and revoked relationships must return a safe current Home instead of an exception.

## Timezone

Persist timestamps in the backend's UTC-aware representation. Display using `effective_timezone_name(user)` and the existing timezone conversion helpers. Telegram must not create a separate timezone model or use server/Telegram time. Be careful with the parallel legacy User/UserProfile timezone fields and naive legacy datetime columns.

## Privacy and security

Parent data is limited by confirmed `FamilyTie`; teacher data is limited by teacher scope. Messages should contain minimum necessary personal/grade information and link to BooStudy for sensitive details. Validate Mini App init data, webhook/internal secrets, callback ownership, link expiry, replay, dedupe, rate limits and audit trails before exposing new actions.

## Testing and operations

Changes should extend unit/integration coverage for context escalation, teacher/parent scope, stale callbacks, linking expiry/reuse, timezone conversion, notification dedupe/quiet hours and Mini App auth. Run the existing Telegram, RBAC and timezone suites before release. Production deployment follows the repository blue-green procedure; do not restart web production directly.

### Durable delivery

`UserNotification` зеркалируется в `TelegramDeliveries` в той же транзакции. Уникальный `dedupe_key` защищает от повторной постановки; Celery dispatcher claim’ит due-записи, повторяет временные ошибки с backoff 60/300/900/3600/21600 секунд и ограничивает пятью попытками. Recovery возвращает зависшие `processing` в retry, а тихие часы откладывают доставку. Эксплуатационные чек-листы находятся в `docs/telegram-manual-qa.md` и `docs/telegram-deployment.md`.

Mini App `initData` дополнительно проверяет `auth_date`; TTL по умолчанию 24 часа, управляется `TELEGRAM_INIT_DATA_MAX_AGE` и ограничен диапазоном 60 секунд–7 дней.

Operations summary также показывает только агрегаты outbox: `pending_deliveries`, `retry_deliveries`, `failed_deliveries`. Тексты сообщений, chat ID и ошибки Telegram наружу не выдаются.

## Current limitations

The application layer remains intentionally read-oriented for sensitive mutations. Grading, billing, permission changes and destructive admin actions still stay on the authenticated web surface. No fake metrics or attendance data should be added to fill those gaps.
