"""Банк заданий гостевой диагностики по программированию на Python.

Содержит 3 независимых варианта по 20 заданий.
Задания строго опираются на 30 тем учебной программы по программированию
(Темы 101–130 из scripts/seed_comprehensive_python_theory.py):
101: Синтаксис Python и вывод print()
102: Переменные и базовая арифметика
103: Деление (/), целочисленное (//) и остаток (%)
104: Типы данных (int, float, str, bool) и их преобразование
105: Ввод данных: функция input()
106: Продвинутый вывод print(): параметры sep, end, f-строки
107: Операторы сравнения и логические выражения
108: Встроенные функции: min(), max(), sum(), len()
109: Ветвление if-else
110: Каскадные условия: if-elif-else
111: Сложные логические связки: and, or, not
112: Паттерны проверки условий в ЕГЭ (делимость, последняя цифра)
113: Цикл for и функция range()
114: Цикл while и динамические условия остановки
115: Управление циклом: break и continue
116: Разбор числа по цифрам в цикле while
117: Вложенные циклы и перебор
118: Строки в Python: создание, длина len(), обход
119: Индексация и срезы строк [start:stop:step]
120: Методы строк: .count(), .find(), оператор in
121: Методы модификации строк: .replace(), .split(), .strip()
122: Списки: создание, индексация, изменение
123: Добавление и удаление элементов: .append(), .pop(), .remove()
124: Поиск и сортировка: .sort() против sorted()
125: Функции len(), min(), max(), sum() со списками
126: Генераторы списков (List Comprehensions)
127: Объявление функций: def, параметры, аргументы
128: Оператор return и возврат значений
129: Функции-предикаты: делители и проверка свойств
130: Область видимости: локальные и глобальные переменные
"""
from __future__ import annotations


def get_programming_variant_specs(variant_index: int) -> list[dict]:
    """Возвращает спецификацию 20 заданий одного из 3 вариантов по программированию."""
    variants = [
        _build_variant_1(),
        _build_variant_2(),
        _build_variant_3(),
    ]
    return variants[variant_index % len(variants)]


