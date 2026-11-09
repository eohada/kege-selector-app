# BooStudy Mathematics Theory — Import Guide V1

Порядок доставки Markdown-пакета в курс. CLI использует обычный Flask app factory и его конфигурацию БД. Прямые мутирующие запуски CLI разрешены только в dev/staging после проверки выбранной БД.

Production-доставка группы «Математический фундамент» выполняется только через ручной GitHub Actions workflow `Deploy to VPS (MANUAL PROD)` с входом `import_math_foundation=true`. Workflow проверяет оба пакета Node/KaTeX на runner, затем после blue-green deploy сверяет SHA-256 на сервере, строит preview для обоих пакетов и останавливается при любом конфликте. При чистом preview материалы импортируются только как черновики; workflow не публикует статьи, не активирует курс и не создаёт назначений. Не запускайте production CLI вручную.

## 1. Структура пакета

~~~text
math-course/
├── manifest.json
└── groups/
    ├── 01-foundation/
    │   ├── 001-real-numbers.md
    │   ├── 002-intervals.md
    │   └── assets/number-line.svg
    └── 02-algebra/
        ├── 013-polynomials.md
        └── assets/factorization.png
~~~

Manifest содержит course slug/title, group metadata, article key/task_number/position/title/description/read_minutes/status/source и assets. Полная схема/синтаксис/лимиты — THEORY_MATH_AUTHORING_CONTRACT_V1.md.

Требования:

- Markdown и JSON UTF-8, статьи отдельными Markdown-файлами.
- Сохраняйте course slug, article key, task_number и ключи интерактивов между версиями.
- DB-группы сопоставляются по name; сохраняйте group name.
- Объявите каждый asset в той же группе и ссылайтесь на него через Markdown image с URL вида asset:ключ.
- Финальный manifest должен содержать expected_structure: 15 групп, 174 статьи.
- Не включайте raw HTML/JS, inline SVG или event handlers.
- Отсутствующая из пакета статья не удаляется.

## 2. Окружение и зависимости

Пакетный LaTeX validator запускает локальный Node и KaTeX из node_modules. Математические JS/CSS/font assets в проекте размещены локально.

CLI вызывает app.create_app() и использует настроенную приложением базу. Перед локальными preview/import-draft/status/publish проверьте, что конфигурация указывает на нужную dev/staging DB. CLI не принимает отдельный DSN argument. Серверный workflow использует production DB только после успешной KaTeX-проверки и бесконфликтного preview.

Для примеров команд подавляется DB bootstrap и запуск background workers:

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package examples/theory_math_demo --mode validate
~~~

## 3. Validate — без БД

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package /path/to/math-course --mode validate
~~~

Validate не создаёт Flask app и не подключается к DB. Exit code 0 означает отсутствие error issues. Требуйте:

- valid=true;
- latex_checked=true;
- группы/статьи/assets совпадают с manifest;
- issues пуст;
- total_bytes в лимите.

Отсутствие Node/KaTeX может быть warning с latex_checked=false; такой package нельзя импортировать или публиковать.

Проверяются JSON schema_version, уникальность group/article keys/numbers/positions, размер, UTF-8, symlink/path traversal, файлы, сигнатуры части image types, SVG sanitizer, asset aliases/alt, парность маркеров, обязательные поля интерактивов, runtime keys и validators, а также LaTeX локальным KaTeX. Ошибка formula указывает Markdown file/line, если место было установлено.

Последняя demo validation:

~~~text
valid: true
groups: 1
articles: 1
assets: 1
total_bytes: 17846
latex_checked: true
issues: []
~~~

## 4. Preview — план DB-изменений без записи

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package /path/to/math-course --mode preview
~~~

Этот режим читает DB и выводит план create/update/unchanged/conflict, block ids, incoming/current content hashes и metadata conflicts; DB не меняется. При конфликте сравните сохранённый материал и пакет. Не запускайте --overwrite, пока не проверили причину.

CLI preview — план импорта, не HTML статьи. Для HTML используйте существующий авторизованный POST /theory/manage/preview: он вызывает рендерер и не сохраняет content. После import-draft преподаватель может проверить материал через штатный интерфейс; новый курс создаётся inactive.

JSON report можно сохранить через --report /path/to/local/report.json. Выбирайте допустимый локальный путь.

## 5. Import Draft

