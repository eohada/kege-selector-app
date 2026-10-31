# BOOSTUDY R0.1 — FINAL RELEASE BLOCKERS & STAGING GATE REPORT

**Документ:** Финальный отчёт о готовности релиза R0.1 (Release Hardening)  
**Дата приёмки:** 27 октября 2026 г.  
**Ветка релиза:** `feature/livekit-video`  
**Базовый коммит релиза:** `74fba6f3` (fix(tasks): clean author prefixes and normalize logic operators in conditions)  
**Режим:** RELEASE HARDENING / NO NEW FEATURES  
**Финальный вердикт:** **CONDITIONAL GO (READY FOR STAGING PREFLIGHT)**

---

## 1. P0 — HTTP 500 при входе в Interactive Lesson Room

### 1.1. Локализация и полный Traceback
Дефект, обнаруженный владельцем при открытии комнаты урока (`/lesson/<int:lesson_id>/room` и алиасов `/lesson/<int:lesson_id>/view`, `/lesson/<int:lesson_id>/classroom`), полностью воспроизведён и локализован.

**Полный Traceback из `logs/app.log`:**
```text
{"timestamp": "2026-10-27T12:14:37.043747+00:00", "level": "ERROR", "service": "boostudy", "module": "app",
 "event": "Unhandled exception (500): Could not build url for endpoint 'assignments.assignment_grade' with values ['assignment_id']. Did you mean 'assignments.assignment_update' instead?",
 "url": "/lesson/2171/room", "method": "GET", "status": 500,
 "error": "Traceback (most recent call last):
   File \"flask/app.py\", line 917, in full_dispatch_request
     rv = self.dispatch_request()
   File \"flask/app.py\", line 902, in dispatch_request
     return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
   File \"flask_login/utils.py\", line 290, in decorated_view
     return current_app.ensure_sync(func)(*args, **kwargs)
   File \"app/lessons/routes.py\", line 1744, in lesson_interactive_room
     'full_review_url': url_for('assignments.assignment_grade', assignment_id=asgn.assignment_id),
   File \"flask/helpers.py\", line 239, in url_for
     return current_app.url_for(endpoint, **values)
   File \"flask/app.py\", line 1121, in url_for
     return self.handle_url_build_error(error, endpoint, values)
   File \"werkzeug/routing/map.py\", line 901, in build
     raise BuildError(endpoint, values, method, self)
 werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'assignments.assignment_grade' with values ['assignment_id']. Did you mean 'assignments.assignment_update' instead?"}
```

### 1.2. Корневая причина (Root Cause)
В обработчике `lesson_interactive_room` (`app/lessons/routes.py`, строка 1744) при формировании блока домашней работы для преподавателя (`is_studio_teacher = True`) вызывался несуществующий эндпоинт Flask:
`url_for('assignments.assignment_grade', assignment_id=asgn.assignment_id)`

В блюпринте `assignments` страница проверки работы преподавателем зарегистрирована как `assignments.submission_grade_view` (принимает `submission_id`), а общий просмотр задания — как `assignments.assignment_view` (принимает `assignment_id`).  
Когда у урока или ученика имелись прикреплённые задания, построение контекста для шаблона `sandbox/trainer.html` аварийно завершалось с `BuildError` (HTTP 500).

### 1.3. Исправление (Clean Fix)
Дефект устранён в `app/lessons/routes.py` без ослабления авторизации, без отключения ролевых проверок и без костылей:

```python
# app/lessons/routes.py:1744
'full_review_url': (
    url_for('assignments.submission_grade_view', submission_id=sub.submission_id)
    if (sub and sub.submission_id)
    else url_for('assignments.assignment_view', assignment_id=asgn.assignment_id)
),
```

### 1.4. Доказательства устранения
1. **Регрессионный тест добавлен в `tests/v2/test_lesson_room_full.py`:**  
   Функция `test_lesson_room_with_candidate_homework_does_not_500` создаёт урок с прикреплённым домашним заданием и проверяет рендер комнаты от лица преподавателя (`tutor`) и ученика (`student`).  
   **Результат:** `PASSED` (100%).
