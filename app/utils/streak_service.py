from datetime import timedelta
from app.models import db, Student, moscow_now

def pluralize_days(n):
    """
    Склонение слова 'день' в зависимости от числа n.
    """
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return f"{n} дней"
    if n % 10 == 1:
        return f"{n} день"
    if n % 10 in (2, 3, 4):
        return f"{n} дня"
    return f"{n} дней"

def update_student_streak(student, *, commit=True):
    """
    Обновляет стрик ежедневной активности ученика.
    """
    if not student:
        return
    
    # Если стрик заморожен, пропускаем всю логику обновлений/сбросов
    if getattr(student, 'streak_frozen', False):
        return
    
    try:
        today = moscow_now().date()
        last_date = student.last_activity_date
        
        if last_date is None:
            # Первый день активности
            student.streak_days = 1
            student.last_activity_date = today
        elif last_date == today:
            # Уже была активность сегодня, ничего не меняем
            pass
        elif last_date == today - timedelta(days=1):
            # Активность вчера -> продлеваем стрик
            student.streak_days += 1
            student.last_activity_date = today
        else:
            # Пропуск дней -> сбрасываем и начинаем заново
            student.streak_days = 1
            student.last_activity_date = today
            
        if commit:
            db.session.commit()
    except Exception as e:
        if commit:
            db.session.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error updating student daily streak: {e}", exc_info=True)

def update_student_streak_by_user_id(user_id):
    """
    Ищет Student по user_id и обновляет стрик.
    """
    if not user_id:
        return
    student = Student.query.filter_by(user_id=user_id).first()
    if student:
        update_student_streak(student)