def _build_variant_1() -> list[dict]:
    return [
        {
            "task_number": 1,
            "skill": "python.topic_101_print",
            "type": "short_text",
            "prompt": "<p><strong>Задание 1 (Вывод print).</strong> Что выведет следующий фрагмент программы?</p><pre><code>print(10, 20, 30)</code></pre>",
            "options": [],
            "expected": "10 20 30",
        },
        {
            "task_number": 2,
            "skill": "python.topic_102_arithmetic",
            "type": "short_text",
            "prompt": "<p><strong>Задание 2 (Базовая арифметика).</strong> Какое число будет напечатано в результате выполнения кода?</p><pre><code>a = 3\nb = 4\nprint(a ** 2 + b ** 2)</code></pre>",
            "options": [],
            "expected": "25",
        },
        {
            "task_number": 3,
            "skill": "python.topic_103_division",
            "type": "short_text",
            "prompt": "<p><strong>Задание 3 (Деление // и %).</strong> Чему равен результат вычисления выражения?</p><pre><code>print(47 // 5 + 47 % 5)</code></pre>",
            "options": [],
            "expected": "11",
        },
        {
            "task_number": 4,
            "skill": "python.topic_104_types",
            "type": "choice",
            "prompt": "<p><strong>Задание 4 (Типы данных).</strong> Какой тип данных будет иметь переменная <code>x</code> после выполнения строки?</p><pre><code>x = \"123\" + \"45\"</code></pre>",
            "options": ["int", "str", "float", "list"],
            "expected": "str",
        },
        {
            "task_number": 5,
            "skill": "python.topic_106_print_format",
            "type": "short_text",
            "prompt": "<p><strong>Задание 5 (Параметры sep и f-строки).</strong> Что выведет следующая программа?</p><pre><code>day = 19\nmonth = 10\nprint(f\"{day:02d}-{month:02d}\")</code></pre>",
            "options": [],
            "expected": "19-10",
        },
        {
            "task_number": 6,
            "skill": "python.topic_107_comparisons",
            "type": "choice",
            "prompt": "<p><strong>Задание 6 (Операторы сравнения).</strong> Какое значение вернёт выражение <code>3 <= 5 < 10</code> в Python?</p>",
            "options": ["True", "False", "None", "SyntaxError"],
            "expected": "True",
        },
        {
            "task_number": 7,
            "skill": "python.topic_108_builtin_funcs",
            "type": "short_text",
            "prompt": "<p><strong>Задание 7 (Встроенные функции).</strong> Что напечатает программа?</p><pre><code>nums = [14, 2, 88, -5, 30]\nprint(max(nums) + min(nums))</code></pre>",
            "options": [],
            "expected": "83",
        },
        {
            "task_number": 8,
            "skill": "python.topic_109_ifelse",
            "type": "short_text",
            "prompt": "<p><strong>Задание 8 (Ветвление if-else).</strong> Какое число выведет программа?</p><pre><code>x = 15\nif x % 2 == 0:\n    res = x // 2\nelse:\n    res = x * 3 + 1\nprint(res)</code></pre>",
            "options": [],
            "expected": "46",
        },
        {
            "task_number": 9,
            "skill": "python.topic_111_logical_ops",
            "type": "choice",
            "prompt": "<p><strong>Задание 9 (Связки and, or, not).</strong> Что напечатает код?</p><pre><code>a = True\nb = False\nprint(not a or b or (5 > 2))</code></pre>",
            "options": ["True", "False", "1", "0"],
            "expected": "True",
        },
        {
            "task_number": 10,
            "skill": "python.topic_112_ege_conditions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 10 (Паттерны условий в ЕГЭ).</strong> Сколько чисел из диапазона от 1 до 50 (включительно) кратны 3 и заканчиваются на 4?</p>",
            "options": [],
            "expected": "2",
        },
        {
            "task_number": 11,
            "skill": "python.topic_113_for_range",
            "type": "short_text",
            "prompt": "<p><strong>Задание 11 (Цикл for и range).</strong> Что выведет программа?</p><pre><code>s = 0\nfor i in range(1, 10, 2):\n    s += i\nprint(s)</code></pre>",
            "options": [],
            "expected": "25",
        },
        {
            "task_number": 12,
            "skill": "python.topic_114_while_loops",
            "type": "short_text",
            "prompt": "<p><strong>Задание 12 (Цикл while).</strong> Сколько раз выполнится тело цикла?</p><pre><code>n = 32\ncount = 0\nwhile n > 1:\n    n //= 2\n    count += 1\nprint(count)</code></pre>",
            "options": [],
            "expected": "5",
        },
        {
            "task_number": 13,
            "skill": "python.topic_115_break_continue",
            "type": "short_text",
            "prompt": "<p><strong>Задание 13 (break и continue).</strong> Что напечатает код?</p><pre><code>total = 0\nfor x in range(1, 8):\n    if x == 4:\n        continue\n    if x == 6:\n        break\n    total += x\nprint(total)</code></pre>",
            "options": [],
            "expected": "11",
        },
        {
            "task_number": 14,
            "skill": "python.topic_116_digit_extraction",
            "type": "short_text",
            "prompt": "<p><strong>Задание 14 (Разбор числа по цифрам).</strong> Что напечатает код?</p><pre><code>n = 7425\nsum_even = 0\nwhile n > 0:\n    d = n % 10\n    if d % 2 == 0:\n        sum_even += d\n    n //= 10\nprint(sum_even)</code></pre>",
            "options": [],
            "expected": "6",
        },
        {
            "task_number": 15,
            "skill": "python.topic_118_strings_basics",
            "type": "short_text",
            "prompt": "<p><strong>Задание 15 (Строки и длина).</strong> Что выведет выражение?</p><pre><code>s = \"ЕГЭ\" * 3\nprint(len(s))</code></pre>",
            "options": [],
            "expected": "9",
        },
        {
            "task_number": 16,
            "skill": "python.topic_119_string_slices",
            "type": "short_text",
            "prompt": "<p><strong>Задание 16 (Срезы строк).</strong> Что выведет срез строки?</p><pre><code>s = \"ИНФОРМАТИКА\"\nprint(s[2:7])</code></pre>",
            "options": [],
            "expected": "ФОРМА",
        },
        {
            "task_number": 17,
            "skill": "python.topic_121_string_methods",
            "type": "short_text",
            "prompt": "<p><strong>Задание 17 (Методы строк replace и count).</strong> Что выведет программа?</p><pre><code>s = \"111222111\"\ns = s.replace(\"11\", \"2\", 2)\nprint(s)</code></pre>",
            "options": [],
            "expected": "22222111",
        },
        {
            "task_number": 18,
            "skill": "python.topic_123_list_mutation",
            "type": "short_text",
            "prompt": "<p><strong>Задание 18 (Добавление и удаление в списках).</strong> Что напечатает программа?</p><pre><code>lst = [10, 20, 30]\nlst.append(40)\nx = lst.pop(1)\nprint(sum(lst))</code></pre>",
            "options": [],
            "expected": "80",
        },
        {
            "task_number": 19,
            "skill": "python.topic_126_comprehensions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 19 (Генераторы списков).</strong> Что выведет программа?</p><pre><code>cubes = [x ** 3 for x in range(1, 5) if x % 2 == 0]\nprint(sum(cubes))</code></pre>",
            "options": [],
            "expected": "72",
        },
        {
            "task_number": 20,
            "skill": "python.topic_128_return",
            "type": "short_text",
            "prompt": "<p><strong>Задание 20 (Функции и return).</strong> Какое значение вернёт и напечатает программа?</p><pre><code>def calc(a, b):\n    return a * 2 + b * 3\n\nprint(calc(4, 5))</code></pre>",
            "options": [],
            "expected": "23",
        },
    ]


