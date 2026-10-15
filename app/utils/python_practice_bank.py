"""Deterministic source catalogue for BooStudy's original Python practice bank.

The catalogue is deliberately separate from the 200-question theory test bank.
It is imported by the data migration so every environment receives the same
1,000 authored items and stable source keys.
"""
from __future__ import annotations

import builtins
import contextlib
import hashlib
import html
import io
import json
from collections import Counter


MODULES = (
    (101, 104, "Основы и типы данных"),
    (105, 108, "Ввод, вывод и логика"),
    (109, 112, "Условные конструкции и логика"),
    (113, 117, "Циклы и переборные алгоритмы"),
    (118, 121, "Строки и методы текста"),
    (122, 126, "Списки (массивы) и методы коллекций"),
    (127, 130, "Функции и подпрограммы"),
)


# Topic data is aligned to the 30 published articles in course 6, «Программирование».
# Each rule and matching pair is original study material, not an exam task.
TOPICS = [
    (101, "Что такое программа и синтаксис Python: вывод через print()", "print() выполняет вывод переданных значений; текстовые значения записывают в кавычках.", [("print(...)", "вывести значения"), ("\"текст\"", "строковый литерал"), ("# комментарий", "пояснение, которое не исполняется")]),
    (102, "Переменные и базовая арифметика: Python как калькулятор", "Переменная связывает имя со значением, а выражение может вычислять новое значение.", [("=", "присваивание"), ("+", "сложение"), ("*", "умножение")]),
    (103, "Деление в Python: /, // и %", "Оператор / даёт частное, // — целую часть деления, % — остаток.", [("/", "обычное деление"), ("//", "целочисленное деление"), ("%", "остаток")]),
    (104, "Типы данных int, float, str, bool и преобразование типов", "input() возвращает строку; int() и float() преобразуют строку в число.", [("int(...) ", "целое число"), ("float(...) ", "вещественное число"), ("str(...) ", "строковое представление")]),
    (105, "Ввод данных: input() и чтение чисел", "input() читает одну строку; числовой ввод нужно преобразовать перед арифметикой.", [("input()", "прочитать строку"), ("int(input())", "прочитать целое число"), ("split()", "разделить строку на части")]),
    (106, "Продвинутый вывод print(): sep и f-строки", "sep задаёт разделитель между аргументами print(), а f-строка подставляет выражения в текст.", [("sep=\"-\"", "разделитель аргументов"), ("f\"{x}\"", "подстановка значения"), ("print(a, b)", "вывод нескольких значений")]),
    (107, "Операторы сравнения и логические выражения", "Сравнения возвращают True или False и могут объединяться логическими операторами.", [("==", "равенство"), ("!=", "неравенство"), (">=", "не меньше")]),
    (108, "Встроенные функции min(), max(), sum(), len()", "min(), max(), sum() и len() вычисляют минимум, максимум, сумму и количество элементов.", [("min(xs)", "минимальный элемент"), ("max(xs)", "максимальный элемент"), ("sum(xs)", "сумма элементов")]),
    (109, "Ветвление if-else", "Условие if выбирает ветвь по истинности выражения; else выполняется, когда условие ложно.", [("if", "проверить условие"), ("else", "иначе"), (":", "начало блока")]),
    (110, "Каскадные условия if-elif-else", "В цепочке if-elif-else выполняется первая ветвь с истинным условием.", [("if", "первая проверка"), ("elif", "дополнительная проверка"), ("else", "ветвь по умолчанию")]),
    (111, "Сложные логические связки and, or, not", "and требует истинности обеих частей, or — хотя бы одной, not меняет истинность на противоположную.", [("and", "обе части истинны"), ("or", "истинна хотя бы одна часть"), ("not", "логическое отрицание")]),
    (112, "Проверка делимости, последней цифры и интервалов", "Делимость проверяют остатком %, последнюю цифру — остатком при делении на 10, интервал — сравнениями.", [("n % k == 0", "проверить делимость"), ("n % 10", "получить последнюю цифру"), ("a <= n <= b", "проверить включённый интервал")]),
    (113, "Цикл for и функция range()", "for перебирает элементы последовательности, а range(stop) создаёт значения от 0 до stop-1.", [("for", "перебор значений"), ("range(n)", "числа от 0 до n-1"), ("range(a, b)", "числа от a до b-1")]),
    (114, "Цикл while и динамические условия остановки", "while повторяет блок, пока условие истинно; внутри цикла состояние должно меняться.", [("while", "цикл с условием"), ("условие", "контролирует продолжение"), ("изменение переменной", "приближает остановку")]),
    (115, "Управление циклом: break и continue", "break завершает цикл, а continue пропускает остаток текущей итерации.", [("break", "выйти из цикла"), ("continue", "перейти к следующей итерации"), ("итерация", "одно повторение цикла")]),
    (116, "Разбор числа по цифрам в цикле while", "Остаток n % 10 даёт последнюю цифру, а целочисленное деление n // 10 убирает её.", [("n % 10", "взять последнюю цифру"), ("n // 10", "убрать последнюю цифру"), ("while n > 0", "обработать цифры до конца")]),
    (117, "Вложенные циклы", "Во вложенном цикле внутренний цикл выполняется целиком для каждой итерации внешнего.", [("внешний цикл", "задаёт строки или группы"), ("внутренний цикл", "перебирает элементы внутри группы"), ("пара циклов", "перебирает пары значений")]),
    (118, "Строки: создание, длина, конкатенация и обход", "Строка — последовательность символов; len() возвращает её длину, а + соединяет строки.", [("len(s)", "длина строки"), ("s[i]", "символ по индексу"), ("s + t", "конкатенация строк")]),
    (119, "Индексация и срезы строк", "Индексирование начинается с 0; срез s[a:b:c] не включает правую границу b.", [("s[0]", "первый символ"), ("s[-1]", "последний символ"), ("s[a:b]", "срез без позиции b")]),
    (120, "Поиск и подсчёт: count(), find(), rfind(), in", "count() считает вхождения, find() ищет первое, rfind() — последнее, in проверяет наличие.", [("count(x)", "посчитать вхождения"), ("find(x)", "найти первое вхождение"), ("x in s", "проверить наличие")]),
    (121, "Изменение строк: replace(), split(), strip()", "replace() заменяет фрагменты, split() делит строку, strip() убирает крайние пробелы.", [("replace(a, b)", "заменить фрагмент"), ("split()", "разделить строку"), ("strip()", "убрать пробелы по краям")]),
    (122, "Списки: создание, индексация, срезы и изменение элементов", "Список изменяем; элементы индексируются с нуля, а присваивание по индексу заменяет элемент.", [("xs[i]", "элемент по индексу"), ("xs[i] = v", "изменить элемент"), ("xs[a:b]", "получить срез")]),
    (123, "Добавление и удаление: append(), pop(), remove(), clear()", "append() добавляет элемент в конец, pop() удаляет и возвращает элемент, remove() удаляет по значению.", [("append(x)", "добавить в конец"), ("pop(i)", "удалить и вернуть элемент"), ("remove(x)", "удалить первое совпадение")]),
    (124, "Поиск и сортировка списков: count(), index(), sort() и sorted()", "sort() сортирует список на месте, sorted() создаёт отсортированную копию.", [("count(x)", "число совпадений"), ("index(x)", "позиция первого совпадения"), ("sorted(xs)", "новый отсортированный список")]),
    (125, "Функции для списков и map()", "map(f, xs) применяет функцию f к каждому элементу; результат можно преобразовать в list.", [("sum(xs)", "сумма"), ("len(xs)", "количество"), ("map(f, xs)", "преобразовать каждый элемент")]),
    (126, "Генераторы списков и фильтрация данных", "Генератор списка формирует новый список выражением для каждого элемента и может включать условие фильтрации.", [("[f(x) for x in xs]", "преобразовать элементы"), ("if условие", "оставить элементы по правилу"), ("[]", "создать новый список")]),
    (127, "Объявление функций: def, параметры и аргументы", "def объявляет функцию, параметры принимают значения, а аргументы передаются при вызове.", [("def", "объявить функцию"), ("параметр", "имя входного значения"), ("аргумент", "значение при вызове")]),
    (128, "Оператор return и возврат значения", "return завершает вызов функции и передаёт вычисленное значение вызывающему коду.", [("return", "вернуть значение"), ("вызов функции", "получить результат"), ("print()", "показать значение на экране")]),
    (129, "Функции-предикаты: делители и простота", "Делитель d числа n даёт остаток 0; простое число больше 1 и имеет ровно два положительных делителя.", [("n % d == 0", "d делит n"), ("n > 1", "необходимое условие простоты"), ("проверить d до корня", "достаточно искать малый делитель")]),
    (130, "Область видимости: локальные и глобальные переменные", "Локальное имя существует в функции; параметр функции может затенить внешнее имя с тем же названием.", [("параметр", "локальное имя при вызове"), ("глобальная переменная", "имя уровня модуля"), ("локальная переменная", "имя внутри функции")]),
]

