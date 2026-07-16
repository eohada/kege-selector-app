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

def get_xp_for_level(lvl):
    """Возвращает кумулятивный XP, необходимый для достижения уровня lvl."""
    if lvl <= 1:
        return 0
    # Прогрессия: Level 2 = 100 XP, Level 3 = 282 XP (~280), Level 4 = 519 XP (~520), Level 5 = 800 XP...
    return int(100 * (lvl - 1) * ((lvl - 1) ** 0.5))

def calculate_level_from_xp(xp):
    """Вычисляет уровень на основе накопленного XP."""
    if xp <= 0:
        return 1
    lvl = 1
    # Итерируемся до максимального подходящего уровня
    while get_xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return lvl

def get_rank_title(level, subject='Информатика'):
    """Возвращает текстовое звание для уровня и предмета."""
    if subject == 'Информатика':
        if level in INFORMATICS_RANKS:
            return INFORMATICS_RANKS[level]
        return f"Божество алгоритмов (ур. {level})"
    return f"Ученик уровня {level}"

def add_xp_to_student(student, amount):
    """Добавляет XP ученику, пересчитывает уровень и сохраняет в базу."""
    if not student or amount <= 0:
        return False
    
    try:
        student.xp = (student.xp or 0) + amount
        new_level = calculate_level_from_xp(student.xp)
        leveled_up = new_level > (student.level or 1)
        student.level = new_level
        db.session.commit()
        return leveled_up
    except Exception as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error adding XP to student {student.student_id}: {e}", exc_info=True)
        return False
