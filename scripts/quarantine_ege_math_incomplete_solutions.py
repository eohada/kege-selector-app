"""Hold profile-math tasks whose imported explanations say the condition is missing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# These exact source cards were inspected after import. Their explanations say
# that formulas or geometry labels are absent, despite the card being marked ready.
TASK_IDS = (
    9987, 10015, 10021, 10126, 10130, 10183, 10196, 10225, 10229,
    10246, 10306, 10407, 10536, 10575, 10610, 10653, 10675, 10710,
    10760, 10787, 10815, 10885, 10974, 11009, 11041, 11116,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-path', type=Path)
    args = parser.parse_args()

    from app import create_app
    from core.db_models import Course, Tasks, db

    with create_app().app_context():
        course = Course.query.filter_by(slug='ege_math_profile').one()
        tasks = Tasks.query.filter(Tasks.course_id == course.id, Tasks.task_id.in_(TASK_IDS)).order_by(Tasks.task_id).all()
        if len(tasks) != len(TASK_IDS):
            raise RuntimeError(f'Expected {len(TASK_IDS)} math tasks, found {len(tasks)}')
        snapshot = [
            {'task_id': task.task_id, 'is_active': task.is_active, 'ingest_status': task.ingest_status}
            for task in tasks
        ]
        print(json.dumps({'review_required': len(tasks), 'active': sum(task.is_active for task in tasks)}, ensure_ascii=False))
        if not args.apply:
            return
        if args.backup_path is None:
            parser.error('--apply requires --backup-path')
        args.backup_path.parent.mkdir(parents=True, exist_ok=True)
        with args.backup_path.open('x', encoding='utf-8') as backup:
            json.dump(snapshot, backup, ensure_ascii=False, indent=2)
        for task in tasks:
            task.is_active = False
            task.ingest_status = 'needs_review'
        db.session.commit()
        print(json.dumps({'quarantined': len(tasks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