TOPIC_BY_ID = {row[0]: row for row in TOPICS}
RULES = [row[2] for row in TOPICS]
SCENARIOS = (
    "учебной мастерской", "каталога настольных игр", "расписания кружка",
    "набора измерений", "списка книг", "мини-опроса", "пункта проката",
    "коллекции открыток", "таблицы результатов", "домашней библиотеки",
)


def python_bank_metadata():
    """Return metadata consumed by the existing teacher task-bank picker."""
    result = {}
    for topic_id, title, _rule, _pairs in TOPICS:
        module = next(name for start, end, name in MODULES if start <= topic_id <= end)
        result[f"python_topic_{topic_id}"] = {
            "title": title,
            "module": module,
            "lesson": title,
        }
    return result


def _difficulty(topic_index, local_index, topic_total):
    targets = {"easy": 10, "medium": 15, "hard": topic_total - 25}
    used = Counter()
    sequence = []
    for position in range(topic_total):
        left = {name: targets[name] * (position + 1) / topic_total - used[name] for name in targets}
        # Rotate ties so neighboring topics do not repeat the same level pattern.
        tie_order = ("medium", "easy", "hard") if topic_index % 2 else ("easy", "medium", "hard")
        selected = max(tie_order, key=lambda name: left[name])
        sequence.append(selected)
        used[selected] += 1
    return sequence[local_index]


def _format(topic_index, local_index, topic_id):
    # 6 choice + 2/3 match + 12/11 trace + 8 code + 5 manual per topic;
    # the first ten topics each receive one extra code task.
    if local_index < 6:
        return "choice"
    if local_index < (9 if topic_index < 10 else 8):
        return "matching"
    trace_start = 9 if topic_index < 10 else 8
    trace_end = trace_start + (11 if topic_index < 10 else 12)
    if local_index < trace_end:
        return "trace"
    if local_index < trace_end + 8:
        return "code"
    if local_index < trace_end + 8 + 5:
        return "manual"
    return "code"  # One additional authored program for topics 101–110.


def _seed(topic_id, local_index):
    return topic_id * 97 + local_index * 31 + 13


