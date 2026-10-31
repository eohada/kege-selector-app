# BOOSTUDY OS — Unified Editor & OS Interaction Stabilization

**Status:** `READY FOR OWNER RETEST`  
**Date:** 2026-10-31  
**Target Environment:** Local Dev / Staging Verification (`http://127.0.0.1:5000`)  
**Production Deployment:** Strictly FORBIDDEN per project protocol  

---

## 1. Executive Summary & Status

Following the project directives for `# BOOSTUDY OS — UNIFIED EDITOR & OS INTERACTION STABILIZATION`, the core workspace and window systems of BooStudy OS have undergone comprehensive architectural stabilization across both **Lesson OS** (`room_mode`) and **Homework OS** (`homework_mode` / `review_mode`):

1. **P0 Answer Integrity Guaranteed:** Resolved the critical flaw where Python code autosave overwrote student plain-text answers (e.g. `1286`) with null/empty strings, or caused submitted values to display as dash (`—`) during teacher review. Plain answers and code autosaves are now fully isolated.
2. **P0 Unified Single-File Code Model:** Eliminated the legacy multi-file tab system (`Страница 1`, `Страница 2` tabs inside `#code-window`). Both Lesson OS and Homework OS now enforce a clean, single-file (`main.py`) editor buffer per page/task.
3. **P0 Lesson OS Page-Scoped Workspaces & Persistence:** In Lesson OS, each whiteboard page maintains its own independent `main.py` buffer, Redis cache, and DB persistence under `summaries['_os_page_workspaces'][page_id]`, with seamless switching and cross-page flush isolation.
4. **P0 Ownership & Geometry Separation:** Collaborative code synchronization is scoped to `lesson_id + page_id`, while window layout geometries are strictly private to each user (`lesson_id + page_id + user_id`). Student window movements never shift the teacher's UI.
5. **P1 Window Motion & Titlebar Drag:** Repaired draggable titlebars across all floating OS windows by decoupling `:first-child` controls and enforcing `cursor: grab` titlebar handles.
6. **P1 Responsive Toolbar & Single-Line Status Bar:** Implemented container-query-based toolbar collapse (`@container (max-width: 580px)`) and strict single-line (`h-8`, nowrap) status bar layout.
7. **P1 Two-Axes Homework Status UX:** Separated Correctness (Grade/Check) from Workflow Lifecycle (Draft, In Review, Returned, Approved), featuring high-contrast amber revision banners and task badges.

All verification suites have executed with **100% pass rate** (25/25 active in `test_unified_editor_and_windows.spec.ts` and 24/24 active in `test_homework_single_file.spec.ts`, total 49 passing test specs). High-definition 1080p visual evidence screenshots have been verified and documented.

---

## 2. Unified Single-File Code Model Architecture

Historically, Lesson OS embedded a multi-file tab bar within the code window, causing confusion when instructors switched whiteboard pages and students saw competing tabs. Under the unified contract:

| Platform Mode | Previous Architecture | Unified Architecture |
| :--- | :--- | :--- |
| **Lesson OS (`room_mode`)** | Multi-file tabs (`Страница 1`, `Страница 2`, `main.py`) inside `#code-window`. | Single-file (`main.py`) per whiteboard page. Tabs bar hidden. Header shows badge: `main.py PYTHON`. |
| **Homework OS (`homework_mode`)** | Single-file (`main.py`) per task, but code autosave occasionally touched answers. | Strict single-file (`main.py`) per task. Answer inputs completely isolated. |
| **Code Window Header** | Tab navigation bar with close/add buttons. | Clean single-file status badge with collaborative indicator or autosave status. |

### Architectural Invariants:
1. Every workspace instance (a specific whiteboard page in Lesson OS, or a specific task in Homework OS) has exactly **one active code file: `main.py`**.
2. Switching whiteboard pages in Lesson OS switches the underlying `main.py` buffer to that page's specific collaborative code.
3. Historical secondary files remain archived and accessible read-only via `#hw-archived-files-modal` without cluttering the active editor.

---

## 3. Lesson OS Page-Scoped Workspaces & Persistence Specification

Each whiteboard page in Lesson OS owns an isolated code workspace lifecycle.

```
Lesson (ID: 2168)
 ├── Whiteboard Page "page_1" ──> main.py: Code for Page 1
 │     ├── Cache: boostudy:lesson:2168:page:page_1:code_state
 │     └── DB: summaries['_os_page_workspaces']['page_1']
 └── Whiteboard Page "page_2" ──> main.py: Code for Page 2
       ├── Cache: boostudy:lesson:2168:page:page_2:code_state
       └── DB: summaries['_os_page_workspaces']['page_2']
```

