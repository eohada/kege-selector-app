"""
Upload routes for S3/local storage.
Supports both JSON API responses and HTMX HTML fragments.
"""
from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify, render_template_string
from flask_login import login_required, current_user

from app.storage.s3_service import storage

logger = logging.getLogger(__name__)

storage_bp = Blueprint('storage', __name__, url_prefix='/storage')

ALLOWED_EXTENSIONS = {
    'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'zip', 'rar', 'mp3', 'mp4',
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


HTMX_FILE_ITEM = """
<div class="flex items-center gap-2 p-2 bg-bg-app rounded-btn text-sm"
     data-file-key="{{ key }}">
  <span class="truncate flex-1">{{ name }}</span>
  <a href="{{ url }}" target="_blank"
     class="text-accent hover:underline text-xs">открыть</a>
  <input type="hidden" name="file_keys[]" value="{{ key }}">
</div>
"""


@storage_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """
    Accept multipart file upload.
    Returns JSON or HTMX HTML fragment based on HX-Request header.
    """
    if 'file' not in request.files:
        return _error_response('Файл не найден в запросе', 400)

    uploaded = request.files.getlist('file')
    if not uploaded or not uploaded[0].filename:
        return _error_response('Файл не выбран', 400)

    folder = request.form.get('folder', 'uploads')
    results = []

    for f in uploaded:
        if not f.filename:
            continue

        if not _allowed_file(f.filename):
            return _error_response(
                f'Недопустимый формат файла: {f.filename}', 400,
            )

        f.stream.seek(0, 2)
        size = f.stream.tell()
        f.stream.seek(0)

        if size > MAX_FILE_SIZE:
            return _error_response(
                f'Файл слишком большой: {f.filename} ({size // 1024 // 1024} МБ)', 400,
            )

        try:
            key = storage.upload_file(f, folder=folder)
            url = storage.get_url(key)
            results.append({
                'key': key,
                'name': f.filename,
                'url': url,
                'size': size,
            })
        except Exception as e:
            logger.error(f"Upload failed for {f.filename}: {e}", exc_info=True)
            return _error_response(f'Ошибка загрузки: {f.filename}', 500)

    is_htmx = request.headers.get('HX-Request') == 'true'

    if is_htmx:
        html_parts = []
        for r in results:
            html_parts.append(render_template_string(
                HTMX_FILE_ITEM,
                key=r['key'],
                name=r['name'],
                url=r['url'],
            ))
        return '\n'.join(html_parts), 200

    return jsonify({'success': True, 'files': results}), 200


def _error_response(message: str, status: int):
    is_htmx = request.headers.get('HX-Request') == 'true'
    if is_htmx:
        return (
            f'<div class="text-red-500 text-sm p-2">{message}</div>',
            status,
        )
    return jsonify({'success': False, 'error': message}), status
