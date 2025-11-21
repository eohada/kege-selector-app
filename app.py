import os
import json
import ast
import logging
import shutil
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, session
from flask_wtf import FlaskForm, CSRFProtect
import re
from html import unescape
from importlib import import_module
from sqlalchemy import inspect, text, or_
from datetime import datetime, UTC, timedelta, time
import math

BeautifulSoup = None
from wtforms import SelectField, IntegerField, SubmitField, BooleanField, StringField, TextAreaField, DateTimeField, DateTimeLocalField
from wtforms.validators import DataRequired, NumberRange, Optional, Email, ValidationError

from core.db_models import db, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, Student, Lesson, LessonTask, moscow_now, MOSCOW_TZ, TOMSK_TZ
from core.selector_logic import (
    get_unique_tasks, record_usage, record_skipped, record_blacklist,
    reset_history, reset_skipped, reset_blacklist,
    get_accepted_tasks, get_skipped_tasks
)
from core.audit_logger import audit_logger
import uuid

app = Flask(__name__)

base_dir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')

database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    # В Railway внутренний URL должен работать, но если нет - используем внешний
    # Проверяем, есть ли переменная для внешнего подключения
    external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
    if external_db_url:
        if external_db_url.startswith('postgres://'):
            external_db_url = external_db_url.replace('postgres://', 'postgresql://', 1)
        database_url = external_db_url
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'local-dev-key-12345')
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None

csrf = CSRFProtect(app)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Логируем информацию о БД после инициализации logger
if database_url:
    external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
    if external_db_url:
        logger.info("Using external database URL")
    else:
        logger.info(f"Using DATABASE_URL: {database_url[:20]}...")
else:
    logger.warning("DATABASE_URL not set, using SQLite")

db.init_app(app)
audit_logger.init_app(app)

# Запускаем worker thread для audit logger при первом запросе
@app.before_request
def ensure_audit_logger_worker():
    if not audit_logger.is_running:
        audit_logger.start_worker()

def ensure_schema_columns():
    try:
        with app.app_context():
            from core.db_models import Tester, AuditLog
            db.create_all()
            db.session.commit()

            inspector = inspect(db.engine)
            
            # Получаем реальное имя таблицы (может быть в нижнем регистре)
            table_names = inspector.get_table_names()
            lessons_table = 'Lessons' if 'Lessons' in table_names else ('lessons' if 'lessons' in table_names else None)
            students_table = 'Students' if 'Students' in table_names else ('students' if 'students' in table_names else None)
            lesson_tasks_table = 'LessonTasks' if 'LessonTasks' in table_names else ('lessontasks' if 'lessontasks' in table_names else None)
            
            if not lessons_table:
                logger.warning("Lessons table not found, skipping schema migration")
                return

            lesson_columns = {col['name'] for col in inspector.get_columns(lessons_table)}
            if 'homework_result_percent' not in lesson_columns:
                db.session.execute(text('ALTER TABLE Lessons ADD COLUMN homework_result_percent INTEGER'))
            if 'homework_result_notes' not in lesson_columns:
                db.session.execute(text('ALTER TABLE Lessons ADD COLUMN homework_result_notes TEXT'))

            if lesson_tasks_table:
                lesson_task_columns = {col['name'] for col in inspector.get_columns(lesson_tasks_table)}
                if 'assignment_type' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN assignment_type TEXT DEFAULT \'homework\''))
                if 'student_submission' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN student_submission TEXT'))
                if 'submission_correct' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN submission_correct INTEGER'))

            if students_table:
                student_columns = {col['name'] for col in inspector.get_columns(students_table)}
                if 'category' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN category TEXT'))

                indexes = {idx['name'] for idx in inspector.get_indexes(students_table)}
                if 'idx_students_category' not in indexes:
                    db.session.execute(text(f'CREATE INDEX idx_students_category ON "{students_table}"(category)'))

            lesson_indexes = {idx['name'] for idx in inspector.get_indexes(lessons_table)}
            if 'idx_lessons_status' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_status ON "{lessons_table}"(status)'))
            if 'idx_lessons_lesson_date' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_lesson_date ON "{lessons_table}"(lesson_date)'))

            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)
        raise  # Пробрасываем ошибку дальше

# Флаг для отслеживания, была ли выполнена инициализация схемы
_schema_initialized = False

@app.before_request
def initialize_on_first_request():
    global _schema_initialized
    
    # Инициализируем схему БД при первом запросе
    if not _schema_initialized:
        try:
            ensure_schema_columns()
            _schema_initialized = True
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
            # Не блокируем запрос, если миграция не удалась
            _schema_initialized = True  # Помечаем как инициализированную, чтобы не повторять
            logger.info("Database schema initialized")
        except Exception as e:
            logger.error(f"Error initializing schema: {e}", exc_info=True)
    
    # Запускаем worker thread для audit logger при первом запросе
    if not audit_logger.is_running:
        audit_logger.start_worker()

@app.before_request
def identify_tester():

    try:

        if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
            return

        tester_name = request.headers.get('X-Tester-Name')

        if 'tester_id' not in session:
            tester_id = str(uuid.uuid4())
            session['tester_id'] = tester_id

            if tester_name:
                session['tester_name'] = tester_name
            else:
                session['tester_name'] = 'Anonymous'

        if tester_name and tester_name != session.get('tester_name'):
            session['tester_name'] = tester_name
    except Exception as e:
        logger.error(f"Error identifying tester: {e}", exc_info=True)

@app.after_request
def log_page_view(response):

    try:

        if (request.endpoint in ('static', 'favicon') or
            request.path.startswith('/static/') or
            request.path.startswith('/admin-audit') or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.is_json):
            return response

        if request.method == 'GET' and response.status_code == 200:
            page_name = request.endpoint or request.path
            audit_logger.log_page_view(
                page_name=page_name,
                metadata={'status_code': response.status_code}
            )
    except Exception as e:
        logger.error(f"Error logging page view: {e}", exc_info=True)

    return response

@app.context_processor
def inject_active_lesson():
    try:
        from sqlalchemy.orm import joinedload
        active_lesson = Lesson.query.options(joinedload(Lesson.student)).filter_by(status='in_progress').first()
        active_student = active_lesson.student if active_lesson else None
        return dict(active_lesson=active_lesson, active_student=active_student)
    except Exception as e:
        return dict(active_lesson=None, active_student=None)

@app.template_filter('from_json')
def from_json_filter(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except:
        return []

@app.context_processor
def inject_csrf_token():

    from flask_wtf.csrf import generate_csrf
    return dict(csrf_token=generate_csrf)

@app.template_filter('markdown')
def markdown_filter(text):

    if not text:
        return ''
    try:
        import markdown
        md = markdown.Markdown(extensions=['extra', 'codehilite', 'nl2br'])
        return md.convert(text)
    except ImportError:

        import re
        html = text

        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)

        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

        html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)

        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'(<li>.*?</li>)', r'<ul>\1</ul>', html, flags=re.DOTALL)

        html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

        html = re.sub(r'\n\n', r'</p><p>', html)
        html = '<p>' + html + '</p>'
        return html

@app.route('/test-katex')
def test_katex():
    task = Tasks.query.filter_by(task_number=2).first()
    return render_template('test_katex.html', task_content=task.content_html if task else 'Нет заданий')

@app.route('/simple-test')
def simple_test():
    return render_template('simple_test.html')

@app.route('/raw-content')
def raw_content():
    task = Tasks.query.filter_by(task_number=2).first()
    if task:
        return render_template('raw_content.html',
                             task_id=task.task_id,
                             content=task.content_html,
                             content_length=len(task.content_html))
    return "Нет заданий типа 2"

@app.route('/test-static')
def test_static():
    import os
    static_dir = os.path.join(app.root_path, 'static', 'katex')
    files_exist = os.path.exists(static_dir)

    files_list = []
    if files_exist:
        for root, dirs, files in os.walk(static_dir):
            for file in files[:10]:
                rel_path = os.path.relpath(os.path.join(root, file), static_dir)
                files_list.append(rel_path)

    return f

class TaskSelectionForm(FlaskForm):
    task_type = SelectField('Номер задания', coerce=int, validators=[DataRequired()])
    limit_count = IntegerField('Количество заданий', validators=[DataRequired(), NumberRange(min=1, max=20, message="От 1 до 20")])
    use_skipped = BooleanField('Включить пропущенные задания', default=False)
    submit = SubmitField('Сгенерировать Набор')

class ResetForm(FlaskForm):
    task_type_reset = SelectField('Сбросить историю для', coerce=str, validators=[DataRequired()])
    reset_type = SelectField('Тип сброса', coerce=str, choices=[
        ('accepted', 'Принятые'),
        ('skipped', 'Пропущенные'),
        ('blacklist', 'Черный список'),
        ('all', 'Все')
    ], validators=[DataRequired()])
    reset_submit = SubmitField('Сбросить')

def validate_platform_id_unique(form, field):

    if field.data and field.data.strip():

        existing_student = Student.query.filter_by(platform_id=field.data.strip()).first()

        if hasattr(form, '_student_id') and form._student_id:
            if existing_student and existing_student.student_id != form._student_id:
                raise ValidationError('Ученик с таким ID на платформе уже существует!')
        else:

            if existing_student:
                raise ValidationError('Ученик с таким ID на платформе уже существует!')

class StudentForm(FlaskForm):
    name = StringField('Имя ученика', validators=[DataRequired()])
    platform_id = StringField('ID на платформе', validators=[Optional(), validate_platform_id_unique])

    target_score = IntegerField('Целевой балл', validators=[Optional(), NumberRange(min=0, max=100)])
    deadline = StringField('Сроки', validators=[Optional()])

    diagnostic_level = StringField('Уровень знаний (диагностика)', validators=[Optional()])
    preferences = TextAreaField('Предпочтения в решении', validators=[Optional()])
    strengths = TextAreaField('Сильные стороны', validators=[Optional()])
    weaknesses = TextAreaField('Слабые стороны', validators=[Optional()])
    overall_rating = StringField('Общая оценка', validators=[Optional()])

    description = TextAreaField('Краткое описание', validators=[Optional()])
    notes = TextAreaField('Дополнительные заметки', validators=[Optional()])
    category = SelectField('Категория', choices=[
        ('', 'Не выбрано'),
        ('ЕГЭ', 'ЕГЭ'),
        ('ОГЭ', 'ОГЭ'),
        ('ЛЕВЕЛАП', 'ЛЕВЕЛАП')
    ], default='', validators=[Optional()])

    submit = SubmitField('Сохранить')

