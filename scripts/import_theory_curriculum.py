"""Import the portable EGE informatics theory package into a course.

Examples:
  python scripts/import_theory_curriculum.py --course-id 1 --author-username creator
  python scripts/import_theory_curriculum.py --course-id 1 --publish
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.models import Course, TheoryBlock, TheoryGroup, User
from app.theory.curriculum import import_curriculum, load_curriculum


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт теории ЕГЭ по информатике")
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--file", default=None)
    parser.add_argument("--author-username", default="creator")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        course = Course.query.get(args.course_id)
        if not course:
            parser.error(f"Курс {args.course_id} не найден")
        author = User.query.filter_by(username=args.author_username).first()
        if not author:
            parser.error(f"Пользователь {args.author_username} не найден")
        package = load_curriculum(args.file) if args.file else load_curriculum()
        if args.validate_only:
            print(f"Пакет корректен: групп={len(package['groups'])}, блоков={sum(len(g['blocks']) for g in package['groups'])}")
            return 0
        result = import_curriculum(db, TheoryBlock, TheoryGroup, package, course.id, author.id, args.publish)
        print(f"Импорт завершён: группы={result['groups_created']}, создано блоков={result['blocks_created']}, обновлено={result['blocks_updated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
