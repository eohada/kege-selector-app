"""
Тексты авто-активности (присутствия): пулы фраз по сценарию + фиксированный «техно-магия» для создателя.
"""
from __future__ import annotations

import random
from typing import Tuple

TECHNO_MAGIC_KEY = "creator_techno_magic"
TECHNO_MAGIC_TEXT = "Творит техно-магию для вас"


def _pick(*phrases: str) -> str:
    return random.choice(phrases)


def _techno_magic_enabled(user) -> bool:
    try:
        if not getattr(user, "is_creator", lambda: False)():
            return False
        prof = getattr(user, "profile", None)
        return bool(getattr(prof, "presence_techno_magic_enabled", False))
    except Exception:
        return False


def resolve_presence_activity(user, endpoint: str, path: str) -> Tuple[str, str]:
    """
    Возвращает (presence_activity_key, presence_activity_text).
    """
    ep = endpoint or ""
    p = path or ""

    if _techno_magic_enabled(user):
        return TECHNO_MAGIC_KEY, TECHNO_MAGIC_TEXT

    # --- Пулы по сценариям (игривый тон) ---

    # Теория / библиотека (путь)
    if p.startswith("/theory/"):
        if user.is_student():
            return "theory_study", _pick(
                "Впитывает теорию словно губка",
                "Читает конспект и кивает монитору",
                "В theory mode: не беспокоить",
            )
        if user.is_creator() or user.is_tutor() or user.is_content_maker():
            return "theory_editor", _pick(
                "Лепит теорию из цифрового пластилина",
                "Собирает блок теории, как пазл",
                "Работает в блоке теории — осторожно, горячо",
            )
        return "theory_browse", _pick(
            "Просматривает библиотеку теории",
            "Шарится по разделам теории",
        )

    if p.startswith("/library/"):
        if user.is_student():
            return "theory_study", _pick(
                "Впитывает теорию словно губка",
                "Копается в материалах библиотеки",
            )
        return "theory_browse", _pick(
            "Просматривает библиотеку",
            "Ищет жемчужину в материалах",
        )

    # Теория по endpoint
    if ep.startswith("theory."):
        if "edit" in ep or "create" in ep or "manage" in ep or p.endswith("/theory/new"):
            if user.is_creator() or user.is_tutor() or user.is_content_maker():
                return "theory_editor", _pick(
                    "Лепит теорию из цифрового пластилина",
                    "Создаёт теоретический блок - с задором и смыслом",
                )
            return "theory_open", _pick(
                "Открывает теоретический блок",
                "Вчитывается в теорию",
            )
        if user.is_student():
            return "theory_study", _pick(
                "Впитывает теорию словно губка",
                "Изучает теорию всерьёз (и немного в шутку)",
            )
        return "theory_browse", _pick("Просматривает теорию", "Листает теорию")

    # Уроки
    if ep.startswith("lessons."):
        if "classwork" in ep or "homework" in ep:
            if user.is_student():
                return "lesson_work", _pick(
                    "В бою с задачей - пока задача побеждает...",
                    "Решает задачу методом упорства",
                    "Думает так сильно, что слышен шум процессора",
                )
            return "lesson_lead", _pick(
                "Держит урок на коротком поводке",
                "Ведёт занятие и не даёт скуке победить",
                "Проверяет работы и мысленно ставит лайки",
            )
        if user.is_tutor() or user.is_creator():
            return "lesson_manage", _pick(
                "Управляет уроками и материалами",
                "Раскладывает уроки по полочкам",
            )
        return "lesson_open", _pick("На странице урока", "Смотрит материалы урока")

    # Работы / задания
    if ep.startswith("assignments."):
        if user.is_student():
            return "assignment_solve", _pick(
                "Выполняет домашнее задание",
                "Бьётся с ДЗ - пока оно не сдаётся",
                "Пишет решение и надеется на лучшее",
            )
        if ep in (
            "assignments.assignment_create",
            "assignments.assignment_edit",
            "assignments.assignment_add_tasks",
        ):
            return "assignment_compose", _pick(
                "Собирает задание как конструктор LEGO",
                "Пишет условия, от которых не уйти без мозгов",
                "Куёт новые работы в цифровой кузне",
            )
        return "assignment_review", _pick(
            "Проверяет и оценивает работы",
            "Разбирает ДЗ с лупой и чашкой кофе",
            "Читает ответы учеников и хмурится вдумчиво",
        )

    # Тренажёр
    if ep.startswith("trainer."):
        if user.is_student():
            return "trainer_practice", _pick(
                "Фармит скилл в тренажёре",
                "Прогоняет задачи на репите",
                "Тренируется, пока задачи не начнут бояться",
            )
        return "trainer_config", _pick(
            "Настраивает тренажёр для учеников",
            "Крутит настройки тренажёра",
        )

    if ep.startswith("task_generator."):
        return "task_generate", _pick(
            "Генерирует новые задания",
            "Заставляет генератор пыхтеть",
        )

    # Расписание
    if ep.startswith("schedule."):
        if user.is_student():
            return "schedule_student", _pick(
                "Выясняет, когда жить и когда учиться",
                "Листает календарь в поиске свободного окна",
                "Сверяет расписание с реальностью (пока реальность побеждает...)",
            )
        return "schedule_teacher", _pick(
            "Раскладывает уроки по полочкам календаря",
            "Играет в тетрис со слотами занятий",
            "Строит график — чтобы все успели и никто не потерялся",
        )

    # Ученики / комнаты / профили
    if ep.startswith("students."):
        if user.is_student():
            if "analytics" in ep or "statistics" in ep:
                return "progress_self", _pick(
                    "Смотрит свой прогресс",
                    "Изучает графики про себя любимого",
                )
            return "student_workspace", _pick(
                "Работает в личном кабинете",
                "Шарится по BooStudy с научным видом",
                "Планирует учёбу и жизнь одновременно",
            )
        if ep in ("students.student_profile", "students.student_info"):
            return "student_watch", _pick(
                "Заглянул в комнату ученика - всё под контролем (наверное)",
                "Смотрит профиль ученика с прищуром наставника",
                "Проверяет, как там дела у подопечного",
            )
        if "analytics" in ep or "statistics" in ep:
            return "progress_review", _pick(
                "Копается в цифрах прогресса ученика",
                "Строит выводы из графиков (надеясь, что они честные)",
                "Анализирует прогресс — с калькулятором в голове",
            )
        return "student_manage", _pick(
            "Работает с профилями учеников",
            "Патрулирует списки учеников",
            "Держит учебный контингент в поле зрения",
        )

    if ep.startswith("notifications."):
        return "notifications", _pick("Просматривает уведомления", "Читает входящие")

    if ep.startswith("courses.") or ep.startswith("groups."):
        if user.is_student():
            return "courses_view", _pick(
                "Изучает структуру курса",
                "Пытается понять, что за модуль следующий",
            )
        return "courses_manage", _pick(
            "Настраивает курсы и группы",
            "Крутит настройки курсов",
        )

    if ep.startswith("billing."):
        return "billing", _pick("Работает с тарифами и оплатами", "Упирается в деньги и подписки")

    if ep.startswith("auth.user_profile"):
        return "profile", _pick("Обновляет профиль", "Шлифует данные профиля")

    if ep.startswith("main.student_dashboard"):
        return "dashboard_student", _pick(
            "Планирует учебные задачи",
            "Расставляет приоритеты как генерал (почти)",
        )
    if ep.startswith("main.dashboard"):
        if user.is_student():
            return "dashboard_student", _pick(
                "Планирует учебные задачи",
                "Смотрит дашборд и строит планы",
            )
        return "dashboard_teacher", _pick(
            "Патрулирует дашборд как диспетчер",
            "Контролирует учебный процесс",
            "Держит метрики на радаре",
        )

    if user.is_student():
        return "active_student", _pick(
            "Изучает платформу и решает задания",
            "На платформе — занят делом (или почти)",
        )
    if user.is_creator() or user.is_tutor() or user.is_content_maker():
        return "active_teacher", _pick(
            "Делает магию, чтобы ученикам было проще",
            "Развивает платформу и помогает ученикам",
            "Тушит учебные пожары и раздаёт мудрость",
        )
    return "active_default", _pick("Сейчас активен на платформе", "На связи с платформой")
