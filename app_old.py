import os
import json
import ast
import logging
import shutil
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, session, send_from_directory
from flask_wtf import FlaskForm, CSRFProtect
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import re
from html import unescape
from importlib import import_module
from sqlalchemy import inspect, text, or_
from datetime import datetime, UTC, timedelta, time
import math

BeautifulSoup = None
from wtforms import SelectField, IntegerField, SubmitField, BooleanField, StringField, TextAreaField, DateTimeField, DateTimeLocalField, PasswordField
from wtforms.validators import DataRequired, NumberRange, Optional, Email, ValidationError

from core.db_models import db, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, Student, Lesson, LessonTask, User, TaskTemplate, TemplateTask, moscow_now, MOSCOW_TZ, TOMSK_TZ
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

# Определение окружения (production, sandbox, local)
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')

csrf = CSRFProtect(app)

# Настройка логирования: вывод в консоль и в файл
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('app.log', encoding='utf-8')  # Вывод в файл app.log
    ]
)
logger = logging.getLogger(__name__)
logger.info("Логирование инициализировано. Логи также сохраняются в файл app.log")

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

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Для доступа к системе необходимо войти.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    return User.query.get(int(user_id))

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
                if 'school_class' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN school_class INTEGER'))  # Добавляем колонку для хранения класса
                if 'goal_text' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN goal_text TEXT'))  # Храним текстовую формулировку цели
                if 'programming_language' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN programming_language VARCHAR(100)'))  # Храним выбранный язык программирования

                indexes = {idx['name'] for idx in inspector.get_indexes(students_table)}
                if 'idx_students_category' not in indexes:
                    db.session.execute(text(f'CREATE INDEX idx_students_category ON "{students_table}"(category)'))

            lesson_indexes = {idx['name'] for idx in inspector.get_indexes(lessons_table)}
            if 'idx_lessons_status' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_status ON "{lessons_table}"(status)'))
            if 'idx_lessons_lesson_date' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_lesson_date ON "{lessons_table}"(lesson_date)'))

            # Обновляем старые статусы ДЗ на новые значения, если таблица уже существовала
            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_done\' WHERE homework_status = \'completed\''))  # Старый completed -> assigned_done
            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_not_done\' WHERE homework_status IN (\'pending\', \'not_done\')'))  # pending/not_done -> assigned_not_done

            # Проверяем и обновляем AuditLog таблицу
            audit_log_table = 'AuditLog' if 'AuditLog' in table_names else ('auditlog' if 'auditlog' in table_names else None)
            if audit_log_table:
                audit_log_columns = {col['name'] for col in inspector.get_columns(audit_log_table)}
                # Изменяем session_id на TEXT если он VARCHAR(100)
                try:
                    pg_cursor = db.session.connection().connection.cursor()
                    pg_cursor.execute("""
                        SELECT data_type, character_maximum_length 
                        FROM information_schema.columns 
                        WHERE table_name = %s AND column_name = 'session_id'
                    """, (audit_log_table,))
                    col_info = pg_cursor.fetchone()
                    if col_info and col_info[0] == 'character varying' and col_info[1] == 100:
                        db.session.execute(text(f'ALTER TABLE "{audit_log_table}" ALTER COLUMN session_id TYPE TEXT'))
                        logger.info(f"Updated session_id column in {audit_log_table} to TEXT")
                except Exception as e:
                    logger.warning(f"Could not update session_id column: {e}")

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

# Кеш для отслеживания времени последней проверки уроков
_last_lesson_check = None
_lesson_check_interval = timedelta(minutes=5)  # Проверяем не чаще раза в 5 минут для оптимизации

@app.before_request
def auto_update_lesson_status():
    """Автоматически обновляет статус запланированных уроков на 'completed' после их окончания"""
    global _last_lesson_check
    
    # Пропускаем статические файлы
    if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
        return
    
    try:
        # Проверяем не чаще чем раз в минуту
        now = moscow_now()
        if _last_lesson_check and (now - _last_lesson_check) < _lesson_check_interval:
            return
        
        _last_lesson_check = now
        
        # Оптимизация: обновляем статусы напрямую через SQL, без загрузки всех уроков
        # Находим уроки, которые должны быть завершены (время окончания прошло)
        # lesson_date + duration <= now означает, что урок уже закончился
        try:
            # Используем SQL для массового обновления
            from sqlalchemy import text
            # Проверяем тип БД и используем соответствующий синтаксис
            db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'postgresql' in db_url or 'postgres' in db_url:
                # PostgreSQL синтаксис
                result = db.session.execute(text("""
                    UPDATE "Lessons" 
                    SET status = 'completed', updated_at = :now
                    WHERE status = 'planned' 
                    AND (lesson_date + (duration || ' minutes')::interval) <= :now
                """), {'now': now})
            else:
                # SQLite синтаксис
                result = db.session.execute(text("""
                    UPDATE Lessons 
                    SET status = 'completed', updated_at = :now
                    WHERE status = 'planned' 
                    AND datetime(lesson_date, '+' || duration || ' minutes') <= :now
                """), {'now': now})
            
            updated_count = result.rowcount
            
            if updated_count > 0:
                db.session.commit()
                # Уменьшаем логирование - только если обновлено больше 0
                if updated_count > 5:  # Логируем только если обновлено много уроков
                    logger.info(f"Автоматически обновлено статусов уроков: {updated_count}")
        except Exception as e:
            # Fallback на старый метод, если SQL не работает
            logger.warning(f"Ошибка при массовом обновлении статусов, используем старый метод: {e}")
            try:
                # Фильтруем только уроки, которые могли закончиться (за последние 24 часа)
                yesterday = now - timedelta(days=1)
                planned_lessons = Lesson.query.filter(
                    Lesson.status == 'planned',
                    Lesson.lesson_date >= yesterday
                ).all()
                
                if not planned_lessons:
                    return
                
                updated_count = 0
                for lesson in planned_lessons:
                    lesson_end_time = lesson.lesson_date + timedelta(minutes=lesson.duration)
                    if now >= lesson_end_time:
                        lesson.status = 'completed'
                        lesson.updated_at = now
                        updated_count += 1
                
                if updated_count > 0:
                    db.session.commit()
                    logger.info(f"Автоматически обновлено статусов уроков: {updated_count}")
            except Exception as e2:
                logger.error(f"Ошибка при обновлении статусов уроков: {e2}", exc_info=True)
                db.session.rollback()
    
    except Exception as e:
        logger.error(f"Ошибка при автоматическом обновлении статуса уроков: {e}", exc_info=True)
        # Не блокируем запрос при ошибке
        db.session.rollback()

@app.before_request
def require_login():
    """Проверка авторизации для всех маршрутов кроме login, logout и static"""
    # Исключаем маршруты, которые не требуют авторизации
    if request.endpoint in ('login', 'logout', 'static', 'font_files') or request.path.startswith('/static/') or request.path.startswith('/font/'):
        return
    
    # Проверяем авторизацию
    if not current_user.is_authenticated:
        # Сохраняем URL для редиректа после входа
        if request.endpoint and request.endpoint != 'login':
            return redirect(url_for('login', next=request.url))

@app.before_request
def identify_tester():
    """Идентификация тестировщика (только для неавторизованных пользователей)"""
    try:
        # Пропускаем для статических файлов
        if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
            return

        # Для авторизованных пользователей не создаем тестировщиков
        # Логирование будет происходить через Flask-Login
        if current_user.is_authenticated:
            return

        # Получаем имя тестировщика из заголовка, декодируя если нужно
        # HTTP заголовки должны содержать только ISO-8859-1 символы
        # Если имя содержит не-ASCII символы, оно кодируется в base64
        tester_name_raw = request.headers.get('X-Tester-Name')
        tester_name_encoded = request.headers.get('X-Tester-Name-Encoded')
        if tester_name_raw and tester_name_encoded == 'base64':
            # Декодируем из base64
            try:
                import base64
                import urllib.parse
                # Декодируем base64
                decoded_bytes = base64.b64decode(tester_name_raw)
                # Декодируем URI компонент
                tester_name = urllib.parse.unquote(decoded_bytes.decode('utf-8'))
            except Exception as e:
                logger.warning(f"Ошибка декодирования имени тестировщика: {e}")
                tester_name = tester_name_raw
        else:
            tester_name = tester_name_raw
        # Для неавторизованных пользователей больше не создаем тестировщиков
        # Логирование происходит только для авторизованных пользователей через Flask-Login
        # Старая логика создания тестировщиков удалена

    except Exception as e:
        logger.error(f"Error identifying tester: {e}", exc_info=True)

@app.after_request
def log_page_view(response):

    try:
        # Пропускаем статику, админку, AJAX, JSON
        if (request.endpoint in ('static', 'favicon') or
            request.path.startswith('/static/') or
            request.path.startswith('/admin-audit') or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.is_json):
            return response

        # Фильтруем ботов и health checks
        user_agent = request.headers.get('User-Agent', '').lower()
        bot_patterns = [
            'bot', 'crawler', 'spider', 'scraper', 'monitor', 'health',
            'uptime', 'pingdom', 'newrelic', 'datadog', 'statuscake',
            'railway', 'render', 'vercel', 'netlify', 'uptimerobot'
        ]
        if any(pattern in user_agent for pattern in bot_patterns):
            return response

        # Логируем все GET запросы (даже для анонимных)
        if request.method == 'GET' and response.status_code == 200:
            page_name = request.endpoint or request.path
            audit_logger.log_page_view(
                page_name=page_name,
                metadata={'status_code': response.status_code}
            )
    except Exception as e:
        logger.error(f"Error logging page view: {e}", exc_info=True)

    return response

# Кеш для active_lesson, чтобы не делать запрос на каждом рендере
_active_lesson_cache = None
_active_lesson_cache_time = None
_active_lesson_cache_ttl = timedelta(seconds=5)  # Кешируем на 5 секунд

def clear_active_lesson_cache():
    """Сбрасывает кеш активного урока (вызывается при изменении статуса урока)"""
    global _active_lesson_cache, _active_lesson_cache_time
    _active_lesson_cache = None
    _active_lesson_cache_time = None

@app.context_processor
def inject_active_lesson():
    global _active_lesson_cache, _active_lesson_cache_time
    
    try:
        # Используем кеш, если он еще актуален
        now = moscow_now()
        if (_active_lesson_cache is not None and 
            _active_lesson_cache_time is not None and 
            (now - _active_lesson_cache_time) < _active_lesson_cache_ttl):
            return _active_lesson_cache
        
        # Обновляем кеш
        from sqlalchemy.orm import joinedload
        active_lesson = Lesson.query.options(joinedload(Lesson.student)).filter_by(status='in_progress').first()
        active_student = active_lesson.student if active_lesson else None
        
        _active_lesson_cache = dict(active_lesson=active_lesson, active_student=active_student)
        _active_lesson_cache_time = now
        
        return _active_lesson_cache
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

