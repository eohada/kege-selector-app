"""Импортирует 150 черновых шаблонов работ Python для ЕГЭ."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app, db
from app.utils.python_ege_templates_import import default_package_path, import_templates_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт шаблонов Python для ЕГЭ")
    parser.add_argument("package", nargs="?", default=str(default_package_path()))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        attachment_root = (
            app.config.get("TASK_ATTACHMENTS_ROOT")
            or str(Path(app.root_path) / "uploads" / "task_attachments")
        )
        result = import_templates_file(
            args.package,
            db,
            attachment_root=attachment_root,
            dry_run=args.dry_run,
        )
    print(
        "python-ege-templates: "
        f"обновлено заданий {result['tasks_updated']}, создано {result['tasks_created']}; "
        f"обновлено шаблонов {result['templates_updated']}, создано {result['templates_created']}"
    )


if __name__ == "__main__":
    main()