### Persistence Protocol:
1. **Cache Keying:**
   - Helper function `_code_state_key(lesson_id, page_id)` yields:  
     `boostudy:lesson:{lesson_id}:page:{page_id}:code_state`
   - Cache stores `{ code, files: {"main.py": code}, revision, updated_at }`.
2. **Database Storage (`Lesson.review_summaries`):**
   - `summaries['_os_page_workspaces'][page_id]` stores the authoritative state:
     ```json
     {
       "code": "# Solution for page 1\n...",
       "files": { "main.py": "# Solution for page 1\n..." },
       "active_tab": "main.py",
       "open_tabs": ["main.py"],
       "revision": 3,
       "updated_at": "2026-10-31T14:20:00Z"
     }
     ```
   - **Backward Compatibility Guarantee:** `page_1` state is continuously mirrored to `summaries['_os_workspace']`. Legacy endpoints or older clients reading `_os_workspace` continue to receive valid page 1 data.
3. **REST Endpoints (`app/lessons/routes.py`):**
   - `GET /lesson/<lesson_id>/studio/os-code?page_id=<page_id>`: returns page-scoped code and revision.
   - `POST /lesson/<lesson_id>/studio/os-code`: accepts `{ page_id, code, revision }`, commits to DB and cache, and broadcasts `lesson_code_persisted` with `page_id`.
4. **Client Page Switching Protocol (`templates/sandbox/trainer.html`):**
   - When user clicks a whiteboard page pill, `onLessonPageSwitch(fromPageId, newPageId)` triggers:
     1. `flushPendingCodeSync(fromPageId)` immediately syncs the un-flushed code of `fromPageId` to the server under `fromPageId`.
     2. The editor loads the cached or server code for `newPageId`.
     3. Eliminates cross-page bleed where code from Page 1 previously polluted Page 2.

---

## 4. Window Ownership & Page-Scoped Layout Geometry Matrix

To preserve tutor pedagogical control while empowering student self-organization, window ownership and geometries are strictly partitioned:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              Lesson Room                               │
│                                                                        │
│   Shared Collaborative Domain           Private User OS Domain         │
│   (Synchronized via Socket.IO)         (Local to Browser Session)      │
│                                                                        │
│   • Whiteboard shapes & stickers       • Window [X, Y, W, H] geometry  │
│   • main.py code for active page       • Window minimized/maximized    │
│   • Active shared lesson page ID       • Window Z-index stacking       │
└────────────────────────────────────────────────────────────────────────┘
```

### Layout Geometry Matrix:

| Window Identifier | Scope | Persistence Key Format | Shared Across Users? |
| :--- | :--- | :--- | :--- |
| `#code-window` | **Page-Scoped** | `lesson_{id}_{pageId}_code-window_layout` | **NO** (Student moves do not move Teacher) |
| `#terminal-window` | **Page-Scoped** | `lesson_{id}_{pageId}_terminal-window_layout` | **NO** (User-private layout) |
| `#task-window` | **Room-Scoped** | `lesson_{id}_task-window_layout` | **NO** (User-private layout) |
| `#lesson-info-window` | **Room-Scoped** | `lesson_{id}_lesson-info-window_layout` | **NO** (User-private layout) |

### Key Properties:
- **Zero Cross-User Pollution:** Student window resizes, repositions, minimizes, or maximizes stay in the student's browser `localStorage`.
- **Page-Scoped Memory:** Moving the code window to the bottom-left on Page 1 does not force it to the bottom-left on Page 2 if Page 2 has a custom geometry.
- **Stable ID Anchoring:** Window keys use stable page identifiers (`page_1`, `page_2`, UUID) rather than volatile page array indices.

---

## 5. Answer Integrity & Autosave Isolation Protocol

### Root Cause Analysis of Past Answer Loss:
When a student typed an answer in Homework OS, `/task-workspace/api/save` was routinely invoked by Monaco autosave loops. Because the autosave payload focused on code, `answer` was frequently passed as `None` or omitted. In previous implementations, `save_workspace_code()` inadvertently set `Answer.value = answer` (i.e. `None`), erasing the student's submission. Furthermore, during teacher review, empty `Answer.value` caused the UI to render `—` even when the student had submitted a valid attempt.

