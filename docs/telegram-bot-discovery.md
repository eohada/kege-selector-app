# BooStudy: Telegram Bot Discovery

> Статус исследования: 2026-10-03. Документ описывает фактическое состояние репозитория, а не целевой UX бота. Новые предложения помечены `POSSIBLE`, `REQUIRES BACKEND` или `UNKNOWN`.

## 1. Executive Summary

BooStudy — монолитное Flask-приложение с SQLAlchemy-моделями, PostgreSQL, Flask-Login, RBAC, Celery/Redis и Flask-SocketIO. Основной пользовательский контур — веб-приложение: dashboard, расписание, уроки, программы/курсы, задания, submissions, проверка и аналитика. Telegram уже не является чистым greenfield: в коде есть webhook на `/webhook/telegram`, обработчики `python-telegram-bot`, связывание аккаунта, уведомления, Celery-задачи, Mini App и отдельные TMA API.

Главный вывод: бот может переиспользовать существующую БД, permission/data-scope helpers, notification services и ряд TMA API. Для чтения сводок и напоминаний readiness высокая. Для безопасного изменения учебного контента, проверки работ, родительских действий и административных мутаций нужны новые endpoint/service-границы и строгая повторная проверка прав; Telegram не должен обращаться к БД напрямую из handler-ов.

Реально обнаруженные роли: `student`, `parent`, `tutor`, `teacher` как фактические teacher-контуры, `admin`, `chief_admin`, `creator`, а также вспомогательные `content_maker`, `designer`, `tester`, `chief_tester`. Отдельной модели OWNER нет: `creator` — роль с полным набором default permissions и creator/platform context; creator может переключаться между creator и teacher режимом.

Наиболее перспективны: привязка аккаунта, уведомления о проверке/ДЗ/уроках, «что сегодня», ближайшее расписание, teacher review queue, parent digest, deep-link в веб и creator/admin operational summary. Наименее подходящи для бота: редакторы программ и уроков, большие тесты, полноценная проверка submission и сложная аналитика.

## 2. Current BooStudy Architecture

### Стек и границы

| Область | Что установлено | Статус |
|---|---|---|
| Backend | Python, Flask application factory, blueprints | `EXISTS` |
| ORM/DB | Flask-SQLAlchemy; модели в `core/db_models.py`; миграции Alembic; production contract ожидает PostgreSQL | `EXISTS` |
| Auth | Flask-Login `current_user`, сессия, CSRF для web | `EXISTS` |
| Authorization | role helpers + `RolePermission`, `UserRole`, custom permissions, data scopes | `EXISTS` |
| API | Flask JSON endpoints внутри blueprints; часть TMA API в `app/telegram/mini_app.py` | `EXISTS` |
| Realtime | Flask-SocketIO; sandbox/lesson/task/presence socket handlers | `EXISTS` |
| Jobs | Celery; Redis используется для task/dedupe/state; telegram reminders/digests/dispatch | `EXISTS` |
| Telegram transport | `python-telegram-bot`, webhook, direct Bot API calls, mock mode | `EXISTS` |
| Frontend | Jinja templates, V2 `templates/sandbox`, JavaScript; package manifest содержит frontend tooling/Playwright | `EXISTS` |
| Files | workspace files, uploads/storage blueprints, attachments/canvas | `EXISTS` |
| Notifications | DB `UserNotification`, in-app routes, unified service, Telegram mirror and typed Telegram notifications | `EXISTS` |
| Deployment | WSGI/Procfile/Nixpacks; `/ready` checks DB, Redis, migrations, Socket.IO; blue-green procedure documented | `EXISTS` |

Упрощённая схема:

```text
User/Telegram User
        |
Web (Jinja/V2)       Telegram webhook / Mini App
        |                       |
Flask blueprints + JSON API + Telegram handlers
        |                       |
permissions/data-scope + domain services + Celery tasks
        |                       |
PostgreSQL/SQLAlchemy ---- Redis ---- Socket.IO
        |
uploads/workspace/files, external Telegram API, optional Miro/LLM/billing
```

Telegram может использовать существующий backend как клиент уже сегодня для webhook, уведомлений и TMA API (`EXISTS`). Для полноценного официального multi-role бота нужен отдельный application/service слой поверх существующих доменных сервисов (`REQUIRES BACKEND`): сейчас часть handler-ов содержит SQL/role-specific aggregation непосредственно в Telegram-модуле.

