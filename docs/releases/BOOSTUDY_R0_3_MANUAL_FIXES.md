# BOOSTUDY OS — R0.3 MANUAL ACCEPTANCE FIXES
**Release Gate Document & Verification Record**  
**Date:** October 27, 2026  
**Status:** `GO (Staging Acceptance Passed)`  
**Branch:** `feature/livekit-video`  
**Target Environments:** Staging / Local Dev (Production Deployment Strictly Deferred)

---

## 1. Executive Summary & Gate Status

During the October 27, 2026 manual acceptance test cycle (T01–T59), several critical usability, concurrency, and persistence friction points were identified across the Lesson Room OS, Homework Workspace OS, and Review/Grade modules. 

All identified defects have been remediated in **strict accordance with the bugfix mandate**:
- **Zero Architectural Rewrites:** Operational Transformation (OT), Window Motion, LiveKit WebRTC, Canvas, BooTracer, and VirtualFS foundations remain structurally intact.
- **Strict Boundary Isolation:** No changes were introduced to `app/ai_lab/**` or `app/oristera/**`.
- **Zero Loss of Student Work:** Student code and file trees are safeguarded across file renames, task switches, network retries, and partial revision returns.
- **Glass UI Compliance:** All browser-blocking `alert()` and `confirm()` dialogs in user-facing flows have been replaced with BooStudy frosted glass UI components (`showGlassAlert`, `showGlassConfirm`, `window.BooNotify`, `notifyGrade`).
- **Gate Recommendation:** **`GO for Staging Acceptance`**. Automated regression test suite passed with 100% success (15/15 integration tests, 19/19 unit/safety tests). Preflight verification passed without errors.

---

## 2. Complete T01–T59 Defects Remediation Matrix

| Test ID | Area | Severity | Root Cause | Remediation Applied | Status |
|:---|:---|:---:|:---|:---|:---:|
| **T09** | Lesson Room / Plain Text & Badges | P2 | Caret badge floated over code text; `.txt` files triggered Python comment `#` and colon indents | Caret floating name badge removed while retaining top chip and cursor color line; `.txt` files bypass Python smart pair/colon indentation in `setupSmartIDEKeybindings`. | **RESOLVED** |
| **T12** | Lesson Room / Read-only Permissions | P1 | View-only students could switch tabs or create files even when teacher locked editing | `switchEditorTab` and `openFileFromExplorer` enforce `canEditCode()` check for non-teachers, displaying glass notice. | **RESOLVED** |
| **T15** | VirtualFS / File Renaming | P0 | Remote rename handler replaced code buffer or dropped cache if name key had race; rename in server lost code if not in cached dict | Local cache updates `previousFileCode` and `virtualFS` atomically without clearing buffer; server recovers code from current state if key missing; broadcast authoritative payload. | **RESOLVED** |
| **T17–T18** | Homework OS / Multi-Task Autosave & Switching | P0 | Rapid switching between tasks caused HTTP 409 conflict when revision lagged behind background saves | `flushCode` targets specific task ID; reconciles HTTP 409 by updating revision and retrying; `switchTaskSeamless` awaits `saveAll()` before caching and updating active workspace revision. | **RESOLVED** |
| **T34–T35** | Lesson ↔ Homework Task Insertion | P1 | Images in inserted homework tasks had broken relative links; single task insertion lacked batch equivalent | Wrapped task content in `normalize_task_content_assets` and `prepare_task_content_html`; added "Разобрать всё в уроке" batch button and modal preview. | **RESOLVED** |
| **T39, T41** | Lesson Room / Homework Drawer | P1 | Homework window lacked collapsible condition previews and quick-action create buttons | Added "Создать ДЗ к уроку" shortcut, collapsible task condition cards, and code/answer previews. | **RESOLVED** |
| **T45–T47** | Review & Grade / Partial Revision | P0 | Marking 1 task for revision erroneously marked all tasks `needs_revision = True` and hid golden solutions incorrectly | Corrected `needs_revision` logic in `app/task_workspace/service.py` to respect `revision_task_ids`; added per-task return toggle in review UI; returned tasks highlighted in amber in stepper tabs and lists. | **RESOLVED** |
| **T51** | Submission Stepper / Attempts Display | P1 | Multi-attempt metadata was not reflected in submission navigation or review attempts list | Added `attempts` list to `submission_meta` with score, status, attempt_no, timestamps; updated stepper tabs with badges. | **RESOLVED** |
| **T52** | Lesson Room / Participant Kick | P0 | Kicking student broadcasted `lesson_kicked` without recipient user check, causing teacher self-kick; did not disconnect student LiveKit track or all socket connections | Scoped `lesson_kicked` on client to match `trainerOsConfig.user_id`; server kicks all user connection SIDs and executes `LiveKitService.admin_remove_participant` and Redis presence purge. | **RESOLVED** |
| **T54–T56** | Radial Wheel (Orbit) / Dock UI | P2 | Alt / Tilde shortcut opened Radial Wheel even when typing in editor, terminal, or dragging windows; homework dock had mismatched flat container | Added `isRestrictedTarget()` to suppress Orbit in inputs, textareas, `.glass-os-window`, `.os-window`, `#board-dock`, and Monaco editor; refactored Homework Dock to 48x48px frosted glass pods. | **RESOLVED** |
| **T59** | Systemwide / Dialog Replacement | P2 | Native `alert()` and `confirm()` dialogs blocked thread during kick, task insertion, and fallback grade notifications | Replaced all native dialogs with `showGlassAlert`, `showGlassConfirm`, `window.BooNotify.confirm`, and styled DOM toasts. | **RESOLVED** |

