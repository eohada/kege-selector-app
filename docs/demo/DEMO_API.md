# BooStudy Demo Experience — API Contract

All mutation endpoints are session-scoped. Unless stated otherwise, they require an authenticated `is_demo_user` with `demo_state` and `demo_session_id`.

## `GET /demo`

Renders `templates/sandbox/demo_welcome.html` with current `demo_state` and active-demo flag. No mutation.

## `POST /demo/api/init`

Rate limit: 10/minute. Body: `student_name`, `exam`, `goal`, `grade`, `mode`, optional `start_at_dashboard`. Creates/ensures demo user and dataset. If `start_at_dashboard` is true, resets the demo session and starts Chapter 2 state. Response: `{success, state, dashboard_url}`. Errors are validation/session/application errors. Side effects include login and demo rows.

## `GET /demo/api/state`

Returns `{success: true, state}`. No mutation beyond state normalization performed by service.

## `POST /demo/api/state`

Body: partial state update, normally `chapter_id`, `step_id`, flags. The requested transition is validated by `is_demo_transition_allowed`; invalid transition returns 409 with current state. Response `{success, state}`.

## `POST /demo/api/director`

Development-only rehearsal control. Body contains `chapter` or a named state such as `mistakes_opened`. Requires demo user. Rewrites session state and prerequisite actions; response contains destination state/url. It is not a customer-facing route and must not be used as a production navigation contract.

## `POST /demo/api/event`

Rate limit: 120/minute. Body: `action_id`, optional `chapter_id`, `step_id`, `payload`. Valid actions are checked against current scene. Repeated non-`transition_step` action returns success with `idempotent: true`; invalid action or transition returns 409 and leaves state unchanged. `demo:finale:shown` adds session-only `cinema_reward=spark`.

## `POST /demo/api/verify-answer`

Rate limit: 30/minute. Body: `answer`, optional `submission_id` (otherwise state `submission_id`). Server checks demo ownership, stores Answer and updates Submission. `5` is correct. Main submission correct → `victory`; wrong → `trial_retry`. Retry submission correct → `mistakes_fixed` and Chapter 5 remains at `mistakes_opened`. Missing submission: 400; wrong demo ownership: 403; normal success: 200.

## `POST /demo/api/request`

Rate limit: 3/hour. Body: `name`, `contact`, `grade`, `goal`, `timezone`, `slot`, `consent=true`, optional honeypot `website`. Validates contact and time zone, upserts the current demo student's `CallRequest`, sets `source='demo_intro'`, `is_demo=True`, updates session flags, and attempts notification delivery. Notification failure does not roll back persisted lead. Response includes `success`, `existing`, `queued`, `request_id`. Validation: 400; missing demo session: 403; profile conflict: 409; persistence failure: 500.

## `POST /demo/api/exit`

Clears demo session, logs out demo user, expires `is_demo` and `cinemaMode` cookies. Returns `{success: true, redirect_url}`.

## Related real routes

The demo navigates real `/dashboard`, `/lesson/...`, `/submissions`, `/task-workspace`, `/theory`, `/courses...`, `/student/.../analytics`, `/schedule` and `/workspace/profile` routes. Their full contracts belong to platform documentation; demo depends on their target markers and dataset compatibility.
