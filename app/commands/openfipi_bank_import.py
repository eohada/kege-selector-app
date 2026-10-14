"""Import the collected OpenFIPI task bank and media into BooStudy."""
from __future__ import annotations

import hashlib
import base64
import binascii
import json
import re
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import ZipFile

import click
from bs4 import BeautifulSoup
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.commands.fipi_bank_import import _drive_asset_url, _resolve_course
from app.commands.openfipi_bank_export import _difficulty_estimate, _fingerprint
from app.storage.s3_service import storage
from core.db_models import TaskReview, TaskSolution, Tasks, db


class BankSource:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.archive = ZipFile(self.path, 'r') if self.path.is_file() else None
        self.root = self.path if self.path.is_dir() else None

    def close(self) -> None:
        if self.archive:
            self.archive.close()

    def task_names(self) -> list[str]:
        if self.archive:
            return sorted(name for name in self.archive.namelist() if name.startswith('tasks/') and name.endswith('.json'))
        task_dir = self.path / 'tasks'
        return sorted(f'tasks/{item.name}' for item in task_dir.glob('*.json')) if task_dir.is_dir() else []

    def read(self, relative_path: str) -> bytes:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or '..' in pure_path.parts:
            raise ValueError(f'Invalid bank archive path: {relative_path}')
        if self.archive:
            return self.archive.read(pure_path.as_posix())
        target = (self.path.joinpath(*pure_path.parts)).resolve()
        if not target.is_relative_to(self.path):
            raise ValueError(f'Invalid bank directory path: {relative_path}')
        return target.read_bytes()

    def exists(self, relative_path: str) -> bool:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or '..' in pure_path.parts:
            return False
        if self.archive:
            try:
                self.archive.getinfo(pure_path.as_posix())
                return True
            except KeyError:
                return False
        target = self.path.joinpath(*pure_path.parts).resolve()
        return target.is_relative_to(self.path) and target.is_file()


def _image_mime(mime_type: str | None, filename: str) -> bool:
    return bool((mime_type or '').lower().startswith('image/')) or Path(filename).suffix.lower() in {
        '.gif', '.jpg', '.jpeg', '.png', '.webp', '.svg'
    }