## 3. Authentication & Authorization

Web authentication — Flask-Login и `User`; роли объединяются из primary `User.role`, `UserRole` и, в dev/test, sandbox role. `has_permission()` учитывает custom permissions, DB `RolePermission` и defaults. `get_user_scope()` ограничивает teacher/student/parent data scope; creator/admin/chief tester имеют расширенный scope. Route decorators `require_role`, `require_admin`, `require_tutor`, `require_student`, `require_parent` существуют, но Telegram handlers имеют дополнительную собственную проверку роли.

Telegram linking уже реализован двумя связанными механизмами:

1. One-time code: веб генерирует 6-значный `telegram_link_code` на 15 минут, пользователь вводит его боту.
2. One-time deep-link token: веб создаёт `telegram_link_token` с expiry, ссылка ведёт к `/start`/link flow.

После проверки профиль получает `telegram_chat_id`; есть `telegram_id`, время привязки, unlink, status и toggle notifications. В коде также есть `TelegramAuthCode`, но фактический профильный link flow использует `UserProfile` поля и API `/api/telegram/link-bot`. Простого доверия email нет (`EXISTS`, безопаснее указанного в требованиях anti-pattern).

## 4. Roles & Permission Matrix

`teacher` и `tutor` — фактически преподавательские роли; `creator` имеет teacher-возможности через более широкий доступ и отдельный creator mode. Parent scope строится через подтверждённые `FamilyTie`/relationship helpers.

| Возможность | Student | Teacher/Tutor | Parent | Admin | Owner/Creator |
|---|---:|---:|---:|---:|---:|
| Dashboard, профиль, собственный scope | EXISTS | EXISTS | EXISTS | EXISTS | EXISTS |
| Просмотр расписания | EXISTS | EXISTS | EXISTS по child scope | EXISTS | EXISTS |
| Просмотр заданий/работ | EXISTS в собственном scope | EXISTS своих учеников | EXISTS по child scope | EXISTS | EXISTS |
| Создание/назначение уроков | — | EXISTS | — | EXISTS | EXISTS |
| Создание/назначение заданий | — | EXISTS | — | EXISTS | EXISTS |
| Отправка/попытки/ответы | EXISTS | ограниченно/teacher review | — | scope-dependent | teacher context |
| Проверка и комментарии | — | EXISTS | — | EXISTS | EXISTS |
| Gradebook/progress/analytics | собственные | свои ученики | child scope | platform scope | platform + teacher |
| Family/child links | — | — | EXISTS read scope | управляет/видит | full scope |
| Управление пользователями/ролями | — | — | — | EXISTS | EXISTS |
| Контент, courses, templates, groups | — | EXISTS по правам | — | EXISTS | EXISTS |
| Billing/subscriptions | ограниченно | ограниченно | child tariff view | EXISTS | EXISTS |
| Platform stats/bug reports | — | — | — | частично | EXISTS |

Примечание: `admin` и `creator` получают все `ALL_PERMISSIONS` по defaults; дополнительные роли (`chief_admin`, `content_maker`, `designer`, tester) требуют отдельной проверки перед публичным Telegram exposure. UI-кнопка не является доказательством права: каждый bot callback/endpoint обязан повторять `has_permission()` и scope checks.

## 5. Domain Model

| Сущность | Назначение и связи | Кто работает | Telegram relevance |
|---|---|---|---|
| `User`, `UserProfile`, `UserRole`, `RolePermission` | identity, role, timezone, Telegram fields, permissions | система/admin | критично для auth/linking |
| `Student`, `TeacherStudent`, `FamilyTie`, `InviteLink`, `GroupStudent` | learner, teacher-child and parent-child scope | teacher/admin/parent | критично для адресации |
| `Course`, `LearningTrajectory`, modules/items, `StudentCourseEnrollment` | curriculum/program and enrollment | teacher/student/admin | summary/deep-link; editor web-only |
| `Lesson`, `RecurringLessonSlot`, `LessonTask`, attachments, room | scheduled lesson, room, lesson tasks/materials | teacher/student | reminders, links, reschedule events |
| `Assignment`, `AssignmentTask` | assigned work and task composition | teacher creates; student receives | deadline/summary/deep-link |
| `Submission`, `SubmissionAttempt`, `Answer`, `SubmissionComment`, `TaskReview`, AI review | student work, attempts, grade/review/comment lifecycle | student submits; teacher reviews | review alerts; review UI web |
| `GradebookEntry`, `StudentSkill`, `UserMastery`, analytics | marks, mastery, learning analytics | teacher/student/parent scope | digest/summary |
| `UserNotification`, `PendingAssignmentNotification`, `Reminder` | in-app/deduped/debounced notification state | service/jobs | delivery source |
| `UserAchievement`, `LearningError`, theory models | gamification and learning cycle | student/teacher | optional achievements |
| `StudentWorkspaceFile`, `TaskCanvasDrawing`, uploads | learner files and work artifacts | scoped users/teacher | links only; files need privacy review |
| `TariffPlan`, `UserSubscription`, billing models | plans/subscriptions | parent/admin/creator | expiry/summary; payment UX web |
| `AuditLog`, `BugReport`, `PlatformBugReport`, `BotErrorReport` | audit/support/operational events | admin/creator | critical alerts and creator inbox |
| `TelegramBroadcast`, `TelegramStartLead`, deadline sent/bot admin models | Telegram-specific operations | creator/admin | existing integration state |