class LessonForm(FlaskForm):
    lesson_type = SelectField('Тип урока', choices=[
        ('regular', '📚 Обычный урок'),
        ('exam', '✅ Проверочный урок'),
        ('introductory', '👋 Вводный урок')
    ], default='regular', validators=[DataRequired()])
    lesson_date = DateTimeLocalField('Дата и время урока', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    duration = IntegerField('Длительность (минуты)', default=60, validators=[DataRequired(), NumberRange(min=15, max=240)])
    status = SelectField('Статус', choices=[
        ('planned', 'Запланирован'),
        ('in_progress', 'Идет сейчас'),
        ('completed', 'Проведен'),
        ('cancelled', 'Отменен')
    ], validators=[DataRequired()])
    topic = StringField('Тема урока', validators=[Optional()])
    notes = TextAreaField('Заметки о уроке', validators=[Optional()])
    homework = TextAreaField('Домашнее задание', validators=[Optional()])
    homework_status = SelectField('Статус ДЗ', choices=[
        ('pending', 'Задано'),
        ('completed', 'Выполнено'),
        ('not_done', 'Не выполнено'),
        ('not_assigned', 'Не задано')
    ], default='pending', validators=[DataRequired()])
    submit = SubmitField('Сохранить')

@app.route('/')
def dashboard():
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')

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

    total_students = Student.query.filter_by(is_active=True).count()
    total_lessons = Lesson.query.count()
    completed_lessons = Lesson.query.filter_by(status='completed').count()
    planned_lessons = Lesson.query.filter_by(status='planned').count()
    ege_students = Student.query.filter_by(is_active=True, category='ЕГЭ').count() if category_filter != 'ЕГЭ' else len(students)
    oge_students = Student.query.filter_by(is_active=True, category='ОГЭ').count() if category_filter != 'ОГЭ' else 0
    levelup_students = Student.query.filter_by(is_active=True, category='ЛЕВЕЛАП').count() if category_filter != 'ЛЕВЕЛАП' else 0

    return render_template('dashboard.html',
                         students=students,
                         pagination=pagination,
                         search_query=search_query,
                         category_filter=category_filter,
                         total_students=total_students,
                         total_lessons=total_lessons,
                         completed_lessons=completed_lessons,
                         planned_lessons=planned_lessons,
                         ege_students=ege_students,
                         oge_students=oge_students,
                         levelup_students=levelup_students)

@app.route('/debug-db')
def debug_db():
    """Временный маршрут для диагностики БД"""
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        
        # Проверяем подключение
        db.session.execute(text('SELECT 1'))
        
        # Получаем список таблиц
        tables = inspector.get_table_names()
        
        # Проверяем данные
        students_count = db.session.execute(text('SELECT COUNT(*) FROM "Students"')).scalar()
        students_active = db.session.execute(text('SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE')).scalar()
        lessons_count = db.session.execute(text('SELECT COUNT(*) FROM "Lessons"')).scalar()
        
        # Пробуем через SQLAlchemy
        try:
            sa_students = Student.query.count()
            sa_students_active = Student.query.filter_by(is_active=True).count()
            sa_lessons = Lesson.query.count()
        except Exception as e:
            sa_students = f"Error: {e}"
            sa_students_active = f"Error: {e}"
            sa_lessons = f"Error: {e}"
        
        # Проверяем DATABASE_URL
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', 'Not set')
        db_url_masked = db_url.split('@')[1] if '@' in db_url else db_url
        
        return f"""
        <h1>Database Debug Info</h1>
        <h2>Connection</h2>
        <p>DATABASE_URL: {db_url_masked}</p>
        <p>Tables found: {', '.join(tables)}</p>
        
        <h2>Direct SQL Queries</h2>
        <p>Students (total): {students_count}</p>
        <p>Students (active): {students_active}</p>
        <p>Lessons: {lessons_count}</p>
        
        <h2>SQLAlchemy Queries</h2>
        <p>Student.query.count(): {sa_students}</p>
        <p>Student.query.filter_by(is_active=True).count(): {sa_students_active}</p>
        <p>Lesson.query.count(): {sa_lessons}</p>
        
        <h2>Sample Students (SQL)</h2>
        <pre>{db.session.execute(text('SELECT student_id, name, platform_id, category, is_active FROM "Students" LIMIT 5')).fetchall()}</pre>
        
        <h2>Sample Students (SQLAlchemy)</h2>
        <pre>{[s.name for s in Student.query.limit(5).all()]}</pre>
        """
    except Exception as e:
        import traceback
        return f"<h1>Error</h1><pre>{traceback.format_exc()}</pre>"

@app.route('/students')
def students_list():
    active_students = Student.query.filter_by(is_active=True).order_by(Student.name).all()
    archived_students = Student.query.filter_by(is_active=False).order_by(Student.name).all()
    return render_template('students_list.html',
                         active_students=active_students,
                         archived_students=archived_students)

@app.route('/student/new', methods=['GET', 'POST'])
def student_new():
    form = StudentForm()

    if form.validate_on_submit():
        try:

            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)

            student = Student(
                name=form.name.data,
                platform_id=platform_id,
                target_score=form.target_score.data,
                deadline=form.deadline.data,
                diagnostic_level=form.diagnostic_level.data,
                preferences=form.preferences.data,
                strengths=form.strengths.data,
                weaknesses=form.weaknesses.data,
                overall_rating=form.overall_rating.data,
                description=form.description.data,
                notes=form.notes.data,
                category=form.category.data if form.category.data else None
            )
            db.session.add(student)
            db.session.commit()
            
            # Логируем создание ученика
            audit_logger.log(
                action='create_student',
                entity='Student',
                entity_id=student.student_id,
                status='success',
                metadata={
                    'name': student.name,
                    'platform_id': student.platform_id,
                    'category': student.category
                }
            )
            
            flash(f'Ученик {student.name} успешно добавлен!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при добавлении ученика: {e}')
            
            # Логируем ошибку
            audit_logger.log_error(
                action='create_student',
                entity='Student',
                error=str(e),
                metadata={'form_data': {k: str(v) for k, v in form.data.items() if k != 'csrf_token'}}
            )
            
            flash(f'Ошибка при добавлении ученика: {str(e)}', 'error')

    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)

@app.route('/student/<int:student_id>')
def student_profile(student_id):
    student = Student.query.get_or_404(student_id)
    lessons = Lesson.query.filter_by(student_id=student_id).order_by(Lesson.lesson_date.desc()).all()
    return render_template('student_profile.html', student=student, lessons=lessons)

@app.route('/student/<int:student_id>/edit', methods=['GET', 'POST'])
def student_edit(student_id):
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)
    form._student_id = student_id

    if form.validate_on_submit():
        try:

            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student and existing_student.student_id != student_id:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return render_template('student_form.html', form=form, title='Редактировать ученика',
                                         is_new=False, student=student)

            student.name = form.name.data
            student.platform_id = platform_id
            student.target_score = form.target_score.data
            student.deadline = form.deadline.data
            student.diagnostic_level = form.diagnostic_level.data
            student.preferences = form.preferences.data
            student.strengths = form.strengths.data
            student.weaknesses = form.weaknesses.data
            student.overall_rating = form.overall_rating.data
            student.description = form.description.data
            student.notes = form.notes.data
            student.category = form.category.data if form.category.data else None
            db.session.commit()
            
            # Логируем обновление ученика
            audit_logger.log(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                status='success',
                metadata={
                    'name': student.name,
                    'platform_id': student.platform_id,
                    'category': student.category
                }
            )
            
            flash(f'Данные ученика {student.name} обновлены!', 'success')
            return redirect(url_for('student_profile', student_id=student.student_id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при обновлении ученика {student_id}: {e}')
            
            # Логируем ошибку
            audit_logger.log_error(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                error=str(e)
            )
            
            flash(f'Ошибка при обновлении данных: {str(e)}', 'error')

    return render_template('student_form.html', form=form, title='Редактировать ученика',
                         is_new=False, student=student)

@app.route('/student/<int:student_id>/delete', methods=['POST'])
def student_delete(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        name = student.name
        platform_id = student.platform_id
        category = student.category
        
        db.session.delete(student)
        db.session.commit()
        
        # Логируем удаление ученика
        audit_logger.log(
            action='delete_student',
            entity='Student',
            entity_id=student_id,
            status='success',
            metadata={
                'name': name,
                'platform_id': platform_id,
                'category': category
            }
        )
        
        flash(f'Ученик {name} удален из системы.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении ученика {student_id}: {e}')
        
        # Логируем ошибку
        audit_logger.log_error(
            action='delete_student',
            entity='Student',
            entity_id=student_id,
            error=str(e)
        )
        
        flash(f'Ошибка при удалении ученика: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/student/<int:student_id>/archive', methods=['POST'])
def student_archive(student_id):
    student = Student.query.get_or_404(student_id)
    student.is_active = not student.is_active
    db.session.commit()

    if student.is_active:
        flash(f'Ученик {student.name} восстановлен из архива.', 'success')
    else:
        flash(f'Ученик {student.name} перемещен в архив.', 'success')

    return redirect(url_for('dashboard'))

@app.route('/student/<int:student_id>/lesson/new', methods=['GET', 'POST'])
def lesson_new(student_id):
    student = Student.query.get_or_404(student_id)
    form = LessonForm()

    if form.validate_on_submit():
        lesson = Lesson(
            student_id=student_id,
            lesson_type=form.lesson_type.data,
            lesson_date=form.lesson_date.data,
            duration=form.duration.data,
            status=form.status.data,
            topic=form.topic.data,
            notes=form.notes.data,
            homework=form.homework.data,
            homework_status=form.homework_status.data
        )
        db.session.add(lesson)
        db.session.commit()
        
        # Логируем создание урока
        audit_logger.log(
            action='create_lesson',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': student_id,
                'student_name': student.name,
                'lesson_type': lesson.lesson_type,
                'lesson_date': str(lesson.lesson_date),
                'status': lesson.status
            }
        )
        
        flash(f'Урок добавлен для ученика {student.name}!', 'success')
        return redirect(url_for('student_profile', student_id=student_id))

    return render_template('lesson_form.html', form=form, student=student, title='Добавить урок', is_new=True)

@app.route('/lesson/<int:lesson_id>/edit', methods=['GET', 'POST'])
def lesson_edit(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student
    form = LessonForm(obj=lesson)

    if form.validate_on_submit():
        lesson.lesson_type = form.lesson_type.data
        lesson.lesson_date = form.lesson_date.data
        lesson.duration = form.duration.data
        lesson.status = form.status.data
        lesson.topic = form.topic.data
        lesson.notes = form.notes.data
        lesson.homework = form.homework.data
        lesson.homework_status = form.homework_status.data
        db.session.commit()
        
        # Логируем обновление урока
        audit_logger.log(
            action='update_lesson',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'lesson_type': lesson.lesson_type,
                'status': lesson.status
            }
        )
        
        flash(f'Урок обновлен!', 'success')
        return redirect(url_for('student_profile', student_id=student.student_id))

    homework_tasks = get_sorted_assignments(lesson, 'homework')
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')

    return render_template('lesson_form.html', form=form, student=student, title='Редактировать урок',
                         is_new=False, lesson=lesson, homework_tasks=homework_tasks, classwork_tasks=classwork_tasks)

@app.route('/lesson/<int:lesson_id>/view')
def lesson_view(lesson_id):

    return redirect(url_for('lesson_edit', lesson_id=lesson_id))

@app.route('/lesson/<int:lesson_id>/delete', methods=['POST'])
def lesson_delete(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    student_id = lesson.student_id
    student_name = lesson.student.name
    
    db.session.delete(lesson)
    db.session.commit()
    
    # Логируем удаление урока
    audit_logger.log(
        action='delete_lesson',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': student_id,
            'student_name': student_name,
            'lesson_type': lesson.lesson_type,
            'lesson_date': str(lesson.lesson_date)
        }
    )
    
    flash('Урок удален.', 'success')
    return redirect(url_for('schedule'))

@app.route('/student/<int:student_id>/lesson-mode')
def lesson_mode(student_id):
    student = Student.query.get_or_404(student_id)
    lessons = Lesson.query.filter_by(student_id=student_id).order_by(Lesson.lesson_date.desc()).all()

    current_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'in_progress'
    ).first()

    upcoming_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'planned',
        Lesson.lesson_date >= moscow_now()
    ).order_by(Lesson.lesson_date).first()

    return render_template('lesson_mode.html',
                         student=student,
                         lessons=lessons,
                         current_lesson=current_lesson,
                         upcoming_lesson=upcoming_lesson)

