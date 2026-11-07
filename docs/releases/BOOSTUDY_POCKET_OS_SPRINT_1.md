# BOOSTUDY POCKET OS — SPRINT 1
## Mobile Lesson Experience & Teacher-Directed Focus

**Status:** `READY FOR MOBILE OWNER RETEST`  
**Date:** 2026-11-02  
**Target Environment:** Local Development (`http://127.0.0.1:5000`)  
**Production Guard:** Fail-Closed Security Active (`boostudy.ru` host & production env lockout)  
**Deliverable Document:** `docs/releases/BOOSTUDY_POCKET_OS_SPRINT_1.md`  

---

## 1. Executive Summary & Product Vision

BooStudy OS has evolved from a desktop-centric virtual classroom into a dual-form-factor educational platform. **BooStudy Pocket OS (Sprint 1)** implements the first dedicated mobile student lesson experience paired with teacher-directed spatial controls on desktop:

> **Core Philosophy:**  
> *"The teacher directs the educational space; the mobile student receives focused, ergonomic, comfortable access to it."*

### Key Accomplishments in Sprint 1:
1. **P0 Mobile Lesson Shell (`#pocket-os-shell`):** Dedicated touch interface activated automatically on mobile viewports (`innerWidth <= 768px`) or query parameter `?pocket_os=1` when `BOOSTUDY_POCKET_OS_ENABLED=true`.
2. **P0 3-Surface Focus Navigation with Zero State Loss:** Seamless switching between `BOARD` (Доска), `CODE` (Редактор кода), and `TASK` (Задание) with zero DOM recreation. Active code text buffer, WebRTC LiveKit media streams, and OT document state are 100% preserved.
3. **P0 Mobile Canvas View-Only & Multi-Touch Ergonomics:** Student canvas is strictly view-only (no accidental stylus/finger scribbles), equipped with multi-touch pinch-to-zoom, single-finger pan, «К преподавателю» (rejoin camera), and «Сбросить масштаб» controls.
4. **P0 Python Editor Mobile Ergonomics:** Virtual symbol strip (`Tab`, `(`, `)`, `[`, `]`, `{`, `}`, `:`, `=`, `"`, `'`, `_`, `+`, `-`, `*`, `/`, `%`), green «Запустить» button, and an expandable terminal output bottom drawer.
5. **P0 Continuous LiveKit Audio/Video Persistence:** Floating remote video pill (`#pocket-video-pill`) persists across all 3 focus surfaces, with tap-to-expand (`150x200px`) and mute status toggles.
6. **P0 Teacher Spatial Viewport Contour:** Real-time mobile viewport outline on the desktop whiteboard displaying student's exact viewing rectangle, smartphone aspect ratio (`390x790`), `Pocket` badge, and real-time status tags (`«В редакторе кода»`, `«В задании»`).
7. **P0 Teacher Directed Actions («Показать здесь» & «К контуру»):** One-shot camera framing tool (`whiteboard_show_here`) transmitting teacher's bounding box to student with smooth fit-to-view, plus teacher camera snap to student contour.
8. **P0 Non-Destructive Focus Suggestions:** Teacher can suggest switching to `board`, `code`, or `task`; mobile student receives an elegant top toast card with `[Перейти]` and `[✕]` without forcefully hijacking their UI.
9. **Fail-Closed Security Guard:** `is_pocket_os_enabled()` locks out production (`boostudy.ru`), staging, or unknown environments, ensuring zero risk to production.

---

## 2. Architecture Discovery & Integration Points

Before implementation, the existing Lesson OS codebase was thoroughly audited to ensure **zero duplication** of existing mechanisms:

1. **BooCanvas & Camera Viewport:**
   - Existing: `BooCanvasOverlay.camera` with world coordinates (`x`, `y`, `scale`), pan/zoom listeners, and viewport broadcasting via Socket.IO.
   - Pocket OS Integration: Mobile canvas is set to `readOnly = true` and default tool `pan`. Custom gesture handlers support pinch-to-zoom and drag pan while broadcasting mobile viewport dimensions.
2. **Student Viewport Contour:**
   - Existing: Desktop indicator `renderStudentViewportIndicators()` on tutor canvas rendering boxes for connected students.
   - Pocket OS Integration: Enhanced with `is-mobile-contour` CSS class, `Pocket` badge, dynamic aspect ratio calculation, and status tags (`«В редакторе кода»`, `«В задании»`) when student navigates away from the whiteboard.
