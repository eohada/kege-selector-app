# BooStudy Mathematics Theory — Authoring Contract V1

Этот контракт задаёт только проверенный renderer/importer синтаксис. Передавайте UTF-8 Markdown, JSON manifest и локальные assets. Не создавайте большую JSON-строку с экранированными обратными слешами.

## 1. Структура пакета и manifest

~~~text
math-course/
├── manifest.json
└── groups/
    ├── 01-foundation/
    │   ├── 001-real-numbers.md
    │   └── assets/number-line.svg
    └── 02-algebra/
        ├── 013-polynomials.md
        └── assets/factorization.png
~~~

Порядок файлов не задаёт порядок курса. Его задают position; task_number — стабильный номер материала.

Минимальный пример manifest:

~~~json
{
  "schema_version": 1,
  "course": {
    "slug": "ege-profile-math-2027",
    "title": "ЕГЭ-2027: профильная математика"
  },
  "expected_structure": {"groups": 15, "articles": 174},
  "groups": [
    {
      "key": "mathematical-foundation",
      "name": "Математический фундамент",
      "description": "Числа, выражения и базовые преобразования",
      "position": 1,
      "assets": [
        {"key": "number-line", "path": "groups/01-foundation/assets/number-line.svg"}
      ],
      "articles": [
        {
          "key": "real-numbers",
          "task_number": 1,
          "position": 1,
          "title": "Действительные числа и числовая прямая",
          "description": "Рациональные и иррациональные числа, интервалы и модуль",
          "read_minutes": 16,
          "status": "draft",
          "source": "groups/01-foundation/001-real-numbers.md"
        }
      ]
    }
  ]
}
~~~

### Поля и лимиты

- schema_version ровно 1.
- course.slug: 2–50 символов, строчные латинские буквы, цифры, дефис или подчёркивание; используйте постоянный уникальный slug.
- course.title: обязательно, 1–200 символов.
- expected_structure optional; для курса задайте ровно 15 групп и 174 статьи, чтобы validator это проверял.
- groups[].key: стабильный уникальный ключ до 64 латинских букв/цифр/дефиса/подчёркивания. Это ключ файлов/assets, не DB id.
- groups[].name обязательно, до 200 символов; сопоставление DB-группы идёт по имени. Не переименовывайте его в обычной редакции.
- groups[].description optional, до 500 символов.
- groups[].position положительное уникальное целое в курсе.
- assets[].key уникален в курсе, до 64 символов; файл должен быть внутри пакета. Форматы PNG, JPG, JPEG, WebP, SVG. GIF пакетно не поддержан. Размер 1…15,000,000 байт.
- articles[].key уникальный, до 64 символов; используется для публикации и отчёта.
- task_number положительный и уникальный во всём курсе; не перенумеровывайте после импорта.
- position положительный и уникальный в группе.
- title обязателен, максимум 200 символов; description optional, максимум 500.
- read_minutes целое 1…180; задавайте явно.
- status draft или published, но importer всегда пишет draft.
- source — UTF-8 Markdown внутри пакета, максимум 500,000 байт.
- manifest до 2,000,000 байт; пакет до 75,000,000; курс до 500 статей.
- Symlinks и path traversal за пределы пакета запрещены.

## 2. Разрешённый Markdown и HTML

Используйте заголовки #–######, абзацы, жирный/курсив, inline code, упорядоченные и маркированные списки, fenced code, pipe tables, Markdown blockquotes, горизонтальный разделитель ---, ссылки и изображения.

Примеры:

~~~markdown
## Свойство

Важный член выделяем **жирным**, обозначение пишем как *a*.

1. Первый шаг
2. Второй шаг

| Условие | Вывод |
|---|---|
| $a>0$ | Ветви направлены вверх |

> Короткое уточнение к основной мысли.

![Числовая прямая с отмеченной точкой](asset:number-line)
Подпись: точка обозначает значение a.
~~~

