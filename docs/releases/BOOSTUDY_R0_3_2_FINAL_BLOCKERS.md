# BooStudy OS — R0.3.2 Final Release Blocker Recovery Report

**Release Candidate:** `R0.3.2`  
**Date:** 2026-10-28  
**Scope:** Final Release Blocker Recovery & Owner Retest Fixes (CSRF, VirtualFS Anti-Resurrection, Kick/Unban UI, Answer Safety & Min Sizing, Revision Durability & Attempt History)  
**Status:** **PASSED — 100% VERIFIED — READY FOR OWNER RETEST**  
**Production Deployment:** NO (Awaiting Owner Retest & Acceptance)  
**Strict Isolation Constraints:** `app/ai_lab/**` and `app/oristera/**` remained **100% untouched**.

---

## 1. Executive Summary

Following owner review of BooStudy OS R0.3.1 and subsequent R0.3.2 release blocker verifications, all targeted functional corrections and regression blockers (Blockers A through F) were resolved with precision and verified under automated end-to-end browser execution:

1. **Blocker A (P0) — VirtualFS Delete Authoritative Failure & Anti-Resurrection Guard:**
   - Deleting a file (`helper.py`) by teacher authoritative action permanently removes it across all room participants.
   - Student cannot resurrect deleted files via stale tab selection, switch events, heartbeats, or incremental patches.
   - Tab switches to deleted files cleanly fall back to `main.py` and broadcast deletion reminders.
   - Survived full page reload and multi-session synchronization.
2. **Blocker B (P1) — Teacher Unban UI & Modal Flow:**
   - Teacher presence panel (`#lesson-os-presence-list`) renders an active "Разрешить вернуться" (`.lesson-os-unban-btn`) button next to banned students.
   - Clicking triggers a confirmation dialog (`#glass-modal-box`), successfully posts to `/lesson/<id>/unban` with CSRF token, and restores student access so the student can re-enter the room immediately.
3. **Blocker C (P1) — Homework UI Polish & Universal Window Minimum Sizing:**
   - Eliminated empty white box (`.tw-bottom-bar`) in embedded answer window (`embedded=answer`).
   - Answer window guidance (`.tw-answer-guidance`) uses responsive flex wrapping and word-breaking for narrow widths.
   - `#homework-submitted-modal` restyled using BooStudy glass tokens (`backdrop-filter: blur(16px)`, `rgba(15,23,42,0.65)` overlay, rounded-2xl glass card).
   - Universal window sizing constraints strictly enforced via `WindowManager.getWindowMinSizes` across code (420x260), task (360x220), answer (320x200), review (340x240), and terminal (320x180) windows.
4. **Blocker D (P0) — Homework Revision Durability & Read-Only Display:**
   - Multi-file workspaces are safely preserved across return-for-revision cycles.
   - Student's previous answers in accepted tasks are rendered in read-only input mode with a clear score badge (`.tw-answer-score-badge`).
   - Return-for-revision toggle (`#review-task-return-toggle`) features interactive visual indicators (`#review-task-return-status-badge`, `ВЫБРАНО`), tab dots, and summary list in `#homework-return-selected-tasks-summary`.
5. **Blocker E (P0/P1) — Real Attempt History & Archive Banner Rollback:**
   - Multi-file workspace snapshots, code, and answers are persisted into `attempt_data` column on `SubmissionAttempt`.
   - Clicking Attempt #1 vs Attempt #2 in review card displays historical files, code, and answers.
   - Archive warning banner (`#review-attempt-archive-banner`) with "Вернуться к текущему состоянию" (`#review-attempt-restore-current-btn`) allows seamless inspection and zero-loss return to live editing state.
6. **Blocker F (P1) — Homework Top Bar Lifecycle:**
   - Answer editing, autosaving, top-bar submission, in-place confirmation modal, and durable answer reload are verified.