class TaskSearchForm(FlaskForm):
    task_id = StringField('ID задания', validators=[DataRequired()], render_kw={'placeholder': 'Введите ID задания (например, 23715)'})
    search_submit = SubmitField('Найти и добавить')

def validate_platform_id_unique(form, field):
    """Валидатор для проверки уникальности platform_id при создании/редактировании ученика"""
    if field.data and field.data.strip():
        existing_student = Student.query.filter_by(platform_id=field.data.strip()).first()
        if hasattr(form, '_student_id') and form._student_id:
            if existing_student and existing_student.student_id != form._student_id:
                raise ValidationError('Ученик с таким ID на платформе уже существует!')
        else:
            if existing_student:
                raise ValidationError('Ученик с таким ID на платформе уже существует!')

def normalize_school_class(raw_value):  # Приводим входное значение класса к целому или None
    try:  # Перехватываем любые ошибки преобразования
        if raw_value in (None, '', '0', 0):  # Пустые или нулевые значения не сохраняем
            return None  # Возвращаем None если класс не указан
        class_int = int(raw_value)  # Пробуем привести значение к целому числу
        if 1 <= class_int <= 11:  # Ограничиваем диапазон значениями от 1 до 11
            return class_int  # Возвращаем корректный класс
    except (ValueError, TypeError):  # Ловим ошибки конвертации
        return None  # В случае ошибки возвращаем None
    return None  # Для любых неподдерживаемых значений возвращаем None

def ensure_introductory_without_homework(lesson_form):  # Гарантируем, что вводный урок остается без ДЗ
    if getattr(lesson_form, 'lesson_type', None) and lesson_form.lesson_type.data == 'introductory':
        lesson_form.homework.data = ''
        lesson_form.homework_status.data = 'not_assigned'

HOMEWORK_STATUS_VALUES = {'assigned_done', 'assigned_not_done', 'not_assigned'}
LEGACY_HOMEWORK_STATUS_MAP = {
    'completed': 'assigned_done',
    'pending': 'assigned_not_done',
    'not_done': 'assigned_not_done',
    'not_assigned': 'not_assigned'
}

def normalize_homework_status_value(raw_status):  # Преобразуем устаревшие статусы к актуальным
    if raw_status is None:
        return 'not_assigned'
    if isinstance(raw_status, str):
        normalized = raw_status.strip()
    else:
        normalized = raw_status
    normalized = LEGACY_HOMEWORK_STATUS_MAP.get(normalized, normalized)
    return normalized if normalized in HOMEWORK_STATUS_VALUES else 'not_assigned'

SCHOOL_CLASS_CHOICES = [(0, 'Не указан')]  # Базовый вариант для отсутствующего класса
SCHOOL_CLASS_CHOICES += [(i, f'{i} класс') for i in range(1, 12)]  # Добавляем варианты классов с 1 по 11

class StudentForm(FlaskForm):
    name = StringField('Имя ученика', validators=[DataRequired()])
    platform_id = StringField('ID на платформе', validators=[Optional(), validate_platform_id_unique])

    target_score = IntegerField('Целевой балл', validators=[Optional(), NumberRange(min=0, max=100)])
    deadline = StringField('Сроки', validators=[Optional()])
    goal_text = TextAreaField('Цель (текст)', validators=[Optional()])  # Храним произвольную цель для категорий без баллов
    programming_language = StringField('Язык программирования', validators=[Optional()])  # Информация о предпочитаемом языке

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
        ('ЛЕВЕЛАП', 'ЛЕВЕЛАП'),
        ('ПРОГРАММИРОВАНИЕ', 'ПРОГРАММИРОВАНИЕ')  # Новая категория для программирования
    ], default='', validators=[Optional()])
    school_class = SelectField('Класс', choices=SCHOOL_CLASS_CHOICES, default=0, coerce=int, validators=[Optional()])  # Выпадающий список с классами 1-11

    submit = SubmitField('Сохранить')

class LessonForm(FlaskForm):
    lesson_type = SelectField('Тип урока', choices=[
        ('regular', '📚 Обычный урок'),
        ('exam', '✅ Проверочный урок'),
        ('introductory', '👋 Вводный урок')
    ], default='regular', validators=[DataRequired()])
    timezone = SelectField('Часовой пояс', choices=[
        ('moscow', '🕐 Московское время (МСК)'),
        ('tomsk', '🕐 Томское время (ТОМСК)')
    ], default='moscow', validators=[DataRequired()])
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
        ('assigned_done', 'Задано, выполнено'),
        ('assigned_not_done', 'Задано, не выполнено'),
        ('not_assigned', 'Не задано')
    ], default='assigned_not_done', validators=[DataRequired()])
    submit = SubmitField('Сохранить')

class LoginForm(FlaskForm):
    """Форма входа для пользователей"""
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

@app.route('/font/<path:filename>')
def font_files(filename):
    """Сервим шрифты из папки font"""
    font_dir = os.path.join(base_dir, 'font')
    return send_from_directory(font_dir, filename, mimetype='font/otf' if filename.endswith('.otf') else 'font/ttf')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа для тестеров"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        
        # Ищем пользователя по логину
        user = User.query.filter_by(username=username).first()
        
        if user and user.is_active:
            # Проверяем пароль
            if check_password_hash(user.password_hash, password):
                # Обновляем время последнего входа
                user.last_login = moscow_now()
                db.session.commit()
                
                # Входим
                login_user(user, remember=True)
                
                # Логируем вход
                audit_logger.log(
                    action='login',
                    entity='User',
                    entity_id=user.id,
                    status='success',
                    metadata={'username': user.username, 'role': user.role}
                )
                
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('dashboard')
                flash('Вход выполнен успешно!', 'success')
                return redirect(next_page)
            else:
                flash('Неверный логин или пароль.', 'danger')
                audit_logger.log(
                    action='login_failed',
                    entity='User',
                    status='error',
                    metadata={'username': username, 'reason': 'invalid_password'}
                )
        else:
            flash('Неверный логин или пароль.', 'danger')
            audit_logger.log(
                action='login_failed',
                entity='User',
                status='error',
                metadata={'username': username, 'reason': 'user_not_found_or_inactive'}
            )
    
    return render_template('login.html', form=form)

@app.route('/logout', methods=['GET', 'POST'])
@csrf.exempt  # Исключаем из CSRF защиты, так как выход - безопасная операция
@login_required
def logout():
    """Выход из системы"""
    username = current_user.username
    logout_user()
    flash('Вы вышли из системы.', 'info')
    
    audit_logger.log(
        action='logout',
        entity='User',
        status='success',
        metadata={'username': username}
    )
    
    return redirect(url_for('login'))

@app.route('/user/profile')
@login_required
def user_profile():
    """Страница профиля пользователя"""
    return render_template('user_profile.html')