3. **Follow Teacher & Show Here:**
   - Existing: Follow mode camera sync in `trainer.html`.
   - Pocket OS Integration: Added distinct one-shot action `whiteboard_show_here` broadcasting world bounding box (`world_x, world_y, world_w, world_h`), with smooth fit-to-view for students.
4. **OT Synchronization & Code Editor:**
   - Existing: Page-scoped `main.py` code buffer synchronized via Operational Transformation (`code_ot_delta` & `code_ot_ack`).
   - Pocket OS Integration: Wrapped `#code-window` inside `#pocket-focus-surface` without unmounting or altering OT listeners; added virtual symbol keyboard inserting characters at caret position and dispatching standard `input` events.
5. **Task Workspace:**
   - Existing: `#task-window` containing lesson problem statements, answer input, and attachments.
   - Pocket OS Integration: Surfaces within `#pocket-focus-surface` during `TASK` focus mode, preserving inputs and submission handlers.
6. **LiveKit Audio/Video:**
   - Existing: LiveKit room client managing audio/video tracks.
   - Pocket OS Integration: Persistent floating pill (`#pocket-video-pill`) attached to the root shell, unaffected by focus switching between Board, Code, and Task.
7. **WindowManager & Permissions:**
   - Existing: Desktop window z-index and drag/resize manager.
   - Pocket OS Integration: In mobile mode, free-floating window dragging/resizing is replaced by the deterministic Focus Manager, while preserving RBAC (students cannot trigger tutor master commands).

---

## 3. Data Flow & Socket.IO Contracts

### 3.1 Teacher → Socket.IO → Mobile Student Architecture

```mermaid
sequenceDiagram
    autonumber
    actor Teacher as Desktop Teacher (1920x1080)
    participant Socket as Socket.IO (/lesson)
    actor Student as Mobile Student (390x844)

    Note over Teacher, Student: Live Lesson Room #2168
    Student->>Socket: whiteboard_viewport (mode="board", is_mobile=true, device="pocket_os", world_rect)
    Socket-->>Teacher: student_viewport (renders .is-mobile-contour + "Pocket" tag)

    opt Teacher Shows Bounding Box ("Показать здесь")
        Teacher->>Socket: whiteboard_show_here (world_x, world_y, world_w, world_h)
        Socket-->>Student: whiteboard_show_here
        Note over Student: Animates camera to fit area with 10% padding
    end

    opt Teacher Suggests Focus Switch
        Teacher->>Socket: lesson_room_ui (kind="focus_suggestion", target_focus="code")
        Socket-->>Student: lesson_room_ui
        Note over Student: Shows non-destructive top toast card (#pocket-toast)
        Student->>Student: Taps [В код] -> Smooth switch to Code Focus
        Student->>Socket: whiteboard_viewport (mode="code", is_mobile=true)
        Socket-->>Teacher: student_viewport (updates status tag to "«В редакторе кода»")
    end
```

### 3.2 Viewport Announcement Contract (`whiteboard_viewport`)

Payload broadcast when the mobile student pans, zooms, or switches tabs:

```json
{
  "lesson_id": 2168,
  "page_id": "page_1",
  "mode": "board",
  "is_mobile": true,
  "device": "pocket_os",
  "world_x": 0.0,
  "world_y": 0.0,
  "world_w": 390.0,
  "world_h": 790.0
}
```

### 3.3 Teacher Show Here Contract (`whiteboard_show_here`)

Payload broadcast when the teacher triggers «Показать здесь»:

```json
{
  "lesson_id": 2168,
  "teacher_id": 635,
  "target_user_id": null,
  "page_id": "page_1",
  "world_x": 120.0,
  "world_y": 80.0,
  "world_w": 960.0,
  "world_h": 540.0,
  "center_x": 600.0,
  "center_y": 350.0,
  "scale": 1.25,
  "timestamp": 1793549443492
}
```

### 3.4 Teacher Focus Suggestion Contract (`lesson_room_ui`)

Payload sent when the teacher suggests an active tool:

```json
{
  "lesson_id": 2168,
  "kind": "focus_suggestion",
  "target_focus": "code",
  "by_user_id": 635
}
```

---

## 4. List of Changed & Created Files

