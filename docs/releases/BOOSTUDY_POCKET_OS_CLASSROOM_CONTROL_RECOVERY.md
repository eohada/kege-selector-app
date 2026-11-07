# BOOSTUDY POCKET OS — SPRINT 1.2.2
## Classroom Control, Shared Python Runtime & Mobile Focus Stabilization
### Recovery & Verification Report

**Status:** `READY FOR PHYSICAL OWNER RETEST`  
**Priority:** P0 — Physical Owner Acceptance Recovery  
**Environment:** Local Development Only (`http://127.0.0.1:5000` / `https://192.168.1.3:5443`)  
**Production:** STRICTLY NO DEPLOY  

---

## 1. Executive Summary

Following physical device acceptance testing by the project owner on a smartphone, 5 critical functional blockers were identified in Pocket OS:
1. **Missing / clipped Run button** for mobile student Python code execution.
2. **Empty student terminal** when teacher executes Python code (no shared execution broadcast).
3. **Teacher blindness to student terminal state** (teacher viewport badge did not report open/closed console).
4. **Lack of forced focus control** (teacher could not forcibly align student's screen between Board, Code, and Task).
5. **Window layout mutability** (accidental swiping on mobile dragged or resized windows).

All 5 blockers have been diagnosed, corrected, and verified across both backend Python socket contracts and frontend browser execution, backed by a 5/5 passing end-to-end Playwright test suite (`tests/e2e/test_pocket_os_classroom_control.spec.ts`) and 12/12 passing contract tests (`tests/v2/test_pocket_os_contract.py`).

---

## 2. Root Cause Analysis & Architectural Fixes

### Blocker 1: Missing / Clipped Mobile Student Python Run Button
* **Root Cause:**
  The desktop code header contained too many horizontal elements (`.pocket-code-filename`, file tags, save indicators). On narrow mobile viewports (<=390px, down to 360px Galaxy S / iPhone SE), the filename container expanded to 229px, pushing the Run button past the viewport boundary to 361px (overflow off screen).
* **Fix:**
  - In `static/css/boostudy-pocket-os.css`: `.pocket-code-header` was updated with `box-sizing: border-box; width: 100% !important; overflow: hidden;`.
  - Added responsive rules for `@media (max-width: 390px)`: `.pocket-code-filename` is constrained with `max-width: calc(100% - 130px) !important; flex: 1 1 0%; min-width: 0;`, while secondary labels (`.pocket-code-save-status`, `.pocket-btn-label`) are hidden.
  - `#pocket-btn-run` is styled with `min-width: 44px; min-height: 38px; flex-shrink: 0; display: inline-flex;` satisfying mobile accessibility requirements.
  - On a 360px screen, the right edge of `#pocket-btn-run` sits safely at 351px (a 9px margin from the viewport edge).
  - In `static/js/boostudy-pocket-os.js`: `mountCodeEnhancements()` renders `#pocket-btn-run` and hooks click events directly into `executeRunCode()`. If `freeze_student` is enabled by teacher, the button is gracefully disabled.

### Blocker 2: Empty Student Terminal on Teacher Python Run (Shared Runtime)
* **Root Cause:**
  Python execution was previously isolated to the initiating client's local DOM. When the teacher executed Python code, the student's mobile terminal drawer never received output data or auto-opened.
* **Fix:**
  - In `templates/sandbox/trainer.html`: `executeRunCode()` enriches and broadcasts `run_start` and `terminal_output` over WebSockets (`window.boostudyLessonControl?.sendUi(...)`) with metadata: `output`, `duration`, `exit_code`, `initiator_name`, `file_name`, `page_id`, and `run_id`.
  - In `static/js/boostudy-pocket-os.js`:
    - `handleTerminalRunStart()` renders execution progress in `#pocket-terminal-body` (`Преподаватель выполняет main.py...`).
    - `handleTerminalOutput()` renders execution results (code: 0, execution duration, output text) in `#pocket-terminal-body`.
    - **Code Focus Rule:** If student is currently in Code Focus, the terminal drawer auto-opens (`this.toggleTerminalDrawer(true)`).
    - **Board / Task Focus Rule:** If student is on Board or Task Focus, a non-intrusive floating toast (`#pocket-toast`) is displayed with action button `[В консоль]`. Tapping the button switches to Code Focus and reveals the drawer with zero disruption.

### Blocker 3: Teacher Cannot See if Student Opened Mobile Terminal
* **Root Cause:**
  Student mobile viewport reporting only sent `{ focus: 'board' | 'code' | 'task' }`. There was no `terminal_open` boolean in the payload, and `lesson_socket.py`'s `_on_whiteboard_viewport` did not accept or broadcast `terminal_open`.
* **Fix:**
  - In `app/lessons/lesson_socket.py`: `_on_whiteboard_viewport` now validates and broadcasts `"terminal_open": bool(payload.get("terminal_open", False))`.
  - In `static/js/boostudy-pocket-os.js`: `reportMobileViewport()` computes `terminal_open: Boolean(this.isTerminalDrawerOpen || (drawer && !drawer.classList.contains('is-collapsed')))` and emits it on drawer toggling.
  - In `templates/sandbox/trainer.html`: `renderStudentViewportIndicators()` parses `data.terminal_open` and updates the teacher viewport badge:
    - Code with drawer open: `Код · Консоль открыта` (emerald styling).
    - Code with drawer closed: `Код · Консоль закрыта` (slate/amber styling).
    - Board focus: `На доске` (sky badge).
    - Task focus: `В задании` (indigo badge).

### Blocker 4: Teacher Classroom Control & Forced Focus Switching
* **Root Cause:**
  Teacher only had soft focus suggestions (`focus_suggestion`), requiring student manual acceptance. Server socket handlers did not authorize `set_focus` as a teacher master kind.
* **Fix:**
  - In `app/lessons/whiteboard_service.py`: Added `"teacher_controls_focus": False` to `default_control()` for server-side persistence.
  - In `app/lessons/lesson_socket.py`: Added `"set_focus"` to `teacher_master_kinds` (strictly teacher-authorized; rejected if sent by student).
  - In `templates/sandbox/trainer.html`:
    - Added `#control-teacher-controls-focus` checkbox ("Управлять экраном ученика") in the teacher classroom control popover.
    - Updated `sendFocusSuggestion(targetFocus)`: If `teacher_controls_focus` is true, emits `set_focus`; otherwise emits `focus_suggestion`.
  - In `static/js/boostudy-pocket-os.js`:
    - `bindSocketEvents()` handles `set_focus` via `this.handleSetFocus(targetFocus)`.
    - Switches student focus immediately to `board`, `code`, or `task`.
    - Displays `#pocket-teacher-focus-pill` floating banner (`Фокус: <Режим> (управляет преподаватель)`).
    - **Data Safety:** Student draft code in `#code-editor-textarea` and task input answers are 100% preserved across focus transitions.

### Blocker 5: Mobile Window Layout Mutability (Resizing & Dragging)
* **Root Cause:**
  Desktop window manager drag handles (`.window-header`, `[data-drag-handle]`) and resizers (`.window-edge-resizer`, `.window-resize-handle`) remained active on touch devices, allowing swipes to unintentionally displace windows.
* **Fix:**
  - In `static/css/boostudy-pocket-os.css`: Added Section 13 with `display: none !important; pointer-events: none !important;` for all `.window-edge-resizer`, `.window-resize-handle`, `[class*="resizer-"]`, `.window-header-drag`, and `[data-drag-handle]` when `body.pocket-os-active`.
  - In `templates/sandbox/trainer.html`: Window dragging and resizing event listeners are explicitly guarded with:
    `if (document.body.classList.contains('pocket-os-active') || window.BooStudyPocketOS?.active) return;`.

---

## 3. Code Modifications Summary

| Component | File | Key Modifications |
| :--- | :--- | :--- |
| **Backend State** | `app/lessons/whiteboard_service.py` | Added `"teacher_controls_focus": False` to room default control state dictionary. |
| **Backend Sockets** | `app/lessons/lesson_socket.py` | Added `"set_focus"` to `teacher_master_kinds`. Extracted and broadcast `"terminal_open"` in `_on_whiteboard_viewport`. |
| **Teacher UI & Sockets** | `templates/sandbox/trainer.html` | Added `#control-teacher-controls-focus` toggle in classroom controls drawer. Enriched `executeRunCode()` with `run_start` and `terminal_output` broadcast metadata. Updated `renderStudentViewportIndicators()` for terminal badge. Dispatched local window events. Guarded window dragging/resizing on mobile. |
| **Pocket OS Styles** | `static/css/boostudy-pocket-os.css` | Styled `#pocket-btn-run` (min 44x38px). Responsive code header down to 360px without overflow. Section 13 strict suppression of resizers and drag handles. Styled `#pocket-teacher-focus-pill`. |
| **Pocket OS Logic** | `static/js/boostudy-pocket-os.js` | Added `handleSetFocus()`, `handleTerminalRunStart()`, `handleTerminalOutput()`. Auto-open terminal drawer in Code Focus; non-intrusive `#pocket-toast` in Board/Task Focus. Reported `terminal_open` in `reportMobileViewport()`. Guarded freeze state on run button. |

---

## 4. Automated Test Verification Results

### A. Contract Tests (`tests/v2/test_pocket_os_contract.py`)
```bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_pocket_os_contract.py -v
```
**Result:** **12/12 PASSED (100%)**

### B. Playwright End-to-End Suite (`tests/e2e/test_pocket_os_classroom_control.spec.ts`)
```bash
BOOSTUDY_E2E_SKIP_SERVER=1 NO_PROXY='*' no_proxy='*' ALL_PROXY='' all_proxy='' npx playwright test tests/e2e/test_pocket_os_classroom_control.spec.ts --project=desktop-chromium
```
**Result:** **5/5 PASSED (100%)** in 1.4 minutes

| Test ID | Scenario Description | Result | Duration |
| :--- | :--- | :---: | :---: |
| **CLASSROOM-01..04** | Student Run button visible, >=44x38px, accessible on 360px viewport, triggers execution, displays output and exit code 0 | **PASS** | 7.3s |
| **CLASSROOM-08..11** | Student terminal open/closed and focus states reflect dynamically in teacher viewport badge (`Код · Консоль открыта`, `Код · Консоль закрыта`, `В задании`, `На доске`) | **PASS** | 20.0s |
| **CLASSROOM-05..07** | Teacher executes Python code; student terminal receives shared output and notification (auto-opens drawer in Code, non-intrusive toast on Board) | **PASS** | 15.2s |
| **CLASSROOM-12..14** | Teacher enables classroom control and forcibly switches student focus (`set_focus`) without student prompt or draft data loss | **PASS** | 31.5s |
| **CLASSROOM-15** | Mobile windows cannot be dragged or resized, preserving immutable pocket focus layout | **PASS** | 11.6s |

---

## 5. Physical Owner Verification Checklist (Smartphone Retest)

### Prerequisites:
- Server running locally on development machine: `http://127.0.0.1:5000`.
- HTTPS Proxy running: `https://192.168.1.3:5443`.
- Teacher desktop browser: Open `http://127.0.0.1:5000/lesson/2168/room` logged in as `qa_pool_tutor_1`.
- Student smartphone browser: Open `https://192.168.1.3:5443/lesson/2168/room?pocket_os=1` logged in as `qa_pool_student_1`.

### Step-by-Step Test Procedure:

1. **Python Run Button Accessibility on Smartphone (Blocker 1)**
   - [ ] On smartphone, tap bottom navigation item **Код**.
   - [ ] Verify the green **Запуск** button (`#pocket-btn-run`) is fully visible in the top header.
   - [ ] Verify the button does not get clipped, does not cause horizontal scroll, and is comfortable to tap with a finger (>= 44x38 px).
   - [ ] Tap **Запуск**. Verify terminal drawer opens and displays execution output with exit code 0 (`Код: 0`).

2. **Teacher Viewport Indicator for Terminal State (Blocker 3)**
   - [ ] On smartphone in **Код**, swipe down or tap header to close the terminal drawer.
   - [ ] On teacher screen, check student viewport tag: verify it says `Код · Консоль закрыта`.
   - [ ] On smartphone, tap to open the terminal drawer.
   - [ ] On teacher screen, verify badge updates to `Код · Консоль открыта` (green highlight).
   - [ ] On smartphone, tap **Доска** or **Задание**. Verify teacher screen updates to `На доске` or `В задании`.

3. **Shared Python Runtime Broadcast (Blocker 2)**
   - [ ] On smartphone, stay in **Код**.
   - [ ] On teacher desktop, click **Запустить** in the code editor.
   - [ ] On smartphone, verify terminal drawer opens automatically and displays the teacher's program output.
   - [ ] On smartphone, switch to **Доска**.
   - [ ] On teacher desktop, click **Запустить** again.
   - [ ] On smartphone, verify you remain on the Board without unexpected jumping; an unobtrusive toast notification appears at the top (`Результат запуска: main.py`).
   - [ ] Tap **[В консоль]** in the toast. Verify student switches to Code and opens the terminal with the teacher's output.

4. **Teacher Classroom Control & Forced Focus (Blocker 4)**
   - [ ] On teacher desktop, click **Управление** in the top bar to open classroom controls.
   - [ ] Check the box **«Управлять экраном ученика»** (`#control-teacher-controls-focus`).
   - [ ] On smartphone, enter draft text into the code editor.
   - [ ] On teacher desktop, click **Фокус** > **Задание**.
   - [ ] On smartphone, verify the screen instantly switches to **Задание** with floating banner `Фокус: Задание (управляет преподаватель)`.
   - [ ] On teacher desktop, click **Фокус** > **Код**.
   - [ ] On smartphone, verify the screen instantly returns to **Код**, and your draft code is intact.

5. **Window Immutability (Blocker 5)**
   - [ ] On smartphone, attempt to drag the window header or grab edges to resize the code or task window.
   - [ ] Verify windows are strictly fixed and immutable; no accidental displacements occur.
