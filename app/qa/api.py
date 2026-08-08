from flask import Blueprint, request, jsonify
from core.db_models import db, QAReport, User
from app.qa.routes import _save_uploaded_file
import json
import logging

qa_api_bp = Blueprint('qa_api', __name__, url_prefix='/api/qa')

@qa_api_bp.route('/desktop-report', methods=['POST'])
def desktop_report():
    """
    Открытый (или защищенный простым API ключом) эндпоинт для Desktop Companion.
    """
    auth_header = request.headers.get('Authorization')
    if auth_header != "Bearer QA_COMPANION_SECRET_TOKEN_2026":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    # Ищем дефолтного пользователя-тестера (от лица которого будут публиковаться Desktop баги)
    # Или можно передавать username в теле запроса
    reporter = User.query.filter(User.username.like('qa_%')).first()
    reporter_id = reporter.id if reporter else 1 
    
    area = request.form.get('area', 'Общая')
    verdict = request.form.get('verdict', 'minor')
    description = request.form.get('description', 'Desktop Report')
    
    # Обработка файла видео
    attachments = []
    if 'video' in request.files:
        file = request.files['video']
        if file.filename:
            try:
                url, fname, _ = _save_uploaded_file(file, allowed_exts=['mp4', 'webm', 'mov'])
                attachments.append({"url": url, "type": "video", "name": fname})
                logging.info(f"Desktop video saved: {url}")
            except Exception as e:
                logging.error(f"Save video error: {e}")
                
    if 'image' in request.files:
        file = request.files['image']
        if file.filename:
            try:
                url, fname, _ = _save_uploaded_file(file, allowed_exts=['png', 'jpg', 'jpeg', 'webp'])
                attachments.append({"url": url, "type": "image", "name": fname})
                logging.info(f"Desktop image saved: {url}")
            except Exception as e:
                logging.error(f"Save image error: {e}")

    try:
        new_report = QAReport(
            test_id=None,
            reporter_id=reporter_id,
            verdict=verdict,
            description=f"{description}\n\n*[Отправлено через BooStudy Desktop Companion]*",
            area=area,
            logs='[]',
            attachments=json.dumps(attachments) if attachments else None
        )
        db.session.add(new_report)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True})
