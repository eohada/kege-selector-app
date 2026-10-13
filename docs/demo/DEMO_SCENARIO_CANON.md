# BooStudy Demo Experience — Canonical Scenario

Источник: текущий `static/js/demo/demo_scenario.js`, `static/js/demo/demo_engine.js`, `static/js/demo/boo_companion.js`, `app/demo/service.py`, templates и `tests/e2e/demo-linear-release.spec.ts`. Старый `docs/demo-scenario-full.md` сохранён как reference.

Статусы: `IMPLEMENTED` — код и тесты указывают на реализацию; `PARTIAL` — основная ветка есть, но есть непокрытые состояния/риски; `BROKEN` — подтверждённая ошибка; `REPORTED` — не перепроверено в этом snapshot.

## Главы

| Глава | Название | Entry | Основной экран | Ключевой результат | Статус |
|---|---|---|---|---|---|
| 1 | Знакомство | `/demo` | cinematic welcome | имя, класс, цель, init | IMPLEMENTED |
| 2 | Учебная база | `/dashboard` | реальный student dashboard | 3 discovery actions и первое испытание | IMPLEMENTED |
| 3 | Первое испытание | `/task-workspace` | реальный workspace | ответ `5` или code branch | IMPLEMENTED |
| 4 | Секретная библиотека | `/theory...` | реальная теория | открыть материал и понять принцип | IMPLEMENTED |
| 5 | Ошибаться — нормально | `/submissions` → `/task-workspace` | review + retry submission | исправить ответ и отправить `5` | PARTIAL |
| 6 | Твой маршрут | `/courses...` | course/catalog | открыть курс и модуль | IMPLEMENTED |
| 7 | Маленькие победы | analytics | student analytics | открыть прогресс | IMPLEMENTED |
| 8 | Ритм занятий | `/schedule` | schedule | показать неделю | IMPLEMENTED |
| 9 | Профиль ученика | `/workspace/profile` | profile | показать достижения | IMPLEMENTED |
| 10 | Финал | Experience Layer | finale CTA | заявка на вводный урок | PARTIAL |

### Глава 1 — Знакомство

- **Цель:** объяснить формат и собрать минимальный контекст.
- **Entry:** `/demo`, state `chapter_1/welcome`.
- **Реплики:** «О! Кажется, у нас гость!», приветствие Бу, вопрос о цели.
- **Действия:** выбрать один из трёх ответов, продолжить, ввести имя, выбрать класс, выбрать цель.
- **CTA:** `Guided demo с Бу` или свободный просмотр.
- **Events/state:** `/demo/api/init`, choice event, `chapter_1 → chapter_2`.
- **Completion:** demo user, Student, dataset и session state созданы.
- **Alternative:** пустое имя блокирует переход; exploratory choices дают реакцию Бу.
- **Фактический статус:** IMPLEMENTED. Текущий визуальный custom grade select — часть рабочей копии.

### Глава 2 — Учебная база

- **Entry:** `/dashboard`, `dashboard_intro/chapter2_mission`.
- **Цель:** показать, что демо использует настоящую учебную базу.
- **Порядок:** открыть программу → открыть курс → показать модуль → вернуться; открыть прошедший урок → вернуться; открыть карточку работ.
- **Реплики:** Бу объясняет маршрут, реальный курс, прошедший урок и раздел работ.
- **Events:** `demo:chapter2:started`, `demo:dashboard:program_explored`, `demo:dashboard:lesson_explored`, `demo:dashboard:assignments_explored`, `demo:chapter2:module_opened`, `demo:chapter2:trial_discovered`.
- **Completion:** все три discovery branches и доступно первое испытание.
- **Alternative:** detour actions сохраняются, но не меняют canonical route.
- **Статус:** IMPLEMENTED.

### Глава 3 — Первое испытание

- **Entry:** task workspace, `trial_intro/trial_input`.
- **Задача:** проследить `score = 0` по пяти командам `UP, UP, RIGHT, DOWN, RIGHT`; правильный результат `5`.
- **Режимы:** `Ответ` и `Код`. Кодовая мини-задача использует `marks = [3, 1, 4, 1, 5]`, ожидаемый результат `12`.
- **Events:** `demo:trial:opened`, `demo:chapter3:mode_prompted`, `trial_completed`.
- **Wrong path:** `trial_retry`, подсказка про `DOWN`, повторная попытка без штрафа; после повторной ошибки — переход к работе над ошибками.
- **Correct path:** `victory`, achievement `first_step`, просмотр решения.
- **Статус:** IMPLEMENTED; фактическая browser-проверка полного пути имеет отдельный 409 telemetry blocker.

