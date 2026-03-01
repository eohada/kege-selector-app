import uuid
from flask import Blueprint, session, redirect, url_for, request, flash, jsonify, render_template
from flask_login import login_required, current_user, login_user
from app.models import db
from core.db_models import User, Student, Enrollment, QATask, QAComment, FamilyTie

qa_bp = Blueprint('qa', __name__, url_prefix='/qa')

QA_POOL_USERNAMES = [
    'qa_pool_student_1', 'qa_pool_student_2', 'qa_pool_student_3',
    'qa_pool_tutor_1', 'qa_pool_tutor_2', 'qa_pool_tutor_3',
    'qa_pool_parent_1', 'qa_pool_parent_2', 'qa_pool_parent_3',
    'qa_pool_admin_1',
]

def is_qa_authorized():
    """Проверка прав: Chief Tester, Creator, Chief Admin или уже в режиме подмены."""
    roles = getattr(current_user, 'roles', lambda: [])() or [getattr(current_user, 'role', None)]
    return any(r in roles for r in ['chief_tester', 'creator', 'chief_admin', 'tester', 'admin']) or 'impersonator_id' in session

# ==========================================
# 1. IMPERSONATION (Тумблер ролей)
# ==========================================

@qa_bp.route('/impersonate/<int:target_user_id>', methods=['POST'])
@login_required
def impersonate(target_user_id):
    if not is_qa_authorized():
        flash('У вас нет прав для этого действия', 'error')
        return redirect(request.referrer or url_for('main.index'))

    target_user = User.query.get_or_404(target_user_id)

    # Запоминаем ID настоящего тестировщика
    if 'impersonator_id' not in session:
        session['impersonator_id'] = current_user.id

    login_user(target_user)
    flash(f'Вы вошли под ролью: {target_user.role}', 'success')
    return redirect(request.referrer or url_for('main.index'))

@qa_bp.route('/revert_impersonation', methods=['POST'])
@login_required
def revert_impersonation():
    impersonator_id = session.pop('impersonator_id', None)
    if not impersonator_id:
        return redirect(url_for('main.index'))

    original_user = User.query.get(impersonator_id)
    if original_user:
        login_user(original_user)
        flash('Вы вернулись в свой QA-аккаунт', 'success')
    
    return redirect(request.referrer or url_for('main.index'))