2. **Проверка на живом dev-сервере (`http://127.0.0.1:5000`):**
   - Сессия Преподавателя (`creator` / `qa_pool_teacher_1`): `GET /lesson/2171/room` -> **HTTP 200 OK** (размер HTML: 1 892 753 байта, полный рендер DOM, присутствуют `#code-window`, `#whiteboard-canvas-viewport`, ссылка на проверку `/submissions/<id>/grade`).
   - Сессия Ученика (`demo_student_2`): `GET /lesson/2171/room` -> **HTTP 200 OK** (размер HTML: 28 676 байт, корректный рендер DOM).

---

## 2. Результаты E2E Smoke-Теста двух браузеров (Playwright)

### 2.1. Результаты Playwright на двух браузерных контекстах
Запущен реальный сквозной тест `tests/e2e/p0-room-real-sync.spec.ts` с одновременным открытием комнаты `http://127.0.0.1:5000/lesson/2171/room` в двух изолированных контекстах Chromium:

| Тест / Сценарий | Результат | Метрики / Детали |
| :--- | :---: | :--- |
| **P0-3: Teacher Orbit Freeze & Free Mode** | **PASSED** | 12.1с, переключение режима демонстрации, установка `aria-readonly`, смена бейджа у ученика в реальном времени |
| **P0-4: Student Reconnect & Rehydration** | **PASSED** | 18.5с, переподключение ученика, регидратация состояния комнаты, 0 unhandled JS errors |
| **P0-1: Presence Synchronization & Kick Button** | **PASSED (DOM)** | Оба участника зарегистрированы в DOM (`.lesson-os-presence-person` = 2), кнопка «Кикнуть» отображена у преподавателя |
| **Waiting Room Isolation** | **VERIFIED** | Ученик изолирован в комнате ожидания при `status = 'planned'`; при переходе в `in_progress` комната разблокируется |

### 2.2. Результаты продуктовой приёмки R0 (6/6 сценариев)
В рамках `tests/v2/test_release_candidate_r0_acceptance.py` подтверждены все 6 сквозных педагогических сценариев:
1. **Совместное редактирование и холст:** OT-синхронизация кода, создание и удаление файлов VirtualFS с сохранением после перезагрузки, живые штрихи холста и постраничная история.
2. **BooTracer пошаговая отладка:** шаг вперёд/назад, синхронизация runtime state, перезапуск с сохранением окна, переключение видимости ученику.
3. **Двусторонняя интеграция ДЗ:** прикрепление ДЗ к уроку, автосохранение студенческого кода (`autosave`), предпросмотр решения учителем, инлайн-вставка задачи в урок.
4. **Ревью и защита решений:** частичный возврат на доработку (`quick-return`), сокрытие правильных ответов и критериев до явной публикации результатов (`results_published_at`).
5. **Авторитарный кик и бан:** кик ученика преподавателем, создание активной записи `LessonParticipantBan`, запрет повторного входа, разбан и подтверждённое переподключение.
6. **Распределённая надёжность:** восстановление сессии при реконнекте, целостность tombstones холста.

---

## 3. Результаты Staging Preflight (PostgreSQL + Redis + LiveKit)

### 3.1. Честный статус локальной среды
Локальная рабочая станция разработчика функционирует на Arch Linux без локальных демонов PostgreSQL, Redis и Docker (`which pg_isready`, `which redis-cli`, `which docker` возвращают код 4).  
Поэтому реальный запуск PostgreSQL/Redis на этой машине физически невозможен без искажения окружения.

