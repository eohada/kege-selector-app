"""Pinned results from the independent synthetic Knowledge Base v5 spot audit.

The tests re-run each deterministic case. A result only applies to the exact
immutable knowledge version listed here; later edits require a new audit run.
"""

TECHNICAL_AUDIT_RECORDED_AT = "2026-10-23"

TECHNICAL_AUDIT_CASES = (
    {
        "case_id": "logic-boundary-new-values",
        "stable_key": "ege.inf.logic-boundaries.v1",
        "version_no": 3,
        "content_sha256": "5390809d1ee21f224907c774284ddf726b7e8cae2f548cba1c75315dbdedda1c",
        "domain": "Логика",
        "method": "Независимая таблица результатов для > 0 и >= 0.",
        "input": {"values": [-3, 0, 8]},
        "observed": {"positive": [False, False, True], "nonnegative": [False, True, True]},
        "scope": "Проверяет эти граничные значения, но не все выражения и программы.",
    },
    {
        "case_id": "number-base-round-trip",
        "stable_key": "ege.inf.positional-number-systems.v1",
        "version_no": 3,
        "content_sha256": "56b31d41906fe19558945968bd56783295af6e4337c96a45a2c8b849b9899292",
        "domain": "Системы счисления",
        "method": "Python int(..., 2) и форматирование шестнадцатеричного числа.",
        "input": {"binary": "101101101", "decimal": 236},
        "observed": {"binary_decimal": 365, "hexadecimal": "EC"},
        "scope": "Проверяет два целых числа; не проверяет все основания и дробные записи.",
    },
    {
        "case_id": "spreadsheet-new-selection",
        "stable_key": "ege.inf.spreadsheet-aggregates.v1",
        "version_no": 3,
        "content_sha256": "119a9e561e8d8598d97b559e4e5bda04ba9e516f1a5c84eaa786b308de32b592",
        "domain": "Электронные таблицы",
        "method": "Независимый расчёт фильтра, количества и агрегатов стандартными средствами Python.",
        "input": {"rows": [{"include": True, "value": 11}, {"include": False, "value": 100}, {"include": True, "value": 15}, {"include": True, "value": 21}]},
        "observed": {"count": 3, "sum": 47, "minimum": 11, "maximum": 21, "mean": 15.666666666666666},
        "scope": "Проверяет арифметику синтетической выборки, но не файл Excel или диапазон конкретной задачи.",
    },
    {
        "case_id": "python-negative-parity",
        "stable_key": "ege.inf.python-integer-parity.v1",
        "version_no": 3,
        "content_sha256": "8ea6ba937fc0844640bcb27a16dd6f92c0e22ff4176a9966043fab8d04ff7ba9",
        "domain": "Программирование",
        "method": "Выполнение Python 3 для % 2 и независимое сравнение с битовой проверкой.",
        "input": {"values": [-1001, -1000, -1, 0, 1, 1000, 1001]},
        "observed": {"odd": [True, False, True, False, True, False, True]},
        "scope": "Подтверждает чётность этих Python int; не переносится на другие языки.",
    },
    {
        "case_id": "graph-degree-handshake",
        "stable_key": "ege.inf.graph-degree.v1",
        "version_no": 1,
        "content_sha256": "dbd6671bc89b660543360799589ccc09033e0b9d46477b124fbad01d3f904e66",
        "domain": "Графы",
        "method": "Подсчёт степеней по списку рёбер и проверка леммы о сумме степеней.",
        "input": {"vertices": ["A", "B", "C", "D", "E"], "edges": [["A", "B"], ["A", "C"], ["B", "C"], ["C", "D"]]},
        "observed": {"degrees": {"A": 2, "B": 2, "C": 3, "D": 1, "E": 0}, "degree_sum": 8, "edge_count": 4},
        "scope": "Проверяет один конечный простой неориентированный граф.",
    },
    {
        "case_id": "ipv4-new-prefix-boundary",
        "stable_key": "ege.inf.ip-prefix-mask.v1",
        "version_no": 3,
        "content_sha256": "af89f4cce84f3a3ea190adc65e4e95bb74b945fdf49d411a04caefeebcbd40d1",
        "domain": "Компьютерные сети",
        "method": "Стандартная библиотека Python ipaddress.",
        "input": {"address": "10.42.19.173/27"},
        "observed": {"network": "10.42.19.160", "broadcast": "10.42.19.191", "addresses": 32, "hosts": 30},
        "scope": "Проверяет обычную /27-подсеть, не особые правила /31 и /32.",
    },
    {
        "case_id": "sql-join-new-data",
        "stable_key": "ege.inf.sql-relational-query.v1",
        "version_no": 1,
        "content_sha256": "a6cbb3882244d39b344b64c553f44b19a7320174d15af68220d3eac7b5b867d9",
        "domain": "SQL",
        "method": "SQLite in-memory: JOIN по ID, GROUP BY, COUNT и SUM.",
        "input": {"students": [["S1", "Ira"], ["S2", "Lev"]], "scores": [["S1", 4], ["S1", 5], ["S2", 3]]},
        "observed": {"rows": [["Ira", 2, 9], ["Lev", 1, 3]]},
        "scope": "Проверяет запрос в SQLite на двух синтетических таблицах, не все SQL-диалекты.",
    },
)

