from datetime import datetime
from app.models import db, Student, UserAchievement
from app.utils.xp_service import add_xp_to_student

# Спецификация достижений (Ачивки) ЕГЭ по Информатике
ACHIEVEMENTS_REGISTRY = {
    'streak_3': {
        'title': 'Первая искра',
        'desc': 'Держать стрик активности 3 дня',
        'icon': 'ph-fire-simple',
        'category': 'streak'
    },
    'streak_7': {
        'title': 'Неделя в огне',
        'desc': 'Держать стрик активности 7 дней',
        'icon': 'ph-fire',
        'category': 'streak'
    },
    'streak_30': {
        'title': 'Огненный марафон',
        'desc': 'Держать стрик активности 30 дней',
        'icon': 'ph-flame',
        'category': 'streak'
    },
    'streak_90': {
        'title': 'Вечный двигатель',
        'desc': 'Держать стрик активности 90 дней (четверть года!)',
        'icon': 'ph-lightning',
        'category': 'streak'
    },
    'streak_180': {
        'title': 'Учебный Самурай',
        'desc': 'Удерживать стрик 180 дней подряд',
        'icon': 'ph-sword',
        'category': 'streak'
    },
    'first_step': {
        'title': 'Быстрый старт',
        'desc': 'Зайти на платформу в первый раз',
        'icon': 'ph-footprints',
        'category': 'streak'
    },
    'weekend_warrior': {
        'title': 'Воин выходного дня',
        'desc': 'Решить 5 задач в субботу или воскресенье',
        'icon': 'ph-calendar-star',
        'category': 'streak'
    },
    'lvl_5': {
        'title': 'Ученик чародея',
        'desc': 'Достичь 5 уровня',
        'icon': 'ph-student',
        'category': 'level'
    },
    'lvl_15': {
        'title': 'Уверенный скриптер',
        'desc': 'Достичь 15 уровня',
        'icon': 'ph-code-block',
        'category': 'level'
    },
    'lvl_30': {
        'title': 'Магистр алгоритмов',
        'desc': 'Достичь 30 уровня',
        'icon': 'ph-books',
        'category': 'level'
    },
    'lvl_50': {
        'title': 'Бог Информатики',
        'desc': 'Достичь легендарного 50 уровня',
        'icon': 'ph-crown',
        'category': 'level'
    },
    'xp_1000': {
        'title': 'Первая тысяча',
        'desc': 'Набрать суммарно 1000 XP',
        'icon': 'ph-coins',
        'category': 'level'
    },
    'xp_10000': {
        'title': 'Опытный майнер',
        'desc': 'Набрать суммарно 10000 XP',
        'icon': 'ph-gemstone',
        'category': 'level'
    },
    'tasks_10': {
        'title': 'Первый десяток',
        'desc': 'Решить правильно 10 задач',
        'icon': 'ph-check-circle',
        'category': 'tasks'
    },
    'tasks_50': {
        'title': 'Индустриальный кодер',
        'desc': 'Решить правильно 50 задач',
        'icon': 'ph-stack',
        'category': 'tasks'
    },
    'tasks_200': {
        'title': 'Стахановец кода',
        'desc': 'Решить правильно 200 задач',
        'icon': 'ph-factory',
        'category': 'tasks'
    },
    'tasks_500': {
        'title': 'Легенда коммитов',
        'desc': 'Решить правильно 500 задач',
        'icon': 'ph-infinite',
        'category': 'tasks'
    },
    'perfect_homework': {
        'title': 'Чистый лист',
        'desc': 'Сдать домашку целиком без единой ошибки с первой попытки',
        'icon': 'ph-medal',
        'category': 'tasks'
    },
    'ege_logic': {
        'title': 'Логик Буля',
        'desc': 'Безошибочно решить задание №2 (таблицы истинности)',
        'icon': 'ph-tree-structure',
        'category': 'ege'
    },
    'ege_excel': {
        'title': 'Властелин Таблиц',
        'desc': 'Успешно сдать задание №3 или №9 (базы/таблицы)',
        'icon': 'ph-table',
        'category': 'ege'
    },
    'ege_fano': {
        'title': 'Криптограф Шеннона',
        'desc': 'Решить кодирование по условию Фано (№4)',
        'icon': 'ph-key',
        'category': 'ege'
    },
    'ege_itertools': {
        'title': 'Комбинатор',
        'desc': 'Использовать itertools для решения задания №8',
        'icon': 'ph-shuffle',
        'category': 'ege'
    },
    'ege_ip': {
        'title': 'Сетевой инженер',
        'desc': 'Безошибочно решить задачу на маски подсетей IP (№13)',
        'icon': 'ph-globe',
        'category': 'ege'
    },
    'ege_recursion': {
        'title': 'Петля Мёбиуса',
        'desc': 'Решить задачу на рекурсивные алгоритмы (№16)',
        'icon': 'ph-spiral',
        'category': 'ege'
    },
    'ege_theory_games': {
        'title': 'Кэшбэк опыта',
        'desc': 'Решить теорию игр (№19-21) кодом с мемоизацией',
        'icon': 'ph-ghost',
        'category': 'ege'
    },
    'ege_mask': {
        'title': 'Масочник',
        'desc': 'Успешно решить поиск делителей по маске (№25)',
        'icon': 'ph-mask-happy',
        'category': 'ege'
    },
    'ege_26': {
        'title': 'Оптимизатор памяти',
        'desc': 'Правильно решить задачу №26 (сортировка/жадные алгоритмы)',
        'icon': 'ph-hard-drive',
        'category': 'ege'
    },
    'ege_27a': {
        'title': 'Первый шаг к сотке',
        'desc': 'Успешно решить задачу №27А',
        'icon': 'ph-flag',
        'category': 'ege'
    },
    'ege_27b': {
        'title': 'Аннигилятор №27Б',
        'desc': 'Решить задачу №27Б на оптимальную сложность',
        'icon': 'ph-trophy',
        'category': 'ege'
    },
    'night_owl': {
        'title': 'Ночная сова',
        'desc': 'Отправить верное решение в интервале с 00:00 до 04:00 по МСК',
        'icon': 'ph-owl',
        'category': 'secret'
    },
    'early_bird': {
        'title': 'Ранняя пташка',
        'desc': 'Отправить верное решение в интервале с 05:00 до 07:00 по МСК',
        'icon': 'ph-bird',
        'category': 'secret'
    },
    'speedrun': {
        'title': 'Спидраннер',
        'desc': 'Решить задачу менее чем за 15 секунд после открытия',
        'icon': 'ph-timer',
        'category': 'secret'
    },
    'recursion_overflow': {
        'title': 'Стек переполнен',
        'desc': 'Попробовать запустить рекурсию без базового случая (вызов ошибки)',
        'icon': 'ph-skull',
        'category': 'secret'
    }
}

