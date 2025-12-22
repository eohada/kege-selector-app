from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import JSON, Index
import json

db = SQLAlchemy()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TOMSK_TZ = ZoneInfo("Asia/Tomsk")

def moscow_now():
    return datetime.now(MOSCOW_TZ)

class Tasks(db.Model):
    __tablename__ = 'Tasks'
    task_id = db.Column(db.Integer, primary_key=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)
    site_task_id = db.Column(db.Text, nullable=True)
    source_url = db.Column(db.Text, nullable=True)
    content_html = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    attached_files = db.Column(db.Text, nullable=True)
    last_scraped = db.Column(db.DateTime, default=moscow_now)

    usage_history = db.relationship('UsageHistory', back_populates='task', lazy=True)
    skipped_tasks = db.relationship('SkippedTasks', back_populates='task', lazy=True)
    blacklist_tasks = db.relationship('BlacklistTasks', back_populates='task', lazy=True)

class UsageHistory(db.Model):
    __tablename__ = 'UsageHistory'
    usage_id = db.Column(db.Integer, primary_key=True)
    task_fk = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    date_issued = db.Column(db.DateTime, default=moscow_now)
    session_tag = db.Column(db.Text, nullable=True)

    task = db.relationship('Tasks', back_populates='usage_history')

class SkippedTasks(db.Model):
    __tablename__ = 'SkippedTasks'
    skipped_id = db.Column(db.Integer, primary_key=True)
    task_fk = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    date_skipped = db.Column(db.DateTime, default=moscow_now)
    session_tag = db.Column(db.Text, nullable=True)

    task = db.relationship('Tasks', back_populates='skipped_tasks')

class BlacklistTasks(db.Model):
    __tablename__ = 'BlacklistTasks'
    blacklist_id = db.Column(db.Integer, primary_key=True)
    task_fk = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, unique=True)
    date_added = db.Column(db.DateTime, default=moscow_now)
    reason = db.Column(db.Text, nullable=True)

    task = db.relationship('Tasks', back_populates='blacklist_tasks')

class Student(db.Model):
    __tablename__ = 'Students'
    student_id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    telegram = db.Column(db.String(100), nullable=True)

    target_score = db.Column(db.Integer, nullable=True)
    deadline = db.Column(db.String(100), nullable=True)

    diagnostic_level = db.Column(db.String(100), nullable=True)
    preferences = db.Column(db.Text, nullable=True)
    strengths = db.Column(db.Text, nullable=True)
    weaknesses = db.Column(db.Text, nullable=True)
    overall_rating = db.Column(db.String(50), nullable=True)

    description = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    goal_text = db.Column(db.Text, nullable=True)  # Текстовая цель для программирования и ЛЕВЕЛАП
    programming_language = db.Column(db.String(100), nullable=True)  # Основной язык программирования ученика
    school_class = db.Column(db.Integer, nullable=True)  # Храним школьный класс ученика (1-11 или None)

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    is_active = db.Column(db.Boolean, default=True)

    lessons = db.relationship('Lesson', back_populates='student', lazy=True, cascade='all, delete-orphan')
    task_statistics = db.relationship('StudentTaskStatistics', back_populates='student', lazy=True, cascade='all, delete-orphan')

class StudentTaskStatistics(db.Model):
    """Ручные изменения статистики выполнения заданий для ученика"""
    __tablename__ = 'StudentTaskStatistics'
    stat_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False)
    task_number = db.Column(db.Integer, nullable=False)
    manual_correct = db.Column(db.Integer, default=0, nullable=False)  # Количество правильных, добавленных вручную
    manual_incorrect = db.Column(db.Integer, default=0, nullable=False)  # Количество неправильных, добавленных вручную
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    # Уникальный индекс для пары student_id + task_number
    __table_args__ = (Index('ix_student_task_statistics', 'student_id', 'task_number', unique=True),)
    
    student = db.relationship('Student', back_populates='task_statistics')

class Lesson(db.Model):
    __tablename__ = 'Lessons'
    lesson_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False)
    lesson_type = db.Column(db.String(50), default='regular')
    lesson_date = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, default=60)
    status = db.Column(db.String(50), default='planned')
    topic = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    homework = db.Column(db.Text, nullable=True)
    homework_status = db.Column(db.String(50), default='not_assigned')
    homework_result_percent = db.Column(db.Integer, nullable=True)
    homework_result_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    student = db.relationship('Student', back_populates='lessons')
    homework_tasks = db.relationship('LessonTask', back_populates='lesson', lazy=True, cascade='all, delete-orphan')

    @property
    def homework_assignments(self):
        return [task for task in self.homework_tasks if (task.assignment_type or 'homework') == 'homework']

    @property
    def classwork_assignments(self):
        return [task for task in self.homework_tasks if (task.assignment_type or 'homework') == 'classwork']
    
    @property
    def exam_assignments(self):
        return [task for task in self.homework_tasks if (task.assignment_type or 'homework') == 'exam']

class LessonTask(db.Model):
    __tablename__ = 'LessonTasks'
    lesson_task_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    date_assigned = db.Column(db.DateTime, default=moscow_now)
    notes = db.Column(db.Text, nullable=True)
    student_answer = db.Column(db.Text, nullable=True)
    assignment_type = db.Column(db.String(20), default='homework')
    student_submission = db.Column(db.Text, nullable=True)
    submission_correct = db.Column(db.Boolean, nullable=True)

    lesson = db.relationship('Lesson', back_populates='homework_tasks')
    task = db.relationship('Tasks')

