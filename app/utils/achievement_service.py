"""
BooStudy Achievements System V2.

Полный реестр из 52 интерактивных и накопительных достижений
с динамическим расчетом прогресса и 10 секретными пасхалками.
"""
from datetime import datetime, timezone, timedelta
import logging
from app.models import db, Student, UserAchievement, Answer, Submission
from app.utils.xp_service import add_xp_to_student

logger = logging.getLogger(__name__)

# Часовой пояс Москвы (UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# Канонический реестр достижений BooStudy (52 достижения, 10 секретных)
ACHIEVEMENTS_REGISTRY = {
    # ---------------------------------------------------------------------
    # 1. Инструменты & Рабочая среда (Workspace & IDE) — 10 интерактивных
    # ---------------------------------------------------------------------
    'ide_run_shortcut': {
        'title': 'Пальцы пианиста',
        'desc': 'Запустить Python-код комбинацией клавиш Ctrl + Enter',
        'icon': 'ph-keyboard',
        'icon_style': 'indigo',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'ide_copy_code': {
        'title': 'Буфер обмена',
        'desc': 'Скопировать решение через кнопку в панели IDE',
        'icon': 'ph-copy',
        'icon_style': 'blue',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'ide_download_py': {
        'title': 'Архиватор',
        'desc': 'Скачать решение в виде отдельного файла .py',
        'icon': 'ph-download-simple',
        'icon_style': 'blue',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'ide_fullscreen': {
        'title': 'Полное погружение',
        'desc': 'Развернуть IDE или рабочую область на весь экран',
        'icon': 'ph-arrows-out-simple',
        'icon_style': 'purple',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'ide_quick_import': {
        'title': 'Быстрый старт',
        'desc': 'Вставить сниппет библиотеки через меню инструментов IDE',
        'icon': 'ph-lightning',
        'icon_style': 'amber',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'ide_format_code': {
        'title': 'Перфекционист кода',
        'desc': 'Воспользоваться инструментом автоформатирования отступов',
        'icon': 'ph-text-indent',
        'icon_style': 'blue',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'canvas_open': {
        'title': 'Художник-мыслитель',
        'desc': 'Открыть интерактивный холст для графических заметок к задаче',
        'icon': 'ph-paint-brush',
        'icon_style': 'purple',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'canvas_save': {
        'title': 'Графический черновик',
        'desc': 'Нарисовать и сохранить рисунок или схему на холсте',
        'icon': 'ph-pencil-line',
        'icon_style': 'purple',
        'category': 'workspace',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'task_hints_view': {
        'title': 'В поисках истины',
        'desc': 'Открыть блок теоретических подсказок к задаче',
        'icon': 'ph-lightbulb',
        'icon_style': 'amber',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'material_download': {
        'title': 'Работа с источниками',
        'desc': 'Скачать прикрепленный файл входных данных к задаче',
        'icon': 'ph-file-text',
        'icon_style': 'blue',
        'category': 'workspace',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },

    # ---------------------------------------------------------------------
    # 2. Практика & Решение задач (КЕГЭ) — 12 интерактивных
    # ---------------------------------------------------------------------
    'first_step': {
        'title': 'Первый шаг',
        'desc': 'Отправить первую работу на проверку',
        'icon': 'ph-footprints',
        'icon_style': 'orange',
        'category': 'tasks',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'работа',
    },
    'perfect_homework': {
        'title': 'Чистый лист',
        'desc': 'Сдать домашнюю работу на 100% без единой ошибки с первой попытки',
        'icon': 'ph-medal',
        'icon_style': 'amber',
        'category': 'tasks',
        'rarity': 'epic',
        'rarity_label': 'ЭПИЧЕСКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 1,
        'unit': 'работа',
    },
    'early_bird_submission': {
        'title': 'С опережением графика',
        'desc': 'Сдать работу более чем за 24 часа до наступления дедлайна',
        'icon': 'ph-alarm',
        'icon_style': 'emerald',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'speedrun_task': {
        'title': 'Спринтер',
        'desc': 'Решить задачу правильно быстрее чем за 30 секунд',
        'icon': 'ph-timer',
        'icon_style': 'blue',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'combo_5_correct': {
        'title': 'В ударе',
        'desc': 'Решить 5 задач подряд с первой попытки без ошибок',
        'icon': 'ph-fire',
        'icon_style': 'orange',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 5,
        'unit': 'задач',
    },
    'ege_task_2': {
        'title': 'Логик Буля',
        'desc': 'Безошибочно решить задание №2 (таблицы истинности)',
        'icon': 'ph-tree-structure',
        'icon_style': 'blue',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_8': {
        'title': 'Комбинатор',
        'desc': 'Успешно решить задание №8 (слова и комбинаторика)',
        'icon': 'ph-shuffle',
        'icon_style': 'purple',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_13': {
        'title': 'Сетевой архитектор',
        'desc': 'Правильно решить задачу №13 (маски подсетей и IP-адреса)',
        'icon': 'ph-globe',
        'icon_style': 'emerald',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_16': {
        'title': 'Повелитель глубин',
        'desc': 'Решить задачу №16 на рекурсивные алгоритмы и функции',
        'icon': 'ph-spiral',
        'icon_style': 'purple',
        'category': 'tasks',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_24': {
        'title': 'Стринг-мастер',
        'desc': 'Правильно решить строковую задачу №24 в файле',
        'icon': 'ph-brackets-curly',
        'icon_style': 'indigo',
        'category': 'tasks',
        'rarity': 'epic',
        'rarity_label': 'ЭПИЧЕСКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_26': {
        'title': 'Жадный стратег',
        'desc': 'Справиться с задачей №26 на сортировку и жадные алгоритмы',
        'icon': 'ph-hard-drive',
        'icon_style': 'amber',
        'category': 'tasks',
        'rarity': 'epic',
        'rarity_label': 'ЭПИЧЕСКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 1,
        'unit': 'задача',
    },
    'ege_task_27': {
        'title': 'Элита КЕГЭ',
        'desc': 'Решить сложнейшую задачу №27 на кластеры или эффективный поиск',
        'icon': 'ph-trophy',
        'icon_style': 'amber',
        'category': 'tasks',
        'rarity': 'legendary',
        'rarity_label': 'ЛЕГЕНДАРНАЯ',
        'is_secret': False,
        'xp_reward': 250,
        'target': 1,
        'unit': 'задача',
    },

    # ---------------------------------------------------------------------
    # 3. Теория & Исследования — 6 интерактивных
    # ---------------------------------------------------------------------
    'theory_first': {
        'title': 'Первые страницы',
        'desc': 'Прочитать свою первую тему в интерактивном учебнике',
        'icon': 'ph-book-open',
        'icon_style': 'emerald',
        'category': 'theory',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'тема',
    },
    'theory_5_topics': {
        'title': 'Книжный червь',
        'desc': 'Освоить 5 различных тем теории',
        'icon': 'ph-books',
        'icon_style': 'blue',
        'category': 'theory',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 5,
        'unit': 'тем',
    },
    'theory_quiz_pass': {
        'title': 'Самопроверка',
        'desc': 'Успешно пройти интерактивный мини-квиз в конце теории',
        'icon': 'ph-check-circle',
        'icon_style': 'emerald',
        'category': 'theory',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'theory_copy_snippet': {
        'title': 'В копилку знаний',
        'desc': 'Скопировать пример кода из теоретической статьи',
        'icon': 'ph-copy-simple',
        'icon_style': 'indigo',
        'category': 'theory',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'theory_search_used': {
        'title': 'Справочное бюро',
        'desc': 'Воспользоваться поиском по конспектам теории',
        'icon': 'ph-magnifying-glass',
        'icon_style': 'blue',
        'category': 'theory',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'theory_python_module': {
        'title': 'Python-теоретик',
        'desc': 'Полностью завершить изучение всех тем блока Python',
        'icon': 'ph-code',
        'icon_style': 'amber',
        'category': 'theory',
        'rarity': 'epic',
        'rarity_label': 'ЭПИЧЕСКАЯ',
        'is_secret': False,
        'xp_reward': 200,
        'target': 1,
        'unit': 'модуль',
    },

    # ---------------------------------------------------------------------
    # 4. Уроки & Социальное взаимодействие — 7 интерактивных
    # ---------------------------------------------------------------------
    'lesson_first_done': {
        'title': 'Боевое крещение',
        'desc': 'Успешно завершить своё первое занятие с преподавателем',
        'icon': 'ph-chalkboard-teacher',
        'icon_style': 'indigo',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'урок',
    },
    'lesson_on_time': {
        'title': 'Точность королей',
        'desc': 'Подключиться к интерактивной комнате урока вовремя',
        'icon': 'ph-clock-check',
        'icon_style': 'emerald',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'lesson_chat_active': {
        'title': 'Голос аудитории',
        'desc': 'Отправить вопрос или сообщение в чат онлайн-урока',
        'icon': 'ph-chat-circle-text',
        'icon_style': 'blue',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'lesson_code_live': {
        'title': 'Кодинг в эфире',
        'desc': 'Запустить решение в комнате онлайн-урока',
        'icon': 'ph-play-circle',
        'icon_style': 'purple',
        'category': 'lessons',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'profile_avatar_set': {
        'title': 'Индивидуальность',
        'desc': 'Установить собственный аватар в личном профиле',
        'icon': 'ph-user-circle',
        'icon_style': 'indigo',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'profile_bio_set': {
        'title': 'О себе',
        'desc': 'Заполнить статус или описание в личном профиле',
        'icon': 'ph-note-pencil',
        'icon_style': 'blue',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'referral_copied': {
        'title': 'Зови друзей!',
        'desc': 'Скопировать свою реферальную ссылку для приглашения друзей',
        'icon': 'ph-share-network',
        'icon_style': 'purple',
        'category': 'lessons',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },

    # ---------------------------------------------------------------------
    # 5. Вехи прогресса (Накопительные) — 7 достижений
    # ---------------------------------------------------------------------
    'streak_3': {
        'title': 'Первая искра',
        'desc': 'Удерживать стрик активности 3 дня подряд',
        'icon': 'ph-fire-simple',
        'icon_style': 'orange',
        'category': 'milestone',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 3,
        'unit': 'дней',
    },
    'streak_7': {
        'title': 'Неделя в огне',
        'desc': 'Удерживать стрик активности 7 дней подряд',
        'icon': 'ph-fire',
        'icon_style': 'orange',
        'category': 'milestone',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 7,
        'unit': 'дней',
    },
    'streak_30': {
        'title': 'Огненный марафон',
        'desc': 'Удерживать стрик активности целый месяц (30 дней)',
        'icon': 'ph-flame',
        'icon_style': 'orange',
        'category': 'milestone',
        'rarity': 'legendary',
        'rarity_label': 'ЛЕГЕНДАРНАЯ',
        'is_secret': False,
        'xp_reward': 300,
        'target': 30,
        'unit': 'дней',
    },
    'tasks_10': {
        'title': 'Первый десяток',
        'desc': 'Решить правильно 10 задач',
        'icon': 'ph-check-circle',
        'icon_style': 'emerald',
        'category': 'milestone',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 10,
        'unit': 'задач',
    },
    'tasks_50': {
        'title': 'Индустриальный кодер',
        'desc': 'Решить правильно 50 задач',
        'icon': 'ph-stack',
        'icon_style': 'blue',
        'category': 'milestone',
        'rarity': 'rare',
        'rarity_label': 'РЕДКАЯ',
        'is_secret': False,
        'xp_reward': 150,
        'target': 50,
        'unit': 'задач',
    },
    'tasks_150': {
        'title': 'Стахановец кода',
        'desc': 'Решить правильно 150 задач',
        'icon': 'ph-factory',
        'icon_style': 'purple',
        'category': 'milestone',
        'rarity': 'epic',
        'rarity_label': 'ЭПИЧЕСКАЯ',
        'is_secret': False,
        'xp_reward': 250,
        'target': 150,
        'unit': 'задач',
    },
    'lvl_5': {
        'title': 'Ученик чародея',
        'desc': 'Достичь 5 уровня платформы',
        'icon': 'ph-student',
        'icon_style': 'indigo',
        'category': 'milestone',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 5,
        'unit': 'уровень',
    },
    'xp_1000': {
        'title': 'Тысячник',
        'desc': 'Накопить 1000 очков опыта платформы',
        'icon': 'ph-sparkle',
        'icon_style': 'amber',
        'category': 'milestone',
        'rarity': 'common',
        'rarity_label': 'ОБЫЧНАЯ',
        'is_secret': False,
        'xp_reward': 100,
        'target': 1000,
        'unit': 'XP',
    },

    # ---------------------------------------------------------------------
    # 6. Секретные достижения — ровно 10 пасхалок! 🕵️‍♂️
    # ---------------------------------------------------------------------
    'secret_night_owl': {
        'title': 'Ночной призрак',
        'desc': 'Отправить верное решение глубокой ночью (с 00:00 до 05:00 МСК)',
        'icon': 'ph-moon-stars',
        'icon_style': 'purple',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 150,
        'target': 1,
        'unit': 'раз',
    },
    'secret_early_bird': {
        'title': 'Ранняя пташка',
        'desc': 'Решить задачу на рассвете (с 05:00 до 07:00 МСК)',
        'icon': 'ph-sun-horizon',
        'icon_style': 'amber',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 150,
        'target': 1,
        'unit': 'раз',
    },
    'secret_recursion_depth': {
        'title': 'В бесконечность и далее',
        'desc': 'Вызвать RecursionError (переполнение стека рекурсии) при запуске кода',
        'icon': 'ph-infinity',
        'icon_style': 'purple',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'secret_zero_division': {
        'title': 'Черная дыра',
        'desc': 'Попытаться поделить на ноль (ZeroDivisionError) в редакторе кода',
        'icon': 'ph-circle-dashed',
        'icon_style': 'slate',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'secret_ghost_friend': {
        'title': 'Друг Бу-призрака',
        'desc': 'Кликнуть по маскоту-призраку в профиле 5 раз подряд',
        'icon': 'ph-ghost',
        'icon_style': 'indigo',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'secret_zen_python': {
        'title': 'Дзен Питона',
        'desc': 'Выполнить в IDE команду import this',
        'icon': 'ph-yin-yang',
        'icon_style': 'emerald',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 150,
        'target': 1,
        'unit': 'раз',
    },
    'secret_theme_toggle': {
        'title': 'Тёмная сторона силы',
        'desc': 'Переключить тему интерфейса на тёмную',
        'icon': 'ph-moon',
        'icon_style': 'slate',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'secret_syntax_recovery': {
        'title': 'Ошибки делают нас сильнее',
        'desc': 'Допустить SyntaxError, а следующим запуском сразу же исправить его',
        'icon': 'ph-bug',
        'icon_style': 'emerald',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 100,
        'target': 1,
        'unit': 'раз',
    },
    'secret_all_sections': {
        'title': 'Любознательный исследователь',
        'desc': 'Посетить все 5 ключевых разделов платформы (Дашборд, Задачи, Теория, Уроки, Профиль)',
        'icon': 'ph-compass',
        'icon_style': 'blue',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 150,
        'target': 1,
        'unit': 'раз',
    },
    'secret_marathon_hour': {
        'title': 'Гиперфокус',
        'desc': 'Непрерывно заниматься на платформе более 60 минут',
        'icon': 'ph-hourglass-high',
        'icon_style': 'amber',
        'category': 'secret',
        'rarity': 'secret',
        'rarity_label': 'ТАЙНА',
        'is_secret': True,
        'xp_reward': 150,
        'target': 1,
        'unit': 'раз',
    },
}

# Карта обратной совместимости старых ключей базы данных
LEGACY_KEY_MAP = {
    'night_owl': 'secret_night_owl',
    'early_bird': 'secret_early_bird',
    'speedrun': 'speedrun_task',
    'recursion_overflow': 'secret_recursion_depth',
    'ege_logic': 'ege_task_2',
    'ege_itertools': 'ege_task_8',
    'ege_ip': 'ege_task_13',
    'ege_recursion': 'ege_task_16',
    'ege_26': 'ege_task_26',
    'tasks_200': 'tasks_150',
    'tasks_500': 'tasks_150',
}


def build_student_achievement_catalog(student):
    """
    Формирует полный список всех 52 достижений для профиля ученика.
    
    Честно рассчитывает прогресс из базы данных.
    Секретные достижения (10 шт), пока не получены, полностью маскируются
    под загадочные заблокированные карточки ('Тайное достижение').
    """
    if not student:
        return []

    unlocked_rows = UserAchievement.query.filter_by(student_id=student.student_id).all()
    unlocked_dates = {}
    for row in unlocked_rows:
        canonical_key = LEGACY_KEY_MAP.get(row.achievement_key, row.achievement_key)
        if row.unlocked_at:
            unlocked_dates[canonical_key] = row.unlocked_at.strftime('%d.%m.%Y')
        else:
            unlocked_dates[canonical_key] = datetime.now().strftime('%d.%m.%Y')
    
    unlocked_keys = set(unlocked_dates.keys())

    completed_submissions = Submission.query.filter(
        Submission.student_id == student.student_id,
        Submission.status.in_(['SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED']),
    ).count()
    correct_answers = (
        Answer.query.join(Submission, Answer.submission_id == Submission.submission_id)
        .filter(Submission.student_id == student.student_id, Answer.is_correct.is_(True))
        .count()
    )

    streak_val = int(student.streak_days or 0)
    level_val = int(student.level or 1)

    # Значения прогресса для накопительных достижений
    progress_values = {
        'first_step': completed_submissions,
        'perfect_homework': 1 if 'perfect_homework' in unlocked_keys else 0,
        'streak_3': streak_val,
        'streak_7': streak_val,
        'streak_30': streak_val,
        'tasks_10': correct_answers,
        'tasks_50': correct_answers,
        'tasks_150': correct_answers,
        'lvl_5': level_val,
        'xp_1000': int(getattr(student, 'xp', 0) or 0),
        'combo_5_correct': 5 if 'combo_5_correct' in unlocked_keys else 0,
        'theory_5_topics': 5 if 'theory_5_topics' in unlocked_keys else 0,
    }

    catalog = []
    for key, meta in ACHIEVEMENTS_REGISTRY.items():
        is_unlocked = key in unlocked_keys
        is_secret = meta.get('is_secret', False)
        target = meta.get('target', 1)
        unit = meta.get('unit', '')

        if is_secret and not is_unlocked:
            # Маскируем неполученное секретное достижение
            catalog.append({
                'key': key,
                'title': 'Тайное достижение',
                'desc': 'Условия открытия окутаны тайной... Соверши что-то необычное на платформе!',
                'condition': 'Условия открытия окутаны тайной...',
                'icon': 'ph-lock-key',
                'icon_style': 'purple',
                'rarity': 'secret',
                'rarity_label': 'ТАЙНА',
                'category': meta.get('category', 'secret'),
                'is_secret': True,
                'unlocked': False,
                'status_type': 'secret_locked',
                'current': 0,
                'target': target,
                'progress_pct': 0,
                'progress_display': f'??? / {target}',
                'date': None,
                'xp': meta.get('xp_reward', 100),
            })
        else:
            if is_unlocked:
                status_type = 'unlocked'
                current = target
                progress_pct = 100
                progress_display = f'{target} / {target}'
            else:
                current = progress_values.get(key, 0)
                if current > 0:
                    status_type = 'in_progress'
                    progress_pct = min(99, int((current / max(1, target)) * 100))
                else:
                    status_type = 'locked'
                    progress_pct = 0
                progress_display = f'{min(current, target)} / {target}'
                if unit:
                    progress_display += f' {unit}'

            catalog.append({
                'key': key,
                'title': meta['title'],
                'desc': meta['desc'],
                'condition': meta['desc'],
                'icon': meta['icon'],
                'icon_style': meta.get('icon_style', 'indigo'),
                'rarity': meta.get('rarity', 'common'),
                'rarity_label': meta.get('rarity_label', 'ОБЫЧНАЯ'),
                'category': meta.get('category', 'tasks'),
                'is_secret': is_secret,
                'unlocked': is_unlocked,
                'status_type': status_type,
                'current': current,
                'target': target,
                'progress_pct': progress_pct,
                'progress_display': progress_display,
                'date': unlocked_dates.get(key),
                'xp': meta.get('xp_reward', 100),
            })

    return catalog


def get_student_unlocked_achievement_keys(student_id):
    """Возвращает список канонических ключей полученных ачивок ученика."""
    unlocked = UserAchievement.query.filter_by(student_id=student_id).all()
    res = set()
    for u in unlocked:
        key = LEGACY_KEY_MAP.get(u.achievement_key, u.achievement_key)
        res.add(key)
    return list(res)


def grant_achievement(student, achievement_key, award_xp=True, *, commit=True):
    """
    Выдает ачивку ученику. Начисляет XP бонусного опыта.
    Возвращает True, если ачивка была выдана только что, или False, если уже была.
    """
    if not student:
        return False
    
    canonical_key = LEGACY_KEY_MAP.get(achievement_key, achievement_key)
    if canonical_key not in ACHIEVEMENTS_REGISTRY:
        return False

    existing = UserAchievement.query.filter(
        UserAchievement.student_id == student.student_id,
        UserAchievement.achievement_key.in_([canonical_key, achievement_key])
    ).first()

    if existing:
        return False

    try:
        new_ach = UserAchievement(
            student_id=student.student_id,
            achievement_key=canonical_key,
            unlocked_at=datetime.utcnow()
        )
        db.session.add(new_ach)

        meta = ACHIEVEMENTS_REGISTRY[canonical_key]
        xp = meta.get('xp_reward', 100)
        if award_xp and xp > 0:
            add_xp_to_student(student, xp, commit=commit)

        if commit:
            db.session.commit()
        logger.info("Granted achievement '%s' to student_id=%s (+%s XP)", canonical_key, student.student_id, xp)
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error granting achievement %s to student %s: %s", canonical_key, student.student_id, e, exc_info=True)
        return False


def revoke_achievement(student, achievement_key):
    """Забирает ачивку у ученика."""
    if not student:
        return False

    canonical_key = LEGACY_KEY_MAP.get(achievement_key, achievement_key)
    try:
        existing = UserAchievement.query.filter(
            UserAchievement.student_id == student.student_id,
            UserAchievement.achievement_key.in_([canonical_key, achievement_key])
        ).first()

        if existing:
            db.session.delete(existing)
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        logger.error("Error revoking achievement %s from student %s: %s", achievement_key, student.student_id, e, exc_info=True)
        return False


def process_achievement_event(student, event_name, event_data=None, *, commit=True):
    """
    Единый диспетчер интерактивных, контекстных и секретных событий.
    Возвращает dict с результатом:
    {
        "unlocked": True / False,
        "achievement": { 'key': ..., 'title': ..., ... } / None
    }
    """
    if not student:
        return {"unlocked": False, "achievement": None}

    event_data = event_data or {}
    key_to_grant = None

    # 1. Прямые интерактивные действия в Workspace/IDE
    if event_name in [
        'ide_run_shortcut', 'ide_copy_code', 'ide_download_py',
        'ide_fullscreen', 'ide_quick_import', 'ide_format_code',
        'canvas_open', 'canvas_save', 'task_hints_view', 'material_download'
    ]:
        key_to_grant = event_name

    # 2. События в теории
    elif event_name in ['theory_first', 'theory_quiz_pass', 'theory_copy_snippet', 'theory_search_used']:
        key_to_grant = event_name
    elif event_name == 'theory_read':
        key_to_grant = 'theory_first'
        read_count = event_data.get('read_count', 0)
        if read_count >= 5:
            grant_achievement(student, 'theory_5_topics', commit=commit)

    # 3. Уроки, профиль и коммуникация
    elif event_name in [
        'lesson_first_done', 'lesson_on_time', 'lesson_chat_active',
        'lesson_code_live', 'profile_avatar_set', 'profile_bio_set', 'referral_copied'
    ]:
        key_to_grant = event_name

    # 4. Задачи и КЕГЭ
    elif event_name == 'submission_created':
        key_to_grant = 'first_step'
    elif event_name == 'perfect_homework':
        key_to_grant = 'perfect_homework'
    elif event_name == 'submission_early':
        key_to_grant = 'early_bird_submission'
    elif event_name == 'task_speedrun':
        key_to_grant = 'speedrun_task'
    elif event_name == 'task_correct':
        task_num = event_data.get('task_number') or event_data.get('kege_number')
        try:
            task_num = int(task_num)
        except (ValueError, TypeError):
            task_num = None

        if task_num == 2: key_to_grant = 'ege_task_2'
        elif task_num == 8: key_to_grant = 'ege_task_8'
        elif task_num == 13: key_to_grant = 'ege_task_13'
        elif task_num == 16: key_to_grant = 'ege_task_16'
        elif task_num == 24: key_to_grant = 'ege_task_24'
        elif task_num == 26: key_to_grant = 'ege_task_26'
        elif task_num == 27: key_to_grant = 'ege_task_27'

        combo = event_data.get('combo_correct', 0)
        if combo >= 5:
            grant_achievement(student, 'combo_5_correct', commit=commit)

    # 5. Секретные пасхалки
    elif event_name == 'secret_ghost_friend':
        clicks = int(event_data.get('clicks', 1) or 1)
        if clicks >= 5:
            key_to_grant = 'secret_ghost_friend'
    elif event_name == 'secret_theme_toggle':
        key_to_grant = 'secret_theme_toggle'
    elif event_name == 'secret_marathon_hour':
        key_to_grant = 'secret_marathon_hour'
    elif event_name == 'secret_all_sections':
        key_to_grant = 'secret_all_sections'
    elif event_name == 'python_error':
        error_type = str(event_data.get('error_type', ''))
        if 'RecursionError' in error_type:
            key_to_grant = 'secret_recursion_depth'
        elif 'ZeroDivisionError' in error_type:
            key_to_grant = 'secret_zero_division'
    elif event_name in ['zen_python', 'secret_zen_python']:
        key_to_grant = 'secret_zen_python'
    elif event_name in ['syntax_recovery', 'secret_syntax_recovery']:
        key_to_grant = 'secret_syntax_recovery'
    elif event_name == 'time_based_submission':
        hour_msk = event_data.get('hour_msk')
        if hour_msk is not None:
            try:
                hour_msk = int(hour_msk)
                if 0 <= hour_msk < 5:
                    key_to_grant = 'secret_night_owl'
                elif 5 <= hour_msk < 7:
                    key_to_grant = 'secret_early_bird'
            except (ValueError, TypeError):
                pass

    # Если имя события совпадает с каноническим ключом реестра
    canonical_name = LEGACY_KEY_MAP.get(event_name, event_name)
    if not key_to_grant and canonical_name in ACHIEVEMENTS_REGISTRY:
        key_to_grant = canonical_name

    if key_to_grant and key_to_grant in ACHIEVEMENTS_REGISTRY:
        unlocked = grant_achievement(student, key_to_grant, commit=commit)
        if unlocked:
            meta = ACHIEVEMENTS_REGISTRY[key_to_grant]
            return {
                "unlocked": True,
                "achievement": {
                    "key": key_to_grant,
                    "title": meta['title'],
                    "desc": meta['desc'],
                    "icon": meta['icon'],
                    "icon_style": meta.get('icon_style', 'indigo'),
                    "rarity": meta.get('rarity', 'common'),
                    "rarity_label": meta.get('rarity_label', 'ОБЫЧНАЯ'),
                    "category": meta.get('category', 'tasks'),
                    "is_secret": meta.get('is_secret', False),
                    "xp_reward": meta.get('xp_reward', 100)
                }
            }

    return {"unlocked": False, "achievement": None}


def check_and_grant_dynamic_achievements(student, *, commit=True):
    """
    Проверяет и выдает накопительные ачивки на основе стрика, уровня и решенных задач.
    """
    if not student:
        return

    # 1. Стрики
    streak = student.streak_days or 0
    if streak >= 3: grant_achievement(student, 'streak_3', commit=commit)
    if streak >= 7: grant_achievement(student, 'streak_7', commit=commit)
    if streak >= 30: grant_achievement(student, 'streak_30', commit=commit)

    # 2. Уровни и опыт
    level = student.level or 1
    if level >= 5: grant_achievement(student, 'lvl_5', commit=commit)
    xp = getattr(student, 'xp', 0) or 0
    if xp >= 1000: grant_achievement(student, 'xp_1000', commit=commit)

    # 3. Решенные задачи
    correct_answers = (
        Answer.query.join(Submission, Answer.submission_id == Submission.submission_id)
        .filter(Submission.student_id == student.student_id, Answer.is_correct.is_(True))
        .count()
    )
    if correct_answers >= 10: grant_achievement(student, 'tasks_10', commit=commit)
    if correct_answers >= 50: grant_achievement(student, 'tasks_50', commit=commit)
    if correct_answers >= 150: grant_achievement(student, 'tasks_150', commit=commit)

    # 4. Первая сданная работа
    submissions_cnt = Submission.query.filter(
        Submission.student_id == student.student_id,
        Submission.status.in_(['SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED']),
    ).count()
    if submissions_cnt >= 1:
        grant_achievement(student, 'first_step', commit=commit)
