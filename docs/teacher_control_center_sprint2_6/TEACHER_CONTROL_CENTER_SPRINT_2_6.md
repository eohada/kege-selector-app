# BooStudy — Teacher Control Center
## Sprint 2.6 — The Ultimate Teaching Workspace: Full Product Experience, Intelligent Scheduling & Interactive Calendar

---

## 1. Executive Summary & Vision

**Sprint 2.6** transforms BooStudy's teacher schedule from a standard calendar into an **Intelligent Teaching Control Center (TCC)**. Designed as a high-density, tactile workstation, it unites calendar scheduling, student roster filtering, homework lifecycle tracking, live lesson management, and intelligent slot recommendation into an ergonomic 3-Zone Adaptive Architecture.

### Core Architectural Pillars
1. **Zone A — Intelligent Tool Rail:** Collapsible left dock (64px compact / 270px expanded) with quick-access student roster, subject filters, visibility layer toggles (Homework Layer, Working Hours overlay, 15m grid), recurring series drawer, availability manager, and density toggle (`comfortable` vs `compact`).
2. **Zone B — Adaptive Focus Calendar:** High-performance viewport supporting **5 distinct temporal views**:
   - **Week View:** Canonical 7-day grid (07:00–23:00) with live red pulsing current time line, day summary metrics, and Variant C Hybrid Homework Layer pills.
   - **Day View:** Deep-focus single-day timeline with full card previews and note editor.
   - **Month View:** 7-column month matrix with lesson chips, deadline chips, and day workload indicators.
   - **Stream View (Agenda):** Chronological feed grouped by day with student avatars, lesson metadata, and instant interactive room launchers.
   - **Day Focus Mode:** Immersive today-centric cockpit with live countdown banner to next lesson ("Следующее занятие") and today's timeline.
3. **Zone C — Smart Context Inspector:** Right intelligence panel (350px dockable on desktop, drawer on tablet $\le$ 1024px, native bottom sheet on mobile $\le$ 768px):
   - **Overview Mode:** Live lesson countdown banner, "Требует внимания" signal feed (live lessons, upcoming lessons within 2 hours, homework submissions awaiting teacher grading), today's load bento, and quick action launchers.
   - **Lesson Inspector Mode:** Full lesson card, student avatar, room launch/copy link, 4-state lifecycle status switcher (`planned`, `in_progress`, `completed`, `cancelled`), attached homework tracking, inline editable teacher notes, and reschedule/cancel actions.
   - **Smart Time Finder ("Найти окно"):** Automated recommendation engine analyzing teacher working hours, date exceptions, existing lessons, and student conflicts to propose optimal non-conflicting slots (45, 60, 90 mins).
   - **Slot Composer Mode:** Native inline lesson creation form directly inside Inspector.
4. **Command Palette (`Ctrl/Cmd + K` or `/`):** Fast keyboard modal for instant navigation, view switching, slot creation, student filtering, and settings.
5. **Mobile Workstation ($\le$ 768px):** Clean week ribbon strip (Mon–Sun pills with active date indicator), daily agenda cards, bottom sheet inspector, and floating action button (+).

---

## 2. 3-Zone Adaptive Architecture

```
+---------------------------------------------------------------------------------------------------------+
| Top Global Header: Navigation, Impersonation Pill, Search Bar (Ctrl+K), Profile Dropdown                |
+---------------------------------------------------------------------------------------------------------+
| [Zone A: Rail] | [Zone B: Adaptive Focus Calendar]                         | [Zone C: Smart Inspector]  |
| 64px / 270px   | - View Switcher: Неделя | День | Месяц | Лента | Фокус     | 350px Dock / Drawer / BS   |
| - Search (/)   | - Timezone Selector & Live MSK/Local conversion           | - Overview: Attention Feed |
| - Students     | - Sub-Bar: Active Filter Pills, Load Metrics              | - Lesson Inspector         |
| - Subjects     | - Calendar Body: 07:00-23:00 Grid                         | - Smart Time Finder        |
| - Layers       |   * Subject Color Stripes (Indigo, Sky, Emerald, Amber)   | - Inline Slot Composer     |
| - Recurrence   |   * Live Red Pulsing Time Line                            | - Editable Teacher Notes   |
| - Avail Hours  |   * Variant C Hybrid Homework Layer Pills                 | - Room Launcher            |
| - Density (C/C)|   * Drag-to-Reschedule Ghost & Bottom Resize Handle       | - Status Switcher          |
+---------------------------------------------------------------------------------------------------------+
```

