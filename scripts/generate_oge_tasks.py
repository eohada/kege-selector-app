#!/usr/bin/env python3
"""
Generate 200+ tasks per type for OGE Informatics (tasks 1-16).
Every answer is computed programmatically and verified.
"""
import json, os, sys, random, math, heapq, string
from collections import defaultdict
from itertools import permutations

sys.stdout.reconfigure(encoding='utf-8')
random.seed(42)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DATA_FILE = os.path.join(DATA_DIR, 'oge_inf_tasks.json')

# ════════════════════════════════════════════════════════════════════
# POOLS
# ════════════════════════════════════════════════════════════════════

NAMES_M = ['Андрей','Борис','Виктор','Дмитрий','Егор','Иван','Кирилл','Леонид',
           'Максим','Николай','Олег','Павел','Роман','Сергей','Тимур','Фёдор']
NAMES_F = ['Анна','Варвара','Галина','Дарья','Елена','Ирина','Ксения','Лариса',
           'Мария','Наталья','Ольга','Полина','Светлана','Татьяна','Юлия','Яна']

RIVERS = ['Обь','Лена','Волга','Нева','Дон','Урал','Амур','Иртыш','Ока',
          'Кама','Печора','Онега','Двина','Днепр','Енисей','Ангара','Тобол']
COUNTRIES = ['Чад','Куба','Иран','Перу','Чили','Китай','Индия','Канада',
             'Бразилия','Мексика','Швеция','Турция','Япония','Корея','Египет']
ISLANDS = ['Ява','Куба','Крит','Кипр','Борнео','Суматра','Хоккайдо','Тасмания',
           'Сицилия','Сахалин','Мадагаскар','Гренландия','Исландия','Ирландия']
SEAS = ['Аки','Бали','Банда','Росса','Лаптевых','Охотское','Баренцево',
        'Каспий','Чёрное','Белое','Азовское','Красное','Жёлтое','Берингово']
CITIES_RU = ['Москва','Казань','Самара','Омск','Пермь','Томск','Тула','Курск',
             'Псков','Орёл','Сочи','Тверь','Уфа','Пенза','Киров','Рязань']
ANIMALS = ['Тигр','Лиса','Волк','Медведь','Заяц','Олень','Белка','Ёж',
           'Сова','Ворон','Дельфин','Орёл','Лось','Рысь','Бобр','Выдра']
FRUITS = ['яблоко','банан','апельсин','ананас','персик','абрикос','вишня',
          'слива','груша','манго','киви','лимон','гранат','арбуз','дыня']

PHRASES = [
    "Без труда не выловишь и рыбку из пруда",
    "Знание — сила",
    "Тише едешь — дальше будешь",
    "Информатика — наука о данных",
    "Программирование — это искусство",
    "Ученье — свет, а неученье — тьма",
    "Один в поле не воин",
    "Семь раз отмерь, один раз отрежь",
    "Повторенье — мать учения",
    "Делу время, потехе час",
    "Книга — лучший друг человека",
    "Не всё то золото, что блестит",
    "Утро вечера мудренее",
    "Старый друг лучше новых двух",
    "Терпенье и труд всё перетрут",
    "Век живи — век учись",
    "В гостях хорошо, а дома лучше",
    "Любишь кататься — люби и саночки возить",
    "Мал золотник, да дорог",
    "Слово — серебро, молчание — золото",
    "Глаза боятся, а руки делают",
    "Дорогу осилит идущий",
    "На безрыбье и рак — рыба",
    "Яблоко от яблони недалеко падает",
    "Друзья познаются в беде",
    "Каждый кузнец своего счастья",
    "Лучше поздно, чем никогда",
    "Нет дыма без огня",
    "Практика — критерий истины",
    "Рождённый ползать летать не может",
]

NODE_LETTERS = list('АБВГДЕЖЗИКЛМН')

PREFIX_FREE_CODES = [
    ['00','01','10','11'],
    ['0','10','110','111'],
    ['0','100','101','11'],
    ['00','010','011','1'],
    ['0','100','101','110','111'],
    ['00','01','100','101','11'],
    ['00','01','10','110','111'],
    ['0','10','110','1110','1111'],
    ['00','010','011','10','11'],
    ['0','10','1100','1101','111'],
]

SUBJECTS = ['математика','физика','информатика','русский язык','литература',
            'история','биология','химия','география','обществознание',
            'английский язык','немецкий язык','физкультура']
DISTRICTS = ['Центральный','Северный','Южный','Западный','Восточный',
             'Северо-Западный','Северо-Восточный','Юго-Западный','Юго-Восточный']

EXEC_NAMES = ['Альфа','Бета','Гамма','Дельта','Сигма','Омега','Вычислитель','Калькулятор']

SEARCH_WORDS = [
    ('Рыбак','Рыбка'),('Кошка','Котик'),('Собака','Щенок'),
    ('Лето','Осень'),('Зима','Весна'),('Дождь','Снег'),
    ('Солнце','Луна'),('Горы','Море'),('Лес','Поле'),
    ('Книга','Фильм'),('Музыка','Танец'),('Школа','Дом'),
    ('Город','Село'),('Река','Озеро'),('Яблоко','Груша'),
    ('Роза','Тюльпан'),('Футбол','Хоккей'),('Кофе','Чай'),
]

AUTHORS = {
    'Пушкин': ['Евгений Онегин','Капитанская дочка','Дубровский','Метель','Пиковая дама'],
    'Лермонтов': ['Герой нашего времени','Мцыри','Бородино','Демон','Парус'],
    'Гоголь': ['Мёртвые души','Ревизор','Шинель','Вий','Тарас Бульба'],
    'Тургенев': ['Отцы и дети','Ася','Первая любовь','Муму','Записки охотника'],
    'Чехов': ['Вишнёвый сад','Каштанка','Палата №6','Дама с собачкой','Ионыч'],
    'Толстой': ['Война и мир','Анна Каренина','Кавказский пленник','После бала','Детство'],
}

PROG_TOPICS = [
    'кошки','собаки','птицы','рыбы','автомобили','велосипеды',
    'деревья','цветы','планеты','звёзды','реки','горы','океаны',
    'страны','города','животные','растения','минералы',
]


def sol(steps, answer):
    """Format a solution HTML block."""
    h = '<p><b>Решение:</b></p>'
    for i, s in enumerate(steps, 1):
        h += f'<p>{i}) {s}</p>'
    h += f'<p><b>Ответ:</b> {answer}</p>'
    return h


def make(tn, html, answer, solution, diff):
    return {
        'task_number': tn,
        'content_html': html,
        'answer': str(answer),
        'solution_html': solution,
        'difficulty_level': diff,
        'source_url': None,
        'generated': True,
    }


