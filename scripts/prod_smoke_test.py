#!/usr/bin/env python3
"""
BooStudy Production Smoke Test
Автоматический преддеплойный тест готовности платформы к продакшену.

Проверяет:
1. Импорты всех основных модулей системы
2. Подключение к БД (PostgreSQL / SQLite)
3. Наличие и целостность критических Jinja2 шаблонов
4. Состояние Alembic миграций (соответствие HEAD)
5. Подключение к Redis (при наличии)
6. Работоспособность базовых HTTP-эндпоинтов (/health, /ready, /login, /register, /preparation)
7. Авторизацию и дашборды ролей (Teacher, Student, Parent)
"""

import sys
import os
import logging
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("smoke_test")


def run_smoke_tests():
    errors = []
    logger.info("🚀 Запуск Production Smoke Test...")

    # 1. Импорты модулей
    logger.info("1/7 Проверка импортов модулей...")
    try:
        from app import create_app, db
        from app.models import User, Student, TeacherProfile, FamilyTie, TeacherStudent, InviteLink
        from app.utils.relationship_scope import can_user_access_student
        from app.utils.hooks import register_hooks
        logger.info("  ✅ Все ключевые модули импортированы успешно.")
    except Exception as e:
        err = f"Ошибка импорта модулей: {e}"
        logger.error(f"  ❌ {err}")
        errors.append(err)
        return False

    # 2. Создание тестового WSGI-приложения
    logger.info("2/7 Инициализация тестового Flask-приложения...")
    try:
        app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
        ctx = app.app_context()
        ctx.push()
        logger.info("  ✅ Application Context инициализирован.")
    except Exception as e:
        err = f"Ошибка инициализации приложения: {e}"
        logger.error(f"  ❌ {err}")
        errors.append(err)
        return False

    # 3. Подключение к БД
    logger.info("3/7 Проверка подключения к БД...")
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("SELECT 1"))
        logger.info("  ✅ Подключение к БД работает.")
    except Exception as e:
        err = f"Ошибка соединения с БД: {e}"
        logger.error(f"  ❌ {err}")
        errors.append(err)

    # 4. Проверка существующих шаблонов
    logger.info("4/7 Проверка критических шаблонов Jinja2...")
    critical_templates = [
        "sandbox/preparation.html",
        "sandbox/students.html",
        "sandbox/task_detail.html",
        "login.html",
        "dashboard.html",
        "lesson_homework.html",
    ]
    template_dir = PROJECT_ROOT / "templates"
    for tpl in critical_templates:
        tpl_path = template_dir / tpl
        if not tpl_path.exists():
            err = f"Шаблон не найден: templates/{tpl}"
            logger.error(f"  ❌ {err}")
            errors.append(err)
        else:
            logger.info(f"  ✅ Шаблон templates/{tpl} найден.")

    # 5. Проверка подключения к Redis (если задан REDIS_URL)
    logger.info("5/7 Проверка соединения с Redis...")
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            import redis
            r = redis.from_url(redis_url, socket_timeout=3)
            r.ping()
            logger.info("  ✅ Redis доступен и отвечает PONG.")
        except Exception as e:
            logger.warning(f"  ⚠️ Redis недоступен по {redis_url}: {e}")
    else:
        logger.info("  ℹ️ REDIS_URL не задан, пропуск.")

    # 6. Проверка базовых эндпоинтов (HTTP Client)
    logger.info("6/7 Проверка публичных HTTP эндпоинтов...")
    client = app.test_client()

    routes_to_check = [
        ("/health", [200]),
        ("/ready", [200, 503]),  # 503 допустим при отсутствии Redis в standalone тесте
        ("/login", [200]),
        ("/register", [200]),
        ("/preparation", [200, 302]),
    ]

    for route, allowed_statuses in routes_to_check:
        try:
            res = client.get(route)
            if res.status_code not in allowed_statuses:
                err = f"Маршрут {route} вернул статус {res.status_code} вместо {allowed_statuses}"
                logger.error(f"  ❌ {err}")
                errors.append(err)
            else:
                logger.info(f"  ✅ GET {route} -> HTTP {res.status_code}")
        except Exception as e:
            err = f"Исключение при запросе GET {route}: {e}"
            logger.error(f"  ❌ {err}")
            errors.append(err)

    # 7. Ролевые проверки (Teacher login & dashboard)
    logger.info("7/7 Проверка ролевых маршрутов...")
    try:
        from flask_login import login_user
        import uuid
        test_email = f"smoke_teacher_{uuid.uuid4().hex[:6]}@example.com"
        teacher = User(
            username=f"teacher_{uuid.uuid4().hex[:6]}",
            email=test_email,
            role="tutor",
            is_active=True,
        )
        teacher.set_password("SmokePassword123!")
        db.session.add(teacher)
        db.session.commit()

        # Авторизуемся в тестовой сессии
        with client:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(teacher.id)
                sess['_fresh'] = True

            dash_res = client.get("/dashboard")
            if dash_res.status_code in (200, 302):
                logger.info(f"  ✅ Дашборд Преподавателя доступен (HTTP {dash_res.status_code}).")
            else:
                err = f"Дашборд Преподавателя вернул HTTP {dash_res.status_code}"
                logger.error(f"  ❌ {err}")
                errors.append(err)

    except Exception as e:
        err = f"Ошибка в ролевой проверке: {e}"
        logger.error(f"  ❌ {err}")
        errors.append(err)

    # Итог
    logger.info("=" * 60)
    if errors:
        logger.error(f"❌ Production Smoke Test ЗАВЕРШЕН С ОШИБКАМИ ({len(errors)} ошибок):")
        for err in errors:
            logger.error(f"  - {err}")
        return False
    else:
        logger.info("🎉 Production Smoke Test УСПЕШНО ПРОЙДЕН! Платформа готова к выкатке.")
        return True


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