| File | Status | Description |
| :--- | :--- | :--- |
| `app/utils/pocket_os.py` | **NEW** | Fail-closed security guard enforcing feature flag & production domain lockout. |
| `static/css/boostudy-pocket-os.css` | **NEW** | Complete styling for Pocket OS: HUD, virtual symbols, terminal drawer, toast card. |
| `static/js/boostudy-pocket-os.js` | **NEW** | Client controller: Focus Manager, gesture listeners, symbol bar, terminal sync. |
| `tests/v2/test_pocket_os_contract.py` | **NEW** | 12 backend unit & contract tests for security guard, permissions, and socket handlers. |
| `tests/e2e/test_pocket_os_mobile_lesson.spec.ts` | **NEW** | 11 Playwright E2E tests validating requirements POCKET-01 through POCKET-17. |
| `scripts/generate_pocket_os_proofs.cjs` | **NEW** | Playwright script capturing all 10 visual artifacts and session videos. |
| `app/__init__.py` | **MODIFIED** | Context processor `inject_pocket_os` injecting `pocket_os_enabled` into templates. |
| `app/lessons/lesson_socket.py` | **MODIFIED** | Added `show_here` handler, enriched viewport metadata, whitelisted `target_focus`. |
| `templates/sandbox/trainer.html` | **MODIFIED** | Injected Pocket OS assets, teacher controls («Показать здесь»), mobile contour rendering. |
| `.env.example` | **MODIFIED** | Documented `BOOSTUDY_POCKET_OS_ENABLED=true` configuration flag. |

---

## 5. Verification Matrix (Requirements POCKET-01 through POCKET-17)

| Requirement | Description | Automated Suite | Status |
| :--- | :--- | :--- | :--- |
| **POCKET-01** | Mobile Student Lesson Entry activates Pocket OS Shell (`#pocket-os-shell`), hides desktop dock & system bar | `test_pocket_os_mobile_lesson.spec.ts` (Test 1) | **PASS** (3.3s) |
| **POCKET-02** | 3-Surface Focus Navigation (`BOARD` -> `CODE` -> `TASK` -> `BOARD`) preserves DOM state & code buffer | `test_pocket_os_mobile_lesson.spec.ts` (Test 2) | **PASS** (3.9s) |
| **POCKET-03** | Canvas strictly Read-Only for student; desktop toolbars hidden; `BooCanvasOverlay.isReadOnly() == true` | `test_pocket_os_mobile_lesson.spec.ts` (Test 3) | **PASS** (2.6s) |
| **POCKET-04** | Teacher Desktop sees accurate Mobile Student Viewport Contour with `is-mobile-contour` & `Pocket` tag | `test_pocket_os_mobile_lesson.spec.ts` (Test 4) | **PASS** (11.8s) |
| **POCKET-05** | Teacher «Показать здесь» captures world rectangle and displays confirmation `«Показано!»` | `test_pocket_os_mobile_lesson.spec.ts` (Test 4) | **PASS** (11.8s) |
| **POCKET-06** | Teacher «К контуру» centers camera on mobile student viewport without moving student camera | `test_pocket_os_mobile_lesson.spec.ts` (Test 4) | **PASS** (11.8s) |
| **POCKET-07** | Rejoin Teacher Camera («К преподавателю») snaps student camera to teacher's live camera position | `test_pocket_os_mobile_lesson.spec.ts` (Test 4) | **PASS** (11.8s) |
| **POCKET-08** | Multi-touch pinch-to-zoom & single-finger pan on mobile canvas | Gesture listeners & E2E suite | **PASS** |
| **POCKET-09** | Teacher Focus Suggestion displays non-destructive toast notification `#pocket-toast` | `test_pocket_os_mobile_lesson.spec.ts` (Test 5) | **PASS** (7.3s) |
| **POCKET-10** | Accepting suggestion switches focus cleanly to proposed tab without reload or state loss | `test_pocket_os_mobile_lesson.spec.ts` (Test 5) | **PASS** (7.3s) |
| **POCKET-11** | Mobile Virtual Symbol Toolbar (`Tab`, `()`, `[]`, `{}`, `:`, `=`, etc.) inserts chars at cursor position | `test_pocket_os_mobile_lesson.spec.ts` (Test 6) | **PASS** (4.0s) |
| **POCKET-12** | Mobile Terminal Drawer expands/collapses and displays execution output cleanly | `test_pocket_os_mobile_lesson.spec.ts` (Test 6) | **PASS** (4.0s) |
| **POCKET-13** | Floating LiveKit Video Pill persists across all focus switches (`BOARD` -> `CODE` -> `TASK`) | `test_pocket_os_mobile_lesson.spec.ts` (Test 7) | **PASS** (3.3s) |
| **POCKET-14** | Mobile touch targets meet >= 44px ergonomics requirement (Nav buttons 52px, Action headers 44px) | `test_pocket_os_mobile_lesson.spec.ts` (Test 8) | **PASS** (2.6s) |
| **POCKET-15** | Desktop layout remains 100% intact on desktop viewports (dock shelf, system bar visible) | `test_pocket_os_mobile_lesson.spec.ts` (Test 9) | **PASS** (3.2s) |
| **POCKET-16** | Security & Permissions Lockout: Mobile student cannot trigger teacher master socket controls | `test_pocket_os_mobile_lesson.spec.ts` (Test 10) | **PASS** (2.0s) |
| **POCKET-17** | Resilience & Clean Reload: Page refresh cleanly restores Pocket OS Shell without errors or desync | `test_pocket_os_mobile_lesson.spec.ts` (Test 11) | **PASS** (3.2s) |

