"""Verify that every stored EGE task asset exists in the configured Drive folder."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from app import create_app
    from app.storage.s3_service import storage
    from core.db_models import Course, Tasks

    with create_app().app_context():
        courses = {course.slug: course.id for course in Course.query.filter(Course.slug.in_(['ege_informatics', 'ege_math_profile']))}
        references = defaultdict(set)
        stats = Counter()
        examples = defaultdict(list)
        for task in Tasks.query.filter(Tasks.course_id.in_(courses.values())).yield_per(100):
            scope = 'active' if task.is_active else 'inactive'
            stats[f'{scope}:tasks'] += 1
            try:
                attachments = json.loads(task.attached_files or '[]')
                if not isinstance(attachments, list):
                    raise ValueError('Not an array')
            except (ValueError, TypeError):
                stats[f'{scope}:invalid_attachments'] += 1
                attachments = []
            urls = [str(entry.get('download_url') or entry.get('path') or entry.get('url') or '') for entry in attachments if isinstance(entry, dict)]
            urls += [str(tag.get('src') or '') for tag in BeautifulSoup(task.content_html or '', 'html.parser').find_all(['img', 'source', 'video', 'audio'])]
            for url in urls:
                if url.startswith('/storage/google-drive/'):
                    references[url.removeprefix('/storage/google-drive/')].add(task.task_id)
                    stats[f'{scope}:drive_references'] += 1
                elif url.startswith('data:'):
                    stats[f'{scope}:embedded'] += 1
                elif url.startswith('/attachments/'):
                    stats[f'{scope}:local_references'] += 1
                    if len(examples[f'{scope}:local']) < 30:
                        examples[f'{scope}:local'].append([task.task_id, url])
                elif url.startswith(('http://', 'https://')):
                    host = urlsplit(url).hostname or 'unknown'
                    stats[f'{scope}:external:{host}'] += 1
                    if len(examples[f'{scope}:external:{host}']) < 40:
                        examples[f'{scope}:external:{host}'].append([task.task_id, url])
                else:
                    stats[f'{scope}:broken_or_relative'] += 1
                    if len(examples[f'{scope}:broken_or_relative']) < 40:
                        examples[f'{scope}:broken_or_relative'].append([task.task_id, url])

        if not storage.use_google_drive:
            raise RuntimeError('Production Google Drive storage is not configured')
        actual = set()
        page_token = None
        pages = 0
        while True:
            response = storage.google_drive.files().list(
                q=f"'{storage.google_drive_folder_id}' in parents and trashed = false",
                fields='nextPageToken,files(id)',
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute(num_retries=5)
            actual.update(item['id'] for item in response.get('files', []))
            pages += 1
            page_token = response.get('nextPageToken')
            if not page_token:
                break
        missing = {file_id: sorted(task_ids) for file_id, task_ids in references.items() if file_id not in actual}
        print(json.dumps({
            'stats': dict(stats),
            'unique_drive_references': len(references),
            'drive_folder_files': len(actual),
            'drive_pages': pages,
            'missing_drive_ids': missing,
            'examples': dict(examples),
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
