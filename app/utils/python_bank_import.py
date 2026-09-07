"""Идемпотентный импорт авторского банка Python для ЕГЭ."""
from __future__ import annotations

import hashlib
import html
import io
import json
from contextlib import redirect_stdout
from functools import lru_cache
from pathlib import Path

from core.db_models import Course, CourseTaskTemplate, Tasks, TaskSolution


_FOUNDATION_ACTIVITY_TITLES = (
    'Проверка результата', 'Разбор выражения', 'Трассировка программы',
    'Изменение данных', 'Поиск закономерности', 'Мини-задача',
    'Пограничный случай', 'Практика', 'Самопроверка', 'Закрепление',
)

_FOUNDATION_PROMPTS = (
    'Определите, что выведет программа.',
    'Выполните код по шагам и запишите результат.',
    'Не запуская программу, укажите вывод.',
    'Проследите изменение данных и укажите ответ.',
    'Найдите значение, которое напечатает программа.',
    'Решите короткую задачу по фрагменту кода.',
    'Проверьте программу на заданных данных.',
    'Вычислите результат выполнения программы.',
    'Запишите точный вывод программы.',
    'Закрепите тему: определите результат кода.',
)


def _foundation_variant_number(item: dict) -> int:
    """Номер упражнения внутри темы из стабильного ID пакета ``N.1`` … ``N.10``."""
    try:
        return max(1, min(10, int(str(item.get('id') or '').rsplit('.', 1)[-1])))
    except (TypeError, ValueError):
        return 1


def _output_of(code: str) -> str:
    """Возвращает вывод контролируемой учебной программы без ручных эталонов."""
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, '<python-foundations>', 'exec'), {})  # noqa: S102 -- source is hard-coded below
    return output.getvalue().rstrip('\n')