def _alternate_program(topic_id, seed, n, a, b, k, lo, hi, word, fragment):
    """Return a second, genuinely different problem archetype for each topic."""
    if topic_id == 101:
        prompt = "Считайте название объекта и его короткий код. Выведите их в одной строке через длинное тире."
        code = 'name = input().strip()\ncode = input().strip()\nprint(name, code, sep=" — ")'
        cases = [f"{word}\nQ{seed % 10}\n", "Северный маяк\nA7\n", "Кружок\n42\n"]
    elif topic_id == 102:
        prompt = "Даны цена одной детали, количество и фиксированная скидка. Выведите стоимость заказа после скидки."
        code = "price, count, discount = map(int, input().split())\nprint(price * count - discount)"
        cases = [f"{a} {b} {k}\n", "0 12 0\n", "25 2 17\n"]
    elif topic_id == 103:
        prompt = "Считайте общее число секунд и разложите его на полные часы, минуты и секунды."
        code = "total = int(input())\nhours = total // 3600\nminutes = total % 3600 // 60\nseconds = total % 60\nprint(hours, minutes, seconds)"
        cases = [f"{a * 3600 + b * 60 + k}\n", "0\n", "86399\n"]
    elif topic_id == 104:
        prompt = "Считайте целую часть измерения и дробную часть в десятых. Сложите их как числа и выведите результат с одним знаком после точки."
        code = 'whole = int(input())\ntenths = int(input())\nvalue = whole + tenths / 10\nprint(f"{value:.1f}")'
        cases = [f"{a}\n{k}\n", "0\n0\n", "12\n5\n"]
    elif topic_id == 105:
        prompt = "В одной строке даны три целых числа. Прочитайте их через split() и выведите их сумму и произведение."
        code = "x, y, z = map(int, input().split())\nprint(x + y + z, x * y * z)"
        cases = [f"{a} {b} {k}\n", "0 4 9\n", "-2 3 5\n"]
    elif topic_id == 106:
        prompt = "Считайте часы и минуты. Выведите время в виде ЧЧ:ММ, сохраняя ведущие нули."
        code = 'hours, minutes = map(int, input().split())\nprint(f"{hours:02d}:{minutes:02d}")'
        cases = [f"{a % 24} {b % 60}\n", "0 0\n", "9 7\n"]
    elif topic_id == 107:
        prompt = "Считайте три результата. Выведите максимальный результат и True, если все три числа различны."
        code = "x, y, z = map(int, input().split())\nprint(max(x, y, z))\nprint(x != y and y != z and x != z)"
        cases = [f"{a} {b} {k}\n", "4 4 9\n", "-2 0 7\n"]
    elif topic_id == 108:
        prompt = "Даны результаты нескольких попыток. Выведите среднее арифметическое, минимум и максимум."
        code = "scores = list(map(int, input().split()))\nprint(sum(scores) / len(scores), min(scores), max(scores))"
        cases = [f"{a} {b} {k}\n", "5\n", "-4 8 -1 8\n"]
    elif topic_id == 109:
        threshold = seed % 30 + 10
        prompt = f"Считайте число попыток. Выведите `достаточно`, если оно не меньше {threshold}, иначе выведите `мало`. Используйте if-else."
        code = f"attempts = int(input())\nif attempts >= {threshold}:\n    print('достаточно')\nelse:\n    print('мало')"
        cases = [f"{threshold}\n", f"{threshold - 1}\n", f"{threshold + 5}\n"]
    elif topic_id == 110:
        border_one, border_two = sorted((seed % 20 + 10, seed % 25 + 30))
        prompt = f"По числу набранных баллов выведите `начальный` для значения меньше {border_one}, `уверенный` для значения до {border_two} включительно и `высокий` для остальных."
        code = f"points = int(input())\nif points < {border_one}:\n    print('начальный')\nelif points <= {border_two}:\n    print('уверенный')\nelse:\n    print('высокий')"
        cases = [f"{border_one - 1}\n", f"{border_one}\n", f"{border_two + 1}\n"]
    elif topic_id == 111:
        prompt = "Считайте возраст и число баллов. Выведите True, если участник старше заданного порога и набрал минимум 6 баллов, либо если у него есть приглашение (1)."
        age_limit = seed % 20 + 10
        code = f"age, points, invited = map(int, input().split())\nprint((age >= {age_limit} and points >= 6) or invited == 1)"
        cases = [f"{age_limit} 6 0\n", "10 0 1\n", f"{age_limit - 1} 20 0\n"]
    elif topic_id == 112:
        divisor = seed % 9 + 2
        prompt = f"Считайте целое число и выведите True, если его последняя цифра чётная и само число делится на {divisor}. Иначе выведите False."
        code = f"value = abs(int(input()))\nlast_digit = value % 10\nprint(last_digit % 2 == 0 and value % {divisor} == 0)"
        cases = [f"{divisor * 8}\n", "0\n", f"{divisor * 3}\n"]
    elif topic_id == 113:
        step = seed % 4 + 2
        prompt = f"Считайте n. Циклом for посчитайте, сколько чисел от 1 до n включительно делятся на {step}."
        code = f"n = int(input())\ncount = 0\nfor value in range(1, n + 1):\n    if value % {step} == 0:\n        count += 1\nprint(count)"
        cases = [f"{n}\n", "0\n", f"{step - 1}\n"]
    elif topic_id == 114:
        prompt = "Считайте положительное n. Умножайте 1 на 2, пока результат меньше n. Выведите первое достигнутое значение и число умножений. Для n не больше 1 выведите `1 0`."
        code = "n = int(input())\nvalue = 1\nsteps = 0\nwhile value < n:\n    value *= 2\n    steps += 1\nprint(value, steps)"
        cases = [f"{2 ** (seed % 8 + 4) - 1}\n", "1\n", "17\n"]
    elif topic_id == 115:
        prompt = "Считайте n и k. Перебирайте числа от 1 до n: завершите цикл после числа больше 20, кратные k пропускайте. Выведите количество добавленных чисел."
        code = "n, k = map(int, input().split())\ncount = 0\nfor value in range(1, n + 1):\n    if value > 20:\n        break\n    if value % k == 0:\n        continue\n    count += 1\nprint(count)"
        cases = [f"{hi + 5} {k}\n", "0 3\n", "8 2\n"]
    elif topic_id == 116:
        prompt = "Считайте неотрицательное число. С помощью while выведите произведение его цифр и число нечётных цифр. У числа 0 единственная цифра — 0."
        code = "n = abs(int(input()))\nif n == 0:\n    product, odd_count = 0, 0\nelse:\n    product, odd_count = 1, 0\n    while n > 0:\n        digit = n % 10\n        product *= digit\n        odd_count += digit % 2\n        n //= 10\nprint(product, odd_count)"
        cases = [f"{a * 101}\n", "0\n", "13579\n"]
    elif topic_id == 117:
        prompt = "Считайте размеры прямоугольной сетки. Вложенными циклами посчитайте клетки, у которых сумма номера строки и столбца чётная. Нумерация начинается с 1."
        code = "rows, columns = map(int, input().split())\ncount = 0\nfor row in range(1, rows + 1):\n    for column in range(1, columns + 1):\n        if (row + column) % 2 == 0:\n            count += 1\nprint(count)"
        cases = [f"{n % 6 + 2} {k + 2}\n", "1 1\n", "2 3\n"]
    elif topic_id == 118:
        prompt = "Считайте строку. Посчитайте в цикле число символов, равных первому символу строки, и выведите это количество вместе с длиной строки. Строка непустая."
        code = "text = input()\nfirst = text[0]\ncount = 0\nfor char in text:\n    if char == first:\n        count += 1\nprint(count, len(text))"
        cases = [f"{word}\n", "a\n", "level\n"]
    elif topic_id == 119:
        prompt = "Считайте строку и число позиций p. Перенесите первые p символов в конец строки с помощью срезов и выведите результат."
        code = "text = input()\np = int(input()) % len(text)\nprint(text[p:] + text[:p])"
        cases = [f"{word}\n{seed % len(word)}\n", "abcdefgh\n3\n", "Python\n0\n"]
    elif topic_id == 120:
        prompt = "Считайте строку и фрагмент. Выведите количество вхождений, позицию последнего вхождения и True/False для наличия фрагмента."
        code = "text = input()\npart = input()\nprint(text.count(part), text.rfind(part), part in text)"
        cases = [f"{word + fragment + word}\n{fragment}\n", "aaaa\naa\n", "north\nx\n"]
    elif topic_id == 121:
        prompt = "Считайте строку с лишними пробелами по краям. Уберите их, разделите строку на слова и выведите число слов и слова через дефис."
        code = "text = input().strip()\nwords = text.split()\nprint(len(words))\nprint('-'.join(words))"
        cases = [f"  {word} {fragment}  \n", " one   two three \n", "Python\n"]
    elif topic_id == 122:
        prompt = "Считайте список чисел и позицию p. Сдвиньте список влево на p элементов с помощью срезов и выведите результат."
        code = "values = list(map(int, input().split()))\np = int(input()) % len(values)\nvalues = values[p:] + values[:p]\nprint(*values)"
        cases = [f"{a} {b} {n} {k}\n{seed % 4}\n", "1 2 3\n1\n", "9\n0\n"]
    elif topic_id == 123:
        prompt = "Считайте список и число x. Добавьте x в конец, затем удалите и выведите последний элемент методом pop(). Выведите оставшийся список."
        code = "values = list(map(int, input().split()))\nx = int(input())\nvalues.append(x)\nremoved = values.pop()\nprint(removed)\nprint(*values)"
        cases = [f"{a} {b} {n}\n{k}\n", "7\n3\n", "2 4\n9\n"]
    elif topic_id == 124:
        prompt = "Считайте список и значение x, которое в нём гарантированно есть. Выведите число его вхождений и индекс первого вхождения в отсортированном списке."
        code = "values = list(map(int, input().split()))\nx = int(input())\nordered = sorted(values)\nprint(ordered.count(x), ordered.index(x))"
        cases = [f"{b} {a} {b} {n}\n{b}\n", "3 1 3 2\n3\n", "5\n5\n"]
    elif topic_id == 125:
        factor = seed % 5 + 2
        prompt = f"Считайте список целых величин. С помощью map() умножьте каждую величину на {factor}, затем выведите преобразованный список и его сумму."
        code = f"values = list(map(int, input().split()))\nscaled = list(map(lambda x: x * {factor}, values))\nprint(*scaled)\nprint(sum(scaled))"
        cases = [f"{a} {b} {n}\n", "0 1 9\n", "-2 3\n"]
    elif topic_id == 126:
        prompt = "Считайте список целых чисел. Генератором списка оставьте только отрицательные нечётные числа, сохранив исходный порядок. Выведите результат."
        code = "values = list(map(int, input().split()))\nresult = [x for x in values if x < 0 and x % 2 != 0]\nprint(*result)"
        cases = [f"{-a} {a} {-b} {n} 0\n", "-3 -2 1 -5\n", "2 4 6\n"]
    elif topic_id == 127:
        prompt = "Объявите функцию `rectangle_info(a, b)`, которая возвращает площадь и периметр прямоугольника. Считайте стороны и выведите оба результата вызова."
        code = "def rectangle_info(a, b):\n    return a * b, 2 * (a + b)\n\na, b = map(int, input().split())\nprint(*rectangle_info(a, b))"
        cases = [f"{a} {b}\n", "0 5\n", "7 7\n"]
    elif topic_id == 128:
        prompt = "Напишите функцию `split_distance(total)`, которая возвращает число полных километров и оставшиеся метры, если 1 км равен 1000 м. Считайте число метров и выведите результат."
        code = "def split_distance(total):\n    return total // 1000, total % 1000\n\nprint(*split_distance(int(input())))"
        cases = [f"{a * 1000 + b}\n", "0\n", "3599\n"]
    elif topic_id == 129:
        prompt = "Реализуйте функцию `count_divisors(n)`, возвращающую число положительных делителей n. Считайте положительное n и выведите результат функции."
        code = "def count_divisors(n):\n    count = 0\n    for divisor in range(1, n + 1):\n        if n % divisor == 0:\n            count += 1\n    return count\n\nprint(count_divisors(int(input())))"
        cases = [f"{seed % 50 + 2}\n", "1\n", "12\n"]
    else:  # 130: function parameter shadows the module-level name.
        prompt = "Создайте внешнюю переменную `score`. Функция `add_bonus(score)` должна вернуть score + 5. Выведите результат функции и исходное значение внешней переменной."
        code = "score = int(input())\ndef add_bonus(score):\n    score += 5\n    return score\n\nprint(add_bonus(score), score)"
        cases = [f"{a}\n", "0\n", "-5\n"]
    return prompt, code, cases


