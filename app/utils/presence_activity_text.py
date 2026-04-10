"""
Тексты авто-активности (присутствия): пулы фраз по сценарию + фиксированный «техно-магия» для создателя.
"""
from __future__ import annotations

import random
import re
from typing import Optional, Tuple

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


def _norm_path(raw: str) -> str:
    if not raw:
        return ""
    p = raw.split("?", 1)[0].strip()
    if not p.startswith("/"):
        p = "/" + p.lstrip("/")
    return p.rstrip("/") or "/"


def _resolve_from_path(user, raw_path: str) -> Optional[Tuple[str, str]]:
    """
    Heartbeat /api/presence/ping передаёт только path (без Flask endpoint).
    Без этого у преподавателя/создателя всегда срабатывал fallback active_teacher.
    """
    p = _norm_path(raw_path)
    if not p or p == "/":
        return None

    if p == "/theory" or p.startswith("/theory/"):
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

    if p.startswith("/schedule"):
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

    if p.startswith("/assignments"):
        if user.is_student():
            return "assignment_solve", _pick(
                "Выполняет домашнее задание",
                "Бьётся с ДЗ — пока оно не сдаётся",
                "Пишет решение и надеется на лучшее",
            )
        if (
            p.startswith("/assignments/create")
            or re.search(r"/assignments/\d+/edit(?:/|$)", p)
            or re.search(r"/assignments/\d+/tasks(?:/|$)", p)
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

    if p.startswith("/submissions"):
        if user.is_student():
            return "assignment_solve", _pick(
                "Выполняет домашнее задание",
                "Бьётся с ДЗ — пока оно не сдаётся",
                "Пишет решение и надеется на лучшее",
            )
        return "assignment_review", _pick(
            "Проверяет и оценивает работы",
            "Разбирает ДЗ с лупой и чашкой кофе",
            "Читает ответы учеников и хмурится вдумчиво",
        )

    # Журнал проверок / ручные ревью — путь НЕ содержит /lesson/, поэтому нельзя прятать это внутри блока lesson ниже.
    if p.startswith("/reviews/") or p.startswith("/tutor/reviews"):
        if user.is_student():
            return "assignment_solve", _pick(
                "Смотрит статус своих работ",
                "Проверяет, что там с проверкой",
            )
        return "assignment_review", _pick(
            "Работает в очереди проверок",
            "Разгребает гору работ на проверку",
            "Выставляет оценки и пишет комментарии",
        )

    if "/lesson/" in p or p.startswith("/lesson/"):
        if (
            "classwork" in p
            or "homework" in p
            or "exam-tasks" in p
            or "/classroom" in p
        ):
            if user.is_student():
                return "lesson_work", _pick(
                    "В бою с задачей — пока задача побеждает...",
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

    if p == "/students" or p.startswith("/students/"):
        if user.is_student():
            return "student_workspace", _pick(
                "Работает в личном кабинете",
                "Шарится по BooStudy с научным видом",
            )
        return "student_manage", _pick(
            "Работает с профилями учеников",
            "Патрулирует списки учеников",
            "Держит учебный контингент в поле зрения",
        )

    if p.startswith("/student/new"):
        if not user.is_student():
            return "student_manage", _pick(
                "Работает с профилями учеников",
                "Патрулирует списки учеников",
            )
        return None

    m_st = re.match(r"^/student/(\d+)(?:/(.+))?$", p)
    if m_st:
        rest = (m_st.group(2) or "").strip("/")
        if user.is_student():
            if rest.startswith("analytics") or rest.startswith("statistics"):
                return "progress_self", _pick(
                    "Смотрит свой прогресс",
                    "Изучает графики про себя любимого",
                )
            return "student_workspace", _pick(
                "Работает в личном кабинете",
                "Шарится по BooStudy с научным видом",
                "Планирует учёбу и жизнь одновременно",
            )
        if not rest:
            return "student_watch", _pick(
                "Заглянул в комнату ученика — всё под контролем (наверное)",
                "Смотрит профиль ученика с прищуром наставника",
                "Проверяет, как там дела у подопечного",
            )
        if rest.startswith("info"):
            return "student_watch", _pick(
                "Заглянул в комнату ученика — всё под контролем (наверное)",
                "Смотрит профиль ученика с прищуром наставника",
                "Проверяет, как там дела у подопечного",
            )
        if rest.startswith("analytics") or rest.startswith("statistics"):
            return "progress_review", _pick(
                "Копается в цифрах прогресса ученика",
                "Строит выводы из графиков (надеясь, что они честные)",
                "Анализирует прогресс — с калькулятором в голове",
            )
        return "student_watch", _pick(
            "Заглянул в комнату ученика — всё под контролем (наверное)",
            "Смотрит раздел ученика",
            "Проверяет, как там дела у подопечного",
        )

    if p == "/dashboard":
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

    if p.startswith("/student/dashboard"):
        return "dashboard_student", _pick(
            "Планирует учебные задачи",
            "Расставляет приоритеты как генерал (почти)",
        )

    if p.startswith("/user/profile"):
        return "profile", _pick("Обновляет профиль", "Шлифует данные профиля")

    if re.match(r"^/user/\d+$", p):
        return "profile", _pick("Смотрит чужой профиль", "Заглянул на публичную страницу")

    if p.startswith("/trainer"):
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

    if p.startswith("/task-generator"):
        return "task_generate", _pick(
            "Генерирует новые задания",
            "Заставляет генератор пыхтеть",
        )

    if p.startswith("/templates"):
        if user.is_student():
            return "lesson_open", _pick("Смотрит шаблоны", "Заглянул в шаблоны заданий")
        return "templates_manage", _pick(
            "Собирает и правит шаблоны заданий",
            "Крутит библиотеку шаблонов",
            "Настраивает заготовки для уроков",
        )

    if p.startswith("/notifications"):
        return "notifications", _pick("Просматривает уведомления", "Читает входящие")

    if p.startswith("/billing"):
        return "billing", _pick("Работает с тарифами и оплатами", "Упирается в деньги и подписки")

    if p.startswith("/courses") or p.startswith("/groups"):
        if user.is_student():
            return "courses_view", _pick(
                "Изучает структуру курса",
                "Пытается понять, что за модуль следующий",
            )
        return "courses_manage", _pick(
            "Настраивает курсы и группы",
            "Крутит настройки курсов",
        )

    if p.startswith("/chief-tester"):
        return "staff_tools", _pick(
            "Ковыряет кабинет главного тестировщика",
            "Гоняет сценарии и проверки",
            "Ловит баги до того, как они доберутся до учеников",
        )

    if p.startswith("/remote-admin"):
        return "remote_admin", _pick(
            "Управляет платформой из удалённой админки",
            "Крутит ручки в remote-admin",
            "Держит прод под прицелом",
        )

    if p.startswith("/qa/") or p == "/qa":
        return "qa_tools", _pick(
            "Прощупывает платформу в QA-режиме",
            "Гоняет чек-листы качества",
        )

    return None


def resolve_presence_activity(user, endpoint: str, path: str) -> Tuple[str, str]:
    """
    Возвращает (presence_activity_key, presence_activity_text).
    """
    ep = endpoint or ""
    p = path or ""

    if _techno_magic_enabled(user):
        return TECHNO_MAGIC_KEY, TECHNO_MAGIC_TEXT

    path_hit = _resolve_from_path(user, p)
    if path_hit is not None:
        return path_hit

    # --- Дальше — по Flask endpoint (полный запрос, не heartbeat) ---

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

    if ep.startswith("templates."):
        if user.is_student():
            return "lesson_open", _pick("Смотрит шаблоны", "Заглянул в шаблоны заданий")
        return "templates_manage", _pick(
            "Собирает и правит шаблоны заданий",
            "Крутит библиотеку шаблонов",
            "Настраивает заготовки для уроков",
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

    if ep.startswith("chief_tester."):
        return "staff_tools", _pick(
            "Ковыряет кабинет главного тестировщика",
            "Гоняет сценарии и проверки",
            "Ловит баги до того, как они доберутся до учеников",
        )
    if ep.startswith("remote_admin."):
        return "remote_admin", _pick(
            "Управляет платформой из удалённой админки",
            "Крутит ручки в remote-admin",
            "Держит прод под прицелом",
        )
    if ep.startswith("qa."):
        return "qa_tools", _pick(
            "Прощупывает платформу в QA-режиме",
            "Гоняет чек-листы качества",
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
