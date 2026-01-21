"""
Основные маршруты приложения
"""
import logging
import json
import shutil
from flask import render_template, request, send_from_directory, flash, redirect, url_for, make_response
from flask_login import login_required
import os
from datetime import datetime

from app.main import main_bp
from app.models import Student, Lesson, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, db, moscow_now
from app.models import User, Enrollment, FamilyTie, UserConsent
from app.students.forms import normalize_school_class
from app.auth.rbac_utils import get_user_scope, apply_data_scope
from sqlalchemy import func, or_
from datetime import timedelta
from core.audit_logger import audit_logger
from flask_login import current_user
from app import csrf

# Базовая директория проекта
base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@main_bp.route('/legal/offer')
def legal_offer():
    return render_template('legal_offer.html')


@main_bp.route('/legal/privacy')
def legal_privacy():
    return render_template('legal_privacy.html')


@main_bp.route('/legal/accept', methods=['POST'])
@login_required
def legal_accept():
    """Зафиксировать согласие пользователя с документом (MVP)."""
    doc = (request.form.get('document_key') or '').strip().lower()
    version = (request.form.get('version') or '1').strip()
    if doc not in {'offer', 'privacy'}:
        flash('Некорректный документ.', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        consent = UserConsent(
            user_id=current_user.id,
            document_key=doc,
            version=version,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        db.session.add(consent)
        db.session.commit()
    except Exception:
        db.session.rollback()

    flash('Согласие сохранено.', 'success')
    return redirect(url_for('main.dashboard'))

@main_bp.route('/health')
def health_check():
    """
    Простейший endpoint для проверки работоспособности приложения
    Не требует авторизации и не использует БД
    """
    try:
        from flask import jsonify
        return jsonify({
            'status': 'OK',
            'message': 'Application is running',
            'environment': os.environ.get('ENVIRONMENT', 'unknown'),
            'database_url_set': 'YES' if os.environ.get('DATABASE_URL') else 'NO',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        from flask import jsonify
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 200

@main_bp.route('/setup/first-user', methods=['GET', 'POST'])
@csrf.exempt  # Отключаем CSRF для этого endpoint (работает только если в БД нет пользователей)
def setup_first_user():
    """
    Временный endpoint для создания первого пользователя в пустой базе
    Работает только если в базе нет пользователей (для безопасности)
    После создания первого пользователя этот endpoint автоматически отключается
    """
    from flask import jsonify, request
    from werkzeug.security import generate_password_hash
    from core.db_models import moscow_now
    
    try:
        # Проверяем подключение к БД и количество пользователей
        try:
            user_count = User.query.count()
        except Exception as db_error:
            # Если БД недоступна, возвращаем ошибку
            return jsonify({
                'success': False,
                'error': f'Database connection failed: {str(db_error)}',
                'hint': 'Check DATABASE_URL configuration in Railway Variables'
            }), 500
        
        if user_count > 0:
            return jsonify({
                'success': False,
                'error': 'Users already exist. This endpoint is disabled for security.',
                'user_count': user_count
            }), 403
        
        if request.method == 'GET':
            # Показываем форму для создания пользователя
            return jsonify({
                'message': 'Create first user',
                'method': 'POST',
                'fields': {
                    'username': 'string (required)',
                    'password': 'string (required)',
                    'role': 'string (optional, default: creator)',
                    'email': 'string (optional)'
                },
                'example': {
                    'username': 'admin',
                    'password': 'your_secure_password',
                    'role': 'creator',
                    'email': 'admin@example.com'
                }
            }), 200
        
        # POST - создаем пользователя
        data = request.get_json() if request.is_json else request.form
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'creator').strip()
        email = data.get('email', '').strip() or None
        
        if not username:
            return jsonify({'success': False, 'error': 'Username is required'}), 400
        
        if not password:
            return jsonify({'success': False, 'error': 'Password is required'}), 400
        
        if len(password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
        
        # Проверяем, что пользователь с таким username не существует
        try:
            if User.query.filter_by(username=username).first():
                return jsonify({'success': False, 'error': 'Username already exists'}), 409
        except Exception as db_error:
            return jsonify({
                'success': False,
                'error': f'Database query failed: {str(db_error)}',
                'hint': 'Check DATABASE_URL configuration'
            }), 500
        
        # Создаем пользователя
        try:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=True,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Failed to create user: {str(db_error)}',
                'hint': 'Check database connection and permissions'
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'User "{username}" created successfully',
            'username': username,
            'role': role,
            'note': 'You can now login with these credentials. This endpoint is now disabled.'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating first user: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/')
@main_bp.route('/landing')
def landing():
    """Гостевая страница (landing page) - доступна без авторизации"""
    # Если это админ-окружение, сразу редиректим в админку
    if os.environ.get('ENVIRONMENT') == 'admin':
        return redirect(url_for('remote_admin.dashboard'))
    
    # Страница доступна всем, включая авторизованных пользователей
    return render_template('landing.html')


@main_bp.route('/index')
@main_bp.route('/home')
def index():
    """Главная страница с описанием платформы"""
    # Если это админ-окружение, сразу редиректим в админку
    if os.environ.get('ENVIRONMENT') == 'admin':
        return redirect(url_for('remote_admin.dashboard'))

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Главная страница (dashboard) со списком студентов"""
    # Редирект для родителя на его дашборд
    if current_user.is_parent():
        return redirect(url_for('parents.parent_dashboard'))
    
    # Редирект для ученика на его дашборд
    if current_user.is_student():
        return redirect(url_for('main.student_dashboard'))
    
    # Для ролей designer и tester - редирект на соответствующие страницы или пустой dashboard
    if current_user.is_designer():
        # Дизайнер может быть перенаправлен на страницу управления ассетами
        # Или показать пустой dashboard с сообщением
        pass  # Продолжаем выполнение, покажем пустой dashboard
    elif current_user.role == 'tester' and not current_user.is_chief_tester():
        # Обычный тестировщик - показываем пустой dashboard
        pass  # Продолжаем выполнение, покажем пустой dashboard
    
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')
    show_archive = request.args.get('show_archive', 'false').lower() == 'true'  # Параметр для просмотра архива

    # Выбираем активных или архивных учеников в зависимости от параметра
    if show_archive:
        query = Student.query.filter_by(is_active=False)
    else:
        query = Student.query.filter_by(is_active=True)
    
    # Применяем data scoping (фильтрация по ролям)
    # Для админа и старых ролей - видит всех
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and scope['student_ids']:
        # Enrollment и FamilyTie содержат user_id (User.id), а не student_id (Student.student_id)
        # Нужно найти Student записи по email пользователей
        student_users = User.query.filter(User.id.in_(scope['student_ids'])).all()
        student_emails = [u.email for u in student_users if u.email]
        
        # Логируем для отладки
        logger.debug(f"Dashboard: scope student_ids={scope['student_ids']}, found {len(student_users)} users, emails={student_emails}")
        
        if student_emails:
            # Находим Student записи по email
            accessible_students = Student.query.filter(Student.email.in_(student_emails)).all()
            logger.debug(f"Dashboard: found {len(accessible_students)} Student records for emails {student_emails}")
            if accessible_students:
                accessible_student_ids = [s.student_id for s in accessible_students]
                query = query.filter(Student.student_id.in_(accessible_student_ids))
            else:
                # Если Student записи не найдены, логируем и показываем пустой список
                logger.warning(f"Dashboard: No Student records found for emails {student_emails}, user_ids={scope['student_ids']}")
                query = query.filter(False)
        else:
            # Если у пользователей нет email, логируем и показываем пустой список
            logger.warning(f"Dashboard: Users {scope['student_ids']} have no email addresses")
            query = query.filter(False)
    elif not scope['can_see_all'] and not scope['student_ids']:
        # Нет доступа ни к каким ученикам
        query = query.filter(False)

    if search_query:
        search_pattern = f'%{search_query}%'
        filters = [
            Student.name.ilike(search_pattern)
        ]
        
        # Если запрос начинается с #, это platform_id
        if search_query.startswith('#'):
            # Убираем # и ищем по platform_id
            platform_id_query = search_query[1:].strip()
            if platform_id_query:
                filters.append(Student.platform_id.ilike(f'%{platform_id_query}%'))
        else:
            # Ищем по platform_id как строке (может содержать числа)
            filters.append(Student.platform_id.ilike(search_pattern))
            # Если запрос - чисто число, ищем также по student_id
            # НО только если это не совпадает с User.id текущего пользователя
            try:
                student_id_num = int(search_query)
                # Исключаем поиск по student_id, если он совпадает с User.id текущего пользователя
                # Это предотвращает конфликт идентификаторов
                if current_user.id != student_id_num:
                    filters.append(Student.student_id == student_id_num)
            except ValueError:
                pass
        
        query = query.filter(or_(*filters))

    if category_filter:
        query = query.filter_by(category=category_filter)

    page = request.args.get('page', 1, type=int)
    per_page = 20
    pagination = query.order_by(Student.name).paginate(page=page, per_page=per_page, error_out=False)
    students = pagination.items

    # Статистика зависит от того, показываем ли мы архив
    # Оптимизация: используем один запрос с группировкой для категорий
    base_is_active = not show_archive
    
    if category_filter:
        # Если есть фильтр категории, считаем только из текущей выборки
        total_students = len(students)
        ege_students = len([s for s in students if s.category == 'ЕГЭ']) if category_filter != 'ЕГЭ' else total_students
        oge_students = len([s for s in students if s.category == 'ОГЭ']) if category_filter != 'ОГЭ' else total_students
        levelup_students = len([s for s in students if s.category == 'ЛЕВЕЛАП']) if category_filter != 'ЛЕВЕЛАП' else total_students
        programming_students = len([s for s in students if s.category == 'ПРОГРАММИРОВАНИЕ']) if category_filter != 'ПРОГРАММИРОВАНИЕ' else total_students
    else:
        # Если нет фильтра, используем один запрос с группировкой
        # Применяем data scoping к подсчету студентов
        count_query = Student.query.filter_by(is_active=base_is_active)
        if not scope['can_see_all'] and scope['student_ids']:
            student_users = User.query.filter(User.id.in_(scope['student_ids'])).all()
            student_emails = [u.email for u in student_users if u.email]
            if student_emails:
                count_query = count_query.filter(Student.email.in_(student_emails))
            else:
                count_query = count_query.filter(False)
        elif not scope['can_see_all']:
            count_query = count_query.filter(False)
        
        try:
            total_students = count_query.count()
        except Exception as e:
            logger.warning(f"Error counting total students: {e}")
            total_students = 0
        
        # Статистика по категориям с учетом data scoping
        try:
            category_stats_query = db.session.query(
                Student.category,
                func.count(Student.student_id).label('count')
            ).filter_by(is_active=base_is_active)
            
            if not scope['can_see_all'] and scope['student_ids']:
                student_users = User.query.filter(User.id.in_(scope['student_ids'])).all()
                student_emails = [u.email for u in student_users if u.email]
                if student_emails:
                    accessible_students = Student.query.filter(Student.email.in_(student_emails)).all()
                    if accessible_students:
                        accessible_student_ids = [s.student_id for s in accessible_students]
                        category_stats_query = category_stats_query.filter(Student.student_id.in_(accessible_student_ids))
                    else:
                        category_stats_query = category_stats_query.filter(False)
                else:
                    category_stats_query = category_stats_query.filter(False)
            elif not scope['can_see_all']:
                category_stats_query = category_stats_query.filter(False)
            
            category_stats = category_stats_query.group_by(Student.category).all()
            
            category_dict = {cat[0]: cat[1] for cat in category_stats if cat[0]}
            ege_students = category_dict.get('ЕГЭ', 0)
            oge_students = category_dict.get('ОГЭ', 0)
            levelup_students = category_dict.get('ЛЕВЕЛАП', 0)
            programming_students = category_dict.get('ПРОГРАММИРОВАНИЕ', 0)
        except Exception as e:
            logger.warning(f"Error getting category statistics: {e}")
            ege_students = 0
            oge_students = 0
            levelup_students = 0
            programming_students = 0
    
    # Оптимизация: объединяем запросы статистики где возможно
    # Статистика по урокам - один запрос с группировкой
    # Применяем data scoping к урокам
    try:
        lesson_query = db.session.query(
            Lesson.status,
            func.count(Lesson.lesson_id).label('count')
        )
        
        # Фильтруем уроки по доступным ученикам
        if not scope['can_see_all'] and scope['student_ids']:
            student_users = User.query.filter(User.id.in_(scope['student_ids'])).all()
            student_emails = [u.email for u in student_users if u.email]
            if student_emails:
                accessible_students = Student.query.filter(Student.email.in_(student_emails)).all()
                accessible_student_ids = [s.student_id for s in accessible_students]
                lesson_query = lesson_query.filter(Lesson.student_id.in_(accessible_student_ids))
            else:
                accessible_student_ids = []
        elif not scope['can_see_all']:
            accessible_student_ids = []
        else:
            accessible_student_ids = None
        
        lesson_stats = lesson_query.group_by(Lesson.status).all()
        
        lesson_stats_dict = {stat[0]: stat[1] for stat in lesson_stats}
        total_lessons = sum(lesson_stats_dict.values())
        completed_lessons = lesson_stats_dict.get('completed', 0)
        planned_lessons = lesson_stats_dict.get('planned', 0)
        in_progress_lessons = lesson_stats_dict.get('in_progress', 0)
        cancelled_lessons = lesson_stats_dict.get('cancelled', 0)
    except Exception as e:
        logger.warning(f"Error getting lesson statistics: {e}")
        accessible_student_ids = []
        total_lessons = 0
        completed_lessons = 0
        planned_lessons = 0
        in_progress_lessons = 0
        cancelled_lessons = 0
    
    # Статистика по архивным ученикам - только если есть доступ
    try:
        archived_students_count = Student.query.filter_by(is_active=False).count()
    except Exception as e:
        logger.warning(f"Error counting archived students: {e}")
        archived_students_count = 0
    
    # Статистика по заданиям - используем подзапросы для оптимизации
    # Ученик и родитель не видят общую статистику по задачам
    try:
        if current_user.is_student() or current_user.is_parent() or current_user.is_designer() or (current_user.role == 'tester' and not current_user.is_chief_tester()):
            total_tasks = 0
            accepted_tasks_count = 0
            skipped_tasks_count = 0
            blacklisted_tasks_count = 0
        else:
            total_tasks = Tasks.query.count()
            # Используем подзапросы вместо distinct для лучшей производительности
            accepted_tasks_count = db.session.query(func.count(func.distinct(UsageHistory.task_fk))).scalar() or 0
            skipped_tasks_count = db.session.query(func.count(func.distinct(SkippedTasks.task_fk))).scalar() or 0
            blacklisted_tasks_count = db.session.query(func.count(func.distinct(BlacklistTasks.task_fk))).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting task statistics: {e}")
        total_tasks = 0
        accepted_tasks_count = 0
        skipped_tasks_count = 0
        blacklisted_tasks_count = 0
    
    # Статистика по последним урокам (за последние 7 дней)
    # Считаем только уроки, которые были проведены за последние 7 дней
    try:
        now = moscow_now()
        week_ago = now - timedelta(days=7)
        
        # Уроки, которые были проведены за последние 7 дней
        recent_completed_query = Lesson.query.filter(
            Lesson.status == 'completed',
            Lesson.lesson_date >= week_ago,
            Lesson.lesson_date <= now
        )
        if accessible_student_ids is not None:
            recent_completed_query = recent_completed_query.filter(Lesson.student_id.in_(accessible_student_ids))
        recent_completed = recent_completed_query.count()
        
        # Уроки, запланированные на ближайшие 7 дней (в будущем)
        week_ahead = now + timedelta(days=7)
        recent_planned_query = Lesson.query.filter(
            Lesson.status.in_(['planned', 'in_progress']),
            Lesson.lesson_date >= now,
            Lesson.lesson_date <= week_ahead
        )
        if accessible_student_ids is not None:
            recent_planned_query = recent_planned_query.filter(Lesson.student_id.in_(accessible_student_ids))
        recent_planned = recent_planned_query.count()
        
        recent_lessons = recent_completed + recent_planned
        
        # Статистика по домашним заданиям (только за последние 7 дней - проведенные уроки)
        homework_query = Lesson.query.filter(
            Lesson.status == 'completed',
            Lesson.lesson_date >= week_ago,
            Lesson.lesson_date <= now,
            Lesson.homework_status.in_(['assigned_done', 'assigned_not_done'])
        )
        if accessible_student_ids is not None:
            homework_query = homework_query.filter(Lesson.student_id.in_(accessible_student_ids))
        lessons_with_homework = homework_query.count()
    except Exception as e:
        logger.warning(f"Error getting recent lessons statistics: {e}")
        recent_lessons = 0
        lessons_with_homework = 0

    # Teacher overview: очередь проверки + группы (не зависит от фильтров UI)
    review_lesson_tasks_count = 0
    review_submissions_count = 0
    groups_count = 0
    try:
        from app.models import LessonTask, Submission, Assignment, SchoolGroup

        accessible_ids = None
        if not scope.get('can_see_all'):
            accessible_ids = []
            try:
                user_ids = scope.get('student_ids') or []
                if user_ids:
                    student_users = User.query.filter(User.id.in_(user_ids)).all()
                    emails = [u.email for u in student_users if u and u.email]
                    if emails:
                        st = Student.query.filter(Student.email.in_(emails)).all()
                        accessible_ids = [s.student_id for s in st if s]
            except Exception:
                accessible_ids = []

        qlt = LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).filter(LessonTask.status == 'submitted')
        if accessible_ids is not None:
            if not accessible_ids:
                qlt = qlt.filter(False)
            else:
                qlt = qlt.filter(Lesson.student_id.in_(accessible_ids))
        review_lesson_tasks_count = qlt.count()

        qs = Submission.query.join(Assignment, Assignment.assignment_id == Submission.assignment_id).filter(Submission.status.in_(['SUBMITTED', 'LATE']))
        if not scope.get('can_see_all'):
            qs = qs.filter(Assignment.created_by_id == current_user.id)
        if accessible_ids is not None:
            if not accessible_ids:
                qs = qs.filter(False)
            else:
                qs = qs.filter(Submission.student_id.in_(accessible_ids))
        review_submissions_count = qs.count()

        qg = SchoolGroup.query
        if not scope.get('can_see_all'):
            qg = qg.filter(SchoolGroup.owner_user_id == current_user.id)
        groups_count = qg.count()
    except Exception as e:
        logger.warning(f"Failed to build teacher overview counters: {e}")

    return render_template('dashboard.html',
                         students=students,
                         pagination=pagination,
                         search_query=search_query,
                         category_filter=category_filter,
                         show_archive=show_archive,
                         total_students=total_students,
                         total_lessons=total_lessons,
                         completed_lessons=completed_lessons,
                         planned_lessons=planned_lessons,
                         in_progress_lessons=in_progress_lessons,
                         cancelled_lessons=cancelled_lessons,
                         ege_students=ege_students,
                         oge_students=oge_students,
                         levelup_students=levelup_students,
                         programming_students=programming_students,
                         archived_students_count=archived_students_count,
                         total_tasks=total_tasks,
                         accepted_tasks_count=accepted_tasks_count,
                         skipped_tasks_count=skipped_tasks_count,
                         blacklisted_tasks_count=blacklisted_tasks_count,
                         lessons_with_homework=lessons_with_homework,
                         recent_lessons=recent_lessons,
                         review_lesson_tasks_count=review_lesson_tasks_count,
                         review_submissions_count=review_submissions_count,
                         groups_count=groups_count)


@main_bp.route('/student/dashboard')
@login_required
def student_dashboard():
    """Дашборд ученика: план, задания, риски по темам."""
    if not current_user.is_student():
        return redirect(url_for('main.dashboard'))

    # Пытаемся найти связанного Student
    student = None
    try:
        if current_user.email:
            student = Student.query.filter_by(email=current_user.email).first()
    except Exception:
        student = None
    if not student:
        # fallback: иногда student_id == User.id
        try:
            student = Student.query.get(current_user.id)
        except Exception:
            student = None

    if not student:
        flash('Профиль ученика не найден.', 'warning')
        return render_template('student_dashboard.html', student=None, plan_items=[], pending_submissions=[], unread_notifications=0, problem_topics=[])

    from app.students.stats_service import StatsService
    from app.models import StudentLearningPlanItem, Submission, UserNotification, GradebookEntry
    try:
        plan_items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
            StudentLearningPlanItem.due_date.asc().nullslast(),
            StudentLearningPlanItem.priority.desc(),
            StudentLearningPlanItem.item_id.desc(),
        ).limit(12).all()
    except Exception:
        plan_items = []

    try:
        pending_submissions = Submission.query.filter(
            Submission.student_id == student.student_id,
            Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED'])
        ).options(db.joinedload(Submission.assignment)).order_by(Submission.assigned_at.desc()).limit(12).all()
    except Exception:
        pending_submissions = []

    try:
        unread_notifications = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).count()
    except Exception:
        unread_notifications = 0

    problem_topics = []
    try:
        stats = StatsService(student.student_id)
        problem_topics = stats.get_problem_topics(threshold=60)[:6]
    except Exception:
        problem_topics = []

    # Последние оценки из журнала (MVP, для мотивации)
    try:
        recent_grades = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
            GradebookEntry.created_at.desc(),
            GradebookEntry.entry_id.desc()
        ).limit(8).all()
    except Exception:
        recent_grades = []

    return render_template(
        'student_dashboard.html',
        student=student,
        plan_items=plan_items,
        pending_submissions=pending_submissions,
        unread_notifications=unread_notifications,
        problem_topics=problem_topics,
        recent_grades=recent_grades,
    )

@main_bp.route('/update-plans')
@login_required
def update_plans():
    """Страница планов обновления"""
    try:
        # Определяем пути относительно текущего файла и рабочей директории
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        # app/main/routes.py -> app/ -> корень проекта
        project_root = os.path.dirname(os.path.dirname(current_file_dir))
        cwd = os.getcwd()
        
        # Список возможных путей (от наиболее вероятных к менее вероятным)
        possible_paths = [
            # В корне проекта (локально и на Railway)
            os.path.join(project_root, 'UPDATE_PLANS.md'),
            os.path.join(cwd, 'UPDATE_PLANS.md'),
            '/app/UPDATE_PLANS.md',  # Railway стандартный путь
            # В docs/ (локально и на Railway)
            os.path.join(project_root, 'docs', 'UPDATE_PLANS.md'),
            os.path.join(cwd, 'docs', 'UPDATE_PLANS.md'),
            '/app/docs/UPDATE_PLANS.md',  # Railway стандартный путь
            # Через base_dir (старый способ)
            os.path.join(base_dir, 'UPDATE_PLANS.md'),
            os.path.join(base_dir, 'docs', 'UPDATE_PLANS.md'),
        ]
        
        plans_content = None
        found_path = None
        
        for plans_file_path in possible_paths:
            try:
                if os.path.exists(plans_file_path) and os.path.isfile(plans_file_path):
                    with open(plans_file_path, 'r', encoding='utf-8') as f:
                        plans_content = f.read()
                    found_path = plans_file_path
                    logger.info(f"✓ Файл UPDATE_PLANS.md найден: {found_path}")
                    break
            except (OSError, IOError, UnicodeDecodeError) as path_error:
                logger.debug(f"Не удалось прочитать путь {plans_file_path}: {path_error}")
                continue
        
        if plans_content is None:
            # Если файл не найден, логируем для отладки
            logger.warning(f"✗ Файл UPDATE_PLANS.md не найден")
            logger.warning(f"Текущая рабочая директория: {cwd}")
            logger.warning(f"project_root: {project_root}, base_dir: {base_dir}")
            logger.warning(f"Проверенные пути: {possible_paths}")
            
            # Возвращаем сообщение с информацией для отладки
            debug_info = f"\n\n**Отладочная информация:**\n"
            debug_info += f"- Рабочая директория: `{cwd}`\n"
            debug_info += f"- Корень проекта: `{project_root}`\n"
            debug_info += f"- base_dir: `{base_dir}`\n"
            debug_info += f"\n**Проверенные пути:**\n"
            for p in possible_paths:
                exists = "✓" if os.path.exists(p) else "✗"
                debug_info += f"- {exists} `{p}`\n"
            
            plans_content = f"# Планы обновления\n\n⚠️ Файл с планами обновления не найден.{debug_info}"
        
        return render_template('update_plans.html', plans_content=plans_content)
    except Exception as e:
        logger.error(f"Ошибка при чтении файла планов обновления: {e}", exc_info=True)
        flash('Не удалось загрузить планы обновления', 'error')
        return redirect(url_for('main.dashboard'))

@main_bp.route('/font/<path:filename>')
def font_files(filename):
    """Сервим шрифты из папки static/font"""
    font_dir = os.path.join(base_dir, 'static', 'font')
    return send_from_directory(font_dir, filename, mimetype='font/otf' if filename.endswith('.otf') else 'font/ttf')

# Вспомогательная функция для нормализации статуса домашнего задания
HOMEWORK_STATUS_VALUES = {'assigned_done', 'assigned_not_done', 'not_assigned'}
LEGACY_HOMEWORK_STATUS_MAP = {
    'completed': 'assigned_done',
    'pending': 'assigned_not_done',
    'not_done': 'assigned_not_done',
    'not_assigned': 'not_assigned'
}

def normalize_homework_status_value(raw_status):
    """Преобразует устаревшие статусы к актуальным"""
    if raw_status is None:
        return 'not_assigned'
    if isinstance(raw_status, str):
        normalized = raw_status.strip()
    else:
        normalized = raw_status
    normalized = LEGACY_HOMEWORK_STATUS_MAP.get(normalized, normalized)
    return normalized if normalized in HOMEWORK_STATUS_VALUES else 'not_assigned'

logger = logging.getLogger(__name__)

@main_bp.route('/export-data')
@login_required
def export_data():
    """Экспорт данных в JSON"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Экспорт доступен только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    try:
        logger.info('Начало экспорта данных')
        export_data_dict = {
            'students': [{
                'name': s.name,
                'platform_id': s.platform_id,
                'category': s.category,
                'target_score': s.target_score,
                'deadline': s.deadline,
                'diagnostic_level': s.diagnostic_level,
                'description': s.description,
                'notes': s.notes,
                'strengths': s.strengths,
                'weaknesses': s.weaknesses,
                'preferences': s.preferences,
                'overall_rating': s.overall_rating,
                'school_class': s.school_class,
                'goal_text': s.goal_text,
                'programming_language': s.programming_language
            } for s in Student.query.filter_by(is_active=True).all()],
            'lessons': [{
                'student_id': l.student_id,
                'lesson_type': l.lesson_type,
                'lesson_date': l.lesson_date.isoformat() if l.lesson_date else None,
                'duration': l.duration,
                'status': l.status,
                'topic': l.topic,
                'notes': l.notes,
                'homework': l.homework,
                'homework_status': l.homework_status,
                'homework_result_percent': l.homework_result_percent,
                'homework_result_notes': l.homework_result_notes
            } for l in Lesson.query.all()]
        }
        response = make_response(json.dumps(export_data_dict, ensure_ascii=False, indent=2))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        logger.info(f'Экспорт завершен: {len(export_data_dict["students"])} учеников, {len(export_data_dict["lessons"])} уроков')
        
        audit_logger.log(
            action='export_data',
            entity='Data',
            entity_id=None,
            status='success',
            metadata={
                'students_count': len(export_data_dict["students"]),
                'lessons_count': len(export_data_dict["lessons"])
            }
        )
        
        return response
    except Exception as e:
        logger.error(f'Ошибка при экспорте данных: {e}')
        audit_logger.log_error(
            action='export_data',
            entity='Data',
            error=str(e)
        )
        flash(f'Ошибка при экспорте данных: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

@main_bp.route('/import-data', methods=['GET', 'POST'])
@login_required
def import_data():
    """Импорт данных из JSON"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Импорт доступен только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    if request.method == 'GET':
        return render_template('import_data.html')
    try:
        if 'file' not in request.files:
            flash('Файл не выбран', 'error')
            return redirect(url_for('main.import_data'))
        file = request.files['file']
        if file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(url_for('main.import_data'))
        if not file.filename.endswith('.json'):
            flash('Поддерживаются только JSON файлы', 'error')
            return redirect(url_for('main.import_data'))
        data = json.loads(file.read().decode('utf-8'))
        imported_students = 0
        imported_lessons = 0
        if 'students' in data:
            for student_data in data['students']:
                existing = Student.query.filter_by(
                    name=student_data.get('name'),
                    platform_id=student_data.get('platform_id')
                ).first()
                if not existing:
                    student = Student(
                        name=student_data.get('name'),
                        platform_id=student_data.get('platform_id'),
                        category=student_data.get('category'),
                        target_score=student_data.get('target_score'),
                        deadline=student_data.get('deadline'),
                        diagnostic_level=student_data.get('diagnostic_level'),
                        description=student_data.get('description'),
                        notes=student_data.get('notes'),
                        strengths=student_data.get('strengths'),
                        weaknesses=student_data.get('weaknesses'),
                        preferences=student_data.get('preferences'),
                        overall_rating=student_data.get('overall_rating'),
                        school_class=normalize_school_class(student_data.get('school_class')),
                        goal_text=student_data.get('goal_text'),
                        programming_language=student_data.get('programming_language'),
                        is_active=True
                    )
                    db.session.add(student)
                    imported_students += 1
        if 'lessons' in data:
            for lesson_data in data['lessons']:
                if Student.query.get(lesson_data.get('student_id')):
                    imported_type = lesson_data.get('lesson_type')
                    imported_homework_status = normalize_homework_status_value(lesson_data.get('homework_status'))
                    imported_homework = lesson_data.get('homework')
                    if imported_type == 'introductory':
                        imported_homework = ''
                        imported_homework_status = 'not_assigned'
                    lesson = Lesson(
                        student_id=lesson_data.get('student_id'),
                        lesson_type=imported_type,
                        lesson_date=datetime.fromisoformat(lesson_data['lesson_date']) if lesson_data.get('lesson_date') else moscow_now(),
                        duration=lesson_data.get('duration', 60),
                        status=lesson_data.get('status', 'planned'),
                        topic=lesson_data.get('topic'),
                        notes=lesson_data.get('notes'),
                        homework=imported_homework,
                        homework_status=imported_homework_status,
                        homework_result_percent=lesson_data.get('homework_result_percent'),
                        homework_result_notes=lesson_data.get('homework_result_notes')
                    )
                    db.session.add(lesson)
                    imported_lessons += 1
        db.session.commit()
        logger.info(f'Импорт завершен: {imported_students} учеников, {imported_lessons} уроков')
        
        audit_logger.log(
            action='import_data',
            entity='Data',
            entity_id=None,
            status='success',
            metadata={
                'students_count': imported_students,
                'lessons_count': imported_lessons,
                'filename': file.filename
            }
        )
        
        flash(f'Импорт завершен: добавлено {imported_students} учеников и {imported_lessons} уроков', 'success')
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при импорте данных: {e}')
        audit_logger.log_error(
            action='import_data',
            entity='Data',
            error=str(e)
        )
        flash(f'Ошибка при импорте данных: {str(e)}', 'error')
        return redirect(url_for('main.import_data'))

@main_bp.route('/backup-db')
@login_required
def backup_db():
    """Создание резервной копии базы данных"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Резервное копирование доступно только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    try:
        # Для PostgreSQL на Railway резервное копирование должно выполняться через pg_dump
        # или через интерфейс Railway. Здесь просто логируем попытку.
        logger.info('Попытка создания резервной копии базы данных')
        
        # Проверяем тип базы данных
        db_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql' in db_url or 'postgres' in db_url:
            flash('Для PostgreSQL резервное копирование должно выполняться через pg_dump или интерфейс Railway. Используйте экспорт данных для создания резервной копии.', 'info')
            return redirect(url_for('main.export_data'))
        
        # Для SQLite (если используется локально)
        backup_dir = os.path.join(base_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_filename = f'keg_tasks_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Если используется SQLite, копируем файл
        db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
            logger.info(f'Резервная копия создана: {backup_path}')
            
            audit_logger.log(
                action='backup_database',
                entity='Database',
                entity_id=None,
                status='success',
                metadata={
                    'backup_filename': backup_filename,
                    'backup_path': backup_path
                }
            )
            flash(f'Резервная копия создана: {backup_filename}', 'success')
        else:
            flash('Файл базы данных не найден. Используется PostgreSQL.', 'info')
            return redirect(url_for('main.export_data'))
        
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        logger.error(f'Ошибка при создании резервной копии: {e}')
        flash(f'Ошибка при создании резервной копии: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

