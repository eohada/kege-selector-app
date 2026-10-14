"""Build a source-preserving archive of EGE Informatics tasks from OpenFIPI."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import click
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from werkzeug.utils import secure_filename

from app.commands.fipi_bank_import import _clean_fragment, _fingerprint


OPENFIPI_HOME = 'https://openfipi.devinf.ru/'
OPENFIPI_CATALOG = 'https://openfipi.devinf.ru/tasks_ege/'
FIPI_EGE_INFORMATICS = 'https://ege.fipi.ru/bank/questions.php?proj=B9ACA5BBB2E19E434CD6BEC25284C67F'
MAX_ASSET_BYTES = 50 * 1024 * 1024
TASK_CARD_EXTRACTOR = r"""boxes => boxes.flatMap(box => {
  const primaryLink = box.querySelector('.level-left a[href^="/task/"]');
  if (!primaryLink) return [];

  const header = box.querySelector('.level-left')?.innerText || '';
  const numberMatch = header.match(/[№#]\s*(\d+)/);
  const dateMatch = header.match(/(\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}:\d{2})?)/);
  const content = box.querySelector('.content');
  if (!content) return [];

  const id = new URL(primaryLink.href).pathname.split('/').filter(Boolean).pop();
  const sections = [...box.querySelectorAll('.content')];
  const answerSection = sections.slice(1).find(section => /ответ\s*:/i.test(section.innerText || ''));
  const answerText = answerSection?.innerText || '';
  const answerMatch = answerText.match(/ответ\s*:\s*([\s\S]*)/i);

  return [{
    source_id: id,
    source_url: primaryLink.href,
    source_task_number: numberMatch ? Number(numberMatch[1]) : null,
    is_current: /актуальное/i.test(header),
    answer_available: /есть ответ/i.test(header),
    mirror_updated_at: dateMatch ? dateMatch[1] : null,
    content_html: content.innerHTML,
    content_text: content.innerText || '',
    answer: answerMatch ? answerMatch[1].trim() : null
  }];
})"""


def _difficulty_estimate(task_number: int | None) -> int:
    number = task_number or 0
    if number >= 1000:
        number %= 1000
    if number <= 8:
        return 1
    if number <= 18:
        return 2
    return 3


def _asset_path(url: str) -> str:
    filename = secure_filename(PurePosixPath(urlsplit(url).path).name) or 'asset'
    digest = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
    return f'assets/{digest}/{filename}'


def _media_name(item: dict, url: str) -> str:
    name = str(item.get('name') or '').strip()
    if name.lower() in {'undefined', 'null', 'none'}:
        name = ''
    return name or PurePosixPath(urlsplit(url).path).name or 'asset'


def _allowed_asset_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (
        host == 'openfipi.devinf.ru'
        or host == 'fipi.ru'
        or host.endswith('.fipi.ru')
    )


def _prepare_task(raw: dict, source_page_url: str) -> tuple[dict, list[dict]]:
    soup, media = _clean_fragment(raw.get('content_html') or '', source_page_url)
    for link in soup.find_all('a', href=True):
        if urlsplit(str(link['href'])).path.startswith('/task/'):
            link.unwrap()

    attachments = []
    media_by_url = {}
    for item in media:
        url = item['url']
        if not _allowed_asset_url(url):
            attachments.append({
                'name': _media_name(item, url),
                'source_url': url,
                'archive_path': None,
                'mime_type': None,
                'download_status': 'external_host_skipped',
            })
            continue
        if url not in media_by_url:
            media_by_url[url] = _asset_path(url)
        archive_path = media_by_url[url]
        tag = item['tag']
        target_attribute = 'src' if tag.name in {'img', 'source', 'video', 'audio', 'iframe'} else 'href'
        tag[target_attribute] = archive_path
        attachments.append({
            'name': _media_name(item, url),
            'source_url': url,
            'archive_path': archive_path,
            'mime_type': None,
            'download_status': 'pending',
        })

    html = str(soup)
    answer = re.sub(r'^\s*', '', raw.get('answer') or '') or None
    current = bool(raw.get('is_current'))
    number = raw.get('source_task_number')
    task = {
        'exam_subject': 'ЕГЭ по информатике',
        'source_name': 'Открытый банк ФИПИ; разметка и ответы OpenFIPI 2.0',
        'source_url': raw['source_url'],
        'official_source_url': FIPI_EGE_INFORMATICS,
        'source_key': f"openfipi:ege-informatics:{raw['source_id']}",
        'source_id': raw['source_id'],
        'source_task_number': number,
        'task_number': number,
        'source_year': None,
        'exam_year': 2027 if current else None,
        'mirror_updated_at': raw.get('mirror_updated_at'),
        'prototype_status': 'real' if current else 'practice_only',
        'is_current': current,
        'difficulty_level': _difficulty_estimate(number),
        'difficulty_estimate_method': 'estimated_from_exam_position_v1',
        'answer': answer,
        'answer_verified': False if answer else None,
        'answer_source_url': raw['source_url'] if answer else None,
        'answer_spec': {'type': 'short_answer', 'source_answer_verified': False},
        'solution': None,
        'hints': None,
        'content_html': html,
        'content_fingerprint': _fingerprint(html + ' ' + ' '.join(item['url'] for item in media)),
        'attached_files': attachments,
        'ingest_status': 'needs_answer_review' if answer else 'needs_answer',
    }
    return task, media


async def _download_asset(request, url: str, destination: Path, semaphore: asyncio.Semaphore) -> tuple[str, str | None, str | None, str]:
    async with semaphore:
        last_error = 'unknown'
        for attempt in range(2):
            try:
                response = await request.get(url, timeout=45_000)
                if not response.ok:
                    last_error = f'HTTP {response.status}'
                    if response.status >= 500 and attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    return url, None, None, f'failed: {last_error}'
                content_length = int(response.headers.get('content-length') or 0)
                if content_length > MAX_ASSET_BYTES:
                    return url, None, None, 'failed: AssetTooLarge'
                payload = await response.body()
                if len(payload) > MAX_ASSET_BYTES:
                    return url, None, None, 'failed: AssetTooLarge'
                if not payload:
                    return url, None, None, 'failed: EmptyAsset'
                mime_type = response.headers.get('content-type', 'application/octet-stream').split(';', 1)[0]
                destination.write_bytes(payload)
                return url, str(destination), mime_type, 'stored'
            except Exception as exc:
                last_error = type(exc).__name__
                if attempt == 0:
                    await asyncio.sleep(0.5)
        destination.unlink(missing_ok=True)
        return url, None, None, f'failed: {last_error}'


async def _download_assets_into_archive(asset_paths: dict[str, str], temp_dir: str, archive: ZipFile) -> dict[str, tuple[str | None, str | None, str]]:
    async with async_playwright() as playwright:
        request = await playwright.request.new_context(
            ignore_https_errors=True,
            timeout=45_000,
            extra_http_headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
            },
        )
        semaphore = asyncio.Semaphore(8)
        futures = []
        for url in asset_paths:
            filename = hashlib.sha256(url.encode('utf-8')).hexdigest() + '.asset'
            destination = Path(temp_dir) / filename
            futures.append(asyncio.create_task(_download_asset(request, url, destination, semaphore)))

        asset_cache = {}
        try:
            for completed, future in enumerate(asyncio.as_completed(futures), start=1):
                url, local_path, mime_type, status = await future
                asset_cache[url] = (local_path, mime_type, status)
                if status == 'stored' and local_path:
                    archive.write(local_path, asset_paths[url])
                if completed % 50 == 0 or completed == len(futures):
                    click.echo(f'Вложения: обработано {completed}/{len(futures)}', err=True)
        finally:
            await request.dispose()
        return asset_cache


def _save_collection_checkpoint(
    checkpoint_path: Path,
    tasks: list[dict],
    page_urls: set[str],
    total_label: str,
    next_page_url: str | None,
    next_page_number: int,
    complete: bool,
) -> None:
    temporary_path = checkpoint_path.with_suffix(checkpoint_path.suffix + '.tmp')
    checkpoint = {
        'tasks': tasks,
        'page_urls': sorted(page_urls),
        'total_label': total_label,
        'next_page_url': next_page_url,
        'next_page_number': next_page_number,
        'complete': complete,
    }
    temporary_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding='utf-8')
    temporary_path.replace(checkpoint_path)


async def _goto_listing_with_retry(page, target_url: str) -> None:
    card_link = page.locator('.box .level-left a[href^="/task/"]').first
    for attempt in range(3):
        try:
            await page.goto(target_url, wait_until='domcontentloaded', timeout=60_000)
            await card_link.wait_for(timeout=20_000)
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise
            await page.wait_for_timeout(1000 * (attempt + 1))


async def _collect_openfipi(
    include_old: bool,
    per_page: int,
    max_pages: int,
    limit: int,
    checkpoint_path: Path,
) -> tuple[list[dict], str]:
    saved = json.loads(checkpoint_path.read_text(encoding='utf-8')) if checkpoint_path.exists() else {}
    if saved.get('complete'):
        return saved.get('tasks', []), saved.get('total_label', '')

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale='ru-RU', ignore_https_errors=True)
        page = await context.new_page()
        try:
            tasks: list[dict] = saved.get('tasks', [])
            page_urls: set[str] = set(saved.get('page_urls', []))
            seen_ids = {str(task.get('source_id')) for task in tasks}
            total_label = saved.get('total_label', '')
            start_page = int(saved.get('next_page_number') or 1)

            if saved.get('next_page_url'):
                await _goto_listing_with_retry(page, saved['next_page_url'])
            else:
                await page.goto(OPENFIPI_HOME, wait_until='domcontentloaded', timeout=60_000)
                await page.get_by_role('link', name=re.compile('Задания ЕГЭ', re.I)).first.click()
                await page.wait_for_load_state('domcontentloaded', timeout=60_000)
                await page.locator('#new').check()
                if include_old:
                    await page.locator('#old').check()
                await page.locator('#per_page').select_option(str(per_page))
                await page.locator('#submit').click()
                await page.wait_for_load_state('domcontentloaded', timeout=60_000)
                await _goto_listing_with_retry(page, page.url)

            for page_number in range(start_page, max_pages + 1):
                visible_text = await page.locator('body').inner_text()
                summary_match = re.search(r'Показаны задания\s+([\d\s,.-]+\s+из\s+[\d\s,]+)', visible_text)
                if summary_match:
                    total_label = summary_match.group(0)
                cards = page.locator('.box')
                await page.evaluate("""() => {
                  for (const box of document.querySelectorAll('.box')) {
                    if (!box.querySelector('.level-left a[href^="/task/"]')) continue;
                    const button = [...box.querySelectorAll('button')].find(item => /показать ответ/i.test(item.innerText || ''));
                    button?.click();
                  }
                }""")
                await page.wait_for_timeout(100)
                raw_rows = await cards.evaluate_all(TASK_CARD_EXTRACTOR)
                for raw in raw_rows:
                    source_id = str(raw.get('source_id') or '')
                    if not source_id or source_id in seen_ids:
                        continue
                    raw['page_url'] = page.url
                    raw['source_id'] = source_id
                    tasks.append(raw)
                    seen_ids.add(source_id)
                    if limit and len(tasks) >= limit:
                        click.echo(f'OpenFIPI: страница {page_number}, собрано карточек {len(tasks)}; {total_label}')
                        return tasks, total_label

                if page_number == 1 or page_number % 5 == 0:
                    click.echo(f'OpenFIPI: просмотрено страниц {page_number}, собрано карточек {len(tasks)}; {total_label}')

                next_link = page.locator('nav.pagination a[aria-label="Next"]').last
                if not await next_link.count():
                    page_urls.add(page.url)
                    _save_collection_checkpoint(checkpoint_path, tasks, page_urls, total_label, None, page_number + 1, True)
                    break
                next_url = await next_link.get_attribute('href')
                next_url = urljoin(page.url, next_url) if next_url else None
                page_urls.add(page.url)
                if not next_url or next_url in page_urls:
                    _save_collection_checkpoint(checkpoint_path, tasks, page_urls, total_label, None, page_number + 1, True)
                    break
                _save_collection_checkpoint(checkpoint_path, tasks, page_urls, total_label, next_url, page_number + 1, False)
                await _goto_listing_with_retry(page, next_url)
            return tasks, total_label
        finally:
            await browser.close()


def _write_archive(tasks: list[dict], output_path: str, source_page_count: str) -> dict:
    prepared = []
    asset_paths: dict[str, str] = {}
    for raw in tasks:
        source_page_url = raw.get('page_url') or OPENFIPI_CATALOG
        task, media = _prepare_task(raw, source_page_url)
        prepared.append((task, media))
        for item in media:
            url = item['url']
            if _allowed_asset_url(url):
                archive_path = next((entry['archive_path'] for entry in task['attached_files'] if entry['source_url'] == url), None)
                if archive_path:
                    asset_paths.setdefault(url, archive_path)

    counts = {
        'tasks': 0,
        'answers': 0,
        'current': 0,
        'historical': 0,
        'assets_total': len(asset_paths),
        'assets_ok': 0,
        'assets_failed': 0,
    }
    asset_cache: dict[str, tuple[str | None, str | None, str]] = {}
    with tempfile.TemporaryDirectory(prefix='boostudy-openfipi-assets-') as temp_dir:
        with ZipFile(output_path, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
            asset_cache = asyncio.run(_download_assets_into_archive(asset_paths, temp_dir, archive))
            counts['assets_ok'] = sum(status == 'stored' for _, _, status in asset_cache.values())
            counts['assets_failed'] = sum(status != 'stored' for _, _, status in asset_cache.values())

            for task, media in prepared:
                for item in media:
                    url = item['url']
                    result = asset_cache.get(url)
                    if not result:
                        continue
                    _, mime_type, status = result
                    stored_path = asset_paths[url]
                    for attachment in task['attached_files']:
                        if attachment['source_url'] == url:
                            attachment['archive_path'] = stored_path if status == 'stored' else None
                            attachment['mime_type'] = mime_type
                            attachment['download_status'] = status
                    if status != 'stored':
                        soup = BeautifulSoup(task['content_html'], 'html.parser')
                        for tag in soup.find_all(True):
                            for attr in ('src', 'href'):
                                if tag.get(attr) == stored_path:
                                    tag[attr] = url
                        task['content_html'] = str(soup)

                task['content_fingerprint'] = _fingerprint(task['content_html'])
                archive.writestr(
                    f"tasks/{task['source_id']}.json",
                    json.dumps(task, ensure_ascii=False, separators=(',', ':')),
                )
                counts['tasks'] += 1
                counts['answers'] += bool(task['answer'])
                counts['current'] += bool(task['is_current'])
                counts['historical'] += not bool(task['is_current'])
                if counts['tasks'] % 500 == 0 or counts['tasks'] == len(prepared):
                    click.echo(f"Карточки: упаковано {counts['tasks']}/{len(prepared)}", err=True)

            manifest = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'catalog_url': OPENFIPI_CATALOG,
                'official_bank_url': FIPI_EGE_INFORMATICS,
                'filter_scope': 'current and historical EGE Informatics tasks' if counts['historical'] else 'current EGE Informatics tasks',
                'catalog_page_summary': source_page_count,
                'counts': counts,
                'answers_are_unverified_community_data': True,
                'current_prototype_exam_year': 2027,
                'exam_year_basis': 'OpenFIPI current marker cross-checked against FIPI 2027 planned changes',
                'prototype_status_requires_review': False,
                'solutions_and_hints_available_from_source': False,
                'media_hosts_restricted_to': ['openfipi.devinf.ru', '*.fipi.ru', 'fipi.ru'],
            }
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    return counts


@click.command('openfipi-bank-export')
@click.option('--include-old/--current-only', default=True, show_default=True, help='Добавлять архивные задания для тренировки.')
@click.option('--per-page', type=click.Choice(['5', '10', '20', '50']), default='50', show_default=True)
@click.option('--max-pages', type=click.IntRange(1, 1000), default=200, show_default=True)
@click.option('--limit', type=click.IntRange(0, 100000), default=0, show_default=True, help='0 — все карточки; число — ограничить пробный сбор.')
@click.option('--output', type=click.Path(dir_okay=False, writable=True), required=True, help='Путь к ZIP-архиву в локальной папке.')
def openfipi_bank_export_command(include_old: bool, per_page: str, max_pages: int, limit: int, output: str):
    """Собрать карточки ЕГЭ по информатике и вложения в архив с исходными ссылками."""
    checkpoint_path = Path(output + '.collect.json')
    try:
        tasks, page_summary = asyncio.run(_collect_openfipi(include_old, int(per_page), max_pages, limit, checkpoint_path))
    except Exception as exc:
        raise click.ClickException(f'Не удалось прочитать каталог OpenFIPI: {type(exc).__name__}: {exc}') from exc
    if not tasks:
        raise click.ClickException('Каталог не вернул карточки заданий; архив не создан.')
    counts = _write_archive(tasks, output, page_summary)
    checkpoint_path.unlink(missing_ok=True)
    click.echo(
        f"Архив готов: карточек {counts['tasks']}, ответов из источника {counts['answers']}, "
        f"актуальных {counts['current']}, архивных {counts['historical']}, "
        f"файлов сохранено {counts['assets_ok']}, ошибок файлов {counts['assets_failed']}; "
        f'путь: {output}'
    )


if __name__ == '__main__':
    openfipi_bank_export_command()