def get_student_unlocked_achievement_keys(student_id):
    """Возвращает список ключей полученных ачивок ученика."""
    unlocked = UserAchievement.query.filter_by(student_id=student_id).all()
    return [u.achievement_key for u in unlocked]

def grant_achievement(student, achievement_key, award_xp=True):
    """
    Выдает ачивку ученику. Начисляет +100 XP бонусного опыта.
    """
    if not student or achievement_key not in ACHIEVEMENTS_REGISTRY:
        return False
    
    # Проверяем, не выдана ли уже
    existing = UserAchievement.query.filter_by(
        student_id=student.student_id, 
        achievement_key=achievement_key
    ).first()
    
    if existing:
        return False
    
    try:
        new_ach = UserAchievement(
            student_id=student.student_id,
            achievement_key=achievement_key
        )
        db.session.add(new_ach)
        
        # За верную ачивку даем +100 XP
        if award_xp:
            add_xp_to_student(student, 100)
            
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error granting achievement {achievement_key} to student {student.student_id}: {e}", exc_info=True)
        return False

def revoke_achievement(student, achievement_key):
    """
    Забирает ачивку у ученика.
    """
    if not student:
        return False
        
    try:
        existing = UserAchievement.query.filter_by(
            student_id=student.student_id, 
            achievement_key=achievement_key
        ).first()
        
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error revoking achievement {achievement_key} from student {student.student_id}: {e}", exc_info=True)
        return False

def check_and_grant_dynamic_achievements(student):
    """
    Проверяет и выдает ачивки на основе стрика, уровня, опыта и решенных задач.
    """
    if not student:
        return
    
    # 1. Проверки по стрикам
    streak = student.streak_days or 0
    if streak >= 3: grant_achievement(student, 'streak_3')
    if streak >= 7: grant_achievement(student, 'streak_7')
    if streak >= 30: grant_achievement(student, 'streak_30')
    if streak >= 90: grant_achievement(student, 'streak_90')
    if streak >= 180: grant_achievement(student, 'streak_180')
    
    # Всегда выдаем первый шаг при входе
    grant_achievement(student, 'first_step', award_xp=False)
    
    # 2. Проверки по уровням и XP
    level = student.level or 1
    xp = student.xp or 0
    if level >= 5: grant_achievement(student, 'lvl_5')
    if level >= 15: grant_achievement(student, 'lvl_15')
    if level >= 30: grant_achievement(student, 'lvl_30')
    if level >= 50: grant_achievement(student, 'lvl_50')
    if xp >= 1000: grant_achievement(student, 'xp_1000')
    if xp >= 10000: grant_achievement(student, 'xp_10000')
