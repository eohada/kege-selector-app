"""
Визуальный аудит платформы (Applitools) по ролям: ученик, преподаватель, родитель, администратор.

Использование:
  1. Создать пак профилей и данные: python scripts/seed_visual_audit_pack.py
  2. Запуск по одной роли:
       python visual_audit.py --role student
       python visual_audit.py --role tutor
       python visual_audit.py --role parent
       python visual_audit.py --role admin
  3. Поочерёдная проверка всех ролей:
       python visual_audit.py --all-roles

Учётные данные берутся из visual_audit_ids.json (после seed) или из переменных окружения:
  VISUAL_AUDIT_LOGIN_USER, VISUAL_AUDIT_LOGIN_PASSWORD (для одной роли).
"""

import os
import sys
import json
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright
from applitools.playwright import Eyes, Target

APPLITOOLS_API_KEY = os.environ.get("APPLITOOLS_API_KEY") or "J8hlf7Mh67bajekkrs100eDYtgwfraBoHS48semxKojoM110"
BASE_URL = os.environ.get("VISUAL_AUDIT_BASE_URL", "https://boostudy.ru").rstrip("/")
IDS_FILE = "visual_audit_ids.json"

# Роли в порядке прохода (--all-roles)
ROLES = ("student", "tutor", "parent", "admin")


def load_audit_ids():
    """Загружает student_id, lesson_id и профили из visual_audit_ids.json (если есть)."""
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        path = base / IDS_FILE
        if path.is_file():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    "student_id": data.get("student_id", 1),
                    "lesson_id": data.get("lesson_id", 1),
                    "profiles": data.get("profiles", {}),
                }
            except Exception as e:
                print(f"Не удалось прочитать {path}: {e}")
    return {"student_id": 1, "lesson_id": 1, "profiles": {}}


def get_paths(student_id: int, lesson_id: int):
    """Список относительных путей для проверки (с подставленными id)."""
    s, l = student_id, lesson_id
    return [
        "/", "/landing", "/index", "/home", "/dashboard", "/student/dashboard",
        "/legal/offer", "/legal/privacy", "/update-plans", "/faq", "/login",
        "/parents/dashboard",
        "/admin", "/admin-audit", "/admin-testers", "/admin-testers/1/edit",
        "/maintenance", "/admin/debug-export", "/admin/tester-entities",
        "/admin/tester-entities/create", "/admin/tester-entities/1/edit",
        "/admin/topics", "/admin/users", "/admin/users/new", "/admin/users/1/edit",
        "/admin/diagnostics", "/admin/permissions",
        "/remote-admin/", "/remote-admin/users", "/remote-admin/users/new",
        "/remote-admin/users/1/edit", "/remote-admin/testers", "/remote-admin/bot",
        "/remote-admin/audit-logs", "/remote-admin/maintenance", "/remote-admin/permissions",
        "/remote-admin/task-formator", "/remote-admin/create-pack",
        "/students", "/student/new",
        f"/student/{s}", f"/student/{s}/edit", f"/student/{s}/plan", f"/student/{s}/gradebook",
        f"/student/{s}/diagnostics", f"/student/{s}/analytics",
        f"/student/{s}/lesson/new", f"/student/{s}/lesson-mode",
        f"/student/{s}/courses", "/courses/1", "/courses/1/edit", "/courses/1/modules/new",
        f"/lesson/{l}/edit", f"/lesson/{l}/homework-tasks", f"/lesson/{l}/classwork-tasks",
        f"/lesson/{l}/exam-tasks", f"/lesson/{l}/manual-create",
        "/reviews/queue", "/reviews/lesson-task/1",
        "/schedule",
        "/templates", "/templates/new", "/templates/1", "/templates/1/edit",
        "/kege-generator", f"/kege-generator/{l}",
        "/assignments", "/assignments/accepted", "/assignments/skipped",
        "/assignments/generator/results", "/assignments/create", "/assignments/1",
        "/submissions", "/submissions/1", "/submissions/1/grade",
        "/billing/plans/public", "/billing/plans", "/billing/subscriptions",
        "/import-data", "/reminders",
        "/groups", "/groups/new", "/groups/1", "/groups/1/edit",
        "/rubrics", "/rubrics/new", "/rubrics/1/edit",
        "/library/materials", "/library/lesson-templates",
        "/onboarding/invites", "/notifications", "/designer/assets", "/trainer",
        "/user/profile",
    ]


