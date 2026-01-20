"""
Реестр прав доступа системы.
Здесь определены все возможные 'рубильники'.
"""

# Категории прав для красивого отображения в UI
PERMISSION_CATEGORIES = {
    'users': 'Управление пользователями',
    'content': 'Управление контентом',
    'system': 'Системные настройки',
    'finance': 'Финансы и статистика',
    'tools': 'Инструменты',
    'design': 'Дизайн и ассеты',
    'groups': 'Группы/классы'
}

# Список всех прав с описанием и категорией
ALL_PERMISSIONS = {
    # Пользователи
    'user.view_list': {'name': 'Просмотр списка пользователей', 'category': 'users'},
    'user.create': {'name': 'Создание пользователей', 'category': 'users'},
    'user.edit': {'name': 'Редактирование пользователей', 'category': 'users'},
    'user.delete': {'name': 'Удаление пользователей', 'category': 'users'},
    'user.manage_roles': {'name': 'Изменение ролей', 'category': 'users'},
    
    # Контент (Уроки, Задания)
    'lesson.create': {'name': 'Создание уроков', 'category': 'content'},
    'lesson.edit': {'name': 'Редактирование уроков', 'category': 'content'},
    'lesson.delete': {'name': 'Удаление уроков', 'category': 'content'},
    'plan.view': {'name': 'Просмотр траектории ученика', 'category': 'content'},
    'plan.edit': {'name': 'Редактирование траектории ученика', 'category': 'content'},
    'task.manage': {'name': 'Управление банком заданий', 'category': 'content'},
    'assignment.create': {'name': 'Создание и распределение работ', 'category': 'content'},
    'assignment.grade': {'name': 'Проверка работ', 'category': 'content'},
    'assignment.view': {'name': 'Просмотр работ', 'category': 'content'},

    # Оценки/журнал
    'gradebook.view': {'name': 'Просмотр журнала оценок', 'category': 'finance'},
    'gradebook.edit': {'name': 'Редактирование журнала оценок', 'category': 'finance'},

    # Группы/классы
    'groups.view': {'name': 'Просмотр групп/классов', 'category': 'groups'},
    'groups.manage': {'name': 'Управление группами/классами', 'category': 'groups'},
    
    # Финансы
    'finance.view_stats': {'name': 'Просмотр общей статистики', 'category': 'finance'},
    
    # Дизайн
    'assets.manage': {'name': 'Управление графикой и иконками', 'category': 'design'},
    
    # Инструменты
    'tools.testers': {'name': 'Управление тестировщиками', 'category': 'tools'},
    'tools.schedule': {'name': 'Управление расписанием', 'category': 'tools'},
    
    # Система
    'system.logs': {'name': 'Просмотр логов', 'category': 'system'},
    'system.settings': {'name': 'Настройки системы', 'category': 'system'},
}

# Права по умолчанию для новых ролей (используются при инициализации)
DEFAULT_ROLE_PERMISSIONS = {
    'creator': list(ALL_PERMISSIONS.keys()), # Все права
    'admin': list(ALL_PERMISSIONS.keys()),   # Все права
    'chief_tester': ['tools.testers', 'task.manage', 'user.view_list'],
    'designer': ['assets.manage'],
    'tutor': ['lesson.create', 'lesson.edit', 'plan.view', 'plan.edit', 'gradebook.view', 'gradebook.edit', 'groups.view', 'groups.manage', 'user.view_list', 'tools.schedule', 'task.manage', 'assignment.create', 'assignment.grade', 'assignment.view'],
    'student': ['plan.view', 'gradebook.view', 'assignment.view'],
    'parent': ['plan.view', 'gradebook.view', 'assignment.view'],
    'tester': []
}
