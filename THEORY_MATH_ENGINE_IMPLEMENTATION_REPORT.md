# BooStudy Theory Engine — Mathematics Upgrade V1

Дата проверки: 2026-11-09. Описано состояние рабочей копии, не production.

## 1. Результат и архитектура

Добавлена первая версия инфраструктуры математических материалов: локальный KaTeX, MathLive input, ограниченная серверная проверка ответов, семантические блоки, декларативные SVG-графики и геометрические схемы, валидатор Markdown-пакета и CLI чернового импорта.

Новых таблиц и миграций БД нет. Демонстрационная статья лежит в examples/theory_math_demo, не импортировалась в постоянную БД и не публиковалась. Production, deploy и commit не выполнялись.

**Статус приёмки: PARTIAL.** Фокусные тесты и браузерный demo прошли. Запуск девяти смежных legacy suites на текущей рабочей копии завершился 17 ошибками и 36 успешными тестами. Чистого baseline до изменений нет, поэтому нельзя приписать все ошибки этому изменению и заявить полную регрессионную готовность курса информатики.

Основные компоненты:

- app/theory/math_rendering.py — защита fenced/inline code и CODE-маркеров, извлечение формул до Markdown/regex pass, Bleach allowlist для authored HTML, восстановление LaTeX как escaped text.
- app/theory/math_validation.py — bounded arithmetic parser и математические validators; не вызывает eval, sympify или SymPy.
- app/theory/visualizations.py — render_function_plot и render_geometry, генерирующие SVG из ограниченного JSON без авторского JavaScript.
- app/theory/math_curriculum.py — validate_math_package, build_import_plan, import_drafts, publish_selected, content hashes, проверка assets и маркеров.
- app/theory/routes.py — _render_theory_content_html, _render_theory_content_html_core, _parse_theory_checkpoints, _parse_theory_interactives, API ответов, _student_block_access_error.
- static/js/theory-math.js — KaTeX render, MathLive init и диагностическая индикация ошибочных формул в preview.
- static/vendor/katex/ и static/vendor/mathlive/ — локальные ресурсы и лицензии; package.json/package-lock.json фиксируют KaTeX 0.19.1 и MathLive 0.111.4.
- templates/sandbox/theory_article.html — формулы, интерактивы, семантические блоки, SVG, таблицы, адаптивность.
- templates/sandbox/theory_admin_hub.html — локальные math assets и существующий серверный HTML-preview.
- scripts/import_theory_math.py — validate, preview, import-draft, publish, status.
- tests/v2/test_theory_math_engine_v1.py — 17 тестов.

## 2. Модели и сохранение пользовательских данных

Модели в core/db_models.py:

| Модель / таблица | Поля и ограничения |
|---|---|
| Course / ExamCourses | id, title String(200), slug String(50), unique/index, is_active, created_at. |
| TheoryGroup / TheoryGroups | course_id, name String(200), description String(500), position, created_by; unique (course_id,name). |
| TheoryBlock / TheoryBlocks | course_id, group_id, task_number, title String(200), description String(500), read_minutes, position, content Text nullable, pdf_path, author_id; unique (course_id,task_number). Text не задаёт короткую длину; пакетный контракт ограничивает статью 500,000 байт. |
| StudentTheoryState | unique (student_id,course_id,task_number); закладки, is_read, reading_progress, last_position, last_opened_at. |
| TheoryCheckpointAttempt / TheoryCheckpointAttempts | unique (student_id,block_id,checkpoint_key); selected_answer String(500), is_correct, attempts_count, answered_at. Это последнее состояние и счётчик, не история всех ответов. |
| StudentCourseEnrollment / StudentCourseEnrollments | unique (student_id,course_id), is_active. |

Группы сортируются по TheoryGroup.position, статьи внутри группы — по TheoryBlock.position; далее учитываются task_number и id. task_number уникален во всём курсе и является ключом состояния чтения. Импорт адресует статью по course slug + task_number, обновляет существующую запись и сохраняет TheoryBlock.id; StudentTheoryState не теряется. Попытки остаются привязанными к block id + checkpoint key, поэтому при смене смысла задания нужен новый key. Отсутствующие статьи не удаляются и не перенумеровываются.

Назначение курса остаётся существующим механизмом StudentCourseEnrollment/management UI; пакетный importer не назначает учеников.

## 3. LaTeX и Markdown

Поддерживаются inline $...$ и delimiters с обратным слешем и круглыми скобками, display $$...$$ и delimiters с обратным слешем и квадратными скобками. math_rendering.py защищает fenced/inline code и legacy [CODE]/[CODE_RUNNER], извлекает формулы перед Markdown/custom markers, затем возвращает исходные обратные слеши как экранированный текст. Двойная обработка math node предотвращается dataset-флагом на клиенте.