def _foundation_case(module: str, n: int) -> tuple[str, str, str]:
    """Десять разных практик для каждой темы, а не один шаблон с другими числами."""
    cases: dict[str, tuple[tuple[str, str, str], ...]] = {
        'Переменные и типы данных': (
            ('Тип значения', 'Определите тип результата целочисленного деления.', "value = 17 // 3\nprint(type(value).__name__)"),
            ('Преобразование строки', 'Проследите преобразование строки в число.', "text = '08'\nnumber = int(text) + 7\nprint(number)"),
            ('Обмен значений', 'Какой будет пара после одновременного присваивания?', "left, right = 4, 9\nleft, right = right - left, left + right\nprint(left, right)"),
            ('Логическое значение', 'Определите результат сравнения.', "age = 16\nprint(age >= 14 and age < 18)"),
            ('Округление вниз', 'Что напечатает программа после преобразования?', "ratio = 8.95\nprint(int(ratio) * 2)"),
            ('Составное присваивание', 'Проследите изменение переменной.', "score = 12\nscore += 5\nscore *= 2\nprint(score)"),
            ('Форматирование текста', 'Определите итоговую строку.', "name = 'Лена'\nplace = 3\nprint(f'{name}: {place} место')"),
            ('Булево значение', 'Проверьте, во что преобразуется непустая строка.', "word = '0'\nprint(bool(word))"),
            ('Остаток и тип', 'Определите значение и его тип.', "result = 19 % 6\nprint(result, type(result).__name__)"),
            ('Цепочка присваиваний', 'Проследите независимое изменение переменных.', "a = b = 5\na += 2\nprint(a, b)"),
        ),
        'Ввод и вывод': (
            ('Два числа в строке', 'Разберите две величины из одной строки.', "raw = '12 7'\na, b = map(int, raw.split())\nprint(a - b)"),
            ('Имя пользователя', 'Соберите приветствие из введённого имени.', "name = 'Мира'\nprint('Привет, ' + name + '!')"),
            ('Три значения', 'Найдите среднее трёх введённых чисел.', "raw = '4 9 14'\nvalues = list(map(int, raw.split()))\nprint(sum(values) // len(values))"),
            ('Разделитель', 'Определите строку с нестандартным разделителем.', "first, second = 'код', 'готов'\nprint(first, second, sep=' → ')"),
            ('Несколько строк', 'Сложите числа, полученные из двух строк.', "first = int('18')\nsecond = int('24')\nprint(first + second)"),
            ('Список слов', 'Посчитайте количество введённых слов.', "line = 'путь к ответу'\nprint(len(line.split()))"),
            ('Вывод без пробела', 'Определите результат параметра end.', "print('A', end='')\nprint('B', end='!')"),
            ('Число с запятой', 'Преобразуйте запись с десятичной точкой.', "price = float('12.5')\nprint(price * 2)"),
            ('Распаковка', 'Выведите второе слово из строки.', "city, subject, day = 'Казань Python пятница'.split()\nprint(subject)"),
            ('Сбор результата', 'Соберите ответ из частей.', "parts = ['ЕГЭ', 'по', 'информатике']\nprint(' '.join(parts))"),
        ),
        'Арифметика и логика': (
            ('Остаток от деления', 'Найдите последнюю цифру числа.', "number = 587\nprint(number % 10)"),
            ('Степень', 'Вычислите значение выражения.', "print(3 ** 3 - 5)"),
            ('Приоритет операций', 'Учтите порядок выполнения операций.', "print(18 - 4 * 3 + 2)"),
            ('Делимость', 'Проверьте, делится ли число на 3.', "number = 42\nprint(number % 3 == 0)"),
            ('Логическое И', 'Определите значение сложного условия.', "score = 76\nprint(score >= 60 and score < 90)"),
            ('Логическое ИЛИ', 'Проверьте, подходит ли символ.', "letter = 'ы'\nprint(letter == 'а' or letter == 'ы')"),
            ('Модуль числа', 'Найдите расстояние до нуля.', "temperature = -13\nprint(abs(temperature))"),
            ('Округление', 'Округлите число до целой части по правилам Python.', "print(round(7.6))"),
            ('Целая часть', 'Вычислите количество полных десятков.', "print(97 // 10)"),
            ('Сравнение', 'Определите результат цепочки сравнений.', "print(4 < 7 <= 7)"),
        ),
        'Условия': (
            ('Знак числа', 'Определите, какой текст будет выведен.', "number = -4\nif number > 0:\n    print('плюс')\nelif number == 0:\n    print('ноль')\nelse:\n    print('минус')"),
            ('Большее число', 'Найдите большее из двух чисел через условие.', "a, b = 15, 11\nif a > b:\n    print(a)\nelse:\n    print(b)"),
            ('Чётность', 'Определите, как классифицируется число.', "number = 27\nprint('чётное' if number % 2 == 0 else 'нечётное')"),
            ('Диапазон', 'Проверьте попадание в диапазон.', "point = 8\nif 1 <= point <= 10:\n    print('внутри')\nelse:\n    print('снаружи')"),
            ('Минимум трёх', 'Выберите наименьшее значение.', "a, b, c = 8, 3, 5\nif a < b and a < c:\n    print(a)\nelif b < c:\n    print(b)\nelse:\n    print(c)"),
            ('Високосный год', 'Проверьте условие кратности.', "year = 2024\nif year % 400 == 0 or year % 4 == 0 and year % 100 != 0:\n    print('да')\nelse:\n    print('нет')"),
            ('Скидка', 'Применится ли скидка?', "total = 1200\nif total >= 1000:\n    total -= 150\nprint(total)"),
            ('Вложенное условие', 'Определите оценку по баллу.', "score = 68\nif score >= 60:\n    if score >= 85:\n        print('отлично')\n    else:\n        print('зачёт')\nelse:\n    print('повторить')"),
            ('Количество цифр', 'Определите разрядность числа.', "number = 99\nif number >= 100:\n    print(3)\nelse:\n    print(2)"),
            ('Выбор тарифа', 'Определите стоимость тарифа.', "lessons = 7\nif lessons >= 10:\n    print(900)\nelif lessons >= 5:\n    print(550)\nelse:\n    print(150)"),
        ),
        'Циклы': (
            ('Сумма диапазона', 'Сложите числа от 1 до 5.', "total = 0\nfor number in range(1, 6):\n    total += number\nprint(total)"),
            ('Количество чётных', 'Посчитайте чётные числа в диапазоне.', "count = 0\nfor number in range(1, 11):\n    if number % 2 == 0:\n        count += 1\nprint(count)"),
            ('Произведение', 'Найдите произведение чисел от 1 до 4.', "product = 1\nfor number in range(1, 5):\n    product *= number\nprint(product)"),
            ('Цикл while', 'Проследите изменение счётчика.', "value = 1\nwhile value < 20:\n    value *= 3\nprint(value)"),
            ('Шаг range', 'Сложите числа с шагом 3.', "print(sum(range(2, 12, 3)))"),
            ('continue', 'Какая сумма получится без кратных трём?', "total = 0\nfor number in range(1, 8):\n    if number % 3 == 0:\n        continue\n    total += number\nprint(total)"),
            ('break', 'На каком числе цикл остановится?', "for number in range(2, 10):\n    if number * number > 30:\n        break\nprint(number)"),
            ('Вложенные циклы', 'Посчитайте число пар.', "count = 0\nfor a in range(3):\n    for b in range(2):\n        count += 1\nprint(count)"),
            ('enumerate', 'Сложите индексы букв.', "total = 0\nfor index, letter in enumerate('код', start=1):\n    total += index\nprint(total)"),
            ('Цифры числа', 'Найдите сумму цифр.', "number = 352\ntotal = 0\nwhile number > 0:\n    total += number % 10\n    number //= 10\nprint(total)"),
        ),
    }
    generic_cases = (
        ('Индексирование', 'Выполните программу и запишите вывод.', "text = 'алгоритм'\nprint(text[2])"),
        ('Срез', 'Определите результат среза.', "text = 'информатика'\nprint(text[1:6])"),
        ('Разворот', 'Разверните последовательность.', "print('Python'[::-1])"),
        ('Подсчёт', 'Посчитайте вхождения символа.', "print('программирование'.count('р'))"),
        ('Замена', 'Выполните замену в строке.', "print('кек'.replace('к', 'г'))"),
        ('Разбиение', 'Посчитайте части строки.', "print(len('один-два-три'.split('-')))"),
        ('Проверка начала', 'Проверьте начало строки.', "print('алгоритм'.startswith('алг'))"),
        ('Удаление пробелов', 'Уберите внешние пробелы.', "print('  код  '.strip())"),
        ('Смена регистра', 'Преобразуйте строку.', "print('PyThOn'.lower())"),
        ('Палиндром', 'Проверьте слово.', "word = 'топот'\nprint(word == word[::-1])"),
    )
    if module in cases:
        selected = cases[module][n - 1]
    elif module == 'Строки':
        selected = generic_cases[n - 1]
    elif module == 'Списки и срезы':
        selected = (
            ('Срез списка', 'Сложите элементы среза.', "numbers = [3, 8, 1, 6, 4]\nprint(sum(numbers[1:4]))"), ('Добавление', 'Проследите изменение списка.', "items = [2, 5]\nitems.append(7)\nprint(items[-1])"), ('Удаление', 'Какой список останется?', "items = [4, 9, 2]\nitems.pop(1)\nprint(items)"), ('Сортировка', 'Определите первый элемент после сортировки.', "items = [7, 2, 5]\nitems.sort()\nprint(items[0])"), ('Разворот', 'Разверните список.', "items = [1, 2, 3]\nitems.reverse()\nprint(items)"), ('Список квадратов', 'Найдите сумму квадратов.', "squares = [x * x for x in range(1, 5)]\nprint(sum(squares))"), ('Фильтрация', 'Посчитайте чётные элементы.', "items = [1, 4, 6, 9]\nprint(len([x for x in items if x % 2 == 0]))"), ('Минимум', 'Найдите разницу максимума и минимума.', "items = [12, 5, 18, 9]\nprint(max(items) - min(items))"), ('Копия среза', 'Проверьте независимость копии.', "first = [1, 2]\nsecond = first[:]\nsecond.append(3)\nprint(len(first), len(second))"), ('Перечисление', 'Сложите элементы на чётных индексах.', "items = [5, 8, 2, 7, 4]\nprint(sum(items[::2]))"),
        )[n - 1]
    elif module == 'Словари, множества, кортежи':
        selected = (
            ('Значение словаря', 'Получите значение по ключу.', "marks = {'Аня': 5, 'Боря': 4}\nprint(marks['Аня'])"), ('Добавление ключа', 'Определите размер словаря.', "data = {'x': 1}\ndata['y'] = 2\nprint(len(data))"), ('Безопасный поиск', 'Используйте значение по умолчанию.', "data = {'a': 3}\nprint(data.get('b', 0))"), ('Множество', 'Посчитайте разные буквы.', "print(len(set('математика')))"), ('Пересечение', 'Найдите общие элементы множеств.', "print(len({1, 2, 3} & {2, 3, 4}))"), ('Объединение', 'Найдите размер объединения.', "print(len({'a', 'b'} | {'b', 'c'}))"), ('Кортеж', 'Обратитесь к последнему элементу.', "point = (4, 7, 9)\nprint(point[-1])"), ('Распаковка кортежа', 'Вычислите сумму координат.', "x, y = (6, 8)\nprint(x + y)"), ('Подсчёт слов', 'Соберите частоты слов.', "words = ['код', 'путь', 'код']\ncounts = {}\nfor word in words:\n    counts[word] = counts.get(word, 0) + 1\nprint(counts['код'])"), ('Ключи словаря', 'Сложите длины ключей.', "data = {'one': 1, 'two': 2}\nprint(sum(len(key) for key in data))"),
        )[n - 1]
    elif module == 'Функции':
        selected = (
            ('Возврат значения', 'Вызовите функцию.', "def twice(value):\n    return value * 2\n\nprint(twice(7))"), ('Два аргумента', 'Найдите результат функции.', "def area(width, height):\n    return width * height\n\nprint(area(4, 6))"), ('Аргумент по умолчанию', 'Используйте значение по умолчанию.', "def greet(name='мир'):\n    return 'Привет, ' + name\n\nprint(greet())"), ('Несколько результатов', 'Распакуйте результат функции.', "def bounds(values):\n    return min(values), max(values)\n\nlow, high = bounds([8, 2, 5])\nprint(high - low)"), ('Локальная переменная', 'Проследите работу локальной переменной.', "value = 10\ndef change():\n    value = 3\n    return value\n\nprint(change() + value)"), ('Именованный аргумент', 'Вызовите функцию с именованным аргументом.', "def power(base, exponent):\n    return base ** exponent\n\nprint(power(exponent=3, base=2))"), ('Проверка функцией', 'Определите результат логической функции.', "def is_even(number):\n    return number % 2 == 0\n\nprint(is_even(13))"), ('Функция и строка', 'Преобразуйте строку в функции.', "def initials(name):\n    return '.'.join(word[0] for word in name.split())\n\nprint(initials('Анна Мария'))"), ('Функция и список', 'Верните количество положительных чисел.', "def positive_count(values):\n    return sum(value > 0 for value in values)\n\nprint(positive_count([-2, 4, 0, 7]))"), ('Композиция функций', 'Выполните вложенный вызов.', "def add_one(value):\n    return value + 1\ndef square(value):\n    return value * value\n\nprint(square(add_one(4)))"),
        )[n - 1]
    elif module == 'Рекурсия':
        selected = (
            ('Факториал', 'Найдите факториал числа.', "def fact(n):\n    return 1 if n <= 1 else n * fact(n - 1)\n\nprint(fact(5))"), ('Сумма чисел', 'Найдите сумму от 1 до n.', "def total(n):\n    return 0 if n == 0 else n + total(n - 1)\n\nprint(total(6))"), ('Степень двойки', 'Вычислите степень рекурсией.', "def power2(n):\n    return 1 if n == 0 else 2 * power2(n - 1)\n\nprint(power2(4))"), ('Количество цифр', 'Посчитайте цифры числа.', "def digits(n):\n    return 1 if n < 10 else 1 + digits(n // 10)\n\nprint(digits(4821))"), ('Сумма цифр', 'Найдите сумму цифр рекурсией.', "def digit_sum(n):\n    return 0 if n == 0 else n % 10 + digit_sum(n // 10)\n\nprint(digit_sum(531))"), ('Числа Фибоначчи', 'Найдите число Фибоначчи.', "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n\nprint(fib(7))"), ('Обратная строка', 'Разверните строку рекурсией.', "def reverse(text):\n    return text if len(text) < 2 else reverse(text[1:]) + text[0]\n\nprint(reverse('код'))"), ('Максимум списка', 'Найдите максимум рекурсией.', "def maximum(values):\n    return values[0] if len(values) == 1 else max(values[0], maximum(values[1:]))\n\nprint(maximum([4, 9, 2]))"), ('Обратный отсчёт', 'Определите итог возвращаемого значения.', "def countdown(n):\n    if n == 0:\n        return 'старт'\n    return countdown(n - 1)\n\nprint(countdown(3))"), ('Чётность', 'Проверьте чётность через рекурсивное вычитание.', "def even(n):\n    return True if n == 0 else False if n == 1 else even(n - 2)\n\nprint(even(14))"),
        )[n - 1]
    elif module == 'Файлы':
        selected = (
            ('Сумма строк', 'Прочитайте числа из текстового файла.', "from io import StringIO\nfile = StringIO('4\\n7\\n2')\nprint(sum(int(line) for line in file))"), ('Количество строк', 'Посчитайте непустые строки.', "from io import StringIO\nfile = StringIO('код\\n\\nPython\\n')\nprint(sum(bool(line.strip()) for line in file))"), ('Максимум', 'Найдите максимум чисел в файле.', "from io import StringIO\nfile = StringIO('8\\n3\\n11')\nprint(max(int(line) for line in file))"), ('Фильтрация', 'Посчитайте чётные числа файла.', "from io import StringIO\nfile = StringIO('2\\n5\\n8\\n9')\nprint(sum(int(line) % 2 == 0 for line in file))"), ('Длины строк', 'Сложите длины строк без пробелов.', "from io import StringIO\nfile = StringIO('кот\\nдом')\nprint(sum(len(line.strip()) for line in file))"), ('Поиск слова', 'Посчитайте строки со словом Python.', "from io import StringIO\nfile = StringIO('Python\\nкод\\nPython 3')\nprint(sum('Python' in line for line in file))"), ('Среднее', 'Найдите целую часть среднего.', "from io import StringIO\nfile = StringIO('6\\n9\\n12')\nvalues = [int(line) for line in file]\nprint(sum(values) // len(values))"), ('Последняя строка', 'Определите последнюю строку файла.', "from io import StringIO\nfile = StringIO('первый\\nвторой\\nтретий')\nprint(list(file)[-1].strip())"), ('Пары чисел', 'Сложите вторые числа из строк.', "from io import StringIO\nfile = StringIO('2 5\\n4 7')\nprint(sum(map(lambda line: int(line.split()[1]), file)))"), ('Минимальная длина', 'Найдите минимальную длину слова.', "from io import StringIO\nfile = StringIO('код\\nалгоритм\\nЕГЭ')\nprint(min(len(line.strip()) for line in file))"),
        )[n - 1]
    elif module == 'Исключения':
        selected = (
            ('Деление на ноль', 'Определите ветку обработки ошибки.', "try:\n    print(8 // 0)\nexcept ZeroDivisionError:\n    print('нельзя делить')"), ('Некорректное число', 'Обработайте ошибку преобразования.', "try:\n    print(int('три'))\nexcept ValueError:\n    print('не число')"), ('Ключ словаря', 'Безопасно обратитесь к отсутствующему ключу.', "data = {'a': 1}\ntry:\n    print(data['b'])\nexcept KeyError:\n    print('нет ключа')"), ('Индекс списка', 'Обработайте выход за границы.', "items = [4, 5]\ntry:\n    print(items[3])\nexcept IndexError:\n    print('нет элемента')"), ('else в try', 'Определите, выполнится ли else.', "try:\n    value = int('12')\nexcept ValueError:\n    print('ошибка')\nelse:\n    print(value + 1)"), ('finally', 'Проследите обязательный блок finally.', "try:\n    print('работа')\nfinally:\n    print('готово')"), ('Несколько except', 'Определите нужный обработчик.', "try:\n    value = int('x')\nexcept ZeroDivisionError:\n    print('ноль')\nexcept ValueError:\n    print('текст')"), ('Проверка файла', 'Обработайте отсутствие файла.', "try:\n    raise FileNotFoundError\nexcept FileNotFoundError:\n    print('файл не найден')"), ('Собственная проверка', 'Проследите ручной вызов ошибки.', "score = -1\ntry:\n    if score < 0:\n        raise ValueError('балл')\nexcept ValueError as error:\n    print(error)"), ('Без ошибки', 'Определите результат корректного выражения.', "try:\n    print(18 // 3)\nexcept ZeroDivisionError:\n    print('ошибка')"),
        )[n - 1]
    elif module == 'Сортировка и поиск':
        selected = (
            ('Порядок чисел', 'Отсортируйте числа и возьмите середину.', "numbers = [8, 2, 5]\nprint(sorted(numbers)[1])"), ('Обратная сортировка', 'Найдите первый элемент обратной сортировки.', "numbers = [4, 9, 1]\nnumbers.sort(reverse=True)\nprint(numbers[0])"), ('Сортировка строк', 'Определите первое слово по алфавиту.', "words = ['зебра', 'аист', 'кот']\nprint(sorted(words)[0])"), ('Поиск индекса', 'Найдите позицию элемента.', "numbers = [3, 7, 4, 9]\nprint(numbers.index(4))"), ('Проверка наличия', 'Определите наличие элемента.', "numbers = [2, 5, 8]\nprint(7 in numbers)"), ('Сортировка по длине', 'Найдите самое короткое слово.', "words = ['алгоритм', 'код', 'цикл']\nprint(sorted(words, key=len)[0])"), ('Второй максимум', 'Найдите второй по величине элемент.', "numbers = [4, 10, 7, 10]\nprint(sorted(set(numbers))[-2])"), ('Двоичный поиск', 'Определите индекс найденного элемента.', "from bisect import bisect_left\nnumbers = [2, 4, 7, 9]\nprint(bisect_left(numbers, 7))"), ('Подсчёт совпадений', 'Посчитайте повторяющийся элемент.', "numbers = [1, 2, 1, 1]\nprint(numbers.count(1))"), ('Сортировка пар', 'Выберите пару с меньшим вторым значением.', "pairs = [('Аня', 8), ('Боря', 5)]\nprint(sorted(pairs, key=lambda pair: pair[1])[0][0])"),
        )[n - 1]
    elif module == 'Матрицы':
        selected = (
            ('Главная диагональ', 'Сложите главную диагональ матрицы.', "matrix = [[2, 1], [4, 3]]\nprint(matrix[0][0] + matrix[1][1])"), ('Сумма строки', 'Найдите сумму второй строки.', "matrix = [[1, 2], [4, 6]]\nprint(sum(matrix[1]))"), ('Сумма столбца', 'Найдите сумму первого столбца.', "matrix = [[3, 5], [7, 2], [1, 4]]\nprint(sum(row[0] for row in matrix))"), ('Максимум', 'Найдите максимум всей матрицы.', "matrix = [[2, 9], [4, 7]]\nprint(max(max(row) for row in matrix))"), ('Количество чётных', 'Посчитайте чётные элементы.', "matrix = [[1, 2], [6, 7]]\nprint(sum(value % 2 == 0 for row in matrix for value in row))"), ('Побочная диагональ', 'Сложите побочную диагональ.', "matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]\nprint(sum(matrix[i][2 - i] for i in range(3)))"), ('Транспонирование', 'Определите элемент после транспонирования.', "matrix = [[1, 2, 3], [4, 5, 6]]\ntransposed = list(zip(*matrix))\nprint(transposed[2][1])"), ('Минимум строки', 'Найдите минимум второй строки.', "matrix = [[8, 3], [6, 4]]\nprint(min(matrix[1]))"), ('Заполнение', 'Найдите сумму элементов, созданных циклом.', "matrix = [[row + column for column in range(3)] for row in range(2)]\nprint(sum(sum(row) for row in matrix))"), ('Граница матрицы', 'Сложите элементы первой строки и последней строки.', "matrix = [[1, 2], [3, 4], [5, 6]]\nprint(sum(matrix[0]) + sum(matrix[-1]))"),
        )[n - 1]
    elif module == 'Алгоритмы и оптимизация':
        selected = (
            ('Максимум соседей', 'Найдите максимальную сумму соседних элементов.', "values = [4, 9, 2, 8]\nprint(max(values[i] + values[i + 1] for i in range(len(values) - 1)))"), ('Минимальная разница', 'Найдите минимальную разницу соседей после сортировки.', "values = [8, 2, 11, 5]\nvalues.sort()\nprint(min(values[i + 1] - values[i] for i in range(len(values) - 1)))"), ('Префиксная сумма', 'Найдите наибольшую накопленную сумму.', "values = [3, -2, 5, -1]\ntotal = best = 0\nfor value in values:\n    total += value\n    best = max(best, total)\nprint(best)"), ('Подсчёт пар', 'Посчитайте пары с чётной суммой.', "values = [1, 2, 3, 4]\nprint(sum((values[i] + values[j]) % 2 == 0 for i in range(len(values)) for j in range(i + 1, len(values))))"), ('Уникальные значения', 'Посчитайте числа, встречающиеся один раз.', "values = [1, 2, 2, 3, 4, 4]\nprint(sum(values.count(value) == 1 for value in set(values)))"), ('Лучший отрезок', 'Найдите длину самого длинного блока положительных чисел.', "values = [1, 3, -1, 2, 4, 5]\nbest = current = 0\nfor value in values:\n    current = current + 1 if value > 0 else 0\n    best = max(best, current)\nprint(best)"), ('Два указателя', 'Найдите число пар с суммой не больше 7.', "values = [1, 2, 3, 5]\nprint(sum(values[i] + values[j] <= 7 for i in range(len(values)) for j in range(i + 1, len(values))))"), ('Частота', 'Найдите максимальную частоту числа.', "values = [2, 5, 2, 3, 2, 5]\nprint(max(values.count(value) for value in set(values)))"), ('Накопление минимума', 'Найдите минимальный элемент после первого.', "values = [9, 4, 7, 2]\nbest = values[0]\nfor value in values[1:]:\n    best = min(best, value)\nprint(best)"), ('Оптимальная покупка', 'Выберите максимальное число предметов в бюджете.', "prices = [2, 4, 3, 5]\nbudget = 8\ncount = 0\nfor price in sorted(prices):\n    if price <= budget:\n        budget -= price\n        count += 1\nprint(count)"),
        )[n - 1]
    elif module == 'Практические мини-задачи':
        selected = (
            ('Билет в кино', 'В кинотеатре билет стоит 350 рублей. Для школьника действует скидка 20%. Выведите стоимость билета для школьника.', "price = 350\nis_student = True\nif is_student:\n    price *= 0.8\nprint(int(price))"),
            ('Пароль', 'Проверьте, подходит ли пароль: длина не меньше 8 символов и в нём есть цифра.', "password = 'Python2026'\nhas_digit = any(symbol.isdigit() for symbol in password)\nprint(len(password) >= 8 and has_digit)"),
            ('Температура недели', 'Найдите количество дней с температурой выше нуля.', "temperatures = [-3, 0, 2, 5, -1, 4, 1]\nprint(sum(value > 0 for value in temperatures))"),
            ('Самое длинное слово', 'Найдите длину самого длинного слова в сообщении.', "message = 'учимся писать понятные программы'\nprint(max(len(word) for word in message.split()))"),
            ('Сдача в магазине', 'Покупатель дал 1000 рублей. Найдите сдачу после покупки товаров.', "money = 1000\ncart = [179, 245, 130]\nprint(money - sum(cart))"),
            ('Номер места', 'В ряду 8 мест. По номеру билета определите номер ряда и места.', "ticket = 19\nrow = (ticket - 1) // 8 + 1\nseat = (ticket - 1) % 8 + 1\nprint(row, seat)"),
            ('Палиндром фразы', 'Проверьте фразу без пробелов и регистра на палиндром.', "phrase = 'А роза упала на лапу Азора'\nprepared = phrase.replace(' ', '').lower()\nprint(prepared == prepared[::-1])"),
            ('Копилка', 'Сколько монет нужно добавить до цели, если каждая монета по 10 рублей?', "saved = 73\ngoal = 120\ncoins = (goal - saved + 9) // 10\nprint(coins)"),
            ('Дневник оценок', 'Найдите средний балл, округлённый вниз.', "marks = [5, 4, 5, 3, 4]\nprint(sum(marks) // len(marks))"),
            ('Шифр Цезаря', 'Сдвиньте каждую букву латинского слова на один шаг вперёд.', "word = 'code'\nresult = ''.join(chr(ord(letter) + 1) for letter in word)\nprint(result)"),
        )[n - 1]
    else:
        raise ValueError(f'Неизвестный модуль тематического банка: {module}')
    return selected