Additional real model groups include library/materials, groups, teacher profiles/programs/results, QA, referrals/promocodes and guest contour. They are not automatically Telegram scenarios.

## 6. Student Journey

Фактический путь: регистрация/invite → `User`/`Student` → teacher/group/family relationship → enrollment/program/course → schedule/lesson room → assignment/submission/attempt/answer → teacher review/comment/grade → gradebook/mastery/analytics/achievement. Не все students проходят один и тот же curriculum path: есть course/trajectory/theory/assignment contours.

- Dashboard показывает ближайший/активный урок, assignments/status and progress-oriented data; точный набор зависит от V2 route и scope.
- Schedule поддерживает lesson date/time, IANA/user timezone conversion, teacher/topic/room links and recurring slots. Cancellation/reschedule are model/route dependent; универсальная Telegram mutation не подтверждена.
- Assignment/submission statuses canonicalized in `submission_lifecycle_service`; есть attempts, answers, comments, deadline, teacher/AI review fields. Сообщения «начали проверять» как отдельное стабильное domain event не подтверждены.
- Progress exists via analytics, gradebook, mastery/skill and student endpoints. Achievements exist via `UserAchievement`; streak/XP/levels как единая модель не подтверждены.

**Telegram opportunities — Student:**

- `EXISTS/READY`: link account, notification settings, lesson reminder, deadline reminder, daily digest, submission/grade/review notifications, schedule/dashboard/progress via existing TMA/deep links.
- `NEEDS API`: authoritative «что сегодня», overdue/upcoming aggregation as a stable bot read API; assignment list with canonical states.
- `WEB ONLY`: doing large tests, editing answers/files/canvas, full lesson room, curriculum editor.

## 7. Teacher Journey

Teacher can be invited/connected to students, manage teacher-student/group scope, create lessons and recurring slots, create/assign assignments/templates/courses, see submissions, review/grade/comment and inspect gradebook/analytics. Exact route permission varies between `teacher`, `tutor`, creator/admin and custom permissions.

Teacher attention signals actually present: submission sent to staff, teacher homework note reminder, lesson start/finish, lesson scheduling, balance/subscription changes, deadline-related states and generic in-app notification. A single normalized teacher inbox/event stream is not present (`PARTIAL`).

**Telegram opportunities — Teacher:** review queue and «who submitted», upcoming lessons, overdue students, quick open student/work, lesson reminder, homework-note reminder (`EXISTS/POSSIBLE` depending on endpoint). Grade/comment mutation should deep-link to web until service-level API and audit/idempotency are added (`WEB ONLY` / `REQUIRES BACKEND`).

## 8. Parent Journey

Parent is a real role. `FamilyTie` and relationship helpers resolve confirmed children; routes include `/parent/dashboard`, `/api/parent/children` and parent dashboard/templates. Parent default permissions include gradebook, assignment, schedule, diagnostics, trainer and theory view, but actual child data is scoped.

Confirmed: parent can see child-oriented dashboard, schedule, assignments/debts and subscription/tariff-related information in parent UI/TMA surfaces. Progress/grades are available where corresponding scope/API is used. Attendance and a formal reporting model are not established. Multiple children are structurally supported by family tie queries, but product limits/presentation require confirmation. Parent comments/messages and payment operations through Telegram are not confirmed.

