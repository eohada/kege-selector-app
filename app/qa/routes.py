import os
import uuid
import json
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from core.db_models import db, QATestCase, QAReport, QAReportHistory
from app.auth.rbac_utils import require_role
from sqlalchemy.orm.attributes import flag_modified
from . import qa_tester_bp

QA_ROLES = ('tester', 'chief_tester', 'admin', 'creator', 'chief_admin')
QA_AREAS = [
    'Авторизация и доступ',
    'Биллинг и подписки',
    'Админка',
    'Курсы и уроки',
    'Генератор задач',
    'Песочница (Sandbox)',
    'Telegram',
    'Библиотека',
    'Workspace',
    'Мобильная версия',
    'Общая',
]

def qa_access_required(f):
    return require_role(*QA_ROLES)(f)

def _get_upload_dir():
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    upload_dir = os.path.join(base_dir, 'static', 'uploads', 'qa')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

def _save_uploaded_file(file_obj, allowed_exts=None):
    raw_name = file_obj.filename or 'file'
    ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else 'png'
    if allowed_exts and ext not in allowed_exts:
        ext = allowed_exts[0]
    filename = f"qa_{uuid.uuid4().hex[:12]}.{ext}"
    upload_dir = _get_upload_dir()
    filepath = os.path.join(upload_dir, filename)
    file_obj.save(filepath)
    file_url = url_for('static', filename=f'uploads/qa/{filename}')
    return file_url, filename, ext


@qa_tester_bp.route('/')
@login_required
@qa_access_required
def index():
    tests = QATestCase.query.filter_by(is_active=True).order_by(QATestCase.area, QATestCase.id).all()
    passed_test_ids = set()
    retest_test_ids = set()
    bug_test_ids = set()
    adhoc_reports = []
    
    user_reports = QAReport.query.filter_by(reporter_id=current_user.id).all()
    for r in user_reports:
        if r.test_id:
            if r.status == 'retest':
                retest_test_ids.add(r.test_id)
            elif r.verdict == 'success' or r.status == 'resolved':
                passed_test_ids.add(r.test_id)
            else:
                bug_test_ids.add(r.test_id)
        else:
            adhoc_reports.append(r)

    tests_by_area = {}
    for test in tests:
        if test.area not in tests_by_area:
            tests_by_area[test.area] = []
        tests_by_area[test.area].append(test)
        
    for r in adhoc_reports:
        area = r.area or 'Общая'
        if area not in tests_by_area:
            tests_by_area[area] = []
        tests_by_area[area].append(r)

    area_progress = {}
    for area, area_items in tests_by_area.items():
        total = len(area_items)
        done = 0
        for item in area_items:
            if hasattr(item, 'steps'):
                if item.id in passed_test_ids and item.id not in retest_test_ids:
                    done += 1
            else:
                if item.status == 'resolved':
                    done += 1
                
        area_progress[area] = {'total': total, 'done': done, 'pct': int(done / total * 100) if total else 0}

    return render_template(
        'qa_tester/index.html',
        tests_by_area=tests_by_area,
        passed_test_ids=passed_test_ids,
        retest_test_ids=retest_test_ids,
        bug_test_ids=bug_test_ids,
        area_progress=area_progress,
    )


@qa_tester_bp.route('/report/<int:report_id>/update', methods=['POST'])
@login_required
@qa_access_required
def update_report(report_id):
    report = QAReport.query.get_or_404(report_id)
    if report.reporter_id != current_user.id:
        return jsonify({'error': 'Нет доступа'}), 403

    verdict = request.form.get('verdict')
    description = request.form.get('description', '').strip()
    tester_comment = request.form.get('tester_comment', '').strip()
    cycle_id = request.form.get('cycle_id', type=int)

    if not verdict:
        return jsonify({'error': 'Необходимо выбрать вердикт'}), 400

    if report.status not in ('retest', 'pending'):
        return jsonify({'error': 'Репорт заблокирован (не на ретесте)'}), 403

    old_status = report.status
    new_status = 'resolved' if verdict == 'success' else 'pending'
    
    report.verdict = verdict
    report.status = new_status
    if description:
        report.description = description
    if cycle_id:
        report.cycle_id = cycle_id

    completed_steps_raw = request.form.get('completed_steps', '[]')
    try:
        report.failed_steps = json.loads(completed_steps_raw)
    except Exception:
        pass

    if old_status != new_status or tester_comment:
        last_hist = QAReportHistory.query.filter_by(report_id=report.id).order_by(QAReportHistory.id.desc()).first()
        history_comment = tester_comment or f"Тестировщик обновил вердикт на '{verdict}'"
        if not last_hist or last_hist.new_status != new_status or last_hist.comment != history_comment:
            history_entry = QAReportHistory(
                report_id=report.id,
                author_id=current_user.id,
                old_status=old_status,
                new_status=new_status,
                comment=history_comment,
            )
            db.session.add(history_entry)

    db.session.commit()
    
    tab_target = 'done' if verdict == 'success' else 'new'
    if report.status == 'retest':
        tab_target = 'attention'
        
    return jsonify({
        'success': True,
        'status': new_status,
        'verdict': verdict,
        'tab': tab_target,
    })


