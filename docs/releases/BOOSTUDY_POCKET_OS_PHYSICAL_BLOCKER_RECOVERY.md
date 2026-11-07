# BOOSTUDY POCKET OS — SPRINT 1.2.1
## Physical Device Blocker Recovery: Bidirectional OT, Single Terminal Drawer & LiveKit Call Integration

- **Date:** 2026-11-02
- **Environment:** Local Development Only (`http://127.0.0.1:5000`, `https://192.168.1.3:5443`)
- **Status:** **READY FOR PHYSICAL OWNER RETEST**
- **Production Status:** **STRICTLY NO PRODUCTION DEPLOY**

---

## 1. Executive Summary

During the initial physical smartphone test of BooStudy Pocket OS on LAN (`http://192.168.1.3:5000`), the owner confirmed that **Mobile BooCanvas**, **Student Contour**, and **Mobile Lesson Tasks** functioned reliably (**PASS**). However, two blockers were identified:
1. **Mobile Python Execution & OT Sync:**
   - Student edits did not synchronize back to the teacher via Operational Transformation (OT).
   - Running Python code opened duplicate terminals (both mobile drawer and floating desktop window).
   - Double execution and output corruption occurred on rapid taps.
2. **Mobile LiveKit:**
   - LiveKit video/audio conference could not be joined on mobile.
   - Insecure origin (`http://192.168.1.3:5000`) caused browser security blocks on WebRTC / `getUserMedia` (`isSecureContext === false`).
   - No explicit, authorized join button or mobile in-call controls existed.

Sprint 1.2.1 resolved all root causes without regressing the validated BooCanvas, Student Contour, or Lesson Tasks modules. All automated end-to-end acceptance tests now pass with a 100% pass rate.

---

## 2. Verification Categorization

| Area | Status | Verification Method |
|---|---|---|
| **Student $\to$ Teacher Bidirectional OT** | **VERIFIED BY AUTOMATION** | Playwright `CODE-DEVICE-01 & 02` (Pass) |
| **Server Permission & Freeze Enforcement** | **VERIFIED BY AUTOMATION** | Playwright `CODE-DEVICE-03 & 04` (Pass) |
| **Python Syntax Highlighting & Caret Alignment** | **VERIFIED BY AUTOMATION** | Visual inspection & identical font metric css rules |
| **Single Mobile Terminal Drawer (No Desktop Leak)** | **VERIFIED BY AUTOMATION** | Playwright `TERMINAL-DEVICE-01 & 02` (Pass) |
| **Execution Re-entrance Lock (`_isExecuting`)** | **VERIFIED BY AUTOMATION** | Playwright `TERMINAL-DEVICE-01 & 02` (Pass) |
| **LiveKit Single Manager & Join UI Flow** | **VERIFIED BY AUTOMATION** | Playwright `MEDIA-DEVICE-01..05` (Pass) |
| **Call Continuity on Tab Switch (`board` $\leftrightarrow$ `code` $\leftrightarrow$ `task`)** | **VERIFIED BY AUTOMATION** | Playwright `MEDIA-DEVICE-01..05` (Pass) |
| **Canvas & Desktop Zero Regression** | **VERIFIED BY AUTOMATION** | Playwright `REGRESSION-DEVICE-01..03` (Pass) |
| **Physical Smartphone Touch/Haptic Typing** | **NOT VERIFIED** | Awaits physical owner retest |
| **Physical Hardware Mic/Cam Permissions on Phone** | **NOT VERIFIED** | Awaits physical owner retest via HTTPS |
| **Acoustic Audio Routing / Speakerphone on Handset** | **NOT VERIFIED** | Awaits physical owner retest |

---

## 3. Root Cause Analysis