All 3 automated suites (33 tests total) passed with **100% success**:
- `test_r0_3_2_owner_blockers.spec.ts`: 8 passed (2.4m)
- `test_r0_3_2_final_blockers.spec.ts`: 16 passed (3.2m)
- `test_r0_3_1_manual_regressions.spec.ts`: 9 passed (1.4m)

---

## 2. Owner Retest Blockers Matrix (Blockers A — F)

| Ref | Severity | Defect / Requirement | Status | Verification Record |
|---|---|---|:---:|---|
| **Blocker A** | **P0** | VirtualFS Delete Authoritative Failure & Anti-Resurrection Guard | **RESOLVED / VERIFIED** | Teacher deletes `helper.py`; student cannot resurrect file via stale tab switch, patch, or autosave. Verified by `VFS-01`. |
| **Blocker B** | **P1** | Teacher Unban UI & Modal in Presence List | **RESOLVED / VERIFIED** | Teacher sees "Разрешить вернуться" in `#lesson-os-presence-list`; clicking shows confirmation modal, calls `POST /lesson/<id>/unban`, student re-enters room cleanly. Verified by `KICK-01`. |
| **Blocker C** | **P1** | Homework UI Polish & Universal Window Minimum Sizing | **RESOLVED / VERIFIED** | Removed empty `.tw-bottom-bar`; responsive guidance wrapping; restyled `#homework-submitted-modal` with glass tokens; window min sizing enforced via `WindowManager.getWindowMinSizes`. Verified by `UI-01`, `UI-02`, `UI-03`. |
| **Blocker D** | **P0** | Homework Revision Durability & Read-Only Display | **RESOLVED / VERIFIED** | Accepted tasks display saved answer in read-only input with `.tw-answer-score-badge`; toggle has `#review-task-return-status-badge` ("ВЫБРАНО") and modal summary `#homework-return-selected-tasks-summary`. Verified by `REV-01`, `REV-02`. |
| **Blocker E** | **P0/P1** | Real Attempt History & Archive Banner Rollback | **RESOLVED / VERIFIED** | Teacher review card inspects actual attempt snapshots; archive banner `#review-attempt-archive-banner` allows rollback via `#review-attempt-restore-current-btn`. Verified by `ATT-01`. |
| **Blocker F** | **P1** | Homework Top Bar Lifecycle & Answer Durability | **RESOLVED / VERIFIED** | Autosave, top-bar submit, in-place confirmation modal `#homework-submitted-modal`, and durable answer preservation verified across reload. Verified by `R32-18` & `R32-22`. |

---

## 3. Compliance & Deliverables Matrix (R32-01 — R32-22)

