"""
Создаёт локальную тестовую БД (SQLite) и заполняет её паком для визуального аудита.
Файл БД: data/keg_tasks.db

После запуска приложение будет обращаться к этой БД, если переменная DATABASE_URL
не задана (не задавайте её в .env для локальной разработки/тестов).

Запуск:
  python scripts/setup_local_test_db.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for key in ("DATABASE_URL", "DATABASE_EXTERNAL_URL", "POSTGRES_URL"):
    os.environ.pop(key, None)

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
data_dir = os.path.join(root_dir, "data")
os.makedirs(data_dir, exist_ok=True)

from app import create_app
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "seed_visual_audit_pack",
    os.path.join(root_dir, "scripts", "seed_visual_audit_pack.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_seed = _mod.run_seed

def main():
    app = create_app()
    with app.app_context():
        code = run_seed(app, root_dir=root_dir, write_ids_file=True)
    if code == 0:
        print()
        print("Локальная БД: data/keg_tasks.db")
        print("Чтобы приложение и скрипты использовали её — не задавайте DATABASE_URL в .env.")
        print("Запуск приложения:  flask run   или  python -m flask run")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