**Telegram opportunities:** immediate safety-conscious alerts for lesson changes/deadlines and periodic child digest (`POSSIBLE`, some notification helpers exist); on-demand child schedule/status (`NEEDS API`); payment and detailed grades should link to authenticated web (`WEB ONLY` until privacy policy).

## 9. Admin Journey

Admin routes/models cover users, roles/permissions, students, parents, teachers, courses/content, groups, billing, bug reports and operational panels. Telegram handlers already expose admin summary, users, students, parents, tutors and search controls for allowed roles. This is operational convenience, not proof that every mutation is safe.

Safe Telegram candidates: read-only health/summary, critical error alert, linked-user search, open admin deep-links, acknowledge/triage low-risk operational alerts (`EXISTS/POSSIBLE`). Keep role changes, deletion, billing changes, impersonation, bulk content changes and permission grants in web (`WEB ONLY`); if later added, require explicit confirmation, audit and idempotency (`REQUIRES BACKEND`).

## 10. Owner Journey

`creator` has all default permissions and is treated as platform owner/creator by bot code. The same Telegram identity can enter creator or teacher mode. Creator Mini App endpoints provide stats, broadcasts, student list and bug report reply. Existing stats include user counts and linked Telegram count; broader operational KPIs are not uniformly modeled.

Teacher context: same student/lesson/assignment/review flows as teacher. Platform context: users, students, parents, tutors, broadcasts, bug reports and some stats. Errors/background jobs/load/payments/new registrations as a comprehensive owner dashboard are `PARTIAL` or `UNKNOWN`, not assumptions.

## 11. System Event Map

Есть логические domain events и typed notification calls, но нет единого typed event bus. Names below are normalized discovery names, not necessarily persisted event identifiers.

| Event | Source | Recipient | Existing notification | Telegram potential | Priority |
|---|---|---|---|---|---|
| `telegram.account_linked/unlinked` | link API/handler | user | direct bot response | exists | high |
| `lesson.scheduled` | lesson/API/notification service | student, parent, teacher as applicable | in-app + Telegram helper | exists | high |
| `lesson.reminder_30m` | Celery lesson task | student | Telegram | exists | high |
| `lesson.started/finished` | lesson notifications | student/teacher | Telegram helpers | exists | normal |
| `lesson.rescheduled/cancelled` | schedule mutation | affected users | not consistently normalized | possible; needs audit | high |
| `assignment.created/assigned` | assignment/lesson flow | student/parents | debounced pending assignment notification | exists/partial | high |
| `submission.created` | submission lifecycle | teacher/staff | Telegram teacher review alert | exists | high |
| `submission.checked/graded` | review service | student/parents | Telegram grade/review | exists | high |
| `submission.comment_added` | comment/review | student/teacher | partial via notification helpers | possible | normal |
| `assignment.deadline_near/overdue` | Celery deadline task | student, possibly parent | Telegram deadline | exists for deadline; overdue policy partial | high |
| `teacher_homework_note_due` | reminder task | teacher | Telegram | exists | normal |
| `family_tie` changes | relationship service | parent/student | family notification helper | possible | high |
| `subscription_expiring` | billing/task | user/parent | Telegram helper | exists | normal |
| `bug_report.created/replied` | bug API/Mini App | creator/student | Telegram | exists | high |
| `system_error/critical` | notification service | admin/creator | in-app/Telegram path | exists/partial | critical |
| `achievement.awarded` | achievement model/service | student | model exists; delivery not consistently proven | possible | low |

## 12. Existing Notification System

`app.notifications.service.notify_user()` persists unified in-app notifications, deduplicates through Redis, and mirrors important notifications to Telegram dispatch. It can notify family/parents and admins. `UserNotification` tracks kind/read/state; `PendingAssignmentNotification` debounces assignment messages. `app.telegram.user_notify` checks linked chat, global enable flag, per-kind settings, quiet hours and Redis dedupe. `app.telegram.notifications` contains specialized senders for submissions, grades, lessons, subscription expiry, bug replies, digest, balance changes and teacher notes.

Celery tasks found: `telegram_dispatch`, `telegram_deadlines`, `telegram_lesson_reminders`, `telegram_homework_notes`, `telegram_daily_digest`, `telegram_broadcast`, `telegram_subscription_expiry`, plus generic notifications/reminders. Delivery is direct Bot API through `send_telegram_message`; webhook processing is queued asynchronously. Existing controls include notification toggle, per-kind flags, quiet hours, dedupe and student acknowledgment/feedback telemetry. This is `EXISTS`, but event taxonomy and preference schema are not fully centralized (`PARTIAL`).

