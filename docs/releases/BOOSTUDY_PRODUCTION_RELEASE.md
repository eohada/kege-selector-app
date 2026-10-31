# BooStudy OS — Production Release Report

**Release Date & Time:** 2026-10-31 20:43 UTC+3  
**Status:** **PRODUCTION DEPLOYED — HEALTHY**  
**Domain:** `https://boostudy.ru`  
**Host IP:** `72.56.239.25` (Timeweb Cloud VPS `6559303-gg070737.twc1.net`)  
**Deployment Pipeline:** GitHub Actions (`Deploy to VPS (MANUAL PROD)`, Run ID: `41225562747`)  
**Helper Script:** `/opt/boostudy/scripts/deploy_blue_green.sh`  

---

## 1. Release Candidate Commit

- **Release Commit SHA:** `f6edc1f6173244d566b3f3083480cd35aafcecb5`
- **Branch:** `main` (synchronized with `feature/livekit-video` and `origin/main`)
- **Working Tree State:** Clean (zero uncommitted changes, untracked artifacts safely ignored)
- **Included Enhancements:**
  - BooStudy OS Unified Editor (`CodeMirror 5` + `Skulpt` single-instance runner + split-diff sync).
  - Virtual Workspaces & Page Separation (`_os_page_workspaces` concurrent locking & persistence).
  - Window interaction stabilization (z-index hierarchy, minimum dimensions, edge-drag bounds).
  - Homework OS single-file submission recovery & attempt data persistence.
  - Forward-only database expand migrations with strict PostgreSQL compatibility.
  - Cache-first storage security hardening (`Cache-Control: private, max-age=2592000, immutable`).

---

## 2. Deployment Target & Blue-Green State

- **Target Architecture:** Zero-downtime Blue-Green Docker Compose with Nginx reverse proxy.
- **Color Transition:**
  - **Previous Active Color:** `blue` (port 8001)
  - **Target Color Deployed:** `green` (port 8002)
  - **New Active Upstream:** `green` (port 8002) via `/etc/nginx/snippets/boostudy-active-upstream.conf`
- **Drain Policy:** 90-second drain window executed gracefully to allow in-flight HTTP requests and WebSockets to drain.
- **Rollback Hot-Standby:** Container `boostudy_web_blue` is kept running on port 8001 for instantaneous zero-rebuild rollback if needed. Image prune skipped to retain instant rollback cache.

---

## 3. Data Safety & Backup Verification

- **Preservation Policy:** Strict forward-only / expand-only operations.
- **Destructive Operations:** ZERO drop table, drop column, or destructive data mutations executed.
- **User & Content Integrity:**
  - All existing users, profiles, and role assignments preserved intact.
  - All lessons, schedules, recurring slots, homework assignments, and student submissions preserved intact.
  - Uploaded student code files, Google Drive assets, and local uploads preserved intact.

---

## 4. Applied Database Migrations

The production PostgreSQL database was upgraded sequentially through the verified forward-only migration chain:

1. `release_r0_wf_bans_pub`:
   - Adds `LessonParticipantBans` table with indexes on `lesson_id`, `user_id`, and composite index.
   - Adds `Submissions.results_published_at` (`DateTime(timezone=True)`).
2. `sched_s2_teacher_and_subject`:
   - Adds `teacher_id` and `subject` columns to `Lessons` with composite index `ix_lessons_teacher_date`.
3. `sched_s2_recur_availability`:
   - Adds recurring columns to `Lessons` and `RecurringLessonSlots`.
   - Creates `RecurringSlotExceptions`, `TeacherWeeklyAvailabilities`, and `TeacherScheduleExceptions` tables.
4. `20261031_submission_attempt_data`:
   - Adds nullable column `attempt_data` (`JSONB` on PostgreSQL) to `SubmissionAttempts`.
5. `20261031_schema_contract_indexes`:
   - Ensures explicit model indexes match database schema:
     - `LessonParticipantBans.ix_LessonParticipantBans_is_active`
     - `RecurringLessonSlots.ix_RecurringLessonSlots_subject`
     - `RecurringLessonSlots.ix_RecurringLessonSlots_series_id`

**Pre-Migration PostgreSQL Compatibility Guard:**  
Added dynamic column widening check in `migrations/env.py` to ensure `alembic_version.version_num` is widened to `VARCHAR(128)` in PostgreSQL, preventing `StringDataRightTruncation` on custom revision names.

---

## 5. Preflight & Test Verification

Prior to release and deployment, the following contract and regression suites passed with 100% success:

- **Blue-Green Contract & Safety Tests:** `tests/v2/test_deploy_bluegreen_contract.py` (4/4 PASSED)
- **V2 Schema Contract Tests:** `tests/v2/test_schema_contract_v2.py` (6/6 PASSED)
- **Release Readiness & Gamification Tests:** `tests/v2/test_release_readiness_v2.py` (3/3 PASSED)
- **End-to-End Browser UX Tests:**
  - `test_unified_editor_and_windows.spec.ts`: 25/25 PASSED
  - `test_homework_single_file.spec.ts`: 24/24 PASSED
- **Staging Preflight Script:** `scripts/staging_preflight.sh` verified connectivity to PostgreSQL, Redis, LiveKit JWT generation, memory, and disk space.

---

## 6. Deployment Execution Log Summary