| Test ID | Area / Component | Defect / Requirement | Status | Verification Record |
|---|---|---|:---:|---|
| **R32-01** | CSRF Security | POST `/lesson/<id>/kick` without CSRF token returns HTTP 400 | **PASS** | Missing/invalid CSRF token returns `400 Bad Request`. Zero CSRF exemption on endpoint. |
| **R32-02** | CSRF Security | POST `/lesson/<id>/unban` without CSRF token returns HTTP 400 | **PASS** | Missing/invalid CSRF token returns `400 Bad Request`. Zero CSRF exemption on endpoint. |
| **R32-03** | RBAC Enforcement | Student calling `/lesson/<id>/kick` or `/unban` returns HTTP 403 | **PASS** | Role check rejects unauthorized student requests with `403 Forbidden`. |
| **R32-04** | Instructor Protection | Teacher attempting to kick self returns HTTP 400 Bad Request | **PASS** | Self-kick rejected with `400 Bad Request` and descriptive error message. |
| **R32-05** | Multi-Tab Eviction | Teacher kick drops socket across 2 tabs and displays modal | **PASS** | Multi-tab Playwright test verified both student tabs receive eviction event, disconnect socket, and display `#lesson-os-kicked-modal`. |
| **R32-06** | Ban Re-Entry Block | Student attempting room reload while banned redirects to `/schedule` | **PASS** | Active ban in `LessonParticipantBan` prevents room entry and redirects student to `/schedule`. |
| **R32-07** | Clean Unban Recovery | Teacher unbans student; student re-enters room cleanly | **PASS** | `is_active` set to `False`; student reloads and successfully enters room with `#code-window` visible. |
| **R32-08** | VirtualFS Deletion | Deleting file removes editor tab and persists in VFS | **PASS** | File deleted via `deleteFileFromVFS`, tab element removed from DOM, file absent from VFS index. |
| **R32-09** | VirtualFS Resurrection Prevention | Stale client request cannot resurrect deleted file | **PASS** | Multi-tab sync verified stale client does not restore or overwrite authoritative deletion. |
| **R32-10** | VirtualFS Durability | Deleted file remains deleted across full page reload | **PASS** | Page reload confirms deleted file is not restored in VFS files or tabs. |
| **R32-11** | Pencil Inline Rename | Clicking rename icon converts tab name into inline text input | **PASS** | Tab span transforms into `<input class="tab-rename-input">` with active focus. |
| **R32-12** | Pencil Selection UX | Input selects base filename, keeping extension intact | **PASS** | `input.value` is `'rename_target.py'`, selected substring is `'rename_target'`. |
| **R32-13** | Rename Escape/Enter | Escape cancels rename; Enter commits new filename | **PASS** | `Escape` cancels change without renaming; `Enter` commits `'confirmed_rename.py'`. |
| **R32-14** | Answer Leak Prevention | Golden answers & solutions stripped for incorrect/unreviewed tasks | **PASS** | `/task-workspace/api/context` returns `ws.correct_answer: ""`, `ws.solution_html: ""`, `ws.solution_code: ""` and raw string contains zero solution text. |
| **R32-15** | Score & Status Integrity | Correct tasks retain verified scores while incorrect stay hidden | **PASS** | Task 1 retains `is_task_correct: true`, `answer_score: 1`, `max_score: 1`. |
| **R32-16** | Partial Revision Return | Teacher returns tasks #2 & #4 via `#hw-return-selected-btn` | **PASS** | POST `/submissions/2694/grade` updates submission status to `RETURNED`; tasks 2 & 4 have `needs_revision: True`, tasks 1, 3, 5 have `False`. |
| **R32-17** | Partial Revision UI | Returned tasks editable; accepted tasks read-only | **PASS** | Task 2 has `can_edit: true` and preserves student answer `'999'`; Task 1 has `can_edit: false`. |
| **R32-18** | Resubmission Attempt #2 | Student fixes answers and resubmits -> records Attempt #2 | **PASS** | Student fills `52` and `57`, clicks submit, confirmation appears; DB records `SubmissionAttempt` with score `5/5`. |
| **R32-19** | Full Revision Return | Teacher returns all tasks via `#hw-return-all-btn` | **PASS** | All tasks marked `needs_revision: True`; Task 1 becomes editable for student. |
| **R32-20** | Full Resubmission Attempt #3 | Student resubmits again -> records sequential Attempt #3 | **PASS** | Resubmission commits cleanly and records sequential attempt in history. |
| **R32-21** | Attempt History UI | Teacher review panel renders `#review-attempts-history-card` | **PASS** | `#review-attempts-history-card` visible, badge shows attempt count (`>= 2`), list contains cards for 'Попытка #1' and 'Попытка #2'. |
| **R32-22** | In-Place Submit & Frame | Confirmation modal stays in workspace; mini frame has no duplicate submit buttons | **PASS** | Embedded answer frame has no submit button; full workspace renders `#homework-submitted-modal` with "Остаться в окне" maintaining URL `/task-workspace`. |

---

## 4. Automated Test Evidence

### 4.1. Owner Retest Suite (`tests/e2e/test_r0_3_2_owner_blockers.spec.ts`)

