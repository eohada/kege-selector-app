# BooStudy — Student Schedule
## Sprint 2.0.1: Real Data Integrity & Acceptance Gate

> **Статус спринта:** Инженерная приёмка завершена успешно  
> **Дата:** 29 октября 2026 г.  
> **Целевой маршрут:** `/schedule` (`templates/sandbox/student_schedule.html`, `app/schedule/routes.py`)  
> **Тестовое покрытие:** 29/29 automated unit & regression tests PASSED, 100% Playwright acceptance criteria met  
> **Каталог ключевых скриншотов:** `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/`

---

## 1. Матрица происхождения данных (Data Lineage Matrix)

| Сущность | Модель БД / Источник | Ключевые поля БД | Обработка в `app/schedule/routes.py` | Поле в `schedule_page_data` | Элемент DOM / UI |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Lesson (Занятие)** | `core.db_models.Lesson` | `lesson_id`, `student_id`, `lesson_date`, `duration`, `status`, `topic`, `notes`, `student_notes`, `materials` | Загрузка с `joinedload(Lesson.student)`, фильтрация по `student_id` и SQL-окну недели (+/- 2 дня для таймзон), конвертация даты в `lesson_storage_to_local(timezone)` | `weekdays[day_idx].events[].id`, `.title`, `.subtitle`, `.time_str`, `.status` | `.peer-event-card`, `.unified-day-tab`, `#unified-events-grid` |
| **Teacher (Преподаватель)** | `core.db_models.User`, `Student.mentor_id`, `Enrollment.tutor_id` | `Users.id`, `username`, `full_name`, `avatar_url`, `role` | Аудит ментора и всех активных `Enrollments`: если преподаватель ровно один — отображается его имя; если у ученика 2+ преподавателей по разным предметам — честный нейтральный fallback | `event.teacher.name`, `event.teacher.full_name`, `event.teacher.avatar` | Блок карточки урока: `.peer-event-card img`, `.peer-event-card .text-xs.font-black` |
| **Assignment / Submission (Дедлайн)** | `app.models.Assignment`, `app.models.Submission` | `Assignment.assignment_id`, `deadline`, `title`, `Submission.student_id`, `status` | Join `Submission` с `Assignment`, дедупликация по `assignment_id`, перевод `deadline` в локальный часовой пояс ученика, сопоставление со днем недели | `active_homework[]`, `weekdays[day_idx].events[].type == 'homework'` | Компактная плашка дедлайна в блоке дня: `[ДЗ сдано]`, `[В процессе]`, `[На доработке]`, `[Домашнее задание]` |
| **Материалы занятия** | `Lesson.materials` (JSON) | `materials` (список словарей: `title`, `url`, `pages`) | **Строгая изоляция:** извлекаются исключительно материалы конкретного урока `l.materials`. Полностью исключена утечка `useful_materials[:2]` между уроками | `event.materials[]` | Блок «Материалы к уроку» внутри карточки конкретного занятия (скрыт, если у урока нет материалов) |
| **Общие материалы** | `schedule_page_data.useful_materials` | Темы уроков + база знаний | Формируются для общего виджета повторения и самоподготовки ученика | `sp_data.useful_materials[]` | Глобальный виджет полезных материалов |
| **Заметки преподавателя** | `Lesson.student_notes`, `Lesson.notes` | `student_notes`, `notes` (Text) | Текст заметки изолирован для карточки урока; разделен с объективным описанием формата занятия (`description`) | `event.notes`, `event.student_notes` | Желтый блок «Совет преподавателя:» (рендерится только при непустом значении) |
| **Стрик (Серия занятий)** | `Student.streak_days`, `last_activity_date` | `streak_days` (Int), `last_activity_date` (Date) | Расчет через `app.utils.streak_service.get_effective_streak(student)`. Фиктивный хардкод `5` удален! При 0 дней отображается ободряющий нейтральный статус | `weekly_stats.streak_days` | Бейдж в нижней полосе ритма: `<i class="ph-flame"></i> N дн. ударный темп` |

---

