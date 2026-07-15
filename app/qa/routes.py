import os
import uuid
import json
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from core.db_models import db, QATestCase, QAReport, QAReportHistory
from app.auth.rbac_utils import require_role
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
    """Доступ для тестировщиков и админов."""
    return require_role(*QA_ROLES)(f)


def _get_upload_dir():
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    upload_dir = os.path.join(base_dir, 'static', 'uploads', 'qa')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _save_uploaded_file(file_obj, allowed_exts=None):
    """Сохраняет файл в static/uploads/qa/, возвращает (url, filename, ext)."""
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


# ---------------------------------------------------------------------------
# Страница тестировщика (список тестов)
# ---------------------------------------------------------------------------

@qa_tester_bp.route('/')
@login_required
@qa_access_required
def index():
    """Список всех активных тестов для прохождения с галочками и прогрессом."""
    tests = QATestCase.query.filter_by(is_active=True).order_by(QATestCase.area, QATestCase.id).all()

    # Какие тесты текущий пользователь уже прошел
    passed_test_ids = set()
    retest_test_ids = set()
    bug_test_ids = set()
    
    # Также собираем все adhoc баги (без test_id)
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
            # Это Ad-Hoc баг
            adhoc_reports.append(r)

    # Группируем тесты по зонам
    tests_by_area = {}
    for test in tests:
        if test.area not in tests_by_area:
            tests_by_area[test.area] = []
        tests_by_area[test.area].append(test)
        
    # Добавляем Ad-Hoc баги в те же зоны, чтобы они выводились на дашборде
    for r in adhoc_reports:
        area = r.area or 'Общая'
        if area not in tests_by_area:
            tests_by_area[area] = []
        tests_by_area[area].append(r) # Миксуем QATestCase и QAReport в одном списке

    # Прогресс по зонам
    area_progress = {}
    for area, area_items in tests_by_area.items():
        total = len(area_items)
        done = 0
        for item in area_items:
            if hasattr(item, 'steps'): # Это QATestCase
                if item.id in passed_test_ids and item.id not in retest_test_ids:
                    done += 1
            else: # Это QAReport (Ad-hoc)
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
    """Обновление ЛЮБОГО репорта (обычный тест или Ad-hoc)."""
    report = QAReport.query.get_or_404(report_id)
    
    if report.reporter_id != current_user.id:
        return jsonify({'error': 'Нет доступа'}), 403

    verdict = request.form.get('verdict')
    description = request.form.get('description', '').strip()
    tester_comment = request.form.get('tester_comment', '').strip()
    cycle_id = request.form.get('cycle_id', type=int)

    if not verdict:
        return jsonify({'error': 'Необходимо выбрать вердикт'}), 400

    # Блокируем обновление если не в retest
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

    # Пишем сообщение тестировщика в историю ТОЛЬКО если изменился статус ИЛИ есть явный коммент
    if old_status != new_status or tester_comment:
        # Проверяем, не дублируем ли мы последнее сообщение (из-за возможных повторных вызовов)
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
    """Интерфейс прохождения конкретного теста."""
    test = QATestCase.query.get_or_404(test_id)

    # Ищем, отправлял ли этот юзер уже репорт по этому тесту (для ретеста)
    existing_report = QAReport.query.filter_by(test_id=test.id, reporter_id=current_user.id).first()
    failed_steps = existing_report.failed_steps if existing_report and existing_report.failed_steps else []

    # Жёсткая логика read-only:
    # форма активна только если нет репорта (первый раз) или статус == 'retest'
    is_readonly = bool(existing_report and existing_report.status != 'retest')

    # Получаем последний комментарий админа при ретесте
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
    """Отправка результата теста или обновление существующего репорта."""
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

    # Ищем существующий репорт от этого юзера
    report = QAReport.query.filter_by(test_id=test.id, reporter_id=current_user.id).first()

    # Статус: success = resolved, баги = pending
    new_status = 'resolved' if verdict == 'success' else 'pending'
    
    is_new_bug = not report and new_status == 'pending'

    if report:
        # Блокируем обновление если не в retest
        if report.status not in ('retest', 'pending'):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Репорт заблокирован (не на ретесте)'}), 403
            flash('Репорт заблокирован. Ждите ретеста от администратора.', 'error')
            return redirect(url_for('qa_tester.execute_test', test_id=test.id))

        old_status = report.status
        report.verdict = verdict
        report.status = new_status
        report.failed_steps = completed_steps
        report.page_url = request.form.get('page_url', report.page_url or '')
        report.user_agent = request.headers.get('User-Agent', '')
        report.screen_size = request.form.get('screen_size', report.screen_size or '')
        if description:  # Разрешаем обновлять description, если оно пустое или изменилось
            report.description = description

        # Обновляем вложения, если пришли новые
        if attachments:
            existing_atts = report.attachments or []
            existing_urls = {a.get('url') for a in existing_atts}
            for att in attachments:
                if att.get('url') not in existing_urls:
                    existing_atts.append(att)
            report.attachments = existing_atts

        # Добавляем новые логи
        if logs:
            existing_logs = report.logs or []
            existing_logs.extend(logs)
            report.logs = existing_logs

        # Пишем сообщение тестировщика в историю ТОЛЬКО если изменился статус ИЛИ есть явный коммент
        if old_status != new_status or tester_comment:
            history_comment = tester_comment or f"Тестировщик обновил вердикт на '{verdict}'"
            history_entry = QAReportHistory(
                report_id=report.id,
                author_id=current_user.id,
                old_status=old_status,
                new_status=new_status,
                comment=history_comment,
            )
            db.session.add(history_entry)
    else:
        # Создаем новый репорт
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
        db.session.flush()  # получаем ID

        # Первая запись в историю
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

    return redirect(url_for('qa_tester.index') + '?tab=' + ('done' if verdict == 'success' else 'new'))


