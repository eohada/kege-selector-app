"""
Присвоение числовых идентификаторов пользователям (не ученикам).
Ученики: Student.platform_id 100–999 (student_id_manager).
Остальные роли: User.numeric_id 10–99 (двузначные по умолчанию).
"""
import logging
from app.models import User, db

logger = logging.getLogger(__name__)

MIN_NONSTUDENT_ID = 10
MAX_NONSTUDENT_ID = 99


def get_next_available_numeric_id():
    """
    Следующий свободный двузначный идентификатор (10–99) для User.numeric_id.
    """
    try:
        occupied = set()
        rows = User.query.filter(User.numeric_id.isnot(None)).with_entities(User.numeric_id).all()
        for (val,) in rows:
            if not val:
                continue
            s = str(val).strip()
            if s.isdigit():
                n = int(s)
                if MIN_NONSTUDENT_ID <= n <= MAX_NONSTUDENT_ID:
                    occupied.add(n)
        for n in range(MIN_NONSTUDENT_ID, MAX_NONSTUDENT_ID + 1):
            if n not in occupied:
                return str(n)
        logger.error(f"Все идентификаторы {MIN_NONSTUDENT_ID}–{MAX_NONSTUDENT_ID} заняты")
        return None
    except Exception as e:
        logger.error(f"Ошибка get_next_available_numeric_id: {e}", exc_info=True)
        for n in range(MIN_NONSTUDENT_ID, MAX_NONSTUDENT_ID + 1):
            if not User.query.filter_by(numeric_id=str(n)).first():
                return str(n)
        return None


def is_valid_two_digit_id(value):
    """Валидный двузначный идентификатор 10–99."""
    if not value:
        return False
    try:
        n = int(str(value).strip())
        return MIN_NONSTUDENT_ID <= n <= MAX_NONSTUDENT_ID
    except (ValueError, TypeError):
        return False


def assign_numeric_id_if_needed(user):
    """
    Присвоить User.numeric_id, если у пользователя его ещё нет и он не ученик
    (у учеников используется Student.platform_id).
    """
    from app.models import Student
    roles = user.roles() if hasattr(user, 'roles') and callable(getattr(user, 'roles')) else [getattr(user, 'role', '')]
    if 'student' in roles:
        return False
    if user.numeric_id:
        return False
    new_id = get_next_available_numeric_id()
    if new_id:
        user.numeric_id = new_id
        logger.info(f"Присвоен numeric_id {new_id} пользователю {user.username}")
        return True
    return False
