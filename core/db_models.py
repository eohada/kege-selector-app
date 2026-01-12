from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import JSON, Index, Table, Column, Integer, ForeignKey, DateTime, String, Boolean, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
import json
import uuid

db = SQLAlchemy()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TOMSK_TZ = ZoneInfo("Asia/Tomsk")

def moscow_now():
    return datetime.now(MOSCOW_TZ)

# Связующая таблица для связи Заданий и Тем (many-to-many)
# Используем правильный синтаксис для SQLAlchemy Table
task_topics = Table('task_topics',
    db.metadata,
    Column('task_id', Integer, ForeignKey('Tasks.task_id'), primary_key=True),
    Column('topic_id', Integer, ForeignKey('Topics.topic_id'), primary_key=True),
    Column('created_at', DateTime, default=moscow_now)
)

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
    topics = db.relationship('Topic', secondary=task_topics, backref='tasks', lazy=True)

class Topic(db.Model):
    """Модель тем (навыков) для тегирования заданий"""
    __tablename__ = 'Topics'
    topic_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)  # Пример: "Логарифмы", "Пунктуация", "Дроби"
    description = db.Column(db.Text, nullable=True)  # Описание темы
    subject_id = db.Column(db.Integer, nullable=True)  # ID предмета (если нужна категоризация)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    def __repr__(self):
        return f'<Topic {self.name}>'

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
    published_at = db.Column(db.DateTime, nullable=True) # Дата отправки урока/ДЗ ученику
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
    
    # Новые поля для полноценной системы сдачи
    status = db.Column(db.String(20), default='pending') # pending, submitted, graded, returned
    submission_files = db.Column(db.JSON, nullable=True) # Список путей к файлам
    teacher_comment = db.Column(db.Text, nullable=True) # Комментарий преподавателя к задаче

    lesson = db.relationship('Lesson', back_populates='homework_tasks')
    task = db.relationship('Tasks')

class User(db.Model):
    """Модель пользователя для авторизации (расширенная для RBAC)"""
    __tablename__ = 'Users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=True)  # Email для входа (новое поле)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Роли: 'admin', 'tutor', 'student', 'parent', 'tester', 'creator' (старые роли для обратной совместимости)
    role = db.Column(db.String(50), default='tester', nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    last_login = db.Column(db.DateTime, nullable=True)

    # Старые поля профиля (оставляем для обратной совместимости)
    avatar_url = db.Column(db.String(500), nullable=True)
    about_me = db.Column(db.Text, nullable=True)
    custom_status = db.Column(db.String(100), nullable=True)
    telegram_link = db.Column(db.String(200), nullable=True)
    github_link = db.Column(db.String(200), nullable=True)
    
    # Flask-Login методы
    def get_id(self):
        return str(self.id)
    
    def is_authenticated(self):
        return True
    
    def is_anonymous(self):
        return False
    
    # Проверки ролей (новые)
    def is_admin(self):
        """Проверка, является ли пользователь администратором"""
        return self.role == 'admin'
    
    def is_tutor(self):
        """Проверка, является ли пользователь тьютором"""
        return self.role == 'tutor'
    
    def is_student(self):
        """Проверка, является ли пользователь учеником"""
        return self.role == 'student'
    
    def is_parent(self):
        """Проверка, является ли пользователь родителем"""
        return self.role == 'parent'

    def is_chief_tester(self):
        return self.role == 'chief_tester'

    def is_designer(self):
        return self.role == 'designer'
    
    # Старые методы (для обратной совместимости)
    def is_creator(self):
        """Проверка, является ли пользователь создателем"""
        return self.role == 'creator'
    
    def get_role_display(self):
        """Возвращает отображаемое название роли"""
        role_map = {
            'creator': 'Создатель',
            'admin': 'Администратор',
            'chief_tester': 'Главный тестировщик',
            'tutor': 'Преподаватель',
            'designer': 'Графический дизайнер',
            'tester': 'Тестировщик',
            'student': 'Ученик',
            'parent': 'Родитель',
        }
        return role_map.get(self.role, self.role)
    
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

    # JSON поле для индивидуальных прав пользователя
    custom_permissions = db.Column(db.JSON, nullable=True)

# Новая модель для хранения настроек ролей
class RolePermission(db.Model):
    __tablename__ = 'RolePermissions'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(50), nullable=False)
    permission_name = db.Column(db.String(100), nullable=False)
    is_enabled = db.Column(db.Boolean, default=False)
    
    __table_args__ = (
        db.UniqueConstraint('role', 'permission_name', name='uq_role_permission'),
    )

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
        # Сравниваем naive datetime с naive datetime
        now = moscow_now()
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        reminder_naive = self.reminder_time.replace(tzinfo=None) if self.reminder_time.tzinfo else self.reminder_time
        return reminder_naive < now_naive
    
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


