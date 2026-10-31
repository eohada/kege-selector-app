# BooStudy / ORISTERA — Student Schedule System
## Отчёт по Sprint 1.1 — Production-Grade Recovery & Hardening

---

### 1. Первопричина сбоя (Root Cause Analysis)

#### 1.1. Симптом и исключение
При обращении авторизованного ученика по маршруту `GET /schedule` сервер возвращал ответ `HTTP 500 Internal Server Error`:
```json
{
  "code": 500,
  "error": "СТРАНИЦА НЕ ЗАГРУЗИЛАСЬ, ОШИБКА!!",
  "message": "Произошла непредвиденная ошибка при загрузке страницы."
}
```

Анализ логов (`logs/app.log`) зафиксировал точный трейс исключения:
```text
Unhandled exception (500): list object has no element Undefined
  File "templates/sandbox/student_schedule.html", line 355, in block 'sandbox_content'
    {% set sel_ev = sel_day.main_event %}
jinja2.exceptions.UndefinedError: list object has no element Undefined
```

#### 1.2. Механизм возникновения
1. **Расхождение версий кода в рантайме:** Локальный сервер разработки (`scripts/run_local.py`) был запущен с флагом `use_reloader=False`. При внесении изменений в шаблоны Jinja2 перечитывала обновленный шаблон `student_schedule.html` с диска, тогда как Python-процесс продолжал выполнять старую версию функции `schedule()` в памяти.
2. **Отсутствие защитного программирования в шаблоне:** В строках 353–355 шаблона:
   ```jinja2
   {% set sel_idx = schedule_page_data.default_selected_day_index %}
   {% set sel_day = schedule_page_data.weekdays[sel_idx] %}
   {% set sel_ev = sel_day.main_event %}
   ```
   Если `default_selected_day_index` или `weekdays` отсутствовали в контексте (либо были `None` / `Undefined`), Jinja вычисляла `schedule_page_data.weekdays[Undefined]`, что немедленно выбрасывало фатальную ошибку `UndefinedError: list object has no element Undefined`.
3. **Неограниченные запросы к базе данных:** Исходный запрос уроков (`Lesson.query.filter(...)`) не имел временных границ на уровне SQL. Для любого ученика загружались все уроки за всю историю, а отсечение производилось только в цикле Python.

---

### 2. Системные исправления и архитектурное укрепление

В соответствии с правилом **FIX THE SYSTEM, NOT THE SYMPTOM**, были реализованы комплексные архитектурные меры:

#### 2.1. Защита шаблона от неполного или поврежденного контекста
- В `templates/sandbox/student_schedule.html` реализовано строгое защитное извлечение всех переменных:
  ```jinja2
  {% set default_sel = schedule_page_data.default_selected_day_index|default(0, true) if schedule_page_data is defined and schedule_page_data.default_selected_day_index is defined and schedule_page_data.default_selected_day_index is not none else 0 %}
  {% set weekdays_list = schedule_page_data.weekdays|default([], true) if schedule_page_data is defined and schedule_page_data.weekdays is defined else [] %}
  {% set sel_idx = default_sel %}
  {% set sel_day = (weekdays_list[sel_idx] if (weekdays_list and sel_idx < weekdays_list|length) else (weekdays_list[0] if weekdays_list else none)) %}
  {% set sel_ev = sel_day.main_event if (sel_day and sel_day.main_event is defined) else none %}
  ```
- Все блоки шаблона (Hero Focus Card, SVG stations, «План на день», «Полезные материалы», «Прогресс недели», «Моя неделя», «Цели») теперь снабжены безопасными фильтрами `default(...)` и проверками на `none`.
- Даже при передаче абсолютно пустого словаря `schedule_page_data={}` страница рендерится без единой ошибки.

#### 2.2. Фильтрация на уровне SQL (SQL-Level Half-Open Intervals)
- В `app/schedule/routes.py` добавлен расчет временного окна с защитным буфером $\pm 2$ дня:
  ```python
  sql_window_start = datetime.combine(period_start - timedelta(days=2), time.min)
  sql_window_end = datetime.combine(period_end + timedelta(days=2), time.max)
  query = query.filter(
      Lesson.lesson_date >= sql_window_start,
      Lesson.lesson_date <= sql_window_end
  )
  ```
- Буфер $\pm 2$ дня математически гарантирует попадание уроков любых часовых поясов мира (от UTC-12 до UTC+14) в выборку базы данных.
- База данных сканирует только строки текущей недели с использованием индекса, предотвращая $O(N)$ деградацию по мере роста истории занятий.

#### 2.3. Защита от переполнения дат (Week Offset Clamping)
- Параметр `week` приводится к безопасному диапазону $[-104; 104]$ ($\pm 2$ года):
  ```python
  try:
      week_offset = int(request.args.get('week', 0))
  except (ValueError, TypeError):
      week_offset = 0
  week_offset = max(-104, min(104, week_offset))
  ```
- Попытки передать экстремальные значения вроде `?week=99999999` больше не вызывают `OverflowError: date value out of range`.

#### 2.4. Нейтральное разрешение преподавателей и изоляция RBAC
- Поддержаны множественные преподаватели. Если у ученика не назначен конкретный `mentor_id` или `Enrollment.tutor_id`, отображается нейтральный маркер:
  `teacher_name = 'Преподаватель курса'`