@app.route('/admin')
@login_required
def admin_panel():
    """Админ панель (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # Статистика для админ панели
        from core.db_models import User, Tester, AuditLog
        from sqlalchemy import func
        from sqlalchemy.exc import OperationalError, ProgrammingError
        
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        creators_count = User.query.filter_by(role='creator').count()
        testers_count = User.query.filter_by(role='tester').count()
        
        # Статистика по логам - с обработкой ошибок
        try:
            # Проверяем, существует ли таблица AuditLog
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()  # Откатываем транзакцию после ошибки
            audit_log_exists = False
        
        if audit_log_exists:
            try:
                total_logs = AuditLog.query.count()
                today_logs = AuditLog.query.filter(
                    func.date(AuditLog.timestamp) == func.current_date()
                ).count()
            except Exception as e:
                logger.error(f"Error querying AuditLog statistics: {e}", exc_info=True)
                db.session.rollback()  # Откатываем транзакцию после ошибки
                total_logs = 0
                today_logs = 0
        else:
            total_logs = 0
            today_logs = 0
        
        return render_template('admin_panel.html',
                             total_users=total_users,
                             active_users=active_users,
                             creators_count=creators_count,
                             testers_count=testers_count,
                             total_logs=total_logs,
                             today_logs=today_logs)
    except Exception as e:
        logger.error(f"Error in admin_panel route: {e}", exc_info=True)
        flash(f'Ошибка при загрузке статистики: {str(e)}', 'error')
        # Fallback: возвращаем минимальную статистику
        try:
            from core.db_models import User
            total_users = User.query.count()
            active_users = User.query.filter_by(is_active=True).count()
            creators_count = User.query.filter_by(role='creator').count()
            testers_count = User.query.filter_by(role='tester').count()
            return render_template('admin_panel.html',
                                 total_users=total_users,
                                 active_users=active_users,
                                 creators_count=creators_count,
                                 testers_count=testers_count,
                                 total_logs=0,
                                 today_logs=0)
        except Exception as e2:
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('dashboard'))

@app.route('/index')
@app.route('/home')
@login_required
def index():
    """Главная страница с описанием платформы"""
    return render_template('index.html')

@app.route('/')
@login_required
def dashboard():
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
    from sqlalchemy import func
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
                         recent_lessons=recent_lessons)  # Передаем количество архивных учеников

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
                    return redirect(url_for('student_new'))

            school_class_value = normalize_school_class(form.school_class.data)  # Приводим выбранный класс к допустимому значению
            goal_text_value = form.goal_text.data.strip() if (form.goal_text.data and form.goal_text.data.strip()) else None  # Забираем текстовую цель
            programming_language_value = form.programming_language.data.strip() if (form.programming_language.data and form.programming_language.data.strip()) else None  # Забираем язык программирования
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
                category=form.category.data if form.category.data else None,
                school_class=school_class_value,  # Сохраняем номер класса ученика
                goal_text=goal_text_value,  # Сохраняем текстовую цель
                programming_language=programming_language_value  # Сохраняем язык программирования
            )
            db.session.add(student)
            db.session.commit()
            

            # Логируем создание ученика (с обработкой ошибок, чтобы не ломать функционал)
            try:
                audit_logger.log(
                    action='create_student',
                status='success',
                metadata={
                    'name': student.name,
                    'platform_id': student.platform_id,
                    'category': student.category,
                    'school_class': student.school_class,  # Добавляем класс в метаданные
                    'goal_text': student.goal_text,  # Фиксируем текстовую цель для истории
                    'programming_language': student.programming_language  # Фиксируем выбранный язык программирования
                }
            )
            except Exception as log_err:
                logger.warning(f"Ошибка при логировании создания ученика: {log_err}")
            
            flash(f'Ученик {student.name} успешно добавлен!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при добавлении ученика: {e}', exc_info=True)
            
            # Логируем ошибку
            try:
                audit_logger.log_error(
                    action='create_student',
                    entity='Student',
                    error=str(e),
                    metadata={'form_data': {k: str(v) for k, v in form.data.items() if k != 'csrf_token'}}
                )
            except Exception as log_error:
                logger.error(f'Ошибка при логировании: {log_error}')
            
            flash(f'Ошибка при добавлении ученика: {str(e)}', 'error')
            # Редирект на GET запрос, чтобы избежать проблемы с повторной отправкой формы
            return redirect(url_for('student_new'))

    # Логируем попытку отправки формы для отладки, если это POST запрос
    if request.method == 'POST' and not form.validate_on_submit():
        logger.warning(f'Ошибки валидации формы при создании ученика: {form.errors}')

    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)

@app.route('/student/<int:student_id>')
def student_profile(student_id):
    # КРИТИЧЕСКАЯ ОПТИМИЗАЦИЯ: загружаем уроки отдельным запросом с joinedload для homework_tasks
    # Это избегает N+1 проблем при обращении к lesson.homework_assignments в шаблоне
    student = Student.query.get_or_404(student_id)
    
    # Загружаем уроки с предзагрузкой homework_tasks и task для каждого homework_task
    lessons = Lesson.query.filter_by(student_id=student_id).options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).order_by(Lesson.lesson_date.desc()).all()
    
    return render_template('student_profile.html', student=student, lessons=lessons)

@app.route('/student/<int:student_id>/statistics')
def student_statistics(student_id):
    """Страница статистики выполнения заданий по номерам"""
    student = Student.query.get_or_404(student_id)
    
    # Загружаем все уроки с заданиями
    lessons = Lesson.query.filter_by(student_id=student_id).options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).all()
    
    # Собираем статистику по номерам заданий
    # Ключ: номер задания (task_number), значение: {correct: вес, total: вес}
    task_stats = {}
    
    for lesson in lessons:
        # Обрабатываем все типы заданий
        for assignment_type in ['homework', 'classwork', 'exam']:
            assignments = get_sorted_assignments(lesson, assignment_type)
            weight = 2 if assignment_type == 'exam' else 1
            
            for lt in assignments:
                if not lt.task or not lt.task.task_number:
                    continue
                
                task_num = lt.task.task_number
                
                if task_num not in task_stats:
                    task_stats[task_num] = {'correct': 0, 'total': 0}
                
                # Учитываем только задания с проверенными ответами
                if lt.submission_correct is not None:
                    task_stats[task_num]['total'] += weight
                    if lt.submission_correct:
                        task_stats[task_num]['correct'] += weight
    
    # Вычисляем проценты и формируем данные для диаграммы
    chart_data = []
    for task_num in sorted(task_stats.keys()):
        stats = task_stats[task_num]
        if stats['total'] > 0:
            percent = round((stats['correct'] / stats['total']) * 100, 1)
            # Определяем цвет: красный (0-40%), желтый (40-80%), зеленый (80-100%)
            if percent < 40:
                color = '#ef4444'  # красный
            elif percent < 80:
                color = '#eab308'  # желтый
            else:
                color = '#22c55e'  # зеленый
            
            chart_data.append({
                'task_number': task_num,
                'percent': percent,
                'correct': stats['correct'],
                'total': stats['total'],
                'color': color
            })
    
    return render_template('student_statistics.html', 
                         student=student, 
                         chart_data=chart_data)

@app.route('/student/<int:student_id>/edit', methods=['GET', 'POST'])
def student_edit(student_id):
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)
    form._student_id = student_id
    if request.method == 'GET':  # При первичном открытии формы выставляем значение класса
        form.school_class.data = student.school_class if student.school_class else 0  # Показываем актуальный класс или "Не указан"

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
            student.school_class = normalize_school_class(form.school_class.data)  # Обновляем сохраненный класс ученика
            student.goal_text = form.goal_text.data.strip() if form.goal_text.data else None  # Сохраняем текстовую цель
            student.programming_language = form.programming_language.data.strip() if form.programming_language.data else None  # Сохраняем язык программирования
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
                    'category': student.category,
                    'school_class': student.school_class,  # Добавляем данные о классе в логи
                    'goal_text': student.goal_text,  # Фиксируем текстовую цель
                    'programming_language': student.programming_language  # Фиксируем язык программирования
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
        ensure_introductory_without_homework(form)  # Вводный урок не содержит ДЗ
        
        # Обрабатываем дату с учетом часового пояса
        lesson_date_local = form.lesson_date.data
        timezone = form.timezone.data
        
        # Преобразуем локальное время в нужный часовой пояс
        if timezone == 'tomsk':
            # Если выбран томский часовой пояс, создаем datetime с TOMSK_TZ
            lesson_date_local = lesson_date_local.replace(tzinfo=TOMSK_TZ)
            # Конвертируем в московское время для хранения в БД
            lesson_date_utc = lesson_date_local.astimezone(MOSCOW_TZ)
        else:
            # Если выбран московский часовой пояс
            lesson_date_local = lesson_date_local.replace(tzinfo=MOSCOW_TZ)
            lesson_date_utc = lesson_date_local
        
        lesson = Lesson(
            student_id=student_id,
            lesson_type=form.lesson_type.data,
            lesson_date=lesson_date_utc,
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
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    form = LessonForm(obj=lesson)
    
    # При редактировании устанавливаем московский часовой пояс по умолчанию
    # (все уроки в БД хранятся в московском времени)
    if request.method == 'GET':
        form.timezone.data = 'moscow'

    if form.validate_on_submit():
        ensure_introductory_without_homework(form)  # Чистим ДЗ, если переключились на вводный урок
        
        # Обрабатываем дату с учетом часового пояса
        lesson_date_local = form.lesson_date.data
        timezone = form.timezone.data
        
        # Преобразуем локальное время в нужный часовой пояс
        if timezone == 'tomsk':
            # Если выбран томский часовой пояс, создаем datetime с TOMSK_TZ
            lesson_date_local = lesson_date_local.replace(tzinfo=TOMSK_TZ)
            # Конвертируем в московское время для хранения в БД
            lesson_date_utc = lesson_date_local.astimezone(MOSCOW_TZ)
        else:
            # Если выбран московский часовой пояс
            lesson_date_local = lesson_date_local.replace(tzinfo=MOSCOW_TZ)
            lesson_date_utc = lesson_date_local
        
        lesson.lesson_type = form.lesson_type.data
        lesson.lesson_date = lesson_date_utc
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
    return redirect(url_for('student_profile', student_id=student_id))

@app.route('/student/<int:student_id>/lesson-mode')
def lesson_mode(student_id):
    # Оптимизация: загружаем все данные одним запросом
    student = Student.query.get_or_404(student_id)
    now = moscow_now()
    
    # Загружаем все уроки одним запросом
    all_lessons = Lesson.query.filter_by(student_id=student_id).order_by(Lesson.lesson_date.desc()).all()
    lessons = all_lessons
    
    # Находим текущий и ближайший урок из уже загруженных данных
    current_lesson = next((l for l in all_lessons if l.status == 'in_progress'), None)
    planned_lessons = [l for l in all_lessons if l.status == 'planned' and l.lesson_date and l.lesson_date >= now]
    upcoming_lesson = sorted(planned_lessons, key=lambda x: x.lesson_date)[0] if planned_lessons else None

    return render_template('lesson_mode.html',
                         student=student,
                         lessons=lessons,
                         current_lesson=current_lesson,
                         upcoming_lesson=upcoming_lesson)

@app.route('/student/<int:student_id>/start-lesson', methods=['POST'])
def student_start_lesson(student_id):
    student = Student.query.get_or_404(student_id)
    now = moscow_now()

    # Оптимизация: один запрос вместо двух
    active_lesson = Lesson.query.filter_by(student_id=student_id, status='in_progress').first()
    if active_lesson:
        flash('Урок уже идет!', 'info')
        return redirect(url_for('student_profile', student_id=student_id))

    # Оптимизация: используем limit(1) для лучшей производительности
    upcoming_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'planned',
        Lesson.lesson_date >= now
    ).order_by(Lesson.lesson_date).limit(1).first()

    if upcoming_lesson:
        upcoming_lesson.status = 'in_progress'
        db.session.commit()
        clear_active_lesson_cache()  # Сбрасываем кеш при изменении статуса
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
        clear_active_lesson_cache()  # Сбрасываем кеш при создании нового урока
        flash(f'Новый урок создан и начат!', 'success')

    return redirect(url_for('student_profile', student_id=student_id))

@app.route('/lesson/<int:lesson_id>/start', methods=['POST'])
def lesson_start(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson.status = 'in_progress'
    db.session.commit()
    clear_active_lesson_cache()  # Сбрасываем кеш при старте урока
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
    """Получает отсортированные задания по типу"""
    if assignment_type == 'homework':
        assignments = lesson.homework_assignments
    elif assignment_type == 'classwork':
        assignments = lesson.classwork_assignments
    elif assignment_type == 'exam':
        assignments = lesson.exam_assignments
    else:
        assignments = lesson.homework_assignments
    return sorted(assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))

@app.route('/lesson/<int:lesson_id>/homework-tasks')
def lesson_homework_view(lesson_id):
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    homework_tasks = get_sorted_assignments(lesson, 'homework')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=homework_tasks,
                           assignment_type='homework')

@app.route('/lesson/<int:lesson_id>/classwork-tasks')
def lesson_classwork_view(lesson_id):
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=classwork_tasks,
                           assignment_type='classwork')

@app.route('/lesson/<int:lesson_id>/exam-tasks')
def lesson_exam_view(lesson_id):
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    exam_tasks = get_sorted_assignments(lesson, 'exam')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=exam_tasks,
                           assignment_type='exam')

@app.route('/lesson/<int:lesson_id>/homework-tasks/save', methods=['POST'])
def lesson_homework_save(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    homework_tasks = [ht for ht in lesson.homework_assignments]

    for hw_task in homework_tasks:
        answer_key = f'answer_{hw_task.lesson_task_id}'
        if answer_key in request.form:
            # Сохраняем ответ в student_answer (для ручного ввода или переопределения ответа из базы)
            submitted_answer = request.form.get(answer_key).strip()
            # Если ответ из базы был изменен вручную, сохраняем новый ответ
            hw_task.student_answer = submitted_answer if submitted_answer else None

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

    if lesson.lesson_type == 'introductory':
        lesson.homework_status = 'not_assigned'
    elif lesson.homework_result_percent is not None or lesson.homework_result_notes:
        lesson.homework_status = 'assigned_done'
    elif homework_tasks:
        lesson.homework_status = 'assigned_not_done'
    else:
        lesson.homework_status = 'not_assigned'

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

def perform_auto_check(lesson, assignment_type):
    """Универсальная функция автопроверки для homework, classwork и exam"""
    tasks = get_sorted_assignments(lesson, assignment_type)
    
    if not tasks:
        type_name = {'homework': 'ДЗ', 'classwork': 'классной работы', 'exam': 'проверочной'}.get(assignment_type, 'заданий')
        error_msg = f'У этого урока нет заданий {type_name} для проверки.'
        # Для AJAX возвращаем ошибку в специальном формате
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'warning'}, None
        flash(error_msg, 'warning')
        return None, None
    
    answers_raw = request.form.get('auto_answers', '').strip()
    if not answers_raw:
        error_msg = 'Вставь массив ответов в формате [1, -1, "Москва"].'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'warning'}, None
        flash(error_msg, 'warning')
        return None, None
    
    try:
        parsed_answers = ast.literal_eval(answers_raw)
        if not isinstance(parsed_answers, (list, tuple)):
            raise ValueError
        answers_list = list(parsed_answers)
    except Exception:
        error_msg = 'Не удалось разобрать ответы. Используй формат [1, -1, "Москва"].'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'danger'}, None
        flash(error_msg, 'danger')
        return None, None
    
    total_tasks = len(tasks)
    correct_count = 0
    incorrect_count = 0
    
    # Для exam вес ×2
    weight = 2 if assignment_type == 'exam' else 1
    
    if len(answers_list) != total_tasks:
        warning_msg = f'Количество ответов ({len(answers_list)}) не совпадает с числом заданий ({total_tasks}). Отсутствующие ответы будут считаться неверными.'
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash(warning_msg, 'warning')
    
    def answer_at(index):
        if index < len(answers_list):
            return answers_list[index]
        return None
    
    for idx, task in enumerate(tasks):
        student_value = answer_at(idx)
        student_text = '' if student_value is None else str(student_value).strip()
        task.student_submission = student_text if student_text else None
        
        is_skip = student_text == '' or student_text == '-1' or student_text.lower() == 'null'
        # Используем student_answer, если он был введен вручную, иначе ответ из базы данных (task.answer)
        expected_text = (task.student_answer if task.student_answer else (task.task.answer if task.task and task.task.answer else '')) or ''
        
        if not expected_text:
            task.submission_correct = False
            incorrect_count += weight  # Учитываем вес для exam
            continue
        
        if is_skip:
            task.submission_correct = False
            incorrect_count += weight  # Учитываем вес для exam
            continue
        
        normalized_student = normalize_answer_value(student_text)
        normalized_expected = normalize_answer_value(expected_text)
        
        is_correct = normalized_student == normalized_expected and normalized_expected != ''
        task.submission_correct = is_correct
        
        if is_correct:
            correct_count += weight  # Учитываем вес для exam
        else:
            incorrect_count += weight  # Учитываем вес для exam
    
    # Для расчета процента учитываем вес
    total_weighted = correct_count + incorrect_count
    percent = round((correct_count / total_weighted) * 100, 2) if total_weighted > 0 else 0
    
    return correct_count, incorrect_count, percent, total_tasks

@app.route('/lesson/<int:lesson_id>/homework-auto-check', methods=['POST'])
def lesson_homework_auto_check(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'homework')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if isinstance(result[0], dict) and 'error' in result[0]:
            # Ошибка из perform_auto_check
            return jsonify({'success': False, 'error': result[0]['error'], 'category': result[0].get('category', 'error')}), 400
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result
        homework_tasks = get_sorted_assignments(lesson, 'homework')

        lesson.homework_result_percent = percent
        summary = f"Автопроверка {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
        if lesson.homework_result_notes:
            lesson.homework_result_notes = lesson.homework_result_notes + "\n" + summary
        else:
            lesson.homework_result_notes = summary

        if lesson.lesson_type == 'introductory' or total_tasks == 0:
            lesson.homework_status = 'not_assigned'
        else:
            lesson.homework_status = 'assigned_done' if correct_count == total_tasks else 'assigned_not_done'

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
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result
    homework_tasks = get_sorted_assignments(lesson, 'homework')

    lesson.homework_result_percent = percent
    summary = f"Автопроверка {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
    if lesson.homework_result_notes:
        lesson.homework_result_notes = lesson.homework_result_notes + "\n" + summary
    else:
        lesson.homework_result_notes = summary

    if lesson.lesson_type == 'introductory' or total_tasks == 0:
        lesson.homework_status = 'not_assigned'
    else:
        lesson.homework_status = 'assigned_done' if correct_count == total_tasks else 'assigned_not_done'

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
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).', 'success')
    return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))

@app.route('/lesson/<int:lesson_id>/classwork-auto-check', methods=['POST'])
def lesson_classwork_auto_check(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'classwork')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result
        
        # Для классной работы сохраняем результат в notes (так как нет отдельного поля)
        summary = f"Автопроверка классной работы {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
        if lesson.notes:
            lesson.notes = lesson.notes + "\n" + summary
        else:
            lesson.notes = summary
        
        db.session.commit()
        
        audit_logger.log(
            action='auto_check_classwork',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lesson_classwork_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lesson_classwork_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result
    
    # Для классной работы сохраняем результат в notes (так как нет отдельного поля)
    summary = f"Автопроверка классной работы {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
    if lesson.notes:
        lesson.notes = lesson.notes + "\n" + summary
    else:
        lesson.notes = summary
    
    db.session.commit()
    
    audit_logger.log(
        action='auto_check_classwork',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).', 'success')
    return redirect(url_for('lesson_classwork_view', lesson_id=lesson_id))

@app.route('/lesson/<int:lesson_id>/exam-auto-check', methods=['POST'])
def lesson_exam_auto_check(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'exam')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result
        
        # Для проверочной работы сохраняем результат в notes
        summary = f"Автопроверка проверочной {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%). Вес ×2."
        if lesson.notes:
            lesson.notes = lesson.notes + "\n" + summary
        else:
            lesson.notes = summary
        
        db.session.commit()
        
        audit_logger.log(
            action='auto_check_exam',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent,
                'weight': 2
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%). Учтено с весом ×2.'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lesson_exam_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lesson_exam_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result
    
    # Для проверочной работы сохраняем результат в notes
    summary = f"Автопроверка проверочной {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%). Вес ×2."
    if lesson.notes:
        lesson.notes = lesson.notes + "\n" + summary
    else:
        lesson.notes = summary
    
    db.session.commit()
    
    audit_logger.log(
        action='auto_check_exam',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent,
            'weight': 2
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%). Учтено с весом ×2.', 'success')
    return redirect(url_for('lesson_exam_view', lesson_id=lesson_id))

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

def lesson_export_md(lesson_id, assignment_type='homework'):
    """
    Универсальная функция экспорта заданий в Markdown
    assignment_type: 'homework', 'classwork', 'exam'
    """
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student

    # Получаем задания по типу
    if assignment_type == 'homework':
        tasks = sorted(lesson.homework_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Домашнее задание"
    elif assignment_type == 'classwork':
        tasks = sorted(lesson.classwork_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Классная работа"
    elif assignment_type == 'exam':
        tasks = sorted(lesson.exam_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Проверочная работа"
    else:
        tasks = sorted(lesson.homework_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Задания"

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

        # Обработка списков (ul, ol) - сохраняем структуру для правильного экспорта
        # ВАЖНО: обрабатываем ДО обработки блочных элементов, чтобы сохранить структуру
        def extract_list_item_text(li):
            """Извлекает текст из элемента списка с сохранением переносов строк"""
            parts = []
            for child in li.children:
                if isinstance(child, str):
                    text = child.strip()
                    if text:
                        parts.append(text)
                elif hasattr(child, 'name'):
                    if child.name == 'br':
                        parts.append('\n')
                    elif child.name in ['p', 'div']:
                        # Для блочных элементов внутри li сохраняем переносы строк
                        p_text = child.get_text(separator='\n', strip=True)
                        if p_text:
                            parts.append(p_text)
                    else:
                        child_text = child.get_text(separator=' ', strip=True)
                        if child_text:
                            parts.append(child_text)
            return ' '.join(parts).strip()
        
        for ul in soup.find_all('ul'):
            if not ul.find_parent(['td', 'th', 'table']):
                items = ul.find_all('li', recursive=False)
                if items:
                    list_items = []
                    for li in items:
                        li_text = extract_list_item_text(li)
                        if li_text:
                            list_items.append(f"- {li_text}")
                    if list_items:
                        list_text = '\n'.join(list_items)
                        ul.replace_with(soup.new_string(f'\n\n{list_text}\n\n'))
                    else:
                        ul.decompose()
                else:
                    ul.decompose()
        
        for ol in soup.find_all('ol'):
            if not ol.find_parent(['td', 'th', 'table']):
                items = ol.find_all('li', recursive=False)
                if items:
                    list_items = []
                    for idx, li in enumerate(items):
                        li_text = extract_list_item_text(li)
                        if li_text:
                            list_items.append(f"{idx + 1}. {li_text}")
                    if list_items:
                        list_text = '\n'.join(list_items)
                        ol.replace_with(soup.new_string(f'\n\n{list_text}\n\n'))
                    else:
                        ol.decompose()
                else:
                    ol.decompose()
        
        # Заменяем <br> на переносы строк (не на пробелы!) для сохранения форматирования
        for br in soup.find_all('br'):
            br.replace_with(soup.new_string('\n'))

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

        # Удаление строк "Файлы к заданию" и подобных перед экспортом
        for text_node in soup.find_all(string=True):
            if text_node.parent and text_node.parent.name not in ['script', 'style']:
                text = str(text_node)
                # Удаляем строки с "Файлы к заданию"
                cleaned_text = re.sub(r'[Фф]айлы?\s+к\s+заданию[:\s-]*[^\n]*', '', text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'[Фф]айлы?\s+к\s+задаче[:\s-]*[^\n]*', '', cleaned_text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'[Пп]рикреплен[а-яё]*\s+файл[а-яё]*[:\s-]*[^\n]*', '', cleaned_text, flags=re.IGNORECASE)
                if cleaned_text != text:
                    text_node.replace_with(cleaned_text)
        
        # Используем separator='\n' вместо ' ' для сохранения переносов строк
        text = soup.get_text(separator='\n', strip=False)
        text = unescape(text)
        text = re.sub(r'\r\n?', '\n', text)
        # Очистка пробелов в строках (но сохраняем переносы строк)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Схлопываем множественные пробелы/табы в строке, но сохраняем саму строку
            cleaned_line = re.sub(r'[ \t]+', ' ', line)
            cleaned_lines.append(cleaned_line)
        text = '\n'.join(cleaned_lines)
        text = re.sub(r' \$\$', '\n\n$$', text)
        text = re.sub(r'\$\$ ', '$$\n\n', text)
        text = re.sub(r' \$', ' $', text)
        text = re.sub(r'\$ ', '$ ', text)
        text = re.sub(r' \n', '\n', text)
        text = re.sub(r'\n ', '\n', text)
        # Удаляем множественные пустые строки (оставляем максимум 2 подряд для разделения блоков)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
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
                # Оставляем максимум одну пустую строку подряд
                if not prev_blank:
                    cleaned.append('')
                prev_blank = True
        result = '\n'.join(cleaned).strip()
        return result

    markdown_content = f"# {title}\n\n"
    markdown_content += f"**Ученик:** {student.name}\n"
    if lesson.lesson_date:
        markdown_content += f"**Дата урока:** {lesson.lesson_date.strftime('%d.%m.%Y')}\n"
    if lesson.topic:
        markdown_content += f"**Тема:** {lesson.topic}\n"
    markdown_content += f"\n---\n\n"

    for idx, hw_task in enumerate(tasks):
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
        if idx < len(tasks) - 1:
            markdown_content += "---\n\n"

    return render_template('markdown_export.html', markdown_content=markdown_content, lesson=lesson, student=student)

@app.route('/lesson/<int:lesson_id>/homework-export-md')
def lesson_homework_export_md(lesson_id):
    """Экспорт домашнего задания"""
    return lesson_export_md(lesson_id, 'homework')

@app.route('/lesson/<int:lesson_id>/classwork-export-md')
def lesson_classwork_export_md(lesson_id):
    """Экспорт классной работы"""
    return lesson_export_md(lesson_id, 'classwork')

@app.route('/lesson/<int:lesson_id>/exam-export-md')
def lesson_exam_export_md(lesson_id):
    """Экспорт проверочной работы"""
    return lesson_export_md(lesson_id, 'exam')

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

        school_class_value = normalize_school_class(data.get('school_class'))  # Приводим класс из API к допустимому значению
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None  # Забираем текстовую цель из API
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None  # Забираем язык программирования из API
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
            category=data.get('category') if data.get('category') else None,
            school_class=school_class_value,  # Сохраняем класс, переданный через API
            goal_text=goal_text_value,  # Сохраняем текстовую цель, полученную через API
            programming_language=programming_language_value  # Сохраняем язык программирования
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
                'category': student.category,
                'school_class': student.school_class,  # Возвращаем текущий класс в ответе API
                'goal_text': student.goal_text,  # Возвращаем текстовую цель
                'programming_language': student.programming_language  # Возвращаем язык программирования
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

        school_class_value = normalize_school_class(data.get('school_class'))  # Приводим значение класса к корректному виду
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None  # Забираем текстовую цель из API
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None  # Забираем язык программирования из API
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
        student.school_class = school_class_value  # Сохраняем обновленный класс
        student.goal_text = goal_text_value  # Сохраняем текстовую цель
        student.programming_language = programming_language_value  # Сохраняем язык программирования

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Данные ученика {student.name} обновлены!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category,
                'school_class': student.school_class,  # Возвращаем обновленный класс
                'goal_text': student.goal_text,  # Возвращаем текстовую цель
                'programming_language': student.programming_language  # Возвращаем язык программирования
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

@app.route('/api/global-search', methods=['GET'])
def api_global_search():
    """Глобальный поиск по всем сущностям: ученики, уроки, задания"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({
            'success': False,
            'error': 'Минимум 2 символа для поиска'
        }), 400
    
    results = {
        'students': [],
        'lessons': [],
        'tasks': []
    }
    
    try:
        # Поиск по ученикам
        search_pattern = f'%{query}%'
        students = Student.query.filter(
            or_(
                Student.name.ilike(search_pattern),
                Student.platform_id.ilike(search_pattern),
                Student.category.ilike(search_pattern)
            )
        ).limit(10).all()
        
        for student in students:
            results['students'].append({
                'id': student.student_id,
                'name': student.name,
                'category': student.category,
                'platform_id': student.platform_id,
                'is_active': student.is_active,
                'url': url_for('student_profile', student_id=student.student_id)
            })
        
        # Поиск по урокам
        try:
            lesson_id = int(query)
            lessons = Lesson.query.filter(Lesson.lesson_id == lesson_id).limit(5).all()
        except ValueError:
            lessons = Lesson.query.filter(
                or_(
                    Lesson.topic.ilike(search_pattern),
                    Lesson.notes.ilike(search_pattern),
                    Lesson.homework.ilike(search_pattern)
                )
            ).limit(5).all()
        
        for lesson in lessons:
            results['lessons'].append({
                'id': lesson.lesson_id,
                'student_name': lesson.student.name if lesson.student else 'Неизвестно',
                'student_id': lesson.student_id,
                'topic': lesson.topic,
                'date': lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else None,
                'status': lesson.status,
                'url': url_for('lesson_edit', lesson_id=lesson.lesson_id)
            })
        
        # Поиск по заданиям
        try:
            task_id = int(query)
            tasks = Tasks.query.filter(
                or_(
                    Tasks.task_id == task_id,
                    Tasks.site_task_id == task_id
                )
            ).limit(5).all()
        except ValueError:
            tasks = Tasks.query.filter(
                Tasks.content_html.ilike(search_pattern)
            ).limit(5).all()
        
        for task in tasks:
            results['tasks'].append({
                'id': task.task_id,
                'site_task_id': task.site_task_id,
                'task_number': task.task_number,
                'content_preview': task.content_html[:200] + '...' if task.content_html and len(task.content_html) > 200 else (task.content_html or ''),
                'url': url_for('generate_results', task_id=task.task_id)
            })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results['students']) + len(results['lessons']) + len(results['tasks'])
        })
    
    except Exception as e:
        logger.error(f"Ошибка при глобальном поиске: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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

        lesson_type = data.get('lesson_type', 'regular')
        homework_status_value = normalize_homework_status_value(data.get('homework_status'))
        homework_value = data.get('homework')
        if lesson_type == 'introductory':
            homework_value = ''
            homework_status_value = 'not_assigned'

        lesson = Lesson(
            student_id=int(data.get('student_id')),
            lesson_type=lesson_type,
            lesson_date=lesson_date,
            duration=int(data.get('duration', 60)),
            status=data.get('status', 'planned'),
            topic=data.get('topic'),
            notes=data.get('notes'),
            homework=homework_value,
            homework_status=homework_status_value
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
                'grade': f"{lesson.student.school_class} класс" if lesson.student.school_class else (lesson.student.category or 'Не указано'),  # Отображаем класс, а при его отсутствии категорию
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
    categories = ['ЕГЭ', 'ОГЭ', 'ЛЕВЕЛАП', 'ПРОГРАММИРОВАНИЕ']  # Добавляем новую категорию для расписания

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
    # Получаем lesson_id из query-параметров, если не передан в пути
    if lesson_id is None:
        lesson_id = request.args.get('lesson_id', type=int)
    assignment_type = request.args.get('assignment_type') or request.form.get('assignment_type') or 'homework'
    # Поддерживаем 'exam' тип задания
    assignment_type = assignment_type if assignment_type in ['homework', 'classwork', 'exam'] else 'homework'
    if not lesson_id and assignment_type == 'classwork':
        assignment_type = 'homework'
    if lesson_id:
        lesson = Lesson.query.get_or_404(lesson_id)
        student = lesson.student

    selection_form = TaskSelectionForm()
    reset_form = ResetForm()
    search_form = TaskSearchForm()

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
    
    # Обработчик поиска задания по уникальному ID
    if search_form.search_submit.data and search_form.validate_on_submit():
        task_id_str = search_form.task_id.data.strip()
        try:
            # Пытаемся найти задание по уникальному ID
            # ВАЖНО: пользователь ищет по site_task_id (ID с сайта, который он видит на странице)
            # Поэтому сначала ищем по site_task_id, а не по внутреннему task_id
            task_id_int = int(task_id_str)
            logger.info(f"Поиск задания с ID: {task_id_str} (пользователь ищет по site_task_id)")
            
            # Ищем СНАЧАЛА по site_task_id (ID с сайта, например 2565, 16330)
            # site_task_id хранится как Text, поэтому ищем по строке
            # ВАЖНО: пользователь видит на сайте site_task_id, поэтому ищем именно по нему
            logger.info(f"Поиск по site_task_id='{task_id_str}' (тип: {type(task_id_str).__name__})")
            task = Tasks.query.filter(Tasks.site_task_id == task_id_str).first()
            found_by_site_task_id = bool(task)
            
            # Для отладки: проверяем, есть ли вообще задания с похожим site_task_id
            if not task:
                sample = Tasks.query.filter(Tasks.site_task_id.isnot(None)).limit(5).all()
                sample_site_ids = [str(t.site_task_id) for t in sample if t.site_task_id]
                logger.info(f"Задание с site_task_id='{task_id_str}' не найдено. Примеры site_task_id в базе: {sample_site_ids}")
            
            # Если не найдено по site_task_id, ищем по task_id (внутренний ID базы данных)
            if not task:
                logger.info(f"Не найдено по site_task_id={task_id_str}, ищу по task_id (внутренний ID): {task_id_int}")
                task = Tasks.query.filter_by(task_id=task_id_int).first()
                if task:
                    logger.info(f"Задание найдено по task_id: task_id={task.task_id}, site_task_id={task.site_task_id}, task_number={task.task_number}")
                else:
                    logger.warning(f"Задание не найдено ни по site_task_id={task_id_str}, ни по task_id={task_id_int}")
            else:
                logger.info(f"Задание найдено по site_task_id: task_id={task.task_id}, site_task_id={task.site_task_id}, task_number={task.task_number}")
            
            if task:
                # Проверяем, что найденное задание соответствует запросу
                found_by_task_id = (task.task_id == task_id_int)
                # found_by_site_task_id уже определен выше
                
                logger.info(f"Задание найдено: task_id={task.task_id}, site_task_id={task.site_task_id}, task_number={task.task_number}")
                logger.info(f"Найдено по site_task_id: {found_by_site_task_id}, найдено по task_id: {found_by_task_id}")
                
                # ВАЖНО: если пользователь искал по site_task_id, но нашли по task_id - это может быть не то задание!
                if not found_by_site_task_id and found_by_task_id:
                    logger.warning(f"ВНИМАНИЕ: Пользователь искал site_task_id={task_id_str}, но найдено задание с site_task_id={task.site_task_id} по внутреннему task_id={task_id_int}")
                    flash(f'Найдено задание по внутреннему ID {task_id_int}, но его site_task_id={task.site_task_id}, а не {task_id_str}. Возможно, вы искали другое задание.', 'warning')
                
                # Если задание найдено, добавляем его в результаты
                audit_logger.log(
                    action='search_and_add_task',
                    entity='Task',
                    entity_id=task.task_id,
                    status='success',
                    metadata={
                        'search_id': task_id_str,
                        'found_task_id': task.task_id,
                        'site_task_id': task.site_task_id,
                        'task_number': task.task_number,
                        'found_by_task_id': found_by_task_id,
                        'found_by_site_task_id': found_by_site_task_id,
                        'lesson_id': lesson_id,
                        'assignment_type': assignment_type
                    }
                )
                # Перенаправляем на страницу результатов с найденным заданием
                # Используем task_number найденного задания для корректного отображения
                # ВАЖНО: передаем task.task_id (внутренний ID), а не site_task_id
                redirect_url_params = {
                    'task_type': task.task_number,
                    'limit_count': 1,
                    'use_skipped': False,
                    'assignment_type': assignment_type,
                    'search_task_id': task.task_id  # ВАЖНО: передаем внутренний task_id
                }
                if lesson_id:
                    redirect_url_params['lesson_id'] = lesson_id
                
                logger.info(f"Перенаправление на результаты с параметрами: {redirect_url_params}")
                return redirect(url_for('generate_results', **redirect_url_params))
            else:
                logger.warning(f"Задание с ID {task_id_int} не найдено ни по task_id, ни по site_task_id")
                
                # Показываем примеры существующих ID для помощи пользователю
                sample_tasks = Tasks.query.order_by(Tasks.task_id).limit(5).all()
                sample_ids = [str(t.task_id) for t in sample_tasks] if sample_tasks else []
                
                # Показываем примеры site_task_id
                sample_site_ids = Tasks.query.filter(Tasks.site_task_id.isnot(None)).limit(5).all()
                sample_site_task_ids = [str(t.site_task_id) for t in sample_site_ids if t.site_task_id] if sample_site_ids else []
                
                # Также проверяем общее количество заданий в базе
                total_count = Tasks.query.count()
                logger.info(f"Всего заданий в базе: {total_count}")
                
                error_msg = f'Задание с ID {task_id_str} не найдено в базе данных.'
                if sample_ids:
                    error_msg += f' Примеры внутренних ID (task_id): {", ".join(sample_ids)}'
                if sample_site_task_ids:
                    error_msg += f' Примеры ID с сайта (site_task_id): {", ".join(sample_site_task_ids)}'
                if total_count > 0:
                    error_msg += f' (всего заданий в базе: {total_count})'
                flash(error_msg, 'warning')
        except ValueError:
            flash('Некорректный ID задания. Введите число (например, 23715, 3348).', 'danger')
        except Exception as e:
            logger.error(f"Ошибка при поиске задания {task_id_str}: {e}", exc_info=True)
            flash(f'Ошибка при поиске задания: {str(e)}', 'danger')
            audit_logger.log(
                action='search_and_add_task',
                entity='Task',
                entity_id=None,
                status='error',
                metadata={
                    'task_id': task_id_str,
                    'error': str(e)
                }
            )
    
    return render_template('kege_generator.html',
                           selection_form=selection_form,
                           reset_form=reset_form,
                           search_form=search_form,
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
        search_task_id = request.args.get('search_task_id', type=int)  # ID конкретного задания для поиска (внутренний task_id)
        
        # Логируем все параметры для отладки
        logger.info(f"generate_results вызван с параметрами: task_type={task_type}, limit_count={limit_count}, search_task_id={search_task_id}, lesson_id={lesson_id}")
    except Exception as e:
        logger.error(f"Ошибка при получении параметров запроса: {e}", exc_info=True)
        flash('Неверные параметры запроса.', 'danger')
        if lesson_id:
            return redirect(url_for('kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator', assignment_type=assignment_type))

    lesson = None
    student = None
    student_id = None
    if lesson_id:
        try:
            lesson = Lesson.query.get_or_404(lesson_id)
            if lesson:
                student = lesson.student
                if student:
                    student_id = student.student_id
        except Exception as e:
            logger.error(f"Error getting lesson {lesson_id}: {e}")
            flash('Ошибка при получении урока', 'error')
            return redirect(url_for('kege_generator', assignment_type=assignment_type))

    try:
        # Если передан search_task_id, получаем конкретное задание и ИГНОРИРУЕМ остальные параметры
        if search_task_id:
            # Убираем избыточное логирование для оптимизации
            # Используем filter_by для надежного поиска по внутреннему task_id
            task = Tasks.query.filter_by(task_id=search_task_id).first()
            if task:
                tasks = [task]  # Возвращаем ТОЛЬКО найденное задание
                # Обновляем task_type на правильный номер типа найденного задания
                task_type = task.task_number
            else:
                logger.error(f"✗ Задание с search_task_id={search_task_id} не найдено в базе данных!")
                flash(f'Задание с ID {search_task_id} не найдено.', 'warning')
                # Если задание не найдено, не генерируем случайные - просто возвращаем пустой список
                tasks = []
        else:
            # Обычная генерация заданий - убираем избыточное логирование
            tasks = get_unique_tasks(task_type, limit_count, use_skipped=use_skipped, student_id=student_id)
    except Exception as e:
        logger.error(f"Error getting unique tasks: {e}", exc_info=True)
        flash(f'Ошибка при генерации заданий: {str(e)}', 'error')
        if lesson_id:
            return redirect(url_for('kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator', assignment_type=assignment_type))
    
    # Логируем генерацию заданий
    try:
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
                'student_name': student.name if student and hasattr(student, 'name') else None
            }
        )
    except Exception as e:
        logger.error(f"Error logging task generation: {e}", exc_info=True)

    if not tasks:
        if use_skipped:
            flash(f'Задания типа {task_type} закончились! Все доступные задания (включая пропущенные) были использованы.', 'warning')
        else:
            flash(f'Задания типа {task_type} закончились! Попробуйте включить пропущенные задания или сбросьте историю.', 'warning')
        return redirect(url_for('kege_generator'))

    # Финальная проверка: если был передан search_task_id, убеждаемся, что вернули правильное задание
    if search_task_id:
        task_ids_in_results = [t.task_id for t in tasks]
        if search_task_id not in task_ids_in_results:
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Запрошено задание с search_task_id={search_task_id}, но в результатах: {task_ids_in_results}")
            flash(f'Ошибка: запрошено задание {search_task_id}, но получено другое задание.', 'error')
        else:
            logger.info(f"✓ Подтверждение: в результатах присутствует запрошенное задание search_task_id={search_task_id}")
            # Показываем информацию о найденном задании
            found_task = next((t for t in tasks if t.task_id == search_task_id), None)
            if found_task:
                logger.info(f"✓ Найденное задание: task_id={found_task.task_id}, site_task_id={found_task.site_task_id}, task_number={found_task.task_number}")

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
        assignment_type = assignment_type if assignment_type in ['homework', 'classwork', 'exam'] else 'homework'

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
                    lesson.homework_status = 'assigned_not_done' if lesson.lesson_type != 'introductory' else 'not_assigned'
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
            'students': [{'name': s.name, 'platform_id': s.platform_id, 'category': s.category, 'target_score': s.target_score, 'deadline': s.deadline, 'diagnostic_level': s.diagnostic_level, 'description': s.description, 'notes': s.notes, 'strengths': s.strengths, 'weaknesses': s.weaknesses, 'preferences': s.preferences, 'overall_rating': s.overall_rating, 'school_class': s.school_class, 'goal_text': s.goal_text, 'programming_language': s.programming_language} for s in Student.query.filter_by(is_active=True).all()],  # Добавляем данные по целям и языкам в экспорт
            'lessons': [{'student_id': l.student_id, 'lesson_type': l.lesson_type, 'lesson_date': l.lesson_date.isoformat() if l.lesson_date else None, 'duration': l.duration, 'status': l.status, 'topic': l.topic, 'notes': l.notes, 'homework': l.homework, 'homework_status': l.homework_status, 'homework_result_percent': l.homework_result_percent, 'homework_result_notes': l.homework_result_notes} for l in Lesson.query.all()]
        }
        response = make_response(json.dumps(export_data, ensure_ascii=False, indent=2))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        logger.info(f'Экспорт завершен: {len(export_data["students"])} учеников, {len(export_data["lessons"])} уроков')
        
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
                    student = Student(name=student_data.get('name'), platform_id=student_data.get('platform_id'), category=student_data.get('category'), target_score=student_data.get('target_score'), deadline=student_data.get('deadline'), diagnostic_level=student_data.get('diagnostic_level'), description=student_data.get('description'), notes=student_data.get('notes'), strengths=student_data.get('strengths'), weaknesses=student_data.get('weaknesses'), preferences=student_data.get('preferences'), overall_rating=student_data.get('overall_rating'), school_class=normalize_school_class(student_data.get('school_class')), goal_text=student_data.get('goal_text'), programming_language=student_data.get('programming_language'), is_active=True)  # Поддерживаем импорт класса, целей и языков
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
                    lesson = Lesson(student_id=lesson_data.get('student_id'), lesson_type=imported_type, lesson_date=datetime.fromisoformat(lesson_data['lesson_date']) if lesson_data.get('lesson_date') else moscow_now(), duration=lesson_data.get('duration', 60), status=lesson_data.get('status', 'planned'), topic=lesson_data.get('topic'), notes=lesson_data.get('notes'), homework=imported_homework, homework_status=imported_homework_status, homework_result_percent=lesson_data.get('homework_result_percent'), homework_result_notes=lesson_data.get('homework_result_notes'))
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