# ---------------------------------------------------------------------------
# Bulk Pass — массовое прохождение тестов как "успешно"
# ---------------------------------------------------------------------------

@qa_tester_bp.route('/bulk-pass', methods=['POST'])
@login_required
@qa_access_required
def bulk_pass():
    """Массово отмечает тесты как пройденные (success)."""
    data = request.get_json(silent=True) or {}
    test_ids = data.get('test_ids', [])

    if not test_ids:
        return jsonify({'error': 'Нет тестов для обработки'}), 400

    passed = 0
    for test_id in test_ids:
        test = QATestCase.query.get(test_id)
        if not test:
            continue

        report = QAReport.query.filter_by(test_id=test_id, reporter_id=current_user.id).first()

        # Пропускаем уже завершённые (не retest и не pending)
        if report and report.status not in ('retest', 'pending'):
            continue

        if report:
            old_status = report.status
            report.verdict = 'success'
            report.status = 'resolved'
            report.failed_steps = []
        else:
            report = QAReport(
                test_id=test_id,
                reporter_id=current_user.id,
                area=test.area,
                status='resolved',
                verdict='success',
                description='Пройдено через Bulk Pass',
                failed_steps=[],
                page_url=request.referrer or '',
                user_agent=request.headers.get('User-Agent', ''),
                cycle_id=1,
            )
            db.session.add(report)
            db.session.flush()
            old_status = None

        history_entry = QAReportHistory(
            report_id=report.id,
            author_id=current_user.id,
            old_status=old_status,
            new_status='resolved',
            comment='Bulk Pass — тест отмечен успешным',
        )
        db.session.add(history_entry)
        passed += 1

    db.session.commit()
    return jsonify({'success': True, 'passed': passed})


# ---------------------------------------------------------------------------
# Ad-hoc баг (вне тест-кейсов)
# ---------------------------------------------------------------------------

@qa_tester_bp.route('/ad-hoc', methods=['GET', 'POST'])
@login_required
@qa_access_required
def ad_hoc_bug():
    """Свободная форма для бага вне тестов."""
    if request.method == 'POST':
        area = request.form.get('area', 'Общая')
        verdict = request.form.get('verdict', 'minor')
        description = request.form.get('description', '').strip()

        if not description:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Опишите баг'}), 400
            flash('Опишите баг', 'error')
            return redirect(url_for('qa_tester.ad_hoc_bug'))

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
    
    if is_new_bug:
        from app.utils.tg_notifier import send_tg_message, ADMIN_TG_ID
        tester_name = current_user.username or "Неизвестный"
        area_name = test.area or "Общая зона"
        test_title = test.title or f"Тест #{test.id}"
        send_tg_message(ADMIN_TG_ID, f"🐛 Новый баг от {tester_name} в зоне {area_name}: {test_title}")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'tab': 'attention'})

    flash('Спонтанный баг зарегистрирован!', 'success')
    return redirect(url_for('qa_tester.index'))