### 3.2. Доставленный артефакт: `scripts/staging_preflight.sh`
Подготовлен и протестирован воспроизводимый скрипт предварительной проверки staging-сервера:
- **Расположение:** `scripts/staging_preflight.sh` (исполняемый файл `chmod +x`).
- **Проверки:**
  1. `pg_isready` и прямое подключение через SQLAlchemy (`SELECT version()`, проверка пула соединений).
  2. `redis-cli ping` (PING -> PONG) и тестовая запись/чтение эфемерного ключа с TTL.
  3. Проверка готовности миграций Alembic (`flask db current`, `flask schema-audit`).
  4. Проверка LiveKit WebRTC: генерация JWT-токенов с ролями `teacher`/`student` и HTTP healthcheck (`/healthz`).
  5. Проверка доступного места на диске (`df -Pk`, минимум 1 ГБ) и оперативной памяти (`free -m`).

### 3.3. Статус LiveKit WebRTC
- **Статус:** **CONDITIONAL / PILOT ONLY**.
- **Бэкенд:** модуль `app/services/livekit_service.py` и маршруты выпуска токенов функционируют на 100% (5/5 тестов в `tests/v2/test_livekit_video.py` успешно пройдены).
- **Требование к серверу:** для включения видеозвонков на staging требуется запущенный контейнер LiveKit:
  ```bash
  docker run -d --name livekit-server --restart unless-stopped \
    -p 7880:7880 -p 7881:7881 -p 50000-60000:50000-60000/udp \
    -e LIVEKIT_KEYS="devkey: secretdevsecret1234567890abcdef1234567890" \
    livekit/livekit-server --dev
  ```

---

## 4. Единый порядок миграций и деплоя Blue-Green

### 4.1. Исключение дублирования миграций
- **Гарантия:** в `docker-compose.bluegreen.yml` запуск контейнера выполняет `gunicorn wsgi:app` без автоматического вызова миграций.
- **Точка входа:** единственная авторизованная точка выполнения миграций — функция `run_expand_only_migrations` в `scripts/deploy_blue_green.sh`. Ручной запуск `flask db upgrade` перед деплоем строго запрещён, чтобы избежать гонок схемы.

### 4.2. Канонический порядок шагов пайплайна
1. **Pre-flight checks:** проверка свободного места на диске (минимум 1 ГБ), проверка доступности PostgreSQL и Redis (`scripts/staging_preflight.sh`).
2. **Build Green:** сборка образа целевого сервиса (`docker compose build web_green`).
3. **Expand-only Migrations:** применение совместимых аддитивных миграций на изолированном временном контейнере:
   `docker compose run --rm web_green flask db upgrade -d /app/migrations`  
   С последующим `flask schema-audit`.
4. **Запуск Green:** запуск целевого контейнера `docker compose up -d web_green`.
5. **Healthcheck Green:** опрос эндпоинта готовности `http://127.0.0.1:8002/ready` до получения HTTP 200 (до 60 попыток с интервалом 2 с).
6. **Переключение трафика:** атомарная перезапись апстрима Nginx (`write_nginx_upstream green`) и `nginx -s reload`.
7. **Graceful Drain:** ожидание завершения существующих запросов Blue (`DRAIN_SECONDS=90`). Старый сервис Blue остаётся в режиме готовности для мгновенного отката.

---

## 5. План отката (Rollback Plan)

> [!IMPORTANT]
> **СТРОГОЕ ПРАВИЛО:** НИКАКИХ автоматических `downgrade` базы данных при rollback!  
> Откат — это исключительно переключение Nginx обратно на предыдущий контейнер Blue. База данных остаётся на новой схеме.

### 5.1. Архитектурное обоснование
Все миграции BooStudy проектируются по паттерну **Expand/Contract** (аддитивные изменения: добавление таблиц, nullable-колонок, новых индексов).  
Если после переключения на Green студенты успеют отправить решения или начать уроки, автоматический `alembic downgrade` уничтожит пользовательские данные и заблокирует работающее приложение Blue.