@app.route('/admin-audit')
@login_required
def admin_audit():
    """Журнал аудита (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))

    try:
        from core.db_models import AuditLog, User
        from sqlalchemy import func, and_
        from sqlalchemy.exc import OperationalError, ProgrammingError
        
        # Проверяем, существует ли таблица AuditLog
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()  # Откатываем транзакцию после ошибки
            audit_log_exists = False
        
        if not audit_log_exists:
            # Если таблицы нет, возвращаем пустую страницу
            from core.db_models import User
            users = User.query.order_by(User.id).all()
            return render_template('admin_audit.html',
                                 logs=[],
                                 pagination=None,
                                 stats={
                                     'total_events': 0,
                                     'total_testers': 0,
                                     'error_count': 0,
                                     'today_events': 0
                                 },
                                 filters={},
                                 actions=[],
                                 entities=[],
                                 users=users)

        user_id = request.args.get('user_id', '')
        action = request.args.get('action', '')
        entity = request.args.get('entity', '')
        status = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        # Логируем только действия авторизованных пользователей
        query = AuditLog.query.filter(AuditLog.user_id.isnot(None))

        if user_id:
            try:
                user_id_int = int(user_id)
                query = query.filter(AuditLog.user_id == user_id_int)
            except:
                pass
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

        # Получаем статистику с обработкой ошибок
        try:
            total_events = AuditLog.query.filter(AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting total_events: {e}")
            db.session.rollback()
            total_events = 0
        
        total_testers = User.query.count()  # Количество авторизованных пользователей
        
        try:
            error_count = AuditLog.query.filter(AuditLog.status == 'error', AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting error_count: {e}")
            db.session.rollback()
            error_count = 0

        from datetime import datetime, timedelta
        today_start = datetime.now(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            today_events = AuditLog.query.filter(AuditLog.timestamp >= today_start, AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting today_events: {e}")
            db.session.rollback()
            today_events = 0

        try:
            actions = db.session.query(AuditLog.action).filter(AuditLog.user_id.isnot(None)).distinct().order_by(AuditLog.action).all()
            actions = [a[0] for a in actions if a[0]]
        except Exception as e:
            logger.warning(f"Error getting actions: {e}")
            db.session.rollback()
            actions = []
        
        try:
            entities = db.session.query(AuditLog.entity).filter(AuditLog.user_id.isnot(None)).distinct().order_by(AuditLog.entity).all()
            entities = [e[0] for e in entities if e[0]]
        except Exception as e:
            logger.warning(f"Error getting entities: {e}")
            db.session.rollback()
            entities = []
        
        users = User.query.order_by(User.id).all()  # Все авторизованные пользователи

        page = request.args.get('page', 1, type=int)
        per_page = 50
        try:
            pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
            logs = pagination.items
        except Exception as e:
            logger.warning(f"Error getting pagination: {e}")
            db.session.rollback()
            logs = []
            pagination = None

        filters = {
            'user_id': user_id,
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
                                 'total_testers': 0,  # Устаревшее поле, оставляем 0
                                 'error_count': error_count,
                                 'today_events': today_events
                             },
                             filters=filters,
                             actions=actions,
                             entities=entities,
                             users=users)  # Передаем users вместо testers
    except Exception as e:
        logger.error(f"Error in admin_audit route: {e}", exc_info=True)
        db.session.rollback()  # Откатываем транзакцию после ошибки
        flash(f'Ошибка при загрузке журнала аудита: {str(e)}', 'error')
        # Fallback: возвращаем пустую страницу
        try:
            from core.db_models import User
            users = User.query.order_by(User.id).all()
            return render_template('admin_audit.html',
                                 logs=[],
                                 pagination=None,
                                 stats={
                                     'total_events': 0,
                                     'total_testers': 0,
                                     'error_count': 0,
                                     'today_events': 0
                                 },
                                 filters={},
                                 actions=[],
                                 entities=[],
                                 users=users)
        except Exception as e2:
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            db.session.rollback()  # Откатываем транзакцию после ошибки в fallback
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('admin_panel'))

@app.route('/admin-testers')
@login_required
def admin_testers():
    """Управление пользователями (только для создателя)"""
    logger.info(f"admin_testers route called by user: {current_user.username if current_user.is_authenticated else 'anonymous'}")
    
    if not current_user.is_creator():
        logger.warning(f"Access denied to admin_testers for user: {current_user.username if current_user.is_authenticated else 'anonymous'}")
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        logger.info("Starting admin_testers query")
        from core.db_models import User, AuditLog
        from sqlalchemy import func
        from sqlalchemy.exc import OperationalError, ProgrammingError
        
        # Проверяем, существует ли таблица AuditLog
        try:
            # Пробуем выполнить простой запрос к таблице AuditLog
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            # Если таблицы нет, работаем без неё
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()  # Откатываем транзакцию после ошибки
            audit_log_exists = False
        
        if audit_log_exists:
            # Получаем всех авторизованных пользователей с статистикой
            try:
                users = db.session.query(
                    User,
                    func.count(AuditLog.id).label('logs_count'),
                    func.max(AuditLog.timestamp).label('last_action')
                ).outerjoin(
                    AuditLog, User.id == AuditLog.user_id
                ).group_by(
                    User.id
                ).order_by(
                    User.id.desc()
                ).all()
            except Exception as e:
                logger.error(f"Error querying users with AuditLog: {e}", exc_info=True)
                db.session.rollback()  # Откатываем транзакцию после ошибки
                # Fallback: получаем пользователей без статистики
                users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
        else:
            # Если таблицы AuditLog нет, получаем только пользователей
            users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
        
        logger.info(f"admin_testers: found {len(users)} users, rendering template")
        return render_template('admin_testers.html', users=users)
    except Exception as e:
        logger.error(f"Error in admin_testers route: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()  # Откатываем транзакцию после ошибки
        flash(f'Ошибка при загрузке данных: {str(e)}', 'error')
        # Fallback: возвращаем пустой список пользователей
        try:
            from core.db_models import User
            users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
            return render_template('admin_testers.html', users=users)
        except Exception as e2:
            db.session.rollback()  # Откатываем транзакцию после ошибки в fallback
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('admin_panel'))

@app.route('/admin-testers/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_testers_edit(user_id):
    """Редактирование пользователя (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))
    
    from core.db_models import User
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        new_role = request.form.get('role', 'tester')
        
        if not new_username:
            flash('Имя пользователя не может быть пустым', 'error')
            return redirect(url_for('admin_testers_edit', user_id=user_id))
        
        old_username = user.username
        old_role = user.role
        
        # Проверяем, что не меняем роль создателя
        if user.is_creator() and new_role != 'creator':
            flash('Нельзя изменить роль создателя', 'error')
            return redirect(url_for('admin_testers_edit', user_id=user_id))
        
        user.username = new_username
        user.role = new_role
        db.session.commit()
        
        # Логируем изменение
        audit_logger.log(
            action='edit_user',
            entity='User',
            entity_id=user_id,
            status='success',
            metadata={
                'old_username': old_username,
                'new_username': new_username,
                'old_role': old_role,
                'new_role': new_role
            }
        )
        
        flash(f'Пользователь "{new_username}" обновлен', 'success')
        return redirect(url_for('admin_testers'))
    
    return render_template('admin_testers_edit.html', user=user)