@qa_tester_bp.route('/report/<int:report_id>')
@login_required
@qa_access_required
def edit_report(report_id):
    """Интерфейс просмотра/редактирования конкретного репорта (для Ad-hoc и тестов)."""
    report = QAReport.query.get_or_404(report_id)
    
    # Проверка, что репорт принадлежит текущему юзеру
    if report.reporter_id != current_user.id:
        flash('У вас нет доступа к этому репорту', 'error')
        return redirect(url_for('qa_tester.history'))

    # Для обычных тестов подтягиваем test_case
    test = report.test_case if report.test_id else None
    
    failed_steps = report.failed_steps if report.failed_steps else []
    is_readonly = bool(report.status != 'retest')

    admin_comment = None
    if report.status == 'retest':
        last_history = QAReportHistory.query.filter_by(
            report_id=report.id, new_status='retest'
        ).order_by(QAReportHistory.created_at.desc()).first()
        if last_history:
            admin_comment = last_history.comment

    history_records = QAReportHistory.query.filter_by(
        report_id=report.id
    ).order_by(QAReportHistory.created_at.asc()).all()

    return render_template(
        'qa_tester/execute.html',
        test=test,
        qa_areas=QA_AREAS,
        existing_report=report,
        failed_steps=failed_steps,
        admin_comment=admin_comment,
        history=history_records,
        is_readonly=is_readonly,
        is_adhoc=not bool(test)
    )


# ---------------------------------------------------------------------------
# История репортов тестировщика
# ---------------------------------------------------------------------------
@qa_tester_bp.route('/history')
@login_required
@qa_access_required
def history():
    """Страница со всеми репортами текущего тестировщика."""
    reports = QAReport.query.filter_by(reporter_id=current_user.id).order_by(QAReport.created_at.desc()).all()
    return render_template('qa_tester/history.html', reports=reports)


# ---------------------------------------------------------------------------
# API: Загрузка файлов (скриншоты, видео)
# ---------------------------------------------------------------------------

@qa_tester_bp.route('/upload', methods=['POST'])
@login_required
@qa_access_required
def upload_screenshot():
    """API для загрузки скриншотов по Ctrl+V."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image part'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    file_url, filename, ext = _save_uploaded_file(file, allowed_exts=['png', 'jpg', 'jpeg', 'gif', 'webp'])
    return jsonify({'success': True, 'url': file_url, 'filename': filename, 'type': 'image'})


@qa_tester_bp.route('/upload-video', methods=['POST'])
@login_required
@qa_access_required
def upload_video():
    """API для загрузки записи экрана (WebM)."""
    if 'video' not in request.files:
        return jsonify({'error': 'No video part'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    file_url, filename, ext = _save_uploaded_file(file, allowed_exts=['webm', 'mp4'])
    return jsonify({'success': True, 'url': file_url, 'filename': filename, 'type': 'video'})


# ---------------------------------------------------------------------------
# API: Быстрый баг из виджета (AJAX, JSON)
# ---------------------------------------------------------------------------

@qa_tester_bp.route('/api/quick-bug', methods=['POST'])
@login_required
@qa_access_required
def api_quick_bug():
    """AJAX-эндпоинт для отправки бага из плавающего виджета."""
    data = request.get_json(silent=True) or {}

    description = (data.get('comment') or data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'Описание бага обязательно'}), 400

    area = data.get('area', 'Общая')
    verdict = data.get('verdict', 'minor')
    page_url = data.get('page_url', '')
    user_agent = data.get('user_agent', request.headers.get('User-Agent', ''))
    screen_size = data.get('screen_size', '')
    attachments = data.get('attachments') or []
    har_summary = data.get('har_summary', '')
    network_errors = data.get('network_errors') or []
    console_errors = data.get('console_errors') or []

    # Собираем системные логи
    logs = []
    if console_errors:
        logs.extend([f"[console] {e}" for e in console_errors])
    if network_errors:
        logs.extend([f"[network] {e}" for e in network_errors])
    if har_summary:
        logs.append(f"[har] {har_summary}")

    report = QAReport(
        test_id=None,
        reporter_id=current_user.id,
        area=area,
        status='pending',
        verdict=verdict,
        description=description,
        logs=logs if logs else None,
        page_url=page_url,
        user_agent=user_agent,
        screen_size=screen_size,
        attachments=attachments if attachments else None,
        cycle_id=1,
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({'success': True, 'report_id': report.id})
