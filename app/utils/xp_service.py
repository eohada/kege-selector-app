import math
from app.models import db, Student

# Карта званий по информатике (на каждый уровень до 50)
INFORMATICS_RANKS = {
    1: "Новичок в Python / print('Hello')",
    2: "Инициализатор переменных / x = 5",
    3: "Разветвитель условий / if-else",
    4: "Повелитель циклов / while True",
    5: "Перебиратель range()",
    6: "Создатель списков / list()",
    7: "Индексатор строк / s[0]",
    8: "Срезчик массивов / s[::-1]",
    9: "Генератор списков / list comprehension",
    10: "Определитель функций / def f()",
    11: "Искатель минимумов / min()",
    12: "Сортировщик / sorted()",
    13: "Анализатор строк / string.count()",
    14: "Читатель файлов / open('17.txt')",
    15: "Обработчик чисел / int(x, 16)",
    16: "Мастер систем счисления",
    17: "Взломщик 14 задания",
    18: "Комбинатор / itertools",
    19: "Генератор перестановок / permutations",
    20: "Математик делителей / №25",
    21: "Древовед игр / №19",
    22: "Игрок выигрышных стратегий / №20",
    23: "Анализатор выигрышей / №21",
    24: "Разработчик рекурсии",
    25: "Кэшер функций / @lru_cache",
    26: "Динамический оптимизатор",
    27: "Взломщик №19-21 кодом",
    28: "Оптимизатор масок / fnmatch",
    29: "Проектировщик №26",
    30: "Алгоритмист двух указателей",
    31: "Пожиратель терабайтов",
    32: "Мастер сортировок с условием",
    33: "Парсер больших файлов / №27",
    34: "Архитектор префиксных сумм",
    35: "Сложный префикс-анализатор",
    36: "Оптимизатор сложности O(N)",
    37: "Мастер динамики №27",
    38: "Магистр кластеризации / №27Б",
    39: "Спец по центроидам кластеров",
    40: "Дата Саентист КЕГЭ",
    41: "Оптимизатор памяти",
    42: "Гуру многопроцессорности",
    43: "Истребитель багов №27Б",
    44: "Архитектор чистых решений",
    45: "Мастер стресс-тестирования",
    46: "Аналитик крайних случаев",
    47: "Алгоритмический Сенсей",
    48: "Программист 100 баллов",
    49: "Легенда КЕГЭ по информатике",
    50: "Создатель ИИ / Bug Exterminator"
}

