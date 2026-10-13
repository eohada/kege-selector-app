"""
BooStudy — Сервис ежедневных блиц-задач в Telegram для поддержания стрика.

Функционал:
- Банк микро-вопросов по КЕГЭ по информатике и основам Python.
- Формирование сообщения с интерактивными инлайн-кнопками вариантов ответа.
- Мгновенная проверка ответа ученика в Telegram.
- Автоматический инкремент ежедневного стрика, начисление +10 XP и проверка ачивок.
- Умная рассылка ученикам, чей стрик под угрозой.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.models import db, Student, User, moscow_now
from app.utils.streak_service import update_student_streak, get_student_streak_info, pluralize_days
from app.utils.xp_service import add_xp_to_student
from app.utils.achievement_service import check_and_grant_dynamic_achievements

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Банк ежедневных блиц-задач (КЕГЭ + Python)
# ---------------------------------------------------------------------------
BLITZ_QUESTIONS: List[Dict[str, Any]] = [
    {
        'id': 'blitz_py_slice',
        'topic': 'Основы Python • Срезы строк',
        'question': 'Что выведет выражение <code>"BooStudy"[::-1]</code>?',
        'options': ['ydutSooB', 'BooStudy', 'yduStooB', 'SyntaxError'],
        'correct_idx': 0,
        'explanation': 'Шаг <code>-1</code> в срезе <code>[::-1]</code> разворачивает строку задом наперёд.',
    },
    {
        'id': 'blitz_py_div',
        'topic': 'Основы Python • Арифметика',
        'question': 'Чему равно значение выражения <code>29 // 5 + 29 % 5</code>?',
        'options': ['9', '10', '8', '29'],
        'correct_idx': 0,
        'explanation': '<code>29 // 5 = 5</code> (целая часть), а <code>29 % 5 = 4</code> (остаток). Итого: 5 + 4 = 9.',
    },
    {
        'id': 'blitz_kege_14_powers',
        'topic': 'КЕГЭ №14 • Системы счисления',
        'question': 'Сколько единиц содержится в двоичной записи числа <code>2**10 - 1</code>?',
        'options': ['10 единиц', '9 единиц', '11 единиц', '1 единица'],
        'correct_idx': 0,
        'explanation': 'Число <code>2^N - 1</code> в двоичной системе счисления всегда записывается как ровно N единиц (здесь ровно 10 единиц).',
    },
    {
        'id': 'blitz_py_set',
        'topic': 'Основы Python • Коллекции set',
        'question': 'Что вернёт функция <code>len(set([5, 5, 2, 2, 8, 8, 8]))</code>?',
        'options': ['3', '7', '4', '8'],
        'correct_idx': 0,
        'explanation': 'Множество <code>set()</code> хранит только уникальные элементы: {2, 5, 8}, длина равна 3.',
    },
    {
        'id': 'blitz_kege_11_hartley',
        'topic': 'КЕГЭ №11 • Формула Хартли',
        'question': 'Сколько бит необходимо для кодирования одного символа из 60-символьного алфавита?',
        'options': ['6 бит', '5 бит', '7 бит', '8 бит'],
        'correct_idx': 0,
        'explanation': 'По формуле Хартли <code>2^i >= 60</code>. Так как 2^5 = 32 < 60, а 2^6 = 64 >= 60, требуется минимум 6 бит на символ.',
    },
    {
        'id': 'blitz_py_list_mult',
        'topic': 'Основы Python • Списки',
        'question': 'Чему равна длина списка <code>len([0] * 15 + [1] * 7)</code>?',
        'options': ['22', '105', '15', 'TypeError'],
        'correct_idx': 0,
        'explanation': 'Оператор <code>*</code> тиражирует списки, а <code>+</code> склеивает их: 15 + 7 = 22 элемента.',
    },
    {
        'id': 'blitz_kege_2_implication',
        'topic': 'КЕГЭ №2 • Математическая логика',
        'question': 'При каких значениях X и Y логическое следование <code>X → Y</code> ложно (равно 0)?',
        'options': ['X = 1, Y = 0', 'X = 0, Y = 1', 'X = 0, Y = 0', 'X = 1, Y = 1'],
        'correct_idx': 0,
        'explanation': 'Импликация <code>1 → 0 = 0</code> (из истины следует ложь). Во всех остальных случаях импликация истинна.',
    },
    {
        'id': 'blitz_py_bool',
        'topic': 'Основы Python • Приведение к bool',
        'question': 'Что вернёт выражение <code>bool("0")</code> в Python?',
        'options': ['True', 'False', '0', 'TypeError'],
        'correct_idx': 0,
        'explanation': 'Любая непустая строка в Python приводится к <code>True</code>, даже если строка содержит символ "0".',
    },
    {
        'id': 'blitz_kege_7_image',
        'topic': 'КЕГЭ №7 • Кодирование изображений',
        'question': 'Изображение 1024x512 пикселей содержит 256 цветов. Сколько Кбайт весит несжатое изображение?',
        'options': ['512 Кбайт', '256 Кбайт', '1024 Кбайт', '128 Кбайт'],
        'correct_idx': 0,
        'explanation': 'Для 256 цветов глубина цвета 8 бит (1 байт). Размер: 1024 * 512 * 1 байт = 524 288 байт = 512 Кбайт.',
    },
    {
        'id': 'blitz_kege_16_recursion',
        'topic': 'КЕГЭ №16 • Анализ рекурсии',
        'question': 'Пусть <code>F(n) = 1 при n=1</code> и <code>F(n) = F(n-1) + 3</code>. Чему равно <code>F(5)</code>?',
        'options': ['13', '15', '12', '16'],
        'correct_idx': 0,
        'explanation': 'F(1)=1, F(2)=4, F(3)=7, F(4)=10, F(5)=13 (арифметическая прогрессия с разностью 3).',
    },
]


def get_blitz_by_id(blitz_id: str) -> Optional[Dict[str, Any]]:
    """Находит задачу по её уникальному идентификатору."""
    for q in BLITZ_QUESTIONS:
        if q['id'] == blitz_id:
            return q
    return None


def get_daily_blitz(target_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Возвращает задачу дня.
    Детерминированно выбирается на основе даты, чтобы в один день
    все ученики получали одну и ту же согласованную тему дня.
    """
    d = target_date or moscow_now().date()
    day_num = d.toordinal()
    idx = day_num % len(BLITZ_QUESTIONS)
    return BLITZ_QUESTIONS[idx]