@app.route('/student/<int:student_id>/start-lesson', methods=['POST'])
def student_start_lesson(student_id):
    student = Student.query.get_or_404(student_id)

    active_lesson = Lesson.query.filter_by(student_id=student_id, status='in_progress').first()
    if active_lesson:
        flash('Урок уже идет!', 'info')
        return redirect(url_for('student_profile', student_id=student_id))

    upcoming_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'planned',
        Lesson.lesson_date >= moscow_now()
    ).order_by(Lesson.lesson_date).first()

    if upcoming_lesson:
        upcoming_lesson.status = 'in_progress'
        db.session.commit()
        flash(f'Урок начат!', 'success')
    else:
        new_lesson = Lesson(
            student_id=student_id,
            lesson_type='regular',
            lesson_date=moscow_now(),
            duration=60,
            status='in_progress',
            topic='Занятие'
        )
        db.session.add(new_lesson)
        db.session.commit()
        flash(f'Новый урок создан и начат!', 'success')

    return redirect(url_for('student_profile', student_id=student_id))

@app.route('/lesson/<int:lesson_id>/start', methods=['POST'])
def lesson_start(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson.status = 'in_progress'
    db.session.commit()
    flash(f'Урок начат! Используй зеленую панель сверху для управления уроком.', 'success')
    return redirect(url_for('student_profile', student_id=lesson.student_id))

@app.route('/lesson/<int:lesson_id>/complete', methods=['POST'])
def lesson_complete(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)

    lesson.topic = request.form.get('topic', lesson.topic)
    lesson.notes = request.form.get('notes', lesson.notes)
    lesson.homework = request.form.get('homework', lesson.homework)
    lesson.status = 'completed'

    db.session.commit()
    flash(f'Урок завершен и данные сохранены!', 'success')
    return redirect(url_for('student_profile', student_id=lesson.student_id))

def get_sorted_assignments(lesson, assignment_type):
    assignments = lesson.homework_assignments if assignment_type == 'homework' else lesson.classwork_assignments
    return sorted(assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))

@app.route('/lesson/<int:lesson_id>/homework-tasks')
def lesson_homework_view(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student
    homework_tasks = get_sorted_assignments(lesson, 'homework')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=homework_tasks,
                           assignment_type='homework')

@app.route('/lesson/<int:lesson_id>/classwork-tasks')
def lesson_classwork_view(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=classwork_tasks,
                           assignment_type='classwork')

@app.route('/lesson/<int:lesson_id>/homework-tasks/save', methods=['POST'])
def lesson_homework_save(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    homework_tasks = [ht for ht in lesson.homework_assignments]

    for hw_task in homework_tasks:
        answer_key = f'answer_{hw_task.lesson_task_id}'
        if answer_key in request.form:
            hw_task.student_answer = request.form.get(answer_key)

    percent_value = request.form.get('homework_result_percent', '').strip()
    if percent_value:
        try:
            percent_int = max(0, min(100, int(percent_value)))
            lesson.homework_result_percent = percent_int
        except ValueError:
            flash('Процент выполнения должен быть числом от 0 до 100', 'warning')
    else:
        lesson.homework_result_percent = None

    result_notes = request.form.get('homework_result_notes', '').strip()
    lesson.homework_result_notes = result_notes or None

    if lesson.homework_result_percent is not None or lesson.homework_result_notes:
        lesson.homework_status = 'completed'
    elif homework_tasks:
        lesson.homework_status = 'not_done'
    else:
        if lesson.homework_status != 'not_assigned':
            lesson.homework_status = 'pending'

    db.session.commit()
    
    # Логируем сохранение домашнего задания
    audit_logger.log(
        action='save_homework',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'homework_status': lesson.homework_status,
            'homework_result_percent': lesson.homework_result_percent,
            'tasks_count': len(homework_tasks)
        }
    )
    
    flash('Данные по ДЗ сохранены!', 'success')
    return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

def normalize_answer_value(value):
    if value is None:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    text_single_space = re.sub(r'\s+', ' ', text)
    if text_single_space.startswith('$') and text_single_space.endswith('$'):
        return text_single_space
    numeric_candidate = text_single_space.replace(',', '.')
    try:
        decimal_value = Decimal(numeric_candidate)
        normalized = format(decimal_value.normalize())
        return normalized
    except InvalidOperation:
        pass
    return text_single_space.lower()

@app.route('/lesson/<int:lesson_id>/homework-auto-check', methods=['POST'])
def lesson_homework_auto_check(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    homework_tasks = get_sorted_assignments(lesson, 'homework')

    if not homework_tasks:
        flash('У этого урока нет заданий ДЗ для проверки.', 'warning')
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

    answers_raw = request.form.get('auto_answers', '').strip()
    if not answers_raw:
        flash('Вставь массив ответов в формате [1, -1, "Москва"].', 'warning')
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

    try:
        parsed_answers = ast.literal_eval(answers_raw)
        if not isinstance(parsed_answers, (list, tuple)):
            raise ValueError
        answers_list = list(parsed_answers)
    except Exception:
        flash('Не удалось разобрать ответы. Используй формат [1, -1, "Москва"].', 'danger')
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

    total_tasks = len(homework_tasks)
    correct_count = 0
    incorrect_count = 0

    if len(answers_list) != total_tasks:
        flash(f'Количество ответов ({len(answers_list)}) не совпадает с числом заданий ({total_tasks}). Отсутствующие ответы будут считаться неверными.', 'warning')

    def answer_at(index):
        if index < len(answers_list):
            return answers_list[index]
        return None

    for idx, hw_task in enumerate(homework_tasks):
        student_value = answer_at(idx)
        student_text = '' if student_value is None else str(student_value).strip()
        hw_task.student_submission = student_text if student_text else None

        is_skip = student_text == '' or student_text == '-1' or student_text.lower() == 'null'
        expected_text = hw_task.student_answer or ''

        if not expected_text:
            hw_task.submission_correct = False
            incorrect_count += 1
            continue

        if is_skip:
            hw_task.submission_correct = False
            incorrect_count += 1
            continue

        normalized_student = normalize_answer_value(student_text)
        normalized_expected = normalize_answer_value(expected_text)

        is_correct = normalized_student == normalized_expected and normalized_expected != ''
        hw_task.submission_correct = is_correct

        if is_correct:
            correct_count += 1
        else:
            incorrect_count += 1

    percent = round((correct_count / total_tasks) * 100, 2) if total_tasks else 0
    lesson.homework_result_percent = percent
    summary = f"Автопроверка {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
    if lesson.homework_result_notes:
        lesson.homework_result_notes = lesson.homework_result_notes + "\n" + summary
    else:
        lesson.homework_result_notes = summary

    if total_tasks == 0:
        lesson.homework_status = 'not_assigned'
    else:
        lesson.homework_status = 'completed' if correct_count == total_tasks else 'not_done'

    db.session.commit()
    
    # Логируем автопроверку ДЗ
    audit_logger.log(
        action='auto_check_homework',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'total_tasks': total_tasks,
            'correct_count': correct_count,
            'incorrect_count': incorrect_count,
            'percent': percent
        }
    )
    
    flash(f'Автопроверка завершена. Правильных: {correct_count}, неправильных: {incorrect_count}.', 'success')
    return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