# Детализированная карта 50 уровней BooStudy (Основы Python -> Все номера КЕГЭ -> 100 баллов)
BOOSTUDY_50_LEVELS = [
    # Блок 1: Основы Python (Уровни 1 – 15)
    {
        'level': 1,
        'title': 'Новичок в Python',
        'desc': 'Первые шаги: вывод данных print(), базовые типы данных и запуск первой программы.',
        'stage': 'Основы Python',
        'icon': 'ph-terminal-window',
        'color': 'emerald'
    },
    {
        'level': 2,
        'title': 'Инициализатор переменных',
        'desc': 'Присваивание значений, целочисленная арифметика и пользовательский ввод input().',
        'stage': 'Основы Python',
        'icon': 'ph-brackets-curly',
        'color': 'emerald'
    },
    {
        'level': 3,
        'title': 'Разветвитель условий',
        'desc': 'Логические операторы and, or, not и условные ветвления if-elif-else.',
        'stage': 'Основы Python',
        'icon': 'ph-git-fork',
        'color': 'emerald'
    },
    {
        'level': 4,
        'title': 'Повелитель циклов',
        'desc': 'Цикл while, бесконечные циклы, флаги, операторы break и continue.',
        'stage': 'Основы Python',
        'icon': 'ph-arrows-clockwise',
        'color': 'emerald'
    },
    {
        'level': 5,
        'title': 'Мастер range()',
        'desc': 'Цикл for, диапазоны чисел, шаги и арифметические последовательности.',
        'stage': 'Основы Python',
        'icon': 'ph-repeat',
        'color': 'sky'
    },
    {
        'level': 6,
        'title': 'Создатель списков',
        'desc': 'Структуры данных: создание списков, добавление append() и вычисление длины len().',
        'stage': 'Основы Python',
        'icon': 'ph-list-dashes',
        'color': 'sky'
    },
    {
        'level': 7,
        'title': 'Индексатор строк',
        'desc': 'Строки в Python: индексы символов, конкатенация и функции ord() / chr().',
        'stage': 'Основы Python',
        'icon': 'ph-text-align-left',
        'color': 'sky'
    },
    {
        'level': 8,
        'title': 'Срезчик массивов',
        'desc': 'Мастерское владение срезами s[start:stop:step] и разворотом s[::-1].',
        'stage': 'Основы Python',
        'icon': 'ph-scissors',
        'color': 'sky'
    },
    {
        'level': 9,
        'title': 'Генератор списков',
        'desc': 'List comprehension: генерация и фильтрация списков в одну чистую строчку.',
        'stage': 'Основы Python',
        'icon': 'ph-sparkle',
        'color': 'sky'
    },
    {
        'level': 10,
        'title': 'Определитель функций',
        'desc': 'Создание собственных функций def, передача аргументов и оператор return.',
        'stage': 'Основы Python',
        'icon': 'ph-function',
        'color': 'indigo'
    },
    {
        'level': 11,
        'title': 'Искатель экстремумов',
        'desc': 'Алгоритмы поиска минимумов min(), максимумов max() и подсчета сумм sum().',
        'stage': 'Основы Python',
        'icon': 'ph-chart-line-up',
        'color': 'indigo'
    },
    {
        'level': 12,
        'title': 'Сортировщик коллекций',
        'desc': 'Сортировка списков sort() и sorted(), аргументы reverse и лямбда-ключи key=lambda.',
        'stage': 'Основы Python',
        'icon': 'ph-sort-ascending',
        'color': 'indigo'
    },
    {
        'level': 13,
        'title': 'Анализатор строк',
        'desc': 'Продвинутые методы строк: count(), find(), replace() и разделение split().',
        'stage': 'Основы Python',
        'icon': 'ph-magnifying-glass',
        'color': 'indigo'
    },
    {
        'level': 14,
        'title': 'Читатель файлов',
        'desc': 'Построчное чтение файлов open(), метод readlines() и парсинг входных данных.',
        'stage': 'Основы Python',
        'icon': 'ph-file-text',
        'color': 'indigo'
    },
    {
        'level': 15,
        'title': 'Обработчик систем счисления',
        'desc': 'Перевод чисел между системами счисления: bin(), oct(), hex() и int(x, base).',
        'stage': 'Основы Python',
        'icon': 'ph-binary',
        'color': 'indigo'
    },

    # Блок 2: Базовые и средние задачи КЕГЭ (Уровни 16 – 30)
    {
        'level': 16,
        'title': 'Мастер систем счисления (№14)',
        'desc': 'Решение сложных математических выражений в позиционных системах счисления КЕГЭ.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-calculator',
        'color': 'purple'
    },
    {
        'level': 17,
        'title': 'Взломщик уравнений счисления',
        'desc': 'Анализ остатков, перебор неизвестных цифр x и y, алгебраические преобразования.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-key',
        'color': 'purple'
    },
    {
        'level': 18,
        'title': 'Комбинатор itertools (№8)',
        'desc': 'Генерация слов, чисел и перестановок через itertools.product и permutations.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-shapes',
        'color': 'purple'
    },
    {
        'level': 19,
        'title': 'Мастер комбинаторных условий',
        'desc': 'Учет ограничений на повторения, гласные/согласные буквы и позиции символов.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-shuffle',
        'color': 'purple'
    },
    {
        'level': 20,
        'title': 'Математик делителей (№25)',
        'desc': 'Оптимальный поиск делителей числа до корня sqrt(N) и быстрая проверка на простоту.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-divide',
        'color': 'purple'
    },
    {
        'level': 21,
        'title': 'Древовед теории игр (№19)',
        'desc': 'Построение дерева игровых позиций и нахождение первого победного хода.',
        'stage': 'Теория игр',
        'icon': 'ph-tree-structure',
        'color': 'amber'
    },
    {
        'level': 22,
        'title': 'Стратег победы за 2 хода (№20)',
        'desc': 'Анализ партий на две кучи камней и нахождение гарантированной победы игрока (В1).',
        'stage': 'Теория игр',
        'icon': 'ph-game-controller',
        'color': 'amber'
    },
    {
        'level': 23,
        'title': 'Анализатор исходов партий (№21)',
        'desc': 'Определение стратегий победы второго игрока при любой игре соперника (В2).',
        'stage': 'Теория игр',
        'icon': 'ph-trophy',
        'color': 'amber'
    },
    {
        'level': 24,
        'title': 'Разработчик рекурсии (№16)',
        'desc': 'Программирование рекурсивных соотношений и обход ограничений глубины стека.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-infinity',
        'color': 'amber'
    },
    {
        'level': 25,
        'title': 'Кэшер функций @lru_cache',
        'desc': 'Мемоизация рекурсивных вызовов декоратором functools.lru_cache для мгновенного ответа.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-cpu',
        'color': 'amber'
    },
    {
        'level': 26,
        'title': 'Динамический оптимизатор (№23)',
        'desc': 'Подсчет программ исполнителя методом динамического программирования по траектории.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-arrows-split',
        'color': 'amber'
    },
    {
        'level': 27,
        'title': 'Универсальный решатель игр',
        'desc': 'Написание универсальной рекурсивной функции для автоматического закрытия номеров 19–21.',
        'stage': 'Теория игр',
        'icon': 'ph-sword',
        'color': 'rose'
    },
    {
        'level': 28,
        'title': 'Оптимизатор масок (№25)',
        'desc': 'Фильтрация чисел по шаблонам и маскам через модуль fnmatch и генерацию цифр.',
        'stage': 'Базовый КЕГЭ',
        'icon': 'ph-asterisk',
        'color': 'rose'
    },
    {
        'level': 29,
        'title': 'Проектировщик жадных задач (№26)',
        'desc': 'Жадные алгоритмы КЕГЭ: упаковка данных на диск, распределение ячеек и интервалы.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-stack',
        'color': 'rose'
    },
    {
        'level': 30,
        'title': 'Алгоритмист двух указателей',
        'desc': 'Техника двух указателей и бинарного поиска для ускорения обработки массивов.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-arrows-left-right',
        'color': 'rose'
    },

    # Блок 3: Сложные задачи КЕГЭ и алгоритмы (Уровни 31 – 45)
    {
        'level': 31,
        'title': 'Укротитель строк (№24)',
        'desc': 'Линейный проход строк длиной миллион символов и поиск непрерывных цепочек.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-text-t',
        'color': 'sky'
    },
    {
        'level': 32,
        'title': 'Мастер динамических срезов',
        'desc': 'Сложные условия на гласные/согласные, регулярные выражения и метод скользящего окна.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-code-simple',
        'color': 'sky'
    },
    {
        'level': 33,
        'title': 'Парсер больших файлов (№27)',
        'desc': 'Потоковая обработка гигантских файлов КЕГЭ без переполнения оперативной памяти.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-database',
        'color': 'sky'
    },
    {
        'level': 34,
        'title': 'Архитектор префиксных сумм',
        'desc': 'Быстрое нахождение сумм на любых подотрезках массива за O(1) с помощью префиксов.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-sigma',
        'color': 'sky'
    },
    {
        'level': 35,
        'title': 'Анализатор делимости сумм',
        'desc': 'Алгоритмы на остатки от деления сумм подпоследовательностей на число K.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-math-operations',
        'color': 'sky'
    },
    {
        'level': 36,
        'title': 'Оптимизатор сложности O(N)',
        'desc': 'Превращение неэффективных квадратичных алгоритмов O(N²) в линейные O(N) для файла B.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-gauge',
        'color': 'teal'
    },
    {
        'level': 37,
        'title': 'Мастер динамики №27',
        'desc': 'Поддержание массива лучших состояний и экстремумов за один проход по файлу.',
        'stage': 'Сложный КЕГЭ',
        'icon': 'ph-circuitry',
        'color': 'teal'
    },
    {
        'level': 38,
        'title': 'Магистр кластеризации (№27Б)',
        'desc': 'Геометрический анализ данных: разделение множества точек на кластеры.',
        'stage': 'Кластеризация',
        'icon': 'ph-circles-three',
        'color': 'teal'
    },
    {
        'level': 39,
        'title': 'Спец по центроидам кластеров',
        'desc': 'Нахождение центроидов кластеров и минимизация суммы расстояний до остальных точек.',
        'stage': 'Кластеризация',
        'icon': 'ph-crosshair',
        'color': 'teal'
    },
    {
        'level': 40,
        'title': 'Дата-аналитик КЕГЭ',
        'desc': 'Автоматизация алгоритмов кластеризации, отсечение шумов и изолированных выбросов.',
        'stage': 'Кластеризация',
        'icon': 'ph-chart-polar',
        'color': 'teal'
    },
    {
        'level': 41,
        'title': 'Оптимизатор памяти и ресурсов',
        'desc': 'Эффективное применение генераторов, итераторов и структур collections.',
        'stage': 'Экспертный уровень',
        'icon': 'ph-hard-drives',
        'color': 'orange'
    },
    {
        'level': 42,
        'title': 'Аналитик процессов (№22)',
        'desc': 'Моделирование зависимостей процессов и расчет критического пути исполнения.',
        'stage': 'Экспертный уровень',
        'icon': 'ph-flow-arrow',
        'color': 'orange'
    },
    {
        'level': 43,
        'title': 'Истребитель багов №27Б',
        'desc': 'Выявление краевых эффектов, погрешностей чисел с плавающей точкой и деления на ноль.',
        'stage': 'Экспертный уровень',
        'icon': 'ph-bug',
        'color': 'orange'
    },
    {
        'level': 44,
        'title': 'Архитектор чистых решений',
        'desc': 'Написание чистого, самодокументированного и безошибочного экзаменационного кода.',
        'stage': 'Экспертный уровень',
        'icon': 'ph-check-circle',
        'color': 'orange'
    },
    {
        'level': 45,
        'title': 'Мастер стресс-тестирования',
        'desc': 'Генерация случайных тестов (рандомайзер) для сверки быстрого и наивного решений.',
        'stage': 'Экспертный уровень',
        'icon': 'ph-test-tube',
        'color': 'orange'
    },

    # Блок 4: Высший пилотаж и 100 баллов (Уровни 46 – 50)
    {
        'level': 46,
        'title': 'Аналитик крайних случаев',
        'desc': 'Полная проверка граничных условий во всех 27 заданиях экзаменационного варианта.',
        'stage': 'Курс на 100',
        'icon': 'ph-shield-check',
        'color': 'indigo'
    },
    {
        'level': 47,
        'title': 'Алгоритмический Сенсей',
        'desc': 'Мгновенный выбор оптимального инструмента (код, Excel или аналитика) для любой задачи.',
        'stage': 'Курс на 100',
        'icon': 'ph-medal',
        'color': 'indigo'
    },
    {
        'level': 48,
        'title': 'Программист 100 баллов',
        'desc': 'Стабильное безошибочное решение авторских и усложненных вариантов КЕГЭ на 90+ баллов.',
        'stage': 'Курс на 100',
        'icon': 'ph-crown-simple',
        'color': 'amber'
    },
    {
        'level': 49,
        'title': 'Гроссмейстер КЕГЭ',
        'desc': 'Безупречное знание спецификации КЕГЭ по информатике и уверенное решение всех 27 номеров.',
        'stage': 'Курс на 100',
        'icon': 'ph-star-four',
        'color': 'amber'
    },
    {
        'level': 50,
        'title': 'Легенда BooStudy',
        'desc': 'Высшая ступень мастерства: готовность к эталонным 100 баллам на КЕГЭ по информатике.',
        'stage': 'Курс на 100',
        'icon': 'ph-crown',
        'color': 'amber'
    }
]