# ============================================================================
# НОВАЯ СИСТЕМА АВТОРИЗАЦИИ И РОЛЕЙ (RBAC)
# ============================================================================

class UserProfile(db.Model):
    """Расширенный профиль пользователя (1-to-1 с User)"""
    __tablename__ = 'UserProfiles'
    profile_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), unique=True, nullable=False)
    
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    middle_name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=True)  # Для SMS уведомлений
    telegram_id = db.Column(db.String(100), nullable=True)  # Для бота уведомлений
    timezone = db.Column(db.String(50), default='Europe/Moscow', nullable=False)
    avatar_url = db.Column(db.String(500), nullable=True)
    
    # Приватные заметки (видны только админу и тьютору)
    internal_notes = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    # Связь с User
    user = db.relationship('User', backref=db.backref('profile', uselist=False), uselist=False)
    
    def __repr__(self):
        return f'<UserProfile {self.user_id}: {self.first_name} {self.last_name}>'


class FamilyTie(db.Model):
    """Связь между Родителем и Учеником (Many-to-Many)"""
    __tablename__ = 'FamilyTies'
    tie_id = db.Column(db.Integer, primary_key=True)
    
    parent_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    
    # Уровень доступа: 'full', 'financial_only', 'schedule_only'
    access_level = db.Column(db.String(50), default='full', nullable=False)
    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)  # Подтверждение связи
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    # Связи
    parent = db.relationship('User', foreign_keys=[parent_id], backref='parent_children')
    student = db.relationship('User', foreign_keys=[student_id], backref='student_parents')
    
    # Уникальный индекс для защиты от дублей
    __table_args__ = (Index('ix_family_tie_unique', 'parent_id', 'student_id', unique=True),)
    
    def __repr__(self):
        return f'<FamilyTie parent:{self.parent_id} -> student:{self.student_id}>'


class Enrollment(db.Model):
    """Учебный контракт: связь Ученик - Тьютор - Предмет"""
    __tablename__ = 'Enrollments'
    enrollment_id = db.Column(db.Integer, primary_key=True)
    
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    
    # Предмет (например, "INFORMATICS_EGE_2025", "MATH_EGE_2025")
    subject = db.Column(db.String(100), nullable=False)
    
    # Статус: 'active', 'paused', 'archived'
    status = db.Column(db.String(50), default='active', nullable=False)
    
    # Индивидуальные настройки (JSON)
    settings = db.Column(JSON, nullable=True)  # Например, цена часа, особые условия
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    # Связи
    student = db.relationship('User', foreign_keys=[student_id], backref='student_enrollments')
    tutor = db.relationship('User', foreign_keys=[tutor_id], backref='tutor_enrollments')
    
    def __repr__(self):
        return f'<Enrollment student:{self.student_id} - tutor:{self.tutor_id} ({self.subject})>'


# ============================================================================
# СИСТЕМА ЗАДАНИЙ И СДАЧИ РАБОТ (ASSIGNMENT/SUBMISSION)
# ============================================================================