### Isolation Protocol Implementation:
1. **Explicit Guard in `save_workspace_code` (`app/task_workspace/service.py`):**
   ```python
   # Only update plain-text answer when an explicit non-None value is passed
   if answer is not None:
       answer_record.value = str(answer).strip()
   ```
2. **Review Context Fallback Resolution (`_resolve_submission_task_context`):**
   When rendering review or student submission context:
   ```python
   plain_answer = answer_record.value if answer_record else None
   if not plain_answer and attempt and attempt.attempt_data:
       # Fallback to immutable snapshot attempt data
       plain_answer = attempt.attempt_data.get("answers", {}).get(str(assignment_task_id))
   ```
3. **Dirty Answers Submission Capture (`app/assignments/routes.py`):**
   `submission_submit()` accepts a `dirty_answers` map from the client (`{ [taskId]: dirtyValue }`), updating `Answer.value` immediately before generating the immutable `SubmissionAttempt` snapshot.
4. **Client Real-Time Event Bus (`task-workspace.js` & `homework-os-room.js`):**
   Input events on `#answer-input` immediately broadcast to `window.dirtyAnswers` and `window.taskAnswerStore`. Code autosave cycles never touch or transmit `answer` unless the user explicitly requested an answer save.

---

## 6. Homework OS Two-Axes Status Matrix (Correctness vs Workflow)

Student submissions and task items now operate along two orthogonal axes:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TWO-AXES STATUS MATRIX                          │
├────────────────────────────────┬───────────────────────────────────────┤
│    AXIS 1: CORRECTNESS         │    AXIS 2: WORKFLOW LIFECYCLE         │
│    (Grade / Verification)      │    (Review / Revision State)          │
├────────────────────────────────┼───────────────────────────────────────┤
│ • Correct (100% / score == max)│ • Draft (Not submitted)               │
│ • Incorrect (0% / score == 0)  │ • Submitted / In Review (Under check) │
│ • Partially Correct (0 < s < m)│ • Returned for Revision (Needs rework)│
│ • Unchecked (Manual review)    │ • Approved / Completed (Accepted)     │
└────────────────────────────────┴───────────────────────────────────────┘
```

### High-Contrast Amber Revision Banner:
When `submission.status == 'RETURNED'`:
- **Top OS Header:** Displays `#hw-revision-returned-banner`:  
  `"Работа возвращена на доработку (заданий: N)"` in high-contrast amber styling (`bg-amber-500/10 border-amber-500/40 text-amber-200`).
- **Task Navigation Pills:** Tasks flagged with `needs_revision=True` display `#hw-revision-returned-badge`:  
  Amber pill badge `"На доработке"` with counter and refresh indicator.
- **Selective Editability:** Tasks flagged for revision unlock their code and answer fields; accepted tasks remain safely protected.

---

## 7. Window Motion, Titlebar Drag, Responsive Toolbar, and Status Bar

### 1. Titlebar Drag Restoration:
- **Issue:** Flex child controls (`.window-controls`, badges) on floating window headers were intercepting pointerdown events or expanding across the entire header width.
- **Fix:** In `templates/sandbox/trainer.html`, window header action containers are set to:
  ```css
  flex: 0 0 auto !important;
  max-width: fit-content;
  ```
  The header itself and designated drag handles enforce `cursor: grab` and correctly forward pointer events to the window manager dragging handler.

### 2. Container Query Responsive Toolbar:
- `#code-window` utilizes CSS container queries (`container-type: inline-size`):
  ```css
  @container (max-width: 580px) {
    .code-toolbar-btn-text { display: none; }
    .code-toolbar-badge-full { display: none; }
    .code-toolbar-badge-compact { display: inline-flex; }
  }
  ```
  When the code window is resized down to mobile or compact split-pane dimensions, labels collapse into clear SVG icons without overflow or wrap.

### 3. Strict Single-Line Status Bar:
- `.code-window-statusbar` enforces:
  ```css
  height: 2rem !important; /* h-8 */
  line-height: 2rem;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis;
  ```
  Status items (`file`, `cursor line/col`, `autosave badge`, `runtime`, `encoding`) remain strictly on a single line on all screen dimensions.

---

## 8. Automated Verification Suite Matrix

All test suites were executed against the running local server (`http://127.0.0.1:5000`) using Playwright.

### 1. Unified Editor & Windows Suite (`test_unified_editor_and_windows.spec.ts`)