def foundation_payload(item: dict) -> dict:
    """Строит содержимое тематического задания с оформленным блоком кода."""
    n = _foundation_variant_number(item)
    module = str(item.get('module') or 'Практические мини-задачи')
    activity, prompt, code = _foundation_case(module, n)
    answer = _output_of(code)
    level = 'базовый' if n <= 3 else ('средний' if n <= 7 else 'продвинутый')
    title = f'{activity}: {module}'
    content_html = (
        f'<p>{prompt}</p>'
        f'<pre><code>{html.escape(code)}</code></pre>'
        '<p>Ответ запишите точно, включая регистр и знаки препинания, если они есть.</p>'
    )
    payload = dict(item)
    payload.update({
        'title': title,
        'level': level,
        'content_html': content_html,
        'answer': answer,
        'solution': code,
        'starter_code': f'# {module}\n{code}',
    })
    return payload


def _key(package_slug: str, item: dict, variant_index: int) -> str:
    raw = f"{package_slug}:{item.get('id') or item.get('task_number')}:{variant_index}"
    return f"author/python-ege/{hashlib.sha1(raw.encode()).hexdigest()[:20]}"


@lru_cache(maxsize=1)
def foundations_metadata():
    """Resolve thematic labels for existing imports without rewriting student tasks."""
    path = Path(__file__).resolve().parents[2] / 'data/task_banks/python_foundations.json'
    with path.open(encoding='utf-8') as handle:
        package = json.load(handle)
    return {_key(package['slug'], item, index): {
        'title': foundation_payload(item)['title'], 'module': item['module']
    } for index, item in enumerate(package['tasks'], 1)}