Используется KaTeX 0.19.1, локально; trust=false, throwOnError=false, maxSize=50, maxExpand=500, HTML+MathML. Поддерживаются требуемые школьные команды: дроби, корни, степени, индексы, суммы, произведения, пределы, интегралы, логарифмы, тригонометрия, cases, aligned, матрицы, греческие символы, векторы и стандартные обозначения. Ошибка одной формулы не ломает статью; в preview видна диагностика. Package validator использует локальный KaTeX через Node, с timeout 15 секунд.

Формулы работают внутри Markdown-таблиц, CHECKPOINT question/options/feedback и interactive prompt/hint/explanation, а также тела новых callouts. Длинная display формула имеет свой scroll container; таблица обёрнута в .theory-table-scroll; mobile shell ограничивает переполнение viewport. Browser demo отрисовал 120 формул на шести размерах.

Статья по-прежнему подключает прежнюю Prism CSS тему с cdnjs. Математические библиотеки локальны, но нельзя обещать полную offline-страницу.

Markdown сохраняет заголовки, абзацы, emphasis, inline code, списки, fenced code, pipe tables, blockquotes, horizontal rule, ссылки и Markdown images. Authored HTML очищается Bleach allowlist в app/theory/math_rendering.py; валидация пакета дополнительно запрещает script, iframe, SVG, math-field, object/embed и on* handlers. App-owned интерактивы и SVG создаются после sanitizer. Raw HTML не является авторским API.

## 4. Блоки, уровни и интерактивы