## 2. Подтверждённые дефекты и исправления

### Дефект 1: Межуроковая утечка материалов (Cross-Lesson Material Leakage)
- **Что было:** В `app/schedule/routes.py` в словарь каждого урока жестко прописывалось `'materials': useful_materials[:2] if useful_materials else []`. В результате материалы одного урока или общие темы курса клонировались во все уроки недели, даже если у них не было никаких материалов.
- **Причина:** Временная подстановка из Sprint 2.0 для наполнения карточки Concept D.
- **Исправление:** Теперь `event['materials']` формируется строго из `l.get('materials')`. Если у урока нет прикрепленных материалов, поле равно `[]`, а интерфейс не показывает блок «Материалы к уроку». Общие материалы передаются только на верхний уровень в `schedule_page_data['useful_materials']`.

### Дефект 2: Ложная атрибуция ментора при нескольких преподавателях
- **Что было:** Карточка любого урока безусловно брала имя из `Student.mentor_id`. Если ученик занимался у двух разных преподавателей (например, Иван — информатика, Елена — математика), уроки математики ложно подписывались именем Ивана.
- **Причина:** Отсутствие поля `teacher_id` в таблице `Lesson` и глобальное присвоение `teacher_name = st_obj.mentor`.
- **Исправление:** Введен механизм обнаружения мульти-тьюторства через `Student.mentor_id` и `Enrollment.tutor_id`. При наличии более 1 преподавателя система не приписывает произвольного учителя, а выводит честный нейтральный статус `Преподаватель курса`.

### Дефект 3: Фиктивный захардкоженный стрик `streak_days: 5`
- **Что было:** В коде присутствовала строчка `if 'streak_days' not in weekly_stats: weekly_stats['streak_days'] = 5`, а в шаблоне `stats.streak_days|default(5)`. Ученики без активности видели ложный «5 дн. ударный темп».
- **Причина:** Заглушка из первоначального дизайн-макета.
- **Исправление:** Подключен `get_effective_streak()` из `app.utils.streak_service`. Стрик берется достоверно из БД. При значении 0 пламя скрывается и показывается честная нейтральная плашка «Новая серия занятий».

### Дефект 4: Скрытые legacy-контейнеры и фиктивные якоря для тестов
- **Что было:** В `student_schedule.html` присутствовали невидимые блоки `#hero-focus-card`, `#svg-stations-container`, `#daily-agenda-col`, сохраненные исключительно ради старых тестов.
- **Причина:** Страх сломать старые тесты при переходе на Concept D.
- **Исправление:** Все тесты в `tests/v2/test_student_schedule_evolution.py` переведены на реальные DOM-селекторы Concept D (`#unified-ribbon-track`, `#unified-day-workspace`, `#unified-events-grid`). Мертвые теги удалены из шаблона.

---

## 3. Неподдерживаемые сценарии (Multi-Teacher Gap Analysis)

### Что текущая схема данных позволяет показать достоверно:
1. Если у ученика ровно один преподаватель (через `mentor_id` или `Enrollment`) — этот преподаватель достоверно атрибутируется карточкам.
2. Факт того, что у ученика несколько преподавателей по разным направлениям (`len(student_tutors_map) > 1`).
3. При мульти-тьюторстве система гарантирует **отсутствие ложной атрибуции**: уроки не приписываются чужому учителю, карточка показывает `Преподаватель курса`.

### Что показать невозможно БЕЗ миграции `Lesson`:
1. **Точная привязка конкретного урока к конкретному преподавателю в multi-teacher режиме:** так как в таблице `Lessons` физически отсутствуют колонки `teacher_id`, `tutor_id` и `course_id`, система не может на уровне SQL/ORM определить, кто именно вел данный урок, если их больше одного.
2. **Предмет урока в БД:** урок хранит только текстовую тему `topic`, а поле `subject` сейчас по умолчанию выводится как «Информатика» (основной профиль платформы).

### Принятые компромиссы:
- До проведения схемы миграции базы данных в Sprint 2.1 в спорных ситуациях используется честный нейтральный fallback `Преподаватель курса` с системным аватаром.