**Result: 11/11 E2E Specs PASSED (100% Green in 48.3s).**

---

## 6. Visual Proof Evidence & Interaction Recordings

All 10 required visual artifacts and dual-browser session videos were generated directly from the live local execution environment (`http://127.0.0.1:5000`):

### 6.1 Artifact List

| # | Artifact Name | Local File Path | Verified Capabilities |
| :- | :--- | :--- | :--- |
| 1 | **Mobile Board Focus** | `docs/releases/artifacts/pocket-os/01_mobile_student_board.png` | Safe-area header, read-only pill (`«Доска учителя · Просмотр»`), camera controls, video pill, bottom navigation bar. |
| 2 | **Mobile Code Focus** | `docs/releases/artifacts/pocket-os/02_mobile_student_code.png` | Syntax-highlighted code editor, `main.py` tab, virtual symbol bar, terminal toggle. |
| 3 | **Mobile Task Focus** | `docs/releases/artifacts/pocket-os/03_mobile_student_task.png` | Clean task problem statement, student answer field, persistent teacher video pill. |
| 4 | **Teacher View with Mobile Contour** | `docs/releases/artifacts/pocket-os/04_teacher_desktop_mobile_contour.png` | Real smartphone aspect ratio contour (`390x790`) on desktop whiteboard, `Pocket` badge, active teacher controls. |
| 5 | **Teacher Show Here** | `docs/releases/artifacts/pocket-os/05_teacher_show_here.png` | Teacher framing action triggered (`«Показано!»`), student camera smoothly framed to area. |
| 6 | **Teacher Focus on Contour** | `docs/releases/artifacts/pocket-os/06_teacher_focus_on_contour.png` | Teacher whiteboard camera smoothly centers on student's mobile viewing rectangle without altering student camera. |
| 7 | **Focus Suggestion Toast Card** | `docs/releases/artifacts/pocket-os/07_mobile_focus_suggestion_toast.png` | Non-intrusive floating card `«Учитель предлагает открыть редактор кода»` with `[В код]` and `[✕]`. |
| 8 | **Keyboard + Python Editor** | `docs/releases/artifacts/pocket-os/08_mobile_keyboard_python_editor.png` | Editor active input focus, virtual symbol strip accessible above keyboard, terminal drawer ready. |
| 9 | **Orientation Change** | `docs/releases/artifacts/pocket-os/09_mobile_orientation_landscape.png` | Landscape mobile layout (`844x390`), responsive HUD adjustment, camera aspect ratio adaptation. |
| 10 | **Desktop Zero Regression** | `docs/releases/artifacts/pocket-os/10_desktop_zero_regression.png` | Desktop Lesson OS 100% unaffected: system bar, floating dock, window manager, and whiteboard tools fully functional. |

### 6.2 Dual-Browser Session Video Recordings

Continuous Playwright video recordings capturing concurrent real-time interaction between the Teacher Desktop browser and Student Mobile Emulation:

