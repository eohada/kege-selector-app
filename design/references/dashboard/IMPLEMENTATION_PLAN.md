# Dashboard implementation plan

| REFERENCE ELEMENT | CURRENT IMPLEMENTATION | TARGET COMPONENT | DATA SOURCE | REQUIRED CHANGE |
|---|---|---|---|---|
| Golden Sidebar | `templates/sandbox/components/_sidebar.html` / sandbox shell | `BsSidebar` / `BsAppShell` | existing nav config and current user | visual refactor after foundation |
| Golden Search | sandbox topbar search | `BsSearch` | existing search state | reuse logic, align placement |
| Golden Profile | sandbox profile menu | `BsAvatar` + profile menu primitive | `current_user` | preserve menu behaviour, restyle |
| Golden Notifications | sandbox topbar notifications | `BsIconButton` + `BsBadge` | existing notifications | align beside profile |
| Page shell | `templates/sandbox/layout_*.html` | `BsAppShell` + `BsPageContainer` | session/role context | normalize width and responsive rules |
| Bento grid | current dashboard teacher/student blocks | `BsBentoGrid` / `BsBentoCard` | existing dashboard services | map spans without changing data |
| Hero | current dashboard hero blocks | `DashboardHero` using card primitives | dashboard context | redesign in a follow-up task |
| Metric cards | current dashboard KPI blocks | `BsMetric` | dashboard service values | compact metric grammar |
| Tasks / next lesson | current dashboard task and lesson blocks | `BsCard` + `BsSectionHeader` | existing queries | preserve actions, recompose visually |
| Boo illustration | `static/images/dashboard/*` and existing Boo assets | mascot inventory | static assets | select by intended usage, avoid stretching |

## Stage 2 status

The student dashboard now uses the Golden shell and bento composition through `templates/sandbox/layout_dashboard.html` and `templates/sandbox/student_dashboard.html`. The teacher dashboard keeps its existing data-driven blocks, forms and scripts inside the same canonical shell, with token-backed visual normalization; a deeper teacher content redesign remains a separate follow-up if needed.

This implementation is `CANDIDATE FOR HUMAN APPROVAL`; screenshots are not baseline yet.