### Component Details
- **Tool Rail (`#tcc-tool-rail`):**
  - Uses CSS flex layout with smooth `transform: translateX` and width transition.
  - Collapsed state (64px) shows icons with interactive tooltips and student badge counter.
  - Expanded state (270px) displays full student search, roster list with active student filter, subject filter, and layer toggles.
- **Calendar Viewport (`#tcc-calendar-viewport`):**
  - Full-height scrollable container (`calc(100vh - 72px)`).
  - Synchronized sticky headers for weekdays (`#tcc-days-header-row`) with day stats and deadline pills.
  - Time column (07:00 to 23:00) with 15-minute subdivisions.
  - Dynamic density toggle: `comfortable` (60px/hour) and `compact` (44px/hour).
- **Smart Context Inspector (`#tcc-inspector`):**
  - Integrated smoothly into desktop layout with dock toggle button.
  - Responsive breakpoint transitions:
    - Desktop ($> 1024\text{px}$): Embedded flex column, 350px width.
    - Tablet ($769\text{px} - 1024\text{px}$): Slide-out drawer with backdrop blur.
    - Mobile ($\le 768\text{px}$): Bottom sheet with swipe handle, rounded top corners (`border-radius: 24px 24px 0 0`).

---

## 3. Direct Manipulation & Scheduling Engine

### 1. Drag-to-Reschedule
- **15-Minute Slot Snapping:** While dragging, coordinates calculate `Math.floor((relY) / (hourHeight / 4)) * 15`.
- **Ghost Preview:** Interactive clone (`.tcc-drag-ghost`) tracks cursor position with subtle shadow and opacity.
- **Collision Detection:** Highlights target cells and verifies teacher availability before drop.
- **Recurrence Scope Modal:** When dropping a lesson belonging to a recurring series, prompts the teacher:
  1. *Только этот урок* (`scope=single`): updates only this instance.
  2. *Этот и все последующие* (`scope=future`): updates current and subsequent slots.
  3. *Вся серия целиком* (`scope=series`): updates base recurring pattern.

### 2. Bottom Resize Handle
- Dedicated handle (`.tcc-resize-handle`) on the bottom edge of lesson cards.
- Dragging downward or upward snaps duration to 15-minute increments (minimum 15 mins, maximum 240 mins).
- On mouse release, dispatches async update to `/api/schedule/update_lesson/<id>` and updates UI instantly.

### 3. Drag-to-Select / Click Empty Slot
- Clicking or dragging across empty grid intervals automatically opens the Inspector in `composer` mode, pre-populating target date, time, and 60m duration.

### 4. Right-Click Context Menu
- Custom context menu (`#tcc-context-menu`) on lesson cards:
  - *Войти в интерактивную комнату* (opens `/room/<id>` in new tab).
  - *Подробнее / Редактировать* (activates Lesson Inspector).
  - *Перенести урок* (activates drag mode).
  - *Отменить занятие* (calls `/schedule/api/lesson/<id>/delete` with confirmation).

---

## 4. Intelligent Backend & Smart Time Finder

### 1. Endpoint: `/api/schedule/find-free-slots`
- Accepts `GET` or `POST` with `duration` (45, 60, 90 mins), `date_from`, `date_to`, `student_id`.
- Algorithmic steps:
  1. Determines teacher's working intervals from `TeacherWeeklyAvailability` for each weekday in the range.
  2. Subtracts full-day and custom-hour exceptions from `TeacherScheduleExceptions`.
  3. Queries teacher's existing non-cancelled lessons and subtracts busy intervals.
  4. If `student_id` is supplied, queries student's lessons across all tutors to prevent cross-teacher collisions.
  5. Computes candidate start slots snapped to 15-minute intervals.
  6. Filters candidate slots into high-priority recommendations (morning, afternoon, evening windows).
- Returns structured JSON: `[{ "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM", "weekday_name": "...", "label": "..." }]`.

### 2. Attention Required Engine
- In `app/schedule/routes.py`, `teacher_attention_items` aggregates:
  - **Live Lessons (`in_progress`):** Highlighted with pulsed badge and immediate "Войти" button.
  - **Upcoming Lessons ($\le 2\text{h}$):** Marked as high priority.
  - **Pending Homework (`SUBMITTED`, `NEEDS_MANUAL_REVIEW`):** Fetched for accessible students with links to grading workspace.