Raw HTML не является авторским API. Authored HTML проходит Bleach allowlist; manifest validator дополнительно запрещает script, iframe, SVG, math-field, object/embed и on* handlers. Не используйте JavaScript или inline SVG. App-owned интерактивы и SVG создает сервер.

Таблица и длинная display формула скроллятся внутри контейнера на мобильном. Изображения адаптивные. Для обычного Markdown изображения подпись добавьте отдельным абзацем: автоматический figcaption не создаётся.

## 3. Формулы

Используйте:

~~~text
Inline:   $x^2+1$
Display:  $$\frac{-b\pm\sqrt{D}}{2a}$$
Inline:   \(a^2+b^2=c^2\)
Display:  \[\begin{cases}x+y=3\\x-y=1\end{cases}\]
~~~

Пример в статье:

~~~markdown
Дискриминант равен

$$D=b^2-4ac.$$

Если $D\ge0$, корни вычисляются так:
$$x_{1,2}=\frac{-b\pm\sqrt{D}}{2a}.$$

\[
\begin{aligned}
x+y&=3,\\
x-y&=1.
\end{aligned}
\]
~~~

Локальный KaTeX 0.19.1 покрывает школьные дроби, корни, степени, индексы, суммы, произведения, пределы, интегралы, логарифмы, тригонометрию, cases, aligned, matrices, греческие символы, векторы и стандартные обозначения. Проверяйте сложные формулы пакетным валидатором и визуально. Это рендерер, не CAS.

Извлечение формул пропускает inline/fenced code и маркеры CODE/CODE_RUNNER. Не используйте доверенные HTML-команды в TeX: trust=false. В Markdown файле пишите реальные обратные слеши, не JSON-экранирование.

## 4. Семантические блоки

Поддерживаемые парные блоки; title optional, но рекомендуется:

~~~text
[DEFINITION title="Определение"]
Точное определение и формула $x^2$.
[/DEFINITION]

[THEOREM title="Теорема"]
Условия и утверждение.
[/THEOREM]

[PROOF title="Доказательство"]
Аргументы и формулы.
[/PROOF]

[EXAMPLE title="Пример"]
Условие и пояснение.
[/EXAMPLE]

[FORMULA title="Формула"]
$$a^2-b^2=(a-b)(a+b)$$
[/FORMULA]

[COMMON_MISTAKE title="Типичная ошибка"]
Неверный ход и объяснение правильного.
[/COMMON_MISTAKE]

[SUMMARY title="Итог"]
Краткий результат.
[/SUMMARY]

[SOLUTION title="Показать решение"]
Пошаговое объяснение с формулами.
[/SOLUTION]
~~~

SOLUTION — раскрываемая карточка. Body имеет ограниченный строковый формат: текст, переносы, inline emphasis/code/math и нумерованные строки. Это не полный Markdown AST. Не размещайте внутри таблицы, большие вложенные списки или другой структурный маркер. Новые семантические блоки не вкладываются; STEP внутри STEP_EXERCISE — единственное разрешённое структурное вложение.

Сохранены legacy блоки:

~~~text
[REMEMBER]Короткое напоминание.[/REMEMBER]
[IMPORTANT title="Важно"]Формула $a\ne0$.[/IMPORTANT]
[NOTE title="Замечание"]Текст.[/NOTE]
[WARNING title="Осторожно"]Текст.[/WARNING]
[TIP title="Совет"]Текст.[/TIP]
[INFO title="Информация"]Текст.[/INFO]
[TRY title="Попробуйте"]Текст.[/TRY]
[HOW_IT_WORKS speech="Ключевое слово"]Текст.[/HOW_IT_WORKS]
[CALLOUT type="warning"]Текст.[/CALLOUT]
~~~

CALLOUT type: info, tip, warning, attention, danger. Markdown цитата — обычная цитата, не отдельная карточка.

## 5. LEVEL

~~~text
[LEVEL name="beginner" label="С нуля"]
Начальный вариант материала.
[/LEVEL]

[LEVEL name="advanced" label="Углублённо"]
Продвинутый вариант материала.
[/LEVEL]
~~~