def _rewrite_asset_urls(content_html: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return content_html
    soup = BeautifulSoup(content_html or '', 'html.parser')
    for tag in soup.find_all(True):
        for attribute in ('src', 'href'):
            value = tag.get(attribute)
            if value in replacements:
                tag[attribute] = replacements[value]
    return str(soup)


def _store_inline_images(content_html: str, asset_cache: dict, uploaded_this_task: list, storage_folder: str) -> str:
    """Move images embedded in task HTML to Drive so the database stays small."""
    if 'data:image/' not in content_html:
        return content_html
    soup = BeautifulSoup(content_html, 'html.parser')
    extensions = {'image/gif': 'gif', 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}
    for image in soup.find_all('img', src=True):
        data_url = image['src']
        if not data_url.startswith('data:image/'):
            continue
        header, separator, encoded = data_url.partition(',')
        mime_type = header[5:].split(';', 1)[0].lower()
        if not separator or ';base64' not in header.lower() or mime_type not in extensions:
            raise ValueError('Неподдерживаемый формат встроенного изображения.')
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError('Повреждённое встроенное изображение.') from exc
        if not image_bytes or len(image_bytes) > 15 * 1024 * 1024:
            raise ValueError('Встроенное изображение пустое или превышает 15 МБ.')
        digest = hashlib.sha256(image_bytes).hexdigest()
        cache_key = f'inline:{digest}'
        stored = asset_cache.get(cache_key)
        if stored is None:
            filename = f'inline_{digest[:20]}.{extensions[mime_type]}'
            upload = FileStorage(stream=BytesIO(image_bytes), filename=filename, content_type=mime_type)
            storage_key = storage.upload_file(upload, folder=storage_folder)
            stored = {'storage_key': storage_key, 'download_url': _drive_asset_url(storage_key)}
            asset_cache[cache_key] = stored
            uploaded_this_task.append((cache_key, storage_key))
        image['src'] = stored['download_url']
    return str(soup)


def _content_fingerprint(source: BankSource, task_data: dict, asset_hash_cache: dict[str, str]) -> str:
    asset_identities = []
    content_html = task_data.get('content_html') or ''
    for inline_image in re.finditer(r'data:image/[a-zA-Z.+-]+;base64,[A-Za-z0-9+/=]+', content_html):
        asset_identities.append(f'inline:{hashlib.sha256(inline_image.group().encode("ascii")).hexdigest()}')
    for attachment in task_data.get('attached_files') or []:
        archive_path = attachment.get('archive_path')
        if archive_path and source.exists(archive_path):
            digest = asset_hash_cache.get(archive_path)
            if digest is None:
                digest = hashlib.sha256(source.read(archive_path)).hexdigest()
                asset_hash_cache[archive_path] = digest
            asset_identities.append(f'sha256:{digest}')
        elif attachment.get('source_url'):
            asset_identities.append(f"url:{attachment['source_url']}")
    return _fingerprint(content_html + '\n' + '\n'.join(sorted(set(asset_identities))))


def _has_single_value_answer(answer: str | None) -> bool:
    value = (answer or '').strip()
    return bool(re.fullmatch(r'(?:[+-]?\d+(?:[.,]\d+)?|[A-Za-zА-Яа-яЁё]+)', value))


@click.command('openfipi-bank-import')
@click.option('--source', 'source_path', type=click.Path(exists=True, path_type=Path), required=True,
              help='Полный ZIP-архив либо папка после распаковки пакета карточек и всех частей медиа.')
@click.option('--course-slug', default='ege_informatics', show_default=True)
@click.option('--limit', type=click.IntRange(0, 100000), default=0, show_default=True,
              help='0 — все карточки из архива.')
@click.option('--dry-run', is_flag=True, help='Проверить состав и наличие файлов без записи в БД и Google Drive.')
@click.option('--activate-ready', is_flag=True,
              help='Активировать актуальные нумерованные задания с одним значением ответа и всеми файлами; ответы источника помечаются непроверенными.')
@with_appcontext
def openfipi_bank_import_command(source_path: Path, course_slug: str, limit: int, dry_run: bool, activate_ready: bool):
    """Загрузить подготовленный банк OpenFIPI и его файлы в подключённую платформу."""
    if not source_path.is_file() and not source_path.is_dir():
        raise click.ClickException('Путь источника должен быть ZIP-файлом или папкой.')
    try:
        source = BankSource(source_path)
    except Exception as exc:
        raise click.ClickException(f'Не удалось открыть источник заданий: {type(exc).__name__}: {exc}') from exc

    try:
        task_names = source.task_names()
        if not task_names:
            raise click.ClickException('В источнике не найдены файлы tasks/*.json.')
        if not source.exists('manifest.json'):
            raise click.ClickException('В источнике не найден manifest.json.')
        if limit:
            task_names = task_names[:limit]

        try:
            course = _resolve_course(course_slug)
        except Exception:
            if not dry_run:
                raise
            course = None

        if not dry_run and (current_app.config.get('STORAGE_BACKEND') != 'google_drive' or not storage.use_google_drive):
            raise click.ClickException(
                'Импорт остановлен: на сервере не подключён Google Drive. Настрой STORAGE_BACKEND=google_drive '
                'и учётные данные приложения с доступом к папке хранилища.'
            )

        if dry_run:
            media_refs = 0
            local_files = 0
            missing_files = 0
            answers = 0
            inline_image_refs = 0
            unique_inline_images = set()
            for name in task_names:
                task = json.loads(source.read(name))
                answers += bool(task.get('answer'))
                for match in re.finditer(r'data:image/[a-zA-Z.+-]+;base64,[A-Za-z0-9+/=]+', task.get('content_html') or ''):
                    inline_image_refs += 1
                    unique_inline_images.add(hashlib.sha256(match.group().encode('ascii')).digest())
                for attachment in task.get('attached_files') or []:
                    media_refs += 1
                    asset_path = attachment.get('archive_path')
                    if asset_path and source.exists(asset_path):
                        local_files += 1
                    elif attachment.get('source_url'):
                        missing_files += 1
            click.echo(
                f'Проверка пройдена: карточек {len(task_names)}, с ответом из источника {answers}, '
                f'ссылок на медиа {media_refs}, локальных файлов {local_files}, файлов недоступны {missing_files}. '
                f'Встроенных изображений {inline_image_refs}, уникальных {len(unique_inline_images)}. '
                'База и Google Drive не изменялись.'
            )
            return

        counts = {'seen': len(task_names), 'imported': 0, 'already_present': 0, 'failed': 0, 'drive_assets_uploaded': 0, 'inactive_missing_data': 0}
        asset_cache: dict[str, dict] = {}
        asset_hash_cache: dict[str, str] = {}
        for name in task_names:
            task_data = json.loads(source.read(name))
            source_id = str(task_data.get('source_id') or '').strip()
            if not source_id:
                counts['failed'] += 1
                click.echo(f'Пропущен файл без source_id: {name}', err=True)
                continue
            source_key = str(task_data.get('source_key') or f'openfipi:ege-informatics:{source_id.lower()}').strip()
            if not source_key or len(source_key) > 190:
                counts['failed'] += 1
                click.echo(f'Пропущен файл с некорректным source_key: {name}', err=True)
                continue
            if Tasks.query.filter_by(source_key=source_key).first():
                counts['already_present'] += 1
                continue

            fingerprint = _content_fingerprint(source, task_data, asset_hash_cache)
            if Tasks.query.filter_by(course_id=course.id, content_fingerprint=fingerprint).first():
                counts['already_present'] += 1
                continue

            uploaded_this_task: list[tuple[str, str]] = []
            try:
                storage_folder = str(task_data.get('storage_folder') or 'openfipi/ege-informatics').strip().strip('/')
                if (not storage_folder or len(storage_folder) > 120
                        or not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+){0,5}', storage_folder)):
                    raise ValueError('У пакета указана некорректная папка Google Drive.')
                source_name = str(task_data.get('source_name') or 'Открытый банк ФИПИ через OpenFIPI').strip()
                if not source_name or len(source_name) > 160:
                    raise ValueError('У пакета указано некорректное название источника.')
                task_group_id = str(task_data.get('task_group_id') or '').strip() or None
                if task_group_id and len(task_group_id) > 64:
                    raise ValueError('Идентификатор группы заданий превышает 64 символа.')
                attachments_json = []
                replacements = {}
                has_missing_media = False
                for attachment in task_data.get('attached_files') or []:
                    source_url = attachment.get('source_url') or ''
                    archive_path = attachment.get('archive_path')
                    stored = asset_cache.get(archive_path) if archive_path else None
                    if archive_path and not stored:
                        if not source.exists(archive_path):
                            raise FileNotFoundError(f"Файл задания отсутствует в пакете: {archive_path}")
                        asset_bytes = source.read(archive_path)
                        filename = secure_filename(attachment.get('name') or PurePosixPath(archive_path).name) or 'asset'
                        mime_type = attachment.get('mime_type') or 'application/octet-stream'
                        uploaded = FileStorage(stream=BytesIO(asset_bytes), filename=filename, content_type=mime_type)
                        storage_key = storage.upload_file(uploaded, folder=storage_folder)
                        download_url = _drive_asset_url(storage_key) if storage_key.startswith('gdrive://') else None
                        stored = {
                            'storage_key': storage_key,
                            'download_url': download_url,
                            'name': filename,
                            'mime_type': mime_type,
                        }
                        asset_cache[archive_path] = stored
                        uploaded_this_task.append((archive_path, storage_key))
                    if stored:
                        download_url = stored['download_url']
                        if download_url:
                            replacements[archive_path] = download_url
                        if not download_url:
                            raise RuntimeError('Google Drive не вернул ссылку на сохранённый файл.')
                    else:
                        has_missing_media = True
                        if archive_path and source_url:
                            replacements[archive_path] = source_url
                        stored = {
                            'storage_key': None,
                            'download_url': None,
                            'name': attachment.get('name') or PurePosixPath(urlsplit(source_url).path).name or 'asset',
                            'mime_type': attachment.get('mime_type'),
                        }
                    is_image = _image_mime(stored['mime_type'], stored['name'])
                    attachments_json.append({
                        'name': stored['name'],
                        'path': stored['download_url'],
                        'url': source_url,
                        'source_url': source_url,
                        'download_url': stored['download_url'],
                        'preview_url': stored['download_url'] if is_image else None,
                        'mime_type': stored['mime_type'],
                        'storage_key': stored['storage_key'],
                        'download_status': attachment.get('download_status') or 'stored',
                    })

                rendered_html = _rewrite_asset_urls(task_data.get('content_html') or '', replacements)
                rendered_html = _store_inline_images(rendered_html, asset_cache, uploaded_this_task, storage_folder)
                if not rendered_html.strip():
                    raise ValueError('У задания пустое условие после импорта.')
                try:
                    source_number = int(task_data.get('source_task_number') or 0)
                except (TypeError, ValueError):
                    source_number = 0
                is_current = bool(task_data.get('is_current'))
                try:
                    requested_task_number = int(task_data.get('task_number') or 0)
                except (TypeError, ValueError):
                    requested_task_number = 0
                platform_number = requested_task_number if 1 <= requested_task_number <= 99 else (
                    source_number if is_current and 1 <= source_number <= 27 else 0
                )
                has_answer = bool(task_data.get('answer'))
                has_single_value_answer = _has_single_value_answer(task_data.get('answer'))
                # Historical cards remain unnumbered so they can be used as training, not misrepresented as a current prototype.
                ready_for_use = bool(activate_ready and has_single_value_answer and not has_missing_media)
                task = Tasks(
                    course_id=course.id,
                    task_number=platform_number,
                    task_group_id=task_group_id,
                    site_task_id=source_id,
                    source_url=task_data.get('source_url'),
                    source_name=source_name,
                    source_year=task_data.get('source_year'),
                    source_task_number=source_number or None,
                    exam_year=task_data.get('exam_year'),
                    source_key=source_key,
                    content_fingerprint=fingerprint,
                    prototype_status=task_data.get('prototype_status') or ('real' if is_current else 'practice_only'),
                    ingest_status='ready' if ready_for_use else 'needs_answer_review' if has_answer else 'needs_answer',
                    content_html=rendered_html,
                    answer=task_data.get('answer'),
                    attached_files=json.dumps(attachments_json, ensure_ascii=False) if attachments_json else '',
                    difficulty_level=task_data.get('difficulty_level') or _difficulty_estimate(source_number),
                    hints=task_data.get('hints'),
                    bank_origin='scraped',
                    answer_spec=task_data.get('answer_spec') or {'type': 'short_answer'},
                    is_active=ready_for_use,
                )
                db.session.add(task)
                db.session.flush()
                solution_text = str(task_data.get('solution') or '').strip()
                if solution_text:
                    db.session.add(TaskSolution(
                        task_id=task.task_id,
                        solution_text=solution_text,
                        source=task_data.get('solution_source') or 'manual',
                        needs_manual_review=bool(task_data.get('solution_needs_review', True)),
                    ))
                review = TaskReview(
                    task_id=task.task_id,
                    status='new',
                    notes=(task_data.get('review_notes') or (
                        f'Импортировано из источника «{source_name}». Ответы не проверены; '
                        'сложность и статус прототипа доступны для проверки и редактирования.'
                    )),
                )
                db.session.add(review)
                db.session.commit()
                counts['imported'] += 1
                counts['drive_assets_uploaded'] += len(uploaded_this_task)
                if activate_ready and not task.is_active:
                    counts['inactive_missing_data'] += 1
                if counts['imported'] % 25 == 0:
                    click.echo(
                        f"В этом запуске добавлено {counts['imported']}; "
                        f"загружено файлов в Drive {counts['drive_assets_uploaded']}."
                    )
            except Exception as exc:
                db.session.rollback()
                for archive_path, storage_key in uploaded_this_task:
                    asset_cache.pop(archive_path, None)
                    try:
                        storage.delete_file(storage_key)
                    except Exception:
                        current_app.logger.exception('Failed to clean up OpenFIPI asset %s', storage_key)
                counts['failed'] += 1
                current_app.logger.exception('OpenFIPI task import failed for source id %s', source_id)
                raise click.ClickException(
                    f"Импорт остановлен на задании {source_id}: {type(exc).__name__}: {exc}. "
                    f"Уже сохранено {counts['imported']} карточек; повторный запуск безопасно пропустит их."
                ) from exc

        click.echo(
            f"Импорт OpenFIPI: просмотрено {counts['seen']}, добавлено {counts['imported']}, "
            f"уже было {counts['already_present']}, файлов отправлено в Drive {counts['drive_assets_uploaded']}, "
            f"ошибок {counts['failed']}, оставлено неактивными из-за данных {counts['inactive_missing_data']}."
        )
    finally:
        source.close()
