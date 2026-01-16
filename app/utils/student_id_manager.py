"""
Утилита для управления автоматическим присвоением идентификаторов ученикам
Присваивает трехзначные числа (100-999) и переиспользует освобожденные идентификаторы
"""
import logging
from sqlalchemy import func
from app.models import Student, db

logger = logging.getLogger(__name__)

# Диапазон идентификаторов: от 100 до 999 (включительно)
MIN_ID = 100
MAX_ID = 999


def get_next_available_id():
    """
    Получает следующий доступный трехзначный идентификатор (100-999)
    Сначала ищет освобожденные идентификаторы, затем берет следующий по порядку
    
    Returns:
        str: Следующий доступный идентификатор в виде строки (например, "123")
        None: Если все идентификаторы заняты (максимум 900 учеников)
    """
    try:
        # Получаем все занятые идентификаторы, которые являются трехзначными числами
        occupied_ids = set()
        
        # Запрашиваем все platform_id
        students = Student.query.filter(
            Student.platform_id.isnot(None)
        ).with_entities(Student.platform_id).all()
        
        for row in students:
            platform_id = row[0]
            if not platform_id:
                continue
            
            # Проверяем, что это трехзначное число в диапазоне 100-999
            platform_id_str = str(platform_id).strip()
            # Проверяем длину (3 символа) и что это число
            if len(platform_id_str) == 3 and platform_id_str.isdigit():
                try:
                    id_num = int(platform_id_str)
                    if MIN_ID <= id_num <= MAX_ID:
                        occupied_ids.add(id_num)
                except (ValueError, TypeError):
                    # Пропускаем некорректные идентификаторы
                    continue
        
        # Ищем первый свободный идентификатор
        for candidate_id in range(MIN_ID, MAX_ID + 1):
            if candidate_id not in occupied_ids:
                return str(candidate_id)
        
        # Если все идентификаторы заняты
        logger.error(f"Все идентификаторы от {MIN_ID} до {MAX_ID} заняты!")
        return None
        
    except Exception as e:
        logger.error(f"Ошибка при получении следующего доступного идентификатора: {e}", exc_info=True)
        # В случае ошибки пытаемся найти любой свободный идентификатор простым способом
        try:
            for candidate_id in range(MIN_ID, MAX_ID + 1):
                existing = Student.query.filter_by(platform_id=str(candidate_id)).first()
                if not existing:
                    return str(candidate_id)
        except Exception as fallback_error:
            logger.error(f"Ошибка при резервном поиске идентификатора: {fallback_error}")
        
        return None


def is_valid_three_digit_id(platform_id):
    """
    Проверяет, является ли идентификатор валидным трехзначным числом (100-999)
    
    Args:
        platform_id: Идентификатор для проверки
        
    Returns:
        bool: True если идентификатор валидный, False иначе
    """
    if not platform_id:
        return False
    
    try:
        id_num = int(str(platform_id).strip())
        return MIN_ID <= id_num <= MAX_ID
    except (ValueError, TypeError):
        return False


def assign_platform_id_if_needed(student):
    """
    Присваивает platform_id ученику, если он не указан
    Используется при создании нового ученика
    
    Args:
        student: Объект Student, которому нужно присвоить идентификатор
        
    Returns:
        bool: True если идентификатор был присвоен, False если уже был указан или не удалось присвоить
    """
    # Если platform_id уже указан, не меняем его
    if student.platform_id:
        return False
    
    # Получаем следующий доступный идентификатор
    new_id = get_next_available_id()
    
    if new_id:
        student.platform_id = new_id
        logger.info(f"Автоматически присвоен идентификатор {new_id} ученику {student.name}")
        return True
    else:
        logger.warning(f"Не удалось присвоить идентификатор ученику {student.name}: все идентификаторы заняты")
        return False