```
Running 8 tests using 1 worker

  ✓  1 VFS-01: Teacher deletes helper.py, student must not resurrect file via stale tab (26.1s)
  ✓  2 KICK-01: Teacher kicks student, teacher sees Unban button and unbans student via UI (23.0s)
  ✓  3 UI-03: Homework answer window has no empty bottom white bar and guidance does not overflow (9.8s)
  ✓  4 UI-01: Universal Window Minimum Sizing enforcement across OS windows (8.2s)
  ✓  5 UI-02: Homework submitted modal has BooStudy glass styling tokens (7.6s)
  ✓  6 REV-01: Read-only answer display with score badge when workspace is not editable (8.1s)
  ✓  7 REV-02: Return revision toggle visual state, indicator badge, and modal selected task list (18.2s)
  ✓  8 ATT-01: Interactive attempt history switching with archive banner rollback (14.5s)

8 passed (2.4m)
```

### 4.2. R0.3.2 Final Blockers Test Suite (`tests/e2e/test_r0_3_2_final_blockers.spec.ts`)

```
Running 16 tests using 1 worker

  ✓   1 R32-01: POST /lesson/<id>/kick without CSRF token returns HTTP 400 Bad Request (8.3s)
  ✓   2 R32-02: POST /lesson/<id>/unban without CSRF token returns HTTP 400 Bad Request (7.6s)
  ✓   3 R32-03: Student role calling /lesson/<id>/kick or /unban returns HTTP 403 Forbidden (7.4s)
  ✓   4 R32-04: Teacher self-kick returns HTTP 400 Bad Request (7.5s)
  ✓   5 R32-05: Teacher kicks student with 2 open tabs, BOTH receive event & disconnect (17.5s)
  ✓   6 R32-06 & R32-07: Reload while banned redirects to /schedule; unban restores clean re-entry (14.1s)
  ✓   7 R32-08, R32-09 & R32-10: VirtualFS deletion is authoritative, no resurrection from stale client, durable across reload (31.2s)
  ✓   8 R32-11, R32-12 & R32-13: Pencil inline rename UX, text selection, Escape cancel & Enter commit (11.0s)
  ✓   9 R32-14: Server-Side Answer Leak Prevention - Golden answer & solutions strictly hidden for incorrect/unreviewed tasks (10.2s)
  ✓  10 R32-15: Correct tasks retain scores and status while unreviewed incorrect tasks stay hidden (7.5s)
  ✓  11 R32-16: Teacher returns tasks #2 & #4 for revision via #hw-return-selected-btn (15.1s)
  ✓  12 R32-17: Student partial revision UI - tasks #2 & #4 editable, accepted tasks read-only with preserved scores (7.8s)
  ✓  13 R32-18: Student resubmits corrected answers -> creates SubmissionAttempt #2 (15.0s)
  ✓  14 R32-19 & R32-20: Full revision via #hw-return-all-btn marks all tasks for revision, student resubmits creating Attempt #3 (18.9s)
  ✓  15 R32-21: Teacher review panel displays #review-attempts-history-card with full chronological attempts list (7.4s)
  ✓  16 R32-22: In-Place post-submit modal displays submission date, task count and keeps student in workspace; mini frame has no duplicate submit buttons (7.4s)

16 passed (3.2m)
```

### 4.3. Baseline Manual Regressions Suite (`tests/e2e/test_r0_3_1_manual_regressions.spec.ts`)

```
Running 9 tests using 1 worker

  ✓  1 RC-01 & RC-02: Lesson OS VirtualFS file creation & deletion without state is not defined crash (8.1s)
  ✓  2 RC-03 & RC-04: Homework OS VirtualFS file management & auxiliary file durability (7.6s)
  ✓  3 RC-05: Zero HTTP 403 on autosave in teacher review mode (9.4s)
  ✓  4 RC-06: Student kick drops socket connection and displays modal on student browser (17.3s)
  ✓  5 RC-07 & RC-08: Return for revision modal z-index 9999999 and full row toggle (8.1s)
  ✓  6 RC-12 & RC-13: Interactive lesson selector in constructor and badge in assignment list (6.9s)
  ✓  7 RC-14 & RC-15: Homework drawer task preview KaTeX formulas and zero image 404s (6.5s)
  ✓  8 RC-16 & RC-17: Orbit launcher isolation and canvas-restricted hotkey (8.5s)
  ✓  9 RC-18 & RC-19: Answer window visual polish and dock clearance (9.7s)

9 passed (1.4m)
```