def _program(topic_id, seed):
    """Build a topic-specific stdin/stdout problem and its reference program."""
    n = seed % 17 + 3
    a = seed % 31 + 4
    b = seed % 13 + 2
    k = seed % 7 + 2
    lo, hi = sorted((seed % 18 + 5, seed % 23 + 19))
    word = ["maple", "orbit", "pixel", "comet", "amber", "fjord", "cobalt", "lemon"][seed % 8]
    fragment = ["a", "e", "o", "m"][seed % 4]
    case_inputs = []

    if seed % 2:
        return _alternate_program(topic_id, seed, n, a, b, k, lo, hi, word, fragment)

    if topic_id == 101:
        prompt = "Считайте одну строку — короткое имя объекта — и выведите `Объект: <имя>`. Не добавляйте другие строки."
        code = 'name = input().strip()\nprint("Объект: " + name)'
        case_inputs = [f"{word}\n", "северный маяк\n", "Q7\n"]
    elif topic_id == 102:
        prompt = "На вход подаются длина и ширина прямоугольной таблички. Выведите её площадь и периметр через пробел."
        code = "length, width = map(int, input().split())\nprint(length * width, 2 * (length + width))"
        case_inputs = [f"{a} {b}\n", "1 12\n", "9 9\n"]
    elif topic_id == 103:
        prompt = "На вход подаются количество карточек и размер пачки. Выведите число полных пачек и остаток карточек."
        code = "cards, pack = map(int, input().split())\nprint(cards // pack, cards % pack)"
        case_inputs = [f"{a * b + 1} {b}\n", "0 5\n", "101 10\n"]
    elif topic_id == 104:
        prompt = "Даны цена одного предмета и количество. Преобразуйте ввод к числам и выведите общую стоимость с двумя знаками после точки."
        code = 'price = float(input())\ncount = int(input())\nprint(f"{price * count:.2f}")'
        case_inputs = [f"{a}.25\n{b}\n", "0.10\n3\n", "12\n0\n"]
    elif topic_id == 105:
        prompt = "Считайте длительность в минутах и выведите полные часы и оставшиеся минуты."
        code = "minutes = int(input())\nprint(minutes // 60, minutes % 60)"
        case_inputs = [f"{a * 60 + b}\n", "0\n", "1439\n"]
    elif topic_id == 106:
        prompt = "Даны день, месяц и год. Выведите дату в формате `ДД.ММ.ГГГГ`, сохранив ведущие нули у дня и месяца."
        code = 'day, month, year = map(int, input().split())\nprint(f"{day:02d}.{month:02d}.{year:04d}")'
        case_inputs = [f"{a % 28 + 1} {b % 12 + 1} {2000 + seed % 27}\n", "1 1 2027\n", "9 11 2031\n"]
    elif topic_id == 107:
        prompt = "Считайте два целых числа. Выведите результаты проверок `a < b`, `a == b`, `a > b` в одной строке."
        code = "a, b = map(int, input().split())\nprint(a < b, a == b, a > b)"
        case_inputs = [f"{a} {b}\n", "4 4\n", "-2 7\n"]
    elif topic_id == 108:
        prompt = "Считайте список целых чисел в одной строке. Выведите минимум, максимум, сумму и длину списка."
        code = "values = list(map(int, input().split()))\nprint(min(values), max(values), sum(values), len(values))"
        case_inputs = [f"{a} {-b} {n} 0\n", "5\n", "-4 8 -1 8\n"]
    elif topic_id == 109:
        threshold = seed % 40 + 10
        prompt = f"Считайте температуру. Если она не ниже {threshold}, выведите `можно`; иначе выведите `подождать`."
        code = f"temperature = int(input())\nif temperature >= {threshold}:\n    print('можно')\nelse:\n    print('подождать')"
        case_inputs = [f"{threshold}\n", f"{threshold - 1}\n", f"{threshold + 12}\n"]
    elif topic_id == 110:
        low, high = sorted((seed % 20 + 10, seed % 25 + 30))
        prompt = f"По числу минут выведите категорию: меньше {low} — `коротко`, от {low} до {high} включительно — `обычно`, больше {high} — `долго`."
        code = f"minutes = int(input())\nif minutes < {low}:\n    print('коротко')\nelif minutes <= {high}:\n    print('обычно')\nelse:\n    print('долго')"
        case_inputs = [f"{low - 1}\n", f"{low}\n", f"{high + 1}\n"]
    elif topic_id == 111:
        minimum = seed % 30 + 10
        prompt = f"Даны возраст, число набранных баллов и признак `1`/`0` наличия пропуска. Выведите `True`, если возраст не меньше {minimum} и баллов не меньше 6, либо если пропуск есть."
        code = f"age, points, pass_card = map(int, input().split())\nprint((age >= {minimum} and points >= 6) or pass_card == 1)"
        case_inputs = [f"{minimum} 6 0\n", "10 10 1\n", f"{minimum - 1} 20 0\n"]
    elif topic_id == 112:
        prompt = f"Считайте целое число n. Выведите его последнюю цифру, затем `True`/`False` для делимости на {k}, затем `True`/`False` для принадлежности отрезку [{lo}, {hi}]."
        code = f"n = int(input())\nprint(abs(n) % 10)\nprint(n % {k} == 0)\nprint({lo} <= n <= {hi})"
        case_inputs = [f"{a * k}\n", "0\n", f"-{b * k}\n"]
    elif topic_id == 113:
        prompt = "Считайте n и вычислите сумму квадратов чисел от 1 до n включительно с помощью цикла `for`. Для n = 0 сумма равна 0."
        code = "n = int(input())\ntotal = 0\nfor value in range(1, n + 1):\n    total += value * value\nprint(total)"
        case_inputs = [f"{n}\n", "0\n", "1\n"]
    elif topic_id == 114:
        limit = seed % 4 + 2
        prompt = f"Считайте положительное число n. Делите его на 2 целочисленно, пока оно больше {limit}; выведите количество выполненных делений. Используйте `while`."
        code = f"n = int(input())\nsteps = 0\nwhile n > {limit}:\n    n //= 2\n    steps += 1\nprint(steps)"
        case_inputs = [f"{2 ** (seed % 8 + 4)}\n", f"{limit}\n", "1\n"]
    elif topic_id == 115:
        prompt = f"Считайте n и k. Просматривайте числа от 1 до n: завершите цикл при значении больше {hi}; кратные k пропускайте. Выведите сумму остальных просмотренных чисел."
        code = f"n, k = map(int, input().split())\ntotal = 0\nfor value in range(1, n + 1):\n    if value > {hi}:\n        break\n    if value % k == 0:\n        continue\n    total += value\nprint(total)"
        case_inputs = [f"{hi + 4} {k}\n", "0 3\n", "8 2\n"]
    elif topic_id == 116:
        prompt = "Считайте неотрицательное целое число. Циклом `while` найдите сумму его цифр и количество чётных цифр. У числа 0 одна цифра — 0."
        code = "n = abs(int(input()))\nif n == 0:\n    digit_sum, even_count = 0, 1\nelse:\n    digit_sum, even_count = 0, 0\n    while n > 0:\n        digit = n % 10\n        digit_sum += digit\n        even_count += digit % 2 == 0\n        n //= 10\nprint(digit_sum, even_count)"
        case_inputs = [f"{a * 101}\n", "0\n", "13579\n"]
    elif topic_id == 117:
        prompt = "Считайте n и предел p. Вложенными циклами посчитайте упорядоченные пары целых i, j от 1 до n, для которых i · j не больше p."
        code = "n, p = map(int, input().split())\ncount = 0\nfor i in range(1, n + 1):\n    for j in range(1, n + 1):\n        if i * j <= p:\n            count += 1\nprint(count)"
        case_inputs = [f"{n % 7 + 2} {a}\n", "1 1\n", "3 0\n"]
    elif topic_id == 118:
        prompt = "Считайте строку. Выведите её длину и строку в обратном порядке на отдельных строках."
        code = "text = input()\nprint(len(text))\nprint(text[::-1])"
        case_inputs = [f"{word}\n", "\n", "Python 3\n"]
    elif topic_id == 119:
        prompt = "В первой строке дана строка, во второй — начало, конец и шаг среза. Выведите `text[start:stop:step]`."
        code = "text = input()\nstart, stop, step = map(int, input().split())\nprint(text[start:stop:step])"
        case_inputs = [f"{word}\n1 7 2\n", "abcdefgh\n0 8 3\n", "0123456789\n-1 -8 -2\n"]
    elif topic_id == 120:
        prompt = "В первой строке дана строка, во второй — фрагмент. Выведите число вхождений и позицию первого вхождения (`-1`, если его нет)."
        code = "text = input()\npart = input()\nprint(text.count(part), text.find(part))"
        case_inputs = [f"{word + fragment + word}\n{fragment}\n", "aaaa\naa\n", "north\nx\n"]
    elif topic_id == 121:
        prompt = "Даны строка, старый фрагмент и новый фрагмент. Уберите пробелы по краям, замените старый фрагмент и сведите последовательности пробелов к одному пробелу."
        code = "text = input().strip()\nold = input()\nnew = input()\ntext = text.replace(old, new)\nprint(' '.join(text.split()))"
        case_inputs = [f"  {word} {word}  \n{word}\n{fragment}\n", "red red\nred\nblue\n", "  one   two \nX\nY\n"]
    elif topic_id == 122:
        prompt = "В первой строке дан список чисел, затем индекс i и новое значение v. Замените элемент с индексом i и выведите весь список. Индекс гарантированно допустим."
        code = "values = list(map(int, input().split()))\ni = int(input())\nv = int(input())\nvalues[i] = v\nprint(*values)"
        case_inputs = [f"{a} {b} {n}\n1\n{a + b}\n", "1 2 3\n0\n9\n", "-1 4\n1\n0\n"]
    elif topic_id == 123:
        prompt = "Считайте список чисел, затем значение v и индекс i. Добавьте v в конец, удалите элемент по индексу i и выведите удалённое значение, а затем оставшийся список."
        code = "values = list(map(int, input().split()))\nv = int(input())\ni = int(input())\nvalues.append(v)\nremoved = values.pop(i)\nprint(removed)\nprint(*values)"
        case_inputs = [f"{a} {b} {n}\n{a - b}\n1\n", "7\n3\n0\n", "2 4\n9\n2\n"]
    elif topic_id == 124:
        prompt = "Считайте список чисел. Сначала выведите отсортированную копию через `sorted()`, затем минимальный и максимальный элементы исходного списка."
        code = "values = list(map(int, input().split()))\nordered = sorted(values)\nprint(*ordered)\nvalues.sort()\nprint(values[0], values[-1])"
        case_inputs = [f"{b} {a} {n} {-k}\n", "5\n", "3 -1 3 0\n"]
    elif topic_id == 125:
        discount = seed % 31 + 5
        prompt = f"Даны цены нескольких товаров и процент скидки {discount}. С помощью `map()` получите целые цены после скидки (дробную часть отбросьте), выведите их, затем сумму."
        code = f"prices = list(map(int, input().split()))\nrate = {discount}\nreduced = list(map(lambda price: price * (100 - rate) // 100, prices))\nprint(*reduced)\nprint(sum(reduced))"
        case_inputs = [f"{a} {b} {n}\n", "0 1 99\n", "100 250\n"]
    elif topic_id == 126:
        prompt = f"Считайте список целых чисел и делитель k. Генератором списка выберите числа, которые положительны и делятся на k без остатка; сохраните порядок."
        code = "values = list(map(int, input().split()))\nk = int(input())\nresult = [x for x in values if x > 0 and x % k == 0]\nprint(*result)"
        case_inputs = [f"{-a} {a} {b * k} 0 {n}\n{k}\n", "2 4 6\n2\n", "1 2 3\n5\n"]
    elif topic_id == 127:
        prompt = "Объявите функцию `order_cost(price, count, discount)`, возвращающую стоимость заказа после вычета фиксированной скидки. Считайте три целых числа и выведите результат вызова."
        code = "def order_cost(price, count, discount):\n    return price * count - discount\n\nprice, count, discount = map(int, input().split())\nprint(order_cost(price, count, discount))"
        case_inputs = [f"{a} {b} {n}\n", "0 12 0\n", "25 2 17\n"]
    elif topic_id == 128:
        prompt = "Напишите функцию `split_seconds(total)`, которая возвращает количество полных минут и оставшиеся секунды. Считайте число секунд и выведите оба значения."
        code = "def split_seconds(total):\n    return total // 60, total % 60\n\nprint(*split_seconds(int(input())))"
        case_inputs = [f"{a * 60 + b}\n", "0\n", "3599\n"]
    elif topic_id == 129:
        prompt = "Реализуйте функцию-предикат `is_prime(n)`: она должна вернуть `True`, если n — простое число, и `False` в остальных случаях. Считайте n и выведите результат."
        code = "def is_prime(n):\n    if n < 2:\n        return False\n    divisor = 2\n    while divisor * divisor <= n:\n        if n % divisor == 0:\n            return False\n        divisor += 1\n    return True\n\nprint(is_prime(int(input())))"
        case_inputs = [f"{seed % 50 + 2}\n", "1\n", "97\n"]
    else:  # 130: local scope and parameter shadowing.
        prompt = "Считайте число base. Реализуйте функцию `shift(base)`, которая использует локальное значение `base + 3` и возвращает его. Выведите результат функции и исходное внешнее значение base."
        code = "base = int(input())\ndef shift(base):\n    local_value = base + 3\n    return local_value\n\nprint(shift(base), base)"
        case_inputs = [f"{a}\n", "0\n", "-5\n"]

    if topic_id in (109, 110, 111, 112, 114, 115, 125, 126):
        # Keep boundaries and awkward values represented in every authored variant.
        case_inputs = case_inputs[:2] + case_inputs[2:]
    return prompt, code, case_inputs


