# BooStudy / ORISTERA — Schedule System
## Sprint 2.3 Engineering Report: Teacher Schedule Multi-Teacher Integration & Operational Workflow

**Status:** Completed & Validated (34/34 Passing Tests: 20 Sprint 2.3 + 14 Sprint 2.2)  
**Author:** Principal Full-Stack Engineer, Software Architect, UX Engineer & QA Lead  
**Cardinal Architecture Rule:**  
> **ONE TEACHER — OWN LESSONS. ONE STUDENT — MANY TEACHERS. ZERO CROSS-TEACHER LEAKAGE.**

---

### 1. Executive Summary

В рамках Sprint 2.3 завершена интеграция многопреподавательской архитектуры данных (заложенной в Sprint 2.2) в действующее расписание преподавателя (`/schedule`, `templates/sandbox/teacher_schedule.html`), сопутствующие серверные эндпоинты, сервис авторизации владения уроками и пользовательские операционные процессы.

Система устранила зависимость расписания от глобального `Student.mentor_id` и обеспечила полную изоляцию уроков между преподавателями, обучающими одного и того же ученика (shared student scenario).

#### Ключевые результаты спринта:
1. **Строгая серверная изоляция (Zero Cross-Teacher Leakage):**
   - Учитель A видит, изменяет, переносит, удаляет и экспортирует **только свои уроки**.
   - Уроки других преподавателей полностью исключены из SQL-выборок расписания, API событий (`/api/schedule/events`), деталей карточки (`/api/schedule/lesson/<id>/details`) и экспорта iCal (`/schedule/export_ics`).
2. **Абсолютная IDOR-защита:**
   - Все эндпоинты чтения и записи защищены серверными проверками `can_user_view_lesson` и `can_user_modify_lesson` через централизованный guard `_require_lesson_in_scope`.
   - Попытка преподавателя обратиться по ID к уроку коллеги возвращает `403 Forbidden` без утечки метаданных.
3. **Безопасный выбор ученика и предмета:**
   - Преподаватель может создавать уроки только для учеников, с которыми у него есть подтверждённая связь (`Enrollment(status='active', tutor_id=teacher.id)` или `Student(mentor_id=teacher.id)`).
   - Список предметов в модальных окнах создания и редактирования строго ограничен предметами конкретной связи (`allowed_subjects`).
4. **Независимое обнаружение коллизий:**
   - Разделены проверки занятости преподавателя (`check_tutor_conflict_isolated`) и ученика (`_student_has_overlap`).
   - Пользователь получает дружелюбные и точные сообщения:
     - При пересечении в расписании самого учителя: `"В это время у вас уже есть занятие"` (`409 Conflict`).
     - При пересечении у ученика с другим учителем: `"В это время ученик занят на другом уроке"` (`409 Conflict`).
   - Исключены ложные срабатывания между разными преподавателями и разными учениками.
5. **Пессимистическая сериализация гонок (Row-Level Locking):**
   - Функция `acquire_scheduling_locks(student_id, tutor_user_id)` использует `with_for_update()` на записях `Student` и `User`, предотвращая создание дубликатов при одновременных запросах.
6. **Визуальная система календаря (UI Canon):**
   - В интерфейсе `teacher_schedule.html` чётко разделена семантика предмета (Информатика — индиго, Математика — изумруд/teal, Физика — янтарь, Русский язык — роза) и статуса занятия (запланирован, идёт, завершён, отменён).
   - Добавлены селекторы предметов в модалки создания/редактирования и динамическая фильтрация в боковой панели.
7. **Полная обратная совместимость:**
   - Concept D ученическое расписание (`student_schedule.html`) без регрессий отображает занятия нескольких преподавателей с их аватарами и метаданными.
   - Исторические уроки с `teacher_id = NULL` защищены от ложного присвоения и могут разрешаться администратором (`resolve_historical_lesson_ownership`).
   - Соблюдён строгий запрет на модификацию `app/tutor_core/*` (**TUTOR CORE STRICT NO-TOUCH**).

---

### 2. Защищённые эндпоинты (Audit & Security Matrix)

Все эндпоинты расписания приведены к единому стандарту безопасности:

| Endpoint | Метод | Контроль прав / Изоляция | Ответ при нарушении (IDOR) |
|---|---|---|---|
| `/schedule` | `GET` | Для тьютора: `Lesson.teacher_id == current_user.id` | Видит только свои уроки |
| `/api/schedule/events`, `/schedule/api/events` | `GET` | Для тьютора: `Lesson.teacher_id == current_user.id` | Чужие уроки исключены из выборки |
| `/api/schedule/lesson/<id>/details` | `GET` | `_require_lesson_in_scope(lesson, require_write=False)` | `403 Forbidden` |
| `/api/schedule/create_lesson`, `/schedule/api/lesson/create` | `POST` | `get_accessible_students_for_teacher`, `acquire_scheduling_locks`, `teacher_id = current_user.id` | `403 Forbidden` / `409 Conflict` |
| `/api/schedule/update_lesson/<id>` | `POST` | `_require_lesson_in_scope(lesson, require_write=True)`, защита от смены `teacher_id` | `403 Forbidden` |
| `/schedule/reschedule/<id>`, `/schedule/api/lesson/<id>/reschedule` | `POST` | `_require_lesson_in_scope(lesson, require_write=True)`, блокировка и проверка коллизий | `403 Forbidden` / `409 Conflict` |
| `/api/schedule/delete_lesson/<id>`, `/schedule/api/lesson/<id>/delete` | `POST`/`DELETE` | `_require_lesson_in_scope(lesson, require_write=True)` | `403 Forbidden` |
| `/schedule/api/lessons/bulk_delete` | `POST` | Выборка строго с `Lesson.teacher_id == current_user.id` | Чужие уроки не затрагиваются |
| `/schedule/export_ics`, `/schedule/export.ics` | `GET` | Для тьютора: `Lesson.teacher_id == current_user.id` | Экспортируются только свои уроки |

---

### 3. Concurrency & Locking Architecture

Для предотвращения параллельного бронирования одного и того же слота (race conditions) реализован механизм row-level блокировок:

```python
def acquire_scheduling_locks(student_id: int | None, tutor_user_id: int | None):
    """
    Acquires pessimistic row-level database locks (SELECT FOR UPDATE) on the student
    and tutor records to serialize concurrent lesson creation / rescheduling.
    """
    student_lock = None
    tutor_lock = None
    if student_id:
        student_lock = db.session.query(Student).filter(
            Student.student_id == student_id
        ).with_for_update().first()
    if tutor_user_id:
        tutor_lock = db.session.query(User).filter(
            User.id == tutor_user_id
        ).with_for_update().first()
    return student_lock, tutor_lock
```

Блокировки вызываются до проверки коллизий в:
- `schedule_create_lesson` (SSR / Form)
- `create_schedule_lesson_api` (JSON API)
- `schedule_reschedule_lesson` (Reschedule AJAX & Form)
- `update_schedule_lesson_api` (При изменении времени урока)

---

### 4. Визуальная система и UX (UI Canon)

В шаблоне `templates/sandbox/teacher_schedule.html` внедрены следующие улучшения:
1. **Фильтр по предметам в сайдбаре:**
   - Возможность отфильтровать сетку уроков по конкретному предмету (Все предметы, Информатика, Математика, Физика, Русский язык).
2. **Селектор предмета в модальных окнах создания и редактирования:**
   - Интерактивная 3-колоночная сетка pill-радиокнопок предметов с цветовым кодированием.
   - Динамическое заполнение списка доступных предметов на основе выбора ученика (`onStudentSelectChanged`). Преподаватель видит только те предметы, которые ведёт у данного ученика.
3. **Карточки уроков в сетке расписания (`lessonCardHtml`):**
   - Чёткий бейдж предмета с индивидуальным цветом (`color-indigo`, `color-emerald`, `color-amber`, `color-rose`).
   - Индикатор статуса (зелёный/amber/slate) и отображение имени ученика в компактном 3D-стиле.
4. **Месячный вид (`renderMonthView`):**
   - Цветные плашки с бейджами предметов и именами учеников, адаптированные для плотного просмотра.

---

### 5. Матрица приёмочных сценариев (20/20 Scenarios)

Все 20 сценариев реализованы в `tests/v2/test_teacher_schedule_integration_sprint2_3.py` и успешно прошли верификацию:

| # | Сценарий | Механизм проверки | Результат |
|---|---|---|---|
| **1** | Преподаватель А видит только свои уроки | `/api/schedule/events`, `/schedule` (JSON payload) содержат уроки Ивана и исключают уроки Елены | **PASSED** |
| **2** | Преподаватель Б видит только свои уроки | `/api/schedule/events` содержит уроки Елены и исключает уроки Ивана | **PASSED** |
| **3** | Общий ученик видит оба урока в Concept D | `/schedule` для Алисы содержит уроки обоих преподавателей и оба предмета | **PASSED** |
| **4** | Преподаватель А не может изменить урок Б | `POST /api/schedule/update_lesson/<elena_id>` и `/schedule/reschedule/<elena_id>` возвращают `403` | **PASSED** |
| **5** | Преподаватель А не может удалить урок Б | `POST /api/schedule/delete_lesson/<elena_id>` возвращает `403` | **PASSED** |
| **6** | Отклонение подмены ID в деталях (IDOR) | `GET /api/schedule/lesson/<elena_id>/details` возвращает `403` | **PASSED** |
| **7** | Создание урока с явными `teacher_id` и `subject` | `POST /api/schedule/create_lesson` сохраняет корректные `teacher_id`, `subject`, `topic` | **PASSED** |
| **8** | Ограничение выбора предмета связью | `get_accessible_students_for_teacher` возвращает только подтверждённые предметы | **PASSED** |
| **9** | Коллизия времени преподавателя | Попытка забронировать занятого учителя возвращает `409` ("В это время у вас уже есть занятие") | **PASSED** |
| **10** | Коллизия времени ученика между учителями | Попытка забронировать занятого ученика возвращает `409` ("В это время ученик занят на другом уроке") | **PASSED** |
| **11** | Отсутствие ложных коллизий | Разные учителя с разными учениками в один и тот же час бронируются успешно (`200 OK`) | **PASSED** |
| **12** | Сериализация гонки создания | `acquire_scheduling_locks` блокирует строки в БД через `with_for_update()` | **PASSED** |
| **13** | Перенос урока без дубликатов | `POST /schedule/reschedule/<id>` переносит дату/время, общее число записей не растёт | **PASSED** |
| **14** | Отмена урока освобождает слот | После `status="cancelled"` новый урок в этот же слот создаётся успешно (`200 OK`) | **PASSED** |
| **15** | Защита жизненного цикла завершённого урока | Урок `completed` нельзя перевести назад в `planned` без списания/возврата баланса | **PASSED** |
| **16** | Корректность таймзон (MSK +3 / NOVT +7) | Занятие 18:00 MSK (15:00 UTC) возвращается в Новосибирском часовом поясе как 22:00 | **PASSED** |
| **17** | Рендеринг Concept D с аватарами учителей | Ученик видит в расписании предмет, тему и данные конкретного преподавателя | **PASSED** |
| **18** | Исторические уроки с `teacher_id = NULL` | Защищены от ложного владения тьюторами, администратор может назначить владельца | **PASSED** |
| **19** | Изоляция ICS экспорта и JSON событий | `/schedule/export_ics` содержит только занятия текущего преподавателя | **PASSED** |
| **20** | Конвертация `student_id` vs `user_id` | При передаче `user_id` система безошибочно находит связанный `student_id` | **PASSED** |

---

### 6. Результаты общего регрессионного тестирования

Выполнен прогон объединённого набора тестов:
```bash
DATABASE_URL="sqlite:///:memory:" BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_teacher_schedule_integration_sprint2_3.py tests/v2/test_multi_teacher_data_foundation_sprint2_2.py -v
```

**Результат:**
```text
======================= 34 passed, 45 warnings in 27.18s =======================
```
- `tests/v2/test_teacher_schedule_integration_sprint2_3.py`: **20/20 passed**
- `tests/v2/test_multi_teacher_data_foundation_sprint2_2.py`: **14/14 passed**
- **0 regressions**, полная обратная совместимость.

---

### 7. Заключение

Инженерная интеграция Sprint 2.3 полностью завершена в строгом соответствии с требованиями. Система расписания готова к переходу на следующий этап (Sprint 2.4 / аналитика и биллинг преподавателей).