def _build_variant_2() -> list[dict]:
    return [
        {
            "task_number": 1,
            "skill": "python.topic_101_print",
            "type": "short_text",
            "prompt": "<p><strong>Задание 1 (Вывод print).</strong> Что напечатает программа при параметре <code>end='*'</code>?</p><pre><code>print(\"A\", end=\"*\")\nprint(\"B\", end=\"*\")\nprint(\"C\")</code></pre>",
            "options": [],
            "expected": "A*B*C",
        },
        {
            "task_number": 2,
            "skill": "python.topic_103_division",
            "type": "short_text",
            "prompt": "<p><strong>Задание 2 (Целочисленное деление).</strong> Чему равно значение выражения?</p><pre><code>print(1234 // 100 % 10)</code></pre>",
            "options": [],
            "expected": "2",
        },
        {
            "task_number": 3,
            "skill": "python.topic_104_types",
            "type": "short_text",
            "prompt": "<p><strong>Задание 3 (Преобразование типов).</strong> Что выведет программа?</p><pre><code>a = \"15\"\nb = 25\nprint(int(a) + b)</code></pre>",
            "options": [],
            "expected": "40",
        },
        {
            "task_number": 4,
            "skill": "python.topic_105_input",
            "type": "choice",
            "prompt": "<p><strong>Задание 4 (Ввод input).</strong> Какая строка правильно считывает целое число с клавиатуры в переменную <code>n</code>?</p>",
            "options": ["n = int(input())", "n = input(int)", "n = read_int()", "int n = input()"],
            "expected": "n = int(input())",
        },
        {
            "task_number": 5,
            "skill": "python.topic_106_print_format",
            "type": "short_text",
            "prompt": "<p><strong>Задание 5 (Параметр sep).</strong> Что выведет вызов?</p><pre><code>print(1, 2, 3, sep=\"::\")</code></pre>",
            "options": [],
            "expected": "1::2::3",
        },
        {
            "task_number": 6,
            "skill": "python.topic_107_comparisons",
            "type": "choice",
            "prompt": "<p><strong>Задание 6 (Операторы сравнения).</strong> Какой оператор в Python проверяет равенство двух значений?</p>",
            "options": ["==", "=", "===", "equals"],
            "expected": "==",
        },
        {
            "task_number": 7,
            "skill": "python.topic_108_builtin_funcs",
            "type": "short_text",
            "prompt": "<p><strong>Задание 7 (Встроенные функции).</strong> Что выведет программа?</p><pre><code>words = [\"егэ\", \"информатика\", \"код\"]\nprint(len(words) * min(len(w) for w in words))</code></pre>",
            "options": [],
            "expected": "9",
        },
        {
            "task_number": 8,
            "skill": "python.topic_110_elif",
            "type": "short_text",
            "prompt": "<p><strong>Задание 8 (Каскадные условия if-elif-else).</strong> Что напечатает код?</p><pre><code>x = 75\nif x >= 90:\n    res = \"A\"\nelif x >= 70:\n    res = \"B\"\nelif x >= 50:\n    res = \"C\"\nelse:\n    res = \"D\"\nprint(res)</code></pre>",
            "options": [],
            "expected": "B",
        },
        {
            "task_number": 9,
            "skill": "python.topic_111_logical_ops",
            "type": "short_text",
            "prompt": "<p><strong>Задание 9 (Приоритет логических операций).</strong> Чему равно <code>int(True and False or not False)</code>?</p>",
            "options": [],
            "expected": "1",
        },
        {
            "task_number": 10,
            "skill": "python.topic_112_ege_conditions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 10 (Паттерны условий в ЕГЭ).</strong> Сколько двузначных чисел делятся на 4 без остатка и НЕ делятся на 8?</p>",
            "options": [],
            "expected": "11",
        },
        {
            "task_number": 11,
            "skill": "python.topic_113_for_range",
            "type": "short_text",
            "prompt": "<p><strong>Задание 11 (Обратный range).</strong> Что выведет код?</p><pre><code>res = []\nfor i in range(10, 0, -3):\n    res.append(i)\nprint(res)</code></pre>",
            "options": [],
            "expected": "[10, 7, 4, 1]",
        },
        {
            "task_number": 12,
            "skill": "python.topic_114_while_loops",
            "type": "short_text",
            "prompt": "<p><strong>Задание 12 (Цикл while).</strong> Какое значение примет переменная <code>x</code> после завершения цикла?</p><pre><code>x = 1\nwhile x < 50:\n    x *= 3\nprint(x)</code></pre>",
            "options": [],
            "expected": "81",
        },
        {
            "task_number": 13,
            "skill": "python.topic_116_digit_extraction",
            "type": "short_text",
            "prompt": "<p><strong>Задание 13 (Произведение цифр числа).</strong> Что напечатает программа?</p><pre><code>n = 234\nprod = 1\nwhile n > 0:\n    prod *= (n % 10)\n    n //= 10\nprint(prod)</code></pre>",
            "options": [],
            "expected": "24",
        },
        {
            "task_number": 14,
            "skill": "python.topic_117_nested_loops",
            "type": "short_text",
            "prompt": "<p><strong>Задание 14 (Вложенные циклы).</strong> Сколько раз напечатается символ «*»?</p><pre><code>c = 0\nfor i in range(4):\n    for j in range(3):\n        c += 1\nprint(c)</code></pre>",
            "options": [],
            "expected": "12",
        },
        {
            "task_number": 15,
            "skill": "python.topic_119_string_slices",
            "type": "short_text",
            "prompt": "<p><strong>Задание 15 (Срез строки с шагом -1).</strong> Что выведет срез <code>s[::-1]</code>, если <code>s = \"PYTHON\"</code>?</p>",
            "options": [],
            "expected": "NOHTYP",
        },
        {
            "task_number": 16,
            "skill": "python.topic_120_string_find",
            "type": "short_text",
            "prompt": "<p><strong>Задание 16 (Методы count и find).</strong> Что выведет следующий код?</p><pre><code>s = \"abracadabra\"\nprint(s.count(\"a\"))</code></pre>",
            "options": [],
            "expected": "5",
        },
        {
            "task_number": 17,
            "skill": "python.topic_122_lists_indexing",
            "type": "short_text",
            "prompt": "<p><strong>Задание 17 (Отрицательные индексы в списках).</strong> Что выведет выражение?</p><pre><code>lst = [100, 200, 300, 400, 500]\nprint(lst[-2] + lst[1])</code></pre>",
            "options": [],
            "expected": "600",
        },
        {
            "task_number": 18,
            "skill": "python.topic_124_sort",
            "type": "short_text",
            "prompt": "<p><strong>Задание 18 (Сортировка списков).</strong> Что напечатает код?</p><pre><code>nums = [5, 2, 8, 1, 9]\nnums.sort(reverse=True)\nprint(nums[1])</code></pre>",
            "options": [],
            "expected": "8",
        },
        {
            "task_number": 19,
            "skill": "python.topic_126_comprehensions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 19 (Генератор списка).</strong> Чему равна длина полученного списка?</p><pre><code>a = [i for i in range(100) if i % 7 == 0]\nprint(len(a))</code></pre>",
            "options": [],
            "expected": "15",
        },
        {
            "task_number": 20,
            "skill": "python.topic_129_predicate_functions",
            "type": "choice",
            "prompt": "<p><strong>Задание 20 (Функции-предикаты).</strong> Что вернёт вызов <code>is_prime(9)</code> при такой реализации?</p><pre><code>def is_prime(n):\n    if n < 2:\n        return False\n    for d in range(2, int(n**0.5) + 1):\n        if n % d == 0:\n            return False\n    return True\n\nprint(is_prime(9))</code></pre>",
            "options": ["True", "False", "None", "Error"],
            "expected": "False",
        },
    ]