@app.route('/lesson/<int:lesson_id>/homework-tasks/<int:lesson_task_id>/delete', methods=['POST'])
def lesson_homework_delete_task(lesson_id, lesson_task_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_task = LessonTask.query.get_or_404(lesson_task_id)
    assignment_type = request.args.get('assignment_type', 'homework')

    if lesson_task.lesson_id != lesson_id:
        flash('Ошибка: задание не принадлежит этому уроку', 'danger')
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

    task_id = lesson_task.task_id
    
    db.session.delete(lesson_task)
    db.session.commit()
    
    # Логируем удаление задачи из ДЗ
    audit_logger.log(
        action='delete_homework_task',
        entity='LessonTask',
        entity_id=lesson_task_id,
        status='success',
        metadata={
            'lesson_id': lesson_id,
            'task_id': task_id,
            'assignment_type': assignment_type,
            'student_id': lesson.student_id,
            'student_name': lesson.student.name
        }
    )
    
    flash('Задание удалено', 'success')

    if assignment_type == 'classwork':
        return redirect(url_for('lesson_classwork_view', lesson_id=lesson_id))
    return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

@app.route('/lesson/<int:lesson_id>/homework-not-assigned', methods=['POST'])
def lesson_homework_not_assigned(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    for hw_task in lesson.homework_assignments:
        db.session.delete(hw_task)
    lesson.homework_status = 'not_assigned'
    lesson.homework = None
    lesson.homework_result_percent = None
    lesson.homework_result_notes = None
    db.session.commit()
    flash('Домашнее задание отмечено как «не задано».', 'info')
    return redirect(url_for('student_profile', student_id=lesson.student_id))

@app.route('/lesson/<int:lesson_id>/homework-export-md')
def lesson_homework_export_md(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student

    homework_tasks = sorted(lesson.homework_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))

    ordinal_names = {
        1: "Первое", 2: "Второе", 3: "Третье", 4: "Четвертое", 5: "Пятое",
        6: "Шестое", 7: "Седьмое", 8: "Восьмое", 9: "Девятое", 10: "Десятое",
        11: "Одиннадцатое", 12: "Двенадцатое", 13: "Тринадцатое", 14: "Четырнадцатое", 15: "Пятнадцатое",
        16: "Шестнадцатое", 17: "Семнадцатое", 18: "Восемнадцатое", 19: "Девятнадцатое", 20: "Двадцатое",
        21: "Двадцать первое", 22: "Двадцать второе", 23: "Двадцать третье", 24: "Двадцать четвертое",
        25: "Двадцать пятое", 26: "Двадцать шестое", 27: "Двадцать седьмое"
    }

    def html_to_text(html_content):
        if not html_content:
            return ""
        global BeautifulSoup
        if BeautifulSoup is None:
            try:
                BeautifulSoup = import_module('bs4').BeautifulSoup
            except ImportError as exc:
                raise RuntimeError("BeautifulSoup is required for markdown export. Install 'beautifulsoup4'.") from exc

        soup = BeautifulSoup(html_content, 'html.parser')

        for tag in soup(['script', 'style']):
            tag.decompose()

        def collapse_spaces(value: str) -> str:
            return re.sub(r'\s+', ' ', value).strip()

        def sup_sub_text(node):
            text_value = collapse_spaces(node.get_text(separator=' ', strip=True))
            if not text_value:
                return ''
            return text_value

        for sup in list(soup.find_all('sup')):
            sup_content = sup_sub_text(sup)
            replacement = f"$^{{{sup_content}}}$" if sup_content else ''
            sup.replace_with(soup.new_string(replacement))

        for sub in list(soup.find_all('sub')):
            sub_content = sup_sub_text(sub)
            replacement = f"$_{{{sub_content}}}$" if sub_content else ''
            sub.replace_with(soup.new_string(replacement))

        def extract_formula(node) -> str:
            aria = node.get('aria-label')
            if aria:
                return aria.strip()
            annotation = node.select_one('annotation[encoding="application/x-tex"]')
            if annotation:
                return annotation.get_text(strip=True)
            text = node.get_text(strip=True)
            return text

        for katex_span in list(soup.select('.katex, .katex-display, .katex-inline')):
            formula = extract_formula(katex_span)
            if formula:
                is_display = 'katex-display' in katex_span.get('class', [])
                if is_display:
                    katex_span.replace_with(soup.new_string(f"\n\n$${formula}$$\n\n"))
                else:
                    katex_span.replace_with(soup.new_string(f" ${formula}$ "))
            else:
                katex_span.decompose()

        def table_to_markdown(table):
            rows = []
            for tr in table.find_all('tr'):
                cells = []
                for cell in tr.find_all(['th', 'td']):
                    cell_text = cell.get_text(separator=' ', strip=True)
                    cell_text = collapse_spaces(cell_text)
                    cells.append(cell_text)
                if cells:
                    rows.append(cells)
            if not rows:
                return ''

            col_count = max(len(r) for r in rows)
            for row in rows:
                if len(row) < col_count:
                    row.extend([''] * (col_count - len(row)))

            widths = [0] * col_count
            for row in rows:
                for idx, cell in enumerate(row):
                    widths[idx] = max(widths[idx], len(cell))

            def fmt_row(row):
                padded = [
                    row[i].ljust(widths[i]) if widths[i] else row[i]
                    for i in range(col_count)
                ]
                return '| ' + ' | '.join(padded) + ' |'

            header = fmt_row(rows[0])
            separator = '| ' + ' | '.join('-' * max(3, widths[i] or 3) for i in range(col_count)) + ' |'
            body = [fmt_row(row) for row in rows[1:]] if len(rows) > 1 else []
            return '\n'.join([header, separator, *body])

        for table in soup.find_all('table'):
            md = table_to_markdown(table)
            table.replace_with(soup.new_string(f'\n\n{md}\n\n'))

        for img in soup.find_all('img'):
            src = img.get('src', '')
            alt = img.get('alt', '')
            title = img.get('title', '')

            if not src:
                img.decompose()
                continue

            if title:
                markdown_img = f'![{alt}]({src} "{title}")'
            else:
                markdown_img = f'![{alt}]({src})'

            img.replace_with(soup.new_string(f'\n\n{markdown_img}\n\n'))

        for br in soup.find_all('br'):
            br.replace_with(' ')

        def process_element(elem):
            if elem.name in ['p', 'div']:
                if not elem.find_parent(['td', 'th', 'table']):
                    if elem.get_text(strip=True):
                        if elem.previous_sibling and not isinstance(elem.previous_sibling, str):
                            elem.insert_before('\n\n')
                        if elem.next_sibling and not isinstance(elem.next_sibling, str):
                            elem.insert_after('\n\n')

        for p in soup.find_all('p'):
            process_element(p)
        for div in soup.find_all('div'):
            process_element(div)

        text = soup.get_text(separator=' ', strip=False)
        text = unescape(text)
        text = re.sub(r'\r\n?', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r' \$\$', '\n\n$$', text)
        text = re.sub(r'\$\$ ', '$$\n\n', text)
        text = re.sub(r' \$', ' $', text)
        text = re.sub(r'\$ ', '$ ', text)
        text = re.sub(r' \n', '\n', text)
        text = re.sub(r'\n ', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'\$\s+([^$]+)\s+\$', r'$\1$', text)
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = []
        prev_blank = False
        for line in lines:
            stripped = line.strip()
            if stripped:
                cleaned.append(stripped)
                prev_blank = False
            else:
                if not prev_blank:
                    cleaned.append('')
                prev_blank = True
        result = '\n'.join(cleaned).strip()
        return result

    markdown_content = f"# Домашнее задание\n\n"
    markdown_content += f"**Ученик:** {student.name}\n"
    if lesson.lesson_date:
        markdown_content += f"**Дата урока:** {lesson.lesson_date.strftime('%d.%m.%Y')}\n"
    if lesson.topic:
        markdown_content += f"**Тема:** {lesson.topic}\n"
    markdown_content += f"\n---\n\n"

    for idx, hw_task in enumerate(homework_tasks):
        order_number = idx + 1
        task_name = ordinal_names.get(order_number, f"{order_number}-е")

        markdown_content += f"## {task_name} задание\n\n"

        task_text = html_to_text(hw_task.task.content_html)
        markdown_content += f"{task_text}\n\n"

        if hw_task.task.attached_files:
            files = json.loads(hw_task.task.attached_files)
            if files:
                markdown_content += "**Прикрепленные файлы:**\n"
                for file in files:
                    markdown_content += f"- [{file['name']}]({file['url']})\n"
                markdown_content += "\n"
        if idx < len(homework_tasks) - 1:
            markdown_content += "---\n\n"

    return render_template('markdown_export.html', markdown_content=markdown_content, lesson=lesson, student=student)

@app.route('/update-plans')
def update_plans():

    try:
        plans_file_path = os.path.join(base_dir, 'UPDATE_PLANS.md')
        with open(plans_file_path, 'r', encoding='utf-8') as f:
            plans_content = f.read()
        return render_template('update_plans.html', plans_content=plans_content)
    except Exception as e:
        logger.error(f"Ошибка при чтении файла планов обновления: {e}")
        flash('Не удалось загрузить планы обновления', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/audit-log', methods=['POST'])
def api_audit_log():

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        audit_logger.log(
            action=data.get('action', 'unknown'),
            entity=data.get('entity'),
            entity_id=data.get('entity_id'),
            status=data.get('status', 'success'),
            metadata=data.get('metadata', {}),
            duration_ms=data.get('duration_ms')
        )

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f'Error processing audit log: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/student/create', methods=['POST'])
def api_student_create():

    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        student = Student(
            name=data.get('name'),
            platform_id=platform_id,
            target_score=int(data.get('target_score')) if data.get('target_score') else None,
            deadline=data.get('deadline'),
            diagnostic_level=data.get('diagnostic_level'),
            preferences=data.get('preferences'),
            strengths=data.get('strengths'),
            weaknesses=data.get('weaknesses'),
            overall_rating=data.get('overall_rating'),
            description=data.get('description'),
            notes=data.get('notes'),
            category=data.get('category') if data.get('category') else None
        )
        db.session.add(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student.name} успешно добавлен!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании студента: {str(e)}'}), 500

@app.route('/api/student/<int:student_id>/update', methods=['POST', 'PUT'])
def api_student_update(student_id):

    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student and existing_student.student_id != student_id:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        student.name = data.get('name')
        student.platform_id = platform_id
        student.target_score = int(data.get('target_score')) if data.get('target_score') else None
        student.deadline = data.get('deadline')
        student.diagnostic_level = data.get('diagnostic_level')
        student.preferences = data.get('preferences')
        student.strengths = data.get('strengths')
        student.weaknesses = data.get('weaknesses')
        student.overall_rating = data.get('overall_rating')
        student.description = data.get('description')
        student.notes = data.get('notes')
        student.category = data.get('category') if data.get('category') else None

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Данные ученика {student.name} обновлены!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при обновлении студента: {str(e)}'}), 500

@app.route('/api/student/<int:student_id>/delete', methods=['POST', 'DELETE'])
def api_student_delete(student_id):

    try:
        student = Student.query.get_or_404(student_id)
        student_name = student.name
        db.session.delete(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student_name} удален'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при удалении студента: {str(e)}'}), 500