Добавлены пары DEFINITION, THEOREM, PROOF, EXAMPLE, FORMULA, COMMON_MISTAKE, SUMMARY и раскрываемый SOLUTION. Пример: [DEFINITION title=\"Определение\"]...[/DEFINITION]. Тело рассчитано на текст, inline emphasis/code/math и отдельные нумерованные строки, не является полным вложенным Markdown AST. Семантические блоки не вкладываются друг в друга; STEP внутри STEP_EXERCISE — исключение.

Существующие REMEMBER, IMPORTANT, NOTE, WARNING, TIP, INFO, TRY, HOW_IT_WORKS, CALLOUT, LEVEL, CHECKPOINT, INTERACTIVE, CODE, CODE_RUNNER и старые материалы сохранены.

LEVEL использует [LEVEL name=\"beginner\" label=\"С нуля\"]...[/LEVEL]. Несколько панелей работают; первая активна, выбор запоминается локально. Уровень не создаёт отдельный прогресс и не блокирует другой. **Если есть хотя бы один LEVEL, текст вне LEVEL-панелей renderer отбрасывает.** Поэтому оборачивайте весь контент; не вкладывайте LEVEL.

CHECKPOINT остаётся single-choice: key, question, options через |, answer — точное совпадение одной option; hint/explanation optional. Формулы рендерятся, но math equivalence отсутствует. Попытки unlimited; в TheoryCheckpointAttempt хранятся последний ответ и счётчик. Успех не завершает статью; прогресс чтения остаётся самостоятельным.

INTERACTIVE сохраняет существующие типы input, choice, order, table, code, boolean, multi, match, classify, fill, slider, hotspot, sequence, trace, regex, binary, formula, predict, debug, explain; добавлен math с MathLive. Общие атрибуты из пакета: type, key, prompt, answer; ключи уникальные на статью. Успешные ответы используют ту же запись попытки. Для пошагового упражнения добавлены STEP_EXERCISE → независимые STEP, с отдельным attempt key каждому шагу.

## 5. Проверка математических ответов

Валидаторы app/theory/math_validation.py: exact, numeric, numeric_tolerance, fraction, symbolic, set, interval.

- exact сравнивает строку без учёта регистра; valid_answers задаёт альтернативы явно.
- numeric принимает десятичную точку/запятую, дроби, арифметику, ограниченные степени и функции sqrt, sin/cos/tan, arcsin/arccos/arctan, ln/log/exp, pi/e; сравнение точное, без epsilon.
- numeric_tolerance использует math.isclose; нужен явный ненулевой absolute и/или relative tolerance.
- fraction использует точную Fraction арифметику.
- symbolic — точные x/y полиномы с рациональными коэффициентами, +/−/×, деление на ненулевую константу, целая степень 0…12.
- set — конечные рациональные множества, порядок не важен.
- interval — один интервал с точкой с запятой и конечными/бесконечными границами.

Защита ограничивает ответ 512 символами, AST 80 nodes и глубиной 20, полином 256 members/degree 16. Переменный знаменатель и x/x отклоняются, чтобы не скрывать изменение области определения. Универсальной символьной математики нет; нет численного sampling вместо доказательства. domain принимает только real/ℝ и не кодирует произвольное ОДЗ. Неподдерживаемая формула возвращается как unsupported, не как доказательство неэквивалентности.

## 6. Графики и геометрия

FUNCTION_PLOT JSON поддерживает 1–4 функции, диапазоны осей от −1000 до 1000, до 30 точек, 12 линий и 12 выделенных интервалов; выражения до 160 символов, выборка 360 интервалов на функцию. Есть сетка/оси, labels, points, guide lines, highlighted x ranges, приблизительные intersections и aspect equal/stretch. JSON до 12,000 символов.

GEOMETRY поддерживает point, segment, line, ray, circle, polygon, angle/right mark и равные метки отрезков; координатный viewBox 640×420, до 60 примитивов/30 точек, polygons 3–12 вершин, цвета только hex.

Ни график, ни геометрия не исполняют author JS. Ограничения: нет pan/zoom, точного GeoGebra, общей CAS-интерполяции, решения геометрических constraints или 3D. Discontinuity detection у графика эвристическое на дискретных samples; сложную 3D-схему передавайте безопасным asset.

## 7. Пакетный импорт и права

Manifest schema_version=1; UTF-8 Markdown. Пределы: manifest 2MB, статья 500KB, пакет 75MB, asset 15MB, курс 500 статей. Число 174 не зашито в importer; expected_structure может зафиксировать 15/174.

validate не создаёт Flask app/не подключает DB. preview строит план/hash изменений и конфликты, это не HTML preview. Авторский HTML preview уже есть через авторизованный POST /theory/manage/preview и не пишет в БД.

import-draft создаёт Course неактивным и все TheoryBlock как draft даже если manifest.status=published. Update/upsert идёт в DB transaction, повтор одинакового пакета не создаёт дубли. Для конфликтующего draft нужен явный --overwrite; опубликованные блоки importer не перезаписывает. publish принимает явно указанные article keys и сравнивает сохранённый текст с текущим source. Публикация статьи не активирует курс; назначение/активация отдельно.

Asset path содержит hash. Filesystem assets записываются до DB commit, поэтому rollback может оставить orphan. Автоматической очистки orphan нет. Группа в БД сопоставляется по имени; manifest group key отдельно не сохраняется, переименование может создать ещё одну группу.

Theory blueprint снят с глобального CSRF exemption; JS отправляет CSRF header. Фокусные тесты проверяют некоторые preview/progress endpoints, не каждый старый route отдельно. Прямой URL ученика и API ответа используют _student_block_access_error: active course, published block, enrollment/access и чтение предыдущей опубликованной статьи. Учитель может просматривать draft. /theory/manage выводит metadata и подгружает body выбранной статьи отдельно.

## 8. Проверки и вердикт

- tests/v2/test_theory_math_engine_v1.py: **17 passed**, 32 warnings.
- Demo package validate: valid, 1 group, 1 article, 1 asset, 17,846 bytes, latex_checked=true, issues=[].
- py_compile новых модулей, routes и CLI: PASS.
- git diff --check по относящимся к работе tracked paths: PASS.
- Playwright: временный Flask app, in-memory SQLite, teacher draft; не persistent DB.
- Viewports 1920×1080, 1440×900, 1366×768, 1024×768, 768×1024, 390×844. На каждом 120 rendered formulas, 0 invalid, 1 graph, 1 geometry, 5 math fields, 3 steps; нет document horizontal overflow, console errors и failed requests. Таблица на 1024 и 390 имеет внутренний scroll.
- Скриншоты/измерения: docs/theory_math_qa/.
- Девять смежных legacy suites: **17 failed, 36 passed**. Baseline не снимался; детали — в THEORY_MATH_QA_REPORT.md.

Ограничения: не загружен реальный пакет 15/174 на staging; не проверена production performance; нет отдельного package preview sandbox до import; старые attempts не сбрасываются при переписывании того же key; assets после DB rollback требуют возможной ручной очистки; group rename отдельно не решён; 2D renderer не заменяет GeoGebra; на статье остаётся Prism CDN.

**Вердикт:** базовый локальный поток LaTeX, MathLive input, ограниченных validators, SVG, semantic blocks, validation и draft upsert демонстрируется успешно. Возможна техническая приёмка и постепенная проверка малых пакетов. Массовая публикация всего курса не подтверждена до разбора legacy failures на чистом baseline, import полного курса в staging и ручной проверки реальных статей.

Полный демонстрационный исходник: examples/theory_math_demo/groups/quadratic-functions/001-quadratic-function.md; manifest: examples/theory_math_demo/manifest.json; SVG: examples/theory_math_demo/groups/quadratic-functions/assets/parabola-scheme.svg.