@app.route('/admin-testers/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_testers_delete(user_id):
    """Удаление пользователя (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))
    
    from core.db_models import User, AuditLog
    from sqlalchemy import delete
    
    user = User.query.get_or_404(user_id)
    
    # Нельзя удалить создателя
    if user.is_creator():
        flash('Нельзя удалить создателя', 'error')
        return redirect(url_for('admin_testers'))
    
    username = user.username
    
    try:
        # Удаляем все логи пользователя
        try:
            deleted_logs = db.session.execute(
                delete(AuditLog).where(AuditLog.user_id == user_id)
            ).rowcount
        except Exception as e:
            logger.warning(f"Error deleting user logs: {e}")
            db.session.rollback()
            deleted_logs = 0
        
        # Удаляем пользователя
        db.session.delete(user)
        db.session.commit()
        
        # Логируем удаление
        audit_logger.log(
            action='delete_user',
            entity='User',
            entity_id=user_id,
            status='success',
            metadata={
                'username': username,
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Пользователь "{username}" и {deleted_logs} его логов удалены', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении пользователя: {e}')
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    
    return redirect(url_for('admin_testers'))

@app.route('/admin-testers/clear-all', methods=['POST'])
@login_required
def admin_testers_clear_all():
    """Очистить все логи пользователей (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('dashboard'))
    
    from core.db_models import AuditLog
    from sqlalchemy import delete
    
    try:
        try:
            logs_count = AuditLog.query.filter(AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting logs_count: {e}")
            db.session.rollback()
            logs_count = 0
        
        if logs_count == 0:
            flash('Нет логов для очистки', 'info')
            return redirect(url_for('admin_testers'))
        
        # Удаляем все логи авторизованных пользователей
        try:
            deleted_logs = db.session.execute(
                delete(AuditLog).where(AuditLog.user_id.isnot(None))
            ).rowcount
            db.session.commit()
        except Exception as e:
            logger.error(f"Error deleting logs: {e}")
            db.session.rollback()
            raise
        
        # Логируем очистку
        audit_logger.log(
            action='clear_all_user_logs',
            entity='AuditLog',
            entity_id=None,
            status='success',
            metadata={
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Удалено {deleted_logs} логов пользователей', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при очистке логов: {e}')
        flash(f'Ошибка при очистке: {str(e)}', 'error')
    
    return redirect(url_for('admin_testers'))

@app.route('/admin-audit/export')
def admin_audit_export():

    check_admin_access()

    from core.db_models import AuditLog
    from sqlalchemy.exc import OperationalError, ProgrammingError
    import csv
    from io import StringIO

    try:
        # Проверяем, существует ли таблица AuditLog
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        if not audit_log_exists:
            flash('Таблица AuditLog недоступна', 'error')
            return redirect(url_for('admin_audit'))
        
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
    except Exception as e:
        logger.error(f"Error in admin_audit_export: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Ошибка при экспорте: {str(e)}', 'error')
        return redirect(url_for('admin_audit'))

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
        from sqlalchemy.exc import OperationalError, ProgrammingError
        
        # Проверяем, существует ли таблица AuditLog
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            print("Таблица AuditLog недоступна")
            return

        week_ago = datetime.now(MOSCOW_TZ) - timedelta(days=7)

        try:
            old_logs = AuditLog.query.filter(AuditLog.timestamp < week_ago).all()
            count = len(old_logs)
        except Exception as e:
            logger.error(f"Error querying old logs: {e}")
            db.session.rollback()
            print(f"Ошибка при запросе логов: {e}")
            return

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
        from sqlalchemy.exc import OperationalError, ProgrammingError
        from sqlalchemy import delete
        
        # Проверяем, существуют ли таблицы
        try:
            db.session.query(Tester).limit(1).all()
            testers_table_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"Tester table not found: {e}")
            db.session.rollback()
            testers_table_exists = False
        
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        # Подсчитываем количество записей перед удалением
        testers_count = 0
        logs_count = 0
        
        if testers_table_exists:
            try:
                testers_count = Tester.query.count()
            except Exception as e:
                logger.warning(f"Error counting testers: {e}")
                db.session.rollback()
        
        if audit_log_exists:
            try:
                logs_count = AuditLog.query.count()
            except Exception as e:
                logger.warning(f"Error counting logs: {e}")
                db.session.rollback()
        
        if testers_count == 0 and logs_count == 0:
            print("Нет данных тестировщиков для очистки")
            return
        
        # Удаляем все логи (сначала, чтобы не было проблем с foreign key)
        deleted_logs = 0
        if audit_log_exists:
            try:
                deleted_logs = db.session.execute(delete(AuditLog)).rowcount
            except Exception as e:
                logger.warning(f"Error deleting logs: {e}")
                db.session.rollback()
        
        # Удаляем всех тестировщиков
        deleted_testers = 0
        if testers_table_exists:
            try:
                deleted_testers = db.session.execute(delete(Tester)).rowcount
            except Exception as e:
                logger.warning(f"Error deleting testers: {e}")
                db.session.rollback()
        
        db.session.commit()
        
        # Проверяем, что действительно удалилось
        remaining_testers = 0
        remaining_logs = 0
        
        if testers_table_exists:
            try:
                remaining_testers = Tester.query.count()
            except Exception as e:
                logger.warning(f"Error counting remaining testers: {e}")
                db.session.rollback()
        
        if audit_log_exists:
            try:
                remaining_logs = AuditLog.query.count()
            except Exception as e:
                logger.warning(f"Error counting remaining logs: {e}")
                db.session.rollback()
        
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

# ==================== БИБЛИОТЕКА ШАБЛОНОВ ====================

@app.route('/templates')
@login_required
def templates_list():
    """Список всех шаблонов с фильтрацией по типу"""
    template_type = request.args.get('type', '')  # homework, classwork, exam, lesson
    category = request.args.get('category', '')  # ЕГЭ, ОГЭ, ЛЕВЕЛАП, ПРОГРАММИРОВАНИЕ
    
    query = TaskTemplate.query.filter_by(is_active=True)
    
    if template_type:
        query = query.filter_by(template_type=template_type)
    if category:
        query = query.filter_by(category=category)
    
    templates = query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).order_by(TaskTemplate.created_at.desc()).all()
    
    # Группируем по типам для отображения
    templates_by_type = {
        'homework': [],
        'classwork': [],
        'exam': [],
        'lesson': []
    }
    
    for template in templates:
        templates_by_type[template.template_type].append(template)
    
    return render_template('templates_list.html',
                         templates=templates,
                         templates_by_type=templates_by_type,
                         current_type=template_type,
                         current_category=category)

@app.route('/templates/new', methods=['GET', 'POST'])
@login_required
def template_new():
    """Создание нового шаблона"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            name = data.get('name', '').strip()
            if not name:
                return jsonify({'success': False, 'error': 'Название шаблона обязательно'}), 400
            
            template = TaskTemplate(
                name=name,
                description=data.get('description', '').strip() or None,
                template_type=data.get('template_type', 'homework'),
                category=data.get('category') or None,
                created_by=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(template)
            db.session.flush()  # Получаем template_id
            
            # Добавляем задания в шаблон
            task_ids = data.get('task_ids', [])
            for order, task_id in enumerate(task_ids):
                template_task = TemplateTask(
                    template_id=template.template_id,
                    task_id=task_id,
                    order=order
                )
                db.session.add(template_task)
            
            db.session.commit()
            
            audit_logger.log(
                action='create_template',
                entity='TaskTemplate',
                entity_id=template.template_id,
                status='success',
                metadata={
                    'name': name,
                    'template_type': template.template_type,
                    'task_count': len(task_ids)
                }
            )
            
            if request.is_json:
                return jsonify({'success': True, 'template_id': template.template_id})
            flash('Шаблон успешно создан', 'success')
            return redirect(url_for('templates_list'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при создании шаблона: {e}", exc_info=True)
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f'Ошибка при создании шаблона: {e}', 'error')
            return redirect(url_for('templates_list'))
    
    # GET запрос - показываем форму создания
    return render_template('template_form.html', template=None, is_new=True)

@app.route('/templates/<int:template_id>')
@login_required
def template_view(template_id):
    """Просмотр шаблона"""
    template = TaskTemplate.query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).get_or_404(template_id)
    
    # Сортируем задания по порядку
    template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
    
    return render_template('template_view.html',
                         template=template,
                         template_tasks=template_tasks)

@app.route('/templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
def template_edit(template_id):
    """Редактирование шаблона"""
    template = TaskTemplate.query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).get_or_404(template_id)
    
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            template.name = data.get('name', template.name).strip()
            template.description = data.get('description', '').strip() or None
            template.template_type = data.get('template_type', template.template_type)
            template.category = data.get('category') or None
            template.updated_at = moscow_now()
            
            # Обновляем задания
            task_ids = data.get('task_ids', [])
            
            # Удаляем старые задания
            TemplateTask.query.filter_by(template_id=template_id).delete()
            
            # Добавляем новые задания
            for order, task_id in enumerate(task_ids):
                template_task = TemplateTask(
                    template_id=template_id,
                    task_id=task_id,
                    order=order
                )
                db.session.add(template_task)
            
            db.session.commit()
            
            audit_logger.log(
                action='edit_template',
                entity='TaskTemplate',
                entity_id=template_id,
                status='success',
                metadata={'name': template.name}
            )
            
            if request.is_json:
                return jsonify({'success': True})
            flash('Шаблон успешно обновлен', 'success')
            return redirect(url_for('template_view', template_id=template_id))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при редактировании шаблона: {e}", exc_info=True)
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f'Ошибка при редактировании шаблона: {e}', 'error')
            return redirect(url_for('template_edit', template_id=template_id))
    
    # GET запрос - показываем форму редактирования
    template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
    return render_template('template_form.html',
                         template=template,
                         template_tasks=template_tasks,
                         is_new=False)

@app.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
def template_delete(template_id):
    """Удаление шаблона (мягкое удаление - is_active=False)"""
    template = TaskTemplate.query.get_or_404(template_id)
    
    template.is_active = False
    template.updated_at = moscow_now()
    db.session.commit()
    
    audit_logger.log(
        action='delete_template',
        entity='TaskTemplate',
        entity_id=template_id,
        status='success',
        metadata={'name': template.name}
    )
    
    flash('Шаблон удален', 'success')
    return redirect(url_for('templates_list'))

@app.route('/templates/<int:template_id>/apply', methods=['POST'])
@login_required
def template_apply(template_id):
    """Применение шаблона к уроку"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        lesson_id = data.get('lesson_id')
        
        if not lesson_id:
            return jsonify({'success': False, 'error': 'ID урока обязателен'}), 400
        
        lesson = Lesson.query.get_or_404(lesson_id)
        template = TaskTemplate.query.options(
            db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
        ).get_or_404(template_id)
        
        # Получаем задания из шаблона в правильном порядке
        template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
        assignment_type = template.template_type  # homework, classwork, exam
        
        # Применяем задания к уроку
        applied_count = 0
        skipped_count = 0
        
        for template_task in template_tasks:
            # Проверяем, не добавлено ли уже это задание
            existing = LessonTask.query.filter_by(
                lesson_id=lesson_id,
                task_id=template_task.task_id
            ).first()
            
            if not existing:
                lesson_task = LessonTask(
                    lesson_id=lesson_id,
                    task_id=template_task.task_id,
                    assignment_type=assignment_type
                )
                db.session.add(lesson_task)
                applied_count += 1
                
                # Автоматически помечаем задание как использованное для этого ученика
                # Создаем запись в UsageHistory
                usage = UsageHistory(
                    task_fk=template_task.task_id,
                    session_tag=f"student_{lesson.student_id}"
                )
                db.session.add(usage)
            else:
                skipped_count += 1
        
        # Обновляем статус ДЗ урока
        if assignment_type == 'homework':
            if lesson.lesson_type != 'introductory':
                lesson.homework_status = 'assigned_not_done'
        elif assignment_type == 'classwork':
            # Для классной работы статус не меняем
            pass
        elif assignment_type == 'exam':
            # Для проверочной работы статус не меняем
            pass
        
        db.session.commit()
        
        audit_logger.log(
            action='apply_template',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'template_id': template_id,
                'template_name': template.name,
                'assignment_type': assignment_type,
                'applied_count': applied_count,
                'skipped_count': skipped_count,
                'student_id': lesson.student_id
            }
        )
        
        message = f'Шаблон применен: добавлено {applied_count} заданий'
        if skipped_count > 0:
            message += f', пропущено {skipped_count} (уже были добавлены)'
        
        if request.is_json:
            return jsonify({
                'success': True,
                'message': message,
                'applied_count': applied_count,
                'skipped_count': skipped_count
            })
        
        flash(message, 'success')
        return redirect(url_for('lesson_homework_view', lesson_id=lesson_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при применении шаблона: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Ошибка при применении шаблона: {e}', 'error')
        return redirect(url_for('templates_list'))

@app.route('/api/templates', methods=['GET'])
@login_required
def api_templates():
    """API для получения списка шаблонов (для выпадающих списков)"""
    template_type = request.args.get('type', '')
    category = request.args.get('category', '')
    
    query = TaskTemplate.query.filter_by(is_active=True)
    
    if template_type:
        query = query.filter_by(template_type=template_type)
    if category:
        query = query.filter_by(category=category)
    
    templates = query.order_by(TaskTemplate.name).all()
    
    return jsonify({
        'success': True,
        'templates': [{
            'id': t.template_id,
            'name': t.name,
            'description': t.description,
            'type': t.template_type,
            'category': t.category,
            'task_count': len(t.template_tasks)
        } for t in templates]
    })

if __name__ == '__main__':
    logger.info('Запуск приложения')
    app.run(debug=True, host='127.0.0.1', port=5000)
