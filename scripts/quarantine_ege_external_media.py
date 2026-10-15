"""Hold EGE tasks with images served by third-party websites."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def external_images(html: str) -> list[str]:
    images = []
    for image in BeautifulSoup(html or '', 'html.parser').find_all('img'):
        url = (image.get('src') or '').strip()
        host = (urlsplit(url).hostname or '').lower()
        if host and host not in {'boostudy.ru', 'www.boostudy.ru'}:
            images.append(url)
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-path', type=Path)
    args = parser.parse_args()

    from app import create_app
    from core.db_models import Course, Tasks, db

    with create_app().app_context():
        courses = Course.query.filter(Course.slug.in_(('ege_informatics', 'ege_math_profile'))).all()
        course_ids = [course.id for course in courses]
        candidates = []
        for task in Tasks.query.filter(Tasks.course_id.in_(course_ids), Tasks.is_active.is_(True)).yield_per(100):
            urls = external_images(task.content_html)
            if urls:
                candidates.append((task.task_id, task.ingest_status, task.is_active, urls))
        print(json.dumps({'tasks': len(candidates), 'image_references': sum(len(row[3]) for row in candidates)}, ensure_ascii=False))
        if not args.apply:
            return
        if args.backup_path is None:
            parser.error('--apply requires --backup-path')
        args.backup_path.parent.mkdir(parents=True, exist_ok=True)
        with args.backup_path.open('x', encoding='utf-8') as backup:
            json.dump([{'task_id': task_id, 'ingest_status': status, 'is_active': active, 'images': urls}
                       for task_id, status, active, urls in candidates], backup, ensure_ascii=False, indent=2)
        for task_id, _, _, _ in candidates:
            task = db.session.get(Tasks, task_id)
            task.is_active = False
            task.ingest_status = 'needs_media'
        db.session.commit()
        print(json.dumps({'quarantined': len(candidates)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