def _run_reference(code, raw_input):
    """Execute only a source string from this trusted catalogue to create expected outputs."""
    source_lines = iter(raw_input.splitlines())
    output = io.StringIO()

    def read_line(prompt=None):
        try:
            return next(source_lines)
        except StopIteration as exc:
            raise EOFError("not enough catalogue test input") from exc

    def write(*values, sep=" ", end="\n", file=None, flush=False):
        target = output if file is None else file
        target.write(sep.join(str(value) for value in values) + end)

    safe_builtins = dict(vars(builtins))
    safe_builtins.update(input=read_line, print=write)
    with contextlib.redirect_stdout(output):
        exec(compile(code, "<trusted-bank-reference>", "exec"), {"__builtins__": safe_builtins})
    return output.getvalue().rstrip("\n")


def _hints(topic_id, difficulty):
    row = TOPIC_BY_ID[topic_id]
    hints = [
        f"Сначала выдели ключевое действие из темы «{row[1]}».",
        "Разбей решение на маленькие шаги и проверь формат каждого промежуточного значения.",
        "Проверь граничный случай: пустое значение, ноль или значение на границе условия.",
    ]
    if difficulty == "easy":
        return hints[:2]
    if difficulty == "medium":
        return hints
    return [hints[0], "Продумай порядок операций и случай, который обычно пропускают.", hints[2]]