TECHNICAL_AUDIT_V6_RECORDED_AT = "2026-10-23"
TECHNICAL_AUDIT_V6_CASES = (
    {
        "case_id": "v6-logic-precedence-counterexample",
        "stable_key": "ege.inf.logic-boundaries.v1",
        "version_no": 3,
        "content_sha256": "5390809d1ee21f224907c774284ddf726b7e8cae2f548cba1c75315dbdedda1c",
        "domain": "Алгебра логики",
        "method": "Полный перебор восьми наборов для трёх булевых переменных.",
        "input": {"expressions": ["(A or B) and C", "A or (B and C)"], "distinguishing_row": [True, False, False]},
        "observed": {
            "left": False, "right": True, "truth_table_rows": 8,
            "left_outputs": [False, False, False, True, False, True, False, True],
            "right_outputs": [False, False, False, True, True, True, True, True],
        },
        "scope": "Опровергает эквивалентность этой пары выражений; не проверяет формализацию любого словесного условия.",
    },
    {
        "case_id": "v6-number-base-seven-round-trip",
        "stable_key": "ege.inf.positional-number-systems.v1",
        "version_no": 3,
        "content_sha256": "56b31d41906fe19558945968bd56783295af6e4337c96a45a2c8b849b9899292",
        "domain": "Системы счисления",
        "method": "Независимое разложение по степеням 7 и обратное деление с остатком.",
        "input": {"base7": "431", "decimal": 218},
        "observed": {"expanded_value": 218, "reverse_base7": "431", "digits_valid": True},
        "scope": "Проверяет один новый целочисленный пример в основании 7, не все основания и дробные числа.",
    },
    {
        "case_id": "v6-spreadsheet-filtered-duplicate-values",
        "stable_key": "ege.inf.spreadsheet-aggregates.v1",
        "version_no": 3,
        "content_sha256": "119a9e561e8d8598d97b559e4e5bda04ba9e516f1a5c84eaa786b308de32b592",
        "domain": "Электронные таблицы",
        "method": "Независимая фильтрация и расчёт агрегатов в Python.",
        "input": {"header_row": 1, "values": [5, 8, 12, 12, 17], "condition": ">= 10"},
        "observed": {"selected": [12, 12, 17], "count": 3, "sum": 41, "mean": 13.666666666666666, "minimum": 12, "maximum": 17},
        "scope": "Проверяет выборку и арифметику; не исполняет формулу Excel и не определяет политику для пустых ячеек.",
    },
    {
        "case_id": "v6-python-negative-integer-semantics",
        "stable_key": "ege.inf.python-integer-parity.v1",
        "version_no": 3,
        "content_sha256": "8ea6ba937fc0844640bcb27a16dd6f92c0e22ff4176a9966043fab8d04ff7ba9",
        "domain": "Алгоритмы Python",
        "method": "Исполнение Python 3 и независимая проверка тождества divmod.",
        "input": {"values": [-17, -18, -1, 0, 1, 18, 19]},
        "observed": {"odd_by_modulo": [True, False, True, False, True, False, True], "odd_by_bit": [True, False, True, False, True, False, True], "divmod_minus17_by_2": [-9, 1]},
        "scope": "Подтверждает значения для Python int; не переносит семантику на другой язык или пользовательский тип.",
    },
    {
        "case_id": "v6-graph-isolated-vertex",
        "stable_key": "ege.inf.graph-degree.v1",
        "version_no": 1,
        "content_sha256": "dbd6671bc89b660543360799589ccc09033e0b9d46477b124fbad01d3f904e66",
        "domain": "Графы",
        "method": "Независимый подсчёт по рёбрам и проверка суммы степеней.",
        "input": {"vertices": ["A", "B", "C", "D", "E", "F"], "edges": [["A", "B"], ["A", "C"], ["B", "C"], ["C", "D"], ["D", "E"]]},
        "observed": {"degrees": {"A": 2, "B": 2, "C": 3, "D": 2, "E": 1, "F": 0}, "degree_sum": 10, "twice_edges": 10},
        "scope": "Проверяет один простой неориентированный граф с изолированной вершиной.",
    },
    {
        "case_id": "v6-ipv4-prefix-boundary-29",
        "stable_key": "ege.inf.ip-prefix-mask.v1",
        "version_no": 3,
        "content_sha256": "af89f4cce84f3a3ea190adc65e4e95bb74b945fdf49d411a04caefeebcbd40d1",
        "domain": "Компьютерные сети",
        "method": "Python ipaddress; отдельно сверена нормативная оговорка для /31 с RFC 3021.",
        "input": {"address": "192.0.2.250/29", "point_to_point_prefix": "192.0.2.8/31"},
        "observed": {"network": "192.0.2.248", "broadcast": "192.0.2.255", "addresses": 8, "ordinary_hosts": 6, "rfc3021_point_to_point_hosts": ["192.0.2.8", "192.0.2.9"]},
        "scope": "Арифметика проверена для /29; использование двух адресов /31 относится только к point-to-point по RFC 3021.",
    },
    {
        "case_id": "v6-sql-left-join-duplicate-names",
        "stable_key": "ege.inf.sql-relational-query.v1",
        "version_no": 1,
        "content_sha256": "a6cbb3882244d39b344b64c553f44b19a7320174d15af68220d3eac7b5b867d9",
        "domain": "SQL",
        "method": "Выполнение запроса в SQLite in-memory с LEFT JOIN, ключами и явной обработкой NULL.",
        "input": {"people": [[1, "Alex"], [2, "Alex"], [3, "Bea"]], "orders": [[101, 1, 4], [102, 1, 6], [103, 2, 9]]},
        "observed": {"rows": [["Alex", 1, 2, 10], ["Alex", 2, 1, 9], ["Bea", 3, 0, 0]]},
        "scope": "Проверяет один запрос SQLite и сохранение строки без заказов; не покрывает все SQL-диалекты.",
    },
)

