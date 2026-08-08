# Telegram Mini App Revamp & Bug Tracker Implementation

This plan addresses layout and functionality issues in the Telegram Mini App (TWA) for creators and students, alongside introducing a structured bug reporting feature on the main web platform.

## Proposed Changes

### Telegram Mini App (`mini_app.html` & `mini_app.py`)

#### Creator Mode
*   **UI/UX Improvements**: Enhance readability with better contrasts, improved margins, and clearer typography.
*   **Data Display**: Fix the "empty data" states where overview cards show empty/zero erroneously. Ensure real metrics flow through API.
*   **Student Filtering**: Add a real-time text filter/search input in the "Students" tab to quickly find specific students rather than scrolling a raw list.

#### Student Mode
*   **Distinct Interface**: Refactor `mini_app.html` so that a student's view genuinely feels like a native dedicated app.
*   **Schedule (Main Screen)**: Update the "Overview" to prioritize the schedule. Tapping a lesson will reveal an external explicit "Go to lesson" action.
*   **Theory Integration**: Ensure `theory.view` articles render beautifully and intuitively inside the Mini App.
*   **My Tasks (HW)**: Submissions list will prominently display status and deadlines, with clear call-to-actions to solve them on the web version.
*   **Profile & Statistics**: Refine the visual grouping to show analytical graphs and a structured gradebook.

---

### Bug Reporting Feature (Platform Backend & Frontend)

#### BugReport Model (`core/db_models.py`)
*   Create a `PlatformBugReport` SQLAlchemy model in the PostgreSQL database.
*   Fields: `id`, `user_id`, `url_context`, `description`, `status` (new, in_progress, resolved).

#### Student View (Main Platform)
*   **UI Component**: Inject a floating "Report Error" (Сообщить об ошибке) button into global layout templates.
*   **Modal Form**: Clicking the button will trigger a modal allowing the student to describe the bug.
*   **Backend API**: Create a route `POST /api/bug_report` to accept these form submissions and save them to the database.

#### Creator View (Main Platform)
*   **Dashboard Section**: Add a panel in the creator/admin platform interface (e.g. `remote_admin` templates) to view all submitted `PlatformBugReports`.
*   **Status Management**: Provide UI controls (buttons/dropdowns) permitting the creator to easily transition report statuses.

## Open Questions

> [!WARNING]
> **To the User**: Please clarify the following before we proceed:
> 
> 1. **Bug Report Visibility**: Do you want the Creator's interface for viewing and managing bug reports to be on the **Main Web Platform** (e.g. inside `/admin` or dashboard)?
> 2. **Student Dashboard**: The existing TWA has an "Overview" tab. To achieve your desired student interface, we will rebuild the student TWA tabs strictly as: Schedule, Theory, Homework, Profile. Is that structure accurate?

## Verification Plan

### Automated/Manual Tests
*   **Creator TWA**: Emulate a creator session, verify that analytics load, empty states are styled, and the "Students" tab search auto-filters the list.
*   **Student TWA**: Emulate a student session, confirm the 4 tabs render correctly.
*   **Bug Reports**: Login as a student on the platform, create a bug report. Switch to Creator, confirm the bug report is visible and mutable.
