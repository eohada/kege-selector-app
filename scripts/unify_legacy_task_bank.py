"""Normalize pre-bank task metadata and migrate KEGE media to Google Drive."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_ASSET_BYTES = 100 * 1024 * 1024


def source_asset_url(raw: str) -> str | None:
    value = str(raw or '').strip()
    if not value or value.startswith(('data:', 'blob:', '/storage/', '/attachments/', '/static/')):
        return None
    url = urljoin('https://kompege.ru/', value)
    parsed = urlsplit(url)
    if parsed.hostname != 'kompege.ru' or parsed.scheme not in ('http', 'https'):
        return None
    return url.replace('http://', 'https://', 1)


def fetch_asset(url: str) -> tuple[bytes, str]:
    with requests.get(url, timeout=(10, 50), stream=True) as response:
        response.raise_for_status()
        if source_asset_url(response.url) is None:
            raise ValueError('Attachment redirected outside KEGE')
        mime = response.headers.get('content-type', '').split(';', 1)[0].strip()
        if mime == 'text/html':
            raise ValueError('Attachment endpoint returned HTML')
        content = BytesIO()
        for chunk in response.iter_content(65536):
            content.write(chunk)
            if content.tell() > MAX_ASSET_BYTES:
                raise ValueError('Attachment exceeds size limit')
        payload = content.getvalue()
        if not payload:
            raise ValueError('Empty attachment')
        return payload, mime or 'application/octet-stream'


def store_asset(url: str, cache: dict[str, dict]) -> dict:
    from app.storage.s3_service import storage

    if url in cache:
        return cache[url]
    payload, mime = fetch_asset(url)
    original_name = Path(urlsplit(url).path).name or 'asset'
    filename = secure_filename(original_name) or 'asset'
    file = FileStorage(stream=BytesIO(payload), filename=filename, content_type=mime)
    key = storage.upload_file(file, folder='kompege/ege-informatics')
    if not key.startswith('gdrive://'):
        raise ValueError('Google Drive did not return a storage key')
    result = {
        'storage_key': key,
        'download_url': '/storage/google-drive/' + key.removeprefix('gdrive://'),
        'mime_type': mime,
        'name': filename,
    }
    cache[url] = result
    return result


def normalize_metadata(task) -> bool:
    changed = False
    if task.course_id == 3 and ('<m:' in (task.content_html or '') or '<mfenced' in (task.content_html or '')):
        from app.utils.mathml import normalize_fipi_mathml

        soup = BeautifulSoup(task.content_html, 'html.parser')
        normalize_fipi_mathml(soup)
        task.content_html = str(soup)
        changed = True
    if task.course_id == 1 and task.bank_origin == 'scraped' and task.source_url and urlsplit(task.source_url).hostname == 'kompege.ru':
        if not task.source_name:
            tag = (task.kege_source_tag or '').strip()
            task.source_name = ('КЕГЭ — ' + tag)[:160] if tag else 'КЕГЭ'
            changed = True
        if not task.source_task_number and 1 <= task.task_number <= 27:
            task.source_task_number = task.task_number
            changed = True
        if not task.source_key:
            task.source_key = f'kompege:ege-informatics:{task.site_task_id}:{task.task_number}'
            changed = True
    else:
        if not task.source_name:
            task.source_name = 'BooStudy — авторское задание' if task.bank_origin == 'manual' else 'BooStudy — учебный курс'
            changed = True
        if not task.source_key:
            task.source_key = f'boostudy:{task.bank_origin or "legacy"}:{task.task_id}'
            changed = True
    if task.answer_spec is None:
        answer_type = 'code' if task.course_id in (6, 7, 8) and task.answer is None else 'short_answer'
        task.answer_spec = {'type': answer_type}
        changed = True
    if task.difficulty_level not in (1, 2, 3):
        task.difficulty_level = task.kege_difficulty_tier if task.kege_difficulty_tier in (1, 2, 3) else 2
        changed = True
    if task.ingest_status == 'ready' and not (task.answer or '').strip():
        task.ingest_status = 'needs_answer'
        changed = True
    if not task.content_fingerprint:
        text = ' '.join(BeautifulSoup(task.content_html or '', 'html.parser').get_text(' ', strip=True).split()).casefold()
        task.content_fingerprint = hashlib.sha256(text.encode('utf-8')).hexdigest()
        changed = True
    return changed


def migrate_assets(task, cache: dict[str, dict]) -> tuple[int, int]:
    try:
        attachments = json.loads(task.attached_files or '[]')
    except json.JSONDecodeError:
        return 0, 1
    if not isinstance(attachments, list):
        return 0, 1
    moved, failed = 0, 0
    rewrite = {}
    by_name = {}
    for entry in attachments:
        if not isinstance(entry, dict):
            continue
        if entry.get('storage_key'):
            for value in (entry.get('name'), entry.get('url'), entry.get('source_url')):
                if value:
                    by_name[Path(urlsplit(str(value)).path).name.lower()] = entry.get('download_url') or entry.get('path')
            continue
        url = source_asset_url(entry.get('source_url') or entry.get('url'))
        if not url:
            failed += 1
            continue
        try:
            stored = store_asset(url, cache)
        except (requests.RequestException, OSError, ValueError):
            failed += 1
            continue
        for value in (entry.get('path'), entry.get('url'), entry.get('source_url')):
            if value:
                rewrite[str(value)] = stored['download_url']
        entry.update(stored, source_url=url, url=url, path=stored['download_url'],
                     preview_url=stored['download_url'] if stored['mime_type'].startswith('image/') else None,
                     download_status='stored')
        for value in (entry.get('name'), url):
            if value:
                by_name[Path(urlsplit(str(value)).path).name.lower()] = stored['download_url']
        moved += 1

    soup = BeautifulSoup(task.content_html or '', 'html.parser')
    html_changed = False
    for tag in soup.find_all(['img', 'source', 'video', 'audio']):
        value = str(tag.get('src') or '').strip()
        known = by_name.get(Path(urlsplit(value).path).name.lower())
        if known:
            if value != known:
                tag['src'] = known
                html_changed = True
            continue
        url = source_asset_url(value)
        if not url:
            continue
        try:
            stored = store_asset(url, cache)
        except (requests.RequestException, OSError, ValueError):
            failed += 1
            continue
        rewrite[value] = stored['download_url']
        tag['src'] = stored['download_url']
        html_changed = True
        if not any(isinstance(entry, dict) and entry.get('source_url') == url for entry in attachments):
            attachments.append({**stored, 'source_url': url, 'url': url, 'path': stored['download_url'],
                                'preview_url': stored['download_url'], 'download_status': 'stored'})
        moved += 1
    for tag in soup.find_all('a', href=True):
        href = str(tag['href'])
        target = rewrite.get(href) or by_name.get(Path(urlsplit(href).path).name.lower())
        if target:
            tag['href'] = target
            html_changed = True
        elif re.search(r'\.(?:txt|csv|xlsx?|ods|docx?|odt|zip|pdf|py|dat)(?:[?#]|$)', href, re.I):
            url = source_asset_url(href)
            if url:
                try:
                    stored = store_asset(url, cache)
                except (requests.RequestException, OSError, ValueError):
                    failed += 1
                else:
                    tag['href'] = stored['download_url']
                    attachments.append({**stored, 'source_url': url, 'url': url, 'path': stored['download_url'],
                                        'download_status': 'stored'})
                    html_changed = True
                    moved += 1
    if moved:
        task.attached_files = json.dumps(attachments, ensure_ascii=False)
    if html_changed:
        task.content_html = str(soup)
    return moved, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--assets', action='store_true', help='Migrate KEGE files and inline images to Google Drive')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--after-id', type=int, default=0)
    parser.add_argument('--through-id', type=int, default=0)
    args = parser.parse_args()
    if args.assets and not args.apply:
        parser.error('--assets requires --apply because Drive uploads are irreversible')

    from app import create_app
    from core.db_models import Tasks, db
    from sqlalchemy import or_
    app = create_app()
    counts = {'seen': 0, 'metadata_changed': 0, 'assets_moved': 0, 'assets_failed': 0}
    cache: dict[str, dict] = {}
    with app.app_context():
        query = Tasks.query
        if args.assets:
            query = query.filter(
                Tasks.source_key.like('kompege:ege-informatics:%'),
                or_(Tasks.attached_files.isnot(None), Tasks.content_html.ilike('%<img%')),
            )
        last_id = args.after_id
        if args.through_id:
            query = query.filter(Tasks.task_id <= args.through_id)
        while True:
            batch = query.filter(Tasks.task_id > last_id).order_by(Tasks.task_id).limit(100).all()
            if not batch:
                break
            for task in batch:
                last_id = task.task_id
                counts['seen'] += 1
                if normalize_metadata(task):
                    counts['metadata_changed'] += 1
                if args.assets:
                    moved, failed = migrate_assets(task, cache)
                    counts['assets_moved'] += moved
                    counts['assets_failed'] += failed
                if args.apply:
                    db.session.commit()
                else:
                    db.session.rollback()
                if counts['seen'] % 250 == 0:
                    print(json.dumps(counts, ensure_ascii=False), flush=True)
                if args.limit and counts['seen'] >= args.limit:
                    break
            if args.limit and counts['seen'] >= args.limit:
                break
    print(json.dumps({'applied': args.apply, **counts}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