EXPERT_PILOT_DOSSIERS = (
    {
        "stable_key": "ege.inf.logic-boundaries.v1", "version_no": 3,
        "content_sha256": "5390809d1ee21f224907c774284ddf726b7e8cae2f548cba1c75315dbdedda1c",
        "technical_case_id": "v6-logic-precedence-counterexample", "scenario_id": "A",
        "scenario": "Синтетическая ошибка: ученик считает (A or B) and C и A or (B and C) равными без скобок.",
        "observed_evidence": "При A=True, B=False, C=False результаты False и True; различающая строка опровергает равносильность.",
        "diagnostic": "Попросить вычислить обе части по отдельности на различающей строке; так отделяется приоритет операций от ошибки в таблице истинности.",
        "next_action": "Дать новую пару выражений и попросить самостоятельно найти различающую строку.",
        "human_questions": ["Достаточно ли таблицы истинности для объяснения этой цели или ожидается эквивалентное преобразование?", "Оставить ли связь с заданием 15 только предварительной до проверки конкретного условия?"],
        "priority_note": "ФИПИ-2026 связывает построение таблиц истинности с заданием 2, а законы логики — с заданием 15; текущая карточка охватывает обе операции, поэтому связь с номером задания нельзя считать точной без условия.",
    },
    {
        "stable_key": "ege.inf.positional-number-systems.v1", "version_no": 3,
        "content_sha256": "56b31d41906fe19558945968bd56783295af6e4337c96a45a2c8b849b9899292",
        "technical_case_id": "v6-number-base-seven-round-trip", "scenario_id": "B",
        "scenario": "Синтетическое самостоятельное решение: ученик переводит 431₇ в десятичную систему разложением по степеням, затем проверяет обратным делением.",
        "observed_evidence": "4·7²+3·7+1=218; обратное деление даёт остатки 1,3,4 и запись 431₇.",
        "diagnostic": "Проверить допустимость каждой цифры и попросить объяснить, почему остатки записываются в обратном порядке.",
        "next_action": "Дать новое основание и попросить показать оба направления перевода без подсказки.",
        "human_questions": ["Засчитывать ли правильный результат без разложения, если задание требует объяснить способ?", "Какие основания и диапазон чисел следует включить в утверждённую учебную цель?"],
        "priority_note": "Позиционные системы прямо названы ФИПИ-2026 для задания 14; карточка пока не охватывает дробные записи.",
    },
    {
        "stable_key": "ege.inf.spreadsheet-aggregates.v1", "version_no": 3,
        "content_sha256": "119a9e561e8d8598d97b559e4e5bda04ba9e516f1a5c84eaa786b308de32b592",
        "technical_case_id": "v6-spreadsheet-filtered-duplicate-values", "scenario_id": "C",
        "scenario": "Синтетическое исправление после подсказки: ученик сначала агрегирует весь диапазон, затем после просьбы отметить строки ≥10 выбирает 12, 12 и 17.",
        "observed_evidence": "После подсказки выборка верна; это подтверждает исправление с помощью, но не самостоятельное выполнение.",
        "diagnostic": "На следующей выборке попросить сначала назвать строки и только затем диапазон формулы; отдельно проверить среднее и число включённых строк.",
        "next_action": "Дать параллельную таблицу с другим условием отбора без подсказки; не делать вывод об устойчивом навыке по исправленному примеру.",
        "human_questions": ["Какие правила оценивания применяются к пустым ячейкам и текстовым значениям в конкретной задаче?", "Когда нужно явно требовать локализованную формулу, а когда достаточно вычисленного результата?"],
        "priority_note": "Числовая обработка в электронных таблицах указана ФИПИ-2026 как задание 9; импортированное задание и точный диапазон всё равно нужно проверить преподавателю.",
    },
    {
        "stable_key": "ege.inf.python-integer-parity.v1", "version_no": 3,
        "content_sha256": "8ea6ba937fc0844640bcb27a16dd6f92c0e22ff4176a9966043fab8d04ff7ba9",
        "technical_case_id": "v6-python-negative-integer-semantics", "scenario_id": "A",
        "scenario": "Синтетическая ошибка: ученик переносит правила другого языка и утверждает, что проверка n % 2 != 0 не работает для отрицательных Python int.",
        "observed_evidence": "Для n=-17 Python даёт -17 % 2 = 1; условие n % 2 != 0 и проверка младшего бита распознают нечётность.",
        "diagnostic": "До запуска попросить предсказать // и % для отрицательного числа, затем проверить тождество a=(a//b)·b+(a%b).",
        "next_action": "Предложить объяснить семантику Python на новом отрицательном входе и отдельно сравнить другой язык только при наличии его спецификации.",
        "human_questions": ["Требует ли учебная цель объяснять битовое представление или только выбрать надёжную проверку чётности?", "Ограничить ли проверяемый домен именно встроенным типом int?"],
        "priority_note": "ФИПИ-2026 относит создание программы для обработки целочисленной информации к заданию 25; локальная карточка проверяет узкую семантику Python, а не всю программу задания.",
    },
    {
        "stable_key": "ege.inf.graph-degree.v1", "version_no": 1,
        "content_sha256": "dbd6671bc89b660543360799589ccc09033e0b9d46477b124fbad01d3f904e66",
        "technical_case_id": "v6-graph-isolated-vertex", "scenario_id": "B",
        "scenario": "Синтетическое самостоятельное решение: ученик считает степени по рёбрам и не забывает изолированную вершину F.",
        "observed_evidence": "Степени 2,2,3,2,1,0; сумма 10 совпадает с удвоенным числом пяти рёбер.",
        "diagnostic": "Сравнить подсчёт по списку рёбер с числом единиц строки матрицы; уточнить направленность и наличие петель.",
        "next_action": "Дать новый граф в другом представлении и попросить назвать область применимости проверки суммы степеней.",
        "human_questions": ["Нужно ли включать изолированные вершины, не перечисленные в списке рёбер?", "Какую модель ориентированного графа преподаватель хочет видеть в этой карточке?"],
        "priority_note": "Связь с заданием 1 остаётся предварительной: номер охватывает разные информационные модели, а карточка касается только базовых степеней неориентированного графа.",
    },
    {
        "stable_key": "ege.inf.ip-prefix-mask.v1", "version_no": 3,
        "content_sha256": "af89f4cce84f3a3ea190adc65e4e95bb74b945fdf49d411a04caefeebcbd40d1",
        "technical_case_id": "v6-ipv4-prefix-boundary-29", "scenario_id": "A",
        "scenario": "Синтетическая ошибка: для обычного /29 ученик выбирает предыдущий блок .240 вместо блока, содержащего адрес .250.",
        "observed_evidence": "Шаг блока 8; адрес сети 192.0.2.248, broadcast 192.0.2.255. Правило /31 отдельно ограничено point-to-point RFC 3021.",
        "diagnostic": "Попросить выписать соседние границы кратные 8 и отдельно уточнить, спрашивают ли размер блока или допустимые узловые адреса.",
        "next_action": "Дать новый адрес на границе блока и сравнить обычную подсеть /30 с point-to-point /31.",
        "human_questions": ["Как формулировать число обычных узлов для условий, где роль сети явно не задана?", "Достаточно ли RFC 3021 как оговорки для ЕГЭ или её лучше оставить справочным расширением?"],
        "priority_note": "Официальный навигатор ФИПИ прямо связывает маску подсети с заданием 13; текущая карточка корректно разделяет размер блока и узловые адреса.",
    },
    {
        "stable_key": "ege.inf.sql-relational-query.v1", "version_no": 1,
        "content_sha256": "a6cbb3882244d39b344b64c553f44b19a7320174d15af68220d3eac7b5b867d9",
        "technical_case_id": "v6-sql-left-join-duplicate-names", "scenario_id": "D",
        "scenario": "Недостаточно данных: ученик прислал только запрос JOIN по имени, но нет схемы таблиц, ключей, данных и ожидаемого результата.",
        "observed_evidence": "Нельзя подтвердить корректность связи или число строк. Синтетический контроль показывает, что дублирующиеся имена не заменяют ID, а LEFT JOIN сохраняет строку без заказов.",
        "diagnostic": "Запросить схему, ключи, пару строк данных и требуемую семантику пустых групп до оценки.",
        "next_action": "Не ставить диагноз по одному фрагменту SQL; проверить тот же запрос на минимальном контрпримере с одинаковыми именами.",
        "human_questions": ["Какой SQL-диалект и какая редакция движка нужны в учебных заданиях?", "Следует ли для пустого набора показывать NULL или 0 в конкретном учебном контракте?"],
        "priority_note": "ФИПИ-2026 относит поиск в реляционных базах данных к заданию 3; текущая карточка не охватывает транзакции, окна и различия диалектов.",
    },
)