def _html_block(text):
    return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"


def _code_html(text):
    return "<pre><code>" + html.escape(text) + "</code></pre>"


def _concept_choice(topic_id, variant):
    row = TOPIC_BY_ID[topic_id]
    term, correct = row[3][(variant // 2) % len(row[3])]
    module_start, module_end, _module_name = next(module for module in MODULES if module[0] <= topic_id <= module[1])
    sibling_definitions = [definition for other_term, definition in row[3] if other_term != term]
    nearby_definitions = [
        definition
        for other_id, _other_title, _rule, pairs in TOPICS
        if module_start <= other_id <= module_end and other_id != topic_id
        for _other_term, definition in pairs
    ]
    start = (topic_id + variant) % len(nearby_definitions)
    candidates = sibling_definitions + [nearby_definitions[(start + offset) % len(nearby_definitions)] for offset in range(len(nearby_definitions))]
    options = [correct]
    for candidate in candidates:
        if candidate not in options:
            options.append(candidate)
        if len(options) == 4:
            break
    # Deterministic rotation prevents the right answer from always occupying A.
    rotation = (topic_id + variant) % len(options)
    options = options[rotation:] + options[:rotation]
    correct_index = options.index(correct)
    labels = "ABCD"
    prompts = (
        f"Что означает элемент `{term}` в теме «{row[1]}»?",
        f"Выбери назначение элемента `{term}` при работе с темой «{row[1]}».",
        f"Какое описание подходит к записи `{term}` из темы «{row[1]}»?",
    )
    prompt = prompts[(variant // 2) % len(prompts)]
    answer_options = [{"value": labels[i], "label": option} for i, option in enumerate(options)]
    return prompt, answer_options, labels[correct_index]


def _matching(topic_id, variant):
    row = TOPIC_BY_ID[topic_id]
    pairs = row[3]
    rotation = variant % len(pairs)
    left = pairs[rotation:] + pairs[:rotation]
    right = list(reversed([definition for _term, definition in left]))
    options = [{"value": chr(65 + i), "label": value} for i, value in enumerate(right)]
    mapping = {}
    answer_pairs = []
    for term, definition in left:
        key = f"L{len(answer_pairs) + 1}"
        option_value = next(item["value"] for item in options if item["label"] == definition)
        mapping[key] = option_value
        answer_pairs.append({"key": key, "label": term})
    return {
        "type": "matching",
        "prompt": "Соотнеси элемент Python с его назначением.",
        "pairs": answer_pairs,
        "options": options,
        "grading_mode": "auto",
    }, mapping


def _output_distractors(output):
    """Build distinct, plausible wrong outputs for code-reading questions."""
    lines = output.splitlines()
    candidates = []
    if lines and all(line.split() and all(token.lstrip("+-").isdigit() for token in line.split()) for line in lines):
        if len(lines) == 1:
            values = lines[0].split()
            try:
                changed = values.copy()
                changed[0] = str(int(changed[0]) + 1)
                candidates.append(" ".join(changed))
                if len(values) > 1:
                    candidates.append(" ".join(reversed(values)))
                    candidates.append(" ".join(values[:-1]))
                else:
                    candidates.append(str(int(values[0]) - 1))
            except ValueError:
                pass
        else:
            candidates.extend(("\n".join(lines[:-1]), "\n".join(reversed(lines)), "\n".join(lines + ["0"])))
    elif len(lines) == 1:
        if lines[0] in ("True", "False"):
            candidates.append("False" if lines[0] == "True" else "True")
        if " — " in lines[0]:
            left, right = lines[0].split(" — ", 1)
            candidates.append(f"{right} — {left}")
        words = lines[0].split()
        if len(words) > 1:
            candidates.append(" ".join(reversed(words)))
        candidates.extend((lines[0].swapcase(), lines[0] + " 0"))
    else:
        candidates.extend(("\n".join(reversed(lines)), "\n".join(lines[:-1]), "\n".join(lines + ["0"])))

    distractors = []
    for candidate in candidates:
        if candidate != output and candidate not in distractors:
            distractors.append(candidate)
        if len(distractors) == 3:
            break
    fallback = 1
    while len(distractors) < 3:
        candidate = f"{output}\n{fallback}"
        fallback += 1
        if candidate != output and candidate not in distractors:
            distractors.append(candidate)
    return distractors


def _make_item(topic_index, topic, local_index, topic_total, format_name, global_number):
    topic_id, title, _rule, _pairs = topic
    difficulty = _difficulty(topic_index, local_index, topic_total)
    seed = _seed(topic_id, local_index)
    prompt_parts = []
    answer = None
    answer_spec = None
    starter_code = None
    tests = None
    scenario = SCENARIOS[(topic_id + local_index) % len(SCENARIOS)]
    program_prompt, reference_code, cases = _program(topic_id, seed)
    computed = [{"input": case, "output": _run_reference(reference_code, case)} for case in cases]

    if format_name == "choice":
        variant = local_index
        if variant % 2 == 0:
            prompt, options, answer = _concept_choice(topic_id, variant)
        else:
            sample = computed[variant % len(computed)]
            distractors = _output_distractors(sample["output"])
            option_texts = [sample["output"]] + distractors
            # Preserve unique choices while keeping one correct label.
            option_texts = list(dict.fromkeys(option_texts))[:4]
            while len(option_texts) < 4:
                option_texts.append(f"Другой результат {len(option_texts)}")
            rotation = (topic_id + variant) % 4
            option_texts = option_texts[rotation:] + option_texts[:rotation]
            answer = "ABCD"[option_texts.index(sample["output"])]
            options = [{"value": "ABCD"[i], "label": value} for i, value in enumerate(option_texts)]
            prompt = (
                f"{program_prompt}\n\nКакой результат появится на экране для этих данных?\n"
                + _code_html(reference_code)
                + "<p><strong>Ввод:</strong></p>"
                + _code_html(sample["input"].rstrip("\n"))
            )
        answer_spec = {"type": "single_choice", "prompt": "Выбери один вариант.", "options": options, "grading_mode": "auto"}
        if not (variant % 2):
            prompt = prompt
        else:
            prompt_parts = [prompt]
        if not prompt_parts:
            prompt_parts = [prompt]
    elif format_name == "matching":
        answer_spec, answer = _matching(topic_id, local_index)
        ordered_terms = ", ".join(pair["label"] for pair in answer_spec["pairs"])
        prompt_parts = [f"<p>Тема: {title}. Соотнеси элементы в этом порядке: <code>{html.escape(ordered_terms)}</code>.</p>"]
    elif format_name == "trace":
        sample = computed[local_index % len(computed)]
        output_lines = sample["output"].splitlines() or ["пустая строка"]
        output_line_number = (topic_id + local_index) % len(output_lines) + 1
        prompt_parts = [
            f"Прочитай программу для ситуации из {scenario}. Укажи только {output_line_number}-ю строку вывода.",
            _code_html(reference_code),
            "<p><strong>Ввод:</strong></p>",
            _code_html(sample["input"].rstrip("\n")),
        ]
        answer = output_lines[output_line_number - 1]
        answer_spec = {"type": "short_answer", "prompt": "Запиши только содержимое указанной строки.", "grading_mode": "auto"}
    elif format_name == "code":
        sample = computed[0]
        prompt_parts = [
            f"<p>Практика по теме «{title}» для {scenario}. {program_prompt}</p>",
            "<p><strong>Пример ввода:</strong></p>", _code_html(sample["input"].rstrip("\n")),
            "<p><strong>Пример результата:</strong></p>", _code_html(sample["output"]),
        ]
        answer_spec = {"type": "code", "language": "python", "grading_mode": "auto", "prompt": "Напиши программу на Python. Пример из условия виден выше; решение проверяется на дополнительных закрытых тестах."}
        starter_code = "# Напиши решение на Python\n"
        answer = None
        tests = computed
    else:
        variant = local_index - (9 if topic_index < 10 else 8) - (11 if topic_index < 10 else 12) - 8
        manual_kind = (topic_id + variant) % 2
        if manual_kind == 0:
            snippet = reference_code
            sample = computed[local_index % len(computed)]
            prompt_parts = [
                f"<p>В контексте {scenario} объясни своими словами, как работает приведённая программа и какую роль в ней играет тема «{title}».</p>",
                _code_html(snippet),
                "<p><strong>Контрольный ввод:</strong></p>", _code_html(sample["input"].rstrip("\n")),
                f"<p>Укажи порядок основных шагов, объясни результат для этого ввода и назови один граничный случай, который стоит проверить.</p>",
            ]
            answer_spec = {"type": "long_answer", "grading_mode": "manual", "prompt": "Ответ проверит преподаватель.", "placeholder": "Опиши ход выполнения программы…"}
            solution = f"Ожидается объяснение ключевого действия по теме «{title}», последовательности операций и разумного граничного случая. Ориентир: программа {program_prompt.lower()} Эталонная реализация:\n\n{reference_code}"
        else:
            prompt_parts = [
                f"<p>Напиши короткую программу для {scenario}, которая демонстрирует навык по теме «{title}».</p>",
                f"<p>Требование: {program_prompt}</p>",
                "<p>Можно использовать собственные названия переменных. Преподаватель проверит корректность алгоритма и аккуратность обработки граничных значений.</p>",
            ]
            answer_spec = {"type": "code", "language": "python", "grading_mode": "manual", "prompt": "Решение проверит преподаватель."}
            starter_code = "# Реализуй алгоритм по условию\n"
            solution = f"Пример решения:\n\n{reference_code}\n\nКритерии: используется подходящий инструмент из темы «{title}»; программа соответствует формату ввода и вывода; учтён граничный случай."
        answer = None
        answer_spec["grading_mode"] = "manual"
        answer_spec["difficulty"] = difficulty
        answer_spec["format"] = "open"
        rendered = "".join(prompt_parts)
        hints = _hints(topic_id, difficulty)
        return {
            "source_key": f"boo-python-v1-{global_number:04d}",
            "source_prototype": f"python_topic_{topic_id}",
            "content_html": rendered,
            "answer": answer,
            "starter_code": starter_code,
            "answer_spec": answer_spec,
            "hints": hints,
            "difficulty_level": {"easy": 1, "medium": 2, "hard": 3}[difficulty],
            "format": "manual_open",
            "tests": None,
            "solution_text": solution,
            "reference_code": reference_code,
        }

    if format_name == "code":
        solution = f"Эталонная программа:\n\n{reference_code}\n\nОна считывает данные и выполняет описанный алгоритм. Примеры проверок подготовлены отдельно и не показываются ученику до сдачи."
    elif format_name == "matching":
        labels_by_value = {option["value"]: option["label"] for option in answer_spec["options"]}
        solution = "\n".join(f"{pair['label']} → {labels_by_value[answer[pair['key']]]}" for pair in answer_spec["pairs"])
    else:
        solution = f"Правильный ответ: {answer!s}.\n\n" + (f"Пояснение: {TOPIC_BY_ID[topic_id][2]}" if format_name == "choice" else f"\nЭталонная программа:\n{reference_code}")

    if format_name == "choice":
        if local_index % 2 == 0:
            prompt_parts = [prompt]
        # Options are deliberately teacher-visible in the picker, never embedded with the key in student content.
    if format_name == "trace":
        pass
    if format_name == "matching":
        pass
    rendered = "".join(prompt_parts) if prompt_parts else _html_block(prompt)
    answer_spec["difficulty"] = difficulty
    answer_spec["format"] = format_name
    return {
        "source_key": f"boo-python-v1-{global_number:04d}",
        "source_prototype": f"python_topic_{topic_id}",
        "content_html": rendered,
        "answer": json.dumps(answer, ensure_ascii=False, separators=(",", ":")) if format_name == "matching" else str(answer),
        "starter_code": starter_code,
        "answer_spec": answer_spec,
        "hints": _hints(topic_id, difficulty),
        "difficulty_level": {"easy": 1, "medium": 2, "hard": 3}[difficulty],
        "format": format_name,
        "tests": tests,
        "solution_text": solution,
        "reference_code": reference_code,
    }


def generate_python_practice_bank():
    """Generate the canonical, exact-size 1,000-task BooStudy Python bank."""
    output = []
    global_number = 1
    for topic_index, topic in enumerate(TOPICS):
        topic_total = 34 if topic_index < 10 else 33
        for local_index in range(topic_total):
            kind = _format(topic_index, local_index, topic[0])
            item = _make_item(topic_index, topic, local_index, topic_total, kind, global_number)
            item["topic_id"] = topic[0]
            item["difficulty_name"] = ("easy", "medium", "hard")[item["difficulty_level"] - 1]
            fingerprint_content = item["content_html"] + json.dumps(item["answer_spec"], ensure_ascii=False, sort_keys=True)
            item["content_fingerprint"] = hashlib.sha256(fingerprint_content.encode("utf-8")).hexdigest()
            output.append(item)
            global_number += 1

    # Guard the immutable migration payload against accidental catalogue drift.
    if len(output) != 1000:
        raise ValueError(f"Python practice bank must contain 1,000 items; got {len(output)}")
    keys = [item["source_key"] for item in output]
    if len(set(keys)) != 1000:
        raise ValueError("Python practice bank source keys are not unique")
    fingerprints = Counter(item["content_fingerprint"] for item in output)
    if any(count > 1 for count in fingerprints.values()):
        duplicate_keys = {}
        for item in output:
            duplicate_keys.setdefault(item["content_fingerprint"], []).append(item["source_key"])
        duplicates = [keys for keys in duplicate_keys.values() if len(keys) > 1]
        raise ValueError(f"Python practice bank contains duplicate task text: {duplicates[:8]}")
    formats = Counter(item["format"] for item in output)
    expected_formats = {"choice": 180, "matching": 70, "trace": 350, "code": 250, "manual_open": 150}
    if formats != expected_formats:
        raise ValueError(f"Unexpected format distribution: {dict(formats)}")
    difficulty_counts = Counter(item["difficulty_name"] for item in output)
    if difficulty_counts != {"easy": 300, "medium": 450, "hard": 250}:
        raise ValueError(f"Unexpected difficulty distribution: {dict(difficulty_counts)}")
    if any(not item["answer_spec"] or not item["solution_text"] or not item["hints"] for item in output):
        raise ValueError("Every task must include an answer specification, solution, and hints")
    return output
