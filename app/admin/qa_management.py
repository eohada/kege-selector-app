from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
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
    """Главный дашборд QA: сводка по багам и тестам."""
    total_tests = QATestCase.query.count()
    all_reports_count = QAReport.query.count()
    active_reports = QAReport.query.filter(QAReport.status.in_(['pending', 'in_progress'])).count()
    retest_reports = QAReport.query.filter(QAReport.status == 'retest').count()

    # Фильтры
    status_filter = request.args.get('status')
    area_filter = request.args.get('area')
    reporter_id_filter = request.args.get('reporter_id')
    cycle_filter = request.args.get('cycle_id')

    query = QAReport.query

    if status_filter:
        query = query.filter(QAReport.status == status_filter)
    if area_filter:
        query = query.filter(QAReport.area == area_filter)
    if reporter_id_filter and reporter_id_filter.isdigit():
        query = query.filter(QAReport.reporter_id == int(reporter_id_filter))
    if cycle_filter and cycle_filter.isdigit():
        query = query.filter(QAReport.cycle_id == int(cycle_filter))

    reports = query.order_by(QAReport.created_at.desc()).all()

    # Для фильтра тестеров
    testers = User.query.filter(User.role.in_(['tester', 'chief_tester'])).all()

    # Топ багхантеров (лидерборд): GROUP BY reporter_id COUNT за всё время
    leaderboard_rows = (
        db.session.query(
            QAReport.reporter_id,
            func.count(QAReport.id).label('total'),
            func.sum(
                db.cast(QAReport.verdict == 'critical', db.Integer)
            ).label('critical_count'),
        )
        .filter(QAReport.reporter_id.isnot(None))
        .group_by(QAReport.reporter_id)
        .order_by(func.count(QAReport.id).desc())
        .limit(5)
        .all()
    )

    # Подгружаем пользователей для лидерборда
    leaderboard_user_ids = [r.reporter_id for r in leaderboard_rows]
    leaderboard_users = {u.id: u for u in User.query.filter(User.id.in_(leaderboard_user_ids)).all()}
    leaderboard = []
    for row in leaderboard_rows:
        u = leaderboard_users.get(row.reporter_id)
        if u:
            leaderboard.append({
                'user': u,
                'total': row.total,
                'critical_count': row.critical_count or 0,
            })

    return render_template(
        'admin/qa/dashboard.html',
        total_tests=total_tests,
        active_reports=active_reports,
        all_reports_count=all_reports_count,
        retest_reports=retest_reports,
        reports=reports,
        all_areas=QA_AREAS,
        testers=testers,
        qa_cycles=QA_CYCLES,
        leaderboard=leaderboard,
    )


@qa_bp.route('/tests', methods=['GET', 'POST'])
@login_required
@qa_admin_required
def manage_tests():
    """Управление тест-кейсами (создание, редактирование)."""
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

    tests = QATestCase.query.order_by(QATestCase.area, QATestCase.id).all()
    return render_template('admin/qa/test_cases.html', tests=tests, all_areas=QA_AREAS)


@qa_bp.route('/reports/<int:report_id>')
@login_required
@qa_admin_required
def view_report(report_id):
    """Просмотр конкретного бага."""
    report = QAReport.query.get_or_404(report_id)
    history = QAReportHistory.query.filter_by(
        report_id=report.id
    ).order_by(QAReportHistory.created_at.asc()).all()
    return render_template('admin/qa/report_detail.html', report=report, history=history)


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
                    send_tg_message(reporter.tg_id, f"🛠 БАГ ПОЧИНИЛИ!
Админ исправил баг: {test_title}
Зайди на платформу и сделай ретест, пожалуйста!")

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