@qa_tester_bp.route('/test/<int:test_id>')
@login_required
@qa_access_required
def execute_test(test_id):
    test = QATestCase.query.get_or_404(test_id)
    existing_report = QAReport.query.filter_by(test_id=test.id, reporter_id=current_user.id).first()
    failed_steps = existing_report.failed_steps if existing_report and existing_report.failed_steps else []
    is_readonly = bool(existing_report and existing_report.status != 'retest')

    admin_comment = None
    if existing_report and existing_report.status == 'retest':
        last_history = QAReportHistory.query.filter_by(
            report_id=existing_report.id, new_status='retest'
        ).order_by(QAReportHistory.created_at.desc()).first()
        if last_history:
            admin_comment = last_history.comment

    history = QAReportHistory.query.filter_by(
        report_id=existing_report.id
    ).order_by(QAReportHistory.created_at.asc()).all() if existing_report else []

    return render_template(
        'qa_tester/execute.html',
        test=test,
        qa_areas=QA_AREAS,
        existing_report=existing_report,
        failed_steps=failed_steps,
        admin_comment=admin_comment,
        history=history,
        is_readonly=is_readonly,
    )


@qa_tester_bp.route('/test/<int:test_id>/submit', methods=['POST'])
@login_required
@qa_access_required
def submit_test(test_id):
    test = QATestCase.query.get_or_404(test_id)
    verdict = request.form.get('verdict')
    description = request.form.get('description', '').strip()
    tester_comment = request.form.get('tester_comment', '').strip()

    completed_steps_raw = request.form.get('completed_steps', '[]')
    try:
        completed_steps = json.loads(completed_steps_raw)
    except Exception:
        completed_steps = []

    attachments_raw = request.form.get('attachments_json', '[]')
    try:
        attachments = json.loads(attachments_raw)
    except Exception:
        attachments = []

    logs_raw = request.form.get('logs_json', '[]')
    try:
        logs = json.loads(logs_raw)
    except Exception:
        logs = []

    if not verdict:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Необходимо выбрать вердикт'}), 400
        flash('Необходимо выбрать вердикт', 'error')
        return redirect(url_for('qa_tester.execute_test', test_id=test.id))

    report = QAReport.query.filter_by(test_id=test.id, reporter_id=current_user.id).first()
    new_status = 'resolved' if verdict == 'success' else 'pending'
    
    if report:
        if report.status not in ('retest', 'pending'):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Репорт заблокирован (не на ретесте)'}), 403
            flash('Репорт заблокирован. Ждите ретеста от администратора.', 'error')
            return redirect(url_for('qa_tester.execute_test', test_id=test.id))

        old_status = report.status
        report.verdict = verdict
        report.status = new_status
        report.failed_steps = completed_steps
        flag_modified(report, "failed_steps")
        report.page_url = request.form.get('page_url', report.page_url or '')
        report.user_agent = request.headers.get('User-Agent', '')
        report.screen_size = request.form.get('screen_size', report.screen_size or '')
        if description:
            report.description = description

        if attachments:
            existing_atts = report.attachments or []
            existing_urls = {a.get('url') for a in existing_atts}
            for att in attachments:
                if att.get('url') not in existing_urls:
                    existing_atts.append(att)
            report.attachments = existing_atts
            flag_modified(report, "attachments")

        if logs:
            existing_logs = report.logs or []
            existing_logs.extend(logs)
            report.logs = existing_logs
            flag_modified(report, "logs")

        db.session.add(report)
        db.session.flush()

        if old_status != new_status or tester_comment:
            last_history = QAReportHistory.query.filter_by(
                report_id=report.id, 
                author_id=current_user.id
            ).order_by(QAReportHistory.created_at.desc()).first()

            history_comment = tester_comment or f"Тестировщик обновил вердикт на '{verdict}'"
            
            if not last_history or last_history.comment != history_comment:
                history_entry = QAReportHistory(
                    report_id=report.id,
                    author_id=current_user.id,
                    old_status=old_status,
                    new_status=new_status,
                    comment=history_comment,
                )
                db.session.add(history_entry)
    else:
        report = QAReport(
            test_id=test.id,
            reporter_id=current_user.id,
            area=test.area,
            status=new_status,
            verdict=verdict,
            description=description or tester_comment,
            failed_steps=completed_steps,
            page_url=request.form.get('page_url', ''),
            user_agent=request.headers.get('User-Agent', ''),
            screen_size=request.form.get('screen_size', ''),
            attachments=attachments if attachments else None,
            logs=logs if logs else None,
            cycle_id=1,
        )
        db.session.add(report)
        db.session.flush()

        history_entry = QAReportHistory(
            report_id=report.id,
            author_id=current_user.id,
            old_status=None,
            new_status=new_status,
            comment=tester_comment or f"Первичный репорт: вердикт '{verdict}'",
        )
        db.session.add(history_entry)

    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        tab_target = 'done' if verdict == 'success' else 'new'
        if report.status == 'retest':
            tab_target = 'attention'
        return jsonify({
            'success': True,
            'status': new_status,
            'verdict': verdict,
            'tab': tab_target,
        })

    if verdict == 'success':
        flash('Тест успешно пройден!', 'success')
    else:
        flash('Баг-репорт отправлен разработчикам', 'warning')

    return redirect(url_for('qa_tester.execute_test', test_id=test.id))