class Assignment(db.Model):
    """
    Модель работы (ДЗ/КР/проверочная)
    Создается учителем и распределяется среди учеников
    """
    __tablename__ = 'Assignments'
    
    assignment_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)  # Название работы
    description = db.Column(db.Text, nullable=True)  # Описание/инструкции
    assignment_type = db.Column(db.String(50), nullable=False)  # 'homework', 'classwork', 'exam', 'test'
    
    # Временные рамки
    deadline = db.Column(db.DateTime, nullable=False)  # Дедлайн сдачи
    hard_deadline = db.Column(db.Boolean, default=False)  # Если True - нельзя сдать после дедлайна
    time_limit_minutes = db.Column(db.Integer, nullable=True)  # Ограничение времени выполнения (для exam/test)
    
    # Создатель и связь с уроком (опционально)
    created_by_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)  # Учитель, создавший работу
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=True)  # Связь с уроком (если есть)
    
    # Метаданные
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Можно ли еще работать с этой работой
    
    # Связи
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_assignments')
    lesson = db.relationship('Lesson', backref='assignments')
    tasks = db.relationship('AssignmentTask', back_populates='assignment', lazy=True, cascade='all, delete-orphan')
    submissions = db.relationship('Submission', back_populates='assignment', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Assignment {self.assignment_id}: {self.title} ({self.assignment_type})>'


class AssignmentTask(db.Model):
    """
    Модель задачи в работе
    Связывает Assignment с конкретной задачей из базы Tasks
    """
    __tablename__ = 'AssignmentTasks'
    
    assignment_task_id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('Assignments.assignment_id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    
    # Порядок задачи в работе
    order_index = db.Column(db.Integer, nullable=False, default=0)  # Порядок отображения
    
    # Оценка задачи
    max_score = db.Column(db.Integer, nullable=False, default=1)  # Максимальный балл за задачу
    
    # Тип проверки
    requires_manual_grading = db.Column(db.Boolean, default=False, nullable=False)  # Требует ли ручной проверки
    
    # Метаданные
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    
    # Связи
    assignment = db.relationship('Assignment', back_populates='tasks')
    task = db.relationship('Tasks', backref='assignment_tasks')
    answers = db.relationship('Answer', back_populates='assignment_task', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<AssignmentTask {self.assignment_task_id}: task {self.task_id} in assignment {self.assignment_id}>'


class Submission(db.Model):
    """
    Модель сдачи работы учеником
    Создается автоматически при распределении работы (статус ASSIGNED)
    """
    __tablename__ = 'Submissions'
    
    submission_id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('Assignments.assignment_id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False)
    
    # Статус сдачи
    status = db.Column(db.String(50), nullable=False, default='ASSIGNED')  
    # Возможные статусы: ASSIGNED, IN_PROGRESS, SUBMITTED, GRADED, RETURNED, LATE
    
    # Временные метки
    assigned_at = db.Column(db.DateTime, default=moscow_now, nullable=False)  # Когда назначено
    started_at = db.Column(db.DateTime, nullable=True)  # Когда ученик начал выполнение
    submitted_at = db.Column(db.DateTime, nullable=True)  # Когда сдано
    graded_at = db.Column(db.DateTime, nullable=True)  # Когда проверено
    
    # Флаги
    is_late = db.Column(db.Boolean, default=False, nullable=False)  # Сдано с опозданием
    
    # Оценка
    total_score = db.Column(db.Integer, nullable=True)  # Общий балл
    max_score = db.Column(db.Integer, nullable=True)  # Максимальный возможный балл
    percentage = db.Column(db.Float, nullable=True)  # Процент выполнения
    
    # Комментарий учителя
    teacher_feedback = db.Column(db.Text, nullable=True)
    
    # Метаданные
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)
    
    # Связи
    assignment = db.relationship('Assignment', back_populates='submissions')
    student = db.relationship('Student', backref='submissions')
    answers = db.relationship('Answer', back_populates='submission', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Submission {self.submission_id}: student {self.student_id}, assignment {self.assignment_id}, status {self.status}>'


class Answer(db.Model):
    """
    Модель ответа ученика на конкретную задачу
    """
    __tablename__ = 'Answers'
    
    answer_id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id'), nullable=False)
    assignment_task_id = db.Column(db.Integer, db.ForeignKey('AssignmentTasks.assignment_task_id'), nullable=False)
    
    # Ответ ученика
    value = db.Column(db.Text, nullable=True)  # Текст ответа или JSON для сложных ответов
    files = db.Column(JSON, nullable=True)  # Массив путей к прикрепленным файлам
    
    # Результат проверки
    is_correct = db.Column(db.Boolean, nullable=True)  # Правильность ответа (для авто-проверки)
    score = db.Column(db.Integer, nullable=True)  # Балл за ответ
    max_score = db.Column(db.Integer, nullable=True)  # Максимальный балл (копия из AssignmentTask)
    
    # Комментарий учителя к конкретному ответу
    teacher_comment = db.Column(db.Text, nullable=True)
    
    # Метаданные
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)
    
    # Связи
    submission = db.relationship('Submission', back_populates='answers')
    assignment_task = db.relationship('AssignmentTask', back_populates='answers')
    
    # Уникальность: один ответ на задачу в одной сдаче
    __table_args__ = (
        db.UniqueConstraint('submission_id', 'assignment_task_id', name='uq_submission_task'),
    )
    
    def __repr__(self):
        return f'<Answer {self.answer_id}: submission {self.submission_id}, task {self.assignment_task_id}, score {self.score}>'