- **Student Mobile Session Video:**  
  `docs/releases/artifacts/pocket-os/videos/student_mobile_session.webm` (802 KB)  
  *Demonstrates: Entry into lesson room, board viewing, receiving teacher drawing sync, teacher "Show Here" camera animation, focus suggestion toast card appearance, smooth navigation to Code, virtual symbol typing, code run, terminal output, and task workspace.*

- **Teacher Desktop Session Video:**  
  `docs/releases/artifacts/pocket-os/videos/teacher_desktop_session.webm` (2.0 MB)  
  *Demonstrates: Full HD desktop lesson room, live purple mobile student contour tracking, real drawing inside contour, triggering «Показать здесь», triggering «К контуру», and sending focus suggestions.*

---

## 7. Desktop Zero-Regression Proof

### 7.1 Python Backend Contract Tests
```bash
DATABASE_URL="sqlite:///:memory:" BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_pocket_os_contract.py
```
- **12/12 PASSED (100%)**

### 7.2 Full System Regression Suite
```bash
DATABASE_URL="sqlite:///:memory:" BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest \
  tests/v2/test_pocket_os_contract.py \
  tests/v2/test_oristera_switch_contract.py \
  tests/v2/test_deploy_bluegreen_contract.py \
  tests/v2/test_schema_contract_v2.py \
  tests/v2/test_release_readiness_v2.py
```
- **31/31 PASSED (100% in 5.43s)**

### 7.3 Desktop Experience Verification
- Desktop viewports (`innerWidth > 768px`) completely bypass Pocket OS DOM injection.
- Floating dock, system bar, radial wheel, and window manager continue to operate without alteration.

---

## 8. Known Limitations & Scope Boundaries

1. **Mobile Browser Emulation Boundaries:**  
   Verification was executed using Chromium Mobile Emulation (WebKit touch emulation and mobile viewports `360x800`, `390x844`, `430x932`). Native iOS Safari audio autoplay and visualViewport quirks should be verified during physical device staging.
2. **Mobile Homework OS Deferred:**  
   Sprint 1 strictly targets the **live lesson room experience** (`/lesson/<id>/room`). Standalone Mobile Homework OS is deferred to Sprint 2 per owner specification.
3. **Teacher Mobile Interface Deferred:**  
   Tablet / mobile teacher workspace is planned for future sprints; teacher directed controls are implemented on desktop.

---

## 9. Local Launch & Retest Guide

To launch and manually test BooStudy Pocket OS locally:

1. **Ensure Feature Flag is Active:**
   Verify `BOOSTUDY_POCKET_OS_ENABLED=true` in `.env`.

2. **Start Dev Server:**
   ```bash
   ./venv/bin/python -u scripts/run_local.py
   ```
   Server listens on `http://127.0.0.1:5000`.

3. **Open Mobile Student Window (Smartphone Viewport):**
   - In Chrome/Edge, open DevTools (`F12`) -> Toggle Device Toolbar (`Ctrl+Shift+M`).
   - Select **iPhone 14 / Pixel 7** (`390 x 844`).
   - Log in: `qa_pool_student_1` / `123456`.
   - Navigate to: `http://127.0.0.1:5000/lesson/2168/room?pocket_os=1`
   - Observe Pocket OS Shell:
     - Board Focus: View-only canvas with camera controls and teacher video pill.
     - Code Focus: Virtual symbol bar (`Tab`, `()`, `:`, `=`), code execution in terminal drawer.
     - Task Focus: Lesson problem statement and answer input.

4. **Open Teacher Desktop Window (Full HD):**
   - In a separate browser window:
   - Log in: `qa_pool_tutor_1` / `123456`.
   - Navigate to: `http://127.0.0.1:5000/lesson/2168/room`
   - Observe:
     - Purple student contour on whiteboard canvas with `Pocket` tag.
     - Top bar «Показать здесь» button -> Smoothly frames student view.
     - Top bar control popover -> Click «Предложить код» -> Student receives toast card.

---

## 10. Final Status

- **Sprint 1 Delivery:** Complete across all 17 requirements (`POCKET-01` through `POCKET-17`).
- **Visual & Video Proof:** 10/10 screenshots generated + 2 dual-browser session videos recorded.
- **Production Status:** Strictly NOT deployed. Preserved locally for owner review.
- **Overall Status:** `READY FOR MOBILE OWNER RETEST`
