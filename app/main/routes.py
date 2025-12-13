"""
Основные маршруты приложения
"""
import logging
from flask import render_template, request, send_from_directory, flash, redirect, url_for
from flask_login import login_required
import os

from app.main import main_bp
from app.models import Student, Lesson, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, db, moscow_now
from sqlalchemy import func, or_
from datetime import timedelta

# Базовая директория проекта
base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

@main_bp.route('/')
@main_bp.route('/index')
@main_bp.route('/home')
@login_required
def index():
    """Главная страница с описанием платформы"""
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Главная страница (dashboard) со списком студентов"""
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')
    show_archive = request.args.get('show_archive', 'false').lower() == 'true'  # Параметр для просмотра архива

    # Выбираем активных или архивных учеников в зависимости от параметра
    if show_archive:
        query = Student.query.filter_by(is_active=False)
    else:
        query = Student.query.filter_by(is_active=True)

    if search_query:
        search_pattern = f'%{search_query}%'
        filters = [
            Student.name.ilike(search_pattern),
            Student.platform_id.ilike(search_pattern)
        ]
        try:
            student_id_num = int(search_query)
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
        total_students = Student.query.filter_by(is_active=base_is_active).count()
        category_stats = db.session.query(
            Student.category,
            func.count(Student.student_id).label('count')
        ).filter_by(is_active=base_is_active).group_by(Student.category).all()
        
        category_dict = {cat[0]: cat[1] for cat in category_stats if cat[0]}
        ege_students = category_dict.get('ЕГЭ', 0)
        oge_students = category_dict.get('ОГЭ', 0)
        levelup_students = category_dict.get('ЛЕВЕЛАП', 0)
        programming_students = category_dict.get('ПРОГРАММИРОВАНИЕ', 0)
    
    # Оптимизация: объединяем запросы статистики где возможно
    # Статистика по урокам - один запрос с группировкой
    lesson_stats = db.session.query(
        Lesson.status,
        func.count(Lesson.lesson_id).label('count')
    ).group_by(Lesson.status).all()
    
    lesson_stats_dict = {stat[0]: stat[1] for stat in lesson_stats}
    total_lessons = sum(lesson_stats_dict.values())
    completed_lessons = lesson_stats_dict.get('completed', 0)
    planned_lessons = lesson_stats_dict.get('planned', 0)
    in_progress_lessons = lesson_stats_dict.get('in_progress', 0)
    cancelled_lessons = lesson_stats_dict.get('cancelled', 0)
    
    archived_students_count = Student.query.filter_by(is_active=False).count()
    
    # Статистика по заданиям - используем подзапросы для оптимизации
    total_tasks = Tasks.query.count()
    # Используем подзапросы вместо distinct для лучшей производительности
    accepted_tasks_count = db.session.query(func.count(func.distinct(UsageHistory.task_fk))).scalar() or 0
    skipped_tasks_count = db.session.query(func.count(func.distinct(SkippedTasks.task_fk))).scalar() or 0
    blacklisted_tasks_count = db.session.query(func.count(func.distinct(BlacklistTasks.task_fk))).scalar() or 0
    
    # Статистика по последним урокам (за последние 7 дней)
    # Считаем только уроки, которые были проведены за последние 7 дней
    now = moscow_now()
    week_ago = now - timedelta(days=7)
    
    # Уроки, которые были проведены за последние 7 дней
    recent_completed = Lesson.query.filter(
        Lesson.status == 'completed',
        Lesson.lesson_date >= week_ago,
        Lesson.lesson_date <= now
    ).count()
    
    # Уроки, запланированные на ближайшие 7 дней (в будущем)
    week_ahead = now + timedelta(days=7)
    recent_planned = Lesson.query.filter(
        Lesson.status.in_(['planned', 'in_progress']),
        Lesson.lesson_date >= now,
        Lesson.lesson_date <= week_ahead
    ).count()
    
    recent_lessons = recent_completed + recent_planned
    
    # Статистика по домашним заданиям (только за последние 7 дней - проведенные уроки)
    lessons_with_homework = Lesson.query.filter(
        Lesson.status == 'completed',
        Lesson.lesson_date >= week_ago,
        Lesson.lesson_date <= now,
        Lesson.homework_status.in_(['assigned_done', 'assigned_not_done'])
    ).count()

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
                         recent_lessons=recent_lessons)

@main_bp.route('/update-plans')
@login_required
def update_plans():
    """Страница планов обновления"""
    try:
        plans_file_path = os.path.join(base_dir, 'UPDATE_PLANS.md')
        with open(plans_file_path, 'r', encoding='utf-8') as f:
            plans_content = f.read()
        return render_template('update_plans.html', plans_content=plans_content)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при чтении файла планов обновления: {e}")
        flash('Не удалось загрузить планы обновления', 'error')
        return redirect(url_for('main.dashboard'))

@main_bp.route('/font/<path:filename>')
def font_files(filename):
    """Сервим шрифты из папки static/font"""
    font_dir = os.path.join(base_dir, 'static', 'font')
    return send_from_directory(font_dir, filename, mimetype='font/otf' if filename.endswith('.otf') else 'font/ttf')