def audit_results_for(entries):
    current_versions = {item["stable_key"]: item for item in entries}
    reports = [{
        **case,
        "recorded_at": TECHNICAL_AUDIT_RECORDED_AT,
        "audit_series": "v5 spot checks",
        "current_version_no": (current_versions.get(case["stable_key"]) or {}).get("version_no"),
        "current_content_sha256": (current_versions.get(case["stable_key"]) or {}).get("content_sha256"),
        "matches_current_version": (
            (current_versions.get(case["stable_key"]) or {}).get("version_no") == case["version_no"]
            and (current_versions.get(case["stable_key"]) or {}).get("content_sha256") == case["content_sha256"]
        ),
        "result": "passed",
        "result_basis": "Повторяемый синтетический технический тест; не педагогическое утверждение и не экспертное утверждение карточки.",
    } for case in TECHNICAL_AUDIT_CASES]
    reports.extend({
        **case,
        "recorded_at": TECHNICAL_AUDIT_V6_RECORDED_AT,
        "audit_series": "v6 expert pilot",
        "current_version_no": (current_versions.get(case["stable_key"]) or {}).get("version_no"),
        "current_content_sha256": (current_versions.get(case["stable_key"]) or {}).get("content_sha256"),
        "matches_current_version": (
            (current_versions.get(case["stable_key"]) or {}).get("version_no") == case["version_no"]
            and (current_versions.get(case["stable_key"]) or {}).get("content_sha256") == case["content_sha256"]
        ),
        "result": "passed",
        "result_basis": "Новая синтетическая проверка v6, повторяемая unit-тестом; не запуск Code Judge и не экспертное утверждение материала.",
    } for case in TECHNICAL_AUDIT_V6_CASES)
    return reports


def expert_pilot_dossiers_for(entries):
    current_versions = {item["stable_key"]: item for item in entries}
    return [{
        **dossier,
        "current_version_no": (current_versions.get(dossier["stable_key"]) or {}).get("version_no"),
        "current_content_sha256": (current_versions.get(dossier["stable_key"]) or {}).get("content_sha256"),
        "matches_current_version": (
            (current_versions.get(dossier["stable_key"]) or {}).get("version_no") == dossier["version_no"]
            and (current_versions.get(dossier["stable_key"]) or {}).get("content_sha256") == dossier["content_sha256"]
        ),
        "review_status": "awaiting_teacher_expert_review",
    } for dossier in EXPERT_PILOT_DOSSIERS]