### 3. Variant C Hybrid Homework Layer
- `teacher_homework_items` supplies assignments with deadlines and student submission status.
- Homework pills render directly inside day headers:
  - `ДЗ: сдали` (Amber badge for submissions needing review).
  - `ДЗ: принято` (Emerald badge for completed homework).
  - `ДЗ: срок` (Sky badge for upcoming deadlines).

---

## 5. Security & Isolation Guarantees

- **Multi-Teacher Isolation:** Every query strictly enforces `Lesson.teacher_id == current_user.id` or `ownership_service.can_user_view_lesson(lesson, current_user)`.
- **IDOR Protection:** Cross-teacher updates, cancellations, or reschedules are rejected with HTTP 403 Forbidden.
- **Student Privacy:** Teachers only see students with active educational relationships (`TeacherStudent`, `Enrollment`, `Student.mentor_id`).
- **Student Schedule Independence:** Student Concept D (`templates/sandbox/student_schedule.html`) remains strictly untouched and pristine.

---

## 6. Verification Artifacts & Visual Acceptance Gallery

All review artifacts are saved in `docs/teacher_control_center_sprint2_6/key_review/`:

| File | Resolution / Type | Verification Target |
| :--- | :--- | :--- |
| `01_desktop_1920_week_view.png` | 1920×1080 Desktop | Canonical Week View with 3-Zone layout, attention items, homework pills, and live time line |
| `02_desktop_1920_tool_rail_expanded.png` | 1920×1080 Desktop | Zone A Tool Rail expanded showing student roster, subject filters, and layer controls |
| `03_desktop_1920_lesson_inspector.png` | 1920×1080 Desktop | Zone C Lesson Inspector showing card metadata, room launcher, status switcher, teacher notes |
| `04_desktop_1920_find_time_modal.png` | 1920×1080 Desktop | Smart Time Finder recommendation interface with duration selector (45/60/90m) |
| `05_desktop_1920_slot_composer.png` | 1920×1080 Desktop | Zone C inline lesson creator with pre-filled slots and tactile submit button |
| `06_desktop_1920_day_view.png` | 1920×1080 Desktop | Focused single-day timeline view with full lesson cards and notes |
| `07_desktop_1920_month_view.png` | 1920×1080 Desktop | 7-column month overview grid with lesson chips, deadline chips, and day workload badges |
| `08_desktop_1920_stream_view.png` | 1920×1080 Desktop | Chronological agenda feed grouped by day with student avatars and direct room entrance buttons |
| `09_desktop_1920_day_focus_mode.png` | 1920×1080 Desktop | Immersive Day Focus mode with countdown banner ("Следующее занятие") and today's timeline |
| `10_desktop_1920_command_palette.png` | 1920×1080 Desktop | Centered Command Palette modal (`Ctrl+K`) with keyboard navigation and quick actions |
| `11_desktop_1440_compact_density.png` | 1440×900 Desktop | 1440px viewport verification with compact density toggled (44px/hour grid) |
| `12_desktop_1366_standard.png` | 1366×768 Desktop | Standard 1366px laptop viewport verification |
| `13_tablet_1024_drawer.png` | 1024×768 Tablet | Tablet viewport showing Zone C as an overlay drawer with backdrop blur |
| `14_mobile_390_week_ribbon.png` | 390×844 Mobile | Mobile workstation with horizontal week ribbon strip (Mon–Sun pills), day agenda cards, FAB |
| `15_mobile_390_bottom_sheet_inspector.png` | 390×844 Mobile | Mobile bottom sheet inspector open with lesson controls and status switcher |
| `16_desktop_reschedule_scope_modal.png` | 1920×1080 Desktop | Recurring lesson reschedule prompt modal (Single, Future, Series options) |
| `motion_proof.webm` | 1920×1080 Video | Full interaction recording: view transitions, drawer animations, modal prompts, and responsive layouts |

---

## 7. Automated Test Results

- **Teacher Schedule Multi-Teacher Integration (`tests/v2/test_teacher_schedule_integration_sprint2_3.py`):**
  - **20 / 20 PASSED (100%)**
  - Verified isolation, IDOR rejection, conflict detection, concurrent lock serialization, timezone awareness, and ICS/JSON export.
- **Student Schedule Evolution (`tests/v2/test_student_schedule_evolution.py`):**
  - **15 / 15 PASSED (100%)**
  - Confirmed 0 regressions on Concept D student schedule.
- **Timezone Clean Extraction (`tests/v2/test_timezone_schedule_v2.py`):**
  - **PASSED**
  - Verified UTC and MSK time conversions without data loss.