def do_login(page, base_url: str, username: str, password: str) -> bool:
    """Выполняет вход. Возвращает True при успехе."""
    if not username or not password:
        print("Вход пропущен: не заданы логин/пароль для этой роли.")
        return False
    login_url = f"{base_url}/login"
    print(f"Вход: {username} @ {login_url}")
    page.goto(login_url)
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    current = page.url.rstrip("/")
    if current.endswith("/login"):
        print("Ошибка входа: остались на странице логина.")
        return False
    print("Вход выполнен успешно.")
    return True


def run_audit_for_role(role: str, headless: bool = False):
    """Один проход аудита под одной ролью."""
    ids = load_audit_ids()
    profiles = ids["profiles"]
    student_id = ids["student_id"]
    lesson_id = ids["lesson_id"]

    login_user = os.environ.get("VISUAL_AUDIT_LOGIN_USER", "")
    login_password = os.environ.get("VISUAL_AUDIT_LOGIN_PASSWORD", "")
    if role and role in profiles:
        login_user = profiles[role].get("username", "")
        login_password = profiles[role].get("password", "")

    paths = get_paths(student_id, lesson_id)
    urls_to_check = [f"{BASE_URL}{p}" for p in paths]

    eyes = Eyes()
    eyes.api_key = APPLITOOLS_API_KEY
    test_name = f"Visual Audit — {role or 'default'}"
    batch_name = "BooStudy Platform"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 1024})

        try:
            eyes.open(page, batch_name, test_name, {"width": 1280, "height": 1024})
            do_login(page, BASE_URL, login_user, login_password)

            for url in urls_to_check:
                print(f"  {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    name = url.replace(BASE_URL, "").strip("/") or "home"
                    eyes.check(Target.window().fully().with_name(name))
                except Exception as e:
                    print(f"    Пропуск: {e}")

            print(f"Аудит для роли «{role or 'default'}» завершён.")
        except Exception as e:
            print(f"Ошибка: {e}")
        finally:
            eyes.close(False)
            browser.close()
            eyes.abort_if_not_closed()


def main():
    parser = argparse.ArgumentParser(description="Визуальный аудит платформы по ролям (Applitools)")
    parser.add_argument("--role", choices=ROLES, help="Запустить аудит под одной ролью")
    parser.add_argument("--all-roles", action="store_true", help="Поочерёдно запустить для всех ролей: ученик, препод, родитель, администратор")
    parser.add_argument("--headless", action="store_true", help="Запуск браузера в фоне")
    args = parser.parse_args()

    if args.all_roles:
        for role in ROLES:
            print("=" * 60)
            print(f"Роль: {role}")
            print("=" * 60)
            run_audit_for_role(role, headless=args.headless)
        print("Проверка всех ролей завершена.")
        return 0

    role = args.role or os.environ.get("VISUAL_AUDIT_ROLE", "")
    if not role and not (os.environ.get("VISUAL_AUDIT_LOGIN_USER") and os.environ.get("VISUAL_AUDIT_LOGIN_PASSWORD")):
        ids = load_audit_ids()
        if ids["profiles"]:
            print("Задайте --role (student|tutor|parent|admin) или --all-roles.")
            print("Либо создайте пак: python scripts/seed_visual_audit_pack.py")
        else:
            print("Задайте VISUAL_AUDIT_LOGIN_USER и VISUAL_AUDIT_LOGIN_PASSWORD или --role / --all-roles.")
        return 1

    run_audit_for_role(role or None, headless=args.headless)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