- **Run ID:** `41225562747`
- **Trigger:** Manual `workflow_dispatch` on `refs/heads/main`
- **Execution Steps:**
  1. `git fetch origin main` & `git reset --hard origin/main` -> updated server workspace to commit `f6edc1f6173244d566b3f3083480cd35aafcecb5`.
  2. `docker compose -f docker-compose.bluegreen.yml build web_green` -> green image built successfully.
  3. `flask db upgrade -d /app/migrations` -> applied migrations up to `20261031_schema_contract_indexes`.
  4. `flask schema-audit` -> executed inside green container: **Schema contract: OK**.
  5. `docker compose -f docker-compose.bluegreen.yml up -d web_green` -> container `boostudy_web_green` started on port 8002.
  6. `wait_ready green` -> probed `http://127.0.0.1:8002/ready` -> returned `status: OK`.
  7. `write_nginx_upstream green` -> wrote upstream file pointing to `127.0.0.1:8002`.
  8. `nginx -t` & `nginx -s reload` -> Nginx configuration validated and reloaded without connection drops.
  9. `drain_old blue` -> 90-second drain window completed.

---

## 7. Live Production Smoke Test Results

All public and core application endpoints were probed live on `https://boostudy.ru` immediately after deployment:

| # | Endpoint / Resource | URL | Status | Response Size |
|---|---------------------|-----|--------|---------------|
| 1 | Readiness Probe | `https://boostudy.ru/ready` | **HTTP 200 OK** | 166 B |
| 2 | Health Probe | `https://boostudy.ru/health` | **HTTP 200 OK** | 144 B |
| 3 | Public Landing | `https://boostudy.ru/` | **HTTP 200 OK** | 69.7 KB |
| 4 | Authentication Login | `https://boostudy.ru/login` | **HTTP 200 OK** | 12.0 KB |
| 5 | Authentication Register | `https://boostudy.ru/register` | **HTTP 200 OK** | 18.4 KB |
| 6 | Legal Hub | `https://boostudy.ru/legal` | **HTTP 200 OK** | 16.7 KB |
| 7 | Legal Public Offer | `https://boostudy.ru/legal/offer` | **HTTP 200 OK** | 132.5 KB |
| 8 | Privacy Policy | `https://boostudy.ru/legal/privacy` | **HTTP 200 OK** | 129.1 KB |
| 9 | Legal Consent | `https://boostudy.ru/legal/consent` | **HTTP 200 OK** | 122.2 KB |
| 10 | Public Pricing Plans | `https://boostudy.ru/billing/plans/public` | **HTTP 200 OK** | 76.4 KB |
| 11 | Design System CSS | `https://boostudy.ru/static/css/boostudy-design-system.css` | **HTTP 200 OK** | 192.7 KB |
| 12 | Lesson OS CSS | `https://boostudy.ru/static/css/lesson-os-v2.css` | **HTTP 200 OK** | 81.9 KB |
| 13 | Task Workspace JS | `https://boostudy.ru/static/task-workspace/task-workspace.js` | **HTTP 200 OK** | 145.6 KB |
| 14 | Homework OS Room JS | `https://boostudy.ru/static/task-workspace/homework-os-room.js` | **HTTP 200 OK** | 124.3 KB |

### Production Readiness Probe Payload:
```json
{
  "checks": {
    "db": true,
    "migrations": true,
    "redis": true,
    "schema": true,
    "socketio": true
  },
  "environment": "production",
  "status": "OK",
  "timestamp": "2026-10-31T17:46:31.585718"
}
```

---

## 8. Infrastructure State

- **PostgreSQL Database:** Connected, healthy (`db: true`), migrations aligned (`migrations: true`), schema audit passing (`schema: true`).
- **Redis & Celery Broker:** Connected, ping responding (`redis: true`), message queue active.
- **Socket.IO:** Redis adapter active on channel `boostudy_socketio_production` (`socketio: true`).
- **Nginx Reverse Proxy:** Upstream routed to `boostudy_web_green` (`127.0.0.1:8002`), SSL certificate valid (`https://boostudy.ru`).
- **LiveKit WebRTC:** Token issuance active in pilot mode.

---

## 9. Rollback Readiness

- The previous stable container (`boostudy_web_blue` on port 8001) remains running and healthy.
- If rollback is ever required, executing `sudo -n /opt/boostudy/scripts/deploy_blue_green.sh rollback` on the server immediately switches Nginx back to port 8001 in under 2 seconds without rebuilding Docker containers.
- All database schema modifications are backward-compatible with the blue container (expand-only columns and tables).

---

## 10. Strict Boundaries & Isolation Compliance

- `app/ai_lab/**`: Strictly untouched; kept disabled in production (`AI_LAB_ENABLED=false`).
- `app/oristera/**`: Strictly untouched; isolated from production workflows.
- `Tutor Core` heuristics: Preserved unchanged.
- `Learning Evidence`: Preserved unchanged.
- Telegram Mini App: Flag-gated (`TELEGRAM_MINI_APP_ENABLED=0`).

---

## 11. Final Empirical Verdict

The BooStudy OS release has been deployed to Timeweb Cloud production infrastructure via the automated blue-green deployment pipeline. All safety gates, database migrations, schema audits, zero-downtime traffic switches, and live production smoke tests have completed with **100% SUCCESS**.

**STATUS:** **`PRODUCTION DEPLOYED — HEALTHY`**