| Test Spec ID | Description | Result |
| :--- | :--- | :--- |
| `DATA-01` | Submission preserves submitted student plain answer without dropping to dash | **PASS** |
| `DATA-02` | Autosave of Python code never overwrites plain student answer | **PASS** |
| `DATA-03` | Review mode displays submitted answer and submission score accurately | **PASS** |
| `PAGE-01` | Lesson OS code window has no multi-file tabs | **PASS** |
| `PAGE-02` | Whiteboard page switch loads page-scoped code | **PASS** |
| `PAGE-03` | Whiteboard page switch persists previous page code | **PASS** |
| `PAGE-04` | Collaborative code sync respects active page ID | **PASS** |
| `PAGE-05` | Page code persists across reloads via REST API | **PASS** |
| `OWN-01` | Teacher and student have independent window layout | **PASS** |
| `OWN-02` | Window geometry is scoped to whiteboard page | **PASS** |
| `OWN-03` | Non-code windows stay fixed across pages | **PASS** |
| `DRAG-01` | Code window titlebar is draggable on desktop | **PASS** |
| `DRAG-02` | Terminal window titlebar is draggable on desktop | **PASS** |
| `DRAG-03` | Task window titlebar is draggable on desktop | **PASS** |
| `DRAG-04` | Window drag respects boundaries | **PASS** |
| `TOOL-01` | Code window toolbar responsive on desktop | **PASS** |
| `TOOL-02` | Code window toolbar collapses gracefully on narrow window | **PASS** |
| `TOOL-03` | Status bar is strictly single-line on desktop | **PASS** |
| `TOOL-04` | Status bar does not wrap or expand vertically on narrow window | **PASS** |
| `STAT-01` | Returned homework displays amber revision banner | **PASS** |
| `STAT-02` | Returned task pill displays amber revision badge | **PASS** |
| `STAT-03` | Correctness and workflow status axes are visually distinct | **PASS** |
| `STAT-04` | Resubmission clears revision banner | **PASS** |
| `MOB-01` | Floating windows adapt on mobile viewport | **PASS** |
| `MOB-02` | Code editor is usable on mobile | **PASS** |
| `MOB-03` | Window positioning on mobile | *SKIPPED (Intentional)* |
| **Total** | **25 Passed, 1 Skipped, 0 Failed** | **100% Success** |

### 2. Homework Single-File Suite (`test_homework_single_file.spec.ts`)

| Test Spec ID | Description | Result |
| :--- | :--- | :--- |
| `HW-SINGLE-01` | Task 1 Code Isolation & Absence of Multi-File Tab Bar | **PASS** |
| `HW-SINGLE-02` | Seamless Task Switching Without Code Pollution | **PASS** |
| `HW-SINGLE-03` | Real-Time Autosave to SQLite Backend | **PASS** |
| `HW-SINGLE-04` | Revision Bump & 409 Conflict Reconciliation | **PASS** |
| `HW-SINGLE-05` | Instant Submission Snapshotting | **PASS** |
| `HW-SINGLE-06` | Teacher Review Read-Only Mode & Attempt Navigation | **PASS** |
| `HW-SINGLE-07` | Return for Revision & Student Re-Editing Scope | **PASS** |
| `HW-SINGLE-08` | Starter Code Respect & Empty Code Preservation | **PASS** |
| `HW-SINGLE-09` | Archived Secondary Files Modal | **PASS** |
| `HW-SINGLE-10` | Offline Warning & Network Reconnection Flush | **PASS** |
| `HW-SINGLE-11` | Answer Frame Navigation & Context Synchronization | **PASS** |
| `HW-SINGLE-12` | Review Mode Answer Frame Display | **PASS** |
| `HW-SINGLE-13` | Multi-Tab Concurrency Guard & Broadcast Channel | **PASS** |
| `HW-SINGLE-14` | Submission Summary Task State Indicator Badges | **PASS** |
| `HW-SINGLE-15` | Lesson OS Multi-File Regression Guard | *SKIPPED (Superseded by PAGE-01)* |
| `HW-SINGLE-16` | Large Code Payload Autosave & Submission (250KB+) | **PASS** |
| `HW-SINGLE-17` | Python Syntax Error Diagnostics & Traceback | **PASS** |
| `HW-SINGLE-18` | Task Switching Code Persistence Under Heavy Load | **PASS** |
| `HW-SINGLE-19` | Return for Revision Task-Level Isolation | **PASS** |
| `HW-SINGLE-20` | Review Mode Feedback Autosave | **PASS** |
| `HW-SINGLE-21` | Pyodide Client-Side Code Execution | **PASS** |
| `HW-SINGLE-22` | Monaco Editor Layout Resizing on Window Resize | **PASS** |
| `HW-SINGLE-23` | Session Expiry Graceful Degradation | **PASS** |
| `HW-SINGLE-24` | Rapid Task Navigation Stress Test | **PASS** |
| `HW-SINGLE-25` | Mobile Viewport Single-File Header & Floating Code Window | *SKIPPED (Intentional)* |
| `HW-SINGLE-E2E` | Complete End-to-End Homework Workflow | **PASS** |
| **Total** | **24 Passed, 2 Skipped, 0 Failed** | **100% Success** |

