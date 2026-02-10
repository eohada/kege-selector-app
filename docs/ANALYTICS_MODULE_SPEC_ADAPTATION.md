# Адаптация спецификации модуля аналитики BooStudy v2.0 под платформу

## 1. Что нужно адаптировать под нашу платформу

### 1.1 Имена таблиц и моделей

- В проекте таблица пользователей — **`Users`** (не `users`). Все FK должны ссылаться на `Users.id`, `Tasks.task_id`, `Submissions.submission_id`, `Students.student_id`.
- Модель задания в банке — **`Tasks`** (не `Task`), таблица `Tasks`.
- В коде движка везде использовать `Tasks`, а не `Task`.

### 1.2 Связь «задание → узел знаний»

- У **Tasks** нет поля `difficulty` (1–10) и нет прямой связи с KnowledgeNode.
- Есть **task_number** (1–27 для КЕГЭ) и связь с **Topic** (M2M через task_topics).
- **Рекомендация:** не добавлять в первую итерацию `task.difficulty`. Определять узел по **task_number** → маппинг из сида (task_number → node_code). Либо добавить в `Tasks` опциональное поле **knowledge_node_id** (FK на knowledge_nodes) и заполнять его при сиде/парсинге.
- Сложность задачи для формулы рейтинга брать из **KnowledgeNode.base_rating** (из JSON), а не из task.difficulty.

### 1.3 Кто «user» в аналитике

- В **Assignments** сдаёт **Student** (submission.student_id). У Student есть **user_id** (может быть NULL для «просто ученика» без входа).
- Вызов: **user_id = submission.student.user_id**. Если `user_id is None` — аналитику для этой сдачи не считаем (или логируем и пропускаем).
- В уроках (LessonTask) тоже ученик = lesson.student → student.user_id; если позже будем кормить аналитику из уроков — использовать тот же принцип.

### 1.4 Где вызывать `AnalyticsEngine.process_submission`

- **Сценарий 1 — авто-проверка при сдаче работы**  
  В `app/assignments/routes.py` в обработчике сдачи (submit): после цикла, где для каждого ответа вызывается `auto_grade_answer` и выставляется `answer.is_correct`, для каждого такого ответа вызвать:
  - `AnalyticsEngine.process_submission(user_id=submission.student.user_id, task_id=task.task_id, is_correct=answer.is_correct, time_spent_sec=None)`  
  только если `submission.student.user_id` не None и движок смог определить узел по заданию.
- **Сценарий 2 — ручная проверка учителем**  
  В `submission_grade_save`: после сохранения оценок/баллов по каждому ответу, для которых выставили `is_correct` (или score), вызвать `process_submission` с теми же параметрами (user_id из submission.student.user_id, task из answer.assignment_task.task, is_correct из answer.is_correct).
- **Время на задачу:** в текущей модели нет **time_spent_sec** на один Answer. Можно передавать `time_spent_sec=None`; при появлении в будущем поля «время на задачу» — просто пробросить его в вызов. Опционально: грубая оценка `(submission.submitted_at - submission.started_at).total_seconds() / len(assignment.tasks)` и передавать её (только для ориентира «угадывания»).

### 1.5 Модель данных: Subject / KnowledgeNode

- **Subject:** в спецификации — корень (Информатика, Математика). В нашей БД уже есть **Topic** с опциональным `subject_id`, но отдельной модели Subject нет. Добавляем **Subject** как в спецификации (slug, name); для КЕГЭ один предмет с slug `kege` (или `informatics`).
- **KnowledgeNode:** в спецификации есть **base_difficulty** (0.0–1.0), в JSON — **base_rating** (800, 900, …). Удобнее хранить **base_rating** в узле (как рейтинг «типичного задания» этой темы) и использовать его в формуле. Тогда:
  - либо добавляем в модель поле **base_rating** (Integer, например 800–2500) и в сиде заполняем из JSON;
  - либо оставляем base_difficulty и при сиде конвертируем: base_difficulty = (base_rating - 800) / 1600 (чтобы 800→0, 2400→1). Рекомендация: хранить **base_rating** в узле и в движке использовать его напрямую как task_rating при отсутствии у задачи своей сложности.
- **UserMastery:** таблица `user_mastery`; FK на `Users.id` и `knowledge_nodes.id`. Совместимо со спецификацией.
- **AnalyticsEvent:** в спецификации есть **submission_id** (FK на submissions). У нас Submission — это «вся работа»; один сабмишн — много Answer. Имеет смысл хранить в событии **submission_id** (опционально) и при желании **answer_id** (FK на Answers) для детального аудита. Имена таблиц: `Submissions`, `Answers` — в FK указать их.

### 1.6 Логика движка (AnalyticsEngine)

- Получение узла по заданию:
  - приоритет: у `Tasks` есть связь с узлом (например, `task.knowledge_node` или `task.knowledge_node_id` → KnowledgeNode);
  - fallback: по **task_number** из маппинга task_number → node_code (словарь из сида или запрос KnowledgeNode по code + subject_id).