BOOSTUDY_50_LEVELS_MAP = {item['level']: item for item in BOOSTUDY_50_LEVELS}

def get_xp_for_level(lvl):
    """Возвращает кумулятивный XP, необходимый для достижения уровня lvl (1-50).
    Сбалансированная квадратичная шкала:
    Уровень 1: 0 XP
    Уровень 2: 200 XP
    Уровень 3: 520 XP
    Уровень 4: 960 XP
    Уровень 5: 1520 XP
    Уровень 6: 2200 XP
    Уровень 7 («Индексатор строк»): 3000 XP
    Уровень 10: 6120 XP
    Уровень 15 (Основы Python): 13720 XP
    Уровень 50 (Легенда КЕГЭ / 100 баллов): ~151000 XP
    """
    if lvl <= 1:
        return 0
    n = lvl - 1
    return int(60 * (n ** 2) + 140 * n)

def calculate_level_from_xp(xp):
    """Вычисляет уровень на основе накопленного XP (1-50)."""
    if not xp or xp <= 0:
        return 1
    lvl = 1
    while lvl < 50 and get_xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return min(50, lvl)

def get_level_info(level_num, xp_val=None):
    """Возвращает метаданные для конкретного уровня (1-50) и прогресс до следующего."""
    level_num = max(1, min(50, int(level_num or 1)))
    lvl_data = BOOSTUDY_50_LEVELS_MAP.get(level_num, BOOSTUDY_50_LEVELS[0])

    xp_base = get_xp_for_level(level_num)
    xp_target = get_xp_for_level(level_num + 1) if level_num < 50 else get_xp_for_level(50)

    current_xp = xp_val if (xp_val is not None and xp_val >= 0) else xp_base
    xp_in_level = max(0, current_xp - xp_base)
    xp_span = max(1, xp_target - xp_base)
    progress_pct = 100 if level_num >= 50 else min(100, max(0, round((xp_in_level / xp_span) * 100)))
    xp_to_next = 0 if level_num >= 50 else max(0, xp_target - current_xp)

    return {
        'number': level_num,
        'title': lvl_data['title'],
        'desc': lvl_data['desc'],
        'stage': lvl_data.get('stage', 'Курс подготовки'),
        'icon': lvl_data.get('icon', 'ph-crown'),
        'color': lvl_data.get('color', 'amber'),
        'current_xp': current_xp,
        'base_xp': xp_base,
        'target_xp': xp_target,
        'progress_pct': progress_pct,
        'xp_to_next': xp_to_next,
    }

