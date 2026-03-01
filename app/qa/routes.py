import uuid
from flask import Blueprint, session, redirect, url_for, request, flash, jsonify, render_template
from flask_login import login_required, current_user, login_user
from app.models import db
# Import from app.models or core.db_models. app.models exports most things.
# I'll use core.db_models for clarity if not in app.models yet, but I should add them there.
# For now, I'll import from core.db_models where I defined them.
from core.db_models import User, Student, Enrollment, QATask, QAComment

qa_bp = Blueprint('qa', __name__, url_prefix='/qa')

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


@qa_bp.route('/impersonate-as-role', methods=['POST'])
@login_required
def impersonate_as_role():
    """Создать временного пользователя (ученик/препода/родитель) и войти под ним."""
    if not is_qa_authorized():
        return jsonify({'error': 'Forbidden'}), 403
    role = (request.form.get('role') or (request.get_json(silent=True) or {}).get('role') or '').strip().lower()
    if role not in ('student', 'tutor', 'parent'):
        return jsonify({'error': 'Укажите role: student, tutor или parent'}), 400
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
        flash(f'Вход под временным пользователем: {role} ({u.username})', 'success')
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
# 4. TASK TRACKER (Роуты)
# ==========================================

@qa_bp.route('/board')
@login_required
def board():
    if not is_qa_authorized():
        return "Access denied", 403
    tasks = QATask.query.order_by(QATask.created_at.desc()).all()
    return render_template('qa/board.html', tasks=tasks)


@qa_bp.route('/bug-report', methods=['GET', 'POST'])
@login_required
def bug_report():
    """Создание баг-репорта. Доступно главному тестировщику и создателю."""
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
                status='todo',
                priority='high'
            )
            db.session.add(task)
            db.session.commit()
            flash('Баг-репорт создан и добавлен на доску.', 'success')
            return redirect(url_for('qa.board'))
    return render_template('qa/bug_report.html', context_url=context_url, target_user_id=target_user_id)


@qa_bp.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def task_new():
    """Стратегические задачи. Только Creator."""
    if not current_user.is_creator():
        return "Access denied: Only Creator can create tasks here.", 403
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        context_url = request.form.get('context_url')
        target_user_id = request.form.get('target_user_id')
        if title:
            task = QATask(
                title=title,
                description=description,
                context_url=context_url,
                target_user_id=int(target_user_id) if target_user_id and target_user_id.isdigit() else None,
                reporter_id=current_user.id,
                status='todo'
            )
            db.session.add(task)
            db.session.commit()
            return redirect(url_for('qa.board'))
    return render_template('qa/task_form.html')