def validate_package(data: dict) -> list[str]:
    errors = []
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return ["schema_version должен быть равен 1"]
    if not data.get("slug") or not data.get("title"):
        errors.append("нужны slug и title")
    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        errors.append("tasks должен быть непустым списком")
        return errors
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"tasks[{i}] не является объектом")
            continue
        if not isinstance(item.get("task_number"), int) or not 1 <= item["task_number"] <= 27:
            errors.append(f"tasks[{i}].task_number вне диапазона 1..27")
        variants = item.get("variants") or [item]
        for j, variant in enumerate(variants, 1):
            for field in ("content_html", "answer", "solution"):
                if not str(variant.get(field) or "").strip():
                    errors.append(f"tasks[{i}].variants[{j}].{field} пуст")
    return errors


def import_package(data: dict, db, *, dry_run=False) -> dict:
    errors = validate_package(data)
    if errors:
        raise ValueError("; ".join(errors))
    slug = data["slug"]
    course = Course.query.filter_by(slug=slug).first()
    if not course:
        course = Course(title=data["title"], slug=slug, is_active=True)
        db.session.add(course)
        db.session.flush()
    for number in range(1, 28):
        template = CourseTaskTemplate.query.filter_by(course_id=course.id, task_number=number).first()
        if not template:
            db.session.add(CourseTaskTemplate(course_id=course.id, task_number=number, max_primary_score=1, description="Python для ЕГЭ"))
    created = updated = 0
    for item in data["tasks"]:
        for variant_index, variant in enumerate(item.get("variants") or [item], 1):
            source = _key(slug, item, variant_index)
            task = Tasks.query.filter_by(source_prototype=source).first()
            values = dict(course_id=course.id, task_number=item["task_number"], content_html=variant["content_html"], answer=str(variant["answer"]),
                          difficulty_level=int(variant.get("difficulty_level", item.get("difficulty_level", 2))), bank_origin="imported",
                          starter_code=variant.get("starter_code"), max_score=int(variant.get("max_score", 1)), source_prototype=source, is_active=True)
            if task:
                if not dry_run:
                    for key, value in values.items(): setattr(task, key, value)
                    solution = TaskSolution.query.filter_by(task_id=task.task_id).first()
                    if solution:
                        solution.solution_text = variant["solution"]
                        solution.source = "manual"
                updated += 1
            else:
                if not dry_run:
                    task = Tasks(**values)
                    db.session.add(task)
                    db.session.flush()
                    db.session.add(TaskSolution(task_id=task.task_id, solution_text=variant["solution"], source="manual", needs_manual_review=False))
                created += 1
    if not dry_run:
        db.session.commit()
    return {"course_slug": slug, "created": created, "updated": updated, "total": created + updated}