def get_all_ranks_list(current_level_num):
    """Возвращает полный список всех 50 уровней со статусами 'unlocked', 'current', 'locked'."""
    current_level_num = max(1, min(50, int(current_level_num or 1)))
    result = []
    for item in BOOSTUDY_50_LEVELS:
        lvl = item['level']
        is_unlocked = current_level_num > lvl
        is_current = current_level_num == lvl
        status = 'current' if is_current else ('unlocked' if is_unlocked else 'locked')

        xp_req = get_xp_for_level(lvl)
        xp_max = (get_xp_for_level(lvl + 1) - 1) if lvl < 50 else None

        result.append({
            **item,
            'xp_required': xp_req,
            'xp_max': xp_max,
            'is_unlocked': is_unlocked,
            'is_current': is_current,
            'status': status
        })
    return result

def get_rank_title(level, subject='Информатика'):
    """Возвращает текстовое звание для уровня и предмета."""
    if subject == 'Информатика':
        if level in BOOSTUDY_50_LEVELS_MAP:
            return BOOSTUDY_50_LEVELS_MAP[level]['title']
        if level in INFORMATICS_RANKS:
            return INFORMATICS_RANKS[level]
        return f"Божество алгоритмов (ур. {level})"
    return f"Ученик уровня {level}"

def add_xp_to_student(student, amount, *, commit=True):
    """Добавляет XP ученику, пересчитывает уровень и сохраняет в базу."""
    if not student or amount <= 0:
        return False
    
    try:
        student.xp = (student.xp or 0) + amount
        new_level = calculate_level_from_xp(student.xp)
        leveled_up = new_level > (student.level or 1)
        student.level = new_level
        if commit:
            db.session.commit()
        return leveled_up
    except Exception as e:
        if commit:
            db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error adding XP to student {student.student_id}: {e}", exc_info=True)
        return False
