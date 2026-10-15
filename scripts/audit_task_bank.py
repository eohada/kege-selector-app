"""Read-only inventory of task-bank completeness and media references."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def classify(url: str) -> str:
    value = str(url or '').strip()
    if not value:
        return 'empty'
    if value.startswith('data:'):
        return 'embedded'
    if value.startswith('/storage/google-drive/'):
        return 'drive'
    if value.startswith('/attachments/'):
        return 'local_attachment'
    if value.startswith('/'):
        return 'relative_site'
    parsed = urlsplit(value)
    return 'external:' + (parsed.hostname or 'unknown') if parsed.scheme in ('http', 'https') else 'relative_unknown'


def inventory():
    from app import create_app
    from core.db_models import Course, TaskSolution, Tasks, db

    result = {}
    with create_app().app_context():
        solutions = {task_id for (task_id,) in db.session.query(TaskSolution.task_id).all()}
        for course in Course.query.order_by(Course.id).all():
            counts = Counter()
            media = Counter()
            for task in Tasks.query.filter_by(course_id=course.id).yield_per(100):
                counts['total'] += 1
                counts['active'] += bool(task.is_active)
                counts['answered'] += bool((task.answer or '').strip())
                counts['with_solution'] += task.task_id in solutions
                counts['with_hints'] += bool(task.hints)
                counts['source_named'] += bool(task.source_name)
                counts['source_keyed'] += bool(task.source_key)
                counts['with_source_year'] += task.source_year is not None
                counts['with_exam_number'] += task.task_number > 0
                counts['needs_answer'] += task.ingest_status == 'needs_answer'
                counts['mathml_prefix_remaining'] += '<m:math' in task.content_html
                counts['mfenced_remaining'] += '<mfenced' in task.content_html
                counts['empty_condition'] += not bool(BeautifulSoup(task.content_html or '', 'html.parser').get_text(' ', strip=True))
                try:
                    attachments = json.loads(task.attached_files or '[]')
                    if not isinstance(attachments, list):
                        raise ValueError('Attachment data is not an array')
                except (json.JSONDecodeError, ValueError):
                    counts['invalid_attachments'] += 1
                    attachments = []
                for entry in attachments:
                    if not isinstance(entry, dict):
                        counts['invalid_attachment_entry'] += 1
                        continue
                    media['attachment:' + classify(entry.get('download_url') or entry.get('path') or entry.get('url'))] += 1
                soup = BeautifulSoup(task.content_html or '', 'html.parser')
                for tag in soup.find_all(['img', 'source', 'video', 'audio']):
                    media['inline:' + classify(tag.get('src') or '')] += 1
            result[course.slug] = {'title': course.title, 'counts': dict(counts), 'media': dict(media)}
        result['_total'] = sum(item['counts'].get('total', 0) for key, item in result.items() if key != '_total')
    return result


if __name__ == '__main__':
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