- Не использовать `task.difficulty` (его нет). Сложность для формулы: **task_rating = node.base_rating** (если храним base_rating в узле) или 800 + node.base_difficulty * 1600.
- Импорты: `from core.db_models import ...` или `from app.models import db, Tasks, ...` в зависимости от того, где лежат модели (всё в core.db_models, реэкспорт в app.models).

### 1.7 Сид (матрица сложности)

- JSON с task_number, topic, node_code, base_rating, exam_points, complexity_tier — использовать как есть.
- Сид должен:
  1. Создать **Subject** (например, slug=`kege`, name=`Информатика (КЕГЭ)`).
  2. Создать **KnowledgeNode** для каждой строки (по node_code, без дублей), с **base_rating** из JSON (и при необходимости exam_points, name из topic).
  3. Связать **Tasks** с узлами: по **task_number** обновить у существующих Tasks поле knowledge_node_id (если добавили) или вести отдельную таблицу маппинга task_number → node_id для движка.
- Задачи 24–27 в КЕГЭ могут быть с разными весами (exam_points=2); в JSON это уже есть — заложить в сид и в прогноз балла.

---

## 2. Что улучшить / добавить

### 2.1 Уникальность и индексы

- **KnowledgeNode:** уникальный ключ (subject_id, code).
- **UserMastery:** составной PK (user_id, node_id) — уже в спецификации; индекс по (user_id) для быстрой выборки всех мастерств ученика.
- **AnalyticsEvent:** индекс (user_id, timestamp) и (node_id, timestamp) для отчётов и пересчёта.

### 2.2 Масштабируемость (как в микро-инструкции)

- Новый предмет (например, Математика): новый Subject + новый JSON с узлами и base_rating; сид без изменения кода движка. Оставить в сиде/доках явное описание формата JSON.
- Загрузка/обновление карты сложности: при необходимости — админ-эндпоинт или скрипт «загрузить JSON и обновить узлы».

### 2.3 Гибкость формулы (как в микро-инструкции)

- Вся логика рейтинга и K-фактора — только в **AnalyticsEngine**. Усложнение (время суток, усталость, детекция угадывания по времени) — правки только там, без трогания assignments/lessons.

### 2.4 Дополнительно полезно

- **Прогноз балла ЕГЭ:** в спецификации — первичные баллы и «линейная аппроксимация» во вторичные. Имеет смысл вынести коэффициенты перевода первичный→вторичный в конфиг/таблицу (например, по году), чтобы не хардкодить.
- **API `/api/analytics/summary`:** возвращать не только рейтинги по узлам, но и **predicted_exam_score** (если уже считаем), чтобы фронт мог показать и радар, и прогноз балла.
- **Уроки (LessonTask):** в следующей фазе — вызывать `process_submission` при автопроверке домашки/классной/проверочной и при ручной смене статуса «верно/неверно». Тогда нужен user_id из lesson.student.user_id и task из lesson_task.task (Tasks).

### 2.5 Обработка ошибок

- Если у задания не найден узел — не падать, а возвращать None и логировать warning, чтобы сдача работы не ломалась из‑за аналитики.
- Вызов движка обернуть в try/except в местах интеграции (assignments): при ошибке логировать и не ронять commit.

---

## 3. Изменения в коде спецификации

- Заменить `Task` на `Tasks` и `task.id` на `task.task_id`.
- Заменить импорт `from app import db` на использование того же `db`, что и в проекте (из `app.models` или `core.db_models`).
- В **AnalyticsEvent** использовать FK на `Submissions.submission_id` и при необходимости на `Answers.answer_id`; имена таблиц у нас с заглавной буквы в ряде мест — проверить FK.
- В **process_submission** не использовать `task.difficulty`; брать task_rating из узла (base_rating).
- **submission_id** в AnalyticsEvent — передавать ID сдачи (submission.submission_id), чтобы связать событие с конкретной работой; при ручной проверке — тот же submission.

---

## 4. Краткий чеклист внедрения

1. **Модели:** добавить в `core/db_models.py`: Subject, KnowledgeNode, UserMastery, AnalyticsEvent; FK на Users, Tasks, Submissions (и при желании Answers). Экспорт в `app/models/__init__.py`.
2. **Миграция:** создать таблицы (ensure_schema или миграция Alembic).
3. **Сид:** скрипт/JSON: Subject «КЕГЭ», узлы из матрицы сложности; маппинг task_number → node (или поле knowledge_node_id у Tasks).
4. **AnalyticsEngine:** отдельный модуль (например, `app/analytics/engine.py` или `core/analytics_engine.py`), логика по спецификации с адаптациями выше (Tasks, base_rating из узла, user_id из student.user_id).
5. **Интеграция в assignments:**  
   - при авто-проверке (submit): после установки is_correct для каждого ответа — вызов process_submission;  
   - при сохранении оценки (submission_grade_save): после сохранения ответов — вызов process_submission по каждому ответу с выставленным is_correct.
6. **API:** эндпоинт `/api/analytics/summary` (или под блюпринтом analytics) — рейтинги по узлам, прогноз балла.
7. **Фронт:** радар по темам (Chart.js/Recharts) на странице профиля/статистики ученика (по желанию в первой версии можно отдать только JSON).

После этого инструкции из спецификации и микро-инструкции будут полностью адаптированы под платформу; масштабируемость и гибкость формулы сохранены.
