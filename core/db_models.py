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
    tester_id = db.Column(db.String(36), db.ForeignKey('Testers.tester_id'), nullable=True, index=True)
    tester_name = db.Column(db.String(100), nullable=True)
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

    tester = db.relationship('Tester', back_populates='audit_logs')

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