@qa_tester_bp.route('/upload-screenshot', methods=['POST'])
@login_required
@qa_access_required
def upload_screenshot():
    if 'image' not in request.files:
        return jsonify({'error': 'Нет файла'}), 400
    file = request.files['image']
    if not file.filename:
        return jsonify({'error': 'Пустое имя файла'}), 400
    url, fname, _ = _save_uploaded_file(file, allowed_exts=['png', 'jpg', 'jpeg', 'webp'])
    return jsonify({'success': True, 'url': url, 'filename': fname})

@qa_tester_bp.route('/upload-video', methods=['POST'])
@login_required
@qa_access_required
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'Нет файла'}), 400
    file = request.files['video']
    if not file.filename:
        return jsonify({'error': 'Пустое имя файла'}), 400
    url, fname, _ = _save_uploaded_file(file, allowed_exts=['mp4', 'webm', 'mov'])
    return jsonify({'success': True, 'url': url, 'filename': fname})

@qa_tester_bp.route('/ad-hoc', methods=['GET', 'POST'])
@login_required
@qa_access_required
def ad_hoc_bug():
    if request.method == 'GET':
        dummy_test = {
            'id': 'ad-hoc',
            'title': 'Спонтанный баг (Ad-Hoc)',
            'description': 'Опишите найденную проблему, которая не привязана к конкретному тест-кейсу. Укажите шаги для воспроизведения и прикрепите скриншоты, если необходимо.',
            'area': 'Общая',
            'priority': 'medium',
            'steps': ['Опишите ваши действия', 'Что вы ожидали увидеть', 'Что произошло на самом деле']
        }
        return render_template('qa_tester/execute.html', test=dummy_test, report=None, is_adhoc=True, is_readonly=False, qa_areas=QA_AREAS)

    if request.method == 'POST':
        area = request.form.get('area', 'Общая')
        verdict = request.form.get('verdict', 'minor')
        description = request.form.get('description', '').strip()

        if not description:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Опишите баг'}), 400
            flash('Опишите баг', 'error')
            return redirect(url_for('qa_tester.ad_hoc_bug'))

        recent_report = QAReport.query.filter_by(
            reporter_id=current_user.id,
            description=description,
            area=area
        ).order_by(QAReport.created_at.desc()).first()

        if recent_report:
            from datetime import datetime
            time_diff = (datetime.utcnow() - recent_report.created_at).total_seconds()
            if time_diff < 10:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'message': 'Баг уже был отправлен.'})
                return redirect(url_for('qa_tester.index'))

        attachments_raw = request.form.get('attachments_json', '[]')
        try:
            attachments = json.loads(attachments_raw)
        except Exception:
            attachments = []

        logs_raw = request.form.get('logs_json', '[]')
        try:
            logs = json.loads(logs_raw)
        except Exception:
            logs = []

        report = QAReport(
            test_id=None,
            reporter_id=current_user.id,
            area=area,
            status='pending',
            verdict=verdict,
            description=description,
            page_url=request.form.get('page_url', ''),
            user_agent=request.headers.get('User-Agent', ''),
            screen_size=request.form.get('screen_size', ''),
            attachments=attachments if attachments else None,
            logs=logs if logs else None,
            cycle_id=1,
        )
        db.session.add(report)
        db.session.flush()

        history_entry = QAReportHistory(
            report_id=report.id,
            author_id=current_user.id,
            old_status=None,
            new_status='pending',
            comment=f"Первичный Ad-hoc репорт: вердикт '{verdict}'"
        )
        db.session.add(history_entry)
        db.session.commit()
        
        try:
            from app.utils.tg_notifier import send_tg_message, ADMIN_TG_ID
            import logging
            logger = logging.getLogger(__name__)
            tester_name = current_user.username or "Неизвестный"
            send_tg_message(ADMIN_TG_ID, f"🐛 НОВЫЙ БАГ (Ad-hoc)!\nОт: {tester_name}\nЗона: {area}\nСуть: {description[:100]}...")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to send tg message: {e}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'tab': 'attention'})

        flash('Спонтанный баг зарегистрирован!', 'success')
        return redirect(url_for('qa_tester.index'))

@qa_tester_bp.route('/history')
@login_required
@qa_access_required
def history():
    reports = QAReport.query.filter_by(reporter_id=current_user.id).order_by(QAReport.created_at.desc()).all()
    return render_template('qa_tester/history.html', reports=reports)