### Глава 4 — Секретная библиотека

- **Entry:** `library_intro/chapter_4`.
- **Action:** открыть theory material.
- **Реплика:** теория показывает принцип и трассировку, а не только число.
- **Event:** `demo:library:material_opened`.
- **Completion:** переход в `mistakes_intro`.
- **Статус:** IMPLEMENTED.

### Глава 5 — Работа над ошибками

- **Entry:** `/submissions`, `mistakes_intro/chapter_5`.
- **Action:** открыть разбор ошибки; увидеть комментарий наставника; перейти в отдельный retry submission.
- **Retry:** переключиться в режим `Ответ`, ввести `5`, нажать `Отправить ответ`.
- **Events:** `demo:mistakes:review_opened`, `demo:mistakes:corrected`.
- **Completion:** retry submission получает `GRADED`, state получает `mistakes_fixed`, затем переход к аналитике.
- **Important state:** исходная ошибочная работа остаётся graded/read-only; для исправления используется отдельный `DEMO_RETRY_TITLE = 'Исправление: след по алгоритму'`.
- **Known risk:** старый URL исходной submission (`context_id` вроде 2500) закономерно read-only; guided CTA обязан вести на retry id из session state. Подсветка retry была недавно усилена, но полный manual pass после snapshot не подтверждён.
- **Статус:** PARTIAL.

### Глава 6 — Персональный маршрут

- **Entry:** route intro, catalogue/course page.
- **Actions:** открыть курс, открыть модуль, не уходить в lesson.
- **Event:** `demo:route:module_opened`.
- **Completion:** route module открыт; следующий шаг — analytics.
- **Статус:** IMPLEMENTED.

### Глава 7 — Маленькие победы

- **Entry:** analytics intro.
- **Action:** открыть progress surface.
- **Event:** `demo:wins:analytics_opened`.
- **Completion:** показать, как lessons/tasks/attempts складываются в progress.
- **Статус:** IMPLEMENTED.

### Глава 8 — Ритм занятий

- **Entry:** `/schedule`, `schedule_intro`.
- **Actions:** показать неделю, затем продолжить к профилю.
- **Event:** `demo:schedule:week_opened`.
- **Статус:** IMPLEMENTED; schedule endpoint был исторически проблемным, см. known issues.

### Глава 9 — Профиль ученика

- **Entry:** `/workspace/profile`, `profile_intro`.
- **Action:** показать достижения.
- **Event:** `demo:profile:achievements_opened`.
- **Completion:** CTA `К финалу`.
- **Статус:** IMPLEMENTED.

### Глава 10 — Финал

- **Entry:** finale Experience Layer.
- **Message:** пользователь увидел цель, практику, поддержку и рост.
- **CTA:** заявка на вводный урок; альтернативы — тарифы и Telegram.
- **API:** `/demo/api/request`; создаётся или обновляется `CallRequest` с `source='demo_intro'`, `is_demo=True`.
- **Completion:** success response и persisted lead.
- **Статус:** PARTIAL: backend contract и pytest покрыты; full desktop/mobile release verdict не подтверждён из-за runtime 409 responses во время E2E.

## Canonical Happy Path

1. Открыть `/demo`.
2. Выбрать guided answer, нажать `Продолжить`.
3. Ввести имя, класс и цель; нажать `Guided demo с Бу`.
4. На `/dashboard` пройти programme → course → module → dashboard.
5. Открыть past lesson → room tour → dashboard.
6. Открыть assignments → первое испытание.
7. Выбрать `Ответ`, показать поле, ввести `5`, отправить.
8. Открыть решение и перейти в Chapter 4 theory.
9. Открыть material, затем submissions/review.
10. Открыть `Исправить ответ`, на retry ввести `5` и отправить.
11. Открыть analytics progress.
12. Открыть schedule week.
13. Открыть profile achievements.
14. Перейти к финалу.
15. Нажать `Оставить заявку на вводный урок`.
16. Заполнить имя, класс, цель, contact, date/time, consent.
17. Отправить и проверить persisted success.