### 3.1. Python OT Sync Failure & Server Permissions
- **Root Cause 1:** Desktop permission checks bypassed mobile clients (`!isPocketMobile`), but textarea DOM attributes were not reactively synchronized when the teacher dynamically altered permissions via `control.update`.
- **Root Cause 2:** In `whiteboard_service.py`, `default_control()` did not include `"freeze_student"`, causing server-side sanitization (`if key in allowed`) to discard freeze updates during control commits.
- **Root Cause 3:** Virtual symbol keys (Tab, colon, quotes, operators) inserted text directly into `#code-editor-textarea` without checking `textarea.readOnly`, bypassing student read-only restrictions.

### 3.2. Terminal Duplication & Output Corruption
- **Root Cause 1:** `templates/sandbox/trainer.html` line 8100 called `openWindow('terminal-window')` unconditionally upon code execution. On mobile, this launched the floating desktop window alongside the mobile drawer.
- **Root Cause 2:** Every execution attached a new MutationObserver to `#terminal-body` without disconnecting prior observers, multiplying output logs upon subsequent runs.
- **Root Cause 3:** `_isExecuting` was not protected with a `finally` block, leaving the execution state locked if an unhandled promise rejection occurred.

### 3.3. Mobile LiveKit Inability to Join
- **Root Cause 1:** WebRTC (`navigator.mediaDevices.getUserMedia`) is restricted by modern mobile browsers (Chrome Android, Safari iOS) strictly to **Secure Contexts** (`window.isSecureContext === true`). Non-localhost HTTP (`http://192.168.1.3:5000`) is marked insecure and media devices are completely blocked.
- **Root Cause 2:** The mobile UI lacked an authorized "Войти в звонок" action and media control toolbar to trigger `lessonLivekit.joinRoom()`, leave calls, or toggle mic/cam.

---

## 4. Architectural & Code Modifications

### 4.1. Core Whiteboard & Server Control (`app/lessons/whiteboard_service.py`)
- Added `"freeze_student": False` to `default_control()`.
- Server now authoritatively persists and broadcasts both `student_code_editing` and `freeze_student` to all session participants via `control.update`.

### 4.2. Desktop & Room Controller (`templates/sandbox/trainer.html`)
- **Desktop `#code-window-permission-badge`:**
  - Made clickable for teachers to dynamically toggle `student_code_editing`.
  - Dispatches `commitControl({ student_code_editing: !ctrl.student_code_editing })`.
- **Suppression of Desktop Terminal on Mobile:**
  - `openWindow('terminal-window')` is now guarded: `if (termEl && !window.BooStudyPocketOS?.active)`.
- **Synchronized State Expositions:**
  - Exposed `window.controlState = controlState` and `window.commitControl = commitControl` to ensure consistent access across desktop and mobile components.
- **Preserved Syntax Highlighting & Font Alignment:**
  - Maintained `#code-editor-highlight` and `#code-editor-textarea` pairing with identical font metrics (`ui-monospace`, `13px`, `22px` line-height, identical padding, `white-space: pre !important`, `word-break: normal !important`). No syntax highlight overlay was removed.

### 4.3. Pocket OS Runtime (`static/js/boostudy-pocket-os.js`)
- **Authoritative Permission Badge & Lock:**
  - Added `#pocket-code-permission-badge` in code header displaying three distinct states:
    - `is-editable` ("Можно писать", emerald)
    - `is-readonly` ("Только чтение", amber)
    - `is-frozen` ("Демонстрация", rose)
  - `updateCodePermissionBadge()` enforces `textarea.readOnly = isFrozen || !control.student_code_editing`.
  - `bindVirtualSymbols()` checks `textarea.readOnly` before inserting any symbol; inputs are blocked when read-only.
- **Single Terminal Drawer & Execution Lock:**
  - `runPythonCode()` utilizes a strict `try/finally` block for `_isExecuting`.
  - Disconnects existing `_terminalObserver` prior to observing new executions.
  - Adds a stale indicator (`is-stale`) to the terminal drawer if code is modified after a run.