def _ensure_qa_pool():
    """Создаёт пул из 3 учеников, 3 преподавателей, 3 родителей, 1 админа (is_qa_pool=True)."""
    from werkzeug.security import generate_password_hash
    pwd = generate_password_hash('123456')
    created = []
    for username in QA_POOL_USERNAMES:
        u = User.query.filter_by(username=username).first()
        if u:
            if not getattr(u, 'is_qa_pool', False):
                u.is_qa_pool = True
                db.session.add(u)
            continue
        if 'student' in username:
            u = User(role='student', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(Student(user_id=u.id, platform_id=username, name=username.replace('_', ' ').title()))
            created.append(username)
        elif 'tutor' in username:
            u = User(role='tutor', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
        elif 'parent' in username:
            u = User(role='parent', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
        else:
            u = User(role='admin', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
    db.session.commit()
    return created


@qa_bp.route('/impersonate-as-role', methods=['POST'])
@login_required
def impersonate_as_role():
    """Вход под пользователем из пула (по username) или создание одноразового темп-юзера."""
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403
    username = (request.form.get('username') or '').strip()
    if username and username in QA_POOL_USERNAMES:
        u = User.query.filter_by(username=username).first()
        if u:
            if 'impersonator_id' not in session:
                session['impersonator_id'] = current_user.id
            login_user(u)
            flash(f'Вход под: {u.username}', 'success')
            return redirect(request.referrer or url_for('main.index'))
    role = (request.form.get('role') or '').strip().lower()
    if role not in ('student', 'tutor', 'parent'):
        return jsonify({'error': 'Укажите role или username из пула'}), 400
    try:
        from werkzeug.security import generate_password_hash
        uid = str(uuid.uuid4())[:6]
        pwd = generate_password_hash('123456')
        if role == 'student':
            u = User(role='student', username=f'qa_temp_student_{uid}', email=f'qa_temp_student_{uid}@qa.local', password_hash=pwd)
            db.session.add(u)
            db.session.flush()
            db.session.add(Student(user_id=u.id, platform_id=f'qa_{uid}', name=f'QA Ученик {uid}'))
        elif role == 'tutor':
            u = User(role='tutor', username=f'qa_temp_tutor_{uid}', email=f'qa_temp_tutor_{uid}@qa.local', password_hash=pwd)
            db.session.add(u)
            db.session.flush()
        else:
            u = User(role='parent', username=f'qa_temp_parent_{uid}', email=f'qa_temp_parent_{uid}@qa.local', password_hash=pwd)
            db.session.add(u)
            db.session.flush()
        db.session.commit()
        if 'impersonator_id' not in session:
            session['impersonator_id'] = current_user.id
        login_user(u)
        flash(f'Вход под временным: {u.username}', 'success')
        return redirect(request.referrer or url_for('main.index'))
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 2. ФАБРИКА ДАННЫХ (Mock Data)
# ==========================================

@qa_bp.route('/factory/tutor-students', methods=['POST'])
@login_required
def factory_tutor_students():
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403

    try:
        uid = str(uuid.uuid4())[:6]
        from werkzeug.security import generate_password_hash
        default_pwd = generate_password_hash('123456')
        
        tutor = User(role='tutor', username=f'mock_tutor_{uid}', email=f'mock_tutor_{uid}@test.com', password_hash=default_pwd)
        db.session.add(tutor)
        db.session.flush() # get ID
        
        student1 = User(role='student', username=f'mock_stud1_{uid}', email=f'mock_stud1_{uid}@test.com', password_hash=default_pwd)
        student2 = User(role='student', username=f'mock_stud2_{uid}', email=f'mock_stud2_{uid}@test.com', password_hash=default_pwd)
        db.session.add_all([student1, student2])
        db.session.flush() 
        
        db.session.add(Student(user_id=student1.id, platform_id=f'{uid}1', name=f'Student 1 {uid}'))
        db.session.add(Student(user_id=student2.id, platform_id=f'{uid}2', name=f'Student 2 {uid}'))
        
        db.session.add(Enrollment(student_id=student1.id, tutor_id=tutor.id, subject='Math (Test)'))
        db.session.add(Enrollment(student_id=student2.id, tutor_id=tutor.id, subject='Math (Test)'))
        
        db.session.commit()
        return jsonify({'status': 'success', 'tutor_id': tutor.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==========================================
# 3. МАНИПУЛЯТОРЫ СТАТУСАМИ (State Overrides)
# ==========================================

@qa_bp.route('/manipulate/pass_assignment', methods=['POST'])
@login_required
def pass_assignment():
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403

    try:
        from app.models import Submission, Student
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
             return jsonify({'status': 'error', 'message': 'Текущий пользователь не является учеником (нет профиля Student)'})

        # Находим последнюю активную работу
        submission = Submission.query.filter(
            Submission.student_id == student.student_id,
            Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED'])
        ).order_by(Submission.created_at.desc()).first()

        if submission:
            submission.status = 'GRADED'
            submission.percentage = 100
            submission.total_score = submission.max_score or 100
            submission.teacher_feedback = '[QA God Mode] Авто-сдача на 100%'
            db.session.commit()
            return jsonify({'status': 'success', 'message': f'Работа ID {submission.submission_id} успешно сдана на 100%!'})
        
        return jsonify({'status': 'error', 'message': 'Нет активных работ для сдачи'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@qa_bp.route('/manipulate/pay_course', methods=['POST'])
@login_required
def pay_course():
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403

    try:
        # ПРИМЕР РЕАЛИЗАЦИИ (Замени "Payments" на твою модель оплат)
        # payment = Payments(user_id=current_user.id, amount=1000, status='paid', description='QA Mock Payment')
        # db.session.add(payment)
        # db.session.commit()
        
        return jsonify({'status': 'success', 'message': '[Имитация] Тестовая оплата на 1000 успешно проведена!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==========================================
# 3.1 ПУЛ ПРОФИЛЕЙ И ПРИВЯЗКИ
# ==========================================

@qa_bp.route('/pool')
@login_required
def pool():
    """Страница управления тестовыми профилями: привязка учеников к преподавателям, родителей к ученикам."""
    if not is_qa_authorized():
        return "Access denied", 403
    _ensure_qa_pool()
    pool_users = User.query.filter(User.username.in_(QA_POOL_USERNAMES)).order_by(User.username).all()
    students = [u for u in pool_users if u.role == 'student']
    tutors = [u for u in pool_users if u.role == 'tutor']
    parents = [u for u in pool_users if u.role == 'parent']
    admins = [u for u in pool_users if u.role == 'admin']
    enrollments = Enrollment.query.filter(
        Enrollment.student_id.in_([u.id for u in students]),
        Enrollment.tutor_id.in_([u.id for u in tutors])
    ).all()
    family_ties = FamilyTie.query.filter(
        FamilyTie.student_id.in_([u.id for u in students]),
        FamilyTie.parent_id.in_([u.id for u in parents])
    ).all()
    return render_template('qa/pool.html', students=students, tutors=tutors, parents=parents, admins=admins,
                           enrollments=enrollments, family_ties=family_ties)


@qa_bp.route('/pool/enrollment', methods=['POST'])
@login_required
def pool_enrollment_add():
    if not is_qa_authorized():
        return "Access denied", 403
    student_id = request.form.get('student_id', type=int)
    tutor_id = request.form.get('tutor_id', type=int)
    if not student_id or not tutor_id:
        flash('Выберите ученика и преподавателя', 'error')
        return redirect(url_for('qa.pool'))
    if Enrollment.query.filter_by(student_id=student_id, tutor_id=tutor_id).first():
        flash('Такая привязка уже есть', 'warning')
        return redirect(url_for('qa.pool'))
    db.session.add(Enrollment(student_id=student_id, tutor_id=tutor_id, subject='QA (тест)'))
    db.session.commit()
    flash('Ученик привязан к преподавателю', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/enrollment/<int:enrollment_id>/delete', methods=['POST'])
@login_required
def pool_enrollment_delete(enrollment_id):
    if not is_qa_authorized():
        return "Access denied", 403
    e = Enrollment.query.get_or_404(enrollment_id)
    db.session.delete(e)
    db.session.commit()
    flash('Привязка ученик–препода удалена', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/family-tie', methods=['POST'])
@login_required
def pool_family_tie_add():
    if not is_qa_authorized():
        return "Access denied", 403
    parent_id = request.form.get('parent_id', type=int)
    student_id = request.form.get('student_id', type=int)
    if not parent_id or not student_id:
        flash('Выберите родителя и ученика', 'error')
        return redirect(url_for('qa.pool'))
    if FamilyTie.query.filter_by(parent_id=parent_id, student_id=student_id).first():
        flash('Такая привязка уже есть', 'warning')
        return redirect(url_for('qa.pool'))
    db.session.add(FamilyTie(parent_id=parent_id, student_id=student_id, is_confirmed=True))
    db.session.commit()
    flash('Родитель привязан к ученику', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/family-tie/<int:tie_id>/delete', methods=['POST'])
@login_required
def pool_family_tie_delete(tie_id):
    if not is_qa_authorized():
        return "Access denied", 403
    t = FamilyTie.query.get_or_404(tie_id)
    db.session.delete(t)
    db.session.commit()
    flash('Привязка родитель–ученик удалена', 'success')
    return redirect(url_for('qa.pool'))


# ==========================================
# 4. КАНБАН (задачи Creator → Tester)
# ==========================================

@qa_bp.route('/board')
@login_required
def board():
    if not is_qa_authorized():
        return "Access denied", 403
    tasks = QATask.query.filter(QATask.task_type == 'task').order_by(QATask.created_at.desc()).all()
    return render_template('qa/board.html', tasks=tasks, can_edit_status=current_user.is_creator() or current_user.is_chief_tester() or current_user.is_tester())


@qa_bp.route('/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def task_set_status(task_id):
    """Смена статуса задачи на доске. Может Creator или назначенный Tester."""
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403
    task = QATask.query.get_or_404(task_id)
    if task.task_type != 'task':
        return jsonify({'error': 'Not a board task'}), 400
    if not current_user.is_creator() and task.assignee_id != current_user.id:
        return jsonify({'error': 'Только создатель или исполнитель могут менять статус'}), 403
    status = (request.form.get('status') or (request.get_json(silent=True) or {}).get('status') or '').strip()
    if status not in ('todo', 'in_progress', 'review', 'done'):
        return jsonify({'error': 'Invalid status'}), 400
    task.status = status
    db.session.commit()
    if request.want_json or request.get_json(silent=True) is not None:
        return jsonify({'success': True, 'status': status})
    flash('Статус обновлён', 'success')
    return redirect(url_for('qa.board'))


@qa_bp.route('/tasks/<int:task_id>/assign', methods=['POST'])
@login_required
def task_assign(task_id):
    """Назначить исполнителя (только Creator)."""
    if not current_user.is_creator():
        return jsonify({'error': 'Forbidden'}), 403
    task = QATask.query.get_or_404(task_id)
    if task.task_type != 'task':
        return jsonify({'error': 'Not a board task'}), 400
    assignee_id = request.form.get('assignee_id', type=int) or (request.get_json(silent=True) or {}).get('assignee_id')
    task.assignee_id = assignee_id if assignee_id else None
    db.session.commit()
    if request.want_json or request.get_json(silent=True) is not None:
        return jsonify({'success': True})
    flash('Исполнитель назначен', 'success')
    return redirect(url_for('qa.board'))


# ==========================================
# 5. БАГ-РЕПОРТЫ (Tester → Creator, Creator управляет)
# ==========================================

@qa_bp.route('/bug-report', methods=['GET', 'POST'])
@login_required
def bug_report():
    if not is_qa_authorized():
        return "Access denied", 403
    context_url = request.args.get('context_url') or request.form.get('context_url') or ''
    target_user_id = request.args.get('target_user_id') or request.form.get('target_user_id') or ''
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip() or 'Баг с страницы'
        description = (request.form.get('description') or '').strip()
        if title:
            task = QATask(
                title=title,
                description=description or None,
                context_url=context_url or None,
                target_user_id=int(target_user_id) if target_user_id and str(target_user_id).isdigit() else None,
                reporter_id=current_user.id,
                status='new',
                priority='high',
                task_type='bug_report'
            )
            db.session.add(task)
            db.session.commit()
            flash('Баг-репорт создан. Создатель увидит его в разделе «Баг-репорты».', 'success')
            return redirect(url_for('qa.bug_reports'))
    return render_template('qa/bug_report.html', context_url=context_url, target_user_id=target_user_id)


@qa_bp.route('/bug-reports')
@login_required
def bug_reports():
    """Список баг-репортов. Creator может менять статус, Tester — только просмотр."""
    if not is_qa_authorized():
        return "Access denied", 403
    reports = QATask.query.filter(QATask.task_type == 'bug_report').order_by(QATask.created_at.desc()).all()
    can_edit = current_user.is_creator()
    return render_template('qa/bug_reports.html', reports=reports, can_edit=can_edit)


@qa_bp.route('/bug-reports/<int:task_id>/status', methods=['POST'])
@login_required
def bug_report_set_status(task_id):
    """Смена статуса баг-репорта. Только Creator."""
    if not current_user.is_creator():
        return jsonify({'error': 'Forbidden'}), 403
    task = QATask.query.get_or_404(task_id)
    if task.task_type != 'bug_report':
        return jsonify({'error': 'Not a bug report'}), 400
    status = (request.form.get('status') or (request.get_json(silent=True) or {}).get('status') or '').strip()
    if status not in ('new', 'in_progress', 'review', 'done'):
        return jsonify({'error': 'Invalid status'}), 400
    task.status = status
    db.session.commit()
    if request.want_json or (request.get_json(silent=True) is not None):
        return jsonify({'success': True, 'status': status})
    flash('Статус баг-репорта обновлён', 'success')
    return redirect(url_for('qa.bug_reports'))


@qa_bp.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def task_new():
    """Создание задачи для тестера. Только Creator."""
    if not current_user.is_creator():
        return "Access denied: Only Creator can create tasks here.", 403
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        context_url = request.form.get('context_url')
        target_user_id = request.form.get('target_user_id')
        assignee_id = request.form.get('assignee_id', type=int)
        if title:
            task = QATask(
                title=title,
                description=description,
                context_url=context_url,
                target_user_id=int(target_user_id) if target_user_id and str(target_user_id).isdigit() else None,
                reporter_id=current_user.id,
                status='todo',
                task_type='task',
                assignee_id=assignee_id or None
            )
            db.session.add(task)
            db.session.commit()
            return redirect(url_for('qa.board'))
    testers = User.query.filter(User.role.in_(['chief_tester', 'tester'])).all()
    return render_template('qa/task_form.html', testers=testers)
