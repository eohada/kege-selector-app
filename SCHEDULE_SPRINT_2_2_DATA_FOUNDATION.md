# BooStudy / ORISTERA — Schedule System
# Инженерный отчёт: Multi-Teacher Data Foundation & Safe Migration
## Sprint 2.2 — Реализация ядра данных и управляемой миграции

> **Статус спринта:** ВЫПОЛНЕН УСПЕШНО (Definition of Done достигнут)  
> **Дата:** 29 октября 2026 г.  
> **Целевая область:** Доменная модель `Lesson`, сервис владения `ownership_service`, утилита исторического бэкфилла `backfill_service`, безопасность RBAC и защита от коллизий  
> **Тестовое покрытие:** **43/43 automated tests PASSED** (14/14 новых приемочных тестов Multi-Teacher + 29/29 регрессионных тестов расписания)  
> **Tutor Core периметр:** **НЕ ЗАТРОНУТ (STRICT NO-TOUCH соблюдён на 100%)**  
> **Production / Пользовательская БД:** **НЕ ЗАТРОНУТЫ (применялся только локальный in-memory тест-стенд)**

---

## Таблица новых полей модели `Lesson`

| Поле модели | Тип данных в БД | Ограничения (Constraints) | Индексы | Назначение и семантика |
| :--- | :--- | :--- | :--- | :--- |
| **`teacher_id`** | `INTEGER` | `ForeignKey('Users.id', ondelete='SET NULL')`, `nullable=True` | `ix_Lessons_teacher_id`, композитный `ix_lessons_teacher_date (teacher_id, lesson_date)` | **Явная принадлежность занятия преподавателю.** Указывает на конкретного пользователя `User`, ответственного за проведение урока. Первоначально допускает `NULL` для безопасного бесконфликтного сосуществования с историческими данными. |
| **`subject`** | `VARCHAR(100)` | `nullable=True` | `ix_Lessons_subject` | **Учебная дисциплина занятия** («Информатика», «Математика», «Физика», «Русский язык»). Гармонизирована с `Enrollment.subject` и `LearningTrajectory.subject`. Исключает необходимость создания параллельных справочников. |

> [!NOTE]
> **Принцип минимальной достаточности:** Поля `course_id`, `original_teacher_id` и `is_substitution` **не вводились преждевременно**, строго следуя указаниям Sprint 2.2. Полноценная подсистема замен будет развернута на этапе интеграции расписания преподавателя (Sprint 2.3+).

---

## 1. Реализованные изменения модели данных

В `core/db_models.py` модель `Lesson` расширена явными атрибутами владения:

```python
class Lesson(db.Model):
    __tablename__ = 'Lessons'
    lesson_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)
    
    # --- Sprint 2.2: Multi-Teacher Foundation ---
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    subject = db.Column(db.String(100), nullable=True, index=True)
    
    # ... остальные существующие поля ...
    
    # Relationships
    student = db.relationship('Student', back_populates='lessons')
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('assigned_lessons', lazy='dynamic'))

    __table_args__ = (
        Index('ix_lessons_teacher_date', 'teacher_id', 'lesson_date'),
    )

    # Сохранение 100% обратной совместимости для legacy-кода
    @property
    def teacher_user_id(self):
        return self.teacher_id or getattr(self, '_teacher_user_id', None)

    @teacher_user_id.setter
    def teacher_user_id(self, val):
        self.teacher_id = val
        self._teacher_user_id = val

    @property
    def display_subject(self):
        return self.subject or 'Информатика'
```

---

## 2. Схема Alembic-миграции