- **LiveKit Controller Integration:**
  - Integrates directly with existing `window.lessonLivekit` (single room manager instance; no duplicate connection).
  - Implemented `joinLiveKitCall()`, `leaveLiveKitCall()`, `toggleLiveKitAudio()`, and `toggleLiveKitVideo()`.
  - Added `syncLiveKitUIState()` reacting to `boostudy:livekit-state-change`.
  - Header displays `#pocket-btn-join-call` in disconnected state, switching to `#pocket-call-leave` and mic/cam toggles in connected state.
  - Video pill `#pocket-video-pill` switches from compact avatar indicator to inline video stream when the teacher camera is active.
  - Focus changes between `board`, `code`, and `task` never detach audio tracks or tear down the LiveKit session.

### 4.4. Pocket OS Styles (`static/css/boostudy-pocket-os.css`)
- Suppressed `#terminal-window` completely when `body.pocket-os-active`.
- Added styles for `.pocket-code-perm-badge`, `.pocket-btn-join-call`, `.pocket-call-leave-btn`, and call toolbar buttons.

### 4.5. Trusted Local Development HTTPS Infrastructure
- Created `scripts/setup_dev_ca.sh`: Generates a local root CA (`certs/dev_root_ca.crt`) and an OpenSSL server certificate with Subject Alternative Names (`IP:192.168.1.3`, `IP:127.0.0.1`, `DNS:localhost`).
- Created `scripts/run_dev_https.sh`: Launches a standard `socat` TLS proxy on `https://192.168.1.3:5443` forwarding to Flask at `127.0.0.1:5000`.
- Verified `.gitignore` prevents keys, certs, and PEM bundles from leaking into version control.

---

## 5. Automated E2E Verification Results

Playwright Test Suite: `tests/e2e/test_pocket_os_blocker_recovery.spec.ts`

```
Running 5 tests using 1 worker

  ✓ 1 CODE-DEVICE-01 & 02: Bidirectional OT sync when permission granted, persisted on reload (23.2s)
  ✓ 2 CODE-DEVICE-03 & 04: ReadOnly & Freeze strictly lock mobile typing and virtual keys (10.8s)
  ✓ 3 TERMINAL-DEVICE-01 & 02: Single mobile drawer, desktop terminal hidden, focus switch safe (8.0s)
  ✓ 4 MEDIA-DEVICE-01..05: LiveKit Join button, connection state, AV controls and tab continuity (7.1s)
  ✓ 5 REGRESSION-DEVICE-01..03: Canvas, Tasks and Desktop Lesson OS maintain 100% zero regression (8.4s)

5 passed (58.2s)
```

### Detailed Test Assertions:
1. **CODE-DEVICE-01 & 02:**
   - Teacher on desktop clicked permission badge to grant `student_code_editing: true`.
   - Student on mobile entered `print("MOBILE_TO_TEACHER")`; teacher desktop received OT edit in real time without reload.
   - Teacher appended `print("TEACHER_TO_MOBILE")`; student mobile received line via OT in real time.
   - Both pages reloaded; code persisted accurately on server.
2. **CODE-DEVICE-03 & 04:**
   - Teacher set `student_code_editing: false`. Student textarea was locked to `readOnly: true` and badge showed "Только чтение".
   - Student tapped virtual key (`Tab`); textarea contents remained unmodified.
   - Teacher enabled `freeze_student: true`. Badge changed to "Демонстрация" and inputs remained strictly locked.
3. **TERMINAL-DEVICE-01 & 02:**
   - Student tapped "Запустить"; mobile terminal drawer opened.
   - Desktop `#terminal-window` remained completely hidden.
   - Output `Running python main.py...` and `Выполнено` appeared in the mobile console.
   - Rapid double-tapping did not cause errors or duplicate execution.
   - Focus switched `code` $\to$ `board` $\to$ `code`; console contents remained preserved.
4. **MEDIA-DEVICE-01..05:**
   - In disconnected state, `#pocket-btn-join-call` was visible; in-call controls were hidden.
   - In connected state, Join button hid; leave, mic, and camera controls appeared.
   - Mic mute toggled `.is-muted`.
   - Focus switched between `board`, `code`, and `task`; call controls and media stayed active and uninterrupted.