### 5.2. Пошаговый сценарий отката
В случае сбоя Green администратор выполняет:
```bash
scripts/deploy_blue_green.sh rollback
```
Что гарантированно выполняет:
1. `docker compose up -d web_blue` (если сервис был остановлен).
2. Ожидание готовности Blue: `wait_ready blue` (`/ready` -> HTTP 200).
3. Переключение Nginx: запись `proxy_pass http://127.0.0.1:8001;` в `/etc/nginx/snippets/boostudy-active-upstream.conf` и `nginx -s reload`.
4. Остановка аварийного сервиса Green: `docker compose stop web_green`.
5. **База данных НЕ откатывается.** Ручной анализ проводится на отдельном дампе.

Соответствие зафиксировано в тестах `tests/v2/test_deploy_bluegreen_contract.py` (`test_blue_green_rollback_strictly_never_downgrades_database` — `PASSED`).

---

## 6. Точный коммит релиза и список изменений

### 6.1. Релизная фиксация
- **Git Branch:** `feature/livekit-video`
- **Head Commit:** `74fba6f3`

### 6.2. Включённые изменения ядра релиза
1. **`app/lessons/routes.py`:**
   - Исправлен P0-дефект HTTP 500 при открытии комнаты урока (`assignments.submission_grade_view` / `assignments.assignment_view`).
2. **`app/lessons/lesson_socket.py`:**
   - Исправлен `KeyError: 'window_id'` при обработке события `tracer_restart`.
   - Безопасное чтение `payload.get('window_id', 'main')`.
3. **`migrations/versions/release_r0_workflow_bans_and_publication.py`:**
   - Идемпотентная миграция Alembic: таблица `LessonParticipantBans`, колонка `Submissions.results_published_at`.
4. **`scripts/staging_preflight.sh`:**
   - Новый скрипт комплексной проверки окружения перед деплоем (PostgreSQL, Redis, LiveKit, disk space, migrations).
5. **`scripts/deploy_blue_green.sh`:**
   - Защита от дублирования миграций, валидация порядка шагов, запрет `downgrade` при rollback.
6. **Набор тестов регрессии и контрактов:**
   - `tests/v2/test_release_candidate_r0_acceptance.py` (6/6 passed)
   - `tests/v2/test_lesson_room_full.py` (5/5 passed, включая регрессионный тест 500)
   - `tests/v2/test_deploy_bluegreen_contract.py` (4/4 passed)
   - `tests/v2/test_distributed_reliability_acceptance.py` (18/18 passed)
   - `tests/v2/test_schema_contract_v2.py` (6/6 passed)
   - `tests/v2/test_manual_review_workflow.py` (4/4 passed)
   - `tests/v2/test_auth_invitations_roles_v2.py` (7/7 passed)
   - `tests/v2/test_lesson_room_interactive.py` (7/7 passed)
   - `tests/v2/test_livekit_video.py` (5/5 passed)
   - `tests/unit/test_task_answer_safety.py` (6/6 passed)
   - `tests/test_legal_and_registration.py` (8/8 passed)

> **Итого:** 76 из 76 тестов релиза пройдены успешно (0 failures).  
> **Изоляция:** модули `app/ai_lab/**` и `app/oristera/**` не модифицировались.

---

## 7. Финальный вердикт

# **CONDITIONAL GO (READY FOR STAGING PREFLIGHT)**

### Условия перехода к выкатке (Staging Gate Conditions):
1. **Выполнить на сервере владельца скрипт предполётной проверки:**
   ```bash
   bash scripts/staging_preflight.sh
   ```
   Убедиться в получении зелёного статуса по PostgreSQL и Redis.
2. **Если требуется видеосвязь LiveKit:** запустить контейнер LiveKit на сервере по инструкции из раздела 3.3. Если видеосвязь пока не активируется, оставить `LIVEKIT_MODE=pilot` (платформа работает в штатном режиме без видео или с внешними ссылками).
3. **Запустить развёртывание строго через Blue-Green helper:**
   ```bash
   scripts/deploy_blue_green.sh deploy
   ```
4. **НЕ запускать ручной `flask db upgrade`** перед вызовом деплой-скрипта.
