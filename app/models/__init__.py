"""
Модели базы данных
Экспортируем модели из core.db_models для удобного импорта
"""
from core.db_models import (
    db,
    Tasks,
    UsageHistory,
    SkippedTasks,
    BlacklistTasks,
    Student,
    StudentTaskStatistics,
    Lesson,
    LessonTask,
    User,
    TaskTemplate,
    TemplateTask,
    Tester,
    AuditLog,
    MaintenanceMode,
    moscow_now,
    MOSCOW_TZ,
    TOMSK_TZ
)

__all__ = [
    'db',
    'Tasks',
    'UsageHistory',
    'SkippedTasks',
    'BlacklistTasks',
    'Student',
    'StudentTaskStatistics',
    'Lesson',
    'LessonTask',
    'User',
    'TaskTemplate',
    'TemplateTask',
    'Tester',
    'AuditLog',
    'MaintenanceMode',
    'moscow_now',
    'MOSCOW_TZ',
    'TOMSK_TZ'
]