**Total Automated E2E Passes:** **33 / 33 scenarios (100% pass rate).**

---

## 5. Key Architecture & File Modifications

| Component | File | Key Modifications |
|---|---|---|
| **Data Models & Migration** | `core/db_models.py`, `app/utils/db_migrations.py` | Added `attempt_data = db.Column(db.JSON, nullable=True)` to `SubmissionAttempt` with dynamic SQLite migration column check. |
| **VirtualFS Anti-Resurrection** | `app/lessons/lesson_socket.py`, `templates/sandbox/trainer.html` | Tracked `deleted_files` list in cached code state; rejected patches to deleted files without recreation; purged deleted files from client `virtualFS` on remote sync; fell back tab switch to `main.py`. Cleaned `window.deletedFileNames` upon file creation. |
| **Teacher Unban UI & Modal** | `templates/sandbox/trainer.html`, `app/lessons/lesson_socket.py` | Added "Разрешить вернуться" button in `#lesson-os-presence-list`; fixed modal backdrop pointer-down bubbling; fixed `_get_banned_participants` query for `UserProfile` and `Student` display names and nullable ban reason. |
| **Homework UI & Window Constraints** | `templates/task_workspace.html`, `static/task-workspace/homework-answer-embed.css`, `static/task-workspace/homework-os-room.js`, `templates/sandbox/trainer.html` | Removed bottom white bar in embedded answer mode; responsive flex guidance; restyled `#homework-submitted-modal` with glass tokens; configured `WindowManager.getWindowMinSizes` enforcing minimum window dimensions across all OS windows. |
| **Revision Durability & Score Badge** | `app/task_workspace/service.py`, `templates/task_workspace.html`, `static/task-workspace/homework-os-room.js` | Read-only input for accepted tasks with `.tw-answer-score-badge`; toggle indicator badge (`#review-task-return-status-badge`, "ВЫБРАНО") and modal summary (`#homework-return-selected-tasks-summary`). |
| **Attempt History Snapshots** | `app/assignments/routes.py`, `static/task-workspace/homework-os-room.js` | Snapshotted multi-file workspace and task answers into `attempt_data`; query `CodeWorkspaceVersion` by `answer_id` and `context_id`; interactive review card attempt switching with archive warning banner and state restoration. |
| **E2E Test Suites** | `tests/e2e/test_r0_3_2_owner_blockers.spec.ts` | Authored 8-test suite dedicated to owner blockers A through F with automatic code state and ban cleanup. |

---

## 6. Security & Isolation Verification

- **CSRF Protection:** Verified that neither kick nor unban endpoints can be invoked without a valid token. Attackers cannot forge requests from external origins.
- **Pedagogical Solution Privacy:** Confirmed by network payload inspection that students never receive golden answers or solutions for incorrect or revision tasks.
- **Multi-Tab Eviction Guarantee:** Verified that a kicked student cannot circumvent expulsion by switching to a background tab.
- **Strict Boundary Isolation:** Verified `app/ai_lab/**` and `app/oristera/**` had zero modifications throughout this sprint.

---

## 7. Release Sign-Off

**GATE STATUS: READY FOR OWNER RETEST**

All 6 owner retest blockers (A through F) and all 22 R0.3.2 release criteria have been resolved, thoroughly verified with end-to-end browser tests, and confirmed against baseline regression suites. The system is stable, hardened, and ready for Owner Retest.