def format_blitz_message(blitz: Dict[str, Any], streak_days: int = 0) -> str:
    """Форматирует красивое HTML-сообщение с задачей дня."""
    streak_label = pluralize_days(streak_days) if streak_days > 0 else '0 дней'
    return (
        f"🔥 <b>Блиц-задача дня для стрика!</b>\n"
        f"Твоя серия: <b>{streak_label}</b>\n\n"
        f"📚 <b>Тема:</b> {blitz['topic']}\n\n"
        f"<b>Вопрос:</b>\n{blitz['question']}\n\n"
        f"<i>Выбери верный вариант ответа кнопкой ниже, чтобы зачесть активность сегодня и сохранить стрик!</i>"
    )


def build_blitz_inline_keyboard(blitz: Dict[str, Any]) -> dict:
    """Формирует инлайн-клавиатуру с вариантами ответа Telegram."""
    blitz_id = blitz['id']
    keyboard = []
    
    # Буквенные маркеры вариантов
    letters = ['A', 'B', 'C', 'D', 'E']
    for idx, opt_text in enumerate(blitz['options']):
        letter = letters[idx] if idx < len(letters) else str(idx + 1)
        btn_text = f"{letter}) {opt_text}"
        callback_data = f"blitz_ans:{blitz_id}:{idx}"
        keyboard.append([{'text': btn_text, 'callback_data': callback_data}])

    return {'inline_keyboard': keyboard}