class User(db.Model):
    """Модель пользователя для авторизации"""
    __tablename__ = 'Users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='tester', nullable=False)  # 'tester' или 'creator'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Flask-Login методы
    def get_id(self):
        return str(self.id)
    
    def is_authenticated(self):
        return True
    
    def is_anonymous(self):
        return False
    
    def is_creator(self):
        """Проверка, является ли пользователь создателем"""
        return self.role == 'creator'
    
    def get_role_display(self):
        """Возвращает отображаемое название роли"""
        role_map = {
            'tester': 'Тестировщик',
            'creator': 'Создатель'
        }
        return role_map.get(self.role, self.role)
    
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

class Tester(db.Model):

    __tablename__ = 'Testers'
    tester_id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    first_seen = db.Column(db.DateTime, default=moscow_now)
    last_seen = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    session_id = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    audit_logs = db.relationship('AuditLog', back_populates='tester', lazy=True)

    def __repr__(self):
        return f'<Tester {self.name} ({self.tester_id})>'

class AuditLog(db.Model):

    __tablename__ = 'AuditLog'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)  # Для авторизованных пользователей
    tester_id = db.Column(db.String(36), db.ForeignKey('Testers.tester_id'), nullable=True, index=True)  # Для неавторизованных (устаревшее)
    tester_name = db.Column(db.String(100), nullable=True)  # Имя пользователя или тестировщика
    action = db.Column(db.String(50), nullable=False, index=True)
    entity = db.Column(db.String(50), nullable=True, index=True)
    entity_id = db.Column(db.Integer, nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, index=True)
    meta_data = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    session_id = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    url = db.Column(db.Text, nullable=True)
    method = db.Column(db.String(10), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])  # Связь с авторизованным пользователем
    tester = db.relationship('Tester', back_populates='audit_logs')  # Связь с тестировщиком (устаревшее)

    __table_args__ = (
        Index('idx_audit_timestamp_tester', 'timestamp', 'tester_id'),
        Index('idx_audit_action_entity', 'action', 'entity'),
        Index('idx_audit_status_timestamp', 'status', 'timestamp'),
    )

    def get_metadata(self):

        if self.meta_data:
            try:
                return json.loads(self.meta_data)
            except:
                return {}
        return {}

    def set_metadata(self, data):

        self.meta_data = json.dumps(data, ensure_ascii=False) if data else None

    def __repr__(self):
        return f'<AuditLog {self.action} {self.entity} by {self.tester_name} at {self.timestamp}>'

class Reminder(db.Model):
    """Модель напоминаний"""
    __tablename__ = 'Reminders'
    reminder_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    reminder_time = db.Column(db.DateTime, nullable=True, index=True)  # Может быть None для напоминаний без времени
    is_completed = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_sent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)
    
    user = db.relationship('User', foreign_keys=[user_id])
    
    def is_overdue(self):
        """Проверяет, просрочено ли напоминание"""
        if self.is_completed or not self.reminder_time:
            return False
        return self.reminder_time < moscow_now()
    
    def __repr__(self):
        return f'<Reminder {self.title} at {self.reminder_time}>'

class TaskTemplate(db.Model):
    """Модель шаблона заданий для библиотеки шаблонов"""
    __tablename__ = 'TaskTemplates'
    template_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)  # Название шаблона
    description = db.Column(db.Text, nullable=True)  # Описание шаблона
    template_type = db.Column(db.String(20), nullable=False)  # 'homework', 'classwork', 'exam', 'lesson'
    category = db.Column(db.String(50), nullable=True)  # Категория ученика (ЕГЭ, ОГЭ, ЛЕВЕЛАП, ПРОГРАММИРОВАНИЕ)
    created_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)  # Кто создал шаблон
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    is_active = db.Column(db.Boolean, default=True)
    
    # Связи
    template_tasks = db.relationship('TemplateTask', back_populates='template', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def __repr__(self):
        return f'<TaskTemplate {self.name} ({self.template_type})>'

class TemplateTask(db.Model):
    """Связь между шаблоном и заданиями"""
    __tablename__ = 'TemplateTasks'
    template_task_id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('TaskTemplates.template_id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    order = db.Column(db.Integer, default=0)  # Порядок задания в шаблоне
    created_at = db.Column(db.DateTime, default=moscow_now)
    
    # Связи
    template = db.relationship('TaskTemplate', back_populates='template_tasks')
    task = db.relationship('Tasks')
    
    def __repr__(self):
        return f'<TemplateTask template_id={self.template_id} task_id={self.task_id}>'

class MaintenanceMode(db.Model):
    """Модель для управления режимом технических работ"""
    __tablename__ = 'MaintenanceMode'
    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    message = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    updated_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    
    updated_by_user = db.relationship('User', foreign_keys=[updated_by])
    
    @classmethod
    def get_status(cls):
        """Получить текущий статус тех работ"""
        status = cls.query.first()
        if not status:
            # Создаем запись по умолчанию, если её нет
            status = cls(is_enabled=False, message='Ведутся технические работы. Пожалуйста, зайдите позже.')
            db.session.add(status)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return status
    
    @classmethod
    def is_maintenance_enabled(cls):
        """Проверить, включен ли режим тех работ"""
        status = cls.get_status()
        return status.is_enabled