## 13. Schedule & Timezone Model

Core timestamps use timezone-aware SQLAlchemy `DateTime(timezone=True)` and UTC helper. `User` has `timezone_mode` (`auto`/manual) and `timezone_iana`; `UserProfile` also has timezone (legacy/parallel field). Recurring slots have explicit IANA `timezone`, and schedule utilities convert stored UTC/lesson values for display. Deadline reminder code derives recipient timezone before formatting. This means the canonical Telegram display timezone should be the effective user timezone helper (`effective_timezone_name`), not Telegram server time and not an independent bot setting.

Risks: parallel timezone fields (`User.timezone_iana` vs `UserProfile.timezone`), some legacy naive datetime columns/assignments, mixed `datetime.utcnow()` and aware UTC in older API code, and multiple conversion helpers. Telegram must reuse the backend effective-timezone function and persist UTC; never parse local time in handlers. Exact DST behavior for every recurring-slot mutation needs additional tests (`UNKNOWN/PARTIAL`).

## 14. Deep-link Map

| Entity | Existing route/API evidence | Auth required | Telegram suitability |
|---|---|---|---|
| Dashboard | `/dashboard` and role dashboards | Flask-Login | suitable |
| Schedule | `/schedule`, sandbox schedule, TMA schedule API | yes/link | suitable |
| Lesson/room | `/lesson_room/<lesson_id>`, teacher room routes; `_lesson_room_url` | yes + scope | excellent deep-link |
| Assignment | assignment list/detail V2 routes and TMA assignment API | yes + scope | suitable |
| Submission/review | assignment detail/task review/workspace routes | yes + scope | web deep-link only |
| Profile/Telegram settings | profile routes, `/api/telegram/status` etc. | yes | suitable |
| Program/course | course/catalog/trajectory routes | yes + scope | deep-link; editor web |
| Progress/analytics | student analytics/profile and TMA progress | yes | summary + deep-link |
| Admin | `/admin`, `/admin/users`, bug report/admin panels | admin | deep-link only |

Exact canonical route names should be generated with `url_for`/central URL helper in a future bot service; do not hardcode guessed legacy routes.

## 15. Telegram Account Linking Options

1. `EXISTS / recommended`: web-generated short-lived one-time code entered in bot. Good for users already logged in; code is scoped, expiring and does not expose email. Must rate-limit attempts and invalidate on success.
2. `EXISTS / recommended for UX`: short-lived one-time deep-link token (`t.me/bot?start=...`) generated in authenticated web profile. Avoid logging token in URLs and clear it after use.
3. `POSSIBLE`: Telegram Login Widget or Mini App `initData` validation, then explicit account confirmation/step-up against logged-in BooStudy session. `validate_init_data` and TMA auth exist, but extending it to all account-linking roles requires threat-model and replay testing.

Do not link on email/username alone. Store Telegram numeric ID/chat ID securely, support unlink/revoke, detect chat reassignment, audit linking and avoid exposing child data before identity and role scope are established.

## 16. Telegram Interaction Classification

| Scenario | Message | Inline | Mini App | Web | Reason |
|---|---:|---:|---:|---:|---|
| lesson/deadline/grade alert | yes | optional | no | link | fast notification |
| today/next lesson summary | yes | refresh/open | optional | link | compact read |
| assignment/review queue | yes | open/ack | possible | preferred | list grows and needs context |
| toggle notification setting | no | yes | possible | fallback | simple state change |
| parent child digest | yes | child selector | possible | detail | privacy + multiple children |
| creator stats/bug triage | yes | refresh/open | exists | preferred for detail | operational summary |
| create/edit course or lesson | no | no | no | yes | complex forms |
| solve/submit large test | no | no | possible only limited | yes | rich task UI/files |
| grade/comment submission | no | limited ack | possible later | yes | audit and rich review |

## 17. Notification Strategy Candidates

| Role | Immediate | Digest | Optional | Never |
|---|---|---|---|---|
| Student | lesson reminder, new/checked work, imminent deadline | daily schedule + pending work | achievements, detailed progress | raw DB/error/debug, every in-app event |
| Teacher | new submission, urgent lesson change, teacher note due | review queue, overdue students | broad analytics, broadcasts | every student activity |
| Parent | material lesson cancellation/change, important child result | daily/weekly child progress and overdue summary | grades, routine reminders | private teacher/admin internals, full answer/files |
| Admin | critical errors, auth/security, operational outage | platform summary | user/activity digests | ordinary student-level events |
| Owner | critical errors, failed jobs, important billing/ops | platform + teacher digest | broadcasts/KPIs | raw high-volume telemetry |