name обязателен, label необязателен. Default labels: beginner → «С нуля», остальные → «С опытом». Первая панель активна изначально; выбор сохраняется локально. LEVEL не создаёт отдельный reading progress и не блокирует другой текст.

**Если в статье есть хотя бы один LEVEL, renderer показывает только содержимое панелей, внешний текст пропадает.** Оберните весь материал в LEVEL или не используйте уровни. Несколько панелей работают; вложенные панели не поддерживаются. Имена должны быть уникальны.

## 6. CHECKPOINT

Реализован один правильный выбор:

~~~text
[CHECKPOINT key="vertex-1" question="Чему равна абсцисса вершины $y=(x-3)^2+1$?" options="$-3$|$1$|$3$" answer="$3$" explanation="В записи (x-h)^2 абсцисса равна h." hint="Сравните с y=(x-h)^2+k."]
~~~

Обязательны key, question, options минимум из двух, answer. Ответ должен точно совпасть с одним options. Key — латиница/цифры/точка/дефис/подчёркивание, до 80 символов, уникальный в статье. Ограничения: question 3000, до 20 options по 500, answer 500 символов. explanation показывается после правильного, hint после ошибки. Формулы поддерживаются во всех видимых текстах, но check точный, не math equivalence. Попытки unlimited; ответ хранится на сервере. Успешный CHECKPOINT не завершает статью и не открывает следующую.

Числовой, свободный, множественный и boolean answer через CHECKPOINT не реализованы.

## 7. INTERACTIVE и математические validators

Все атрибуты пишутся в одной строке с двойными кавычками. Не помещайте в значения непарные двойные кавычки.

~~~text
[INTERACTIVE type="math" key="half-answer" prompt="Введите $\frac{1}{2}$" answer="\frac{1}{2}" validator="fraction" valid_answers="0.5|0,5" explanation="Это одна рациональная величина." hint="Можно ввести 1/2."]
~~~

Обязательные для пакета общие поля: type, key, prompt, answer. Хотя legacy runtime может сгенерировать key, package validator требует стабильный key. У type=math указывайте validator явно; если пропустить, runtime применит numeric.

Поддерживаемые validators:

| validator | Проверка |
|---|---|
| exact | Строка без регистра; valid_answers задаёт явные варианты. |
| numeric | Ограниченное значение в R; десятичная точка/запятая, обыкновенная дробь, арифметика, ограниченные степени/функции. Сравнение точное, без допуска. |
| numeric_tolerance | numeric comparison с явным абсолютным и/или относительным допуском. |
| fraction | Точная рациональная арифметика; 2/4 равно 1/2. |
| symbolic | Точное сравнение полиномов x/y с рациональными коэффициентами. |
| set | Конечное множество рациональных чисел в фигурных скобках, разделитель ;. |
| interval | Один интервал вида [-1; 2), границы через ;. |

Поддерживаемые optional attrs: absolute_tolerance, relative_tolerance, valid_answers, domain="real", explanation, hint. valid_answers задаёт строковый список через | и не доказывает эквивалентность.

numeric_tolerance требует ненулевой абсолютный и/или относительный tolerance; absolute максимум 1,000,000, relative максимум 1. domain принимает только real/reals/ℝ, это не общее задание ОДЗ. Input ограничен 512 символами, AST — 80 nodes/глубина 20. Symbolic ограничен 256 polynomial terms, degree 16, степени 0…12 и переменные x/y. Разрешены +, −, × и деление на ненулевую константу. Функции, неравенства, иные переменные и переменный знаменатель не входят в grammar. x/x специально отклоняется, поскольку сокращение меняет ОДЗ. Универсального CAS нет.

Неверный формат возвращается отдельно от unsupported expression. Не выдавайте невозможность проверки за доказательство неэквивалентности.

### Реальные UI-типы

