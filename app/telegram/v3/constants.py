"""Constants and configuration defaults for BooStudy Bot V3."""
from __future__ import annotations

# Callback data prefix
CB_PREFIX = "v3"

# Domains
DOMAIN_NAV = "nav"
DOMAIN_CONTEXT = "ctx"
DOMAIN_STUDENT = "stu"
DOMAIN_TEACHER = "tch"
DOMAIN_PARENT = "par"
DOMAIN_ADMIN = "adm"
DOMAIN_CREATOR = "cre"
DOMAIN_SETTINGS = "set"
DOMAIN_PREVIEW = "preview"
DOMAIN_BROADCAST = "bc"

# Pagination defaults
PAGE_SIZE_HW = 4
PAGE_SIZE_QUEUE = 4
PAGE_SIZE_STUDENTS = 5
PAGE_SIZE_USERS = 5

# Human readable roles
ROLE_TITLES: dict[str, str] = {
    "student": "Ученик",
    "teacher": "Преподаватель",
    "tutor": "Преподаватель-тьютор",
    "parent": "Родитель",
    "admin": "Администратор",
    "chief_admin": "Главный администратор",
    "creator": "Создатель",
    "tester": "Тестировщик",
    "chief_tester": "Ведущий тестировщик",
}

ROLE_EMOJIS: dict[str, str] = {
    "student": "🎓",
    "teacher": "👨‍🏫",
    "tutor": "👨‍🏫",
    "parent": "👨‍👩‍👧",
    "admin": "⚙️",
    "chief_admin": "🛠️",
    "creator": "👑",
    "tester": "🧪",
    "chief_tester": "🧪",
}

# Bot commands
CMD_START = "start"
CMD_MENU = "menu"
CMD_HELP = "help"
CMD_SETTINGS = "settings"
CMD_CANCEL = "cancel"
CMD_ROLE = "role"
CMD_UNLINK = "unlink"
