# BooStudy Theory Mathematics Upgrade — QA Report

Дата: 2026-11-09. QA выполнен в текущем dirty working tree. В нём параллельно присутствуют несвязанные изменения; clean baseline для legacy regression не снимался. Импортов в persistent database не делали.

## 1. Статус тестирования

| Область | Статус | Доказательство и границы |
|---|---|---|
| Новый unit/API suite | PASS | tests/v2/test_theory_math_engine_v1.py: 17 passed, 32 warnings. |
| Demo package validator | PASS | 1 group, 1 article, 1 asset, 17,846 bytes, local KaTeX checked, no issues. |
| Python syntax/compile | PASS | Изменённые routes, math modules и importer прошли py_compile. |
| Scoped diff whitespace | PASS | git diff --check для принадлежащих работе tracked paths. |
| Playwright visual demo | PASS | Временный Flask app/in-memory SQLite, browser errors и failed requests отсутствуют. |
| Legacy theory batch | PARTIAL | Девять suites: 36 passed, 17 failed; clean baseline отсутствует. |
| Реальный полный пакет 15/174 | NOT TESTED | Ничего не загружалось в persistent DB; full package latency/memory не измерены. |
| Staging/production load | NOT TESTED | Deploy и production не выполнялись. |
| Физическая MathLive клавиатура и accessibility | NOT TESTED | Проверены DOM presence и API validation, не устройства/screen readers. |

## 2. Unit/API проверки

Запуск:

~~~text
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_theory_math_engine_v1.py -q
17 passed, 32 warnings in 8.20s
~~~

Suite проверяет:

- защиту LaTeX source/backslashes и таблицы Markdown;
- синтаксис KaTeX для frac/dfrac, корней, сумм/произведений, пределов/интегралов, логарифмов/тригонометрии, cases/aligned, pmatrix/bmatrix, греческих обозначений и векторов;
- формулы в callout, CHECKPOINT и INTERACTIVE;
- исключение code fence из formula extraction;
- удаление authored script/event markup;
- numeric/fraction/tolerance/alternate answers, symbolic polynomial, set и interval;
- разделение incorrect, invalid_format и unsupported;
- запрет выполнять Python payload в math parser;
- semantic block rendering, раскрываемое решение, независимые шаги;
- безопасный график/геометрию и SVG sanitization;
- draft import, stable block id и отсутствие дубля при повторе;
- API ответов и сохранение latest attempt/count;
- CSRF на выбранных preview/progress routes;
- проверку sequential access для прямого URL и interaction API.

32 предупреждения — в том числе SQLAlchemy Query.get и datetime.utcnow deprecations из текущего проекта; suite ими не провалился.

## 3. Package validation

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package examples/theory_math_demo --mode validate
~~~

**PASS:** valid=true, groups=1, articles=1, assets=1, total_bytes=17846, latex_checked=true, issues=[]. Это только validate; demo не создавался в DB.

## 4. Playwright visual matrix

Использован преподавательский draft preview на временном Flask app и in-memory SQLite. Измерения в docs/theory_math_qa/playwright_visual_audit.json. Скриншоты в docs/theory_math_qa/screenshots/.

| Viewport | Document overflow | KaTeX / invalid | График / geometry | Math fields / steps | Таблица |
|---|---|---|---|---|---|
| 1920×1080 | нет | 120 / 0 | 1 / 1 | 5 / 3 | в ширине статьи |
| 1440×900 | нет | 120 / 0 | 1 / 1 | 5 / 3 | в ширине статьи |
| 1366×768 | нет | 120 / 0 | 1 / 1 | 5 / 3 | в ширине статьи |
| 1024×768 | нет | 120 / 0 | 1 / 1 | 5 / 3 | свой горизонтальный scroll |
| 768×1024 | нет | 120 / 0 | 1 / 1 | 5 / 3 | в ширине статьи |
| 390×844 | нет | 120 / 0 | 1 / 1 | 5 / 3 | свой горизонтальный scroll |

На всех viewport document scrollWidth равен clientWidth. Browser errors и failedRequests отсутствуют. Изображения загружены; validImages=3 включает системную графику страницы и demo image. Demo document достигает 15,679px высоты на ширине 390px, без page horizontal overflow.

Скриншоты:

- [1920×1080 viewport](docs/theory_math_qa/screenshots/1920x1080-viewport.png)
- [1440×900 viewport](docs/theory_math_qa/screenshots/1440x900-viewport.png)
- [1440×900 full page](docs/theory_math_qa/screenshots/1440x900-full.png)
- [1366×768 viewport](docs/theory_math_qa/screenshots/1366x768-viewport.png)
- [1024×768 viewport](docs/theory_math_qa/screenshots/1024x768-viewport.png)
- [768×1024 viewport](docs/theory_math_qa/screenshots/768x1024-viewport.png)
- [390×844 viewport](docs/theory_math_qa/screenshots/390x844-viewport.png)
- [Playwright JSON measurements](docs/theory_math_qa/playwright_visual_audit.json)

## 5. Existing theory regression batch

Запущены suites course isolation, admin hub, Python curriculum, lesson studio, student course assignment, learning cycle, dropzone API, curriculum package и новый math suite. Итог: **17 failed, 36 passed, 189 warnings**. Новая math suite прошла целиком. test_theory_admin_hub.py и test_student_theory_learning_cycle прошли; весь пакет не зелёный.