Quiet hours and per-kind toggles already exist in part. Digest frequency, parent policy, locale and channel precedence are new product settings (`POSSIBLE/REQUIRES BACKEND`).

## 18. Telegram Settings

| Setting | Existing BooStudy setting | New Telegram need |
|---|---|---|
| Telegram linked/enabled | `UserProfile` fields and API | no |
| global Telegram notifications | `telegram_notifications_enabled` | no |
| per-event toggles | `tg_notify_*` profile flags | partial; taxonomy completion needed |
| quiet hours | helper logic/profile fields | partial; UI/API consistency needed |
| timezone | user/profile/effective timezone | no new clock; Telegram must reuse it |
| digest cadence/content | daily task exists | schedule/content preferences need backend |
| child selection | family ties exist | selector and persisted preference needed |

## 19. Privacy & Security

Treat Telegram chat as a less-controlled notification channel. Minimize names/grades and never send full answers, private files, tokens, passwords, phone numbers or internal diagnostics by default. Child data must be sent only after verified parent-child scope, not merely role `parent`. Do not include one-time auth tokens in logs or message text. Use short-lived deep links, HTTPS, webhook secret/internal dispatch secret, replay protection, rate limits, idempotency, audit logs and unlink/revoke.

Admin/creator actions need step-up confirmation and preferably web deep-link. Telegram `chat_id`/`telegram_id` are personal identifiers; protect access, avoid exposing them in admin search responses unnecessarily, and define retention/deletion policy (`UNKNOWN`).

## 20. API Readiness

### READY

Account link/status/unlink/toggle; webhook transport; direct notification delivery; lesson reminder; deadline reminder; daily digest; submission/grade alerts; TMA dashboard/schedule/progress/theory/profile; creator stats/bug-report/broadcast surfaces; deep links to lesson/dashboard.

### NEEDS API

Stable multi-role read API for today/next lesson, assignment states, teacher review queue, parent child digest, overdue aggregation, operational health and canonical deep-link resolution. Existing handlers/TMA can be sources, but bot should not depend on ad-hoc SQL result shapes.

### NEEDS SERVICE REFACTOR

Normalize domain events and notification kinds; extract Telegram handler SQL aggregation into reusable services; unify User/UserProfile Telegram fields and timezone source; centralize role/scope checks; standardize schedule/deadline conversions.

### BLOCKED

No safe basis yet for broad Telegram mutation of curriculum, submissions/reviews, permissions, billing, deletion, impersonation or bulk admin actions. These require service contracts, audit/idempotency and security design.

## 21. Telegram Scenario Matrix

| Role | Scenario | Value | Existing backend | Existing API | Event available | Telegram format | Complexity | Recommendation |
|---|---|---:|---:|---:|---:|---|---|---|
| all | account link/status/unlink | high | yes | yes | yes | inline/web | low | MVP |
| all | notification preferences | high | yes | yes | yes | inline | low | MVP |
| student | next lesson/today | high | partial | TMA partial | yes | message + link | low | MVP |
| student | new/checked work | high | yes | partial | yes | message + inline | low | MVP |
| student | deadline reminder | high | yes | task exists | yes | message + link | low | MVP |
| student | progress/achievements | medium | yes/partial | TMA progress | partial | message/web | medium | V2 |
| student | solve/submit complex task | medium | web | no bot API | partial | web | high | WEB ONLY |
| teacher | submission review queue | high | partial | no stable read API | yes | message + web | medium | MVP |
| teacher | today lessons | high | yes | partial | yes | message + link | low | MVP |
| teacher | overdue students | high | partial | no stable API | partial | digest | medium | V2 |
| teacher | grade/comment | high | service exists | not bot-safe | yes | web | high | WEB ONLY |
| parent | child schedule | high | yes | partial | yes | message/Mini App | medium | MVP |
| parent | child overdue/result digest | high | partial | needs scoped API | partial | digest | medium | V2 |
| parent | payment management | medium | billing exists | web-oriented | partial | web | high | WEB ONLY |
| admin | platform summary | high | partial | creator stats | partial | message/inline | medium | MVP |
| admin | critical errors | high | yes/partial | internal path | yes | immediate | low | MVP |
| admin | role/user deletion/billing | high | yes | not safe bot API | yes | web | high | WEB ONLY |
| owner | teacher mode | high | yes | bot mode exists | yes | menu | low | MVP |
| owner | platform stats | high | partial | Mini App stats | partial | message/Mini App | medium | MVP |
| owner | broadcasts | medium | yes | Mini App | yes | web/Mini App | medium | V2 |
| owner | failed jobs/load/full ops | high | partial | unknown | partial | alert/digest | medium | V2/LATER |

