"""Загружает полный курс Python для ЕГЭ в банк и библиотеку шаблонов уроков."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app, db
from app.utils.python_ege_curriculum_import import default_archive_path, import_curriculum_archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт полного курса Python для ЕГЭ")
    parser.add_argument("archive", nargs="?", default=str(default_archive_path()), help="Путь к python_ege_complete.zip")
    parser.add_argument("--dry-run", action="store_true", help="Проверить пакет без записи в базу")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        result = import_curriculum_archive(args.archive, db, dry_run=args.dry_run)
    print(
        "python-ege-curriculum: "
        f"создано заданий {result['tasks_created']}, обновлено {result['tasks_updated']}; "
        f"создано шаблонов {result['templates_created']}, обновлено {result['templates_updated']}"
    )


if __name__ == "__main__":
    main()