Сначала убедитесь в выбранной dev/staging DB:

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package /path/to/math-course --mode import-draft --author-username AUTHOR
~~~

Необязательный --author-username должен принадлежать существующему пользователю; его id сохраняется в TheoryBlock.author_id. Без флага author_id остаётся null.

Поведение:

- новый Course создаётся неактивным;
- группы и статьи создаются/обновляются в транзакции БД;
- все материалы импортируются draft, даже если manifest status=published;
- identity статьи: course.slug + task_number;
- повтор идентичного пакета не создаёт дубликат;
- изменившийся draft конфликтует без явного --overwrite;
- published TheoryBlock не перезаписывается этим draft importer;
- отсутствующие статьи не удаляются;
- курс не включается и не назначается ученикам автоматически.

Используйте --overwrite только после осмотра плана и подтверждения целевой DB. Изменение task_number/keys может повлиять на привязку ученических данных.

DB работа обёрнута одной транзакцией: ошибка вызывает rollback. Assets сначала записываются под static/uploads/theory_math/<slug>/<group-key>/<content-hash>..., поэтому rollback БД может оставить orphan static file. Автоочистки этих файлов нет.

## 6. Авторский HTML preview и приёмка

Для каждого материала:

1. Проверьте validator и устраните все errors.
2. Откройте server-rendered preview статьи.
3. Проверьте KaTeX и предупреждение о broken формуле.
4. Пройдите интерактивы с верным и неверным ответом.
5. Проверьте график, схему, точки и подписи.
6. Убедитесь, что все assets открываются и alt объясняет картинку.
7. Проверьте таблицы/длинные display formulas на узком экране.
8. Проведите содержательную проверку человеком.

Пакетный validator проверяет синтаксис/структуру, не истинность доказательств, качество объяснения, корректность графического масштаба или педагогическую ценность задания.

## 7. Publish — только выбранные материалы

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package /path/to/math-course --mode publish --article real-numbers
~~~

Для нескольких статей повторите --article KEY. Публиковать можно только article.key из текущего manifest. CLI требует успешной validation и точного совпадения сохранённого контента с source package. Если блок изменён или не импортирован, публикация завершается ошибкой.

Publish помечает выбранные TheoryBlock published, но не активирует Course и не назначает его ученикам. Это отдельный явно принятый шаг через текущий management flow.

## 8. Status

~~~bash
BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/python scripts/import_theory_math.py --package /path/to/math-course --mode status
~~~

Status сначала валидирует current package, затем показывает Course и существующие блоки: ids, task_number, group id, title, position, draft/published, content hash. Если исходный пакет отсутствует или не проходит validation, status не служит автономным DB explorer — укажите актуальный валидный пакет.

## 9. Обновление и повторный импорт

1. Сохраните manifest и Markdown именно импортированной версии.
2. Запустите validate.
3. Запустите preview на нужной тестовой DB.
4. Сравните keys, номера и hashes.
5. Если update ожидаем, осмотрите preview с --overwrite.
6. Выполните import-draft и сохраните JSON report.
7. Проверьте draft в приложении.
8. Перед публикацией снова validate и передайте publish только выбранные keys.

Идентичный повтор безопасен и оставляет существующие ids. Update по тому же course/task_number сохраняет TheoryBlock id и reading state. Попытки CHECKPOINT остаются на block id + key; если смысл вопроса меняется, создайте новый key. Старые attempts автоматически не сбрасываются.

Manifest group key не хранится в отдельном поле. DB match идёт по group name; rename может создать новую группу. Согласуйте такое изменение отдельно.

## 10. Частые ошибки и ограничения

- LaTeX error: откройте указанную Markdown строку и проверьте синтаксис; preview не заменяет validate.
- Unknown type/validator: используйте только варианты из author contract.
- Content hash conflict: не затирайте молча; сверьте last approved source.
- Asset not found: проверьте key, путь и объявление в нужной группе.
- Непредвиденный course slug: остановитесь до подтверждения DB target.
- Orphan hash files после rollback требуют отдельной проверки и могут быть удалены оператором; CLI cleanup не выполняет.
- Для 174 материалов каждая статья ≤500 KB и весь пакет ≤75 MB.

Полная структура и примеры: examples/theory_math_demo/. Одностатейный demo валидирован, но полный курс 15/174 не импортировался.
