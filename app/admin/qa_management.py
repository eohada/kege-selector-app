from flask import Blueprint, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from core.db_models import db, QATestCase, QAReport, QAReportHistory, User
from app.auth.rbac_utils import require_role
from app.qa.routes import QA_AREAS

qa_bp = Blueprint('qa_admin', __name__, url_prefix='/admin/qa')

def qa_admin_required(f):
    return require_role('admin', 'creator', 'chief_admin', 'chief_tester')(f)

# Список спринтов/циклов (статически для MVP)
QA_CYCLES = [
    (1, 'Итерация 1'),
    (2, 'Итерация 2'),
    (3, 'Итерация 3'),
    (4, 'Итерация 4'),
]

@qa_bp.route('/')
@login_required
@qa_admin_required
def dashboard():
    """Совместимый URL: единый QA-центр рендерится только V2-маршрутом."""
    return redirect(url_for('admin.admin_testers_page'), code=302)


@qa_bp.route('/tests', methods=['GET', 'POST'])
@login_required
@qa_admin_required
def manage_tests():
    """Управление тест-кейсами (создание, редактирование)."""
    if request.method == 'GET':
        return redirect(url_for('admin.admin_testers_page'), code=302)
    if request.method == 'POST':
        action = request.form.get('action')
        title = request.form.get('title')
        area = request.form.get('area')
        role = request.form.get('role')
        steps_raw = request.form.get('steps', '')
        expected_result = request.form.get('expected_result')

        # Преобразуем многострочный текст в массив шагов
        steps = [s.strip() for s in steps_raw.split('\n') if s.strip()]

        if action == 'create':
            test = QATestCase(
                title=title, area=area, role=role,
                steps=steps, expected_result=expected_result, is_active=True
            )
            db.session.add(test)
            flash('Тест успешно создан', 'success')

        elif action == 'edit':
            test_id = request.form.get('test_id')
            test = QATestCase.query.get_or_404(test_id)
            test.title = title
            test.area = area
            test.role = role
            test.steps = steps
            test.expected_result = expected_result
            flash('Тест успешно обновлен', 'success')

        elif action == 'toggle':
            test_id = request.form.get('test_id')
            test = QATestCase.query.get_or_404(test_id)
            test.is_active = not test.is_active
            flash('Статус теста обновлен', 'success')

        db.session.commit()
        return redirect(url_for('qa_admin.manage_tests'))

    return redirect(url_for('admin.admin_testers_page'), code=302)


@qa_bp.route('/reports/<int:report_id>')
@login_required
@qa_admin_required
def view_report(report_id):
    """Совместимый URL: отчёты открываются внутри V2 QA-центра."""
    QAReport.query.get_or_404(report_id)
    return redirect(url_for('admin.admin_testers_page', report_id=report_id), code=302)


@qa_bp.route('/reports/<int:report_id>/status', methods=['POST'])
@login_required
@qa_admin_required
def update_report_status(report_id):
    """Обновление статуса бага."""
    report = QAReport.query.get_or_404(report_id)
    new_status = request.form.get('status')
    admin_comment = request.form.get('admin_comment', '').strip()

    # Допустимые статусы (убрали rejected из основного workflow)
    allowed = ['pending', 'in_progress', 'retest', 'resolved', 'rejected']

    if new_status in allowed:
        old_status = report.status
        if old_status != new_status or admin_comment:
            report.status = new_status
            
            if new_status == 'retest':
                report.cycle_id = (report.cycle_id or 1) + 1
                from app.utils.tg_notifier import send_tg_message
                reporter = User.query.get(report.reporter_id)
                if reporter and reporter.tg_id:
                    test_title = report.test_case.title if report.test_case else f"Репорт #{report.id}"
                    send_tg_message(reporter.tg_id, f"🛠 БАГ ПОЧИНИЛИ!\nАдмин исправил баг: {test_title}\nЗайди на платформу и сделай ретест, пожалуйста!")

            # Логируем в историю
            history = QAReportHistory(
                report_id=report.id,
                author_id=current_user.id,
                old_status=old_status,
                new_status=new_status,
                comment=admin_comment or f"Статус изменён на '{new_status}'",
            )
            db.session.add(history)
            db.session.commit()
            flash('Статус обновлён', 'success')
        else:
            flash('Нет изменений', 'info')
    else:
        flash('Неверный статус', 'error')

    return redirect(url_for('qa_admin.view_report', report_id=report.id))
