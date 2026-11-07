"""Centralized notification type definitions and registry for BooStudy Telegram ecosystem.

Provides strict metadata for all notification kinds, supported roles, defaults,
opt-out permissions, and sample payloads for synthetic preview.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class NotificationCategory:
    LESSONS = "lessons"
    HOMEWORK = "homework"
    BILLING = "billing"
    FAMILY = "family"
    GENERAL = "general"
    SYSTEM = "system"
    BROADCAST = "broadcast"

    ALL = (LESSONS, HOMEWORK, BILLING, FAMILY, GENERAL, SYSTEM, BROADCAST)


CATEGORY_TITLES = {
    NotificationCategory.LESSONS: "📅 Занятия и расписание",
    NotificationCategory.HOMEWORK: "📝 Домашние задания",
    NotificationCategory.BILLING: "💳 Баланс и занятия",
    NotificationCategory.FAMILY: "👨‍👩‍👦 Семья и связки",
    NotificationCategory.GENERAL: "⭐ Общее и дайджесты",
    NotificationCategory.SYSTEM: "🚨 Системные оповещения",
    NotificationCategory.BROADCAST: "📢 Объявления платформы",
}

CATEGORY_ICONS = {
    NotificationCategory.LESSONS: "📅",
    NotificationCategory.HOMEWORK: "📝",
    NotificationCategory.BILLING: "💳",
    NotificationCategory.FAMILY: "👨‍👩‍👦",
    NotificationCategory.GENERAL: "⭐",
    NotificationCategory.SYSTEM: "🚨",
    NotificationCategory.BROADCAST: "📢",
}


@dataclass(frozen=True)
class NotificationTypeDefinition:
    kind: str
    title: str
    category: str
    description: str
    supported_roles: tuple[str, ...]
    default_enabled: dict[str, bool] = field(default_factory=dict)
    allow_opt_out: bool = True
    priority: str = "normal"  # high, normal, low
    bypass_quiet_hours: bool = False
    batchable: bool = False
    status: str = "active"  # active, deprecated, retired
    sample_payload: dict[str, Any] = field(default_factory=dict)

    def is_enabled_by_default(self, role: str) -> bool:
        if self.status == "retired":
            return False
        return self.default_enabled.get(role, True)


class NotificationTypeRegistry:
    """Registry maintaining all platform notification types."""

    _types: dict[str, NotificationTypeDefinition] = {}
    _ALIASES: dict[str, str] = {
        "achievement_unlocked": "achievement",
    }

    @classmethod
    def register(cls, definition: NotificationTypeDefinition) -> None:
        cls._types[definition.kind] = definition

    @classmethod
    def get(cls, kind: str) -> Optional[NotificationTypeDefinition]:
        canonical = cls._ALIASES.get(kind, kind)
        return cls._types.get(canonical)

    @classmethod
    def list_all(cls) -> list[NotificationTypeDefinition]:
        return list(cls._types.values())

    @classmethod
    def list_active(cls) -> list[NotificationTypeDefinition]:
        return [t for t in cls._types.values() if t.status == "active"]

    @classmethod
    def list_for_role(cls, role: str) -> list[NotificationTypeDefinition]:
        role_norm = str(role).lower().strip()
        return [
            t for t in cls._types.values()
            if t.status == "active" and role_norm in t.supported_roles
        ]

    @classmethod
    def list_categories_for_role(cls, role: str) -> list[str]:
        role_norm = str(role).lower().strip()
        seen = []
        for cat in NotificationCategory.ALL:
            for t in cls._types.values():
                if t.status == "active" and role_norm in t.supported_roles and t.category == cat:
                    seen.append(cat)
                    break
        return seen

    @classmethod
    def list_for_role_and_category(cls, role: str, category: str) -> list[NotificationTypeDefinition]:
        role_norm = str(role).lower().strip()
        return [
            t for t in cls._types.values()
            if t.status == "active" and role_norm in t.supported_roles and t.category == category
        ]

    @classmethod
    def is_default_enabled(cls, kind: str, role: str) -> bool:
        canonical = cls._ALIASES.get(kind, kind)
        item = cls._types.get(canonical)
        if not item:
            return True
        return item.is_enabled_by_default(role)

    @classmethod
    def get_sample_meta(cls, kind: str, role: str) -> dict[str, Any]:
        canonical = cls._ALIASES.get(kind, kind)
        item = cls._types.get(canonical)
        if not item:
            return {"recipient_role": role}
        res = dict(item.sample_payload)
        res["recipient_role"] = role
        return res


# Register canonical notifications

# --- 1. SYSTEM & OPERATIONAL ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="system_critical_error",
        title="Критическая ошибка системы",
        category=NotificationCategory.SYSTEM,
        description="Сбои в критических подсистемах (LiveKit WebRTC, биллинг, БД)",
        supported_roles=("creator", "admin"),
        default_enabled={"creator": True, "admin": True},
        allow_opt_out=False,
        priority="high",
        bypass_quiet_hours=True,
        sample_payload={
            "service": "LiveKit WebRTC Server",
            "error_text": "LiveKit WebRTC Server heartbeat missed: node-eu-1 unreachable",
            "link_url": "https://boostudy.ru/admin/status",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="operational_alert",
        title="Операционный алерт",
        category=NotificationCategory.SYSTEM,
        description="Операционные предупреждения (длина очереди Outbox, хранилище)",
        supported_roles=("creator", "admin"),
        default_enabled={"creator": True, "admin": True},
        allow_opt_out=False,
        priority="high",
        bypass_quiet_hours=True,
        sample_payload={
            "component": "Outbox Dispatcher",
            "alert_text": "Длина очереди Outbox превысила порог: 28 сообщений",
            "link_url": "https://boostudy.ru/admin/status",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="system_errors",
        title="Системная ошибка сервисов",
        category=NotificationCategory.SYSTEM,
        description="Ошибки воркеров фоновых задач Celery и очередей",
        supported_roles=("creator", "admin"),
        default_enabled={"creator": True, "admin": True},
        allow_opt_out=False,
        priority="high",
        bypass_quiet_hours=True,
        sample_payload={
            "error_text": "Воркер Celery tasks.worker_default завершился аварийно (SIGTERM)",
            "link_url": "https://boostudy.ru/admin/status",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_reminder_response",
        title="Отклик на напоминание об уроке",
        category=NotificationCategory.SYSTEM,
        description="Отчет о подтверждении или отклонении напоминания учеником",
        supported_roles=("creator", "admin"),
        default_enabled={"creator": True, "admin": True},
        allow_opt_out=True,
        sample_payload={
            "student_name": "Иван Смирнов",
            "response": "Подтвердил присутствие на уроке по КЕГЭ №24",
            "subject": "Информатика КЕГЭ",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="bug_report_reply",
        title="Ответ службы поддержки",
        category=NotificationCategory.SYSTEM,
        description="Ответ команды на сообщение об ошибке или вопрос",
        supported_roles=("student", "teacher", "parent", "admin", "creator"),
        default_enabled={"student": True, "teacher": True, "parent": True, "admin": True, "creator": True},
        allow_opt_out=True,
        bypass_quiet_hours=True,
        sample_payload={
            "ticket_id": "BUG-104",
            "reply_text": "Проблема с загрузкой вложений в ДЗ успешно устранена.",
            "link_url": "https://boostudy.ru/support/tickets/104",
        },
    )
)

# --- 2. LESSONS & SCHEDULE ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_scheduled",
        title="Назначение урока",
        category=NotificationCategory.LESSONS,
        description="Уведомление о новом назначенном уроке в расписании",
        supported_roles=("student", "teacher", "parent"),
        default_enabled={"student": True, "teacher": True, "parent": True},
        batchable=True,
        sample_payload={
            "subject": "Информатика КЕГЭ: Рекурсия и ДП",
            "teacher_name": "Михаил Викторович",
            "student_name": "Иван Смирнов",
            "lesson_date": "2026-11-05T18:00:00Z",
            "start_time": "2026-11-05T18:00:00Z",
            "link_url": "https://boostudy.ru/schedule",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_batch_scheduled",
        title="Пакетное назначение занятий",
        category=NotificationCategory.LESSONS,
        description="Единая карточка при назначении от 3 занятий одновременно",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        batchable=False,
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "teacher_name": "Михаил Викторович",
            "lessons_count": 5,
            "items_preview": [
                "5 ноября (вт) в 18:00 МСК — Рекурсивные алгоритмы",
                "7 ноября (чт) в 18:00 МСК — Деревья поиска",
                "12 ноября (вт) в 18:00 МСК — Динамическое программирование",
                "14 ноября (чт) в 18:00 МСК — Теория игр (19-21)",
                "19 ноября (вт) в 18:00 МСК — Разбор сложных прототипов",
            ],
            "link_url": "https://boostudy.ru/schedule",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_rescheduled",
        title="Перенос урока",
        category=NotificationCategory.LESSONS,
        description="Оповещение об изменении времени или даты урока",
        supported_roles=("student", "teacher", "parent"),
        default_enabled={"student": True, "teacher": True, "parent": True},
        bypass_quiet_hours=True,
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "teacher_name": "Михаил Викторович",
            "student_name": "Иван Смирнов",
            "old_start_time": "2026-11-05T18:00:00Z",
            "start_time": "2026-11-06T19:00:00Z",
            "link_url": "https://boostudy.ru/schedule",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_cancelled",
        title="Отмена урока",
        category=NotificationCategory.LESSONS,
        description="Оповещение об отмене занятия с указанием причины",
        supported_roles=("student", "teacher", "parent"),
        default_enabled={"student": True, "teacher": True, "parent": True},
        bypass_quiet_hours=True,
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "teacher_name": "Михаил Викторович",
            "student_name": "Иван Смирнов",
            "start_time": "2026-11-05T18:00:00Z",
            "reason": "Перенос по согласованию сторон",
            "link_url": "https://boostudy.ru/schedule",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_reminder",
        title="Напоминание об уроке",
        category=NotificationCategory.LESSONS,
        description="Напоминание за 15 минут до начала занятия с прямой ссылкой",
        supported_roles=("student", "teacher", "parent"),
        default_enabled={"student": True, "teacher": True, "parent": True},
        bypass_quiet_hours=True,
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "teacher_name": "Михаил Викторович",
            "student_name": "Иван Смирнов",
            "minutes_left": 15,
            "start_time": "2026-11-05T18:00:00Z",
            "room_url": "https://boostudy.ru/room/lesson-42",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_started",
        title="Начало урока (преподаватель)",
        category=NotificationCategory.LESSONS,
        description="Подсказка преподавателю о начале занятия со ссылкой",
        supported_roles=("teacher",),
        default_enabled={"teacher": True},
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "student_name": "Иван Смирнов",
            "lesson_id": 42,
            "room_url": "https://boostudy.ru/room/lesson-42",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_started_student",
        title="Приглашение в классную комнату",
        category=NotificationCategory.LESSONS,
        description="Приглашение ученику войти в класс, когда учитель начал урок",
        supported_roles=("student",),
        default_enabled={"student": True},
        bypass_quiet_hours=True,
        sample_payload={
            "subject": "Информатика КЕГЭ",
            "teacher_name": "Михаил Викторович",
            "room_url": "https://boostudy.ru/room/lesson-42",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_finished",
        title="Завершение урока (заметка ДЗ)",
        category=NotificationCategory.LESSONS,
        description="Запрос преподавателю о фиксации домашнего задания после урока",
        supported_roles=("teacher",),
        default_enabled={"teacher": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "lesson_id": 42,
        },
    )
)

# --- 3. HOMEWORK ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="assignment_assigned",
        title="Новое домашнее задание",
        category=NotificationCategory.HOMEWORK,
        description="Уведомление о выданном домашнем задании и дедлайне",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "assignment_title": "Задание №26: Обработка больших массивов данных",
            "task_id": 55,
            "deadline": "2026-11-08T23:59:00Z",
            "link_url": "https://boostudy.ru/homework/55",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="teacher_homework_submitted",
        title="Ученик сдал домашнее задание",
        category=NotificationCategory.HOMEWORK,
        description="Уведомление преподавателю о поступившей на проверку работе",
        supported_roles=("teacher",),
        default_enabled={"teacher": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "assignment_title": "Задание 24 КЕГЭ: Текстовые файлы",
            "submission_id": 101,
            "link_url": "https://boostudy.ru/teacher/review/101",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="homework_submitted",
        title="Ребёнок сдал работу",
        category=NotificationCategory.HOMEWORK,
        description="Оповещение родителю о сдаче работы ребёнком (для ученика отключается)",
        supported_roles=("parent",),
        default_enabled={"parent": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "assignment_title": "Задание 24 КЕГЭ",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="homework_checked",
        title="Домашнее задание проверено",
        category=NotificationCategory.HOMEWORK,
        description="Результаты проверки: оценка, баллы и комментарий преподавателя",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "assignment_title": "Задание №24 КЕГЭ",
            "score": "100%",
            "comment": "Отличное эффективное решение через скользящее окно!",
            "task_id": 55,
            "link_url": "https://boostudy.ru/homework/55",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="homework_returned",
        title="Работа возвращена на доработку",
        category=NotificationCategory.HOMEWORK,
        description="Работа требует правок с пояснениями от преподавателя",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "assignment_title": "Задание №27 КЕГЭ",
            "reason": "Программа не укладывается по памяти для файла Б (максимум 5 МБ)",
            "task_id": 56,
            "link_url": "https://boostudy.ru/homework/56",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="assignment_deadline",
        title="Приближение дедлайна ДЗ",
        category=NotificationCategory.HOMEWORK,
        description="Предупреждение о скором истечении срока сдачи задания",
        supported_roles=("student",),
        default_enabled={"student": True},
        sample_payload={
            "assignment_title": "Пробный вариант КЕГЭ №3",
            "deadline": "2026-11-04T23:59:00Z",
            "task_id": 57,
            "link_url": "https://boostudy.ru/homework/57",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="review_queue",
        title="Очередь работ на проверку",
        category=NotificationCategory.HOMEWORK,
        description="Сводка преподавателю о работах, ожидающих проверки",
        supported_roles=("teacher",),
        default_enabled={"teacher": True},
        sample_payload={
            "pending_count": 3,
            "link_url": "https://boostudy.ru/teacher/review",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="teacher_hw_note_reminder",
        title="Напоминание о заметке к уроку",
        category=NotificationCategory.HOMEWORK,
        description="Напоминание преподавателю зафиксировать домашнее задание",
        supported_roles=("teacher",),
        default_enabled={"teacher": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "lesson_id": 42,
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_comment",
        title="Комментарий к заданию",
        category=NotificationCategory.HOMEWORK,
        description="Новые комментарии преподавателя или ученика к задаче в домашней работе",
        supported_roles=("student", "teacher"),
        default_enabled={"student": True, "teacher": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "assignment_title": "Домашняя работа: Алгоритмы",
            "body": "Обрати внимание на краевой случай при N = 1",
            "link_url": "https://boostudy.ru/homework",
        },
    )
)

# --- 4. BILLING & BALANCES ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="lesson_balance_changed",
        title="Изменение баланса занятий",
        category=NotificationCategory.BILLING,
        description="Пополнение или списание занятий в личном кабинете",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "delta": "+8",
            "lessons_remaining": 10,
            "reason": "Оплата абонемента на 8 занятий",
            "link_url": "https://boostudy.ru/billing",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="low_lessons",
        title="Остаток занятий заканчивается",
        category=NotificationCategory.BILLING,
        description="Предупреждение: осталось 2 или менее оплаченных уроков",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "lessons_remaining": 2,
            "link_url": "https://boostudy.ru/billing",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="package_exhausted",
        title="Пакет занятий завершён",
        category=NotificationCategory.BILLING,
        description="Уведомление об окончании оплаченных уроков",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "lessons_remaining": 0,
            "link_url": "https://boostudy.ru/billing",
        },
    )
)

# --- 5. FAMILY & CONNECTIONS ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="family_link_created",
        title="Запрос на семейную привязку",
        category=NotificationCategory.FAMILY,
        description="Запрос на связывание аккаунтов родителя и ученика",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "parent_name": "Ольга Смирнова",
            "student_name": "Иван Смирнов",
            "link_url": "https://boostudy.ru/family",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="family_link_confirmed",
        title="Семейная привязка подтверждена",
        category=NotificationCategory.FAMILY,
        description="Успешное подтверждение привязки родителя и ученика",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "parent_name": "Ольга Смирнова",
            "student_name": "Иван Смирнов",
            "link_url": "https://boostudy.ru/family",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="family_link_revoked",
        title="Семейная привязка отключена",
        category=NotificationCategory.FAMILY,
        description="Отключение связки между аккаунтами",
        supported_roles=("student", "parent"),
        default_enabled={"student": True, "parent": True},
        sample_payload={
            "parent_name": "Ольга Смирнова",
            "student_name": "Иван Смирнов",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="child_digest",
        title="Еженедельный отчёт по ребёнку",
        category=NotificationCategory.FAMILY,
        description="Сводка для родителей: посещаемость, оценки, статус ДЗ за неделю",
        supported_roles=("parent",),
        default_enabled={"parent": True},
        sample_payload={
            "student_name": "Иван Смирнов",
            "attended_lessons": 2,
            "completed_hw": 2,
            "avg_score": "95%",
            "link_url": "https://boostudy.ru/family",
        },
    )
)

# --- 6. GENERAL & DIGESTS ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="daily_digest",
        title="Утренний дайджест дня",
        category=NotificationCategory.GENERAL,
        description="Расписание и список задач на текущий день (по умолчанию выкл)",
        supported_roles=("student", "teacher"),
        default_enabled={"student": False, "teacher": False},  # opt-in
        sample_payload={
            "lessons_count": 2,
            "hw_pending_count": 1,
            "summary_text": "Сегодня 2 урока: в 16:00 и 18:00 МСК",
            "link_url": "https://boostudy.ru/schedule",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="achievement",
        title="Награды и достижения",
        category=NotificationCategory.GENERAL,
        description="Оповещения об игровых достижениях и учебных сериях",
        supported_roles=("student",),
        default_enabled={"student": True},
        sample_payload={
            "title": "Марафонец кода",
            "description": "5 решённых вариантов КЕГЭ подряд без единой ошибки!",
            "badge_name": "streak_5",
            "link_url": "https://boostudy.ru/achievements",
        },
    )
)

# --- 7. BROADCAST & NEWS ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="news",
        title="Новости платформы",
        category=NotificationCategory.BROADCAST,
        description="Обновления функционала, статьи и анонсы платформы",
        supported_roles=("student", "teacher", "parent", "admin", "creator"),
        default_enabled={"student": True, "teacher": True, "parent": True, "admin": True, "creator": True},
        sample_payload={
            "title": "Новые материалы по информатике КЕГЭ 2026",
            "body": "В каталог добавлены актуальные демонстрационные варианты и видеоразборы заданий 26 и 27.",
            "link_url": "https://boostudy.ru/blog/kege-2026",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="announcement",
        title="Важные объявления платформы",
        category=NotificationCategory.BROADCAST,
        description="Официальные объявления руководства и технические уведомления",
        supported_roles=("student", "teacher", "parent", "admin", "creator"),
        default_enabled={"student": True, "teacher": True, "parent": True, "admin": True, "creator": True},
        sample_payload={
            "title": "Плановое техническое обслуживание",
            "body": "В ночь со вторника на среду с 03:00 до 04:30 МСК сервер будет недоступен в связи с обновлением ядра LiveKit.",
            "link_url": "https://boostudy.ru",
        },
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="broadcast",
        title="Рассылка преподавателя / куратора",
        category=NotificationCategory.BROADCAST,
        description="Персональные объявления от преподавателя для своих учеников",
        supported_roles=("student", "teacher", "parent", "admin", "creator"),
        default_enabled={"student": True, "teacher": True, "parent": True, "admin": True, "creator": True},
        sample_payload={
            "sender_name": "Михаил Викторович",
            "title": "Подготовка к субботнему интенсиву",
            "body": "Прошу всех проверить установку PyCharm и библиотеки sympy перед субботним вебинаром.",
            "link_url": "https://boostudy.ru/homework",
        },
    )
)

# --- RETIRED NOTIFICATIONS (Audited and cleanly decommissioned) ---
NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="new_gradebook_entry",
        title="Новая оценка в журнале (Устарело)",
        category=NotificationCategory.GENERAL,
        description="Выведено из эксплуатации: журнал оценок объединен с карточками заданий",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="subscription_expiring",
        title="Истечение подписки (Устарело)",
        category=NotificationCategory.BILLING,
        description="Выведено из эксплуатации: заменено на баланс занятий (lesson_balance_changed)",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="package_expiring",
        title="Срок пакета (Устарело)",
        category=NotificationCategory.BILLING,
        description="Выведено из эксплуатации: в BooStudy занятия учитываются количеством доступных уроков (low_lessons, package_exhausted), дата истечения отсутствует.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="payment_received",
        title="Оплата получена (Не поддерживается)",
        category=NotificationCategory.BILLING,
        description="Отсутствует внешний платёжный шлюз: покупка пакетов симулируется в кабинете биллинга.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="schedule_conflict",
        title="Конфликт расписания (Синхронный API)",
        category=NotificationCategory.LESSONS,
        description="Коллизии возвращаются как синхронный ответ API (HTTP 409 Conflict); доставка через Outbox не предусмотрена.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="system_announcement",
        title="Системное объявление (Объединено)",
        category=NotificationCategory.BROADCAST,
        description="Объединено с каноническим типом broadcast/announcement.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="user_linked_telegram",
        title="Привязка Telegram (Интерактивно)",
        category=NotificationCategory.GENERAL,
        description="Интерактивный ответ бота на команду /start link_<token>; не является отложенным событием Outbox.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="streak_saved",
        title="Серия сохранена (Не подключено)",
        category=NotificationCategory.GENERAL,
        description="Подсчёт серий ведётся в БД; фоновый генератор уведомлений в Telegram не предусмотрен.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="streak_broken",
        title="Серия сгорела (Не подключено)",
        category=NotificationCategory.GENERAL,
        description="Фоновый крон сгорания стриков активности в текущей версии платформы не предусмотрен.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="parent_weekly_digest",
        title="Еженедельный дайджест (Веб-аналитика)",
        category=NotificationCategory.FAMILY,
        description="Аналитические графики доступны в веб-кабинете; периодический генератор дайджестов для Telegram не предусмотрен.",
        supported_roles=(),
        status="retired",
    )
)

NotificationTypeRegistry.register(
    NotificationTypeDefinition(
        kind="monthly_report",
        title="Месячный отчёт (Веб-аналитика)",
        category=NotificationCategory.GENERAL,
        description="Месячный отчёт формируется в панели администратора веб-платформы; рассылка в Telegram не предусмотрена.",
        supported_roles=(),
        status="retired",
    )
)