@app.route('/api/lesson/create', methods=['POST'])
def api_lesson_create():

    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('student_id'):
            return jsonify({'success': False, 'error': 'ID студента обязателен'}), 400
        if not data.get('lesson_date'):
            return jsonify({'success': False, 'error': 'Дата урока обязательна'}), 400

        try:
            if isinstance(data.get('lesson_date'), str):
                lesson_date = datetime.fromisoformat(data['lesson_date'].replace('Z', '+00:00'))
            else:
                lesson_date = data.get('lesson_date')
        except Exception as e:
            return jsonify({'success': False, 'error': f'Неверный формат даты: {str(e)}'}), 400

        lesson = Lesson(
            student_id=int(data.get('student_id')),
            lesson_type=data.get('lesson_type', 'regular'),
            lesson_date=lesson_date,
            duration=int(data.get('duration', 60)),
            status=data.get('status', 'planned'),
            topic=data.get('topic'),
            notes=data.get('notes'),
            homework=data.get('homework'),
            homework_status=data.get('homework_status', 'pending')
        )
        db.session.add(lesson)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Урок успешно создан!',
            'lesson': {
                'id': lesson.lesson_id,
                'student_id': lesson.student_id,
                'lesson_date': lesson.lesson_date.isoformat() if lesson.lesson_date else None,
                'duration': lesson.duration,
                'status': lesson.status
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании урока через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании урока: {str(e)}'}), 500

@app.route('/schedule')
def schedule():
    week_offset = request.args.get('week', 0, type=int)
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    timezone = request.args.get('timezone', 'moscow')

    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ

    today = moscow_now().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]

    slot_minutes = 60
    day_start_hour = 0
    day_end_hour = 23
    total_slots = int((24 * 60) / slot_minutes)
    time_labels = [f"{hour:02d}:00" for hour in range(day_start_hour, day_end_hour + 1)]

    week_start_datetime = datetime.combine(week_start, time.min).replace(tzinfo=MOSCOW_TZ)
    week_end_datetime = datetime.combine(week_end, time.max).replace(tzinfo=MOSCOW_TZ)

    query = Lesson.query.filter(Lesson.lesson_date >= week_start_datetime, Lesson.lesson_date <= week_end_datetime)

    if status_filter:
        query = query.filter_by(status=status_filter)

    if category_filter:
        query = query.join(Student).filter(Student.category == category_filter)

    lessons = query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date).all()

    real_events = []
    for lesson in lessons:
        lesson_date = lesson.lesson_date
        if lesson_date.tzinfo is None:
            lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)

        lesson_date_display = lesson_date.astimezone(display_tz)
        lesson_date_local = lesson_date_display.date()
        day_index = (lesson_date_local - week_start).days
        if 0 <= day_index < 7:
            start_time = lesson_date_display.time()
            end_time = (lesson_date_display + timedelta(minutes=lesson.duration)).time()
            status_text = {'planned': 'Запланирован', 'in_progress': 'Идет сейчас', 'completed': 'Проведен', 'cancelled': 'Отменен'}.get(lesson.status, lesson.status)
            with app.app_context():
                profile_url = url_for('student_profile', student_id=lesson.student.student_id)
            real_events.append({
                'lesson_id': lesson.lesson_id,
                'student': lesson.student.name,
                'student_id': lesson.student.student_id,
                'subject': 'Информатика',
                'grade': lesson.student.category or 'Не указано',
                'status': status_text,
                'status_code': lesson.status,
                'day_index': day_index,
                'start': start_time,
                'end': end_time,
                'start_time': start_time.strftime('%H:%M'),
                'profile_url': profile_url,
                'topic': lesson.topic,
                'lesson_type': lesson.lesson_type
            })

    slot_height_px = 32
    visual_slot_height_px = slot_height_px * 2
    day_events = {i: [] for i in range(7)}
    day_start_minutes = day_start_hour * 60

    for event in real_events:
        start_minutes = (event['start'].hour * 60 + event['start'].minute) - day_start_minutes
        start_minutes = max(start_minutes, 0)
        duration_minutes = ((event['end'].hour * 60 + event['end'].minute) - (event['start'].hour * 60 + event['start'].minute))
        duration_minutes = max(duration_minutes, slot_minutes)
        offset_slots = start_minutes / slot_minutes
        duration_slots = duration_minutes / slot_minutes
        event['offset_slots'] = offset_slots
        event['duration_slots'] = duration_slots
        event['start_total'] = event['start'].hour * 60 + event['start'].minute
        event['end_total'] = event['end'].hour * 60 + event['end'].minute
        event['top_px'] = offset_slots * visual_slot_height_px
        event['height_px'] = max(duration_slots * visual_slot_height_px - 4, visual_slot_height_px * 0.75)
        day_events[event['day_index']].append(event)

    for day_index, events in day_events.items():
        events.sort(key=lambda e: (e['start_total'], e['end_total']))
        active = []
        max_columns = 1
        for event in events:
            current_start = event['start_total']
            active = [a for a in active if a['end_total'] > current_start]
            used_columns = {a['column_index'] for a in active}
            column_index = 0
            while column_index in used_columns:
                column_index += 1
            event['column_index'] = column_index
            active.append(event)
            max_columns = max(max_columns, len(active))
        for event in events:
            event['columns_total'] = max_columns
            column_width = 100 / max_columns
            event['left_percent'] = column_width * event['column_index']
            event['width_percent'] = max(column_width - 1.5, 5)

    day_events_json = {i: [] for i in range(7)}
    for day_index, events in day_events.items():
        for event in events:
            json_event = {
                'lesson_id': event['lesson_id'],
                'student': event['student'],
                'student_id': event['student_id'],
                'subject': event['subject'],
                'grade': event['grade'],
                'status': event['status'],
                'status_code': event['status_code'],
                'start_time': event['start_time'],
                'profile_url': event['profile_url'],
                'top_px': event['top_px'],
                'height_px': event['height_px'],
                'left_percent': event['left_percent'],
                'width_percent': event['width_percent']
            }
            day_events_json[day_index].append(json_event)

    week_label = f"{week_days[0].strftime('%d.%m.%Y')} — {week_days[-1].strftime('%d.%m.%Y')}"

    students = Student.query.filter_by(is_active=True).order_by(Student.name).all()
    statuses = ['planned', 'in_progress', 'completed', 'cancelled']
    categories = ['ЕГЭ', 'ОГЭ', 'ЛЕВЕЛАП']

    return render_template(
        'schedule.html',
        week_days=week_days,
        week_label=week_label,
        time_labels=time_labels,
        day_events=day_events_json,
        slot_minutes=slot_minutes,
        total_slots=total_slots,
        start_hour=day_start_hour,
        end_hour=day_end_hour,
        week_offset=week_offset,
        status_filter=status_filter,
        category_filter=category_filter,
        timezone=timezone,
        students=students,
        statuses=statuses,
        categories=categories
    )