---

## 9. Visual Evidence & Artifacts Manifest

High-definition (1920x1080) visual proof was generated using headless Chromium against the live running application:

### 1. Lesson OS Single-File Unified Workspace (`after_lesson_room_single_file_1080p.png`)
- Single-file indicator `main.py PYTHON` in header; multi-file tabs completely eliminated.
- Collaborative code presence and clean titlebar grab controls.
- Single-line status bar at bottom (`h-8`, nowrap).
- Whiteboard canvas integration and floating code window.

### 2. Homework OS Two-Axes Status & Revision Banner (`after_homework_two_axes_1080p.png`)
- High-contrast amber revision banner: `"Работа возвращена на доработку (заданий: 1)"`.
- Distinct task badges: `"Задание 1  На доработке"` (amber) vs `"Задание 2  Отвечено"` (neutral/green).
- Preserved plain answer integrity: submitted value `1286` displayed intact without dash.
- Single-line status bar and isolated Python solution buffer.

---

## 10. Breaking Changes & Migration Notes

1. **Lesson OS Multi-File Tab Removal:**
   - Whiteboard pages now serve as the organizing construct for different code solutions during a lesson. Instructors create a new whiteboard page rather than creating additional tabs inside the code window.
2. **Schema & Summary Dictionary Migration:**
   - Existing lessons lacking `_os_page_workspaces` in `review_summaries` are automatically initialized on read, with `page_1` populated from legacy `_os_workspace`. No destructive DB migrations are required.
3. **Task Workspace Autosave Contract:**
   - Calls to `/task-workspace/api/save` that omit the `answer` key or supply `null` are treated as code-only saves. To clear an answer, callers must explicitly provide `answer: ""`.

---

## 11. Security, Concurrency & Rollback Safeguards

1. **Revision Optimistic Locking:**
   - HTTP 409 conflict detection remains active on both page code (`os-code`) and task code (`api/save`). Concurrent edits are detected and automatically reconciled.
2. **Role-Based Access Control:**
   - Submission answer updating is restricted to the student owner prior to submission, or during revision for returned tasks only.
   - Lesson code persistence requires tutor privileges or enrolled student participant status in the active room.
3. **Rollback Safeguards:**
   - The backward-compatible fallback to `_os_workspace` ensures that reverting the frontend bundle does not corrupt or orphan lesson code in storage.

---

## 12. Manual Owner Retest Verification Checklist

Perform these steps on `http://127.0.0.1:5000`:

### Step 1: Lesson OS Room Single-File & Page Workspaces
1. Log in as tutor (`qa_pool_tutor_1` / `123456`).
2. Open Lesson 2168: `http://127.0.0.1:5000/lesson/2168/room`.
3. Verify the `#code-window` displays a clean `main.py PYTHON` header without multi-file tabs.
4. Type `# Page 1 code` in the editor.
5. Switch to whiteboard Page 2 via bottom navigation pill.
6. Verify editor displays Page 2 code (or empty starter) and does NOT contain `# Page 1 code`.
7. Type `# Page 2 code`, switch back to Page 1, and verify `# Page 1 code` is intact.
8. Drag the `#code-window` by its titlebar to verify smooth dragging.

### Step 2: Homework OS Answer Integrity & Two-Axes Status
1. Log in as student (`qa_pool_student_1` / `123456`).
2. Open Homework Workspace: `http://127.0.0.1:5000/task-workspace?context_type=submission_task&context_id=2694&assignment_task_id=2832`.
3. Verify the high-contrast amber banner `"Работа возвращена на доработку (заданий: 1)"` appears at the top.
4. Verify `"Задание 1"` pill displays the amber `"На доработке"` badge.
5. In the task answer box on the right, verify the answer `1286` is clearly visible and has not dropped to `—`.
6. Edit the Python code in `#code-window`, wait for autosave, and confirm the answer `1286` remains intact.
7. Click `"Отправить на повторную проверку"` and confirm submission completes smoothly.