---

## 4. Результаты тестового прогона

### Automated Unit & Regression Tests (Pytest)
Команда:
`BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_student_schedule_evolution.py tests/v2/test_schedule_diagnostics_sprint1_3.py`

**Итог: 29 passed, 0 failed, 0 errors (время: 19.52s)**

Ключевые проверенные тесты:
- `test_student_schedule_page_structure_and_no_mocks` — PASSED (реальная структура Concept D, отсутствие моков)
- `test_student_schedule_real_lesson_and_rbac` — PASSED (изоляция данных между учениками)
- `test_student_schedule_week_navigation` — PASSED (навигация по неделям)
- `test_student_schedule_data_contract_fields` — PASSED (структура JSON-контракта)
- `test_student_schedule_empty_week_state` — PASSED (чистое состояние каникул, 0% прогресса)
- `test_student_schedule_neutral_teacher_fallback` — PASSED (корректный fallback без ментора)
- `test_multi_teacher_isolation_scenario` — **PASSED (новый тест Sprint 2.0.1: защита от ложной атрибуции)**
- `test_materials_and_notes_strict_isolation` — **PASSED (новый тест Sprint 2.0.1: отсутствие утечки материалов)**
- `test_real_streak_integrity_and_no_fictitious_fallback` — **PASSED (новый тест Sprint 2.0.1: достоверный стрик)**
- `test_cancelled_lesson_excluded_from_completion_base` — **PASSED (новый тест Sprint 2.0.1: математика отмен)**

### E2E Acceptance Suite (Playwright Chromium)
Скрипт: `scripts/diagnostics_sprint2_0_1_integrity.py`

```json
{
  "acceptance_criteria": {
    "single_teacher_attributed_correctly": true,
    "multi_teacher_neutral_fallback": true,
    "materials_isolated_without_leakage": true,
    "notes_isolated_without_leakage": true,
    "cancelled_lesson_badge_rendered": true,
    "cancelled_lesson_excluded_from_base": true,
    "homework_lifecycle_statuses_accurate": true,
    "mobile_zero_horizontal_scroll": true,
    "empty_week_friendly_state": true
  }
}
```

---

## 5. Аудит legacy DOM-элементов

| Идентификатор элемента | Назначение в старом Weekscape | Статус в Sprint 2.0.1 | Действие |
| :--- | :--- | :--- | :--- |
| `#hero-focus-card` | Главная карточка фокуса старого спринта 1.5 | Мёртвый код (скрыт через `display:none`) | **Удален.** Тесты переведены на `#unified-ribbon-track` и `#unified-day-workspace`. |
| `#svg-stations-container` | Контейнер SVG-станций метро-карты | Мёртвый код | **Удален.** Тест переведен на Concept D DOM. |
| `#daily-agenda-col` | Колонка повестки дня | Мёртвый код | **Удален.** |
| `#daily-companion-col` | Колонка спутника/маскота | Мёртвый код | **Удален.** Заменен на `#unified-boo-coach-tip`. |
| `#useful-materials-card` | Скрытый список ссылок | Мёртвый код | **Удален.** |
| `#tutor-note-card` | Скрытый блок заметок | Мёртвый код | **Удален.** Заменен на `#unified-general-notes`. |

---

## 6. Проверка прав доступа (RBAC Access Matrix)

| Роль пользователя | Доступ к `/schedule` | Параметр `?student_id=X` | Поведение системы |
| :--- | :--- | :--- | :--- |
| **Гость (Anonymous)** | ❌ Запрещен | Любой | Редирект на `/auth/login` |
| **Ученик (Student A)** | ✅ Разрешен | Отсутствует | Видит строго свои уроки и дедлайны |
| **Ученик (Student A)** | ❌ Запрещен | `?student_id=B` (чужой) | **Блокировка:** `flash('Доступ запрещен.')`, автоматический редирект на свое расписание |
| **Преподаватель (Tutor)** | ✅ Разрешен | Свои ученики | Доступны только ученики из `Student.mentor_id == current_user.id` |
| **Администратор / Создатель** | ✅ Полный | Любой ученик | Доступен глобальный обзор всех учеников и фильтрация |