@app.route('/schedule/create-lesson', methods=['POST'])
def schedule_create_lesson():
    try:
        student_id = request.form.get('student_id', type=int)
        lesson_date_str = request.form.get('lesson_date')
        lesson_time_str = request.form.get('lesson_time')
        duration = request.form.get('duration', 60, type=int)
        lesson_type = request.form.get('lesson_type', 'regular')
        timezone = request.form.get('timezone', 'moscow')
        lesson_mode = request.form.get('lesson_mode', 'single')
        repeat_count = request.form.get('repeat_count', type=int)

        if not student_id or not lesson_date_str or not lesson_time_str:
            error_message = 'Заполните все обязательные поля'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({
                    'success': False,
                    'error': error_message
                }), 400
            flash(error_message, 'error')
            return redirect(url_for('schedule'))

        input_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
        lesson_datetime_str = f"{lesson_date_str} {lesson_time_str}"
        lesson_datetime_local = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
        lesson_datetime_local = lesson_datetime_local.replace(tzinfo=input_tz)
        base_lesson_datetime = lesson_datetime_local.astimezone(MOSCOW_TZ)

        student = Student.query.get_or_404(student_id)

        if lesson_mode == 'recurring' and repeat_count and repeat_count > 1:
            lessons_to_create = repeat_count
        else:
            lessons_to_create = 1

        created_lessons = []
        for week_offset in range(lessons_to_create):
            lesson_datetime = base_lesson_datetime + timedelta(weeks=week_offset)
            new_lesson = Lesson(
                student_id=student_id,
                lesson_date=lesson_datetime,
                duration=duration,
                lesson_type=lesson_type,
                status='planned'
            )
            db.session.add(new_lesson)
            created_lessons.append(new_lesson)

        db.session.commit()
        
        # Логируем создание урока(ов) из расписания
        for created_lesson in created_lessons:
            audit_logger.log(
                action='create_lesson_from_schedule',
                entity='Lesson',
                entity_id=created_lesson.lesson_id,
                status='success',
                metadata={
                    'student_id': student_id,
                    'student_name': student.name,
                    'lesson_mode': lesson_mode,
                    'repeat_count': lessons_to_create,
                    'lesson_date': str(created_lesson.lesson_date),
                    'duration': duration,
                    'lesson_type': lesson_type
                }
            )

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if lessons_to_create > 1:
            success_message = f'Создано {lessons_to_create} уроков с {student.name} (на {lessons_to_create} недель)'
            logger.info(f'Created {lessons_to_create} lessons for student {student_id} starting from {base_lesson_datetime}')
        else:
            success_message = f'Урок с {student.name} успешно создан'
            logger.info(f'Created lesson {created_lessons[0].lesson_id} for student {student_id} at {base_lesson_datetime}')

        if is_ajax:
            return jsonify({
                'success': True,
                'message': success_message
            }), 200

        flash(success_message, 'success')
    except Exception as e:
        db.session.rollback()
        error_details = str(e)
        logger.error(f'Error creating lesson: {error_details}', exc_info=True)

        if 'time' in error_details.lower() or 'date' in error_details.lower() or 'strptime' in error_details.lower():
            error_message = f'Ошибка в формате даты или времени: {error_details}'
        elif 'not found' in error_details.lower() or '404' in error_details.lower():
            error_message = 'Ученик не найден'
        else:
            error_message = f'Ошибка при создании урока: {error_details}'

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if is_ajax:
            return jsonify({
                'success': False,
                'error': error_message
            }), 500

        flash(error_message, 'error')

    week_offset = request.form.get('week_offset', 0, type=int)
    status_filter = request.form.get('status_filter', '')
    category_filter = request.form.get('category_filter', '')
    timezone = request.form.get('timezone', 'moscow')

    params = {'week': week_offset, 'timezone': timezone}
    if status_filter:
        params['status'] = status_filter
    if category_filter:
        params['category'] = category_filter

    return redirect(url_for('schedule', **params))