def import_package_file(path: str | Path, db, *, dry_run=False) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return import_package(json.load(handle), db, dry_run=dry_run)


def import_foundations_package(data: dict, db, *, dry_run=False) -> dict:
    """Импорт тематического банка без экзаменационной нумерации."""
    tasks = data.get("tasks") or []
    if len(tasks) < 160 or len({item.get("module") for item in tasks}) < 16:
        raise ValueError("тематический банк должен содержать минимум 160 заданий и 16 модулей")
    course = Course.query.filter_by(slug=data["slug"]).first()
    if not course:
        course = Course(title=data["title"], slug=data["slug"], is_active=True)
        db.session.add(course)
        db.session.flush()
    created = updated = 0
    for index, item in enumerate(tasks, 1):
        source = _key(data["slug"], item, index)
        task = Tasks.query.filter_by(source_prototype=source).first()
        payload = foundation_payload(item)
        values = dict(course_id=course.id, task_number=1000 + index, content_html=payload["content_html"], answer=str(payload["answer"]),
                      difficulty_level={"базовый": 1, "средний": 2, "продвинутый": 3}.get(payload.get("level"), 2),
                      bank_origin="imported", starter_code=payload.get("starter_code"), source_prototype=source, max_score=1, is_active=True)
        if task:
            if not dry_run:
                for key, value in values.items(): setattr(task, key, value)
                solution = TaskSolution.query.filter_by(task_id=task.task_id).first()
                if solution:
                    solution.solution_text = payload["solution"]
            updated += 1
        else:
            if not dry_run:
                task = Tasks(**values)
                db.session.add(task)
                db.session.flush()
                db.session.add(TaskSolution(task_id=task.task_id, solution_text=payload["solution"], source="manual"))
            created += 1
    if not dry_run:
        db.session.commit()
    return {"course_slug": data["slug"], "created": created, "updated": updated, "total": created + updated}
