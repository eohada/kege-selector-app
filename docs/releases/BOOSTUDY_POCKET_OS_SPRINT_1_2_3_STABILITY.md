# BOOSTUDY POCKET OS — SPRINT 1.2.3 RELEASE REPORT
## Final Interaction Stabilization: Focus Reliability, Mobile Geometry, Keyboard UX & Shared Terminal Lifecycle

**Status:** `READY FOR PHYSICAL OWNER RETEST`  
**Environment:** Local Development Only  
**Production:** STRICTLY NO DEPLOY  
**Target Lesson:** `/lesson/2168/room`  
**Test Users:** `qa_pool_tutor_1` (Teacher) / `qa_pool_student_1` (Student), password `123456`  
**HTTPS Endpoint:** `https://192.168.1.3:5443/lesson/2168/room?pocket_os=1`  

---

## 1. Executive Summary

Following physical owner testing in Sprint 1.2.2, five critical physical interaction blockers were identified on real smartphone hardware. Sprint 1.2.3 delivers permanent architectural resolutions for all five defects with zero desktop regression, verified by an end-to-end Playwright test suite (`STABILITY-01` through `STABILITY-14`) and Python contract tests.

### Confirmed Fixes Matrix
| Defect | Severity | Area | Root Cause | Resolution | Automated Test |
|---|---|---|---|---|---|
| **1. Focus Suggestions Delivery Reliability** | P0 Blocker | Sockets / State | Student ACK blocked by socket permissions; no retry/dedup queue; TTL missing | Added `focus_suggestion_ack` to student permissions, ACK retry queue (1500ms bounded), TTL expiry (30s), command deduplication | `STABILITY-01..02` (PASS) |
| **2. Mobile Window Half-Screen Collapse** | P0 Blocker | Geometry / Layout | Desktop window layout sync stamped inline coordinates with `!important` on mobile | Strict `pocket-os-active` layout isolation guards + `stripInlineCoordinates` on focus switch | `STABILITY-03..04` (PASS) |
| **3. Unwanted Zoom on Python Typing** | P1 Blocker | Mobile UX | Editor `<textarea>` font size 13px triggered mobile browser auto-zoom | Upgraded mobile editor and syntax highlight to `16px` / `24px` line-height; synchronized gutter lines | `STABILITY-05` (PASS) |
| **4. Virtual Python Symbols Opening Closed Keyboard** | P1 Blocker | Mobile UX | Button click triggered unconditional `.focus()` & duplicate click events | Tracked `lastSelection`; only retains focus if keyboard was already open; deduplicated pointerdown/click | `STABILITY-06..08` (PASS) |
| **5. Shared Terminal Lifecycle Management** | P1 Blocker | Terminal Lifecycle | Teacher close didn't broadcast `terminal_close`; presence tag didn't update | Teacher minimize/close broadcasts `terminal_close`; student drawer collapses preserving stdout; presence reflects state | `STABILITY-09..12` (PASS) |

---

## 2. Root Cause Analysis & Architectural Resolutions

### 2.1 Defect 1 (P0): Focus Suggestions Delivery Reliability
- **Problem:** Teacher suggestions appeared intermittently; spamming caused UI desynchronization; student responses were lost.
- **Root Cause:**
  1. In `app/lessons/lesson_socket.py`, `_on_lesson_room_ui` rejected student-emitted `focus_suggestion_ack` because the student permission gate only allowed window/tracer actions, raising `"Недостаточно прав для управления интерфейсом комнаты"`.
  2. Teacher lacked a reliable retry mechanism; if a packet was dropped or race condition occurred, the suggestion was lost.
  3. No deduplication or TTL check existed on the client, causing delayed packets to trigger obsolete prompts.