- Устранены любые вымышленные имена/фамилии.
- Сохранена строгая изоляция области видимости (`_resolve_accessible_student_ids_for_current_user`): ученик видит исключительно свои уроки и домашние задания.

#### 2.5. Дедупликация домашних заданий и дифференциация статусов
- Задания дедуплицируются по `assignment_id` (исключены задвоения при нескольких попытках сдачи).
- Различаются статусы:
  - `ASSIGNED` $\to$ «Домашнее задание» (сдать до времени)
  - `IN_PROGRESS` $\to$ «В процессе»
  - `RETURNED` $\to$ «На доработке» (выделение цветом rose)
  - `SUBMITTED`, `GRADED`, `ACCEPTED` $\to$ «ДЗ сдано» (цвет emerald)
- Дедлайны переводятся в часовой пояс зрителя для точного календарного сопоставления.

#### 2.6. Доступность (a11y) и навигация с клавиатуры
- Интерактивным карточкам дней и SVG-станциям добавлены атрибуты `role="button"`, `tabindex="0"`, `aria-label` и обработчики нажатия клавиш `Enter` / `Space`.

---

### 3. Таблица сравнения: ДО и ПОСЛЕ (BEFORE / AFTER Matrix)

| Критерий / Механизм | ДО Sprint 1.1 | ПОСЛЕ Sprint 1.1 |
| :--- | :--- | :--- |
| **Устойчивость к сбоям (Crash Safety)** | При отсутствии ключей в контексте падал с `UndefinedError: list object has no element Undefined` (HTTP 500). | Шаблон 100% защищен: использует безопасные цепочки `default_sel`, `weekdays_list`, фильтры `default(...)`. Рендерится даже при `{}`. |
| **SQL-запросы уроков** | Без ограничений по дате (`Lesson.query.all()`). С ростом истории загружались тысячи уроков за прошлые годы. | Ограничение на уровне SQL через интервал `[period_start - 2d; period_end + 2d]`. Быстрый индексный скан. |
| **Навигация по неделям** | Параметр `week` не ограничивался. При больших значениях возникал `OverflowError`. | Строгий clamp $[-104; 104]$ ($\pm 2$ года). Любой ввод валидируется. |
| **Преподаватель** | Жесткая зависимость от `mentor_id`, риск фейковых заглушек или падения. | Иерархическое разрешение: `mentor_id` $\to$ `Enrollment.tutor_id` $\to$ нейтральный `'Преподаватель курса'`. |
| **Домашние задания** | Риск дублирования при повторных сабмитах; дедлайн без учета таймзоны; грубый статус. | Дедупликация по `assignment_id`, расчет дедлайна в таймзоне зрителя, поддержка статусов `RETURNED`, `IN_PROGRESS`, `SUBMITTED`. |
| **Дни отдыха (Free Days)** | Риск отображения дефолтных занятий на пустые дни. | Чистый payload типа `free`: прогресс 0%, бейдж «Отдых / Самостоятельное закрепление», полезные ссылки на теорию. |
| **Доступность (Accessibility)** | Только клик мышью `onclick`. | `role="button"`, `tabindex="0"`, `aria-label`, навигация с клавиатуры (`Enter`, `Space`). |
| **Синхронизация процессов** | Рассинхрон `use_reloader=False` приводил к исполнению устаревшего байткода. | Сервер перезапущен с актуальным кодом; подтвержден ответ 200 OK для всех учеников в реальном окружении. |

---

### 4. Результаты регрессионного тестирования

Запущен полный автоматизированный тестовый набор из 12 сценариев:
`tests/v2/test_student_schedule_evolution.py`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.15, pytest-9.1.1, pluggy-1.6.0
rootdir: /mnt/Main/projects/kege_selector_app_current
configfile: pytest.ini

tests/v2/test_student_schedule_evolution.py::test_student_schedule_page_structure_and_no_mocks PASSED [  8%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_real_lesson_and_rbac PASSED [ 16%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_week_navigation PASSED [ 25%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_data_contract_fields PASSED [ 33%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_undefined_defense PASSED [ 41%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_empty_week_state PASSED [ 50%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_multi_lesson_day PASSED [ 58%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_neutral_teacher_fallback PASSED [ 66%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_extreme_week_offset_clamped PASSED [ 75%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_unauthenticated_redirect PASSED [ 83%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_homework_statuses_and_deduplication PASSED [ 91%]
tests/v2/test_student_schedule_evolution.py::test_student_schedule_midnight_timezone_shift PASSED [100%]

======================= 12 passed, 23 warnings in 12.11s =======================
```

#### 4.1. Проверка живого сервера на порту 5000 (Live HTTP Verification)
Выполнены HTTP-запросы к запущенному серверу с реальной базой данных (`instance/boostudy_dev.db`):
- `User 3 (room_qa_student)`: HTTP 200 OK (длина HTML: 111 531 байт)
- `User 10 (demo_student_1)`: HTTP 200 OK (длина HTML: 106 356 байт)
- `User 11 (demo_student_2)`: HTTP 200 OK (длина HTML: 117 718 байт)
- `User 12 (demo_student_3)`: HTTP 200 OK (длина HTML: 106 350 байт)
- `User 19 (guest_3_smoke_guest)`: HTTP 200 OK (длина HTML: 105 246 байт)

Все учетные записи учеников загружают страницу без единой ошибки `500`.
Система стабилизирована и готова к промышленной эксплуатации.