| type | Реальный control/ответ |
|---|---|
| math | MathLive math-field и math validator. |
| input, fill, regex, binary, formula, predict, explain | Обычное text input; exact lowercase после trim, если нет validator. regex не имеет отдельного regex matcher. |
| choice | Single-choice кнопки; options разделены |. |
| multi, classify | Multi-select; options и answer разделены |, сравниваются как множества строк. |
| boolean | Да/нет; true/1/да/yes трактуются как true, остальные как false. |
| order, sequence | Нажатия в заданном порядке; options, ответ соединён через >. |
| table, trace | 1–8 input cells через rows, результат соединяется через |. |
| match | Два text inputs, один ответ левая=правая, trim/lowercase. |
| slider | Range 0…100, exact string если validator не задан. |
| hotspot | Grid 3×3 cells 1…9; клиент соединяет выбранные номера через |, сервер проверяет exact. Используйте только одну клетку. |
| code, debug | Legacy Python editor/runner, не math engine. |

Для choice/multi/classify/order/sequence задайте options, максимум 20 вариантов по 500 символов. prompt ≤3000, answer ≤500, key ≤80. Несколько интерактивов в статье поддерживаются при уникальных keys. Не вкладывайте их внутрь других маркеров. Попытки unlimited; hint показывается при ошибке, explanation — при успехе.

## 8. Пошаговое упражнение

~~~text
[STEP_EXERCISE key="quadratic" title="Решите уравнение"]
[STEP key="discriminant" prompt="Найдите $D$." answer="1" validator="numeric" explanation="25-24=1."]
[STEP key="root" prompt="Введите меньший корень." answer="2" validator="numeric" hint="Корни равны 2 и 3."]
[/STEP_EXERCISE]
~~~

Каждый STEP имеет независимый key, prompt и answer; поддерживает те же math validator/tolerance/valid_answers/domain/hint/explanation. Хотя бы один STEP обязателен. Exercise key максимум 40, суммарный exercise.step key максимум 80. STEP допускается только внутри STEP_EXERCISE; каждый шаг сохраняется отдельно.

## 9. FUNCTION_PLOT

~~~text
[FUNCTION_PLOT]
{"title":"Парабола и прямая","functions":[{"expression":"x^2-4","label":"y=x²−4"},{"expression":"2x","label":"y=2x"}],"x_min":-4,"x_max":4,"y_min":-5,"y_max":12,"points":[{"x":2,"y":4,"label":"(2; 4)"}],"lines":[{"axis":"x","value":0}],"intervals":[{"x_min":-2,"x_max":2}],"show_intersections":true}
[/FUNCTION_PLOT]
~~~

JSON максимум 12,000 символов. functions — массив 1…4 объектов expression/optional label. Optional поля: title; оси x_min/x_max/y_min/y_max внутри −1000…1000, min<max; aspect equal/stretch; points ≤30; lines ≤12 с axis x/y; intervals ≤12; show_intersections. Expression до 160 символов, безопасный arithmetic AST с x. JavaScript не принимается. Сэмплирование 360 интервалов; intersections approximate, разрывы фильтруются эвристически. Pan/zoom и CAS точность отсутствуют.

## 10. GEOMETRY

~~~text
[GEOMETRY]
{"title":"Прямоугольный треугольник","items":[{"type":"point","name":"A","x":100,"y":300},{"type":"point","name":"B","x":100,"y":100},{"type":"point","name":"C","x":360,"y":300},{"type":"segment","from":"A","to":"B","equal_marks":1},{"type":"segment","from":"A","to":"C","equal_marks":1},{"type":"segment","from":"B","to":"C"},{"type":"polygon","points":["A","B","C"],"fill":"#c7d2fe"},{"type":"angle","a":"B","vertex":"A","b":"C","right":true}]}
[/GEOMETRY]
~~~

Items: point (name, x, y, optional label); segment/line/ray (from/to/color; equal_marks 1…3 для segment); circle (center/radius/color); polygon (3…12 имён точек, fill/color); angle (a/vertex/b, optional radius 8…80, right=true). ViewBox 640×420; координаты x=0…640, y=0…420; максимум 60 items/30 points; уникальное имя до 12 chars; цвета только hex. Только 2D. Сложную стереометрию отдайте как безопасный asset.