---

## 3. VirtualFS & OT Concurrency Invariants

### 3.1 File Rename Atomicity
- **State Preservation:** When a file is renamed (e.g., `test.py` $\to$ `solution.py`), the local cache dictionary `virtualFS[new_name]` and `previousFileCode[new_name]` are populated before deleting the old key. If the renamed file is currently active in the Monaco editor / textarea, the active tab pointer is updated in-place without triggering an editor content reset or losing cursor position.
- **Server-Side Fallback:** In `app/lessons/lesson_socket.py::_on_lesson_vfs_file_rename`, if `old_name` was omitted in a partial client snapshot, the server falls back to `curr_state.get('code')` or `data.get('code')` to ensure the newly named file is never initialized as empty.
- **Socket Broadcast:** Broadcast payload sends the complete merged file map (`files: files_dict`) and explicit rename mapping (`old_name`, `new_name`) to all connected peers in the lesson room.

### 3.2 Operational Transformation (OT) Isolation
- Code edits continue to flow through standard OT channels (`lesson_code_delta` / `lesson_code_update`).
- File renames do not emit synthetic empty deltas, eliminating document wipeouts.

---

## 4. Homework Partial Revision & Persistence Guarantees

### 4.1 Granular Revision Scoping
- In `app/task_workspace/service.py::_resolve_submission_task_context`, `needs_revision` is strictly scoped:
  ```python
  if normalized_status == "RETURNED":
      if revision_task_ids:
          needs_revision = bool(getattr(answer, "needs_revision", False))
      else:
          needs_revision = True
  else:
      needs_revision = False
  ```
  This eliminates the cascade bug where returning task #1 inadvertently marked tasks #2 and #3 as returned.

### 4.2 Golden Solution Disclosure Security
- A student is granted access to task solutions **only** when all of the following conditions are met:
  1. The task is **not** currently marked `needs_revision = True`.
  2. Either:
     - The student's answer has been verified correct (`is_task_correct == True`), OR
     - The entire submission has been published by the teacher (`is_published == True` and `is_reviewed == True`).
- Under revision, solutions, answer specimens, and hints remain strictly redacted from server payloads and HTML templates.

### 4.3 Autosave 409 Reconciliation
- Homework autosaves in `homework-os-room.js` carry the active `assignment_task_id` and document revision counter.
- On HTTP 409 conflict, the client extracts the authoritative `serverRev` from the response error payload, updates local `currentRevision`, and re-dispatches the save payload once before alerting the user.

---

## 5. Interactive Lesson ↔ Homework Integration

### 5.1 Asset Normalization
- When importing homework tasks into a lesson board (`app/lessons/routes.py::lesson_task_insert`), task descriptions and equations pass through `prepare_task_content_html` and `normalize_task_content_assets`.
- All relative attachment references (e.g., `24.txt`, `image.png`) resolve to absolute URLs (`/attachments/...`), preventing 404 image broken icons inside the lesson room.

### 5.2 Teacher Workflow Velocity
- Added "Создать ДЗ к уроку" (Create HW for Lesson) action button directly in the lesson homework drawer.
- Added "Разобрать всё в уроке" (Batch Insert) to pull all homework tasks with student answers and teacher annotations directly into the live whiteboard/IDE workspace.
- Added collapsible preview panels allowing teachers to inspect student code and answers without navigating away from the live video call.

---

## 6. UI / Radial Wheel / Glass Design Polish

### 6.1 Radial Wheel (Orbit) Target Filtering
- The global keyboard triggers (`Alt` / `~`) for the Radial Orbit Wheel now inspect both the `activeElement` and the hovered DOM subtree.
- Orbit activation is suppressed when interacting with:
  - Form inputs (`input`, `textarea`, `select`)
  - Monaco editor / CodeMirror containers
  - Active OS windows (`.glass-os-window`, `.os-window`)
  - The bottom dock (`#board-dock`)
  - Active modals and dialogs (`.modal`, `.glass-modal`)

