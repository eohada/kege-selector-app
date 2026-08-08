import os
import uuid
import json
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from core.db_models import db, QATestCase, QAReport, QAReportHistory, TestCase, TestStep, BugReport, BugReportComment
from core.audit_logger import audit_logger
from app import csrf
from app.auth.rbac_utils import require_role
from sqlalchemy.orm.attributes import flag_modified
from . import qa_tester_bp

QA_ROLES = ('tester', 'chief_tester', 'admin', 'creator', 'chief_admin')
QA_AREAS = [
    '1. Вход и деньги',
    '2. Админка и управление',
    '3. Мобильный инспектор',
    '4. Библиотека знаний',
    '5. Задачи, домашка, генератор',
    '6. Кодерская',
    '7. Тг, уведомления, родители',
    '666',
    '777'
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
def index():
    """Кабинет тестировщика V2 (/tester)"""
    if not (current_user.is_admin() or current_user.is_creator() or getattr(current_user, 'role', '') in QA_ROLES):
        flash('Доступ запрещен. Кабинет предназначен только для роли Тестировщик.', 'danger')
        return redirect(url_for('main.dashboard'))

    assigned_cases = TestCase.query.filter(
        (TestCase.assigned_to_id == current_user.id) | (TestCase.assigned_to_id.is_(None))
    ).order_by(TestCase.area, TestCase.id.desc()).all()

    my_bug_reports = BugReport.query.filter_by(reporter_id=current_user.id).order_by(BugReport.id.desc()).all()

    # Group tests by area
    cases_by_area = {}
    for tc in assigned_cases:
        area_key = tc.area or 'Общая'
        if area_key not in cases_by_area:
            cases_by_area[area_key] = []
        cases_by_area[area_key].append(tc)

    return render_template(
        'sandbox/tester/dashboard.html',
        assigned_cases=assigned_cases,
        cases_by_area=cases_by_area,
        my_bug_reports=my_bug_reports
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

    if not logs and current_user and current_user.is_authenticated:
        try:
            from core.db_models import AuditLog
            recent_audit = AuditLog.query.filter_by(user_id=current_user.id).order_by(AuditLog.timestamp.desc()).limit(25).all()
            logs = [{
                'timestamp': a.timestamp.isoformat() if a.timestamp else '',
                'action': a.action,
                'entity': a.entity,
                'entity_id': a.entity_id,
                'status': a.status,
                'metadata': a.log_metadata
            } for a in recent_audit]
        except Exception as e:
            current_app.logger.warning(f"Failed to auto-bind recent 25 audit logs: {e}")

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


@qa_tester_bp.route('/test-cases/<int:tc_id>/status', methods=['POST'])
@qa_tester_bp.route('/api/qa/test-cases/<int:tc_id>/status', methods=['POST'])
@csrf.exempt
@login_required
def update_test_case_status(tc_id):
    """Обновление статуса тест-кейса тестировщиком (PASSED / FAILED / ACTIVE)"""
    tc = TestCase.query.get(tc_id)
    if not tc:
        return jsonify({'success': False, 'message': f'Тест-кейс #{tc_id} не найден'}), 444

    if not (current_user.is_admin() or current_user.is_creator() or getattr(current_user, 'role', '') in QA_ROLES or tc.assigned_to_id == current_user.id):
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    new_status = data.get('status', '').upper()
    if new_status not in ('PASSED', 'FAILED', 'ACTIVE', 'DRAFT'):
        return jsonify({'success': False, 'message': 'Невалидный статус'}), 400

    try:
        tc.status = new_status
        db.session.commit()
        audit_logger.log(action='update_test_case_status', entity='TestCase', entity_id=tc.id, status='success', metadata={'status': new_status})
        return jsonify({'success': True, 'status': new_status, 'message': f'Статус изменен на {new_status}'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Ошибка обновления: {str(e)}'}), 500


@qa_tester_bp.route('/api/qa/assigned-test-cases', methods=['GET'])
@qa_tester_bp.route('/api/qa/assigned-tests', methods=['GET'])
@login_required
def get_assigned_test_cases():
    """Эндпоинт для виджета QA Companion: список тест-кейсов, назначенных на текущего тестировщика"""
    if not (current_user.is_admin() or current_user.is_creator() or getattr(current_user, 'role', '') in QA_ROLES):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403

    assigned = TestCase.query.filter(
        (TestCase.assigned_to_id == current_user.id) | (TestCase.assigned_to_id.is_(None))
    ).order_by(TestCase.area, TestCase.id.desc()).all()

    results = [{
        'id': tc.id,
        'title': tc.title,
        'area': tc.area,
        'status': tc.status
    } for tc in assigned]

    return jsonify({'success': True, 'test_cases': results})


@qa_tester_bp.route('/api/qa/test-cases/<int:tc_id>', methods=['GET'])
@login_required
def get_test_case_detail(tc_id):
    """Детальные данные тест-кейса с шагами и списком прикрепленных баг-репортов"""
    tc = db.session.get(TestCase, tc_id) or TestCase.query.get(tc_id)
    if not tc:
        return jsonify({'success': False, 'message': f'Тест-кейс #{tc_id} не найден'}), 444

    # Fetch all attached bug reports (one-to-many)
    all_bugs = BugReport.query.filter_by(test_case_id=tc.id).order_by(BugReport.id.desc()).all()
    bug_reports_list = []
    for b in all_bugs:
        comments_list = [{
            'id': c.id,
            'author_name': c.author.username if c.author else 'Пользователь',
            'author_role': c.author.role if c.author else 'user',
            'text': c.text,
            'created_at': c.created_at.strftime('%d.%m %H:%M') if c.created_at else ''
        } for c in b.comments]

        bug_reports_list.append({
            'id': b.id,
            'title': b.title,
            'severity': b.severity,
            'status': b.status,
            'test_step_id': b.test_step_id,
            'step_failed': b.step_failed or '',
            'expected_vs_actual': b.expected_vs_actual or '',
            'page_url': b.page_url or '',
            'reporter_username': b.reporter.username if b.reporter else 'System',
            'comments': comments_list
        })

    return jsonify({
        'success': True,
        'test_case': {
            'id': tc.id,
            'title': tc.title,
            'area': tc.area,
            'description': tc.description or '',
            'status': tc.status,
            'assigned_to_id': tc.assigned_to_id,
            'assigned_to_username': tc.assigned_to.username if tc.assigned_to else 'Все тестеры',
            'created_by_username': tc.created_by.username if tc.created_by else 'System',
            'steps_count': len(tc.steps),
            'steps': [{
                'id': s.id,
                'step_number': s.step_number,
                'action_text': s.action_text,
                'expected_result': s.expected_result,
                'is_completed': getattr(s, 'is_completed', False)
            } for s in tc.steps],
            'bug_report': bug_reports_list[0] if bug_reports_list else None,
            'bug_reports': bug_reports_list
        }
    })


@qa_tester_bp.route('/api/qa/test-steps/<int:step_id>/toggle', methods=['POST'])
@csrf.exempt
@login_required
def toggle_test_step(step_id):
    """Переключение флага is_completed у шага проверки"""
    step = db.session.get(TestStep, step_id) or TestStep.query.get(step_id)
    if not step:
        return jsonify({'success': False, 'message': 'Шаг не найден'}), 404

    step.is_completed = not getattr(step, 'is_completed', False)
    db.session.commit()

    return jsonify({
        'success': True,
        'step_id': step.id,
        'is_completed': step.is_completed
    })


@qa_tester_bp.route('/api/qa/test-cases/<int:tc_id>/fail-with-report', methods=['POST'])
@csrf.exempt
@login_required
def fail_test_case_with_report(tc_id):
    """Отправка баг-репорта и перевод тест-кейса в статус FAILED"""
    tc = db.session.get(TestCase, tc_id) or TestCase.query.get(tc_id)
    if not tc:
        return jsonify({'success': False, 'message': f'Тест-кейс #{tc_id} не найден'}), 444

    data = request.get_json(silent=True) or request.form.to_dict()
    severity = data.get('severity', 'MAJOR').strip()
    step_failed = data.get('step_failed', '').strip()
    expected_vs_actual = data.get('expected_vs_actual', '').strip()
    page_url = data.get('page_url', '').strip() or request.headers.get('Referer', '')
    test_step_id = data.get('test_step_id')

    bug = BugReport(
        test_case_id=tc.id,
        test_step_id=test_step_id if test_step_id else None,
        reporter_id=current_user.id,
        title=f"Баг при прохождении теста #{tc.id}: {tc.title}",
        description=f"Шаг сбоя: {step_failed}\nОжидаемый vs Фактический: {expected_vs_actual}",
        page_url=page_url,
        step_failed=step_failed,
        expected_vs_actual=expected_vs_actual,
        severity=severity,
        status='NEW'
    )
    db.session.add(bug)
    
    tc.status = 'FAILED'
    db.session.commit()

    audit_logger.log(
        action='fail_test_case_with_report',
        entity='TestCase',
        entity_id=tc.id,
        status='success',
        metadata={'bug_id': bug.id, 'severity': severity}
    )

    return jsonify({
        'success': True,
        'message': f'Баг-репорт #{bug.id} зафиксирован. Тест #{tc.id} переведен в FAILED.',
        'bug_id': bug.id,
        'test_case_status': 'FAILED'
    })


@qa_tester_bp.route('/api/qa/test-cases/<int:tc_id>/steps', methods=['GET'])
@login_required
def get_test_case_steps(tc_id):
    """Эндпоинт для виджета QA Companion: список шагов выбранного тест-кейса"""
    tc = TestCase.query.get(tc_id)
    if not tc:
        return jsonify({'success': False, 'steps': []}), 444

    steps_list = [{
        'id': s.id,
        'step_number': s.step_number,
        'action_text': s.action_text,
        'expected_result': s.expected_result
    } for s in tc.steps]

    return jsonify({'success': True, 'steps': steps_list})


@qa_tester_bp.route('/api/qa/bug-reports/create', methods=['POST'])
@csrf.exempt
@login_required
def create_bug_report_api():
    """Создание баг-репорта из виджета QA Companion или из кабинета тестировщика"""
    if not (current_user.is_admin() or current_user.is_creator() or getattr(current_user, 'role', '') in QA_ROLES):
        return jsonify({'success': False, 'message': 'Forbidden: Доступ запрещен для данной роли'}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    page_url = data.get('page_url', '').strip() or request.headers.get('Referer', '')
    step_failed = data.get('step_failed', '').strip()
    expected_vs_actual = data.get('expected_vs_actual', '').strip()
    severity = data.get('severity', 'MAJOR').upper()
    test_case_id = data.get('test_case_id')
    test_step_id = data.get('test_step_id')

    if not title:
        return jsonify({'success': False, 'message': 'Заголовок проблемы обязателен'}), 400

    if severity not in ('CRITICAL', 'MAJOR', 'MINOR'):
        severity = 'MAJOR'

    if test_case_id:
        try:
            test_case_id = int(test_case_id)
        except (ValueError, TypeError):
            test_case_id = None

    if test_step_id:
        try:
            test_step_id = int(test_step_id)
        except (ValueError, TypeError):
            test_step_id = None

    try:
        bug = BugReport(
            test_case_id=test_case_id,
            test_step_id=test_step_id,
            reporter_id=current_user.id,
            title=title,
            description=description,
            page_url=page_url,
            step_failed=step_failed,
            expected_vs_actual=expected_vs_actual,
            severity=severity,
            status='NEW'
        )
        db.session.add(bug)

        if test_case_id:
            tc = TestCase.query.get(test_case_id)
            if tc:
                tc.status = 'FAILED'

        db.session.commit()

        audit_logger.log(action='create_bug_report', entity='BugReport', entity_id=bug.id, status='success', metadata={'title': title, 'severity': severity})
        return jsonify({'success': True, 'bug_id': bug.id, 'message': f'Баг-репорт #{bug.id} «{title}» успешно отправлен!'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Ошибка сохранения баг-репорта: {str(e)}'}), 500


@qa_tester_bp.route('/api/qa/bug-reports/<int:bug_id>/comments', methods=['GET'])
@login_required
def get_bug_report_comments(bug_id):
    """Получение списка комментариев к баг-репорту"""
    bug = BugReport.query.get(bug_id)
    if not bug:
        return jsonify({'success': False, 'comments': []}), 444

    comments_list = [{
        'id': c.id,
        'author_id': c.author_id,
        'author_name': c.author.username if c.author else 'Неизвестный',
        'author_role': c.author.role if c.author else 'user',
        'text': c.text,
        'created_at': c.created_at.strftime('%d.%m %H:%M') if c.created_at else ''
    } for c in bug.comments]

    return jsonify({'success': True, 'comments': comments_list})


@qa_tester_bp.route('/api/qa/bug-reports/<int:bug_id>/comments', methods=['POST'])
@csrf.exempt
@login_required
def add_bug_report_comment(bug_id):
    """Добавление комментария / ответа в баг-репорт"""
    if not (current_user.is_admin() or current_user.is_creator() or getattr(current_user, 'role', '') in QA_ROLES):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403

    bug = BugReport.query.get(bug_id)
    if not bug:
        return jsonify({'success': False, 'message': f'Баг-репорт #{bug_id} не найден'}), 444

    data = request.get_json(silent=True) or request.form.to_dict()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'message': 'Текст комментария не может быть пустым'}), 400

    try:
        cmt = BugReportComment(
            bug_report_id=bug.id,
            author_id=current_user.id,
            text=text
        )
        db.session.add(cmt)
        db.session.commit()

        audit_logger.log(action='add_bug_comment', entity='BugReportComment', entity_id=cmt.id, status='success', metadata={'bug_id': bug.id})
        return jsonify({
            'success': True,
            'comment': {
                'id': cmt.id,
                'author_name': current_user.username,
                'author_role': current_user.role,
                'text': cmt.text,
                'created_at': cmt.created_at.strftime('%d.%m %H:%M') if cmt.created_at else ''
            },
            'message': 'Комментарий успешно отправлен!'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Ошибка сохранения комментария: {str(e)}'}), 500
