"""Import original task markup and media from the public FIPI task bank."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, urljoin, urlsplit

import click
import requests
from bs4 import BeautifulSoup
from flask.cli import with_appcontext
from flask import current_app
from playwright.async_api import async_playwright
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.storage.s3_service import storage
from app.utils.mathml import normalize_fipi_mathml
from core.db_models import Course, TaskReview, Tasks, db


FIPI_PROJECTS = {
    'ege_informatics': {
        'host': 'ege.fipi.ru',
        'project': 'B9ACA5BBB2E19E434CD6BEC25284C67F',
        'course_slug': 'ege_informatics',
        'title': 'ЕГЭ по информатике',
    },
    'ege_math_profile': {
        'host': 'ege.fipi.ru',
        'project': 'AC437B34557F88EA4115D2F374B0A07B',
        'course_slug': 'ege_math_profile',
        'title': 'ЕГЭ по математике, профильный уровень',
    },
    'oge_informatics': {
        'host': 'oge.fipi.ru',
        'project': '74676951F093A0754D74F2D6E7955F06',
        'course_slug': 'oge_informatics',
        'title': 'ОГЭ по информатике',
    },
    'oge_math': {
        'host': 'oge.fipi.ru',
        'project': 'DE0E276E497AB3784C3FC4CC20248DC0',
        'course_slug': 'oge_math',
        'title': 'ОГЭ по математике',
    },
}

FIPI_PAGE_TEMPLATE = 'https://{host}/bank/questions.php?proj={project}&init_filter_themes=1'
MEDIA_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf', '.txt', '.csv',
    '.xls', '.xlsx', '.ods', '.doc', '.docx', '.odt', '.zip', '.py', '.dat',
}


@dataclass
class ImportCounts:
    seen: int = 0
    imported: int = 0
    already_present: int = 0
    failed: int = 0


EXTRACT_BLOCKS_JS = r"""() => {
  return [...document.querySelectorAll('.qblock')].map(block => {
    const cells = [...block.querySelectorAll('td.cell_0')];
    const content = cells.length
      ? cells.map(cell => cell.innerHTML).join('<br>')
      : (block.querySelector('td') || block).innerHTML;
    const qid = (block.id || '').replace(/^q/, '');
    const guid = block.querySelector('input[name="guid"]')?.value || '';
    const radios = block.querySelectorAll('input[type="radio"]');
    const checkboxes = block.querySelectorAll('input[type="checkbox"]');
    const text = block.innerText || '';
    let answerType = 'short_answer';
    if (radios.length) answerType = 'single_choice';
    else if (checkboxes.length) answerType = 'multiple_choice';
    else if (/разв[её]рнут|обоснован|решение представьте/i.test(text)) answerType = 'long_answer';
    const files = [...block.querySelectorAll('a[href]')]
      .map(a => ({href: a.href, name: (a.innerText || a.textContent || '').trim()}))
      .filter(x => /\.(png|jpe?g|gif|webp|svg|pdf|txt|csv|xlsx?|ods|docx?|odt|zip|py|dat)(?:[?#]|$)/i.test(x.href));
    return {qid, guid, content, answerType, files};
  });
}"""


def _clean_fragment(raw_html: str, page_url: str) -> tuple[BeautifulSoup, list[dict]]:
    soup = BeautifulSoup(raw_html or '', 'html.parser')
    for node in soup.find_all(['script', 'style', 'noscript']):
        node.decompose()
    normalize_fipi_mathml(soup)
    for node in soup.find_all(True):
        for attribute in list(node.attrs):
            if attribute.lower().startswith('on') or attribute.lower() == 'srcdoc':
                del node.attrs[attribute]

    media = []
    for tag in soup.find_all(['img', 'source', 'video', 'audio', 'iframe']):
        src = str(tag.get('src') or tag.get('data-src') or '').strip()
        if not src or src.startswith(('data:', 'blob:')):
            continue
        absolute = urljoin(page_url, src)
        tag['src'] = absolute
        tag.attrs.pop('srcset', None)
        media.append({'tag': tag, 'url': absolute, 'name': tag.get('alt') or ''})

    for tag in soup.find_all('a', href=True):
        href = str(tag['href']).strip()
        absolute = urljoin(page_url, href)
        tag['href'] = absolute
        extension = urlsplit(absolute).path.lower()
        if any(extension.endswith(ext) for ext in MEDIA_EXTENSIONS):
            media.append({'tag': tag, 'url': absolute, 'name': tag.get_text(' ', strip=True)})

    for field in soup.find_all(['input', 'button', 'textarea', 'select']):
        field.decompose()
    return soup, media


def _plain_text(fragment: str) -> str:
    soup = BeautifulSoup(fragment or '', 'html.parser')
    return ' '.join(soup.get_text(' ', strip=True).split())


def _fingerprint(fragment: str) -> str:
    normalized = re.sub(r'\s+', ' ', _plain_text(fragment)).casefold()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _drive_asset_url(key: str) -> str:
    file_id = key.removeprefix('gdrive://')
    return f'/storage/google-drive/{quote(file_id, safe="")}'


def _store_assets(media: list[dict], guid: str) -> tuple[str, list[str]]:
    attachments = []
    uploaded_keys = []
    stored_urls = {}
    for item in media:
        source_url = item['url']
        if source_url in stored_urls:
            stored = stored_urls[source_url]
        else:
            response = requests.get(source_url, timeout=(10, 30))
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f'ФИПИ вернул пустой файл: {source_url}')
            filename = secure_filename(urlsplit(source_url).path.rsplit('/', 1)[-1]) or 'asset'
            content_type = response.headers.get('content-type', 'application/octet-stream').split(';', 1)[0]
            uploaded = FileStorage(
                stream=BytesIO(response.content),
                filename=filename,
                content_type=content_type,
            )
            key = storage.upload_file(uploaded, folder=f'fipi/{guid}')
            uploaded_keys.append(key)
            target_url = _drive_asset_url(key) if key.startswith('gdrive://') else None
            stored = {'key': key, 'url': target_url, 'name': filename, 'mime_type': content_type}
            stored_urls[source_url] = stored

        is_embedded_media = item['tag'].name in ('img', 'source', 'video', 'audio', 'iframe')
        target_url = stored['url']
        if target_url:
            item['tag']['src' if is_embedded_media else 'href'] = target_url
            item['tag'].attrs.pop('srcset', None)
        attachments.append({
            'name': stored['name'],
            'path': source_url,
            'source_url': source_url,
            'download_url': target_url,
            'preview_url': target_url if is_embedded_media else None,
            'mime_type': stored['mime_type'],
            'storage_key': stored['key'],
        })
    return json.dumps(attachments, ensure_ascii=False) if attachments else '', uploaded_keys


async def _extract_bank(project: dict, max_pages: int, limit: int) -> list[dict]:
    base_url = FIPI_PAGE_TEMPLATE.format(host=project['host'], project=project['project'])
    extracted: list[dict] = []
    seen: set[str] = set()

    async def read_visible_blocks(page) -> list[dict]:
        await page.wait_for_selector('.qblock', timeout=30_000)
        await page.wait_for_timeout(1_000)
        return await page.evaluate(EXTRACT_BLOCKS_JS)

    async def open_next_page(page, page_number: int, previous_guids: set[str]) -> list[dict] | None:
        for parameter in ('pagenum', 'page'):
            candidate_url = f'{base_url}&{parameter}={page_number}'
            try:
                await page.goto(candidate_url, wait_until='domcontentloaded', timeout=60_000)
                blocks = await read_visible_blocks(page)
                guids = {str(block.get('guid') or '').strip() for block in blocks if block.get('guid')}
                if guids and not guids.issubset(previous_guids):
                    return blocks
            except Exception:
                continue

        next_selectors = (
            '.pagination a.next', 'a.pagination-next',
            "img[onclick*='nextPage']", "[onclick*='nextPage']", "[onclick*='changePage']",
        )
        for selector in next_selectors:
            link = page.locator(selector).first
            if await link.count():
                try:
                    await link.click(timeout=3_000)
                    await page.wait_for_timeout(1_000)
                    blocks = await read_visible_blocks(page)
                    guids = {str(block.get('guid') or '').strip() for block in blocks if block.get('guid')}
                    if guids and not guids.issubset(previous_guids):
                        return blocks
                except Exception:
                    continue
        return None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale='ru-RU', ignore_https_errors=True)
        page = await context.new_page()
        try:
            previous_page_guids: set[str] = set()
            for page_number in range(1, max_pages + 1):
                if page_number == 1:
                    await page.goto(base_url, wait_until='domcontentloaded', timeout=60_000)
                    try:
                        blocks = await read_visible_blocks(page)
                    except Exception as exc:
                        raise RuntimeError('The FIPI bank did not render task cards. Check FIPI access from this server.') from exc
                else:
                    blocks = await open_next_page(page, page_number, previous_page_guids)
                    if not blocks:
                        break
                page_url = page.url
                page_guids = {str(block.get('guid') or '').strip() for block in blocks if block.get('guid')}
                if not page_guids or page_guids.issubset(previous_page_guids):
                    break
                previous_page_guids = page_guids
                for block in blocks:
                    guid = str(block.get('guid') or '').strip()
                    if not guid or guid in seen:
                        continue
                    seen.add(guid)
                    block['page_url'] = page_url
                    block['source_page_url'] = f"https://{project['host']}/bank/index.php?proj={project['project']}&qid={quote(str(block.get('qid') or ''), safe='')}"
                    extracted.append(block)
                    if limit and len(extracted) >= limit:
                        return extracted
        finally:
            await browser.close()
    return extracted


def _resolve_course(course_slug: str) -> Course:
    course = Course.query.filter_by(slug=course_slug).first()
    if not course and '-' in course_slug:
        course = Course.query.filter_by(slug=course_slug.replace('-', '_')).first()
    if not course:
        available = ', '.join(f'{row.slug} ({row.title})' for row in Course.query.order_by(Course.id).all())
        raise click.ClickException(f"Не найден курс со slug '{course_slug}'. Доступные курсы: {available or 'нет'}")
    return course


def _save_task(block: dict, project: dict, course: Course, exam_year: int | None) -> str:
    guid = str(block['guid']).strip()
    source_key = f"fipi:{project['project']}:{guid.lower()}"
    existing = Tasks.query.filter_by(source_key=source_key).first()
    if existing:
        return 'already_present'

    soup, media = _clean_fragment(block.get('content') or '', block['page_url'])
    source_html = str(soup)
    source_fingerprint = _fingerprint(source_html + ' ' + ' '.join(item['url'] for item in media))
    if not existing:
        duplicate = Tasks.query.filter_by(course_id=course.id, content_fingerprint=source_fingerprint).first()
        if duplicate:
            return 'already_present'

    if not current_app.config.get('STORAGE_BACKEND') == 'google_drive' or not storage.use_google_drive:
        raise click.ClickException(
            'Перед импортом включи STORAGE_BACKEND=google_drive и настрой авторизацию Google Drive '
            '(OAuth пользователя или сервисный аккаунт с доступом к целевой папке).'
        )

    uploaded_keys: list[str] = []
    try:
        attachments_json, uploaded_keys = _store_assets(media, guid)
        rendered_html = str(soup)
        if not rendered_html.strip():
            raise RuntimeError('FIPI task condition is empty after extraction.')
        task_number = 0
        task = Tasks()
        task.course_id = course.id
        task.task_number = task_number
        task.task_group_id = None
        task.site_task_id = guid
        task.source_url = block['source_page_url']
        task.source_name = 'ФИПИ — открытый банк заданий'
        task.source_year = None
        task.source_task_number = None
        task.exam_year = exam_year
        task.source_key = source_key
        task.content_fingerprint = source_fingerprint
        task.prototype_status = 'unreviewed'
        task.ingest_status = 'needs_classification'
        task.content_html = rendered_html
        task.answer = None
        task.attached_files = attachments_json
        task.difficulty_level = 2
        task.hints = None
        task.bank_origin = 'scraped'
        task.answer_spec = {'type': block.get('answerType') or 'short_answer'}
        task.is_active = False
        db.session.add(task)
        db.session.flush()
        review = TaskReview.query.filter_by(task_id=task.task_id).first()
        if not review:
            review = TaskReview(task_id=task.task_id, status='new', notes='Импортировано из открытого банка ФИПИ; проверить номер, ответ, сложность и статус прототипа.')
            db.session.add(review)
        db.session.commit()
        return 'imported'
    except Exception:
        db.session.rollback()
        for key in uploaded_keys:
            try:
                storage.delete_file(key)
            except Exception:
                current_app.logger.exception('Failed to clean up imported FIPI asset %s', key)
        raise


@click.command('fipi-bank-import')
@click.option('--exam', 'exam_key', type=click.Choice(sorted(FIPI_PROJECTS)), default='ege_informatics', show_default=True)
@click.option('--course-slug', default=None, help='Slug курса в ExamCourses; по умолчанию берётся из выбранного экзамена.')
@click.option('--exam-year', type=click.IntRange(2020, 2100), default=None, help='Год экзаменационной версии, если он подтверждён источником.')
@click.option('--max-pages', type=click.IntRange(1, 1000), default=500, show_default=True)
@click.option('--limit', type=click.IntRange(0, 100000), default=0, show_default=True, help='0 — все доступные карточки в пределах max-pages.')
@click.option('--dry-run', is_flag=True, help='Только прочитать банк и показать объём; не загружать файлы и не менять базу.')
@with_appcontext
def fipi_bank_import_command(exam_key: str, course_slug: str | None, exam_year: int | None, max_pages: int, limit: int, dry_run: bool):
    """Забрать оригинальные задания ФИПИ и сохранить карточки с медиа в подключённое хранилище."""
    project = FIPI_PROJECTS[exam_key]
    course = _resolve_course(course_slug or project['course_slug'])
    if not dry_run and not storage.use_google_drive:
        raise click.ClickException(
            'Импорт остановлен: Google Drive не подключён. Настрой сервисный аккаунт и выдай ему доступ к папке банка.'
        )

    try:
        blocks = asyncio.run(_extract_bank(project, max_pages=max_pages, limit=limit))
    except Exception as exc:
        raise click.ClickException(f'Не удалось прочитать банк ФИПИ: {exc}') from exc

    counts = ImportCounts(seen=len(blocks))
    if dry_run:
        media_count = sum(len(block.get('files') or []) for block in blocks)
        answer_types = {}
        for block in blocks:
            answer_type = block.get('answerType') or 'short_answer'
            answer_types[answer_type] = answer_types.get(answer_type, 0) + 1
        click.echo(
            f"Пробный обход {project['title']}: найдено карточек {counts.seen}, "
            f"ссылок на файлы и медиа {media_count}, типы ответов {answer_types}. "
            'База и Google Drive не изменялись.'
        )
        return

    for block in blocks:
        try:
            outcome = _save_task(block, project, course, exam_year)
            setattr(counts, outcome, getattr(counts, outcome) + 1)
        except Exception as exc:
            counts.failed += 1
            current_app.logger.exception('FIPI task import failed for source id %s', block.get('guid'))
            click.echo(f"Не удалось сохранить карточку {block.get('guid')}: {exc}", err=True)

    click.echo(
        f"{project['title']}: просмотрено {counts.seen}, добавлено {counts.imported}, "
        f"уже было {counts.already_present}, ошибок {counts.failed}."
    )
