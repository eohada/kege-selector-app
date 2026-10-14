"""Package a public KEGE API snapshot and its assets for the bank importer."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup


ORIGIN = 'https://kompege.ru'
MAX_BYTES = 100 * 1024 * 1024


def asset_url(value):
    url = urljoin(ORIGIN + '/', str(value))
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname != 'kompege.ru':
        raise ValueError(f'Unexpected asset host: {url[:150]}')
    return url.replace('http://', 'https://', 1)


def prepare(rows):
    tasks, assets, seen = [], {}, set()
    for row in rows:
        if row.get('hide'):
            continue
        source_id = str(row['taskId'])
        number = int(row['number'])
        if source_id in seen:
            raise ValueError(f'Duplicate source ID: {source_id}')
        seen.add(source_id)
        if not 1 <= number <= 27:
            raise ValueError(f'Invalid exam position: {number}')
        parts = [row]
        if number == 19:
            subs = row.get('subTask') or []
            if sorted(int(s['number']) for s in subs) != [20, 21]:
                raise ValueError(f'Incomplete game triple: {source_id}')
            parts += subs
        for part in parts:
            part_number = int(part['number'])
            html = row.get('text') or ''
            if part is not row:
                # Preserve the complete shared statement and clearly identify the question to answer.
                html += f'<h3>Задание {part_number}</h3>' + (part.get('text') or '')
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup.find_all(['script', 'style', 'iframe', 'object', 'embed']):
                tag.decompose()
            for tag in soup.find_all(True):
                for attr in list(tag.attrs):
                    if attr.lower().startswith('on') or attr in {'srcdoc', 'srcset', 'style'}:
                        del tag.attrs[attr]
            refs = {}

            def attach(value, name=''):
                url = asset_url(value)
                filename = re.sub(r'[^\w.\-]', '_', Path(urlsplit(url).path).name) or 'asset'
                path = f'assets/{hashlib.sha256(url.encode()).hexdigest()[:20]}/{filename}'
                assets[url] = path
                refs[url] = {'source_url': url, 'archive_path': path, 'name': name or filename}
                return path

            for tag in soup.find_all(['img', 'audio', 'video', 'source']):
                value = tag.get('src') or tag.get('data-src')
                if value:
                    if str(value).startswith('data:image/'):
                        # The importer stores embedded images in Drive as well.
                        tag['src'] = value
                        tag.attrs.pop('data-src', None)
                        continue
                    tag['src'] = attach(value)
                    tag.attrs.pop('data-src', None)
            for tag in soup.find_all('a', href=True):
                value = str(tag['href'])
                if value.lower().startswith(('javascript:', 'data:')):
                    tag.unwrap()
                elif re.search(r'\.(?:txt|csv|xlsx?|ods|docx?|odt|zip|pdf|py|png|jpe?g|gif|svg|dat)(?:[?#]|$)', value, re.I):
                    tag['href'] = attach(value)
                else:
                    tag['href'] = urljoin(ORIGIN + '/', value)
            for entry in row.get('files') or []:
                value = entry.get('url') or entry.get('href')
                if value:
                    attach(value, entry.get('name') or entry.get('text') or '')
            if not soup.get_text(strip=True) and not soup.find('img'):
                raise ValueError(f'Empty statement: {source_id}')
            comment = str(row.get('comment') or '').strip()
            years = re.findall(r'\b20\d{2}\b', comment)
            difficulty = row.get('difficulty')
            difficulty = difficulty if difficulty in (1, 2, 3) else (1 if part_number <= 8 else 2 if part_number <= 18 else 3)
            answer = str(part['key']).strip() if part.get('key') is not None else None
            tasks.append({
                'source_id': source_id, 'source_key': f'kompege:ege-informatics:{source_id}:{part_number}',
                'source_name': ('КЕГЭ — ' + comment)[:160] if comment else 'КЕГЭ',
                'source_url': f'{ORIGIN}/task?id={source_id}',
                'source_year': int(years[-1]) if years else None,
                'source_task_number': part_number, 'task_number': part_number,
                'task_group_id': source_id if number == 19 else None,
                'exam_year': 2027, 'is_current': True,
                'prototype_status': 'real' if comment.startswith('Демоверсия 2027') else 'unreviewed',
                'difficulty_level': difficulty, 'answer': answer,
                'answer_spec': {'type': 'short_answer', 'source_table': part.get('table') or {}, 'source_answer_verified': False},
                'solution': None, 'hints': None, 'content_html': str(soup),
                'attached_files': list(refs.values()), 'storage_folder': 'kompege/ege-informatics',
                'review_notes': f'КЕГЭ: {comment}. Нумерация текущего каталога на дату выгрузки. Ответ из поля key; решение не подставлялось вместо ответа.',
            })
    return tasks, assets


def download(url, target):
    for attempt in range(3):
        try:
            with requests.get(url, timeout=(10, 45), stream=True) as response:
                response.raise_for_status()
                asset_url(response.url)
                mime = response.headers.get('Content-Type', 'application/octet-stream').split(';')[0]
                if mime == 'text/html':
                    raise ValueError('HTML returned instead of attachment')
                size = 0
                with target.open('wb') as sink:
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError('Attachment exceeds size limit')
                        sink.write(chunk)
                if not size:
                    raise ValueError('Empty attachment')
                return mime
        except (requests.RequestException, OSError, ValueError):
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    tasks, assets = prepare(json.loads(args.input.read_text(encoding='utf-8')))
    print(f'Prepared {len(tasks)} tasks; downloading {len(assets)} unique assets', flush=True)
    temporary = args.output.with_suffix(args.output.suffix + '.partial')
    try:
        with tempfile.TemporaryDirectory(prefix='kege-assets-') as tmp, ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            mimes = {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {}
                for url, path in assets.items():
                    local = Path(tmp) / hashlib.sha256(url.encode()).hexdigest()
                    futures[pool.submit(download, url, local)] = (url, path, local)
                for index, future in enumerate(as_completed(futures), 1):
                    url, path, local = futures[future]
                    mimes[url] = future.result()
                    archive.write(local, path)
                    if index % 25 == 0 or index == len(assets):
                        print(f'Assets: {index}/{len(assets)}', flush=True)
            for task in tasks:
                for entry in task['attached_files']:
                    entry.update(mime_type=mimes[entry['source_url']], download_status='stored')
                archive.writestr(f"tasks/{task['source_id']}-{task['task_number']}.json", json.dumps(task, ensure_ascii=False))
            archive.writestr('manifest.json', json.dumps({
                'created_at': datetime.now(timezone.utc).isoformat(),
                'source_url': ORIGIN, 'counts': {'tasks': len(tasks), 'assets': len(assets)},
                'exam_year': 2027, 'source_answers_independently_verified': False,
            }, ensure_ascii=False))
        temporary.replace(args.output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f'Archive ready: {args.output}', flush=True)


if __name__ == '__main__':
    main()