def _build_variant_3() -> list[dict]:
    return [
        {
            "task_number": 1,
            "skill": "python.topic_102_arithmetic",
            "type": "short_text",
            "prompt": "<p><strong>Задание 1 (Порядок действий).</strong> Чему равен результат вычисления выражения?</p><pre><code>print(2 + 3 * 4 ** 2)</code></pre>",
            "options": [],
            "expected": "50",
        },
        {
            "task_number": 2,
            "skill": "python.topic_103_division",
            "type": "short_text",
            "prompt": "<p><strong>Задание 2 (Остаток от деления).</strong> Какое число выведет программа?</p><pre><code>x = 256\nprint(x % 10 + x // 10 % 10)</code></pre>",
            "options": [],
            "expected": "11",
        },
        {
            "task_number": 3,
            "skill": "python.topic_104_types",
            "type": "choice",
            "prompt": "<p><strong>Задание 3 (Логический тип bool).</strong> Какое из следующих выражений вернёт <code>False</code>?</p>",
            "options": ["bool(0)", "bool(1)", "bool(\"False\")", "bool([0])"],
            "expected": "bool(0)",
        },
        {
            "task_number": 4,
            "skill": "python.topic_106_print_format",
            "type": "short_text",
            "prompt": "<p><strong>Задание 4 (f-строки и округление).</strong> Что выведет следующий фрагмент?</p><pre><code>val = 7 / 3\nprint(f\"{val:.2f}\")</code></pre>",
            "options": [],
            "expected": "2.33",
        },
        {
            "task_number": 5,
            "skill": "python.topic_107_comparisons",
            "type": "choice",
            "prompt": "<p><strong>Задание 5 (Операторы сравнения строк).</strong> Что вернёт выражение <code>\"apple\" < \"banana\"</code> в Python?</p>",
            "options": ["True", "False", "TypeError", "None"],
            "expected": "True",
        },
        {
            "task_number": 6,
            "skill": "python.topic_109_ifelse",
            "type": "short_text",
            "prompt": "<p><strong>Задание 6 (Тернарный оператор / ветвление).</strong> Что напечатает код?</p><pre><code>a = 18\nstatus = \"adult\" if a >= 18 else \"minor\"\nprint(status)</code></pre>",
            "options": [],
            "expected": "adult",
        },
        {
            "task_number": 7,
            "skill": "python.topic_110_elif",
            "type": "short_text",
            "prompt": "<p><strong>Задание 7 (Определение знака числа).</strong> Какое число выведет программа?</p><pre><code>def sign(n):\n    if n > 0:\n        return 1\n    elif n < 0:\n        return -1\n    return 0\n\nprint(sign(-42) + sign(10))</code></pre>",
            "options": [],
            "expected": "0",
        },
        {
            "task_number": 8,
            "skill": "python.topic_111_logical_ops",
            "type": "choice",
            "prompt": "<p><strong>Задание 8 (Логические законы де Моргана).</strong> Какое условие эквивалентно <code>not (x > 5 and y < 10)</code>?</p>",
            "options": [
                "x <= 5 or y >= 10",
                "x <= 5 and y >= 10",
                "x > 5 or y < 10",
                "not (x > 5) and not (y < 10)"
            ],
            "expected": "x <= 5 or y >= 10",
        },
        {
            "task_number": 9,
            "skill": "python.topic_112_ege_conditions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 9 (Паттерны условий в ЕГЭ).</strong> Сколько натуральных чисел $n$ от 10 до 99 обладают свойством: сумма их цифр равна 9?</p>",
            "options": [],
            "expected": "10",
        },
        {
            "task_number": 10,
            "skill": "python.topic_113_for_range",
            "type": "short_text",
            "prompt": "<p><strong>Задание 11 (Произведение нечётных чисел).</strong> Что выведет код?</p><pre><code>p = 1\nfor i in range(1, 6, 2):\n    p *= i\nprint(p)</code></pre>",
            "options": [],
            "expected": "15",
        },
        {
            "task_number": 11,
            "skill": "python.topic_114_while_loops",
            "type": "short_text",
            "prompt": "<p><strong>Задание 11 (Поиск степени двойки).</strong> Какое наименьшее $k$ сделает условие $2^k > 1000$ истинным?</p>",
            "options": [],
            "expected": "10",
        },
        {
            "task_number": 12,
            "skill": "python.topic_115_break_continue",
            "type": "short_text",
            "prompt": "<p><strong>Задание 12 (Оператор else у цикла while).</strong> Что напечатает код?</p><pre><code>i = 1\nwhile i < 4:\n    i += 1\nelse:\n    i *= 10\nprint(i)</code></pre>",
            "options": [],
            "expected": "40",
        },
        {
            "task_number": 13,
            "skill": "python.topic_116_digit_extraction",
            "type": "short_text",
            "prompt": "<p><strong>Задание 13 (Подсчёт максимальной цифры).</strong> Что выведет программа?</p><pre><code>n = 38592\nmx = 0\nwhile n > 0:\n    mx = max(mx, n % 10)\n    n //= 10\nprint(mx)</code></pre>",
            "options": [],
            "expected": "9",
        },
        {
            "task_number": 14,
            "skill": "python.topic_118_strings_basics",
            "type": "short_text",
            "prompt": "<p><strong>Задание 14 (Итерация по строке).</strong> Сколько раз в цикле переменная <code>ch</code> примет значение гласной буквы?</p><pre><code>vowels = \"аеёиоуыэюя\"\nword = \"программирование\"\nc = sum(1 for ch in word if ch in vowels)\nprint(c)</code></pre>",
            "options": [],
            "expected": "7",
        },
        {
            "task_number": 15,
            "skill": "python.topic_119_string_slices",
            "type": "short_text",
            "prompt": "<p><strong>Задание 15 (Срезы с четными позициями).</strong> Что выведет срез <code>s[::2]</code> для строки <code>\"АБВГДЕ\"</code>?</p>",
            "options": [],
            "expected": "АВД",
        },
        {
            "task_number": 16,
            "skill": "python.topic_120_string_find",
            "type": "short_text",
            "prompt": "<p><strong>Задание 16 (Метод find).</strong> Что вернёт вызов <code>\"abracadabra\".find(\"cad\")</code>?</p>",
            "options": [],
            "expected": "4",
        },
        {
            "task_number": 17,
            "skill": "python.topic_121_string_methods",
            "type": "short_text",
            "prompt": "<p><strong>Задание 17 (Методы split и join).</strong> Что напечатает код?</p><pre><code>s = \"10,20,30,40\"\nparts = s.split(\",\")\nprint(sum(int(x) for x in parts))</code></pre>",
            "options": [],
            "expected": "100",
        },
        {
            "task_number": 18,
            "skill": "python.topic_124_sort",
            "type": "short_text",
            "prompt": "<p><strong>Задание 18 (sorted по ключу длины).</strong> Какое слово будет первым после сортировки <code>sorted(words, key=len)</code>?</p><pre><code>words = [\"информатика\", \"код\", \"егэ\", \"python\"]\nres = sorted(words, key=len)\nprint(res[0])</code></pre>",
            "options": [],
            "expected": "код",
        },
        {
            "task_number": 19,
            "skill": "python.topic_126_comprehensions",
            "type": "short_text",
            "prompt": "<p><strong>Задание 19 (Генератор списков с условием).</strong> Чему равна сумма чисел в полученном списке?</p><pre><code>nums = [x for x in range(1, 11) if x % 3 == 0]\nprint(sum(nums))</code></pre>",
            "options": [],
            "expected": "18",
        },
        {
            "task_number": 20,
            "skill": "python.topic_130_scope",
            "type": "short_text",
            "prompt": "<p><strong>Задание 20 (Область видимости переменных).</strong> Что выведет программа?</p><pre><code>x = 10\ndef modify():\n    global x\n    x = 25\n\nmodify()\nprint(x)</code></pre>",
            "options": [],
            "expected": "25",
        },
    ]