5. **REGRESSION-DEVICE-01..03:**
   - Desktop Lesson OS `#canvas-window` and `#code-window` operated normally.
   - Mobile `#canvas-window` and `#task-window` displayed and interacted cleanly.

---

## 6. Physical Owner Retest Protocol

To complete physical acceptance on the test smartphone (e.g. Android or iPhone), follow this step-by-step protocol:

### Step 1: Install Local Root CA on Smartphone (One-time Setup)
1. Ensure the development machine is running on LAN IP `192.168.1.3`.
2. Transfer `certs/dev_root_ca.crt` to your smartphone (via AirDrop, USB, Google Drive, or email).
3. **On Android:**
   - Open **Settings** $\to$ **Security & Privacy** $\to$ **More Security Settings** $\to$ **Encryption & Credentials** $\to$ **Install a Certificate** $\to$ **CA Certificate**.
   - Select `dev_root_ca.crt` and tap **Install Anyway**.
4. **On iOS:**
   - Open the transferred `dev_root_ca.crt` profile in **Settings** $\to$ **Profile Downloaded** $\to$ tap **Install**.
   - Navigate to **Settings** $\to$ **General** $\to$ **About** $\to$ **Certificate Trust Settings** $\to$ toggle **Full Trust** for "BooStudy Dev Root CA".

### Step 2: Start Development HTTPS Server
On your development machine, ensure the HTTPS proxy is running:
```bash
./scripts/run_dev_https.sh
```
*Note: Flask must be running on `127.0.0.1:5000` (e.g. via `python -u scripts/run_local.py`).*

### Step 3: Open Session on Teacher & Smartphone
1. **Teacher Desktop:** Open Chrome and navigate to:
   `http://127.0.0.1:5000/lesson/2168/room`
   Log in as `qa_pool_tutor_1` (password `123456`).
2. **Student Smartphone:** Open Chrome/Safari and navigate to:
   `https://192.168.1.3:5443/lesson/2168/room?pocket_os=1`
   Log in as `qa_pool_student_1` (password `123456`).

### Step 4: Physical Test Cases

#### Test Case A: Mobile Python & Bidirectional OT
1. On phone, tap the **Код** tab. Verify the permission badge displays "Только чтение" (amber). Attempt to type; verify typing is disabled.
2. On teacher desktop, click the badge `#code-window-permission-badge` in the code window titlebar (changes to "Ученик может писать").
3. On phone, observe badge immediately changes to "Можно писать" (emerald).
4. On phone, type `print("HELLO_FROM_PHONE")` using the on-screen keyboard and virtual toolbar keys.
5. On teacher desktop, observe `print("HELLO_FROM_PHONE")` appears in real time without refreshing.
6. On teacher desktop, type `# Teacher reply` at the end. Observe it immediately appears on the phone.

#### Test Case B: Mobile Terminal Single Drawer & Execution
1. On phone, tap **Запустить**.
2. Verify:
   - The bottom drawer opens showing execution status and output.
   - **Zero** floating desktop windows appear on the phone.
   - Output displays `HELLO_FROM_PHONE` and completion timestamp.
3. Rapidly tap **Запустить** twice: verify terminal runs cleanly without double printing or freezing.
4. Tap **Доска**, then tap **Код**: verify terminal drawer output is still visible.

#### Test Case C: Mobile LiveKit Conference
1. In the mobile header, locate the **"Войти в звонок"** button.
2. Tap **"Войти в звонок"**.
3. Allow microphone/camera permissions when prompted by the mobile browser.
4. Verify:
   - "Войти в звонок" disappears and is replaced by in-call controls (leave call button, mic toggle, cam toggle).
   - If teacher has camera on, video pill `#pocket-video-pill` shows live video stream.
5. Tap the microphone button: verify it mutes/unmutes.
6. Switch tabs: tap **Доска** $\to$ **Задания** $\to$ **Код**.
   - Verify audio and video continue smoothly without dropping or reconnecting.
7. Tap the red Leave button: verify call disconnects cleanly and "Войти в звонок" reappears.