def check_blitz_answer(user: User, blitz_id: str, selected_idx: int) -> Dict[str, Any]:
    """
    Проверяет выбранный ответ, обновляет стрик, начисляет опыт и ачивки.
    """
    blitz = get_blitz_by_id(blitz_id)
    if not blitz:
        return {'success': False, 'message': 'Задача не найдена.'}

    is_correct = (selected_idx == blitz['correct_idx'])
    explanation = blitz.get('explanation', '')

    student = getattr(user, 'student_profile', None) or Student.query.filter_by(user_id=user.id).first()
    if not student:
        return {
            'success': False,
            'is_correct': is_correct,
            'message': 'Профиль ученика не найден в базе BooStudy.'
        }

    streak_info_before = get_student_streak_info(student)
    already_active_today = streak_info_before.get('is_active_today', False)

    if not is_correct:
        return {
            'success': True,
            'is_correct': False,
            'blitz_id': blitz_id,
            'message': (
                "❌ <b>Не совсем так!</b>\n\n"
                "Попробуй ещё раз подумать над вопросом или выбери другой вариант. Твой стрик ждёт!"
            )
        }

    # Ответ ВЕРНЫЙ!
    streak_incremented = update_student_streak(student, commit=False)
    xp_awarded = 10
    add_xp_to_student(student, xp_awarded, commit=False)
    check_and_grant_dynamic_achievements(student, commit=False)
    db.session.commit()

    streak_info_after = get_student_streak_info(student)
    curr_streak = streak_info_after.get('streak_days', student.streak_days or 1)
    streak_word = pluralize_days(curr_streak)

    if already_active_today:
        msg = (
            f"🎉 <b>ВЕРНО! Отличный ответ!</b>\n\n"
            f"💡 <i>Пояснение:</i> {explanation}\n\n"
            f"⚡ <b>+{xp_awarded} XP</b> начислено за решение задачи дня.\n"
            f"🔥 Твоя серия: <b>{streak_word}</b> (активность на сегодня уже была зачтена ранее)!"
        )
    else:
        msg = (
            f"🎉 <b>ВЕРНО! Супер!</b>\n\n"
            f"💡 <i>Пояснение:</i> {explanation}\n\n"
            f"🔥 <b>Стрик сохранён и продлён:</b> {streak_word} подряд!\n"
            f"⚡ <b>+{xp_awarded} XP</b> начислено в твой профиль BooStudy!"
        )

    return {
        'success': True,
        'is_correct': True,
        'blitz_id': blitz_id,
        'streak_days': curr_streak,
        'xp_awarded': xp_awarded,
        'message': msg
    }


def send_daily_blitz_to_student(student: Student, force: bool = False) -> bool:
    """
    Отправляет задачу дня конкретному ученику в Telegram, если у него есть привязанный аккаунт.
    Если force=False, отправляет только если ученик ещё не проявлял активности сегодня.
    """
    if not student or not student.user_id:
        return False

    user = User.query.get(student.user_id)
    if not user:
        return False

    # Получаем chat_id
    profile = getattr(user, 'profile', None)
    chat_id = getattr(user, 'telegram_chat_id', None) or getattr(user, 'telegram_id', None)
    if not chat_id and profile:
        chat_id = getattr(profile, 'telegram_chat_id', None) or getattr(profile, 'telegram_id', None)

    if not chat_id:
        return False

    # Если уже активен сегодня и не форсируем — не спамим
    streak_info = get_student_streak_info(student)
    if not force and streak_info.get('is_active_today'):
        return False

    blitz = get_daily_blitz()
    text_msg = format_blitz_message(blitz, streak_days=int(student.streak_days or 0))
    markup = build_blitz_inline_keyboard(blitz)

    from app.telegram.notifications import send_telegram_message
    res = send_telegram_message(
        chat_id=int(chat_id),
        text_body=text_msg,
        parse_mode='HTML',
        reply_markup=markup
    )
    return bool(res)


def broadcast_daily_blitz_reminders(force: bool = False) -> int:
    """
    Рассылает задачу дня всем ученикам, у которых привязан Telegram и которые ещё не были активны сегодня.
    Возвращает количество успешно отправленных сообщений.
    """
    students = Student.query.filter(Student.user_id.isnot(None)).all()
    count = 0
    for st in students:
        try:
            if send_daily_blitz_to_student(st, force=force):
                count += 1
        except Exception as e:
            logger.error("Failed to send daily blitz to student_id=%s: %s", getattr(st, 'student_id', None), e)
    return count