## 22. MVP Candidates

### Universal

Verified link/unlink, notification preferences, quiet-hours-aware delivery, deep-link builder, `/start`/menu/help, safe delivery dedupe and audit. Backend mostly exists; central service/read models still needed.

### Student

Today/next lesson, upcoming deadlines, submission checked/result, daily digest. Data and tasks largely exist; stable read aggregation and canonical links are needed.

### Teacher

New submission/review queue, lessons today, homework-note reminders, open student/work. Notification paths exist; teacher queue endpoint and scoped query service are needed.

### Parent

Verified child schedule and low-volume digest. Family scope exists; parent-specific read model, child selection and privacy copy are needed.

### Admin

Read-only summary, critical error alerts, deep links to admin panels. Existing handlers/services cover part; health/operational aggregation should be defined.

### Owner

Teacher/creator mode switch, platform summary, bug report/reply notification. Existing bot/Mini App has significant support; KPI contract and security audit remain.

## 23. Anti-features

- Full course/program/lesson editor in chat: too many fields and poor reviewability; use web deep-link.
- Large tests, rich answers, file/canvas work: Telegram message model is not the authoritative workspace; use lesson/task web UI.
- Full teacher gradebook and analytics: tables/filters/context are too dense; use web/Mini App.
- Permission, deletion, impersonation, billing or bulk admin actions: high-impact and hard to audit safely in chat; web with step-up auth.
- Sending every in-app event to Telegram: causes notification fatigue and duplicates existing in-app state.

## 24. Technical Blockers / Debt

1. No single domain-event bus; event names are inferred from services/tasks.
2. Telegram handlers contain role-specific SQL/aggregation, making reuse and testing harder.
3. Notification kinds and preference fields are partly specialized and not fully normalized.
4. `User` and `UserProfile` both carry Telegram identity/timezone-like data; ownership must be clarified.
5. Mixed aware/naive datetime patterns and multiple timezone helpers create DST/deadline risk.
6. Existing route permissions are stronger than a UI check, but a future bot service must not rely on handler menu visibility.
7. Parent reporting/attendance and some operational owner metrics are not established models/contracts.
8. Telegram delivery now has a durable `TelegramDeliveries` outbox with idempotency, retry/backoff and stale-claim recovery; specialized legacy reminder producers still use the existing preference-aware sender until migrated individually.

## 25. Open Questions

- Is the intended official bot one bot with role-aware menus or multiple bots?
- Which role is authoritative when a user has multiple roles, especially creator + teacher?
- What is the product policy for parent consent, minors, multiple children and data retention?
- Should Telegram be a notification channel only, or may it perform low-risk mutations?
- Which event priorities and digest cadence should product choose?
- Is `User.timezone_iana` or `UserProfile.timezone` the long-term canonical profile field?
- Are attendance, streak/XP/levels, formal reports and teacher-parent messaging planned or out of scope?
- Which current legacy routes are canonical for deep links in production?
- What is the required locale/content policy for Telegram messages?
- What monitoring, retry, dead-letter and webhook replay policy is required?
- Which admin/owner operational metrics are contractual and how should they be calculated?
- What is the Telegram ID/token retention and deletion policy?

## 26. Source Map