@app.route('/kege-generator', methods=['GET', 'POST'])
@app.route('/kege-generator/<int:lesson_id>', methods=['GET', 'POST'])
def kege_generator(lesson_id=None):
    lesson = None
    student = None
    assignment_type = request.args.get('assignment_type') or request.form.get('assignment_type') or 'homework'
    assignment_type = assignment_type if assignment_type in ['homework', 'classwork'] else 'homework'
    if not lesson_id and assignment_type == 'classwork':
        assignment_type = 'homework'
    if lesson_id:
        lesson = Lesson.query.get_or_404(lesson_id)
        student = lesson.student

    selection_form = TaskSelectionForm()
    reset_form = ResetForm()

    try:
        available_types = db.session.query(Tasks.task_number).distinct().order_by(Tasks.task_number).all()
        choices = [(t[0], f'Задание {t[0]}') for t in available_types]

        if not choices:
            flash('База данных пуста! Запустите парсер для заполнения: python scraper/playwright_parser.py', 'warning')
            choices = [(i, f'Задание {i} (не загружено)') for i in range(1, 28)]

        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    except Exception as e:
        flash(f'Ошибка! База данных ({db_path}) не найдена или пуста. Запустите парсер (scraper) для ее заполнения. Ошибка: {str(e)}', 'danger')
        choices = [(i, f'Задание {i} (не загружено)') for i in range(1, 28)]
        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    if selection_form.submit.data and selection_form.validate_on_submit():
        task_type = selection_form.task_type.data
        limit_count = selection_form.limit_count.data
        use_skipped = selection_form.use_skipped.data
        
        # Логируем запрос на генерацию заданий
        audit_logger.log(
            action='request_task_generation',
            entity='Generator',
            entity_id=lesson_id,
            status='success',
            metadata={
                'task_type': task_type,
                'limit_count': limit_count,
                'use_skipped': use_skipped,
                'assignment_type': assignment_type,
                'student_id': lesson.student_id if lesson_id and lesson else None,
                'student_name': lesson.student.name if lesson_id and lesson else None
            }
        )

        if lesson_id:
            return redirect(url_for('generate_results', task_type=task_type, limit_count=limit_count, use_skipped=use_skipped, lesson_id=lesson_id, assignment_type=assignment_type))
        else:
            return redirect(url_for('generate_results', task_type=task_type, limit_count=limit_count, use_skipped=use_skipped, assignment_type=assignment_type))

    if reset_form.reset_submit.data and reset_form.validate_on_submit():
        task_type_to_reset = reset_form.task_type_reset.data
        reset_type = reset_form.reset_type.data

        task_type_int = None if task_type_to_reset == 'all' else int(task_type_to_reset)

        if reset_type == 'accepted':
            reset_history(task_type=task_type_int)
            audit_logger.log(
                action='reset_history',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('История принятых заданий сброшена.', 'success')
        elif reset_type == 'skipped':
            reset_skipped(task_type=task_type_int)
            audit_logger.log(
                action='reset_skipped',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('История пропущенных заданий сброшена.', 'success')
        elif reset_type == 'blacklist':
            reset_blacklist(task_type=task_type_int)
            audit_logger.log(
                action='reset_blacklist',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('Черный список очищен.', 'success')
        elif reset_type == 'all':
            reset_history(task_type=task_type_int)
            reset_skipped(task_type=task_type_int)
            reset_blacklist(task_type=task_type_int)
            audit_logger.log(
                action='reset_all_history',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('Вся история сброшена.', 'success')

        return redirect(url_for('kege_generator', lesson_id=lesson_id, assignment_type=assignment_type) if lesson_id else url_for('kege_generator', assignment_type=assignment_type))
    return render_template('kege_generator.html',
                           selection_form=selection_form,
                           reset_form=reset_form,
                           lesson=lesson,
                           student=student,
                           lesson_id=lesson_id,
                           assignment_type=assignment_type)

@app.route('/results')
def generate_results():
    try:
        task_type = request.args.get('task_type', type=int)
        limit_count = request.args.get('limit_count', type=int)
        use_skipped = request.args.get('use_skipped', 'false').lower() == 'true'
        lesson_id = request.args.get('lesson_id', type=int)
        assignment_type = request.args.get('assignment_type', default='homework')
    except:
        flash('Неверные параметры запроса.', 'danger')
        if lesson_id:
            return redirect(url_for('kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator', assignment_type=assignment_type))

    lesson = None
    student = None
    student_id = None
    if lesson_id:
        lesson = Lesson.query.get_or_404(lesson_id)
        student = lesson.student
        student_id = student.student_id

    tasks = get_unique_tasks(task_type, limit_count, use_skipped=use_skipped, student_id=student_id)
    
    # Логируем генерацию заданий
    audit_logger.log(
        action='generate_tasks',
        entity='Generator',
        entity_id=lesson_id,
        status='success' if tasks else 'warning',
        metadata={
            'task_type': task_type,
            'limit_count': limit_count,
            'use_skipped': use_skipped,
            'tasks_generated': len(tasks) if tasks else 0,
            'assignment_type': assignment_type,
            'student_id': student_id,
            'student_name': student.name if student else None
        }
    )

    if not tasks:
        if use_skipped:
            flash(f'Задания типа {task_type} закончились! Все доступные задания (включая пропущенные) были использованы.', 'warning')
        else:
            flash(f'Задания типа {task_type} закончились! Попробуйте включить пропущенные задания или сбросьте историю.', 'warning')
        return redirect(url_for('kege_generator'))

    return render_template('results.html',
                           tasks=tasks,
                           task_type=task_type,
                           lesson=lesson,
                           student=student,
                           lesson_id=lesson_id,
                           assignment_type=assignment_type)

@app.route('/action', methods=['POST'])
def task_action():
    try:
        data = request.get_json()
        action = data.get('action')
        task_ids = data.get('task_ids', [])
        lesson_id = data.get('lesson_id')

        if not action or not task_ids:
            return jsonify({'success': False, 'error': 'Неверные параметры'}), 400

        assignment_type = data.get('assignment_type', 'homework')
        assignment_type = assignment_type if assignment_type in ['homework', 'classwork'] else 'homework'

        if action == 'accept':
            if lesson_id:
                lesson = Lesson.query.get(lesson_id)
                if not lesson:
                    return jsonify({'success': False, 'error': 'Урок не найден'}), 404

                for task_id in task_ids:
                    existing = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).first()
                    if not existing:
                        lesson_task = LessonTask(lesson_id=lesson_id, task_id=task_id, assignment_type=assignment_type)
                        db.session.add(lesson_task)
                if assignment_type == 'homework':
                    lesson.homework_status = 'not_done'
                    lesson.homework_result_percent = None
                    lesson.homework_result_notes = None
                try:
                    db.session.commit()
                    
                    # Логируем принятие заданий для урока
                    audit_logger.log(
                        action='accept_tasks',
                        entity='Lesson',
                        entity_id=lesson_id,
                        status='success',
                        metadata={
                            'task_ids': task_ids,
                            'task_count': len(task_ids),
                            'assignment_type': assignment_type,
                            'student_id': lesson.student_id,
                            'student_name': lesson.student.name
                        }
                    )
                except Exception as e:
                    db.session.rollback()
                    audit_logger.log_error(
                        action='accept_tasks',
                        entity='Lesson',
                        entity_id=lesson_id,
                        error=str(e)
                    )
                    return jsonify({'success': False, 'error': f'Ошибка при сохранении: {str(e)}'}), 500
                if assignment_type == 'classwork':
                    message = f'{len(task_ids)} заданий добавлено в классную работу.'
                else:
                    message = f'{len(task_ids)} заданий добавлено в домашнее задание.'
            else:
                try:
                    record_usage(task_ids)
                    
                    # Логируем принятие заданий (без урока)
                    audit_logger.log(
                        action='accept_tasks',
                        entity='Task',
                        entity_id=None,
                        status='success',
                        metadata={
                            'task_ids': task_ids,
                            'task_count': len(task_ids)
                        }
                    )
                except Exception as e:
                    audit_logger.log_error(
                        action='accept_tasks',
                        entity='Task',
                        error=str(e)
                    )
                    return jsonify({'success': False, 'error': f'Ошибка при записи: {str(e)}'}), 500
                message = f'{len(task_ids)} заданий принято.'
        elif action == 'skip':
            if lesson_id:
                lesson = Lesson.query.get(lesson_id)
                audit_logger.log(
                    action='skip_tasks',
                    entity='Lesson',
                    entity_id=lesson_id,
                    status='success',
                    metadata={
                        'task_ids': task_ids,
                        'task_count': len(task_ids),
                        'assignment_type': assignment_type,
                        'student_id': lesson.student_id if lesson else None
                    }
                )
                if assignment_type == 'classwork':
                    message = f'{len(task_ids)} заданий пропущено в режиме классной работы.'
                else:
                    message = f'{len(task_ids)} заданий пропущено (только для этого урока).'
            else:
                record_skipped(task_ids)
                audit_logger.log(
                    action='skip_tasks',
                    entity='Task',
                    entity_id=None,
                    status='success',
                    metadata={
                        'task_ids': task_ids,
                        'task_count': len(task_ids)
                    }
                )
                message = f'{len(task_ids)} заданий пропущено.'
        elif action == 'blacklist':
            reason = data.get('reason', 'Добавлено пользователем')
            record_blacklist(task_ids, reason=reason)
            audit_logger.log(
                action='blacklist_tasks',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={
                    'task_ids': task_ids,
                    'task_count': len(task_ids),
                    'reason': reason
                }
            )
            message = f'{len(task_ids)} заданий добавлено в черный список.'
        else:
            return jsonify({'success': False, 'error': 'Неизвестное действие'}), 400

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/accepted')
def show_accepted():
    try:
        task_type = request.args.get('task_type', type=int, default=None)

        accepted_tasks = get_accepted_tasks(task_type=task_type)

        if not accepted_tasks:
            message = f'Нет принятых заданий типа {task_type}.' if task_type else 'Нет принятых заданий.'
            flash(message, 'info')
            return redirect(url_for('kege_generator'))

        return render_template('accepted.html', tasks=accepted_tasks, task_type=task_type)

    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('kege_generator'))

@app.route('/skipped')
def show_skipped():
    try:
        task_type = request.args.get('task_type', type=int, default=None)

        skipped_tasks = get_skipped_tasks(task_type=task_type)

        if not skipped_tasks:
            message = f'Нет пропущенных заданий типа {task_type}.' if task_type else 'Нет пропущенных заданий.'
            flash(message, 'info')
            return redirect(url_for('kege_generator'))

        return render_template('skipped.html', tasks=skipped_tasks, task_type=task_type)

    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('kege_generator'))

@app.cli.command('init-db')
def init_db_command():
    if not os.path.exists(os.path.join(base_dir, 'data')):
        os.makedirs(os.path.join(base_dir, 'data'))

    db.create_all()
    print(f'База данных инициализирована в {db_path}')

@app.cli.command('remove-show-answer')
def remove_show_answer_command():
    from sqlalchemy import text

    print('Удаление "показать ответ" из всех заданий...')

    try:
        all_tasks = Tasks.query.all()
        updated_count = 0

        for task in all_tasks:
            original = task.content_html
            if not original:
                continue

            updated = original
            updated = updated.replace('показать ответ', '')
            updated = updated.replace('Показать ответ', '')
            updated = updated.replace('ПОКАЗАТЬ ОТВЕТ', '')
            updated = updated.replace('Показать Ответ', '')
            updated = updated.replace('Показать ОТВЕТ', '')
            updated = updated.replace('показать ОТВЕТ', '')

            if updated != original:
                task.content_html = updated
                updated_count += 1

        db.session.commit()

        print(f'Обновлено заданий: {updated_count}')
        print('Готово!')

    except Exception as e:
        db.session.rollback()
        print(f'Ошибка: {e}')
        import traceback
        traceback.print_exc()

@app.route('/export-data')
def export_data():
    try:
        logger.info('Начало экспорта данных')
        export_data = {
            'students': [{'name': s.name, 'platform_id': s.platform_id, 'category': s.category, 'target_score': s.target_score, 'deadline': s.deadline, 'diagnostic_level': s.diagnostic_level, 'description': s.description, 'notes': s.notes, 'strengths': s.strengths, 'weaknesses': s.weaknesses, 'preferences': s.preferences, 'overall_rating': s.overall_rating} for s in Student.query.filter_by(is_active=True).all()],
            'lessons': [{'student_id': l.student_id, 'lesson_type': l.lesson_type, 'lesson_date': l.lesson_date.isoformat() if l.lesson_date else None, 'duration': l.duration, 'status': l.status, 'topic': l.topic, 'notes': l.notes, 'homework': l.homework, 'homework_status': l.homework_status, 'homework_result_percent': l.homework_result_percent, 'homework_result_notes': l.homework_result_notes} for l in Lesson.query.all()]
        }
        response = make_response(json.dumps(export_data, ensure_ascii=False, indent=2))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        logger.info(f'Экспорт завершен: {len(export_data["students"])} учеников, {len(export_data["lessons"])} уроков')
        
        # Логируем экспорт данных
        audit_logger.log(
            action='export_data',
            entity='Data',
            entity_id=None,
            status='success',
            metadata={
                'students_count': len(export_data["students"]),
                'lessons_count': len(export_data["lessons"])
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
        return redirect(url_for('dashboard'))

@app.route('/import-data', methods=['GET', 'POST'])
def import_data():
    if request.method == 'GET':
        return render_template('import_data.html')
    try:
        if 'file' not in request.files:
            flash('Файл не выбран', 'error')
            return redirect(url_for('import_data'))
        file = request.files['file']
        if file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(url_for('import_data'))
        if not file.filename.endswith('.json'):
            flash('Поддерживаются только JSON файлы', 'error')
            return redirect(url_for('import_data'))
        data = json.loads(file.read().decode('utf-8'))
        imported_students = 0
        imported_lessons = 0
        if 'students' in data:
            for student_data in data['students']:
                existing = Student.query.filter_by(name=student_data.get('name'), platform_id=student_data.get('platform_id')).first()
                if not existing:
                    student = Student(name=student_data.get('name'), platform_id=student_data.get('platform_id'), category=student_data.get('category'), target_score=student_data.get('target_score'), deadline=student_data.get('deadline'), diagnostic_level=student_data.get('diagnostic_level'), description=student_data.get('description'), notes=student_data.get('notes'), strengths=student_data.get('strengths'), weaknesses=student_data.get('weaknesses'), preferences=student_data.get('preferences'), overall_rating=student_data.get('overall_rating'), is_active=True)
                    db.session.add(student)
                    imported_students += 1
        if 'lessons' in data:
            for lesson_data in data['lessons']:
                if Student.query.get(lesson_data.get('student_id')):
                    lesson = Lesson(student_id=lesson_data.get('student_id'), lesson_type=lesson_data.get('lesson_type'), lesson_date=datetime.fromisoformat(lesson_data['lesson_date']) if lesson_data.get('lesson_date') else moscow_now(), duration=lesson_data.get('duration', 60), status=lesson_data.get('status', 'planned'), topic=lesson_data.get('topic'), notes=lesson_data.get('notes'), homework=lesson_data.get('homework'), homework_status=lesson_data.get('homework_status', 'pending'), homework_result_percent=lesson_data.get('homework_result_percent'), homework_result_notes=lesson_data.get('homework_result_notes'))
                    db.session.add(lesson)
                    imported_lessons += 1
        db.session.commit()
        logger.info(f'Импорт завершен: {imported_students} учеников, {imported_lessons} уроков')
        
        # Логируем импорт данных
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
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при импорте данных: {e}')
        audit_logger.log_error(
            action='import_data',
            entity='Data',
            error=str(e)
        )
        flash(f'Ошибка при импорте данных: {str(e)}', 'error')
        return redirect(url_for('import_data'))

@app.route('/backup-db')
def backup_db():
    try:
        backup_dir = os.path.join(base_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_filename = f'keg_tasks_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        shutil.copy2(db_path, backup_path)
        logger.info(f'Резервная копия создана: {backup_path}')
        
        # Логируем создание бэкапа
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
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f'Ошибка при создании резервной копии: {e}')
        flash(f'Ошибка при создании резервной копии: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/bulk-create-lessons', methods=['GET', 'POST'])
def bulk_create_lessons():

    if request.method == 'GET':
        return render_template('bulk_create_lessons.html')

    try:

        data = request.form.get('lessons_data', '')
        if not data:
            flash('Данные не указаны', 'error')
            return redirect(url_for('bulk_create_lessons'))

        try:
            lessons_data = json.loads(data)
        except json.JSONDecodeError as e:
            flash(f'Ошибка парсинга JSON данных: {str(e)}', 'error')
            return redirect(url_for('bulk_create_lessons'))

        created_count = 0
        skipped_count = 0
        errors = []

        for lesson_data in lessons_data:
            try:
                platform_id = lesson_data.get('platform_id')
                if not platform_id:
                    errors.append(f"Пропущен урок: не указан platform_id")
                    skipped_count += 1
                    continue

                student = Student.query.filter_by(platform_id=platform_id.strip()).first()
                if not student:
                    errors.append(f"Ученик с ID '{platform_id}' не найден")
                    skipped_count += 1
                    continue

                date_str = lesson_data.get('date')
                time_str = lesson_data.get('time', '10:00')
                duration = lesson_data.get('duration', 60)
                status = lesson_data.get('status', 'completed')

                datetime_str = f"{date_str} {time_str}"
                lesson_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
                lesson_datetime = lesson_datetime.replace(tzinfo=MOSCOW_TZ)

                existing = Lesson.query.filter_by(
                    student_id=student.student_id,
                    lesson_date=lesson_datetime
                ).first()

                if existing:
                    errors.append(f"Урок уже существует: {student.name} - {datetime_str}")
                    skipped_count += 1
                    continue

                lesson = Lesson(
                    student_id=student.student_id,
                    lesson_type='regular',
                    lesson_date=lesson_datetime,
                    duration=duration,
                    status=status,
                    homework_status='not_assigned'
                )

                db.session.add(lesson)
                created_count += 1

            except Exception as e:
                errors.append(f"Ошибка: {lesson_data} - {str(e)}")
                skipped_count += 1
                continue

        db.session.commit()
        flash(f'Создано уроков: {created_count}, пропущено: {skipped_count}', 'success')
        if errors:
            flash(f'Ошибки: {len(errors)}. Проверьте логи для деталей.', 'warning')
            logger.warning(f'Ошибки при массовом создании уроков: {errors[:10]}')

        return redirect(url_for('bulk_create_lessons'))

    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при массовом создании уроков: {e}', exc_info=True)
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('bulk_create_lessons'))

def check_admin_access():
    # Если уже авторизован через сессию, пропускаем
    if session.get('is_admin'):
        return
    
    # Иначе проверяем секрет из URL
    admin_secret = os.environ.get('ADMIN_SECRET', 'default-admin-secret-change-me')
    request_secret = request.args.get('secret')

    if request_secret != admin_secret:
        from flask import abort
        abort(403)

    session['is_admin'] = True

@app.route('/admin-audit')
def admin_audit():

    check_admin_access()

    from core.db_models import AuditLog, Tester
    from sqlalchemy import func, and_

    tester_id = request.args.get('tester_id', '')
    action = request.args.get('action', '')
    entity = request.args.get('entity', '')
    status = request.args.get('status', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = AuditLog.query

    if tester_id:
        query = query.filter(AuditLog.tester_id == tester_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity:
        query = query.filter(AuditLog.entity == entity)
    if status:
        query = query.filter(AuditLog.status == status)
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%dT%H:%M')
            query = query.filter(AuditLog.timestamp >= date_from_obj)
        except:
            pass
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%dT%H:%M')
            query = query.filter(AuditLog.timestamp <= date_to_obj)
        except:
            pass

    total_events = AuditLog.query.count()
    total_testers = Tester.query.filter_by(is_active=True).count()
    error_count = AuditLog.query.filter_by(status='error').count()

    from datetime import datetime, timedelta
    today_start = datetime.now(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = AuditLog.query.filter(AuditLog.timestamp >= today_start).count()

    actions = db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
    actions = [a[0] for a in actions if a[0]]
    entities = db.session.query(AuditLog.entity).distinct().order_by(AuditLog.entity).all()
    entities = [e[0] for e in entities if e[0]]
    testers = Tester.query.filter_by(is_active=True).order_by(Tester.last_seen.desc()).all()

    page = request.args.get('page', 1, type=int)
    per_page = 50
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    filters = {
        'tester_id': tester_id,
        'action': action,
        'entity': entity,
        'status': status,
        'date_from': date_from,
        'date_to': date_to
    }

    return render_template('admin_audit.html',
                         logs=logs,
                         pagination=pagination,
                         stats={
                             'total_events': total_events,
                             'total_testers': total_testers,
                             'error_count': error_count,
                             'today_events': today_events
                         },
                         filters=filters,
                         actions=actions,
                         entities=entities,
                         testers=testers)

@app.route('/admin-testers')
def admin_testers():
    """Управление тестировщиками"""
    check_admin_access()
    
    from core.db_models import Tester, AuditLog
    from sqlalchemy import func
    
    # Получаем всех тестировщиков с статистикой
    testers = db.session.query(
        Tester,
        func.count(AuditLog.id).label('logs_count'),
        func.max(AuditLog.timestamp).label('last_action')
    ).outerjoin(
        AuditLog, Tester.tester_id == AuditLog.tester_id
    ).group_by(
        Tester.tester_id
    ).order_by(
        Tester.first_seen.desc()
    ).all()
    
    return render_template('admin_testers.html', testers=testers)

@app.route('/admin-testers/<tester_id>/edit', methods=['GET', 'POST'])
def admin_testers_edit(tester_id):
    """Редактирование тестировщика"""
    check_admin_access()
    
    from core.db_models import Tester
    
    tester = Tester.query.get_or_404(tester_id)
    
    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        if not new_name:
            flash('Имя не может быть пустым', 'error')
            return redirect(url_for('admin_testers_edit', tester_id=tester_id))
        
        old_name = tester.name
        tester.name = new_name
        tester.is_active = is_active
        db.session.commit()
        
        # Логируем изменение
        audit_logger.log(
            action='edit_tester',
            entity='Tester',
            entity_id=tester_id,
            status='success',
            metadata={
                'old_name': old_name,
                'new_name': new_name,
                'is_active': is_active
            }
        )
        
        flash(f'Тестировщик "{new_name}" обновлен', 'success')
        return redirect(url_for('admin_testers'))
    
    return render_template('admin_testers_edit.html', tester=tester)

@app.route('/admin-testers/<tester_id>/delete', methods=['POST'])
def admin_testers_delete(tester_id):
    """Удаление тестировщика"""
    check_admin_access()
    
    from core.db_models import Tester, AuditLog
    from sqlalchemy import delete
    
    tester = Tester.query.get_or_404(tester_id)
    tester_name = tester.name
    
    try:
        # Удаляем все логи тестировщика
        deleted_logs = db.session.execute(
            delete(AuditLog).where(AuditLog.tester_id == tester_id)
        ).rowcount
        
        # Удаляем тестировщика
        db.session.delete(tester)
        db.session.commit()
        
        # Логируем удаление
        audit_logger.log(
            action='delete_tester',
            entity='Tester',
            entity_id=tester_id,
            status='success',
            metadata={
                'tester_name': tester_name,
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Тестировщик "{tester_name}" и {deleted_logs} его логов удалены', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении тестировщика: {e}')
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    
    return redirect(url_for('admin_testers'))

@app.route('/admin-testers/clear-all', methods=['POST'])
def admin_testers_clear_all():
    """Очистить всех тестировщиков через админ-панель"""
    check_admin_access()
    
    from core.db_models import Tester, AuditLog
    from sqlalchemy import delete
    
    try:
        testers_count = Tester.query.count()
        logs_count = AuditLog.query.count()
        
        if testers_count == 0 and logs_count == 0:
            flash('Нет данных для очистки', 'info')
            return redirect(url_for('admin_testers'))
        
        # Удаляем все логи
        deleted_logs = db.session.execute(delete(AuditLog)).rowcount
        
        # Удаляем всех тестировщиков
        deleted_testers = db.session.execute(delete(Tester)).rowcount
        
        db.session.commit()
        
        # Логируем очистку
        audit_logger.log(
            action='clear_all_testers',
            entity='Tester',
            entity_id=None,
            status='success',
            metadata={
                'deleted_testers': deleted_testers,
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Удалено {deleted_testers} тестировщиков и {deleted_logs} логов', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при очистке тестировщиков: {e}')
        flash(f'Ошибка при очистке: {str(e)}', 'error')
    
    return redirect(url_for('admin_testers'))

@app.route('/admin-audit/export')
def admin_audit_export():

    check_admin_access()

    from core.db_models import AuditLog
    import csv
    from io import StringIO

    query = AuditLog.query
    tester_id = request.args.get('tester_id', '')
    action = request.args.get('action', '')
    entity = request.args.get('entity', '')
    status = request.args.get('status', '')

    if tester_id:
        query = query.filter(AuditLog.tester_id == tester_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity:
        query = query.filter(AuditLog.entity == entity)
    if status:
        query = query.filter(AuditLog.status == status)

    logs = query.order_by(AuditLog.timestamp.desc()).limit(10000).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Время', 'Тестировщик', 'Действие', 'Сущность', 'ID сущности', 'Статус', 'URL', 'Метод', 'IP', 'Длительность (мс)', 'Метаданные'])

    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            log.tester_name or 'Anonymous',
            log.action,
            log.entity or '',
            log.entity_id or '',
            log.status,
            log.url or '',
            log.method or '',
            log.ip_address or '',
            log.duration_ms or '',
            log.meta_data or ''
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response

@app.cli.command('rotate-audit-logs')
def rotate_audit_logs():

    from core.db_models import AuditLog
    from datetime import datetime, timedelta

    try:

        week_ago = datetime.now(MOSCOW_TZ) - timedelta(days=7)

        old_logs = AuditLog.query.filter(AuditLog.timestamp < week_ago).all()
        count = len(old_logs)

        if count == 0:
            print("Нет логов для архивирования")
            return

        for log in old_logs:
            db.session.delete(log)

        db.session.commit()
        print(f"Архивировано {count} логов старше недели")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при ротации логов: {e}", exc_info=True)
        print(f"Ошибка: {e}")

@app.cli.command('clear-testers-data')
def clear_testers_data():
    """Очистить все данные тестировщиков (Testers и AuditLog)"""
    from core.db_models import Tester, AuditLog
    
    try:
        # Подсчитываем количество записей перед удалением
        testers_count = Tester.query.count()
        logs_count = AuditLog.query.count()
        
        if testers_count == 0 and logs_count == 0:
            print("Нет данных тестировщиков для очистки")
            return
        
        # Удаляем все логи (сначала, чтобы не было проблем с foreign key)
        # Используем правильный синтаксис для bulk delete
        from sqlalchemy import delete
        deleted_logs = db.session.execute(delete(AuditLog)).rowcount
        
        # Удаляем всех тестировщиков
        deleted_testers = db.session.execute(delete(Tester)).rowcount
        
        db.session.commit()
        
        # Проверяем, что действительно удалилось
        remaining_testers = Tester.query.count()
        remaining_logs = AuditLog.query.count()
        
        if remaining_testers > 0 or remaining_logs > 0:
            print(f"⚠️  Внимание: осталось {remaining_testers} тестировщиков и {remaining_logs} логов")
        
        print(f"✅ Очистка завершена:")
        print(f"   - Удалено тестировщиков: {deleted_testers}")
        print(f"   - Удалено логов: {deleted_logs}")
        print(f"   Теперь можно начинать с чистого листа!")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при очистке данных тестировщиков: {e}", exc_info=True)
        print(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    logger.info('Запуск приложения')
    app.run(debug=True, host='127.0.0.1', port=5000)
