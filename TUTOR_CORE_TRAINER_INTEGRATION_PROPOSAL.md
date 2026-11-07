# Tutor Core — Production Integration Architecture

**Статус:** проект для архитектурного согласования. Это не спецификация уже работающего production API и не разрешение на реализацию. Все новые маршруты, хранилища и поля ниже помечены как предлагаемые.

**Проверенная область:** статический анализ текущей реализации в `/mnt/Main/projects/kege_selector_app_current`. Production-база и реальные пользовательские записи не открывались; production deployment и подключение реальных источников не проверялись.

## Ответы на четыре главных вопроса

### A. Что уже можно переиспользовать без переписывания?

- Существующий фасад `TutorCoreV1` и его Python-методы: профиль, регистрация результата, выбор следующей практики, объяснение решения, спецификация короткой проверки и read-only рекомендация по курсу. Методы делегируют существующим Tutor Core 3.1, Learning Evidence v2 и Practice — второго педагогического ядра создавать не требуется. См. [`tutor_core_contract.py`](app/ai_lab/tutor_core_contract.py#L42), [`learning_evidence.py`](app/ai_lab/learning_evidence.py#L78), [`tutor_core31.py`](app/ai_lab/tutor_core31.py#L757).
- Серверный интерфейс доверенного `ClientAdapter`: он разрешает источник попытки, точный skill/criterion и проверенный каталог материалов. Адаптер регистрируется кодом сервера, не данными запроса. См. [`ClientAdapter`](app/ai_lab/tutor_core_contract.py#L34).
- Нормализацию, проверку provenance, идемпотентное событие и объединение истории. Текущий ingestion сначала перечитывает запись через adapter и валидирует Learning Evidence v2; клиент не передаёт готовые баллы или `mastered`. См. [`record_learning_event`](app/ai_lab/tutor_core_contract.py#L117), [`validate_evidence_event`](app/ai_lab/learning_evidence.py#L122).
- Текущую платформенную оценку Assignment можно использовать как источник для классной/домашней работы: `Assignment → AssignmentTask → Submission → Answer`; для ревизий существует append-only `AnswerEvaluationRevision` с методом, автором, состоянием и связью с предыдущей ревизией. См. [`db_models.py`](core/db_models.py#L2876), [`db_models.py`](core/db_models.py#L2966), [`db_models.py`](core/db_models.py#L3010), [`db_models.py`](core/db_models.py#L3049).
- Course recommendation можно сохранить как отдельный read-only путь; Tutor Core не применяет изменение курса (`course_mutated=false`). После production-адаптации курс всё равно должен разрешаться по действующему назначению платформы, а изменение оставаться за существующим подтверждением преподавателя. См. [`course_recommendation`](app/ai_lab/tutor_core_contract.py#L378).

### Б. Что мешает использовать Tutor Core с настоящими учениками?

1. Это фактический hard gate, а не только настройка: `_require_safe_local_runtime()` разрешает фасад только в локальной AI Lab с проверенной synthetic SQLite; `_authorize_subject()` требует synthetic allowlist и `demo_`/`synthetic_` учётную запись. См. [`tutor_core_contract.py`](app/ai_lab/tutor_core_contract.py#L75), [`database_safety.py`](app/ai_lab/database_safety.py#L15).
2. События клиента сохраняются в `AiLabExperiment`, модель которого прямо описана как изолированный эксперимент; это не production-журнал учебных событий. См. [`record_learning_event`](app/ai_lab/tutor_core_contract.py#L151), [`AiLabExperiment`](core/db_models.py#L4235).
3. `Learning Evidence v2` пока разрешает только модули `ai_homework`, `ai_classwork`, `ai_analytics`, `ai_practice`, `ai_course`, `ai_lesson_intelligence`, `ai_tutor_core`; внешний production trainer не является зарегистрированным источником. См. [`learning_evidence.py`](app/ai_lab/learning_evidence.py#L31), [`tutor_core_contract.py`](app/ai_lab/tutor_core_contract.py#L50).
4. `course_recommendation()` использует synthetic `_platform_profile_cases`; он не является production-разрешителем курса. См. [`tutor_core_contract.py`](app/ai_lab/tutor_core_contract.py#L384).
5. Отдельного публичного HTTP API Tutor Core в текущем контракте нет. `TutorCoreV1` — внутренний Python-фасад; `actor_user_id` и `subject_id` должны поступать от аутентифицированного backend, а не из браузерного payload.
6. Универсальный durable event store, source adapter к самостоятельным попыткам тренажёра и production-модель Student Skill Profile пока не подключены.
7. Прошлая внутренняя приёмка оставила Code Judge Runner без полного security PASS из-за недоступности локального изолированного Runner. Это отдельный блокер для производственных сценариев исполнения кода; данный статический анализ Runner не переоценивал.

### В. Какой минимальный production-контракт необходимо реализовать?

Оставить один Tutor Core и существующий Python-фасад основой. Добавить production-композицию доверенных access/source/evidence adapters и долговременный журнал доказательств; предоставить тренажёру стабильный server-side API для своего профиля и запроса практики. Для записи результата использовать только ссылку на уже сохранённую и проверенную сервером попытку. Не принимать от браузера оценку, `mastered`, источник или идентификатор чужого ученика.

При общей Flask-программе предпочтителен **внутренний Python service API**, а не новый сетевой сервис. Публичные маршруты — тонкие контроллеры аутентификации/DTO, которые вызывают фасад. Межсервисный HTTP имеет смысл только если Trainer Backend фактически развернут отдельно; тогда нужна отдельная service-to-service идентичность и тот же контракт событий.

Текущий `boostudy.tutor-core-client.v1` не следует молча превращать в общедоступный API: его методы и обязательные поля можно сохранить для внутренних Python-клиентов, но текущая реализация ограничена synthetic. Для внешнего trainer DTO предлагается отдельная явная версия **`boostudy.tutor-core-trainer.v1`**. Это версия транспортного контракта, а не новая версия педагогического алгоритма. Общие модели данных и правила вывода должны переиспользоваться из ядра.

### Г. Что может делать команда тренажёра уже сейчас?

- Реализовать UI тренировочной сессии, локальные состояния загрузки/ошибки и показ результата штатного checker.
- Сохранять попытку через собственный официальный backend/source API, присваивать ей стабильный ID и версию материала/checker, вести журнал показа задания и подсказок.
- Интегрироваться в synthetic-контуре через существующий серверный `ClientAdapter` и Python-фасад, не вызывая его напрямую из браузера.
- Подготовить контрактные тесты к будущим `GET skills`, `POST recommendation` и ingestion callback, используя фиктивные источники; не маркировать synthetic-ответы production-ready и не собирать ответы в `AiLabExperiment` как постоянное хранилище реальных учеников.

## 1. Executive summary

Tutor Core V1 — уже существующая серверная фасадная интеграция над Tutor Core 3.1. Основные пригодные элементы: нормализованный Learning Evidence v2, точный resolver навыка и критерия, trusted adapter, дедупликация событий, независимая от курса практика и read-only course preview. Имеющиеся тесты подтверждали synthetic работу разных клиентов, сохранение между экземплярами и проверки доступа в этой изолированной конфигурации; они не подтверждают production-аутентификацию, production-хранилище или подключение реальных Submission.

Рекомендуемый путь: оставить один алгоритм Tutor Core; в том же Flask-процессе собрать его за production access policy, source adapters и evidence repository; открыть ученику только безопасный профиль и запрос практики. Попытки остаются у источника (Assignment или backend тренажёра), Tutor Core хранит только нормализованное доказательство/ссылку и его ревизионную историю. При недоступности Tutor Core тренажёр сохраняет свою обычную попытку и отправляет событие повторно с тем же idempotency key.

## 2. Фактическое состояние компонентов

| Компонент | Установленный факт | Статус для production |
|---|---|---|
| Фасад `TutorCoreV1` | Методы `profile`, `record_result`, `next_practice`, `explain_decision`, `quiz_specification`, `course_recommendation` существуют; сами методы являются thin wrapper поверх одной инстанции фасада. | Алгоритм и shape внутреннего API можно переиспользовать; runtime production отсутствует. |
| Авторизация | Субъект — `platform-student:<user_id>`; разрешение проверяет активные synthetic User/Student, allowlist и relationship access для synthetic-актора. | Реальные аккаунты намеренно не проходят текущие проверки. Нужна production policy, не удаление всех проверок. |
| История | Client event проверяется и записывается в `AiLabExperiment`; Tutor Core 3.1 объединяет его с несколькими synthetic AI Lab источниками. | Непригодно как долговременное production-хранилище. |
| Evidence schema | Learning Evidence v2 валидирует timestamps, результаты, навыки, критерии, assistance, provenance, контекст попытки и оценки; источник обязан входить в фиксированный перечень. | Подходящая основа нормализации, но новый источник/поля требуют явного версионирования и тестов. |
| Assignment | Существуют Assignment, Submission, Answer и несколько SubmissionAttempt; `AnswerEvaluationRevision` явно хранит метод/автора/состояние оценки. | Хороший authoritative source для назначенных заданий после точного выбора активной попытки и текущей ревизии. Не превращать свободную практику в фиктивный Assignment. |
| Каталог материалов | `ClientAdapter.list_candidates` предполагает проверенные материал, checker и provenance. | Требует owner-owned catalog adapter и фильтрации по доступу/повторному показу. |
| Course | `course_recommendation` read-only, но строит проекцию через synthetic `_platform_profile_cases`. | Нужен production course-context provider; для самостоятельного тренажёра Course/Lesson не обязательны. |
| Oristera adapter | Atlas построен на статическом перечне номеров ЕГЭ; рекомендации вызываются через несовместимую сигнатуру и исключение скрывается. | Не подключать как официальный Student Skill Profile. Требуется отдельное исправление владельцем Oristera; детали в разделе 8. |

## 3. Предпочтительная архитектура

```text
Student UI
    │ same-origin authenticated request
    ▼
Trainer Backend route ── resolves current_user → Student
    │ in-process Python call; no user-supplied actor/source identity
    ▼
Tutor Core production composition
    ├── AccessPolicy (student self / teacher relationship)
    ├── Trusted ClientAdapter registry (server code only)
    ├── EvidenceRepository (durable event/revision ledger)
    ├── existing Learning Evidence v2 validation/merge
    ├── existing Tutor Core 3.1 profile/decision logic
    └── checked material catalog references (no answer-key export)
```

### Факт

`ClientAdapter` уже реализует нужную границу: сервер разрешает попытку, skill/criterion и кандидатов. Сейчас `TutorCoreV1` сам фиксирует AI Lab runtime и synthetic authorization, а event persistence обращается к `AiLabExperiment` напрямую.

### Предложение

После согласования разделить **композицию/доступ/репозиторий** от педагогического решения: оставить текущую synthetic-конфигурацию и проверки как отдельную реализацию policy/repository; добавить production bindings в ту же фасадную логику. Не снимать synthetic gate глобально и не делать `ENVIRONMENT`-флаг заменой предметной проверки.

Trainer route получает субъекта только из сессии (`current_user` → активная Student). Для teacher-specific подробной аналитики применяется уже существующая relationship scope с проверкой конкретного Student. Тренажёр никогда не передаёт `actor_user_id` и не выбирает произвольный `subject_id` для ученической сессии.

Поскольку текущий проект — единое Flask-приложение, внутренний вызов устраняет дополнительный сетевой trust boundary и сохраняет возможность adapter перечитать Assignment/Answer в той же транзакционной базе. Если backend тренажёра окажется отдельным сервисом, решение меняется на private HTTP: взаимная аутентификация сервисов (mTLS или эквивалентный short-lived service token), жёсткое сопоставление client identity → разрешённые source modules, TLS, replay/idempotency protection и аудит. Не публиковать `record_result` как endpoint, принимающий произвольное JSON-событие от браузера.

## 4. Официальный Student Skill Profile

### Предлагаемая выдача `boostudy.tutor-core-trainer.v1`

Ученик получает только собственные skills из каталога, разрешённого для выбранного предмета. Для каждого навыка API возвращает стабильные `skill_id`, название, критерий, качественное состояние, достаточность данных, последнее безопасное наблюдение, следующее действие и короткое объяснение. Не отдавать сырые ответы, hidden checker/test cases, закрытые комментарии, персональные данные других людей или внутренний teacher rationale.

Возможные состояния должны отображать существующие вычисления, а не вводить проценты:

| Представление API | Основание |
|---|---|
| `no_data` | У каталожного навыка нет допустимого события. Это отсутствие наблюдений, а не неуспех. |
| `single_difficulty`, `repeated_difficulty` | Текущие `_skill_state` различают одну ошибку и ошибки на разных заданиях. Причина ошибки не считается доказанной. |
| `contradictory_recent_error`, `mixed_history_progress` | Последняя ошибка противоречит прежнему успеху либо история содержит ошибки и более поздние успехи. Требуют сдержанного объяснения/диагностики. |
| `single_independent_success`, `success_after_help`, `success_help_unrecorded`, `success_help_unobserved` | Различает результат и наблюдаемую самостоятельность/помощь. Не равно mastery. |
| `repeated_independent_success` | Два и более независимых задания в текущей логике; не выдавать как процент или универсальное доказательство освоения. |
| `insufficient_data` | В источнике нет подтверждённой оценки/точного skill-criterion либо история не достигает требований агрегата. |

`Tutor Core 3.1._skill_state` реализует перечисленные состояния и отдельно считает подтверждённые успехи, ошибки, самостоятельные успехи и разные задания; сейчас профиль также содержит `history`. Для ученика нужен отдельный allowlist DTO без этой сырой истории и без закрытых полей. Для преподавателя допустимы ссылки на источники, метод/checker, revision, помощь и основания исключения при наличии прав на этого ученика. См. [`_skill_state`](app/ai_lab/tutor_core31.py#L101), [`learning_profile`](app/ai_lab/tutor_core_contract.py#L217).

## 5. Practice Recommendation Contract

Тренажёр может передать явный выбор ученика `skill_id`/`criterion_id` либо попросить предложение по доступному набору навыков. При cold start он получает диагностическую цель и метку `personalization="none"`; отсутствие истории не блокирует обычную практику и не маскируется под персональный выбор.

Tutor Core возвращает: цель и критерий, качественную основу решения (`no_history`, `insufficient_data`, `practice_signal`, `mixed_evidence`), предпочитаемый формат/сложность только в пределах имеющихся checker/candidate метаданных, причины исключения несовместимых источников и перечень **ссылок на материалы**. Текст условия и checker обслуживает Task Bank/Trainer backend после собственной авторизации. Эталон и скрытые тесты не входят в DTO.

Существующий `next_practice` уже валидирует точные skill/criterion и фильтрует задания через trusted `list_candidates`; если кандидат не найден, возвращает явную недоступность. Сегодня его ответ включает prompt кандидата и служит внутренней synthetic интеграцией. Production DTO рекомендуется ограничить `material_ref`, версией и checker metadata, а не переносить условие/ключи из Tutor Core.

Если история отсутствует, интерфейс явно сообщает «диагностическая практика, история ещё не учитывается». Если навыки не сопоставлены однозначно, checker не поддержан или материал знаком/непригоден, вернуть `unavailable` с машинным `reason_code` и доступным действием (выбрать другую цель/обычная практика/обратиться к преподавателю), не угадывать skill.

## 6. Регистрация результата и история

### Единственный поддерживаемый путь

1. Trainer backend определяет ученика из authenticated session.
2. Источник создаёт immutable attempt с серверным ID, ID/версией материала, временем показа/отправки и журналом подсказок/повторов.
3. Штатный checker или преподаватель создаёт authoritative evaluation. Пока оценка не проверена, событие может учитываться как exposure, но не как успешное/ошибочное доказательство.
4. После commit источник отправляет в Tutor Core только свой stable source record ID; trusted adapter перечитывает попытку, Student ownership, material mapping, актуальный checker/evaluation revision и provenance.
5. Tutor Core валидирует и регистрирует нормализованное событие. Ни `score`, ни `correct`, ни `mastered`, ни `source_module`, ни subject из браузера не принимаются как authority.
6. Исправление оценки создаёт новую evaluation revision/event; предыдущая запись сохраняется как superseded/voided. Projection пересчитывается по актуальной ревизии, сохраняя аудит.

### Assignment/Submission пригодность

Существующий Assignment-путь подходит для назначенных классных/домашних работ при корректном source adapter: `Submission` связан со Student и Assignment; `Answer` ссылается на Submission и AssignmentTask; `AnswerEvaluationRevision` хранит revision number, метод, автора, баллы, состояние и `supersedes_revision_id`. `SubmissionAttempt` имеет `submission_id`, `attempt_no`, status, итог и `attempt_data`.

Ограничение: это жизненный цикл назначенной работы. `Answer` уникален по `(submission_id, assignment_task_id)`, а запись SubmissionAttempt привязана к Submission; эти модели сами по себе не являются свободной тренировочной сессией. Создавать фиктивный Assignment/урок ради Tutor Core нельзя.

Если у Trainer нет собственной durable модели попыток, владельцу тренажёра нужен минимальный источник `TrainerAttempt` (название условно): `attempt_id`, `student_id`, `material_id + version + content hash`, `submitted_at`, `answer_ref` (сам ответ хранится только у Trainer), exposure/hint refs, evaluation method/checker version/revision, confirmed outcome/criteria и supersession/void linkage. Trainer владеет записью и её API; Tutor Core получает только trusted reference. Не добавлять эту модель в Tutor Core как второе хранилище ответов.

### Production event store

`AiLabExperiment` оставить только AI Lab. Предпочтительный production вариант — append-only `TutorLearningEvidence` projection в платформенном PostgreSQL и transactional outbox рядом с источником попытки:

- уникальный ключ доставки: `(source_system, source_record_id, evaluation_revision_id)`; стабильный `event_id`;
- `student_id`/`user_id`, stable skill/criterion IDs и версия mapping, attempt/material/checker IDs и версии/хеши;
- outcome/status, evidence method, assistance/exposure metadata, `occurred_at`, `evaluated_at`, source reference/hash;
- `course_context` опциональный и записывается только при явной подтверждённой связи;
- ревизии и отмены добавляются как новые записи/связи supersedes/void, а не перезаписывают историю;
- сырые ответы и ключи остаются в Assignment/Trainer storage. Evidence store по умолчанию содержит references и outcome, не копию ответа.

Запись source attempt и outbox должна атомарно фиксироваться в транзакции владельца источника. Доставка — at-least-once; unique key и сравнение fingerprint делают retry идемпотентным. Tutor Core projection обновляется из журнала; dashboard, profile и recommendations читают один версионированный evidence bundle/snapshot. Если событие пришло раньше проверки, сохраняется exposure/`insufficient_data`; после новой ревизии приходит новое событие и проекция пересчитывается.

Для удаления/ограничения данных пользователя платформа должна применять действующую retention/privacy policy; в Tutor Core хранятся только необходимые ссылки, outcome и provenance. Точные сроки и legal basis требуют решения владельца privacy/platform data.

## 7. Версия, DTO и ошибки

**Рекомендация:** не менять обязательные поля/семантику `boostudy.tutor-core-client.v1`; оставить его внутренним server-to-server Python API. Добавить явный transport contract `boostudy.tutor-core-trainer.v1` для безопасных student DTO. Это не новый движок и не обязательно отдельный HTTP сервис.

Правила trainer v1: добавочные необязательные поля разрешены; изменение значения state, авторизации, идемпотентности, источника истины, доступа к evidence или раскрываемого содержимого требует новой major contract version. В каждом ответе есть `contract_version`, `request_id`, `status`; ошибки имеют стабильный `code` и безопасное `message`. Не включать exception text с данными источника.

Предлагаемые коды: `unauthenticated` 401; `student_scope_denied` 403; `attempt_not_owned` 403; `skill_mapping_missing`/`attempt_not_found` 404; `invalid_request` 400; `event_conflict`/`revision_conflict` 409; `rate_limited` 429; `tutor_core_unavailable` 503. Пустой каталог — успешный ответ со `status="unavailable"`, не HTTP 500.

## 8. Обнаруженные несовместимости и владельцы исправлений

| Проблема и точная причина | Влияние | Владелец и минимальный шаг |
|---|---|---|
| **Oristera `task_number`/`task_no`:** [`get_student_skills_atlas`](app/oristera/adapters/tutor_core_adapter.py#L93) читает оба варианта поля и агрегирует по номеру экзаменационного задания. Канонический Learning Evidence v2 связывает событие через `skill_ids`, `criteria`, `topic_ids`, provenance; номер КИМ не является стабильным skill ID. Atlas помечает `verified_mastery` при `count >= 3`, без проверки результата, критерия, независимости задания или действующей ревизии. | Может показать ложное освоение или не увидеть события с точным skill ID. | **Oristera владелец**: использовать официальный Student Skill Profile и stable skill/criterion, удалить подсчёт попыток по номеру и mastery по количеству; добавить свои contract tests. Tutor Core команда предоставляет DTO/семантику и resolver навыка. |
| **Несовместимый вызов `recommend_practice`:** [`get_tutor_recommendations`](app/oristera/adapters/tutor_core_adapter.py#L123) вызывает `recommend_practice(subject_id)`, а функция требует `snapshot, catalog` и принимает дополнительные `completed_assignment_ids`, `course_outline` ([`practice.py`](app/ai_lab/practice.py#L1040)). Исключение ловится и возвращается `[]`. | На практике рекомендация не вызывается; UI получает неразличимый пустой ответ. | **Oristera владелец** удаляет этот обход и вызывает официальный Tutor Core backend facade; временно до его доступности возвращает явный `unavailable`, а не молча пустой список. |
| **Два пути рекомендации и статусы:** `build_analytics_snapshot` выставляет `demonstrated`, `developing`, `insufficient_data`; `recommend_practice` выбирает только `status == "needs_support"` ([`analytics.py`](app/ai_lab/analytics.py#L286), [`practice.py`](app/ai_lab/practice.py#L1040)). Отдельно `TutorCoreV1.next_practice_step` читает evidence bundle и вызывает `select_next_practice_exercise`. | AI Lab analytics recommendation и Tutor Core recommendation могут расходиться; текущий analytics recommender не получает статус `needs_support` от указанного builder. | **Tutor Core команда**: до production унифицировать источник/версию snapshot и единую детерминированную decision function; не менять пороги без независимой проверки. Добавить parity tests на одни и те же события. |
| **События между профилем и Analytics:** `get_tutor_core31_evidence_bundle` включает `stored_tutor_core_client_events` ([`tutor_core31.py`](app/ai_lab/tutor_core31.py#L757)); `all_analytics_evidence` включает synthetic demo, homework, lesson и practice источники, но client store в список не добавляет ([`analytics.py`](app/ai_lab/analytics.py#L2024)). | Snapshot/Analytics может не видеть события, которые видит профиль Tutor Core. `synthetic_demo_events()` также означает, что этот сборщик нельзя считать production-потоком. | **Tutor Core команда**: единый production EvidenceRepository/merge path; тест «profile = analytics = recommendation evidence refs» после каждой ревизии. |
| **Profile DTO не student-safe для прямой публикации:** `learning_profile()` возвращает `evidence.events`; Learning Evidence v2 допускает поле `response.value` (до 16 KiB). | Прямая выдача текущего результата ученику/тренажёру может раскрыть содержимое ответа и внутренние причины. | **Tutor Core команда**: production transport serializer формирует allowlisted view; не сериализовать целиком внутренний профиль/evidence bundle. |
| **Документация и сигнатура Course расходятся:** client contract описывает `expected_course_id` как обязательный positive ID, но `TutorCoreV1.course_recommendation(..., expected_course_id=None)` допускает пропуск. | Клиенты могут по-разному трактовать требуемый контекст курса. | **Tutor Core команда**: до расширения курса выбрать и зафиксировать один вариант; предпочтительно оставить контекст optional для course-free trainer, но при переданном ID строго проверять совпадение. Документировать это additive/совместимым изменением до первого production клиента. |
| **Production restriction/storage:** `_authorize_subject` и `_require_safe_local_runtime` synthetic-only; ingestion пишет AiLabExperiment. | Нельзя разрешить настоящие аккаунты удалением allowlist без настоящего source ownership, privacy, durable storage и teacher scope. | **Tutor Core команда + platform identity/data owner**: production policy, repository/outbox и источники; миграция после согласования и на backward-compatible rollout. |
| **Свободная практика:** Assignment/SubmissionAttempt связаны с назначением; в осмотренных Oristera routes присутствуют экран практики и `/api/practice/run`, но подтверждённый submit/evaluation event source для самостоятельной практики не найден. | Нельзя доказательно регистрировать ответ только фактом запуска sandbox. | **Trainer владелец**: подтвердить/создать собственный durable attempt + evaluation endpoint; не просить Tutor Core создавать Assignment. |
| **Course adapter synthetic:** `course_recommendation` обращается к synthetic `_platform_profile_cases`. | Production course context и назначение курса не подтверждены этим методом. | **Tutor Core + course platform owner**: предоставить read-only canonical assigned-course resolver; применение плана остаётся платформенному teacher decision flow. BooStudy OS/schedule не меняются этой задачей. |
| **Runner:** прежняя приёмка отметила локальный isolated Runner недоступным и не дала secure-profile verification. | Нет security evidence для production выполнения ученического кода. | **Code Judge/Runner owner**: отдельно предоставить подтверждённый isolation profile и E2E проверки. Не блокирует архитектуру non-code упражнений. |

## 9. Предлагаемые примеры API (production, пока не реализованы)

Все JSON ниже — **проектируемый DTO**, не существующий HTTP endpoint. Внутри одной Flask-системы frontend вызывает собственный backend route; он обращается к Tutor Core in-process. Для межсервисного варианта используется тот же DTO только по private authenticated channel.

### Сценарий 1 — ученик открывает тренажёр

```http
GET /api/v1/tutor-core/me/skills?subject=ege.inf
```

```json
{
  "contract_version": "boostudy.tutor-core-trainer.v1",
  "request_id": "req_01J...",
  "status": "ok",
  "personalization": "available",
  "skills": [{
    "skill_id": "ege.inf.graph.optimal-paths.v1",
    "title": "Поиск кратчайшего пути в графе",
    "criterion": {"criterion_id": "optimal_cost", "title": "Определяет минимальную стоимость маршрута"},
    "state": "single_independent_success",
    "evidence_sufficiency": "limited",
    "latest_observation": {"result": "met", "occurred_at": "2026-11-07T10:15:00Z"},
    "next_action": "transfer_check",
    "student_explanation": "Есть один самостоятельный успешный результат. Для более уверенного вывода нужна другая задача."
  }]
}
```

`subject` фильтруется серверным catalog resolver; ученик не получает чужие subject IDs. Не включены сырые ответы, hidden tests или teacher-only notes.

### Сценарий 2 — следующая практика

```http
POST /api/v1/tutor-core/me/practice-recommendations
Content-Type: application/json
```

```json
{"skill_id":"ege.inf.graph.optimal-paths.v1","criterion_id":"optimal_cost","preference":"recommended"}
```

```json
{
  "contract_version":"boostudy.tutor-core-trainer.v1",
  "request_id":"req_01J...",
  "status":"recommended",
  "personalization":"limited",
  "action":"transfer_check",
  "goal":{"skill_id":"ege.inf.graph.optimal-paths.v1","criterion_id":"optimal_cost"},
  "material_refs":[{"material_id":"task-bank:item-42","version":3,"content_sha256":"...","checker_id":"graph-cost-v2","checker_version":"2"}],
  "evidence_refs":["event_..."],
  "student_explanation":"Предлагается проверить тот же навык на другом графе. Это проверка на ограниченном наборе задач, не доказательство общей корректности."
}
```

Условия отображает Task Bank/Trainer backend после своей проверки доступа. При отсутствии истории `personalization="none"`, `action="diagnostic"`, `evidence_refs=[]`; стандартная тренировка продолжается без заявления о персонализации.

### Сценарий 3 — правильный ответ

**Последовательность, а не входящий ответ из браузера:**

```text
POST trainer attempt → attempt_id=tr-attempt-804 сохранён
server checker → evaluation revision 1: technical_confirmed, skill/criterion exact
internal Python call: client.record_result(server_actor_id, server_subject_id, "tr-attempt-804")
```

```json
{"contract_version":"boostudy.tutor-core-trainer.v1","event_id":"trainer:attempt:804:eval:1","status":"accepted","duplicate":false,"evidence_status":"technical_confirmed"}
```

Tutor Core получает от source adapter нормализованный исход, checker/version, hash/provenance и assistance metadata. Браузер не отправляет `is_correct`, `score_awarded` или `mastered` в Tutor Core.

### Сценарий 4 — несколько ошибок

```json
{
  "status":"ok",
  "skill":{"skill_id":"ege.inf.graph.optimal-paths.v1","state":"repeated_difficulty","evidence_sufficiency":"limited"},
  "observation":"Ошибки зафиксированы в двух разных заданиях.",
  "cause":"not_established",
  "next_action":"diagnostic_or_teacher_review",
  "student_explanation":"В двух задачах результат не совпал с критерием. Это сигнал для разбора, но данные не устанавливают причину ошибки."
}
```

Повторный `error_code` — наблюдаемый паттерн, не диагноз. При смешанных результатах состояние остаётся смешанным/противоречивым и не превращается в общий пробел.

### Сценарий 5 — использована подсказка

Событие от source adapter содержит assistance из серверного лога инструмента, например `level="leading_question"`; при неизвестной помощи передаётся `null`, а не догадка.

```json
{"skill":{"state":"success_after_help","independent_success_count":0},"next_action":"independent_transfer_check","student_explanation":"Ответ верный после подсказки. Чтобы проверить самостоятельное решение, можно попробовать другую задачу без содержательной помощи."}
```

Подсказка не превращает верный ответ в ошибку; результат остаётся технически правильным, а вывод о самостоятельности ограничивается.

### Сценарий 6 — недостаточно данных

```json
{"status":"insufficient_data","personalization":"none","reason_code":"no_confirmed_evaluation","next_action":"continue_regular_practice","material_refs":[],"student_explanation":"Проверенного результата пока нет. Можно продолжать обычную практику; вывод о навыке не сделан."}
```

Непроверенная попытка и неизвестное соответствие навыку не выставляются как ноль.

### Сценарий 7 — Tutor Core временно недоступна

Trainer уже сохранил попытку и evaluation у себя. При internal-service timeout он оставляет результат доступным как обычную проверку, помечает синхронизацию как pending и повторяет доставку события с тем же source record/revision ID.

```json
{"status":"accepted_by_trainer","tutor_core_sync":"pending","message":"Результат сохранён. Персональная история обновится после синхронизации."}
```

Worker/outbox повторяет с bounded backoff; одинаковый event ID/payload возвращает duplicate, конфликтующее содержимое той же ревизии — 409 и очередь на разбор. Новая оценка получает новый revision ID. Не показывать персональную рекомендацию как обновлённую, пока событие не подтверждено.

## 10. Совместимость Evidence, оценок и курсов

- `Learning Evidence v2` остаётся общей нормализованной моделью; любое расширение source kinds, evaluation provenance или revision lifecycle согласуется с владельцем схемы и проходит contract tests. Нельзя принимать дополнительный source string из запроса.
- Для Assignment adapter должен выбрать конкретные `SubmissionAttempt` и действующую `AnswerEvaluationRevision`, проверить, что ревизия не superseded/voided, что назначение/ответ действительно принадлежат указанному Student, и разрешить skill через versioned mapping. Одного `Answer.reviewed_at` недостаточно для provenance.
- `AnswerEvaluationRevision` содержит `method`, `actor_user_id`, score, correct, state и supersession link. Источник checker version, hint history и material exposure должен поступать из checker/Trainer source; его отсутствие сохраняется как unknown.
- Повторное назначение того же задания в другой курс/урок не создаёт нового независимого материала автоматически. Event сохраняет исходный `material_id/version/content hash` и отдельно явно разрешённый course binding/version. Несовпадающий критерий или checker делает evidence unverified/excluded для новой цели.
- `course_recommendation` остаётся optional и read-only. Для production нужен provider, который возвращает единственную действующую индивидуальную программу по платформенной связи и статусу; отсутствие/неоднозначность — явный `unavailable`/`ambiguous`, не «последний курс». Tutor Core не становится владельцем расписания, Lesson Room или lifecycle.
- Единый EvidenceRepository/read model нужен до сравнения Analytics и Practice. Snapshots должны быть вычисляемыми проекциями с версией алгоритма и `source_revision`; они не являются вторым источником истины.

## 11. Безопасность, доступ и отказоустойчивость

1. **Идентичность:** ученический вызов всегда `me`; backend получает `current_user`, проверяет активный User и однозначную Student связь. Никакого subject ID из body как authority.
2. **Teacher read:** отдельная роль/маршрут и проверка relationship на конкретного Student при каждом запросе. Teacher explanation недоступно ученику.
3. **Source adapter:** стабильный client ID и разрешённые source modules задаются конфигурацией/кодом. Adapter перечитывает источник и самостоятельно устанавливает владельца, timestamp, evaluation revision, checker, material и mapping.
4. **Подмена:** браузер не может прислать trusted source ID чужой попытки и получить результат; lookup должен быть ограничен тем же Student. Не принимать `source_module`, skill result, `assistance_level`, `correct` как доверенные поля от клиента.
5. **Материалы:** ответы, code hidden tests, scorer config, solution и private teacher note не передаются в Student DTO. Возвращается ref; content API источника выполняет отдельную student authorization.
6. **Повторы/конкуренция:** уникальный idempotency key на source + evaluation revision, транзакционная запись/outbox, конфликтный fingerprint → 409, retry не создаёт второе педагогическое свидетельство.
7. **Ревизия/исключение:** исправление/void — новая аудируемая запись с автором, причиной и timestamp. Read model пересчитывает текущую проекцию, история сохраняет предыдущую версию.
8. **Отказ:** при unavailable ядра Trainer сохраняет учебный продукт и попытку; отмечает неполную синхронизацию, ограниченно повторяет и отображает дату обновления профиля. Не делает синхронную запись обязательной для отображения результата checker.
9. **Логи и privacy:** логировать request/event/source IDs, contract version, outcome code и latency; не логировать answer body, expected answer, токены и закрытый checker. Доступ учителя к истории аудитируется. Retention, deletion, data export и правовое основание наследуются общей платформенной policy и должны быть подтверждены владельцем данных до production.
10. **Наблюдаемость:** метрики queue age, retries, rejected provenance, duplicate/conflict, stale profile projection, source lookup errors; алерты не содержат PII.

## 12. Матрица ответственности

| Область | Ответственный | Граница |
|---|---|---|
| Официальный внутренний/transport contract, DTO и error codes | Команда Tutor Core | Переиспользует текущую семантику; не принимает решения/оценки клиента. |
| Нормализация и Learning Evidence validation | Команда Tutor Core | Стабильные навыки/критерии, provenance, совместимость ревизий. |
| Педагогический профиль и рекомендация | Команда Tutor Core | Одна детерминированная логика; без второго агрегатора и выдуманных процентов. |
| Authorization boundary и source registry для Tutor Core | Команда Tutor Core совместно с Identity owner | Роль, ownership и relationship проверяются сервером на каждом запросе. |
| UI и тренировочная сессия | Команда тренажёра | Не хранит персонализацию самостоятельно и не трактует unknown как ошибку. |
| Сохранение попытки/ответа, checker, version и hint/exposure logs | Команда тренажёра или владелец соответствующего источника | Это источник истины ответов; Tutor Core не становится вторым Assignment. |
| Assignment/Submission/Answer lifecycle и revision provenance | Владельцы Assignment/Submission | Предоставляют read adapter/событие; Tutor Core не меняет общую модель без их согласования. |
| Task Bank и скрытие ключей | Владелец Task Bank/материалов | Авторизованная выдача содержимого, версии и checker metadata. |
| Course assignment/version resolver | Владелец курсовой платформы + Tutor Core | Resolver read-only; teacher decision flow сохраняет право применения. |
| BooStudy OS, синхронизация, расписание, Lesson Room | Владельцы этих подсистем | В текущей задаче ничего не менять; Tutor Core только потребляет поддержанные связи. |
| Production DB/privacy/retention policy | Platform data/security owner | Утверждает storage, сроки и обработку PII. |
| Изоляция исполнения Python | Code Judge/Runner owner | Предоставляет отдельное подтверждение безопасного execution profile. |

## 13. План внедрения после согласования

### P1. Production foundation

- **Результат:** production composition для существующего ядра, реальная self/teacher access policy, trusted source registry, durable evidence repository/outbox, versioned skill resolver.
- **Зависимости:** согласие platform identity/data owners; owner Assignment/Submission; решение по отдельному TrainerAttempt; privacy/retention; схема и backward-compatible миграция.
- **Затрагиваемое:** Tutor Core facade/repository, новая production evidence model/migration, источники/outbox по владельцам. Не OS/schedule.
- **Приёмка:** реальные HTTP principals в integration tests; cross-student/teacher denial; idempotency/revision/void; перезапуск приложения читает одну историю; synthetic path остаётся изолирован.

### P2. Student read-only API

- **Результат:** `boostudy.tutor-core-trainer.v1` для own skill profile, explanations и recommendation; cold start и explicit unavailable.
- **Зависимости:** P1 access/repository, approved DTO privacy review, stable skill catalog.
- **Затрагиваемое:** backend routes + serializers + Tutor Core adapter; без checker и авторинга заданий.
- **Приёмка:** student получает только себя; teacher endpoint только своего ученика; enum состояний покрывает реальные состояния; нет баллов/процентов/ответов/закрытых тестов; empty profile и material shortfall различимы.

### P3. Evidence ingestion

- **Результат:** source adapters к Assignment/Submission/Answer и к собственному источнику мини-тренажёра; подтверждение после сохранения checker/revision; повторное событие безопасно.
- **Зависимости:** Assignment owner предоставляет актуальную evaluation revision/checker metadata; Trainer owner предоставляет попытку, exposure/hints, evaluation version и ownership read.
- **Затрагиваемое:** trusted adapters, event repository, source outbox/callback. Assignment schemas только владельцем этого модуля.
- **Приёмка:** correct/incorrect/manual pending/hint/unknown help/revision correction/void/repeated material; клиентская оценка игнорируется; stale/ambiguous skill mapping получает `insufficient_data`.

### P4. Trainer integration acceptance

- **Результат:** один real backend client, без прямого вызова из браузера; обычная практика работает при Tutor Core outage.
- **Зависимости:** P1–P3; secure Code Judge Runner для code-based materials.
- **Затрагиваемое:** Trainer-owned routes/UI и contract tests; production E2E только в разрешённой среде.
- **Приёмка:** cold start; рекомендация; trusted correct/error; repeated errors без диагноза причины; hinted success; no candidate; retry duplicate/conflict; restart; access denial; скрытые ответы отсутствуют в API/logs.

Каждый этап должен иметь отдельный acceptance artifact. Synthetic test PASS нельзя объединять с production readiness PASS.

## 14. Критерии готовности для команды тренажёра

Тренажёр готов к integration acceptance, если:

- браузер общается только со своим authenticated backend;
- attempt, checker output, material/checker version, help/exposure и время сохранены до вызова Tutor Core;
- backend вызывает официальный adapter с source record ID, не строит Learning Evidence из request body;
- при `no_data`/`insufficient_data` практика продолжает работать, персонализация честно маркируется;
- задание получает из Task Bank по ref; hidden answer/test config остаются на сервере;
- повтор доставки не дублирует историю, новая evaluation revision пересчитывает профиль;
- timeout Tutor Core не теряет попытку и не показывает устаревший профиль как обновлённый;
- на одинаковом evidence profile, Analytics и Practice используют одинаковые event refs и версию проекции.

## 15. Решения, требующие согласования

1. Утвердить внутренний Python service API как предпочтительный при общем Flask backend; отдельный HTTP сервис не создавать без подтверждённого deployment boundary.
2. Утвердить разделение версий: внутренний `boostudy.tutor-core-client.v1` сохраняет семантику; внешний backend DTO — `boostudy.tutor-core-trainer.v1`.
3. Выбрать production durable event ledger + outbox в PostgreSQL и владельца миграции/retention; `AiLabExperiment` остаётся synthetic-only.
4. Определить владельца и минимальный контракт независимых Trainer attempts, если текущий источник не предоставляет сохранённый attempt/evaluation.
5. Утвердить точный student-safe набор состояний/объяснений и teacher-only fields; не отображать `StudentSkill.mastery_percent` как Tutor Core confidence.
6. Согласовать единый EvidenceRepository/read model для Tutor Core profile, AI Analytics и recommendations и владельца исправления нынешней несовместимости Oristera.
7. Подтвердить canonical skill/criterion catalog, mapping version и процедуры пересмотра совместимости старых материалов.
8. Утвердить privacy retention/deletion/audit policy до реального хранения учебных событий.
9. Зафиксировать отдельный security gate Code Judge Runner перед использованием исполнения кода в production.

## Источники фактов в репозитории

- [Tutor Core client contract v1](docs/TUTOR_CORE_CLIENT_CONTRACT_V1.md)
- [TutorCoreV1 facade и synthetic guard](app/ai_lab/tutor_core_contract.py)
- [Learning Evidence v2 validator/merger](app/ai_lab/learning_evidence.py)
- [Tutor Core 3.1 evidence bundle/profile](app/ai_lab/tutor_core31.py)
- [Analytics snapshot и evidence assembly](app/ai_lab/analytics.py)
- [Practice selection/recommendation](app/ai_lab/practice.py)
- [Oristera Tutor Core adapter](app/oristera/adapters/tutor_core_adapter.py)
- [Assignment, Submission, Answer, evaluation revisions](core/db_models.py)
- [Contract integration tests](tests/v2/test_tutor_core_client_contract.py)

---

**Решение:** передавать этот документ на архитектурное согласование. Реализацию, миграции, endpoint и подключение production-источников в рамках этой задачи не начинать.