| Finding | Primary source |
|---|---|
| Flask factory, blueprint registration, Socket.IO, readiness | `app/__init__.py`, `wsgi.py`, `Procfile`, `nixpacks.toml` |
| Dependencies | `requirements.txt`, `package.json` |
| Domain model, roles, Telegram fields, timestamps | `core/db_models.py` |
| Default permissions and checks | `app/auth/permissions.py`, `app/auth/rbac_utils.py` |
| Telegram webhook/handlers/menu/linking | `app/telegram/webhook.py`, `app/telegram/handlers.py`, `app/telegram/keyboards.py` |
| Link code/token/status APIs | `app/api/routes.py`, `app/telegram/link_api.py` |
| Mini App auth and role endpoints | `app/telegram/mini_app.py`, `templates/telegram/mini_app.html` |
| Telegram delivery and notification kinds | `app/telegram/notifications.py`, `app/telegram/user_notify.py` |
| Unified in-app notification/dedupe/family routing | `app/notifications/service.py`, `app/notifications/routes.py` |
| Scheduled Telegram jobs | `app/tasks/telegram_dispatch.py`, `telegram_deadlines.py`, `telegram_daily_digest.py`, `telegram_lesson_reminders.py`, `telegram_homework_notes.py`, `telegram_broadcast.py` |
| Parent scope and dashboard | `app/parents/routes.py`, `templates/parent_dashboard.html`, `templates/sandbox/profile/_parent_body.html` |
| Schedule routes and timezone handling | `app/schedule/routes.py`, `app/utils/timezone.py`, `app/utils/datetime_utc.py`, `core/db_models.py` |
| Assignment/submission lifecycle | `app/assignments/routes.py`, `app/assignments/submission_lifecycle_service.py`, relevant models in `core/db_models.py` |
| Teacher/lesson/course workflows | `app/lessons/routes.py`, `app/courses/routes.py`, `app/groups/routes.py`, `app/assignments/routes.py` |
| Admin/owner operations | `app/admin/*`, `app/remote_admin/*`, `app/telegram/mini_app.py`, `app/telegram/handlers.py` |
| Existing integration tests and contracts | `tests/v2/test_telegram_bots_v2.py`, `test_parent_subsystem_v2.py`, `test_rbac_403_and_active_role.py`, `test_unified_timezone_contract.py`, `test_timezone_schedule_v2.py` |

## 27. Final Readiness Assessment

`EXISTS`: Telegram transport, linking, role menus, notifications, reminders, digest, TMA and creator/admin surfaces.

`PARTIAL`: unified event model, parent reporting, operational metrics, notification taxonomy, canonical timezone ownership and teacher inbox.

`REQUIRES BACKEND`: stable multi-role read API, parent digest read model and safe mutation endpoints. The core application read layer and durable delivery contract are now present.

`UNKNOWN`: final product policy, consent/retention, exact cadence, canonical production deep-link list and scope of owner operational monitoring.

Сейчас backend достаточно готов для notification-first Telegram MVP и deep-links. Он недостаточно готов для переноса полноценных учебных и административных рабочих процессов в чат без дополнительного API/service/security слоя.

## 28. Implementation Delta (2026-10-03)

После discovery в production-контур добавлен application/read-model слой `app/telegram/application.py` и стабильные Mini App read endpoints:

- `/tg-app/api/context` — проверенная identity и доступные role contexts;
- `/tg-app/api/home` — bounded role-aware Home;
- `/tg-app/api/action-center` — curated attention items;
- `/tg-app/api/teacher/review-queue` — teacher-scoped review queue;
- `/tg-app/api/teacher/students` — bounded mentor-scoped student summaries/search;
- `/tg-app/api/parent/children-summary` — подтверждённые дети и безопасная сводка;
- `/tg-app/api/parent/digest` — bounded digest подтверждённого ребёнка;
- `/tg-app/api/parent/context/switch` — scoped parent child preference;
- `/tg-app/api/operations/summary` — read-only admin/creator counts;
- `/tg-app/api/operations/problems` — bounded actionable problems;
- `/tg-app/api/operations/users/search` — safe bounded user search;
- `/tg-app/api/student/assignments` — canonical assignment categories.

Также добавлены canonical deep-link builders, creator context persistence, notification taxonomy normalization и role-aware Student/Teacher/Parent Home surfaces в Mini App. Эти изменения подтверждены regression suite (`20 passed` на Telegram/RBAC/timezone/schedule наборе) и не переносят grading, сложные задания, billing, permissions или destructive admin actions в Telegram.

Creator context можно безопасно переключать из Mini App через creator-only `/tg-app/api/context/switch`; parent summary использует batch queries без N+1, а notification delivery нормализует kind до dedupe/preferences policy.

Оставшиеся ограничения: нет единого event bus для всех доменных событий, полноценного teacher/student/parent mutation API здесь не добавлялся намеренно, а ручной QA в реальном Telegram client и production deployment требуют внешнего окружения. Durable Telegram outbox/retry/recovery contract реализован локально.