---

## 7. Формулы аналитики и метрик

```python
# 1. Занятия недели:
conducted = count(status in ['completed', 'done'])
planned   = count(status in ['planned', 'in_progress'])
cancelled = count(status in ['cancelled', 'canceled'])

# 2. База выполнения (отмененные занятия НЕ входят в знаменатель!):
completion_base = conducted + planned

# 3. Процент выполнения недели:
progress_percent = round((conducted / completion_base) * 100) if completion_base > 0 else 0

# 4. Дедлайны текущей недели:
week_homework = count(active_homework where week_start <= deadline_date <= week_end)

# 5. Стрик (ударный темп):
streak_days = get_effective_streak(student, today_date=today)
# Если ученик не занимался >= 2 дней и стрик не заморожен, streak_days = 0.
```

---

## 8. Архитектурные требования к будущей связке `Lesson -> Teacher` (Sprint 2.1)

Для полной поддержки мульти-тьюторства без эвристик и компромиссов в следующем спринте требуется:

### 1. Изменение схемы базы данных (`core/db_models.py`):
```python
class Lesson(db.Model):
    ...
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete='SET NULL'), nullable=True, index=True)
    
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('taught_lessons', lazy='dynamic'))
    course = db.relationship('Course', foreign_keys=[course_id], backref=db.backref('lessons', lazy='dynamic'))
```

### 2. Стратегия миграции существующих данных (Data Backfill):
1. **Для существующих записей `Lesson`:** выполнить SQL-миграцию:
   ```sql
   UPDATE "Lessons" 
   SET teacher_id = (SELECT mentor_id FROM "Students" WHERE "Students".student_id = "Lessons".student_id)
   WHERE teacher_id IS NULL;
   ```
2. **Для уроков в рамках курсов (`Enrollment`):** если у студента есть ровно один тьютор по предмету урока, заполнить `teacher_id = Enrollment.tutor_id`.

### 3. Обратная совместимость:
- Если `Lesson.teacher_id IS NULL`, сохранять fallback на `Student.mentor_id` или нейтральный `Преподаватель курса`.

---

## 9. Каталог ключевых скриншотов приёмки

Все скриншоты изолированы в специальной папке текущего спринта:  
`/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/`

1. **`01_single_teacher_assigned.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/01_single_teacher_assigned.png`  
   *Описание:* Ученик с одним назначенным тьютором. Карточка урока четко и корректно атрибутирует преподавателя («Иван Сергеевич»).

2. **`02_multi_teacher_neutral_fallback.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/02_multi_teacher_neutral_fallback.png`  
   *Описание:* Ученик занимается у двух преподавателей по разным предметам. Карточка урока честно отображает нейтральный статус «Преподаватель курса» без ложной атрибуции.

3. **`03_materials_and_notes_isolated.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/03_materials_and_notes_isolated.png`  
   *Описание:* Строгая изоляция материалов и заметок. Урок А содержит свой прикрепленный PDF и совет учителя; урок Б чист и не содержит чужих материалов.

4. **`04_cancelled_and_completed_semantics.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/04_cancelled_and_completed_semantics.png`  
   *Описание:* Отмененный урок отмечен сдержанным бейджем «Отменено», не штрафует ученика и исключен из базы прогресса (прогресс ровно 50%).

5. **`05_homework_lifecycle_statuses.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/05_homework_lifecycle_statuses.png`  
   *Описание:* Жизненный цикл домашних заданий с понятными статусами: «Домашнее задание», «В процессе», «На доработке», «ДЗ сдано».

6. **`06_mobile_390x844_first_screen.png`**  
   `/mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint2_0_1_screenshots/key_review/06_mobile_390x844_first_screen.png`  
   *Описание:* Мобильный вид (iPhone 12/13/14, 390x844). Нулевой горизонтальный скролл, 7-дневный навигатор доступен, главный CTA первого урока виден на первом экране без скролла.