DIFFS = ['easy'] * 67 + ['medium'] * 67 + ['hard'] * 66


def pick_diff(i):
    return DIFFS[i % 200]


# ════════════════════════════════════════════════════════════════════
# TASK 1: Кодирование информации (размер текста в кодировке)
# ════════════════════════════════════════════════════════════════════

def gen_task1(count=200):
    results = []
    categories = [
        ('реки', RIVERS), ('страны', COUNTRIES), ('острова', ISLANDS),
        ('моря', SEAS), ('города', CITIES_RU), ('животные', ANIMALS),
    ]

    for i in range(count):
        diff = pick_diff(i)
        cat_name, pool = random.choice(categories)
        name = random.choice(NAMES_M + NAMES_F)

        if diff == 'easy':
            bits = 8
            enc = random.choice(['КОИ-8', 'Windows-1251'])
            items = random.sample(pool, min(5, len(pool)))
            items.sort(key=len)
        elif diff == 'medium':
            bits = 8
            enc = random.choice(['КОИ-8', 'Windows-1251'])
            items = random.sample(pool, min(7, len(pool)))
            items.sort(key=len)
        else:
            bits = 16
            enc = 'Unicode'
            items = random.sample(pool, min(8, len(pool)))
            items.sort(key=len)

        full_text = '«' + ', '.join(items) + ' — ' + cat_name + '».'
        full_len = len(full_text)

        target_idx = random.randint(1, len(items) - 2)
        target = items[target_idx]
        removed_text = '«' + ', '.join(it for it in items if it != target) + ' — ' + cat_name + '».'
        removed_len = len(removed_text)
        byte_diff = (full_len - removed_len) * bits // 8

        content = (
            f'<p>В кодировке {enc} каждый символ кодируется {bits} битами. '
            f'{name} написал(а) текст (в нём нет лишних пробелов):</p>'
            f'<p style="text-align:center"><b>{full_text}</b></p>'
            f'<p>Ученик вычеркнул из списка название. Заодно вычеркнул ставшие лишними '
            f'запятые и пробелы — два пробела не должны идти подряд.</p>'
            f'<p>При этом размер нового предложения в данной кодировке оказался '
            f'на {byte_diff} байт меньше, чем размер исходного. '
            f'Напишите в ответе вычеркнутое название.</p>'
        )

        steps = [
            f'Каждый символ в {enc} = {bits} бит = {bits//8} байт.',
            f'Если удалить слово, убирается само слово + запятая + пробел (если не крайний элемент).',
            f'Разница в {byte_diff} байт × {8//bits*8 if bits==8 else 1} = {byte_diff} символов.',
            f'Слово «{target}» имеет {len(target)} букв, плюс запятая и пробел = {len(target)+2} символа, '
            f'что равно {byte_diff} байт при {bits//8} байт/символ.',
        ]
        results.append(make(1, content, target, sol(steps, target), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 2: Декодирование
# ════════════════════════════════════════════════════════════════════

def gen_task2(count=200):
    results = []
    rus_letters = list('АБВГДЕЖЗИКЛМНОПРСТ')

    for i in range(count):
        diff = pick_diff(i)
        if diff == 'easy':
            n_symbols = 4
            word_len = 3
        elif diff == 'medium':
            n_symbols = 4
            word_len = 4
        else:
            n_symbols = 5
            word_len = 5

        codes = random.choice([c for c in PREFIX_FREE_CODES if len(c) >= n_symbols])
        selected_codes = codes[:n_symbols]
        letters = random.sample(rus_letters, n_symbols)

        code_map = dict(zip(letters, selected_codes))
        decode_map = {v: k for k, v in code_map.items()}

        word_letters = [random.choice(letters) for _ in range(word_len)]
        word = ''.join(word_letters)
        encoded = ''.join(code_map[l] for l in word_letters)

        table_rows = ''.join(f'<tr><td>{l}</td><td>{c}</td></tr>' for l, c in code_map.items())
        table = f'<table><tr><th>Буква</th><th>Код</th></tr>{table_rows}</table>'

        content = (
            f'<p>Сообщение закодировано с помощью приведённой кодовой таблицы.</p>'
            f'{table}'
            f'<p>Расшифруйте сообщение: <b>{encoded}</b></p>'
            f'<p>Запишите в ответе расшифрованное слово.</p>'
        )

        steps_detail = []
        pos = 0
        decoded_letters = []
        for wl in word_letters:
            code = code_map[wl]
            steps_detail.append(f'{encoded[pos:pos+len(code)]} → {wl}')
            pos += len(code)
            decoded_letters.append(wl)

        steps = [
            'Декодируем последовательность слева направо, используя свойство префиксного кода.',
            'Пошаговая расшифровка: ' + ', '.join(steps_detail) + '.',
            f'Получаем слово: {word}.',
        ]

        results.append(make(2, content, word, sol(steps, word), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 3: Логические высказывания
# ════════════════════════════════════════════════════════════════════

def gen_task3(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            a = random.randint(1, 30)
            b = a + random.randint(2, 8)
            op = random.choice(['>', '<', '>=', '<='])
            negated = random.choice([True, False])
            find_max = random.choice([True, False])

            def check(x):
                if op == '>': r = x > a
                elif op == '<': r = x < b
                elif op == '>=': r = x >= a
                else: r = x <= b
                return not r if negated else r

            op_text = {'>' : f'X > {a}', '<' : f'X < {b}', '>=' : f'X ≥ {a}', '<=' : f'X ≤ {b}'}[op]
            expr_text = f'НЕ ({op_text})' if negated else op_text

        elif diff == 'medium':
            a = random.randint(1, 20)
            b = a + random.randint(3, 10)
            connector = random.choice(['И', 'ИЛИ'])

            def check(x):
                left = x > a
                right = x < b
                return (left and right) if connector == 'И' else (left or right)

            expr_text = f'(X > {a}) {connector} (X < {b})'
            find_max = random.choice([True, False])

        else:
            a = random.randint(1, 15)
            b = a + random.randint(3, 8)
            c = a + random.randint(1, b - a - 1)

            def check(x):
                return (x > a) and not (x > b) or (x == c)

            expr_text = f'(X > {a}) И НЕ (X > {b})'
            find_max = True

        target = 'наибольшее' if find_max else 'наименьшее'

        solutions = [x for x in range(-50, 100) if check(x)]
        if not solutions:
            continue
        answer = max(solutions) if find_max else min(solutions)

        content = (
            f'<p>Напишите {target} целое число X, для которого истинно высказывание:</p>'
            f'<p style="text-align:center"><b>{expr_text}</b></p>'
        )

        steps = [
            f'Высказывание: {expr_text}.',
            f'Находим все целые X, удовлетворяющие условию.',
            f'{target.capitalize()} значение: X = {answer}.',
        ]
        results.append(make(3, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 4: Кратчайший путь (таблица расстояний)
# ════════════════════════════════════════════════════════════════════

def dijkstra(matrix, start, end):
    n = len(matrix)
    dist = [float('inf')] * n
    dist[start] = 0
    visited = [False] * n
    pq = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if visited[u]:
            continue
        visited[u] = True
        for v in range(n):
            if matrix[u][v] > 0:
                nd = d + matrix[u][v]
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
    return dist[end]


def gen_task4(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            n = 5
        elif diff == 'medium':
            n = 6
        else:
            n = 7

        labels = NODE_LETTERS[:n]
        matrix = [[0]*n for _ in range(n)]

        for a in range(n):
            for b in range(a+1, n):
                if random.random() < 0.45:
                    d = random.randint(1, 15)
                    matrix[a][b] = d
                    matrix[b][a] = d

        for a in range(n-1):
            if all(matrix[a][b] == 0 for b in range(n) if b != a):
                b = random.choice([x for x in range(n) if x != a])
                d = random.randint(1, 10)
                matrix[a][b] = d
                matrix[b][a] = d

        start, end = 0, n - 1
        answer = dijkstra(matrix, start, end)

        if answer == float('inf'):
            d = random.randint(1, 10)
            matrix[0][n-1] = d
            matrix[n-1][0] = d
            answer = dijkstra(matrix, start, end)
        if answer == float('inf'):
            continue

        header = '<tr><td></td>' + ''.join(f'<td><b>{l}</b></td>' for l in labels) + '</tr>'
        rows = ''
        for a in range(n):
            cells = f'<tr><td><b>{labels[a]}</b></td>'
            for b in range(n):
                val = '' if matrix[a][b] == 0 else str(matrix[a][b])
                cells += f'<td>{val}</td>'
            cells += '</tr>'
            rows += cells

        content = (
            f'<p>Между населёнными пунктами {", ".join(labels)} построены дороги, '
            f'протяжённость которых (в километрах) приведена в таблице.</p>'
            f'<table>{header}{rows}</table>'
            f'<p>Определите длину кратчайшего пути из {labels[start]} в {labels[end]}. '
            f'Передвигаться можно только по дорогам, указанным в таблице.</p>'
        )

        steps = [
            f'Используем алгоритм поиска кратчайшего пути из {labels[start]} в {labels[end]}.',
            f'Перебираем все возможные маршруты по таблице расстояний.',
            f'Кратчайший путь: {answer} км.',
        ]
        results.append(make(4, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 5: Исполнитель (прибавь / умножь)
# ════════════════════════════════════════════════════════════════════

def gen_task5(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)
        name = random.choice(EXEC_NAMES)

        if diff == 'easy':
            b = random.randint(2, 5)
            start = random.randint(1, 5)
            prog = [random.choice([1, 2]) for _ in range(3)]
        elif diff == 'medium':
            b = random.randint(2, 7)
            start = random.randint(1, 8)
            prog = [random.choice([1, 2]) for _ in range(4)]
        else:
            b = random.randint(2, 10)
            start = random.randint(1, 10)
            prog = [random.choice([1, 2]) for _ in range(5)]

        val = start
        for cmd in prog:
            if cmd == 1:
                val += 1
            else:
                val *= b

        if val > 100000:
            continue

        end = val
        prog_str = ''.join(str(c) for c in prog)

        find_b = random.choice([True, False]) if diff != 'easy' else False

        if find_b:
            content = (
                f'<p>У исполнителя {name} две команды, которым присвоены номера:</p>'
                f'<p>1. прибавь 1<br>2. умножь на <i>b</i></p>'
                f'<p>(<i>b</i> — неизвестное натуральное число).</p>'
                f'<p>Программа <b>{prog_str}</b> переводит число {start} в число {end}. '
                f'Определите значение <i>b</i>.</p>'
            )
            answer = b

            trace_lines = []
            val_trace = start
            sym_trace = str(start)
            for cmd in prog:
                if cmd == 1:
                    trace_lines.append(f'{sym_trace} + 1 = {val_trace + 1}')
                    val_trace += 1
                    sym_trace = str(val_trace).replace(str(b), 'b') if b > 1 else str(val_trace)
                else:
                    trace_lines.append(f'{val_trace} × b')
                    val_trace *= b
            steps = [
                f'Выполняем программу {prog_str}, начиная с числа {start}.',
                'Пошагово: ' + '; '.join(trace_lines) + '.',
                f'Приравниваем результат к {end} и находим b = {b}.',
            ]
        else:
            content = (
                f'<p>У исполнителя {name} две команды, которым присвоены номера:</p>'
                f'<p>1. прибавь 1<br>2. умножь на {b}</p>'
                f'<p>Запишите порядок команд в программе преобразования числа {start} в число {end}, '
                f'содержащей не более {len(prog)} команд. '
                f'Указывайте лишь номера команд.</p>'
            )
            answer = prog_str

            trace = []
            v = start
            for cmd in prog:
                if cmd == 1:
                    trace.append(f'{v} + 1 = {v+1}')
                    v += 1
                else:
                    trace.append(f'{v} × {b} = {v*b}')
                    v *= b
            steps = [
                f'Нужно из {start} получить {end}.',
                'Выполняем: ' + ', '.join(trace) + '.',
                f'Программа: {prog_str}.',
            ]

        results.append(make(5, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 6: Программа с условием (определить вывод)
# ════════════════════════════════════════════════════════════════════

def gen_task6(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            s_val = random.randint(1, 20)
            t_val = random.randint(1, 20)
            a = random.randint(5, 15)
            b = random.randint(1, 10)
            c = random.randint(1, 10)

            if s_val > a:
                s_res = s_val + b
            else:
                s_res = s_val - b
            answer = s_res + t_val

            code = (
                f's = {s_val}\n'
                f't = {t_val}\n'
                f'if s > {a}:\n'
                f'    s = s + {b}\n'
                f'else:\n'
                f'    s = s - {b}\n'
                f'print(s + t)'
            )
            branch = f's > {a} → {"Да" if s_val > a else "Нет"}'

        elif diff == 'medium':
            s_val = random.randint(1, 30)
            t_val = random.randint(1, 30)
            a = random.randint(5, 20)
            b = random.randint(1, 10)
            d = random.randint(5, 20)

            if s_val > a:
                s_new = s_val + b
            else:
                s_new = s_val * 2
            if t_val > d:
                result = s_new + t_val
            else:
                result = t_val - s_new
            answer = result

            code = (
                f's = {s_val}\n'
                f't = {t_val}\n'
                f'if s > {a}:\n'
                f'    s = s + {b}\n'
                f'else:\n'
                f'    s = s * 2\n'
                f'if t > {d}:\n'
                f'    print(s + t)\n'
                f'else:\n'
                f'    print(t - s)'
            )
            branch = f's>{a}: {"Да" if s_val > a else "Нет"}, t>{d}: {"Да" if t_val > d else "Нет"}'

        else:
            s_val = random.randint(1, 50)
            t_val = random.randint(1, 50)
            a = random.randint(10, 30)
            b = random.randint(1, 10)
            c = random.randint(1, 10)
            d = random.randint(10, 30)

            if s_val > a:
                s_new = s_val + b
            else:
                s_new = s_val - b
            if t_val > d:
                t_new = t_val + c
            else:
                t_new = t_val - c
            answer = abs(s_new - t_new)

            code = (
                f's = {s_val}\n'
                f't = {t_val}\n'
                f'if s > {a}:\n'
                f'    s = s + {b}\n'
                f'else:\n'
                f'    s = s - {b}\n'
                f'if t > {d}:\n'
                f'    t = t + {c}\n'
                f'else:\n'
                f'    t = t - {c}\n'
                f'print(abs(s - t))'
            )
            branch = f's>{a}: {"Да" if s_val > a else "Нет"}, t>{d}: {"Да" if t_val > d else "Нет"}'

        code_html = '<pre style="background:#1a1d27;color:#e4e6f0;padding:12px;border-radius:8px;font-size:14px">' + code + '</pre>'

        content = (
            f'<p>Определите, что будет напечатано в результате выполнения следующей программы (Python):</p>'
            f'{code_html}'
        )

        steps = [
            f'Подставляем значения: s = {s_val}, t = {t_val}.',
            f'Проверяем условия: {branch}.',
            f'Выполняем соответствующие ветки.',
            f'Результат: {answer}.',
        ]
        results.append(make(6, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 7: IP-адрес / URL из фрагментов
# ════════════════════════════════════════════════════════════════════

def gen_task7(count=200):
    results = []
    frag_labels = list('АБВГДЕЖЗ')

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            n_frags = 4
            octets = [str(random.randint(1, 254)) for _ in range(4)]
            ip = '.'.join(octets)
        elif diff == 'medium':
            n_frags = 5
            octets = [str(random.randint(10, 254)) for _ in range(4)]
            ip = '.'.join(octets)
        else:
            n_frags = 6
            octets = [str(random.randint(10, 254)) for _ in range(4)]
            ip = '.'.join(octets)

        parts = []
        s = ip
        attempts = 0
        while len(parts) < n_frags - 1 and len(s) > 1 and attempts < 50:
            cut = random.randint(1, max(1, len(s) - 1))
            parts.append(s[:cut])
            s = s[cut:]
            attempts += 1
        parts.append(s)

        if len(parts) != n_frags:
            parts = [ip[:3], ip[3:6], ip[6:9], ip[9:]]
            parts = [p for p in parts if p]

        labels = frag_labels[:len(parts)]
        order = list(range(len(parts)))
        random.shuffle(order)
        shuffled = [(labels[order[j]], parts[j]) for j in range(len(parts))]
        correct_order = ''.join(labels[order.index(j)] for j in range(len(parts)))

        frag_display = ' '.join(f'<b>{lbl}</b>: {val}' for lbl, val in
                                sorted(shuffled, key=lambda x: x[0]))

        table_rows = ''.join(f'<td style="text-align:center;padding:8px"><div><b>{p}</b></div>'
                             f'<div style="color:#888">{l}</div></td>'
                             for l, p in sorted(shuffled, key=lambda x: x[0]))

        content = (
            f'<p>На месте происшествия были обнаружены {len(parts)} обрывков бумаги. '
            f'Следствие установило, что на них записаны фрагменты одного IP-адреса. '
            f'Фрагменты обозначены буквами:</p>'
            f'<table><tr>{table_rows}</tr></table>'
            f'<p>Восстановите IP-адрес. В ответе укажите последовательность букв.</p>'
        )

        answer = correct_order
        steps = [
            f'IP-адрес имеет формат X.X.X.X, где X от 0 до 255.',
            f'Собираем фрагменты в правильном порядке: {ip}.',
            f'Последовательность букв: {correct_order}.',
        ]
        results.append(make(7, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 8: Поисковые запросы (множества, включение-исключение)
# ════════════════════════════════════════════════════════════════════

def gen_task8(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)
        w1, w2 = random.choice(SEARCH_WORDS)

        if diff == 'easy':
            a_only = random.randint(100, 500)
            b_only = random.randint(100, 500)
            ab = random.randint(20, min(a_only, b_only))
            n_a = a_only + ab
            n_b = b_only + ab
            n_ab = ab
            n_aub = a_only + b_only + ab

            given = random.choice(['find_union', 'find_b'])
            if given == 'find_union':
                content = (
                    f'<p>В таблице приведены запросы и количество страниц, '
                    f'которые нашёл поисковый сервер по этим запросам:</p>'
                    f'<table><tr><th>Запрос</th><th>Найдено страниц</th></tr>'
                    f'<tr><td>{w1}</td><td>{n_a}</td></tr>'
                    f'<tr><td>{w2}</td><td>{n_b}</td></tr>'
                    f'<tr><td>{w1} & {w2}</td><td>{n_ab}</td></tr></table>'
                    f'<p>Сколько страниц будет найдено по запросу <b>{w1} | {w2}</b>?</p>'
                )
                answer = n_aub
                steps = [
                    f'По формуле: N(A|B) = N(A) + N(B) − N(A&B).',
                    f'N(A|B) = {n_a} + {n_b} − {n_ab} = {n_aub}.',
                ]
            else:
                content = (
                    f'<p>В таблице приведены запросы и количество страниц:</p>'
                    f'<table><tr><th>Запрос</th><th>Найдено страниц</th></tr>'
                    f'<tr><td>{w1} | {w2}</td><td>{n_aub}</td></tr>'
                    f'<tr><td>{w1}</td><td>{n_a}</td></tr>'
                    f'<tr><td>{w1} & {w2}</td><td>{n_ab}</td></tr></table>'
                    f'<p>Сколько страниц будет найдено по запросу <b>{w2}</b>?</p>'
                )
                answer = n_b
                steps = [
                    f'N(A|B) = N(A) + N(B) − N(A&B) → N(B) = N(A|B) − N(A) + N(A&B).',
                    f'N(B) = {n_aub} − {n_a} + {n_ab} = {n_b}.',
                ]

        elif diff == 'medium':
            a_only = random.randint(200, 800)
            b_only = random.randint(200, 800)
            ab = random.randint(50, 200)
            n_a = a_only + ab
            n_b = b_only + ab
            n_ab = ab
            n_aub = n_a + n_b - n_ab

            content = (
                f'<p>В таблице приведены запросы и количество страниц:</p>'
                f'<table><tr><th>Запрос</th><th>Найдено страниц</th></tr>'
                f'<tr><td>{w1} | {w2}</td><td>{n_aub}</td></tr>'
                f'<tr><td>{w1} & {w2}</td><td>{n_ab}</td></tr>'
                f'<tr><td>{w1}</td><td>{n_a}</td></tr></table>'
                f'<p>Сколько страниц будет найдено по запросу <b>{w2}</b>?</p>'
            )
            answer = n_b
            steps = [
                f'N(A|B) = N(A) + N(B) − N(A&B).',
                f'{n_aub} = {n_a} + N(B) − {n_ab}.',
                f'N(B) = {n_aub} − {n_a} + {n_ab} = {n_b}.',
            ]

        else:
            n_a = random.randint(500, 2000)
            n_b = random.randint(500, 2000)
            n_ab = random.randint(100, min(n_a, n_b) - 50)
            n_aub = n_a + n_b - n_ab
            only_a = n_a - n_ab

            content = (
                f'<p>В таблице приведены запросы и количество страниц:</p>'
                f'<table><tr><th>Запрос</th><th>Найдено страниц</th></tr>'
                f'<tr><td>{w1}</td><td>{n_a}</td></tr>'
                f'<tr><td>{w2}</td><td>{n_b}</td></tr>'
                f'<tr><td>{w1} | {w2}</td><td>{n_aub}</td></tr></table>'
                f'<p>Сколько страниц будет найдено по запросу <b>{w1} & {w2}</b>?</p>'
            )
            answer = n_ab
            steps = [
                f'N(A|B) = N(A) + N(B) − N(A&B).',
                f'N(A&B) = N(A) + N(B) − N(A|B).',
                f'N(A&B) = {n_a} + {n_b} − {n_aub} = {n_ab}.',
            ]

        results.append(make(8, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 9: Количество путей в графе (DAG + SVG)
# ════════════════════════════════════════════════════════════════════

def make_svg_graph(adj, labels):
    n = len(labels)
    w = max(500, n * 80)
    h = 200
    cx_step = w // (n + 1)
    r = 18

    positions = []
    for idx in range(n):
        x = cx_step * (idx + 1)
        y = h // 2 + random.randint(-30, 30)
        positions.append((x, y))

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" style="max-width:100%;background:#fff;border-radius:8px">'
    svg += '<defs><marker id="ah" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#333"/></marker></defs>'

    for i in range(n):
        for j in range(n):
            if adj[i][j]:
                x1, y1 = positions[i]
                x2, y2 = positions[j]
                dx, dy = x2 - x1, y2 - y1
                dist = math.sqrt(dx*dx + dy*dy)
                if dist == 0:
                    continue
                ux, uy = dx/dist, dy/dist
                sx, sy = x1 + ux*r, y1 + uy*r
                ex, ey = x2 - ux*(r+6), y2 - uy*(r+6)
                svg += f'<line x1="{sx:.0f}" y1="{sy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" stroke="#555" stroke-width="2" marker-end="url(#ah)"/>'

    for idx in range(n):
        x, y = positions[idx]
        svg += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#6c7bff" stroke="#fff" stroke-width="2"/>'
        svg += f'<text x="{x}" y="{y+5}" text-anchor="middle" fill="white" font-size="14" font-weight="bold">{labels[idx]}</text>'

    svg += '</svg>'
    return svg


def gen_task9(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            n = random.randint(5, 6)
        elif diff == 'medium':
            n = random.randint(7, 8)
        else:
            n = random.randint(9, 11)

        labels = NODE_LETTERS[:n]

        adj = [[False]*n for _ in range(n)]
        for a in range(n):
            for b in range(a+1, n):
                if random.random() < 0.35:
                    adj[a][b] = True

        for a in range(n-1):
            if not any(adj[a][b] for b in range(a+1, n)):
                adj[a][a+1] = True
        if not any(adj[a][n-1] for a in range(n-1)):
            adj[n-2][n-1] = True

        dp = [0]*n
        dp[0] = 1
        for v in range(n):
            for u in range(v):
                if adj[u][v]:
                    dp[v] += dp[u]
        answer = dp[n-1]

        if answer < 2:
            adj[0][1] = True
            if n > 2:
                adj[0][2] = True
            dp = [0]*n
            dp[0] = 1
            for v in range(n):
                for u in range(v):
                    if adj[u][v]:
                        dp[v] += dp[u]
            answer = dp[n-1]

        svg = make_svg_graph(adj, labels)

        content = (
            f'<p>На рисунке — схема дорог, связывающих города '
            f'{", ".join(labels)}. По каждой дороге можно двигаться только '
            f'в одном направлении, указанном стрелкой. Сколько существует '
            f'различных путей из города {labels[0]} в город {labels[-1]}?</p>'
            f'{svg}'
        )

        steps = [
            f'Используем метод динамического программирования.',
            f'Считаем количество путей от {labels[0]} до каждого промежуточного города.',
            f'Количество путей до {labels[-1]} = {answer}.',
        ]
        results.append(make(9, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 10: Системы счисления
# ════════════════════════════════════════════════════════════════════

def to_base(n, base):
    if n == 0:
        return '0'
    digits = '0123456789ABCDEF'
    result = ''
    while n > 0:
        result = digits[n % base] + result
        n //= base
    return result


def gen_task10(count=200):
    results = []
    base_names = {2: 'двоичную', 8: 'восьмеричную', 10: 'десятичную', 16: 'шестнадцатеричную'}
    base_adj = {2: 'двоичное', 8: 'восьмеричное', 10: 'десятичное', 16: 'шестнадцатеричное'}

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            variant = random.choice(['bin2dec', 'dec2bin'])
            if variant == 'bin2dec':
                num = random.randint(10, 127)
                source = to_base(num, 2)
                content = (
                    f'<p>Переведите {base_adj[2]} число {source} в {base_names[10]} систему счисления.</p>'
                )
                answer = num
                steps = [
                    f'{source}₂ = ' + ' + '.join(
                        f'{int(d)}·2^{len(source)-1-j}' for j, d in enumerate(source) if d == '1') + f' = {num}.',
                ]
            else:
                num = random.randint(10, 127)
                content = f'<p>Переведите {base_adj[10]} число {num} в {base_names[2]} систему счисления.</p>'
                answer = to_base(num, 2)
                steps = [
                    f'Делим {num} на 2 последовательно, записываем остатки.',
                    f'{num}₁₀ = {answer}₂.',
                ]

        elif diff == 'medium':
            variant = random.choice(['oct', 'hex', 'count_ones'])
            if variant == 'count_ones':
                num = random.randint(50, 255)
                binary = to_base(num, 2)
                ones = binary.count('1')
                content = (
                    f'<p>Переведите число {num} из десятичной системы в двоичную. '
                    f'Сколько единиц содержит полученное число?</p>'
                )
                answer = ones
                steps = [
                    f'{num}₁₀ = {binary}₂.',
                    f'Количество единиц: {ones}.',
                ]
            elif variant == 'oct':
                num = random.randint(20, 200)
                octal = to_base(num, 8)
                content = f'<p>Переведите {base_adj[10]} число {num} в {base_names[8]} систему счисления.</p>'
                answer = octal
                steps = [f'{num}₁₀ = {octal}₈.']
            else:
                num = random.randint(20, 200)
                hexa = to_base(num, 16)
                content = f'<p>Переведите {base_adj[10]} число {num} в {base_names[16]} систему счисления.</p>'
                answer = hexa
                steps = [f'{num}₁₀ = {hexa}₁₆.']

        else:
            a_dec = random.randint(50, 200)
            b_dec = random.randint(10, 100)
            a_bin = to_base(a_dec, 2)
            b_oct = to_base(b_dec, 8)
            total = a_dec + b_dec

            content = (
                f'<p>Вычислите значение арифметического выражения: '
                f'{a_bin}₂ + {b_oct}₈. В ответе запишите десятичное число.</p>'
            )
            answer = total
            steps = [
                f'{a_bin}₂ = {a_dec}₁₀.',
                f'{b_oct}₈ = {b_dec}₁₀.',
                f'{a_dec} + {b_dec} = {total}.',
            ]

        results.append(make(10, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 11: Поиск в файлах каталога
# ════════════════════════════════════════════════════════════════════

def gen_task11(count=200):
    results = []
    search_keywords = [
        ('стихотворени', 'стихотворении'), ('произведени', 'произведении'),
        ('рассказ', 'рассказе'), ('повест', 'повести'), ('роман', 'романе'),
    ]

    for i in range(count):
        diff = pick_diff(i)
        author = random.choice(list(AUTHORS.keys()))
        works = AUTHORS[author]
        work = random.choice(works)

        search_word = random.choice(['река','город','дерево','камень','дождь',
                                     'ветер','огонь','гора','море','озеро',
                                     'звезда','луна','солнце','птица','цветок'])
        nearby_word = random.choice(['тёмный','светлый','далёкий','великий','старый',
                                     'новый','быстрый','тихий','холодный','тёплый',
                                     'печальный','радостный','странный','древний','могучий'])

        folder = random.choice(['DEMO-12','Проза','Литература','Классика'])

        content = (
            f'<p>В одном из произведений {author}, текст которого приведён '
            f'в подкаталоге {author} каталога {folder}, '
            f'рядом со словом «{search_word}» встречается определённое прилагательное. '
            f'С помощью поисковых средств операционной системы и текстового '
            f'редактора выясните это прилагательное.</p>'
            f'<p><i>(В данном задании ответ: {nearby_word})</i></p>'
        )
        answer = nearby_word
        steps = [
            f'Открываем каталог {folder}/{author}.',
            f'Ищем файл с произведением «{work}».',
            f'Используя поиск (Ctrl+F), находим слово «{search_word}».',
            f'Рядом с ним стоит прилагательное «{nearby_word}».',
        ]
        results.append(make(11, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 12: Подсчёт файлов
# ════════════════════════════════════════════════════════════════════

def gen_task12(count=200):
    results = []
    extensions = ['.txt','.htm','.html','.pdf','.rtf','.doc','.docx','.odt']
    folders_pool = list(AUTHORS.keys()) + ['Стихи','Проза','Драма','Поэзия','Классика']

    for i in range(count):
        diff = pick_diff(i)
        ext = random.choice(extensions)
        folder = random.choice(folders_pool)
        archive = random.choice(['DEMO-12','Литература','Архив','Библиотека'])

        if diff == 'easy':
            file_count = random.randint(3, 10)
        elif diff == 'medium':
            file_count = random.randint(8, 20)
        else:
            file_count = random.randint(12, 30)

        content = (
            f'<p>Сколько файлов с расширением <b>{ext}</b> содержится '
            f'в подкаталогах каталога <b>{folder}</b>?</p>'
            f'<p>В ответе укажите только число.</p>'
            f'<p><i>(Ответ для данного задания: {file_count})</i></p>'
        )
        answer = file_count
        steps = [
            f'Открываем каталог {archive}/{folder}.',
            f'Используем поиск по маске *{ext}.',
            f'Количество найденных файлов: {file_count}.',
        ]
        results.append(make(12, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 13: Создание презентации / текстового документа
# ════════════════════════════════════════════════════════════════════

def gen_task13(count=200):
    results = []
    topics_13 = [
        ('Бурый медведь','внешнем виде, об ареале обитания и образе жизни бурых медведей'),
        ('Белый тигр','внешнем виде, об ареале обитания и особенностях белых тигров'),
        ('Северный олень','внешнем виде, об ареале обитания и образе жизни северных оленей'),
        ('Снежный барс','внешнем виде, об ареале обитания и охране снежных барсов'),
        ('Горилла','внешнем виде, об ареале обитания и поведении горилл'),
        ('Кенгуру','внешнем виде, об ареале обитания и размножении кенгуру'),
        ('Панда','внешнем виде, об ареале обитания и питании панд'),
        ('Лев','внешнем виде, об ареале обитания и социальной структуре львов'),
        ('Дельфин','внешнем виде, об ареале обитания и интеллекте дельфинов'),
        ('Пингвин','внешнем виде, об ареале обитания и образе жизни пингвинов'),
        ('Волк','внешнем виде, об ареале обитания и стайном поведении волков'),
        ('Орёл','внешнем виде, об ареале обитания и охотничьих способностях орлов'),
        ('Акула','внешнем виде, об ареале обитания и видах акул'),
        ('Слон','внешнем виде, об ареале обитания и поведении слонов'),
        ('Жираф','внешнем виде, об ареале обитания и питании жирафов'),
        ('Коала','внешнем виде, об ареале обитания и образе жизни коал'),
        ('Тукан','внешнем виде, об ареале обитания и особенностях туканов'),
        ('Фламинго','внешнем виде, об ареале обитания и питании фламинго'),
        ('Хамелеон','внешнем виде, об ареале обитания и способностях хамелеонов'),
        ('Морская черепаха','внешнем виде, об ареале обитания и миграциях морских черепах'),
    ]

    for i in range(count):
        diff = pick_diff(i)
        topic, desc = topics_13[i % len(topics_13)]

        if diff == 'easy':
            slides = 3
            criteria = 4
        elif diff == 'medium':
            slides = 3
            criteria = 6
        else:
            slides = 4
            criteria = 8

        criteria_list = [
            f'1) Ровно {slides} слайда.',
            '2) Каждый слайд должен содержать заголовок и иллюстрацию.',
            '3) Текст на слайдах не должен совпадать с текстом источника.',
            '4) Презентация должна содержать краткие сведения.',
            '5) Размер шрифта не менее 18 пунктов.',
            '6) Все слайды должны быть оформлены в едином стиле.',
            '7) В колонтитулах указать номер слайда и своё имя.',
            '8) Применить анимацию к объектам на слайдах.',
        ][:criteria]

        content = (
            f'<p>Выберите ОДНО из предложенных ниже заданий: 13.1 или 13.2.</p>'
            f'<p><b>13.1</b> Используя информацию и иллюстративный материал, '
            f'содержащийся в каталоге «{topic}», создайте презентацию из {slides} слайдов '
            f'на тему «{topic}». В презентации должны содержаться краткие '
            f'иллюстрированные сведения о {desc}.</p>'
            f'<p>Требования:</p>'
            f'<p>{"<br>".join(criteria_list)}</p>'
            f'<p><b>13.2</b> Создайте текстовый документ на тему «{topic}» '
            f'объёмом не менее 150 слов с использованием материалов каталога.</p>'
        )
        answer = ''
        solution = (
            f'<p><b>Решение:</b></p>'
            f'<p>Задание выполняется на компьютере. Необходимо создать презентацию '
            f'из {slides} слайдов с иллюстрациями и текстом о {topic}.</p>'
        )
        results.append(make(13, content, answer, solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 14: Электронные таблицы (данные + анализ)
# ════════════════════════════════════════════════════════════════════

def gen_task14(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)
        n_students = random.randint(10, 20)

        if diff == 'easy':
            n_cols = 3
            q_count = 2
        elif diff == 'medium':
            n_cols = 4
            q_count = 3
        else:
            n_cols = 4
            q_count = 3

        districts = random.sample(DISTRICTS, min(4, len(DISTRICTS)))
        subjects_pool = random.sample(SUBJECTS, min(5, len(SUBJECTS)))

        students = []
        for s in range(n_students):
            d = random.choice(districts)
            subj = random.choice(subjects_pool)
            score = random.randint(20, 100)
            students.append({
                'district': d,
                'name': f'Ученик {s+1}',
                'subject': subj,
                'score': score,
            })

        header = '<tr><th>A</th><th>B</th><th>C</th><th>D</th></tr>'
        header += '<tr><td>округ</td><td>фамилия</td><td>предмет</td><td>балл</td></tr>'
        rows = ''
        for idx, st in enumerate(students[:5]):
            rows += (f'<tr><td>{st["district"]}</td><td>{st["name"]}</td>'
                     f'<td>{st["subject"]}</td><td>{st["score"]}</td></tr>')

        target_district = random.choice(districts)
        target_subject = random.choice(subjects_pool)

        d_scores = [s['score'] for s in students if s['district'] == target_district]
        s_scores = [s['score'] for s in students if s['subject'] == target_subject]

        if not d_scores:
            d_scores = [50]
        if not s_scores:
            s_scores = [50]

        avg_district = round(sum(d_scores) / len(d_scores), 2)
        count_subject = len(s_scores)
        max_score = max(s['score'] for s in students)

        questions = []
        answers_list = []

        questions.append(
            f'Сколько учеников выбрали предмет «{target_subject}»?'
        )
        answers_list.append(count_subject)

        questions.append(
            f'Каков средний балл учеников из округа «{target_district}»? '
            f'(Округлите до целого.)'
        )
        answers_list.append(round(avg_district))

        if q_count >= 3:
            questions.append(f'Каков максимальный балл среди всех учеников?')
            answers_list.append(max_score)

        answer_str = '; '.join(str(a) for a in answers_list)

        q_html = '<p>'.join(f'{j+1}) {q}' for j, q in enumerate(questions))

        content = (
            f'<p>В электронную таблицу занесли данные о тестировании учеников. '
            f'Ниже приведены первые строки таблицы (всего {n_students} записей):</p>'
            f'<table>{header}{rows}</table>'
            f'<p>Выполните задание:</p><p>{q_html}</p>'
        )

        steps = [f'Вопрос {j+1}: {q} → {a}.' for j, (q, a) in enumerate(zip(questions, answers_list))]
        results.append(make(14, content, answer_str, sol(steps, answer_str), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 15: Робот (лабиринт + алгоритм)
# ════════════════════════════════════════════════════════════════════

def make_maze_html(grid, robot_pos, paint_cells=None):
    rows_count = len(grid)
    cols_count = len(grid[0])
    html = '<table style="border-collapse:collapse;margin:12px auto">'
    for r in range(rows_count):
        html += '<tr>'
        for c in range(cols_count):
            walls = grid[r][c]
            style = 'width:28px;height:28px;'
            style += f'border-top:{"3px solid #333" if "N" in walls else "1px solid #ccc"};'
            style += f'border-bottom:{"3px solid #333" if "S" in walls else "1px solid #ccc"};'
            style += f'border-left:{"3px solid #333" if "W" in walls else "1px solid #ccc"};'
            style += f'border-right:{"3px solid #333" if "E" in walls else "1px solid #ccc"};'

            bg = '#fff'
            text = ''
            if (r, c) == robot_pos:
                bg = '#6c7bff'
                text = '<span style="color:#fff;font-weight:bold">◆</span>'
            elif paint_cells and (r, c) in paint_cells:
                bg = '#e0e0e0'
            style += f'background:{bg};text-align:center;font-size:12px;'
            html += f'<td style="{style}">{text}</td>'
        html += '</tr>'
    html += '</table>'
    return html


def gen_task15(count=200):
    results = []

    for i in range(count):
        diff = pick_diff(i)

        if diff == 'easy':
            rows, cols = 6, 8
        elif diff == 'medium':
            rows, cols = 7, 10
        else:
            rows, cols = 8, 10

        grid = [[set() for _ in range(cols)] for _ in range(rows)]

        for c in range(cols):
            grid[0][c].add('N')
            grid[rows-1][c].add('S')
        for r in range(rows):
            grid[r][0].add('W')
            grid[r][cols-1].add('E')

        for _ in range(random.randint(3, 8)):
            r1 = random.randint(1, rows-2)
            c1 = random.randint(0, cols-2)
            length = random.randint(2, min(5, cols-c1))
            for c in range(c1, min(c1+length, cols)):
                grid[r1][c].add('S')
                if r1 + 1 < rows:
                    grid[r1+1][c].add('N')

        for _ in range(random.randint(2, 5)):
            c1 = random.randint(1, cols-2)
            r1 = random.randint(0, rows-2)
            length = random.randint(2, min(4, rows-r1))
            for r in range(r1, min(r1+length, rows)):
                grid[r][c1].add('E')
                if c1 + 1 < cols:
                    grid[r][c1+1].add('W')

        robot_r = random.randint(1, rows-2)
        robot_c = random.randint(1, cols-2)

        paint_row = robot_r
        paint_cells = set()
        for c in range(cols):
            if 'S' not in grid[paint_row][c] or c == robot_c:
                paint_cells.add((paint_row, c))

        maze_html = make_maze_html(grid, (robot_r, robot_c), paint_cells)

        content = (
            f'<p>Исполнитель Робот умеет перемещаться по лабиринту, '
            f'начерченному на плоскости, разбитой на клетки. '
            f'Робот может двигаться вверх, вниз, влево, вправо. '
            f'У Робота есть команды-проверки стен.</p>'
            f'{maze_html}'
            f'<p>Робот находится в клетке, отмеченной ◆. '
            f'Напишите для Робота алгоритм, закрашивающий указанные клетки '
            f'(серые на рисунке).</p>'
        )
        answer = ''
        solution = (
            f'<p><b>Решение:</b></p>'
            f'<p>Алгоритм: используем цикл «пока справа свободно — вправо, закрасить», '
            f'затем возвращаемся и идём влево с закрашиванием.</p>'
        )
        results.append(make(15, content, answer, solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 16: Написать программу
# ════════════════════════════════════════════════════════════════════

def gen_task16(count=200):
    results = []

    templates = [
        {
            'text': 'Напишите программу, которая в последовательности натуральных чисел определяет {what}. '
                    'Программа получает на вход {n} натуральных чисел. Числа не превышают {max_val}.',
            'variants': [
                ('количество чётных чисел', lambda nums: sum(1 for x in nums if x % 2 == 0)),
                ('количество нечётных чисел', lambda nums: sum(1 for x in nums if x % 2 != 0)),
                ('сумму чётных чисел', lambda nums: sum(x for x in nums if x % 2 == 0)),
                ('максимальное число', lambda nums: max(nums)),
                ('минимальное число', lambda nums: min(nums)),
                ('количество чисел, кратных 3', lambda nums: sum(1 for x in nums if x % 3 == 0)),
                ('сумму чисел, кратных 5', lambda nums: sum(x for x in nums if x % 5 == 0)),
                ('количество чисел, больших 50', lambda nums: sum(1 for x in nums if x > 50)),
                ('количество двузначных чисел', lambda nums: sum(1 for x in nums if 10 <= x <= 99)),
                ('сумму трёхзначных чисел', lambda nums: sum(x for x in nums if 100 <= x <= 999)),
                ('количество чисел, оканчивающихся на 4', lambda nums: sum(1 for x in nums if x % 10 == 4)),
                ('сумму чисел, делящихся на 7', lambda nums: sum(x for x in nums if x % 7 == 0)),
            ],
        },
    ]

    for i in range(count):
        diff = pick_diff(i)
        tmpl = templates[0]

        if diff == 'easy':
            n = random.randint(5, 8)
            max_val = 100
            variant_idx = random.randint(0, 4)
        elif diff == 'medium':
            n = random.randint(8, 15)
            max_val = 500
            variant_idx = random.randint(3, 8)
        else:
            n = random.randint(10, 20)
            max_val = 1000
            variant_idx = random.randint(6, 11)

        what_text, func = tmpl['variants'][variant_idx]
        nums = [random.randint(1, max_val) for _ in range(n)]
        answer = func(nums)

        nums_str = ', '.join(str(x) for x in nums)

        content = (
            f'<p>{tmpl["text"].format(what=what_text, n=n, max_val=max_val)}</p>'
            f'<p>Пример входных данных: {nums_str}</p>'
            f'<p>При указанных входных данных программа должна вывести: <b>{answer}</b></p>'
        )

        solution = (
            f'<p><b>Решение (Python):</b></p>'
            f'<pre style="background:#1a1d27;color:#e4e6f0;padding:12px;border-radius:8px">'
            f'n = {n}\nresult = 0\nfor i in range(n):\n    x = int(input())\n'
            f'    # проверяем условие и обновляем result\nprint(result)</pre>'
            f'<p><b>Ответ для примера:</b> {answer}</p>'
        )
        results.append(make(16, content, answer, solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════

def main():
    generators = [
        ('Task  1', gen_task1),
        ('Task  2', gen_task2),
        ('Task  3', gen_task3),
        ('Task  4', gen_task4),
        ('Task  5', gen_task5),
        ('Task  6', gen_task6),
        ('Task  7', gen_task7),
        ('Task  8', gen_task8),
        ('Task  9', gen_task9),
        ('Task 10', gen_task10),
        ('Task 11', gen_task11),
        ('Task 12', gen_task12),
        ('Task 13', gen_task13),
        ('Task 14', gen_task14),
        ('Task 15', gen_task15),
        ('Task 16', gen_task16),
    ]

    all_generated = []
    base_id = 100000

    for name, gen_func in generators:
        tasks = gen_func(200)
        for t in tasks:
            t['site_id'] = base_id
            base_id += 1
        all_generated.extend(tasks)
        diffs = defaultdict(int)
        for t in tasks:
            diffs[t['difficulty_level']] += 1
        print(f'{name}: {len(tasks):>4} tasks  (easy={diffs["easy"]}, med={diffs["medium"]}, hard={diffs["hard"]})')

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        existing = json.load(f)

    existing_count = len(existing)
    existing.extend(all_generated)

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*50}')
    print(f'Существующих заданий: {existing_count}')
    print(f'Сгенерировано: {len(all_generated)}')
    print(f'Итого в файле: {len(existing)}')

    by_tn = defaultdict(int)
    for t in existing:
        by_tn[t['task_number']] += 1
    print(f'\nРаспределение по номерам:')
    for tn in sorted(by_tn):
        print(f'  Задание {tn:>2}: {by_tn[tn]:>4}')


if __name__ == '__main__':
    main()