## 11. Изображения

Объявление в manifest группы:

~~~json
{"key":"parabola-scheme","path":"groups/01-foundation/assets/parabola.svg"}
~~~

В статье:

~~~markdown
![Парабола с вершиной и осью симметрии](asset:parabola-scheme)
Подпись: вершина — точка минимума.
~~~

Поддерживаются PNG/JPG/JPEG/WebP/SVG, GIF пакетно не поддержан. SVG sanitizes; raw inline SVG запрещён. Валидируются path, размер, формат, сигнатуры некоторых raster formats. Asset объявляется в той же группе, alt обязателен. Используйте локальные файлы и стабильные ключи; внешние URLs не гарантируют долговечность импорта.

## 12. Код и старые конструкции

~~~text
[CODE lang="python"]
print(2 + 2)
[/CODE]

[CODE_RUNNER]
print(2 + 2)
[/CODE_RUNNER]
~~~

Эти маркеры сохранены для старых информатических материалов и исключены из math extraction. Не запускайте в них JS и не используйте как контейнер формул. Legacy REMEMBER/IMPORTANT/NOTE/WARNING/TIP/HOW_IT_WORKS/LEVEL сохраняют прежнее назначение.

## 13. Целостность и шаблон

Не меняйте course slug, article key, task_number и существующие checkpoint keys косметически. Новая семантика задания — новый key, иначе прежние сохранённые попытки останутся. Не переименовывайте group name без отдельного согласования. Отсутствие статьи в manifest не удаляет ее из DB. Package validate проверяет syntax/structure, но не математическую истинность и педагогическое качество — ответ должен быть независимо перепроверен.

Рекомендуемый skeleton:

~~~markdown
# Название темы

Цель, предварительные знания, обозначения.

## 1. Понятие

[DEFINITION title="Определение"]
Точное утверждение.
[/DEFINITION]

## 2. Теорема

[THEOREM title="Формулировка"]
Условия и результат.
[/THEOREM]

[PROOF title="Доказательство"]
Аргументы с формулами.
[/PROOF]

## 3. Формула и таблица

[FORMULA title="Основная формула"]
$$...$$
[/FORMULA]

| Условие | Действие | Вывод |
|---|---|---|
| ... | ... | ... |

## 4. График, чертёж или изображение

Пояснение, затем FUNCTION_PLOT/GEOMETRY JSON или asset.

## 5. Пример и решение

[EXAMPLE title="Условие"]
...
[/EXAMPLE]

[SOLUTION title="Показать полный разбор"]
Шаг 1. ...
$$...$$
Шаг 2. ...
[/SOLUTION]

## 6. Самопроверка

[CHECKPOINT key="topic-check-1" question="..." options="...|...|..." answer="..." explanation="..." hint="..."]

[INTERACTIVE type="math" key="topic-answer-1" prompt="..." answer="..." validator="fraction" explanation="..." hint="..."]

[STEP_EXERCISE key="topic-steps" title="..."]
[STEP key="step-1" prompt="..." answer="..." validator="numeric"]
[STEP key="step-2" prompt="..." answer="..." validator="numeric"]
[/STEP_EXERCISE]

## Итог

[SUMMARY title="Главное"]
Алгоритм и основные выводы.
[/SUMMARY]
~~~

## 14. Передача

Передавайте полный пакет каталогом/архивом с manifest, отдельными Markdown-файлами и assets. В сообщении укажите стабильный course slug, диапазон номеров, keys добавленных/изменённых статей, версию пакета и редакционное состояние. Для импорта одного md без полного manifest недостаточно: валидатор проверяет уникальность номера и ключей относительно курса.

Перед импортом требуйте validate: valid=true, latex_checked=true, issues=[]; затем HTML preview и мобильную проверку. Команды описаны в THEORY_MATH_IMPORT_GUIDE.md. Не обходите ошибки SQL или прямой публикацией.