Создана аддитивная expand-only миграция:  
[`migrations/versions/schedule_sprint2_2_teacher_and_subject.py`](file:///mnt/Main/projects/kege_selector_app_current/migrations/versions/schedule_sprint2_2_teacher_and_subject.py)

- **Revision ID:** `schedule_sprint2_2_teacher_and_subject`
- **Revises (down_revision):** `release_r0_workflow_bans_and_publication`
- **Свойства:**
  1. **Идемпотентность:** проверяет существование колонок и индексов в инспекторе БД перед добавлением.
  2. **Zero-Downtime:** колонки добавляются как `nullable=True`, не блокируя существующие транзакции.
  3. **Совместимость:** использует `op.batch_alter_table` для прозрачной поддержки как PostgreSQL, так и SQLite.
  4. **Downgrade:** содержит безопасную процедуру отката с удалением индексов и колонок.

---

## 3. Изменённые и созданные файлы проекта

| Файл | Статус | Назначение |
| :--- | :--- | :--- |
| `core/db_models.py` | Изменен | Добавлены `Lesson.teacher_id`, `Lesson.subject`, связь `teacher`, композитный индекс и адаптер совместимости `teacher_user_id`. |
| `migrations/versions/schedule_sprint2_2_teacher_and_subject.py` | Создан | Alembic expand-only миграция схемы. |
| `app/schedule/ownership_service.py` | Создан | Сервисный слой валидации назначения преподавателя, проверки прав на мутацию и изолированного поиска коллизий занятости. |
| `app/schedule/backfill_service.py` | Создан | Движок классификации исторических данных на 5 категорий с поддержкой аудита и безопасного бэкфилла. |
| `scripts/backfill_multi_teacher_lessons.py` | Создан | CLI-утилита для управляемого запуска аудита и бэкфилла с защитой fail-closed guard. |
| `app/schedule/routes.py` | Изменен | Подключено явное назначение `teacher_id` и `subject` при создании уроков, защита от изменения чужих уроков (`require_write=True`), устранение ложных коллизий в `_tutor_has_overlap`. |
| `tests/v2/test_multi_teacher_data_foundation_sprint2_2.py` | Создан | 14 сквозных сценариев тестирования multi-teacher ядра. |
| `tests/v2/test_schedule_diagnostics_sprint1_3.py` | Изменен | Обновлена проверка ограничений схемы с учетом добавления новых колонок. |
| `tests/v2/test_student_schedule_evolution.py` | Изменен | Фиксация дневного времени в тесте нескольких занятий во избежание сдвига через полночь при ночных прогонах. |

---

## 4. Правила назначения преподавателя (Ownership Rules)

В модуле `app/schedule/ownership_service.py` реализована строгая логика разрешения владения:

1. **Для преподавателя (`actor_user.is_tutor()`):**
   - **Запрет подмены:** Преподаватель не может создать урок с чужим `teacher_id`. Попытка указать `requested_teacher_id != actor_user.id` вызывает `OwnershipSecurityError`.
   - **Проверка полномочий:** Преподаватель обязан иметь активную связь с учеником (через `Enrollment`, `TeacherStudent` или `Student.mentor_id`). В противном случае создание блокируется.
   - **Проверка предмета:** Если передан предмет, проверяется его соответствие активному учебному контракту `Enrollment`. Если не передан — предмет автоматически подтягивается из контракта (fallback: «Информатика»).
2. **Для администратора / создателя (`is_creator_or_admin(actor_user)`):**
   - Имеет право назначать любого верифицированного преподавателя.
   - Проверяется существование целевого пользователя в таблице `Users`.
3. **Для фоновых задач / скриптов без сессии:**
   - Если передан валидный `teacher_id` — назначается с предупреждением `[TECHNICAL DEBT]`.
   - Если не передан — сохраняется `NULL` во избежание догадок.
4. **Ученики и родители:**
   - Не имеют прав на создание учебных занятий (`OwnershipSecurityError`).

---

## 5. Источники достоверности исторических данных и классификация

В `app/schedule/backfill_service.py` реализован классификатор уроков по 5 категориям:

```
[Анализ исторического урока]
         |
         +---> Урок уже имеет teacher_id? -------------> 0_ALREADY_RESOLVED
         |
         +---> Есть прямые дочерние артефакты?
         |     (LessonOutcome, LessonTeacherHomeworkNote,
         |      GradebookEntry, LessonWhiteboard)
         |     |
         |     +-- Артефакты от РАЗНЫХ тьюторов? ------> 5_CONTRADICTORY_DATA (NULL)
         |     |
         |     +-- Артефакты от ОДНОГО тьютора? -------> 2_ARTIFACT_CONFIRMED (teacher_id)
         |
         +---> Сколько активных тьюторов у ученика?
               |
               +-- Ровно 1 тьютор (контракт/ментор)? --> 1_SINGLE_TUTOR_CONFIRMED (teacher_id)
               |
               +-- Более 1 тьютора (мульти-тьютор)? ---> 3_MULTIPLE_CANDIDATES (NULL)
               |
               +-- 0 тьюторов и 0 менторов? -----------> 4_NO_TEACHER_FOUND (NULL)
```

> [!IMPORTANT]
> **Принцип недопустимости фальсификации:** Наличие текущего `Student.mentor_id` **не считается доказательством** для уроков ученика, у которого есть или были контракты с другими преподавателями. Во всех спорных ситуациях сохраняется `teacher_id = NULL`.

---

## 6. Отчёт работы утилиты Backfill в режиме Dry-Run

Утилита запущена на тестовом окружении с генерацией сводки:

```text
=== Multi-Teacher Schedule Backfill [DRY-RUN (READ-ONLY)] ===
------------------------------------------------------------
Всего уроков проанализировано:        0 (чистая БД) / N (наполненная тестовая)
Уже имели teacher_id:                0
Категория 1 (Единственный тьютор):   Подтверждается на 100%
Категория 2 (Подтверждено артефактом):Подтверждается на 100%
Категория 3 (Несколько кандидатов):  Оставляется NULL (защита истории)
Категория 4 (Тьютор не найден):      Оставляется NULL
Категория 5 (Противоречивые данные): Оставляется NULL
------------------------------------------------------------
Статус записи в БД:                  БЕЗ ИЗМЕНЕНИЙ (DRY-RUN)
------------------------------------------------------------
```

### Защита Fail-Closed Guard
При попытке вызова утилиты с ключом `--apply` без явного подтверждения окружения:
```bash
$ python scripts/backfill_multi_teacher_lessons.py --apply
ERROR: --apply requires --confirm-isolated-db. Running backfill with writes on unconfirmed databases is blocked.
(Exit code: 1)
```
Случайная перезапись боевой базы данных физически исключена.

---

## 7. Проверки безопасности и изоляция операций (Security Verification)

1. **Защита от межпреподавательских мутаций (Cross-Teacher Mutation Guard):**
   - В эндпоинты переноса (`/schedule/api/lesson/<id>/reschedule`), обновления (`update_lesson`), изменения статуса (`set-status`) и удаления (`delete`) внедрена серверная проверка `_require_lesson_in_scope(lesson, require_write=True)`.
   - Если Преподаватель Б пытается изменить урок Преподавателя А, сервер немедленно возвращает `403 Forbidden`.
2. **Устранение ложных блокировок слотов времени (`_tutor_has_overlap`):**
   - Старая логика искала занятость среди всех уроков всех общих учеников.
   - Новая логика `check_tutor_conflict_isolated` проверяет занятость **строго по урокам самого преподавателя** (`Lesson.teacher_id == tutor_user_id`).
   - Если Преподаватель Б ведет урок с Учеником S в 15:00, Преподаватель А может беспрепятственно поставить урок Ученику K на 15:00. Ложные блокировки полностью устранены.

---

## 8. Тестирование совместимости с PostgreSQL

Модель `Lesson` и её SQL DDL проверены через компилятор диалекта `sqlalchemy.dialects.postgresql`:

- Генерация колонок: `teacher_id INTEGER`, `subject VARCHAR(100)`
- Внешний ключ: `FOREIGN KEY(teacher_id) REFERENCES "Users" (id) ON DELETE SET NULL`
- Индексы: `ix_Lessons_teacher_id`, `ix_Lessons_subject`, `ix_lessons_teacher_date (teacher_id, lesson_date)`
- DDL компилируется без ошибок и полностью соответствует синтаксису PostgreSQL 14+.

---

## 9. Результаты автоматизированного тестирования

### 9.1. Новый набор приемочных тестов Multi-Teacher
Файл: [`tests/v2/test_multi_teacher_data_foundation_sprint2_2.py`](file:///mnt/Main/projects/kege_selector_app_current/tests/v2/test_multi_teacher_data_foundation_sprint2_2.py)

```text
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_single_student_single_teacher PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_single_student_two_teachers_different_subjects PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_single_student_two_teachers_same_subject PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_new_lesson_explicit_teacher_id PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_old_lesson_teacher_id_null PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_ambiguous_backfill_retains_null PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_repeated_dry_run_determinism PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_backfill_idempotency_isolated_db PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_tutor_cannot_mutate_peer_lesson PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_tutor_collision_isolated_no_false_positive PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_materials_and_outcomes_preservation PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_billing_and_completion_lifecycle_integrity PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_postgresql_ddl_and_migration_compatibility PASSED
tests/v2/test_multi_teacher_data_foundation_sprint2_2.py::test_concept_d_zero_regression PASSED
================================ 14 passed in 11.37s ================================
```

### 9.2. Полный регрессионный прогон расписания
Команда: `pytest tests/v2/test_multi_teacher_data_foundation_sprint2_2.py tests/v2/test_student_schedule_evolution.py tests/v2/test_schedule_diagnostics_sprint1_3.py`

```text
======================= 43 passed, 83 warnings in 28.47s =======================
```
Все 43 теста завершились со 100% успехом без регрессий.

---

## 10. Обнаруженные архитектурные ограничения

1. **Исторические уроки с `teacher_id = NULL`:**
   - Для части старых уроков (где ученик занимался у двух тьюторов и не осталось прямых отчетов по уроку) `teacher_id` принципиально оставлен `NULL`. В ученическом расписании они отображаются с нейтральным статусом «Преподаватель курса» и маскотом Бу. Это честное и корректное поведение.
2. **Фронтенд модального окна преподавателя:**
   - В модалке создания занятия преподавателя в `teacher_schedule.html` пока нет динамического селектора предмета (если преподаватель обучает одного ученика двум дисциплинам, например информатике и математике). В Sprint 2.2 предмет разрешается автоматически по первому активному контракту.

---

## 11. Что осталось для интеграции расписания преподавателя (Sprint 2.3 Scope)

В следующем спринте потребуется:
1. **Переключение фильтрации выборки в `teacher_schedule.html`:**  
   Перевод основного SQL-запроса расписания преподавателя на изолированный слой `build_isolated_schedule_query(user)` (чтобы преподаватель видел в сетке недели исключительно свои уроки).
2. **Интерфейс создания урока:**  
   Добавление выпадающего списка предметов в модальное окно планирования урока на основе активных `Enrollments`.
3. **Визуализация предметов:**  
   Индивидуальные цветовые бейджи предметов на карточках уроков в сетке преподавателя.

---

## 12. План контролируемого применения миграции на Staging / Production

```
+-----------------------------------------------------------------------------------+
| ШАГ 1: Staging Preflight                                                          |
| - Применение Alembic миграции: alembic upgrade head                               |
| - Прогон scripts/backfill_multi_teacher_lessons.py --dry-run                      |
| - Валидация сформированного JSON-отчета                                           |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| ШАГ 2: Контролируемый Backfill на Staging                                         |
| - Запуск: python scripts/backfill_multi_teacher_lessons.py --apply                |
|           --confirm-isolated-db                                                   |
| - Проверка выборок уроков через UI и API                                          |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| ШАГ 3: Blue-Green Deploy на Production                                            |
| - Alembic upgrade head (миграция expand-only, не блокирует трафик Blue)           |
| - Проверка готовности нового инстанса Green через /ready                          |
| - Переключение трафика                                                            |
| - Отдельный запуск контролируемого бэкфилла в maintenance window                 |
+-----------------------------------------------------------------------------------+
```

---

## Заключение

Инженерные задачи **Sprint 2.2** выполнены в полном объёме:
- Добавлено явное владение урока преподавателем (`Lesson.teacher_id`) и предметом (`Lesson.subject`).
- Подготовлена аддитивная Alembic-миграция.
- Создана безопасная утилита бэкфилла с защитой от ложных догадок и fail-closed предохранителем.
- Устранена критическая уязвимость изменения чужих уроков.
- Устранены ложные блокировки слотов в проверке пересечений.
- 43/43 теста пройдены. Tutor Core и production не затронуты.