- **Resolution:**
  - Added `is_ack_action = kind in {"focus_suggestion_ack"}` to `_on_lesson_room_ui` in [lesson_socket.py](file:///mnt/Main/projects/kege_selector_app_current/app/lessons/lesson_socket.py).
  - Implemented teacher retry queue in [trainer.html](file:///mnt/Main/projects/kege_selector_app_current/templates/sandbox/trainer.html): sends `command_id` + `created_at`, schedules up to 2 retries at 1500ms intervals, and clears the timer immediately upon receiving `focus_suggestion_ack`.
  - Added deduplication cache (`_processedCommandIds`) and 30-second TTL guard in [boostudy-pocket-os.js](file:///mnt/Main/projects/kege_selector_app_current/static/js/boostudy-pocket-os.js).
  - Maintained strict distinction between **Suggest Mode** (toast dialog with Accept/Dismiss) and **Controlled Mode** (`teacher_controls_focus = true`, instant switch with pill badge).

### 2.2 Defect 2 (P0): Mobile Window Half-Screen Collapse
- **Problem:** When switching between Board, Code, and Task, windows randomly occupied 50% width or shrunk into partial tiles.
- **Root Cause:**
  - The desktop WindowManager (`savePageWindows`, `restoreWindowLayout`, `applyRoomUi`) broadcasted desktop coordinate changes (`left`, `top`, `width: 50%`) which were applied as inline styles with `!important` to window DOM nodes shared between desktop and mobile modes.
- **Resolution:**
  - Added strict mobile isolation guards in `savePageWindows` and `restoreWindowLayout` in [trainer.html](file:///mnt/Main/projects/kege_selector_app_current/templates/sandbox/trainer.html):
    `if (document.body.classList.contains('pocket-os-active') || window.BooStudyPocketOS?.active) return;`
  - Created `stripInlineCoordinates(el)` in [boostudy-pocket-os.js](file:///mnt/Main/projects/kege_selector_app_current/static/js/boostudy-pocket-os.js) that strips `left`, `top`, `width`, `height`, `transform`, `margin`, `position` whenever a window is mounted or focused.
  - Reinforced 100vw/100vh CSS rules in [boostudy-pocket-os.css](file:///mnt/Main/projects/kege_selector_app_current/static/css/boostudy-pocket-os.css) under `.pocket-os-active`.

### 2.3 Defect 3 (P1): Unwanted Zoom on Python Typing
- **Problem:** Tapping into the Python editor caused iOS Safari and Android Chrome to zoom in the viewport automatically, breaking the interface layout.
- **Root Cause:**
  - Standard mobile browsers automatically zoom the page whenever an editable input or textarea has a `font-size` less than `16px`. The editor previously used `font-size: 13px` / `0.75rem`.
- **Resolution:**
  - Upgraded mobile editor typography in [boostudy-pocket-os.css](file:///mnt/Main/projects/kege_selector_app_current/static/css/boostudy-pocket-os.css):
    - `#code-editor-textarea`: `font-size: 16px !important; line-height: 24px !important;`
    - `#code-editor-highlight`: `font-size: 16px !important; line-height: 24px !important;`
  - Upgraded and synchronized line gutter metrics:
    - `#line-numbers-gutter`: `width: 38px !important; font-size: 13px !important; line-height: 24px !important;`
    - `.pocket-gutter-line`: `height: 24px !important; line-height: 24px !important;`
  - Fixed font size without disabling `user-scalable` meta tag, maintaining accessibility.

### 2.4 Defect 4 (P1): Virtual Python Symbols Opening Closed Keyboard
- **Problem:** Tapping virtual symbol keys (`:`, `=`, `(`, `)`) opened the system on-screen keyboard even when closed, obscuring the screen.
- **Root Cause:**
  - Virtual keys called `textarea.focus()` unconditionally upon insertion.
  - Listeners on both `pointerdown` and `click` caused duplicate insertion and unwanted focus-stealing events on mobile touch devices.
- **Resolution:**
  - In [boostudy-pocket-os.js](file:///mnt/Main/projects/kege_selector_app_current/static/js/boostudy-pocket-os.js), tracked cursor selection via `lastSelection` on `select`, `keyup`, `click`, `input`.
  - Conditioned `.focus()`: if the keyboard was closed (`document.activeElement !== textarea`), character is inserted at `lastSelection` without calling `textarea.focus()`, keeping the keyboard closed. If the keyboard was already active, focus and typing flow are preserved.
  - Deduplicated `pointerdown` and `click` events with timestamp debouncing (<500ms).
  - Dispatched `input` event and invoked `onCodeEditorInput` to keep Operational Transformation (OT) synchronizing in real time.

### 2.5 Defect 5 (P1): Shared Terminal Lifecycle Management
- **Problem:** When the teacher closed their desktop terminal window, the student's mobile drawer remained open.
- **Root Cause:**
  - Desktop terminal close only toggled the local desktop window without broadcasting a lifecycle close action across the room.
- **Resolution:**
  - Added `"terminal_close"` to `teacher_master_kinds` in [lesson_socket.py](file:///mnt/Main/projects/kege_selector_app_current/app/lessons/lesson_socket.py).
  - In [trainer.html](file:///mnt/Main/projects/kege_selector_app_current/templates/sandbox/trainer.html), closing or minimizing `terminal-window` by the teacher emits `terminal_close` and dispatches `boostudy:terminal-close`.
  - In [boostudy-pocket-os.js](file:///mnt/Main/projects/kege_selector_app_current/static/js/boostudy-pocket-os.js), receiving `terminal_close` collapses the student drawer (`is-collapsed`) while preserving the console buffer and output history.
  - Local student drawer close (tapping header or close button) remains strictly private and does not close the teacher's terminal.
  - Updated mobile presence tracking to broadcast `terminal_open: true/false`, rendering `Код · Консоль открыта` vs `Код · Консоль закрыта` on the teacher's viewport tag.

---

## 3. Automated Test Verification Results

### Suite: `tests/e2e/test_pocket_os_sprint1_2_3_stability.spec.ts`
All 5 test suites containing 14 verification checks passed:

| Test ID | Scope | Verification Description | Result | Duration |
|---|---|---|---|---|
| **STABILITY-01** | Focus Suggestion | 20 sequential focus suggestions deliver reliably with ACK; toast displays correct icons and targets | **PASS** | 41.5s (suite) |
| **STABILITY-02** | Focus Control | Controlled Mode (`teacher_controls_focus = true`) immediately switches focus with pill indicator | **PASS** | included |
| **STABILITY-03** | Mobile Geometry | 100 consecutive rapid focus switches (Board ↔ Code ↔ Task) maintain full 100vw/100vh without collapse | **PASS** | 20.6s (suite) |
| **STABILITY-04** | Orientation Safety | Switching device orientation (Portrait ↔ Landscape ↔ Portrait) preserves clean geometry | **PASS** | included |
| **STABILITY-05** | Editor Typography | `#code-editor-textarea` and highlight font-size is strictly `16px` and line-height is `24px` (preventing zoom) | **PASS** | 23.5s (suite) |
| **STABILITY-06** | Virtual Symbols | Tapping virtual symbol keys with keyboard closed inserts characters without summoning keyboard | **PASS** | included |
| **STABILITY-07** | Virtual Symbols | Tapping virtual symbol keys with keyboard open retains focus and seamless typing flow | **PASS** | included |
| **STABILITY-08** | OT Sync | Virtual symbol key insertions synchronize instantly to teacher editor via OT | **PASS** | included |
| **STABILITY-09** | Terminal Lifecycle | Teacher closing desktop terminal automatically collapses student mobile console drawer | **PASS** | 14.6s (suite) |
| **STABILITY-10** | Terminal Lifecycle | Student closing local console drawer does NOT close teacher terminal | **PASS** | included |
| **STABILITY-11** | Presence Sync | Teacher viewport presence tag updates accurately (`Код · Консоль открыта` / `Консоль закрыта`) | **PASS** | included |
| **STABILITY-12** | Output Persistence | Collapsing and re-opening drawer preserves stdout text and exit code | **PASS** | included |
| **STABILITY-13** | Regression Guard | Board tools, gestures, zoom controls, and task presentation remain completely intact | **PASS** | 12.2s (suite) |
| **STABILITY-14** | Regression Guard | Desktop Lesson OS window manager, dock, and controls operate with zero regression | **PASS** | included |

### Regression Suites:
- `tests/v2/test_pocket_os_contract.py`: **12 / 12 PASS** (1.81s)
- `tests/e2e/test_pocket_os_classroom_control.spec.ts`: **5 / 5 PASS** (55.7s)

---

## 4. Physical Retest Instructions for Owner (Smartphone)

### Prerequisites:
1. Connect smartphone to same Wi-Fi network.
2. Open Chrome/Safari and navigate to:
   `https://192.168.1.3:5443/lesson/2168/room?pocket_os=1`
3. Log in as student:
   - Login: `qa_pool_student_1`
   - Password: `123456`
4. On desktop PC, open `http://127.0.0.1:5000/lesson/2168/room` and log in as teacher:
   - Login: `qa_pool_tutor_1`
   - Password: `123456`

### Step-by-Step Retest Checklist:

#### Test 1: Focus Suggestions & Controlled Mode
1. Ensure student is on the **Доска** tab.
2. In teacher desktop header, click `Фокус ▼` and select `Предложить фокус: Код`.
   - **Expected:** Student sees toast card `"Учитель предлагает открыть редактор кода"`.
3. Student taps `"В код"`.
   - **Expected:** Student instantly switches to Code tab; toast disappears.
4. On teacher desktop, open `Управление` and enable `Принудительный фокус преподавателя`.
5. In teacher header, select `Фокус: Задание`.
   - **Expected:** Student screen switches immediately to Task tab without dialog; pill `"Фокус: Задание (управляет преподаватель)"` briefly appears.

#### Test 2: Full Width Geometry Stability
1. On smartphone, tap `Доска`, `Код`, `Задание` rapidly 10 times in a row.
2. Rotate smartphone to Landscape, then back to Portrait.
   - **Expected:** Windows NEVER collapse to 50% width or shift into partial tiles. Every surface occupies 100% screen width.

#### Test 3: No Unwanted Zoom on Python Typing
1. Switch student to `Код`.
2. Tap inside the code editor textarea.
   - **Expected:** The on-screen keyboard opens naturally. The mobile browser **does NOT zoom in** or shift the page viewport (font is crisp 16px).
   - **Expected:** Text line height matches gutter numbers line for line without vertical drift.

#### Test 4: Virtual Python Symbols Without Opening Keyboard
1. With keyboard open, tap outside the editor (e.g. on header or navigation bar) to close the on-screen keyboard.
2. Tap the virtual symbols `: `, `=`, `(`, `)` on the toolbar.
   - **Expected:** The symbols are inserted into the code editor.
   - **Expected:** The on-screen keyboard **remains closed** and does NOT pop up.
3. Tap into the editor to open keyboard; tap `:` on the virtual toolbar.
   - **Expected:** `:` is inserted and keyboard **remains open**, allowing continuous typing.
4. Check teacher desktop editor.
   - **Expected:** All inserted symbols appear synchronously on teacher's screen.

#### Test 5: Shared Terminal Close Lifecycle
1. On student, switch to `Код`.
2. On teacher desktop, click `Запустить` (or press `Ctrl+Enter`).
   - **Expected:** Student terminal drawer auto-opens and prints execution output.
   - **Expected:** Teacher student status tag shows `"Код · Консоль открыта"`.
3. On teacher desktop, click the close button `✕` on the desktop terminal window.
   - **Expected:** Student mobile console drawer automatically collapses down.
   - **Expected:** Teacher student status tag updates to `"Код · Консоль закрыта"`.
4. On student mobile, tap the console header `"Консоль"`.
   - **Expected:** Drawer opens locally showing preserved stdout history.
   - **Expected:** Teacher desktop terminal does NOT open or close unexpectedly.

---

## 5. Artifact Links
- Test Suite: [test_pocket_os_sprint1_2_3_stability.spec.ts](file:///mnt/Main/projects/kege_selector_app_current/tests/e2e/test_pocket_os_sprint1_2_3_stability.spec.ts)
- Contract Suite: [test_pocket_os_contract.py](file:///mnt/Main/projects/kege_selector_app_current/tests/v2/test_pocket_os_contract.py)
- Mobile Engine: [boostudy-pocket-os.js](file:///mnt/Main/projects/kege_selector_app_current/static/js/boostudy-pocket-os.js)
- Mobile Styles: [boostudy-pocket-os.css](file:///mnt/Main/projects/kege_selector_app_current/static/css/boostudy-pocket-os.css)
- Room Template: [trainer.html](file:///mnt/Main/projects/kege_selector_app_current/templates/sandbox/trainer.html)
- Socket Backend: [lesson_socket.py](file:///mnt/Main/projects/kege_selector_app_current/app/lessons/lesson_socket.py)
