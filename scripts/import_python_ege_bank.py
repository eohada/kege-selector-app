#!/usr/bin/env python3
"""Загрузка авторского банка Python для ЕГЭ в локальную или серверную БД."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.models import db
from app.utils.python_bank_import import import_package_file, import_foundations_package


def main():
    parser = argparse.ArgumentParser(description="Импорт банка Python для ЕГЭ")
    parser.add_argument("package", nargs="?", default="data/task_banks/python_ege_full.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--foundations", action="store_true", help="Импорт тематического банка без номеров ЕГЭ")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if args.foundations:
            with open(args.package, encoding="utf-8") as handle:
                result = import_foundations_package(json.load(handle), db, dry_run=args.dry_run)
        else:
            result = import_package_file(args.package, db, dry_run=args.dry_run)
        print(f"{result['course_slug']}: создано {result['created']}, обновлено {result['updated']}")
        if args.dry_run:
            print("dry-run: база не изменена")


if __name__ == "__main__":
    main()