Список ошибок:

1. test_theory_course_isolation.py::test_programming_course_theory_isolation — 302 вместо ожидаемого 200.
2. test_theory_course_isolation.py::test_programming_course_progression_and_final_test_locking — StopIteration при поиске ожидаемого fixture.
3. test_python_theory_curriculum.py::test_python_comprehensive_curriculum_integrity — GET /theory возвращает 404 вместо ожидаемого 200.
4. test_theory_learning_cycle_v2.py::test_theory_experience_keeps_course_identity_and_uses_real_completion — StopIteration.
5. test_theory_learning_cycle_v2.py::test_theory_experience_excludes_drafts_and_respects_teacher_locks — StopIteration.
6. test_theory_learning_cycle_v2.py::test_theory_experience_empty_course_renders_without_writes — StopIteration.
7. test_theory_learning_cycle_v2.py::test_lesson_studio_uses_canonical_theory_and_validates_selected_block — assertion ожидает data-view=\"theory\", не найдено в текущем HTML.
8. test_theory_dropzone_api.py::TestTheoryDropzoneApiV2::test_1_create_theory_with_file — тест падает при fixture setup: teacher is None, до запроса dropzone.
9. test_theory_dropzone_api.py::TestTheoryDropzoneApiV2::test_2_create_theory_text_only — тест падает при fixture setup: teacher is None, до запроса dropzone.
10–17. Восемь тестов test_theory_curriculum_package_v2.py — существующий старый curriculum package отвергнут с сообщением «Пакет должен содержать минимум две группы теории».

Некоторые ошибки выглядят связанными с fixture/legacy expectation, однако без clean baseline и с concurrent dirty files их происхождение не доказано. Чужие модули, fixtures и информатический контент не менялись для маскировки этих сбоев. До полной приёмки запустить batch на чистом commit, затем сравнить результаты; отдельно проверить lesson studio, dropzone и старый importer.

## 6. Acceptance criteria

| # | Критерий | Статус | Комментарий |
|---:|---|---|---|
| 1 | LaTeX отображается | PASS | Локальный KaTeX, 120 формул, 0 invalid в demo. |
| 2 | Формулы в тексте и интерактивах | PASS | Unit coverage Markdown/table/callout/checkpoint/interactive + browser rendering. |
| 3 | Числовая проверка ответа | PASS | Десятичные формы, отрицательные, fraction и tolerance тесты. |
| 4 | Символьная проверка безопасна и ограничена | PARTIAL | Restricted exact polynomial parser, намеренно не general CAS. |
| 5 | Ученик вводит математические выражения | PARTIAL | MathLive render/API проходят; mobile virtual keyboard/accessibility не тестировались. |
| 6 | Графики функций | PASS | Safe server SVG и browser demo; не каждый option визуально проверен. |
| 7 | Геометрические чертежи | PASS | Points/segments/polygon/angle отрисованы в demo. |
| 8 | Новые semantic blocks | PASS | Renderer tests и demo содержат новые types. |
| 9 | Авторский preview | PARTIAL | Existing authenticated HTML preview есть; отдельной package preview sandbox нет. |
| 10 | Bulk draft import | PARTIAL | CLI и helper готовы; полный курс не импортирован, DB берётся из app config. |
| 11 | Повторный импорт без дубликата | PASS | Unit test повторяет пакет; ID остаётся, второй block не создаётся. |
| 12 | Информатика/regression | PARTIAL | Есть passed legacy tests и 17 current-worktree failures; baseline не снят. |
| 13 | Сохранение progress | PARTIAL | Схема не менялась, update сохраняет block id/task_number; существующий progress полный end-to-end не загружался. |
| 14 | CSRF и access security | PARTIAL | Global theory exemption снят и representative routes тестированы; не все legacy mutation routes проверены отдельно. |
| 15 | Длинные статьи на mobile | PASS | 390px без document overflow; таблица scroll внутри себя. |
| 16 | Author contract | PASS | Создан отдельный полный THEORY_MATH_AUTHORING_CONTRACT_V1.md. |

## 7. Не проверено

- Пакет курса из 15 групп и 174 реальных статей.
- Полный import/publish в staging DB.
- Production, миграции/rollback миграций (миграций в этом upgrade не было).
- Нагрузочная оценка длинной серии статей, сотен интерактивов/графиков и пакета 75MB.
- MathLive клавиатура на физических Android/iOS устройствах, screen reader и keyboard-only QA.
- Точное поведение sampled intersections/asymptotes для математически сложных функций.
- Отдельный isolated preview пакета без импорта draft.
- Чистый контрольный запуск существующих suites на исходном checkout.
- Полный end-to-end набор legacy информатических статей и CSRF всех старых mutation routes.

## 8. Вывод

Доказательств достаточно для review V1 и постепенной проверки небольших черновых пакетов. Полная пользовательская приёмка ещё не пройдена. До массового наполнения нужно разобрать legacy failures на чистом baseline, импортировать representative пакет в staging, проверить MathLive на мобильном устройстве и прогнать полный manifest 15/174 через validate/preview. Публиковать курс следует после отдельного утверждения содержания и этих проверок.