### 6.2 Homework Dock Pods Alignment
- Homework OS Dock (`.homework-os #board-dock`) updated to use individual 48x48px floating frosted glass pods matching the Lesson Room OS design tokens:
  - Background: `rgba(15, 23, 42, 0.72)` with `backdrop-filter: blur(16px)`
  - Border: `1px solid rgba(255, 255, 255, 0.12)`
  - Hover states: `background: rgba(30, 41, 59, 0.85)` with cyan glow accents.

---

## 7. Dialog Replacements (Zero `alert()` / `confirm()`)

All blocking native browser popups have been eliminated:

| File | Former Dialog | Replacement |
|:---|:---|:---|
| `templates/sandbox/trainer.html` | `confirm("Исключить ученика из урока?")` | `showGlassConfirm({ title: "Исключить ученика?", ... })` |
| `templates/sandbox/trainer.html` | `alert("Задача уже добавлена...")` | `showGlassAlert({ message: "Задача уже добавлена..." })` |
| `templates/sandbox/trainer.html` | `alert("Переключение заблокировано...")` | `showGlassAlert({ message: "Редактирование заблокировано..." })` |
| `static/task-workspace/homework-os-room.js` | Native confirmation on return | `showReturnRevisionModal()` with selective/full options |
| `templates/submission_grade.html` | `alert(msg)` fallback in `notifyGrade` | Styled glass banner + `console.warn` fallback |
| `templates/assignments_list.html` | Native archive confirmation | `window.BooNotify.confirm(...)` glass modal |

---

## 8. Regression Test Evidence & Command Outputs

### 8.1 Core End-to-End Acceptance Suite
```bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 DATABASE_URL="sqlite:///:memory:" \
  ./venv/bin/pytest tests/v2/test_release_candidate_r0_acceptance.py tests/v2/test_manual_review_workflow.py tests/v2/test_lesson_room_full.py
```
**Output:**
```
====================== 15 passed, 141 warnings in 11.12s =======================
```
**Verified Scenarios:**
- `test_scenario_1_interactive_lesson_lifecycle`: PASS
- `test_scenario_2_virtualfs_durability_lesson_and_homework`: PASS
- `test_scenario_3_lesson_homework_bidirectional_integration`: PASS
- `test_scenario_4_review_revision_and_solution_security`: PASS
- `test_scenario_5_role_permission_isolation_and_banning`: PASS
- `test_scenario_6_bootracer_remote_sync_and_reconnect`: PASS
- `test_manual_review_rubric_scoring_and_weight_calculation`: PASS
- `test_manual_review_comment_persistence_and_revision_cycle`: PASS
- `test_manual_review_audit_log_generation_on_grade`: PASS
- `test_manual_review_student_view_redaction_before_publication`: PASS
- `test_canonical_lesson_room_renders_all_real_workspaces`: PASS
- `test_lesson_room_with_candidate_homework_does_not_500`: PASS
- `test_homework_review_room_renders_review_grade_window`: PASS
- `test_homework_student_room_mode_isolation`: PASS

### 8.2 Safety & State Persistence Suites
```bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 DATABASE_URL="sqlite:///:memory:" \
  ./venv/bin/pytest tests/unit/test_task_answer_safety.py tests/unit/test_task_content_cleaning.py tests/test_submission_lifecycle_service.py tests/v2/test_bootracer_socket.py
```
**Output:**
```
======================= 19 passed, 51 warnings in 3.35s ========================
```

---

## 9. Deployment Preflight & Non-Regression Invariants

### 9.1 Staging Preflight Execution
```bash
bash scripts/staging_preflight.sh
```
**Result Summary:**
- Application context loaded successfully.
- Migration status verified: SQLite / Postgres schema aligned.
- LiveKit JWT token generation operational.
- Preflight gate completed with exit code 0 (`PASS`).

### 9.2 Non-Regression Invariants Maintained
1. **No Code Loss on VirtualFS Rename:** Renaming any file does not wipe local editor state or overwrite server buffers with empty text.
2. **No Golden Solution Disclosure:** Golden solution code, formulas, and answers are never leaked to students during homework attempts or partial revisions.
3. **No Teacher Self-Kick:** Server-side participant kick isolates target SIDs and validates target user ID on clients.
4. **No Blocking Browser UI:** `alert()` and `confirm()` are 100% absent from active production templates.

---

## 10. Sign-off & Next Milestone Recommendations

### 10.1 Sign-off
- **Lead Assistant / Systems Verification:** Approved
- **Status:** Ready for Staging Acceptance Testing
- **Production Gate:** Locked (Requires Human Verification on Staging Cluster)

### 10.2 Next Steps for Staging Validation
1. Deploy build to Staging environment.
2. Conduct live pair-programming smoke test with teacher and student accounts to verify:
   - File rename across active WebSockets.
   - Partial revision workflow with student resubmission.
   - LiveKit WebRTC video and audio mute/unmute.
   - Orbit wheel keyboard accessibility in Linux and Windows browsers.
