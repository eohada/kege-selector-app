from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import JSON, Index, Table, Column, Integer, ForeignKey, DateTime, String, Boolean, Enum as SQLEnum, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB as PG_JSONB
import json
import uuid

db = SQLAlchemy()


class JSONBCompat(TypeDecorator):
    """
    JSON-поле: в PostgreSQL — JSONB (индексируемый), в SQLite — JSON (нет нативного JSONB).
    Использовать для hints, behavior_flags и других JSON-полей, где в проде нужен JSONB.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TOMSK_TZ = ZoneInfo("Asia/Tomsk")

def moscow_now():
    return datetime.now(MOSCOW_TZ)


def utc_now():
    """Aware UTC «now» for DB defaults and business logic (timestamptz)."""
    return datetime.now(timezone.utc)

class QATestCase(db.Model):
    """Тест-кейсы для QA-отдела."""
    __tablename__ = 'QATestCases'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    area = db.Column(db.String(100), nullable=False, index=True)
    role = db.Column(db.String(100), nullable=True)
    steps = db.Column(JSONBCompat, nullable=True) # Массив строк (шагов)
    expected_result = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

class QAReport(db.Model):
    """Баг-репорты или результаты прохождения тест-кейсов."""
    __tablename__ = 'QAReports'
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('QATestCases.id', ondelete='SET NULL'), nullable=True, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)

    # Спринт/цикл тестирования (для разделения данных между спринтами)
    cycle_id = db.Column(db.Integer, nullable=True, index=True, default=1)

    area = db.Column(db.String(100), nullable=True, index=True)
    # Статусы: pending -> in_progress -> retest -> resolved (rejected скрытый)
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)
    verdict = db.Column(db.String(50), nullable=True)  # success, minor, critical

    # Иммутабельное первичное описание проблемы (заполняется один раз при создании)
    description = db.Column(db.Text, nullable=True)
    # Системные логи: HAR, консольные ошибки, сетевые ошибки (JSON-массив строк)
    logs = db.Column(JSONBCompat, nullable=True)

    failed_steps = db.Column(JSONBCompat, nullable=True)  # Массив индексов шагов с багом

    page_url = db.Column(db.String(500), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    screen_size = db.Column(db.String(50), nullable=True)   # "1920x1080"
    attachments = db.Column(JSONBCompat, nullable=True)  # [{url, type, filename}]

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    test_case = db.relationship('QATestCase', backref=db.backref('reports', lazy='dynamic', cascade='all, delete-orphan'))
    reporter = db.relationship('User', foreign_keys=[reporter_id])

class QAReportHistory(db.Model):
    """История переписки и смены статусов по баг-репорту."""
    __tablename__ = 'QAReportHistory'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('QAReports.id', ondelete='CASCADE'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True)
    
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=moscow_now)

    report = db.relationship('QAReport', backref=db.backref('history', lazy='dynamic', cascade='all, delete-orphan'))
    author = db.relationship('User', foreign_keys=[author_id])


class TestCase(db.Model):
    """Тест-кейс системы тестирования V2."""
    __tablename__ = 'test_cases'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    area = db.Column(db.String(100), nullable=False, default='general', index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(50), default='DRAFT', nullable=False, index=True)  # DRAFT, ACTIVE, PASSED, FAILED
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref=db.backref('assigned_test_cases', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    steps = db.relationship('TestStep', backref='test_case', cascade='all, delete-orphan', lazy='joined', order_by='TestStep.step_number')
    bug_reports = db.relationship('BugReport', backref='test_case', cascade='all, delete-orphan', lazy='dynamic')


class TestStep(db.Model):
    """Шаг чек-листа проверки для тест-кейса."""
    __tablename__ = 'test_steps'
    id = db.Column(db.Integer, primary_key=True)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id', ondelete='CASCADE'), nullable=False, index=True)
    step_number = db.Column(db.Integer, nullable=False, default=1)
    action_text = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text, nullable=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text, nullable=True)


class BugReport(db.Model):
    """Отчет об ошибке / баг-репорт от тестировщика."""
    __tablename__ = 'bug_reports'
    id = db.Column(db.Integer, primary_key=True)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_cases.id', ondelete='SET NULL'), nullable=True, index=True)
    test_step_id = db.Column(db.Integer, db.ForeignKey('test_steps.id', ondelete='SET NULL'), nullable=True, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    page_url = db.Column(db.String(500), nullable=True)
    step_failed = db.Column(db.String(255), nullable=True)
    expected_vs_actual = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(50), default='MAJOR', nullable=False, index=True)  # CRITICAL, MAJOR, MINOR
    status = db.Column(db.String(50), default='NEW', nullable=False, index=True)        # NEW, IN_PROGRESS, RESOLVED, REJECTED
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    test_step = db.relationship('TestStep', foreign_keys=[test_step_id])
    reporter = db.relationship('User', foreign_keys=[reporter_id])


class BugReportComment(db.Model):
    """Комментарии / ветка обсуждения в баг-репорте."""
    __tablename__ = 'bug_report_comments'
    id = db.Column(db.Integer, primary_key=True)
    bug_report_id = db.Column(db.Integer, db.ForeignKey('bug_reports.id', ondelete='CASCADE'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    author = db.relationship('User', foreign_keys=[author_id])
    bug_report = db.relationship('BugReport', backref=db.backref('comments', cascade='all, delete-orphan', order_by='BugReportComment.id.asc()'))

task_topics = Table('task_topics',
    db.metadata,
    Column('task_id', Integer, ForeignKey('Tasks.task_id'), primary_key=True),
    Column('topic_id', Integer, ForeignKey('Topics.topic_id'), primary_key=True),
    Column('created_at', DateTime, default=moscow_now)
)

class Course(db.Model):
    """Программа подготовки (тип экзамена): ЕГЭ Информатика, ОГЭ Информатика и т.д."""
    __tablename__ = 'ExamCourses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    task_templates = db.relationship('CourseTaskTemplate', back_populates='course', lazy=True,
                                     order_by='CourseTaskTemplate.task_number')
    grading_scales = db.relationship('GradingScale', back_populates='course', lazy=True)
    enrollments = db.relationship('StudentCourseEnrollment', back_populates='course', lazy=True)

    def __repr__(self):
        return f'<Course {self.slug}: {self.title}>'


class CourseTaskTemplate(db.Model):
    """Спецификация: какие номера заданий входят в экзамен и их параметры."""
    __tablename__ = 'CourseTaskTemplates'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=False, index=True)
    task_number = db.Column(db.Integer, nullable=False)
    max_primary_score = db.Column(db.Integer, default=1, nullable=False)
    requires_manual_review = db.Column(db.Boolean, default=False, nullable=False)
    description = db.Column(db.String(300), nullable=True)

    course = db.relationship('Course', back_populates='task_templates')

    __table_args__ = (
        db.UniqueConstraint('course_id', 'task_number', name='uq_course_task_number'),
    )

    def __repr__(self):
        return f'<CourseTaskTemplate course={self.course_id} task={self.task_number}>'


class ExamSkill(db.Model):
    """Атомарный экзаменационный навык, общий для всех индивидуальных планов."""
    __tablename__ = 'ExamSkills'
    skill_id = db.Column(db.Integer, primary_key=True)
    exam_course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    subject = db.Column(db.String(120), nullable=True, index=True)
    topic = db.Column(db.String(200), nullable=True, index=True)
    subtopic = db.Column(db.String(200), nullable=True)
    difficulty = db.Column(db.Integer, nullable=True)
    weight = db.Column(db.Float, nullable=False, default=1.0)
    theory_ref = db.Column(db.String(300), nullable=True)
    mastery_criteria = db.Column(db.JSON, nullable=True)
    prerequisite_skill_id = db.Column(db.Integer, db.ForeignKey('ExamSkills.skill_id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)

    course = db.relationship('Course', foreign_keys=[exam_course_id])
    prerequisite = db.relationship('ExamSkill', remote_side=[skill_id], uselist=False)


class StudentSkill(db.Model):
    """Текущее состояние освоения конкретного навыка учеником."""
    __tablename__ = 'StudentSkills'
    student_skill_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('ExamSkills.skill_id'), nullable=False, index=True)
    mastery_percent = db.Column(db.Integer, nullable=False, default=0)
    state = db.Column(db.String(30), nullable=False, default='not_started', index=True)
    theory_done = db.Column(db.Boolean, nullable=False, default=False)
    practice_done = db.Column(db.Boolean, nullable=False, default=False)
    homework_total = db.Column(db.Integer, nullable=False, default=0)
    homework_done = db.Column(db.Integer, nullable=False, default=0)
    last_checked_at = db.Column(db.DateTime, nullable=True, index=True)
    next_review_at = db.Column(db.DateTime, nullable=True, index=True)
    source = db.Column(db.String(40), nullable=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id])
    skill = db.relationship('ExamSkill', foreign_keys=[skill_id])
    __table_args__ = (db.UniqueConstraint('student_id', 'skill_id', name='uq_student_skill'),)


class LearningError(db.Model):
    """Журнал ошибок ученика с повторяемостью и планом исправления."""
    __tablename__ = 'LearningErrors'
    error_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('ExamSkills.skill_id'), nullable=True, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=True, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=True, index=True)
    error_type = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    occurrences = db.Column(db.Integer, nullable=False, default=1)
    last_seen_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    next_review_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    student = db.relationship('Student', foreign_keys=[student_id])
    skill = db.relationship('ExamSkill', foreign_keys=[skill_id])
    lesson = db.relationship('Lesson', foreign_keys=[lesson_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])


class LearningItem(db.Model):
    """Универсальный элемент программы; Lesson — один из его типов."""
    __tablename__ = 'LearningItems'
    item_id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('Courses.course_id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('CourseModules.module_id'), nullable=True, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=True, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('ExamSkills.skill_id'), nullable=True, index=True)
    item_type = db.Column(db.String(30), nullable=False, default='lesson', index=True)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='planned', index=True)
    due_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    why_now = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, nullable=False, default=0)
    metadata_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    course = db.relationship('LearningTrajectory', foreign_keys=[course_id], overlaps='items')
    module = db.relationship('TrajectoryModule', foreign_keys=[module_id])
    lesson = db.relationship('Lesson', foreign_keys=[lesson_id])
    skill = db.relationship('ExamSkill', foreign_keys=[skill_id])


class LearningTrajectoryVersion(db.Model):
    """Снимок маршрута перед изменением программы."""
    __tablename__ = 'CourseVersions'
    version_id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('Courses.course_id'), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(300), nullable=True)
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    course = db.relationship('LearningTrajectory', foreign_keys=[course_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    __table_args__ = (db.UniqueConstraint('course_id', 'version_number', name='uq_course_version'),)


class LearningTrajectoryTemplate(db.Model):
    """Переиспользуемая программа, из которой строится персональный маршрут."""
    __tablename__ = 'CourseTemplates'
    template_id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    exam_course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    title = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_score = db.Column(db.Integer, nullable=True)
    estimated_lessons = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    owner = db.relationship('User', foreign_keys=[owner_user_id])
    exam_course = db.relationship('Course', foreign_keys=[exam_course_id])
    modules = db.relationship('LearningTrajectoryTemplateModule', back_populates='template', lazy=True, cascade='all, delete-orphan')


class LearningTrajectoryTemplateModule(db.Model):
    __tablename__ = 'CourseTemplateModules'
    template_module_id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('CourseTemplates.template_id'), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    template = db.relationship('LearningTrajectoryTemplate', back_populates='modules')
    items = db.relationship('LearningTrajectoryTemplateItem', back_populates='module', lazy=True, cascade='all, delete-orphan')


class LearningTrajectoryTemplateItem(db.Model):
    __tablename__ = 'CourseTemplateItems'
    template_item_id = db.Column(db.Integer, primary_key=True)
    template_module_id = db.Column(db.Integer, db.ForeignKey('CourseTemplateModules.template_module_id'), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('ExamSkills.skill_id'), nullable=True, index=True)
    item_type = db.Column(db.String(30), nullable=False, default='practice')
    title = db.Column(db.String(300), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=True)
    order_index = db.Column(db.Integer, nullable=False, default=0)
    metadata_json = db.Column(db.JSON, nullable=True)

    module = db.relationship('LearningTrajectoryTemplateModule', back_populates='items')
    skill = db.relationship('ExamSkill', foreign_keys=[skill_id])


class LessonOutcome(db.Model):
    """Структурированный итог занятия для аналитики и следующего шага."""
    __tablename__ = 'LessonOutcomes'
    outcome_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, unique=True, index=True)
    covered = db.Column(db.JSON, nullable=True)
    mastery = db.Column(db.String(20), nullable=True)
    next_action = db.Column(db.String(30), nullable=True)
    homework_assigned = db.Column(db.Boolean, nullable=False, default=False)
    teacher_note = db.Column(db.Text, nullable=True)
    content_snapshot = db.Column(db.JSON, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    lesson = db.relationship('Lesson', foreign_keys=[lesson_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])


class Tasks(db.Model):
    __tablename__ = 'Tasks'
    task_id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)
    # Для заданий 19–21: одна задача на источнике = три задания (19, 20, 21). Связка по task_group_id (например site_task_id).
    task_group_id = db.Column(db.String(64), nullable=True, index=True)
    site_task_id = db.Column(db.Text, nullable=True)
    source_url = db.Column(db.Text, nullable=True)
    content_html = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    attached_files = db.Column(db.Text, nullable=True)
    last_scraped = db.Column(db.DateTime, default=moscow_now)
    knowledge_node_id = db.Column(db.Integer, db.ForeignKey('knowledge_nodes.id', ondelete='SET NULL'), nullable=True, index=True)

    # --- Фаза 0: сложность задачи и подсказки ---
    # difficulty_level: 1 = лёгкий, 2 = средний, 3 = сложный; NULL = не размечено (считать средний)
    difficulty_level = db.Column(db.Integer, nullable=True, index=True)
    # hints: лестница подсказок; в PostgreSQL — JSONB (индексируемый), в SQLite — JSON
    hints = db.Column(JSONBCompat, nullable=True)
    # source_prototype: путь к эталонному JSON (напр. task_19/medium/task_19_medium.json) для upsert при синхронизации
    source_prototype = db.Column(db.String(256), nullable=True, index=True)
    # Происхождение записи в банке: manual | scraped | imported | legacy (NULL = до введения поля, считать банковым импортом/парсингом)
    bank_origin = db.Column(db.String(32), nullable=True, index=True)
    # Стартовый код для песочницы / подсказки ученику (опционально)
    starter_code = db.Column(db.Text, nullable=True)
    # Мягкое отключение записей банка (синхронизация КЕГЭ); генераторы выбирают только is_active=True
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Метки синхронизации с kompege.ru (API / парсер)
    kege_source_tag = db.Column(db.String(64), nullable=True, index=True)
    # 1 = базовый, 2 = средний, 3 = сложный (как на сайте); NULL — до синка или не КЕГЭ
    kege_difficulty_tier = db.Column(db.Integer, nullable=True, index=True)
    max_score = db.Column(db.Integer, default=1, nullable=True)

    DIFFICULTY_LEVEL_EASY = 1
    DIFFICULTY_LEVEL_MEDIUM = 2
    DIFFICULTY_LEVEL_HARD = 3

    @property
    def difficulty_label(self) -> str:
        """Человекочитаемая метка сложности: easy / medium / hard."""
        v = self.difficulty_level
        if v == 1:
            return 'easy'
        if v == 3:
            return 'hard'
        return 'medium'

    @property
    def kege_tier_label_ru(self) -> str | None:
        """Подпись уровня КЕГЭ (базовый/средний/сложный) для UI."""
        t = self.kege_difficulty_tier
        if t == 1:
            return "Базовый"
        if t == 2:
            return "Средний"
        if t == 3:
            return "Сложный"
        return None

    def get_elo_rating(self) -> float:
        """Рейтинг задачи для формул Elo с учётом difficulty_level и base_rating узла."""
        node = self.knowledge_node
        base = float(getattr(node, 'base_rating', 1000)) if node else 1000.0
        label = self.difficulty_label
        if label == 'easy':
            return base - 100.0
        if label == 'hard':
            return base + 150.0
        return base  # medium или не размечено

    course = db.relationship('Course', foreign_keys=[course_id], backref='tasks')
    usage_history = db.relationship('UsageHistory', back_populates='task', lazy=True)
    skipped_tasks = db.relationship('SkippedTasks', back_populates='task', lazy=True)
    blacklist_tasks = db.relationship('BlacklistTasks', back_populates='task', lazy=True)
    topics = db.relationship('Topic', secondary=task_topics, backref='tasks', lazy=True)
    knowledge_node = db.relationship('KnowledgeNode', foreign_keys=[knowledge_node_id], backref='tasks')

    @property
    def is_manual_bank_task(self) -> bool:
        return (self.bank_origin or '').strip() == 'manual'

class TaskReview(db.Model):
    """Результат ручной проверки задания (фундамент для формироватора банка заданий)."""
    __tablename__ = 'TaskReviews'
    review_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, unique=True, index=True)

    status = db.Column(db.String(30), default='new', nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)

    reviewer_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    task = db.relationship('Tasks', foreign_keys=[task_id])
    reviewer = db.relationship('User', foreign_keys=[reviewer_user_id])


class TaskSolution(db.Model):
    """Сгенерированное LLM или ручное решение задания (для просмотра создателем)."""
    __tablename__ = 'TaskSolutions'
    solution_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, unique=True, index=True)
    solution_text = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(20), default='llm', nullable=False, index=True)  # llm | manual
    needs_manual_review = db.Column(db.Boolean, default=False, nullable=False, index=True)  # ответ не совпал с источником
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    task = db.relationship('Tasks', foreign_keys=[task_id], backref=db.backref('task_solution', uselist=False))


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
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, unique=True, index=True)  # Прямая связь с User
    platform_id = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    telegram = db.Column(db.String(100), nullable=True)
    telegram_username = db.Column(db.String(100), nullable=True)
    discord_id = db.Column(db.String(100), nullable=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    lessons_balance = db.Column(db.Integer, default=0, nullable=True)
    
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('student_profile', uselist=False))

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
    
    # Ежедневная активность (Стрики)
    streak_days = db.Column(db.Integer, default=0, nullable=False)
    last_activity_date = db.Column(db.Date, nullable=True)
    streak_frozen = db.Column(db.Boolean, default=False, nullable=False)
    
    # Опыт и Уровни
    xp = db.Column(db.Integer, default=0, nullable=False)
    level = db.Column(db.Integer, default=1, nullable=False)

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    is_active = db.Column(db.Boolean, default=True)

    @property
    def id(self):
        return self.student_id

    @property
    def tutor_id(self):
        return self.mentor_id

    @tutor_id.setter
    def tutor_id(self, val):
        self.mentor_id = val

    @property
    def teacher_id(self):
        return self.mentor_id

    @teacher_id.setter
    def teacher_id(self, val):
        self.mentor_id = val

    lessons = db.relationship('Lesson', back_populates='student', lazy=True, cascade='all, delete-orphan')
    task_statistics = db.relationship('StudentTaskStatistics', back_populates='student', lazy=True, cascade='all, delete-orphan')
    learning_plan_items = db.relationship('StudentLearningPlanItem', back_populates='student', lazy=True, cascade='all, delete-orphan')
    diagnostic_checkpoints = db.relationship('StudentDiagnosticCheckpoint', back_populates='student', lazy=True, cascade='all, delete-orphan')

class StudentTaskStatistics(db.Model):
    """Ручные изменения статистики выполнения заданий для ученика"""
    __tablename__ = 'StudentTaskStatistics'
    stat_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False)
    manual_correct = db.Column(db.Integer, default=0, nullable=False)
    manual_incorrect = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    __table_args__ = (Index('ix_student_task_statistics', 'student_id', 'course_id', 'task_number', unique=True),)

    student = db.relationship('Student', back_populates='task_statistics')
    course = db.relationship('Course', foreign_keys=[course_id])


class StudentLearningPlanItem(db.Model):
    """
    Элемент учебной траектории ученика.

    MVP: привязка к Topic и/или TrajectoryModule + дедлайн + статус + заметки.
    Статусы: planned | in_progress | done | failed
    """
    __tablename__ = 'StudentLearningPlanItems'

    item_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)

    topic_id = db.Column(db.Integer, db.ForeignKey('Topics.topic_id'), nullable=True, index=True)
    course_module_id = db.Column(db.Integer, db.ForeignKey('CourseModules.module_id'), nullable=True, index=True)

    title = db.Column(db.String(300), nullable=False)  # человекочитаемое название пункта траектории
    status = db.Column(db.String(20), default='planned', nullable=False, index=True)
    due_date = db.Column(db.DateTime, nullable=True, index=True)  # дедлайн (обычно MSK)
    priority = db.Column(db.Integer, default=0, nullable=False, index=True)  # чем больше — тем выше
    notes = db.Column(db.Text, nullable=True)

    x = db.Column(db.Integer, nullable=True)  # Координата X на карте
    y = db.Column(db.Integer, nullable=True)  # Координата Y на карте
    parent_id = db.Column(db.Integer, db.ForeignKey('StudentLearningPlanItems.item_id'), nullable=True, index=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    student = db.relationship('Student', back_populates='learning_plan_items')
    topic = db.relationship('Topic', foreign_keys=[topic_id])
    course_module = db.relationship('TrajectoryModule', foreign_keys=[course_module_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    parent = db.relationship('StudentLearningPlanItem', remote_side=[item_id], backref='children')


class StudentDiagnosticCheckpoint(db.Model):
    """
    Контрольная точка диагностики ученика (входная/промежуточная).

    MVP: сохраняем снимок "дыр" по темам + заметки/рекомендации от преподавателя.
    """
    __tablename__ = 'StudentDiagnosticCheckpoints'

    checkpoint_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    kind = db.Column(db.String(30), default='checkpoint', nullable=False, index=True)  # baseline|checkpoint
    note = db.Column(db.Text, nullable=True)
    metrics = db.Column(db.JSON, nullable=True)        # summary_metrics (как есть)
    problem_topics = db.Column(db.JSON, nullable=True) # список слабых тем
    recommendations = db.Column(db.JSON, nullable=True)  # список рекомендаций/шагов

    created_at = db.Column(db.DateTime, default=moscow_now, index=True)

    student = db.relationship('Student', back_populates='diagnostic_checkpoints')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])


class SchoolGroup(db.Model):
    """
    Группа/класс как сущность (для массовых действий и отчётов).

    Важно: это НЕ расписание. Это просто состав группы.
    """
    __tablename__ = 'SchoolGroups'

    group_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(30), default='active', nullable=False, index=True)  # active|archived
    owner_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    tag = db.Column(db.String(100), default='Мини-группа', nullable=True)
    telegram_chat_link = db.Column(db.String(255), nullable=True)

    @property
    def id(self):
        return self.group_id

    @property
    def name(self):
        return self.title

    @name.setter
    def name(self, val):
        self.title = val

    @property
    def teacher_id(self):
        return self.owner_user_id

    @teacher_id.setter
    def teacher_id(self, val):
        self.owner_user_id = val

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    owner = db.relationship('User', foreign_keys=[owner_user_id])
    students = db.relationship('GroupStudent', back_populates='group', lazy=True, cascade='all, delete-orphan')


class GroupStudent(db.Model):
    """Участник группы (связь группа → Student)."""
    __tablename__ = 'GroupStudents'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('SchoolGroups.group_id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=moscow_now)
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)

    group = db.relationship('SchoolGroup', back_populates='students')
    student = db.relationship('Student', foreign_keys=[student_id])
    added_by = db.relationship('User', foreign_keys=[added_by_user_id])

    __table_args__ = (
        Index('ix_group_students_unique', 'group_id', 'student_id', unique=True),
    )


class LearningTrajectory(db.Model):
    """Индивидуальная учебная траектория ученика: траектория -> модули -> уроки."""
    __tablename__ = 'Courses'
    course_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    learning_goal = db.Column(db.Text, nullable=True)
    expected_result = db.Column(db.Text, nullable=True)
    exam_course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    target_score = db.Column(db.Integer, nullable=True)
    exam_date = db.Column(db.Date, nullable=True)
    current_forecast = db.Column(db.Integer, nullable=True)
    forecast_low = db.Column(db.Integer, nullable=True)
    forecast_high = db.Column(db.Integer, nullable=True)
    current_version = db.Column(db.Integer, nullable=False, default=1)
    default_lesson_duration = db.Column(db.Integer, default=60, nullable=False)
    lessons_per_week = db.Column(db.Integer, nullable=True)
    lesson_duration_minutes = db.Column(db.Integer, nullable=True)
    homework_hours_per_week = db.Column(db.Numeric(5, 2), nullable=True)
    diagnostic_mode = db.Column(db.String(30), nullable=True)  # test|manual
    starting_forecast = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(30), default='active', nullable=False, index=True)  # active|archived
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    student = db.relationship('Student', foreign_keys=[student_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    exam_course = db.relationship('Course', foreign_keys=[exam_course_id])
    modules = db.relationship('TrajectoryModule', back_populates='trajectory', lazy=True, cascade='all, delete-orphan')
    items = db.relationship('LearningItem', foreign_keys='LearningItem.course_id', lazy=True, overlaps='course')


class TrajectoryModule(db.Model):
    """Модуль учебной траектории (раздел/тема)."""
    __tablename__ = 'CourseModules'
    module_id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('Courses.course_id'), nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    learning_result = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    trajectory = db.relationship('LearningTrajectory', back_populates='modules')
    lessons = db.relationship('Lesson', back_populates='course_module', lazy=True)


class MaterialAsset(db.Model):
    """Материал в библиотеке (файлы/раздатки), который можно прикреплять к разным урокам."""
    __tablename__ = 'MaterialAssets'
    asset_id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    tag = db.Column(db.String(100), default='Мини-группа', nullable=True)
    telegram_chat_link = db.Column(db.String(255), nullable=True)

    @property
    def id(self):
        return self.group_id

    @property
    def name(self):
        return self.title

    @name.setter
    def name(self, val):
        self.title = val

    @property
    def teacher_id(self):
        return self.owner_user_id

    @teacher_id.setter
    def teacher_id(self, val):
        self.owner_user_id = val
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tags = db.Column(db.JSON, nullable=True)  # ["геометрия", "pdf", ...]
    visibility = db.Column(db.String(20), default='private', nullable=False)  # private|shared

    file_name = db.Column(db.String(300), nullable=False)
    file_url = db.Column(db.Text, nullable=False)  # публичный URL (через static)
    storage_path = db.Column(db.Text, nullable=True)  # относительный путь на диске (для защищенной отдачи)
    file_mime = db.Column(db.String(120), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    owner = db.relationship('User', foreign_keys=[owner_user_id])
    lesson_links = db.relationship('LessonMaterialLink', back_populates='asset', lazy=True, cascade='all, delete-orphan')


class LessonMaterialLink(db.Model):
    """Связь урока с материалом из библиотеки."""
    __tablename__ = 'LessonMaterialLinks'
    link_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('MaterialAssets.asset_id'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    lesson = db.relationship('Lesson', foreign_keys=[lesson_id])
    asset = db.relationship('MaterialAsset', back_populates='lesson_links')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index('ix_lesson_material_unique', 'lesson_id', 'asset_id', unique=True),
    )


class LessonRoomTemplate(db.Model):
    """Шаблон комнаты/урока: конспект, блоки, материалы."""
    __tablename__ = 'LessonRoomTemplates'
    template_id = db.Column(db.Integer, primary_key=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    payload = db.Column(db.JSON, nullable=False)  # {"content": "...", "content_blocks": [...], "materials": [...], "asset_ids": [...]}
    visibility = db.Column(db.String(20), default='private', nullable=False)  # private|shared
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    created_by = db.relationship('User', foreign_keys=[created_by_user_id])


class RecurringLessonSlot(db.Model):
    """
    Шаблон повторяющегося слота урока (автоплан).

    Пример: каждый вторник 18:00 (Tomsk), 60 минут, regular.
    На основе слотов можно “сгенерировать” уроки на неделю/месяц.
    """
    __tablename__ = 'RecurringLessonSlots'

    slot_id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)  # кто создал (обычно тьютор)

    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    tag = db.Column(db.String(100), default='Мини-группа', nullable=True)
    telegram_chat_link = db.Column(db.String(255), nullable=True)

    @property
    def id(self):
        return self.group_id

    @property
    def name(self):
        return self.title

    @name.setter
    def name(self, val):
        self.title = val

    @property
    def teacher_id(self):
        return self.owner_user_id

    @teacher_id.setter
    def teacher_id(self, val):
        self.owner_user_id = val
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)

    weekday = db.Column(db.Integer, nullable=False, index=True)  # 0=Mon..6=Sun
    time_hhmm = db.Column(db.String(5), nullable=False)          # "HH:MM" в выбранной timezone
    duration = db.Column(db.Integer, default=60, nullable=False) # minutes
    lesson_type = db.Column(db.String(50), default='regular', nullable=False)
    # IANA-зона автора слота: например, Asia/Krasnoyarsk.
    # Старые значения moscow/tomsk распознаются утилитой lesson_time.
    timezone = db.Column(db.String(64), default='Europe/Moscow', nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    owner = db.relationship('User', foreign_keys=[owner_user_id])
    student = db.relationship('Student', foreign_keys=[student_id])


class RubricTemplate(db.Model):
    """
    Шаблон рубрики/критериев для проверки.

    items хранится как JSON-список:
    [{"key":"crit1","title":"Критерий 1","max_score":2,"description":"..."}, ...]
    """
    __tablename__ = 'RubricTemplates'

    rubric_id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    tag = db.Column(db.String(100), default='Мини-группа', nullable=True)
    telegram_chat_link = db.Column(db.String(255), nullable=True)

    @property
    def id(self):
        return self.group_id

    @property
    def name(self):
        return self.title

    @name.setter
    def name(self, val):
        self.title = val

    @property
    def teacher_id(self):
        return self.owner_user_id

    @teacher_id.setter
    def teacher_id(self, val):
        self.owner_user_id = val

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    assignment_type = db.Column(db.String(50), nullable=True, index=True)  # homework|classwork|exam|test|...

    items = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    owner = db.relationship('User', foreign_keys=[owner_user_id])


class Lesson(db.Model):
    __tablename__ = 'Lessons'
    lesson_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False)
    learning_trajectory_id = db.Column(db.Integer, db.ForeignKey('Courses.course_id'), nullable=True, index=True)
    course_module_id = db.Column(db.Integer, db.ForeignKey('CourseModules.module_id'), nullable=True, index=True)
    exam_course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    lesson_type = db.Column(db.String(50), default='regular')
    lesson_date = db.Column(db.DateTime(timezone=True), nullable=True)
    duration = db.Column(db.Integer, default=60)
    course_order_index = db.Column(db.Integer, default=0, nullable=False, index=True)
    status = db.Column(db.String(50), default='planned')
    topic = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)  # Markdown контент урока (теория)
    content_blocks = db.Column(db.JSON, nullable=True)  # Конструктор контента (блоки): [{"type":"paragraph",...}, ...]
    student_notes = db.Column(db.Text, nullable=True)  # Личные заметки ученика
    materials = db.Column(db.JSON, nullable=True)  # Прикрепленные файлы/материалы [{"name": "...", "url": "...", "type": "..."}]
    homework = db.Column(db.Text, nullable=True)
    homework_status = db.Column(db.String(50), default='not_assigned')
    homework_result_percent = db.Column(db.Integer, nullable=True)
    homework_result_notes = db.Column(db.Text, nullable=True)
    review_summaries = db.Column(db.JSON, nullable=True)  # Итоги проверки по типам работ: {"homework": {...}, "classwork": {...}, "exam": {...}}
    # --- Попытки и режим сдачи ---
    # По умолчанию для каждого типа работы. NULL/пусто = 1 попытка.
    homework_max_attempts_default = db.Column(db.Integer, nullable=True)
    classwork_max_attempts_default = db.Column(db.Integer, nullable=True)
    exam_max_attempts_default = db.Column(db.Integer, nullable=True)

    # Разрешить ученику "сдавать по заданиям" (вместо/в дополнение к сдаче всей работы).
    allow_task_submit_homework = db.Column(db.Boolean, default=False, nullable=False)
    allow_task_submit_classwork = db.Column(db.Boolean, default=False, nullable=False)
    allow_task_submit_exam = db.Column(db.Boolean, default=False, nullable=False)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True) # Дата отправки урока/ДЗ ученику
    student_late = db.Column(db.Boolean, default=False, nullable=False)  # Ученик опоздал на урок
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Фактическое время начала (для авто-завершения через 1 ч)
    tg_reminder_30min_sent = db.Column(db.Boolean, default=False, nullable=False)  # Отправлено ли напоминание за 30 мин
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    student = db.relationship('Student', back_populates='lessons')
    course_module = db.relationship('TrajectoryModule', foreign_keys=[course_module_id], back_populates='lessons')
    exam_course = db.relationship('Course', foreign_keys=[exam_course_id])
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

    @property
    def start_dt(self):
        return self.lesson_date

    @start_dt.setter
    def start_dt(self, val):
        self.lesson_date = val

    @property
    def duration_minutes(self):
        return self.duration or 60

    @duration_minutes.setter
    def duration_minutes(self, val):
        self.duration = val

    @property
    def teacher_user_id(self):
        return getattr(self, '_teacher_user_id', None) or getattr(self, 'tutor_id', None) or getattr(self, 'teacher_id', None)

    @teacher_user_id.setter
    def teacher_user_id(self, val):
        self._teacher_user_id = val

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
    
    status = db.Column(db.String(20), default='pending') # pending, submitted, graded, returned
    submission_files = db.Column(db.JSON, nullable=True) # Список путей к файлам
    teacher_comment = db.Column(db.Text, nullable=True) # Комментарий преподавателя к задаче
    # Рейтинг задания в этой работе: 1 = лёгкий, 2 = средний, 3 = сложный. NULL = брать из Task.difficulty_level
    difficulty_level = db.Column(db.Integer, nullable=True, index=True)
    # Время, потраченное учеником на это задание (сек). Передаётся с фронта при сдаче или фиксируется на бэке
    time_spent_sec = db.Column(db.Integer, nullable=True)
    # Максимум попыток на это задание (переопределение). NULL = брать из Lesson.<type>_max_attempts_default (или 1)
    max_attempts = db.Column(db.Integer, nullable=True)

    lesson = db.relationship('Lesson', back_populates='homework_tasks')
    task = db.relationship('Tasks')
    teacher_comments = db.relationship('LessonTaskTeacherComment', back_populates='lesson_task', lazy=True, cascade='all, delete-orphan')  # comment
    attempts = db.relationship('LessonTaskAttempt', back_populates='lesson_task', lazy=True, cascade='all, delete-orphan')

    @property
    def difficulty_label(self) -> str:
        """Лёгкий / средний / сложный по difficulty_level (для отображения и аналитики)."""
        v = self.difficulty_level
        if v == 1:
            return 'easy'
        if v == 3:
            return 'hard'
        return 'medium'

    @property
    def attempts_used(self) -> int:
        """Сколько попыток сдачи уже зафиксировано (LessonTaskAttempts)."""
        try:
            return len(self.attempts or [])
        except Exception:
            return 0

    def get_effective_max_attempts(self) -> int:
        """
        Эффективный лимит попыток:
        - LessonTask.max_attempts (если задано и > 0)
        - иначе Lesson.<type>_max_attempts_default (если задано и > 0)
        - иначе 1
        """
        try:
            if self.max_attempts is not None:
                v = int(self.max_attempts)
                if v > 0:
                    return v
        except Exception:
            pass

        at = (self.assignment_type or 'homework').strip().lower() or 'homework'
        lesson = getattr(self, 'lesson', None)
        lesson_val = None
        if lesson is not None:
            key = {
                'homework': 'homework_max_attempts_default',
                'classwork': 'classwork_max_attempts_default',
                'exam': 'exam_max_attempts_default',
            }.get(at, 'homework_max_attempts_default')
            lesson_val = getattr(lesson, key, None)
        try:
            if lesson_val is not None:
                v = int(lesson_val)
                if v > 0:
                    return v
        except Exception:
            pass
        return 1

    def is_task_submit_allowed(self) -> bool:
        """Можно ли ученику сдавать именно это задание отдельно (зависит от Lesson и assignment_type)."""
        at = (self.assignment_type or 'homework').strip().lower() or 'homework'
        lesson = getattr(self, 'lesson', None)
        if not lesson:
            return False
        flag = {
            'homework': 'allow_task_submit_homework',
            'classwork': 'allow_task_submit_classwork',
            'exam': 'allow_task_submit_exam',
        }.get(at, 'allow_task_submit_homework')
        return bool(getattr(lesson, flag, False))


class StudentTaskSeen(db.Model):
    """
    Глобальный анти-повтор для конкретного ученика (Students.student_id):
    фиксируем факт того, что задача (Tasks.task_id) уже была выдана/прикреплена,
    чтобы исключать её из других источников (уроки ↔ тренажёр).
    """
    __tablename__ = 'StudentTaskSeen'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, index=True)
    source = db.Column(db.String(40), nullable=True)  # trainer|lesson:homework|lesson:classwork|...
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    student = db.relationship('Student', foreign_keys=[student_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])

    __table_args__ = (
        Index('ix_student_task_seen_unique', 'student_id', 'task_id', unique=True),
    )


class LessonTaskTeacherComment(db.Model):  # comment
    """Комментарий преподавателя к конкретному заданию урока (мульти-комментарии с таймстампами)."""  # comment
    __tablename__ = 'LessonTaskTeacherComments'  # comment
    comment_id = db.Column(db.Integer, primary_key=True)  # comment
    lesson_task_id = db.Column(db.Integer, db.ForeignKey('LessonTasks.lesson_task_id'), nullable=False, index=True)  # comment
    author_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)  # comment
    body = db.Column(db.Text, nullable=False)  # comment
    created_at = db.Column(db.DateTime, default=moscow_now)  # comment

    lesson_task = db.relationship('LessonTask', back_populates='teacher_comments')  # comment
    author = db.relationship('User', foreign_keys=[author_user_id])  # comment


class LessonTaskAttempt(db.Model):
    """
    Попытка сдачи конкретного задания в классной комнате (LessonTask).

    Создаётся при нажатии "Сдать работу" (и при пересдаче после returned).
    Хранит снимок ответа и результата автопроверки на момент сдачи.
    """
    __tablename__ = 'LessonTaskAttempts'

    attempt_id = db.Column(db.Integer, primary_key=True)
    lesson_task_id = db.Column(db.Integer, db.ForeignKey('LessonTasks.lesson_task_id'), nullable=False, index=True)
    attempt_no = db.Column(db.Integer, nullable=False, default=1, index=True)

    submitted_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    student_submission = db.Column(db.Text, nullable=True)
    submission_files = db.Column(db.JSON, nullable=True)
    submission_correct = db.Column(db.Boolean, nullable=True)

    status = db.Column(db.String(20), nullable=True)  # submitted/graded/returned

    lesson_task = db.relationship('LessonTask', back_populates='attempts')

    __table_args__ = (
        Index('ix_lesson_task_attempt_unique', 'lesson_task_id', 'attempt_no', unique=True),
    )

class User(db.Model):
    """Модель пользователя для авторизации (расширенная для RBAC)"""
    __tablename__ = 'Users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=True)  # Email для входа (новое поле)
    password_hash = db.Column(db.String(255), nullable=True)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password) if self.password_hash else False
    
    role = db.Column(db.String(50), default='tester', nullable=False)
    numeric_id = db.Column(db.String(10), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    last_login = db.Column(db.DateTime(timezone=True), nullable=True)

    avatar_url = db.Column(db.String(500), nullable=True)
    cover_url = db.Column(db.String(500), nullable=True)  # Фоновое изображение профиля
    about_me = db.Column(db.Text, nullable=True)
    custom_status = db.Column(db.String(100), nullable=True)
    telegram_link = db.Column(db.String(200), nullable=True)
    github_link = db.Column(db.String(200), nullable=True)
    presence_activity_key = db.Column(db.String(80), nullable=True, index=True)
    presence_activity_text = db.Column(db.String(180), nullable=True)
    presence_last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    presence_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Часовой пояс отображения: auto = браузер (Intl) + профиль; manual = timezone_iana
    timezone_mode = db.Column(db.String(16), nullable=False, default='auto')
    timezone_iana = db.Column(db.String(64), nullable=True)

    tg_auth_key = db.Column(db.String(120), unique=True, nullable=True)
    tg_id = db.Column(db.BigInteger, nullable=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=True, index=True)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True)
    telegram_linked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    creator_bot_mode = db.Column(db.String(20), default='ADMIN', nullable=False)
    parent_link_code = db.Column(db.String(20), nullable=True, unique=True, index=True)

    def get_children(self):
        """Возвращает список привязанных учеников (User objects)."""
        ties = FamilyTie.query.filter(
            FamilyTie.parent_id == self.id,
            FamilyTie.is_confirmed == True
        ).all()
        child_ids = [t.student_id for t in ties]
        if not child_ids:
            return []
        return User.query.filter(User.id.in_(child_ids)).all()

    def get_parents(self):
        """Возвращает список привязанных родителей (User objects)."""
        ties = FamilyTie.query.filter(
            FamilyTie.student_id == self.id,
            FamilyTie.is_confirmed == True
        ).all()
        parent_ids = [t.parent_id for t in ties]
        if not parent_ids:
            return []
        return User.query.filter(User.id.in_(parent_ids)).all()

    def generate_parent_code(self):
        """Генерирует или возвращает уникальный 6-значный код привязки для родителей (например, BS-893A)."""
        if getattr(self, 'parent_link_code', None):
            return self.parent_link_code
        import random, string
        chars = string.ascii_uppercase + string.digits
        for _ in range(20):
            code = "BS-" + "".join(random.choices(chars, k=4))
            existing = User.query.filter_by(parent_link_code=code).first()
            if not existing:
                self.parent_link_code = code
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                return code
        fallback = f"BS-{self.id:04d}"
        self.parent_link_code = fallback
        return fallback

    @property
    def link_code(self):
        return self.generate_parent_code()

    @property
    def full_name(self):
        return getattr(self, '_full_name', None) or self.username or ''

    @full_name.setter
    def full_name(self, val):
        self._full_name = val

    def get_id(self):
        return str(self.id)
    
    def is_authenticated(self):
        return True
    
    def is_anonymous(self):
        return False
    
    user_roles = db.relationship('UserRole', backref='user', lazy='select', cascade='all, delete-orphan', foreign_keys='UserRole.user_id')

    def roles(self):
        """Список ролей пользователя (объединение из UserRole; при отсутствии записей — [role])."""
        # Flask-Login can retain the user object while a nested application
        # context has already removed its SQLAlchemy session.  Maintenance and
        # access hooks must still be able to use the primary role in that case.
        from sqlalchemy.orm.exc import DetachedInstanceError

        try:
            user_roles = self.user_roles
        except DetachedInstanceError:
            state = self._sa_instance_state
            primary_role = state.dict.get('role')
            if primary_role:
                return [primary_role]

            # A detached instance can also have expired scalar attributes.
            # Use its identity to read only the primary role in the active
            # request session instead of attempting to reattach the object.
            identity = state.identity
            if identity:
                primary_role = db.session.query(type(self).role).filter_by(id=identity[0]).scalar()
                return [primary_role] if primary_role else []
            return []

        roles_set = {ur.role for ur in user_roles} if user_roles else set()
        if self.role:
            roles_set.add(self.role)
        try:
            from flask import session
            sandbox_role = session.get('sandbox_role')
            if sandbox_role:
                roles_set.add(sandbox_role)
        except RuntimeError:
            pass
        return list(roles_set)

    def is_admin(self):
        """Проверка, является ли пользователь администратором или главным администратором"""
        return 'admin' in self.roles() or 'chief_admin' in self.roles()

    def is_tutor(self):
        """Проверка, является ли пользователь тьютором (creator также может работать как tutor)"""
        r = self.roles()
        return 'tutor' in r or 'creator' in r

    def is_student(self):
        """Проверка, является ли пользователь учеником"""
        return 'student' in self.roles()

    def is_parent(self):
        """Проверка, является ли пользователь родителем"""
        return 'parent' in self.roles()

    def is_chief_tester(self):
        return 'chief_tester' in self.roles()

    def is_designer(self):
        return 'designer' in self.roles()

    def is_chief_admin(self):
        return 'chief_admin' in self.roles()

    def is_content_maker(self):
        return 'content_maker' in self.roles()

    def is_tester(self):
        """Проверка, является ли пользователь тестировщиком (обычным)"""
        return 'tester' in self.roles()

    def is_creator(self):
        """Проверка, является ли пользователь создателем"""
        return 'creator' in self.roles()

    def get_role_display(self):
        """Возвращает отображаемое название основной роли."""
        role_map = {
            'creator': 'Создатель',
            'chief_admin': 'Старший администратор',
            'admin': 'Администратор',
            'chief_tester': 'Главный тестировщик',
            'content_maker': 'Контент мейкер',
            'tutor': 'Преподаватель',
            'designer': 'Графический дизайнер',
            'tester': 'Тестировщик',
            'student': 'Ученик',
            'parent': 'Родитель',
        }
        return role_map.get(self.role, self.role)

    def get_roles_display(self):
        """Возвращает список отображаемых названий всех ролей пользователя."""
        role_map = {
            'creator': 'Создатель',
            'chief_admin': 'Старший администратор',
            'admin': 'Администратор',
            'chief_tester': 'Главный тестировщик',
            'content_maker': 'Контент мейкер',
            'tutor': 'Преподаватель',
            'designer': 'Графический дизайнер',
            'tester': 'Тестировщик',
            'student': 'Ученик',
            'parent': 'Родитель',
        }
        return [role_map.get(r, r) for r in self.roles()]

    ROLE_STRENGTH_ORDER = ('creator', 'chief_admin', 'admin', 'tutor', 'parent', 'student', 'chief_tester', 'content_maker', 'designer', 'tester')

    def get_primary_role_display(self):
        """Возвращает отображаемое название «главной» роли (для бейджа у авы): creator > chief_admin > admin > ..."""
        role_map = {
            'creator': 'Создатель',
            'chief_admin': 'Старший администратор',
            'admin': 'Администратор',
            'chief_tester': 'Главный тестировщик',
            'content_maker': 'Контент мейкер',
            'tutor': 'Преподаватель',
            'designer': 'Графический дизайнер',
            'tester': 'Тестировщик',
            'student': 'Ученик',
            'parent': 'Родитель',
        }
        r = self.roles()
        if not r:
            return role_map.get(self.role, self.role or '—')
        for slug in self.ROLE_STRENGTH_ORDER:
            if slug in r:
                return role_map.get(slug, slug)
        return role_map.get(r[0], r[0])
    
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

    def is_online_now(self, online_window_seconds: int = 120) -> bool:
        """True, если пользователь был активен недавно.

        psycopg2 сохраняет tz-aware datetime в TIMESTAMP WITHOUT TIME ZONE,
        конвертируя в UTC (PostgreSQL приводит значение с timezone к UTC перед
        сохранением в колонку без timezone). Поэтому сравниваем через UTC.
        """
        if not self.presence_last_seen_at:
            return False
        try:
            from datetime import datetime as _dt, timezone as _tz
            seen = self.presence_last_seen_at
            if getattr(seen, 'tzinfo', None) is not None:
                # Если вдруг хранится tz-aware — приводим к UTC
                now_utc = _dt.now(_tz.utc)
                delta_sec = (now_utc - seen.astimezone(_tz.utc)).total_seconds()
            else:
                # Naive UTC (psycopg2 конвертировал Moscow → UTC при сохранении)
                now_utc_naive = _dt.utcnow()
                delta_sec = (now_utc_naive - seen).total_seconds()
            return 0.0 <= delta_sec <= max(30, int(online_window_seconds or 120))
        except Exception:
            return False

    def presence_state_label(self) -> str:
        """Человекочитаемое состояние присутствия."""
        return 'В сети' if self.is_online_now() else 'Не в сети'

    def get_live_activity_text(self):
        """Текущая авто-активность пользователя."""
        text = (self.presence_activity_text or '').strip()
        return text or None

    custom_permissions = db.Column(db.JSON, nullable=True)

    schedule_ics_token = db.Column(db.String(120), nullable=True, unique=True, index=True)

    # QA: пользователь из пула тестовых профилей (3 ученика, 3 препода, 3 родителя, 1 админ)
    is_qa_pool = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Демо-пользователь (временный)
    is_demo_user = db.Column(db.Boolean, default=False, nullable=False, index=True)

class TelegramAuthCode(db.Model):
    """Одноразовые 6-8 значные коды для привязки Telegram-аккаунта"""
    __tablename__ = 'telegram_auth_codes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    user = db.relationship('User', foreign_keys=[user_id])

class RolePermission(db.Model):
    __tablename__ = 'RolePermissions'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(50), nullable=False)
    permission_name = db.Column(db.String(100), nullable=False)
    is_enabled = db.Column(db.Boolean, default=False)
    
    __table_args__ = (
        db.UniqueConstraint('role', 'permission_name', name='uq_role_permission'),
    )


class UserRole(db.Model):
    """Назначенные роли пользователя (один пользователь может иметь несколько ролей; права объединяются)."""
    __tablename__ = 'UserRoles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(50), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'role', name='uq_user_role'),
    )


class UserNotification(db.Model):
    """Внутреннее уведомление (in-app)."""
    __tablename__ = 'UserNotifications'

    notification_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)

    kind = db.Column(db.String(50), nullable=False, default='generic', index=True)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=True)
    link_url = db.Column(db.Text, nullable=True)
    meta = db.Column(db.JSON, nullable=True)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    telegram_sent = db.Column(db.Boolean, default=False, nullable=False, index=True)  # Отправлено ли в Telegram
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))


class PendingAssignmentNotification(db.Model):
    """Отложенные уведомления о прикрепленных заданиях (дебаунс 5 минут)."""
    __tablename__ = 'PendingAssignmentNotifications'

    pending_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    assignment_type = db.Column(db.String(50), nullable=False, index=True)  # homework|classwork|exam
    task_ids = db.Column(db.JSON, nullable=True)
    link_url = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    last_activity_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('lesson_id', 'assignment_type', name='uq_pending_assignment_notification'),
    )


class LessonMessage(db.Model):
    """Сообщение в диалоге по уроку (ученик ↔ преподаватель)."""
    __tablename__ = 'LessonMessages'

    message_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)

    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    lesson = db.relationship('Lesson', foreign_keys=[lesson_id], backref=db.backref('messages', lazy=True, cascade='all, delete-orphan'))
    author = db.relationship('User', foreign_keys=[author_user_id])


class LessonTeacherHomeworkNote(db.Model):
    """Приватная заметка преподавателя по итогам урока с отложенным напоминанием."""
    __tablename__ = 'LessonTeacherHomeworkNotes'

    note_id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, index=True)
    teacher_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)

    homework_text = db.Column(db.Text, nullable=False)
    remind_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    reminder_sent_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    is_sent = db.Column(db.Boolean, default=False, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    lesson = db.relationship('Lesson', foreign_keys=[lesson_id], backref=db.backref('teacher_homework_notes', lazy=True, cascade='all, delete-orphan'))
    teacher = db.relationship('User', foreign_keys=[teacher_user_id])


class CallRequest(db.Model):
    """Заявка ученика на созвон/консультацию."""
    __tablename__ = 'CallRequests'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)

    preferred_at = db.Column(db.DateTime, nullable=True)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='new', nullable=False, index=True)  # new|seen|scheduled|closed

    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])


class LessonWhiteboard(db.Model):
    """Интерактивная доска Miro, привязанная к уроку."""
    __tablename__ = 'LessonWhiteboards'

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=False, unique=True, index=True)
    
    miro_board_id = db.Column(db.String(100), nullable=False, index=True)  # ID доски в Miro
    miro_board_url = db.Column(db.String(500), nullable=True)  # Полная ссылка на доску (для редактирования)
    miro_view_link = db.Column(db.String(500), nullable=True)  # Публичная ссылка для просмотра
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Активна ли доска (во время урока = True)
    allow_student_edit = db.Column(db.Boolean, default=True, nullable=False)  # Может ли ученик редактировать
    
    board_name = db.Column(db.String(200), nullable=True)  # Название доски
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    lesson = db.relationship('Lesson', foreign_keys=[lesson_id], backref=db.backref('whiteboard', uselist=False, lazy=True))


class MiroUserToken(db.Model):
    """Токены Miro OAuth для пользователей (позволяет редактировать доски в iframe)."""
    __tablename__ = 'MiroUserTokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, unique=True, index=True)
    
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=True)
    token_type = db.Column(db.String(50), default='bearer')
    
    expires_at = db.Column(db.DateTime, nullable=True)  # Когда истекает access_token
    
    miro_user_id = db.Column(db.String(100), nullable=True)
    miro_team_id = db.Column(db.String(100), nullable=True)
    
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    user = db.relationship('User', backref=db.backref('miro_token', uselist=False, lazy=True))


class ReferralCode(db.Model):
    """Реферальный код для демо-версии и отслеживания трафика."""
    __tablename__ = 'ReferralCodes'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    usage_limit = db.Column(db.Integer, nullable=True)  # NULL = безлимитно
    usage_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    
    creator = db.relationship('User', foreign_keys=[creator_id], backref='created_referral_codes')

    def __repr__(self):
        return f'<ReferralCode {self.code} by {self.creator_id}>'


class ReferralUsage(db.Model):
    """Лог использования реферальных кодов при старте демо-версии."""
    __tablename__ = 'ReferralUsage'
    id = db.Column(db.Integer, primary_key=True)
    referral_code_id = db.Column(db.Integer, db.ForeignKey('ReferralCodes.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)  # Демо-пользователь
    created_at = db.Column(db.DateTime, default=moscow_now)
    
    referral_code = db.relationship('ReferralCode', backref='usages')
    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('referral_code_id', 'user_id', name='uq_referral_usage_per_user'),
    )

    def __repr__(self):
        return f'<ReferralUsage code_id={self.referral_code_id} user_id={self.user_id}>'


class PromoCode(db.Model):
    """Промокод для скидок, бонусных уроков или бесплатного доступа."""
    __tablename__ = 'PromoCodes'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    
    discount_percent = db.Column(db.Integer, nullable=True)     # Скидка в процентах (например, 20 для 20%)
    discount_rub = db.Column(db.Integer, nullable=True)         # Скидка в рублях (например, 500 для 500 руб)
    bonus_lessons = db.Column(db.Integer, nullable=True)        # Бонусные уроки (например, +2 урока)
    bonus_days = db.Column(db.Integer, nullable=True)           # Дополнительные дни подписки (например, +7 дней)
    
    plan_id = db.Column(db.Integer, db.ForeignKey('TariffPlans.plan_id'), nullable=True, index=True)
    
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    usage_limit = db.Column(db.Integer, nullable=True)          # NULL = безлимитно
    usage_count = db.Column(db.Integer, default=0, nullable=False)
    
    starts_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    
    plan = db.relationship('TariffPlan', foreign_keys=[plan_id])

    def __repr__(self):
        return f'<PromoCode {self.code}>'


class PromoCodeUsage(db.Model):
    """История использования промокодов."""
    __tablename__ = 'PromoCodeUsage'

    id = db.Column(db.Integer, primary_key=True)
    promocode_id = db.Column(db.Integer, db.ForeignKey('PromoCodes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('UserSubscriptions.subscription_id'), nullable=True, index=True)
    applied_at = db.Column(db.DateTime, default=moscow_now, nullable=False)

    promocode = db.relationship('PromoCode', backref='usages')
    user = db.relationship('User', foreign_keys=[user_id])
    subscription = db.relationship('UserSubscription', foreign_keys=[subscription_id])

    __table_args__ = (
        db.UniqueConstraint('promocode_id', 'user_id', name='uq_promocode_usage_per_user'),
    )

    def __repr__(self):
        return f'<PromoCodeUsage code_id={self.promocode_id} user_id={self.user_id}>'


class TeacherStudent(db.Model):
    """Таблица связи (Many-to-Many) Преподавателя и Ученика"""
    __tablename__ = 'teacher_students'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='active', nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='teacher_students')
    student_user = db.relationship('User', foreign_keys=[student_id], backref='student_teachers')

    __table_args__ = (Index('ix_teacher_student_unique', 'teacher_id', 'student_id', unique=True),)

    def __repr__(self):
        return f'<TeacherStudent teacher:{self.teacher_id} -> student:{self.student_id}>'


class InviteLink(db.Model):
    """
    Приглашение в систему (ученика или родителя).

    Flow:
    - тьютор/система создаёт invite (роль + optional student_id / teacher_id)
    - пользователь открывает /register/student/<token> или /register/parent/<token>
    - invite фиксируется как used
    """
    __tablename__ = 'InviteLinks'

    invite_id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)

    email = db.Column(db.String(200), nullable=True, default='', index=True)
    role = db.Column(db.String(50), nullable=False, index=True)  # student|parent|tutor|...
    note = db.Column(db.Text, nullable=True)

    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    used_at = db.Column(db.DateTime, nullable=True, index=True)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)

    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    teacher = db.relationship('User', foreign_keys=[teacher_id])
    used_by = db.relationship('User', foreign_keys=[used_by_user_id])
    student = db.relationship('Student', foreign_keys=[student_id])

    @property
    def is_valid(self) -> bool:
        if self.used_at or self.revoked_at:
            return False
        if self.expires_at:
            now_val = moscow_now().replace(tzinfo=None)
            exp_val = self.expires_at.replace(tzinfo=None) if hasattr(self.expires_at, 'replace') else self.expires_at
            if now_val > exp_val:
                return False
        return True

    def mark_used(self, user_id: int | None = None):
        self.used_at = moscow_now()
        if user_id:
            self.used_by_user_id = user_id

    def revoke(self):
        self.revoked_at = moscow_now()


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
    estimated_time = db.Column(db.Integer, default=45, nullable=True)  # Время выполнения в минутах
    course_id = db.Column(db.Integer, nullable=True)
    
    template_tasks = db.relationship('TemplateTask', back_populates='template', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def __repr__(self):
        return f'<TaskTemplate {self.name} ({self.template_type})>'

    @property
    def id(self):
        return self.template_id

    @property
    def title(self):
        return self.name

    @title.setter
    def title(self, val):
        self.name = val

    @property
    def teacher_id(self):
        return self.created_by

    @teacher_id.setter
    def teacher_id(self, val):
        self.created_by = val

    @property
    def tasks_count(self):
        return len(self.template_tasks) if self.template_tasks else 0

class TemplateTask(db.Model):
    """Связь между шаблоном и заданиями"""
    __tablename__ = 'TemplateTasks'
    template_task_id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('TaskTemplates.template_id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False)
    order = db.Column(db.Integer, default=0)  # Порядок задания в шаблоне
    created_at = db.Column(db.DateTime, default=moscow_now)
    
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



class UserProfile(db.Model):
    """Расширенный профиль пользователя (1-to-1 с User)"""
    __tablename__ = 'UserProfiles'
    profile_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), unique=True, nullable=False)
    
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    middle_name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=True)  # Для SMS уведомлений
    telegram_id = db.Column(db.String(100), nullable=True)  # Legacy: username/ссылка
    timezone = db.Column(db.String(50), default='Europe/Moscow', nullable=False)
    avatar_url = db.Column(db.String(500), nullable=True)
    cover_url = db.Column(db.String(500), nullable=True)  # Баннер/обложка профиля (GIF или изображение), для креатора

    telegram_chat_id = db.Column(db.BigInteger, nullable=True, unique=True, index=True)  # Chat ID для отправки уведомлений
    telegram_link_code = db.Column(db.String(32), nullable=True)  # Одноразовый код привязки
    telegram_link_code_expires = db.Column(db.DateTime, nullable=True)  # Срок действия кода
    telegram_link_token = db.Column(db.String(64), nullable=True, unique=True, index=True)  # Токен для t.me deep link ?start=
    telegram_link_token_expires = db.Column(db.DateTime, nullable=True)
    telegram_last_interaction_at = db.Column(db.DateTime, nullable=True, index=True)  # Последняя активность в боте (webhook)
    telegram_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)  # Включены ли уведомления
    
    tg_notify_lesson_reminder = db.Column(db.Boolean, default=True, nullable=False)  # Напоминания об уроках
    tg_notify_homework_checked = db.Column(db.Boolean, default=True, nullable=False)  # ДЗ проверено
    tg_notify_homework_returned = db.Column(db.Boolean, default=True, nullable=False)  # ДЗ возвращено на доработку
    tg_notify_new_message = db.Column(db.Boolean, default=True, nullable=False)  # Новое сообщение от преподавателя
    tg_notify_lesson_scheduled = db.Column(db.Boolean, default=True, nullable=False)  # Урок запланирован
    tg_notify_low_lessons = db.Column(db.Boolean, default=True, nullable=False)  # Уроки заканчиваются
    tg_notify_news = db.Column(db.Boolean, default=True, nullable=False)  # Новости платформы (по умолчанию вкл)
    
    tg_notify_referral_used = db.Column(db.Boolean, default=True, nullable=False)  # Новый реферал (для админов)
    tg_notify_homework_submitted = db.Column(db.Boolean, default=True, nullable=False)  # ДЗ сдано (для учителей)
    tg_notify_system_errors = db.Column(db.Boolean, default=True, nullable=False)  # Системные ошибки (для админов)
    tg_notify_subscription_expiring = db.Column(db.Boolean, default=True, nullable=False)  # Подписка истекает
    tg_notify_bug_report_reply = db.Column(db.Boolean, default=True, nullable=False)  # Ответ на баг-репорт
    tg_notify_daily_digest = db.Column(db.Boolean, default=False, nullable=False)  # Утренний дайджест (opt-in)
    tg_quiet_hours_start = db.Column(db.Integer, nullable=True)  # Тихие часы: начало (0-23, МСК)
    tg_quiet_hours_end = db.Column(db.Integer, nullable=True)    # Тихие часы: конец (0-23, МСК)

    internal_notes = db.Column(db.Text, nullable=True)
    profile_onboarding_completed_at = db.Column(db.DateTime, nullable=True, index=True)

    # Только для создателя: фиксированная строка активности «техно-магия» поверх авто-статусов
    presence_techno_magic_enabled = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    user = db.relationship('User', backref=db.backref('profile', uselist=False), uselist=False)
    
    def __repr__(self):
        return f'<UserProfile {self.user_id}: {self.first_name} {self.last_name}>'


class TelegramStartLead(db.Model):
    """Telegram-пользователь, который писал боту, но ещё не получил роль/профиль."""
    __tablename__ = 'TelegramStartLeads'

    lead_id = db.Column(db.Integer, primary_key=True)
    telegram_chat_id = db.Column(db.BigInteger, nullable=False, unique=True, index=True)
    telegram_username = db.Column(db.String(100), nullable=True, index=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    is_authorized = db.Column(db.Boolean, default=False, nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    last_seen_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    assigned_user = db.relationship('User', foreign_keys=[assigned_user_id])

    def __repr__(self):
        return f'<TelegramStartLead chat_id={self.telegram_chat_id} authorized={self.is_authorized}>'


class TelegramBroadcast(db.Model):
    """Массовая рассылка в Telegram (инициатор — creator/chief_admin через Mini App)."""
    __tablename__ = 'TelegramBroadcasts'
    broadcast_id = db.Column(db.Integer, primary_key=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    message_text = db.Column(db.Text, nullable=False)
    photo_url = db.Column(db.String(2000), nullable=True)  # Опционально URL для sendPhoto
    status = db.Column(db.String(32), default='pending', nullable=False)  # pending|running|completed|failed|cancelled
    recipient_scope = db.Column(db.String(64), default='all_linked_students', nullable=False)
    total_planned = db.Column(db.Integer, default=0, nullable=False)
    sent_ok = db.Column(db.Integer, default=0, nullable=False)
    sent_failed = db.Column(db.Integer, default=0, nullable=False)
    cursor_last_user_id = db.Column(db.Integer, nullable=True, index=True)  # для пошаговой обработки
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f'<TelegramBroadcast {self.broadcast_id} status={self.status}>'


class SubmissionTelegramDeadlineSent(db.Model):
    """Факт отправки напоминания о дедлайне работы (антиспам)."""
    __tablename__ = 'SubmissionTelegramDeadlineSents'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id'), nullable=False, index=True)
    window_key = db.Column(db.String(16), nullable=False)  # e.g. 24h, 1h
    sent_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('submission_id', 'window_key', name='uq_submission_deadline_window'),
    )

    def __repr__(self):
        return f'<SubmissionTelegramDeadlineSent sub={self.submission_id} {self.window_key}>'


class BotAdmin(db.Model):
    """Администраторы Telegram-бота (управляются из админки платформы)."""
    __tablename__ = 'BotAdmins'
    admin_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, unique=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    user = db.relationship('User', foreign_keys=[user_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f'<BotAdmin user_id={self.user_id} active={self.is_active}>'


class BotErrorReport(db.Model):
    """Сообщения об ошибках от учеников в Telegram-боте."""
    __tablename__ = 'BotErrorReports'
    report_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True, index=True)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), default='new', nullable=False)  # new|in_progress|answered|closed
    admin_reply = db.Column(db.Text, nullable=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    reply_sent_at = db.Column(db.DateTime, nullable=True)
    screenshot_file_id = db.Column(db.String(200), nullable=True)  # Telegram file_id скриншота
    creator_tg_message_id = db.Column(db.BigInteger, nullable=True)  # ID сообщения боту создателю (для reply)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    replied_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
    admin_user = db.relationship('User', foreign_keys=[admin_user_id])

    def __repr__(self):
        return f'<BotErrorReport {self.report_id} status={self.status}>'


class FamilyTie(db.Model):
    """Связь между Родителем и Учеником (Many-to-Many)"""
    __tablename__ = 'FamilyTies'
    tie_id = db.Column(db.Integer, primary_key=True)
    
    parent_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    
    access_level = db.Column(db.String(50), default='full', nullable=False)
    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)  # Подтверждение связи
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    parent = db.relationship('User', foreign_keys=[parent_id], backref='parent_children')
    student = db.relationship('User', foreign_keys=[student_id], backref='student_parents')
    
    __table_args__ = (Index('ix_family_tie_unique', 'parent_id', 'student_id', unique=True),)

    @property
    def id(self):
        return self.tie_id

    @property
    def status(self):
        return 'active' if self.is_confirmed else 'pending'

    @status.setter
    def status(self, val):
        self.is_confirmed = (val == 'active')

    def __repr__(self):
        return f'<FamilyTie parent:{self.parent_id} -> student:{self.student_id}>'


ParentStudentLink = FamilyTie


class UserAchievement(db.Model):
    """Достижения, полученные учениками"""
    __tablename__ = 'UserAchievements'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    achievement_key = db.Column(db.String(100), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=moscow_now, nullable=False)

    student = db.relationship('Student', backref=db.backref('achievements_list', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (Index('ix_student_achievement_unique', 'student_id', 'achievement_key', unique=True),)

class SystemSetting(db.Model):
    """Таблица системных настроек платформы (BooStudy V2)"""
    __tablename__ = 'SystemSettings'
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    @classmethod
    def get_value(cls, key: str, default: str = None) -> str:
        try:
            row = cls.query.filter_by(setting_key=key).first()
            return row.setting_value if row and row.setting_value is not None else default
        except Exception:
            return default

    @classmethod
    def set_value(cls, key: str, value: str, description: str = None) -> bool:
        try:
            row = cls.query.filter_by(setting_key=key).first()
            if not row:
                row = cls(setting_key=key, setting_value=str(value), description=description)
                db.session.add(row)
            else:
                row.setting_value = str(value)
                if description:
                    row.description = description
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            return False

    def __repr__(self):
        return f'<SystemSetting {self.setting_key}={self.setting_value}>'


class Enrollment(db.Model):
    """Учебный контракт: связь Ученик - Тьютор - Предмет"""
    __tablename__ = 'Enrollments'
    enrollment_id = db.Column(db.Integer, primary_key=True)
    
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    
    subject = db.Column(db.String(100), nullable=False)
    
    status = db.Column(db.String(50), default='active', nullable=False)
    
    settings = db.Column(JSON, nullable=True)  # Например, цена часа, особые условия
    
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    
    student = db.relationship('User', foreign_keys=[student_id], backref='student_enrollments')
    tutor = db.relationship('User', foreign_keys=[tutor_id], backref='tutor_enrollments')
    
    def __repr__(self):
        return f'<Enrollment student:{self.student_id} - tutor:{self.tutor_id} ({self.subject})>'



class TariffGroup(db.Model):
    """Группа тарифов для ручной сортировки/группировки в UI."""
    __tablename__ = 'TariffGroups'

    group_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)


class TariffPlan(db.Model):
    """Тариф/план (оплата и доступ управляются вручную админом)."""
    __tablename__ = 'TariffPlans'

    plan_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    group_id = db.Column(db.Integer, db.ForeignKey('TariffGroups.group_id'), nullable=True, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False, index=True)

    price_rub = db.Column(db.Integer, nullable=True)     # цена в рублях (информативно)
    price_per_lesson_rub = db.Column(db.Integer, nullable=True)  # цена за урок (информативно)
    period_days = db.Column(db.Integer, nullable=True)   # длительность доступа (информативно)
    lessons_count = db.Column(db.Integer, nullable=True)  # количество уроков в тарифе

    allow_lessons = db.Column(db.Boolean, nullable=True)   # None => не ограничиваем (backward compatible)
    allow_trainer = db.Column(db.Boolean, nullable=True)   # None => не ограничиваем (backward compatible)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    group = db.relationship('TariffGroup', foreign_keys=[group_id])


class UserSubscription(db.Model):
    """Подписка пользователя на тариф (выдача доступа вручную)."""
    __tablename__ = 'UserSubscriptions'

    subscription_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('TariffPlans.plan_id'), nullable=True, index=True)

    status = db.Column(db.String(30), default='active', nullable=False, index=True)  # active|expired|cancelled|paused
    started_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    lessons_remaining = db.Column(db.Integer, nullable=True)  # оставшееся количество уроков
    note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    user = db.relationship('User', foreign_keys=[user_id])
    plan = db.relationship('TariffPlan', foreign_keys=[plan_id])


class TrainerSession(db.Model):
    """
    Сессия/попытка в ИИ-тренажёре.

    Важно: хранится отдельно от LessonTask/Assignments. Используется для истории и (в дальнейшем)
    для анти-повтора между уроками и тренажёром.
    """
    __tablename__ = 'TrainerSessions'

    session_id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)

    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=True, index=True)
    task_type = db.Column(db.Integer, nullable=True, index=True)

    language = db.Column(db.String(50), default='python', nullable=False)
    code = db.Column(db.Text, nullable=True)

    analysis = db.Column(db.JSON, nullable=True)
    tests = db.Column(db.JSON, nullable=True)
    messages = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False, index=True)

    user = db.relationship('User', foreign_keys=[user_id])
    student = db.relationship('Student', foreign_keys=[student_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])

    __table_args__ = (
        Index('ix_trainer_sessions_user_task_created', 'user_id', 'task_id', 'created_at'),
    )


class TrainerLlmLog(db.Model):
    """
    Логи обращений к LLM из тренажёра (через platform proxy).

    Зачем:
    - отладка качества ответов
    - сбор датасета/промптов (без ключей!)
    - диагностика таймаутов/ошибок провайдера
    """
    __tablename__ = 'TrainerLlmLogs'

    log_id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)

    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=True, index=True)
    task_type = db.Column(db.Integer, nullable=True, index=True)

    request_kind = db.Column(db.String(30), default='chat', nullable=False, index=True)  # chat|ping
    provider = db.Column(db.String(30), nullable=True, index=True)  # gigachat
    model = db.Column(db.String(120), nullable=True)

    messages = db.Column(db.JSON, nullable=True)
    answer = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)

    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    user = db.relationship('User', foreign_keys=[user_id])
    student = db.relationship('Student', foreign_keys=[student_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])

    __table_args__ = (
        Index('ix_trainer_llm_user_created', 'user_id', 'created_at'),
    )


class UserConsent(db.Model):
    """Лог согласий (оферта/политика)."""
    __tablename__ = 'UserConsents'

    consent_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)

    document_key = db.Column(db.String(60), nullable=False, index=True)  # offer|privacy|...
    version = db.Column(db.String(40), nullable=False, default='1', index=True)
    accepted_at = db.Column(db.DateTime, default=moscow_now, index=True)

    ip_address = db.Column(db.Text, nullable=True)
    user_agent = db.Column(db.Text, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])



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
    
    deadline = db.Column(db.DateTime(timezone=True), nullable=False)  # Дедлайн сдачи (UTC)
    hard_deadline = db.Column(db.Boolean, default=False)  # Если True - нельзя сдать после дедлайна
    hide_before_start = db.Column(db.Boolean, default=True, nullable=False)  # Скрывать условия до нажатия "Начать выполнение"
    allow_separate_submission = db.Column(db.Boolean, default=True, nullable=False)  # Разрешить сдавать по одной задаче
    time_limit_minutes = db.Column(db.Integer, nullable=True)  # Ограничение времени выполнения (для exam/test)
    time_limit_strict = db.Column(db.Boolean, default=False, nullable=False)  # True: после истечения таймера блокировать сдачу; False: только помечать как не уложился
    max_attempts_default = db.Column(db.Integer, nullable=True)  # Макс. попыток сдачи по умолчанию (1 если NULL)
    attempts_per_task = db.Column(db.Boolean, default=False, nullable=False)  # True: попытки считаются на каждое задание; False: на всю работу

    created_by_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=True)
    exam_course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)

    rubric_template_id = db.Column(db.Integer, db.ForeignKey('RubricTemplates.rubric_id'), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Можно ли еще работать с этой работой

    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_assignments')
    lesson = db.relationship('Lesson', backref='assignments')
    exam_course = db.relationship('Course', foreign_keys=[exam_course_id])
    tasks = db.relationship('AssignmentTask', back_populates='assignment', lazy=True, cascade='all, delete-orphan')
    submissions = db.relationship('Submission', back_populates='assignment', lazy=True, cascade='all, delete-orphan')
    rubric_template = db.relationship('RubricTemplate', foreign_keys=[rubric_template_id])
    
    def get_effective_max_attempts(self) -> int:
        """Учитывает max_attempts_default работы и переопределение по заданиям (минимум по всем задачам)."""
        default = max(1, int(self.max_attempts_default or 1))
        if not self.tasks:
            return default
        effective = default
        for t in self.tasks:
            task_max = int(t.max_attempts) if getattr(t, 'max_attempts', None) is not None else default
            effective = min(effective, max(1, task_max))
        return max(1, effective)

    def get_effective_max_attempts_for_task(self, assignment_task) -> int:
        """Макс. попыток для конкретного задания: AssignmentTask.max_attempts или max_attempts_default."""
        default = max(1, int(self.max_attempts_default or 1))
        if getattr(assignment_task, 'max_attempts', None) is not None:
            return max(1, int(assignment_task.max_attempts))
        return default

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
    
    order_index = db.Column(db.Integer, nullable=False, default=0)  # Порядок отображения
    
    max_score = db.Column(db.Integer, nullable=False, default=1)  # Максимальный балл за задачу
    max_attempts = db.Column(db.Integer, nullable=True)  # Переопределение лимита попыток для этого задания (NULL = из Assignment)
    
    answer_override = db.Column(db.Text, nullable=True)  # Эталонный ответ для сравнения (если задан — используется вместо task.answer)
    requires_manual_grading = db.Column(db.Boolean, default=False, nullable=False)  # Требует ли ручной проверки
    
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    
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
    
    status = db.Column(db.String(50), nullable=False, default='ASSIGNED')  
    
    assigned_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)  # Когда назначено
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Когда ученик начал выполнение
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Когда сдано
    graded_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Когда проверено
    
    is_late = db.Column(db.Boolean, default=False, nullable=False)  # Сдано с опозданием
    is_overtime = db.Column(db.Boolean, default=False, nullable=False)  # Сдано после истечения лимита времени (не уложился в таймер)

    total_score = db.Column(db.Integer, nullable=True)  # Общий балл
    max_score = db.Column(db.Integer, nullable=True)  # Максимальный возможный балл
    percentage = db.Column(db.Float, nullable=True)  # Процент выполнения
    
    teacher_feedback = db.Column(db.Text, nullable=True)

    rubric_template_id = db.Column(db.Integer, db.ForeignKey('RubricTemplates.rubric_id'), nullable=True, index=True)
    rubric_scores = db.Column(db.JSON, nullable=True)  # {"crit1": {"score": 1, "comment": "..."}, ...}
    
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    assignment = db.relationship('Assignment', back_populates='submissions')
    student = db.relationship('Student', backref='submissions')
    answers = db.relationship('Answer', back_populates='submission', lazy=True, cascade='all, delete-orphan')
    attempts = db.relationship('SubmissionAttempt', back_populates='submission', lazy=True, cascade='all, delete-orphan')
    rubric_template = db.relationship('RubricTemplate', foreign_keys=[rubric_template_id])
    
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
    
    value = db.Column(db.Text, nullable=True)  # Текст ответа или JSON для сложных ответов
    files = db.Column(JSON, nullable=True)  # Массив путей к прикрепленным файлам
    
    is_correct = db.Column(db.Boolean, nullable=True)  # Правильность ответа (для авто-проверки)
    score = db.Column(db.Integer, nullable=True)  # Балл за ответ
    max_score = db.Column(db.Integer, nullable=True)  # Максимальный балл (копия из AssignmentTask)
    
    teacher_comment = db.Column(db.Text, nullable=True)
    needs_revision = db.Column(db.Boolean, default=False, nullable=False)  # Вернуть это задание на доработку
    
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    submitted_separately_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Когда ученик нажал «Сдать задание» по этому ответу (при allow_separate_submission)
    attempts_used = db.Column(db.Integer, default=0, nullable=False)  # Сколько раз сдавали это задание (при attempts_per_task)
    student_code = db.Column(db.Text, nullable=True)  # Код ученика в редакторе (Python), для проверки преподавателем
    student_code_saved_at = db.Column(db.DateTime(timezone=True), nullable=True)  # Когда ученик нажал «Сохранить код»

    submission = db.relationship('Submission', back_populates='answers')
    assignment_task = db.relationship('AssignmentTask', back_populates='answers')
    
    __table_args__ = (
        db.UniqueConstraint('submission_id', 'assignment_task_id', name='uq_submission_task'),
    )
    
    def __repr__(self):
        return f'<Answer {self.answer_id}: submission {self.submission_id}, task {self.assignment_task_id}, score {self.score}>'


class CodePlaybackTrace(db.Model):
    """
    История редактирования кода для просмотра преподавателем.
    Хранит последовательность снапшотов кода и метаданных, чтобы можно было воспроизводить набор текста.
    """
    __tablename__ = 'CodePlaybackTraces'

    trace_id = db.Column(db.Integer, primary_key=True)
    context_type = db.Column(db.String(40), nullable=False, index=True)  # demo | lesson_task | submission_task
    context_id = db.Column(db.Integer, nullable=True, index=True)
    student_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, index=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('Answers.answer_id'), nullable=True, index=True)

    frames = db.Column(db.JSON, nullable=False, default=list)  # [{"ts":..., "code":..., "caret":[s,e], "action":...}, ...]
    meta = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    student_user = db.relationship('User', foreign_keys=[student_user_id])
    student_ref = db.relationship('Student', foreign_keys=[student_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])
    answer = db.relationship('Answer', foreign_keys=[answer_id])

    __table_args__ = (
        Index('ix_code_playback_trace_lookup', 'context_type', 'context_id', 'task_id', unique=False),
    )

    def __repr__(self):
        return f'<CodePlaybackTrace {self.trace_id}: {self.context_type}#{self.context_id}, task {self.task_id}>'


class CodeWorkspaceVersion(db.Model):
    """
    Версия кода workspace после автосохранения или ручного сохранения.
    Нужна для откатов и анализа эволюции решения.
    """
    __tablename__ = 'CodeWorkspaceVersions'

    version_id = db.Column(db.Integer, primary_key=True)
    context_type = db.Column(db.String(40), nullable=False, index=True)
    context_id = db.Column(db.Integer, nullable=True, index=True)
    student_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=True, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id'), nullable=False, index=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('Answers.answer_id'), nullable=True, index=True)

    code = db.Column(db.Text, nullable=False, default='')
    answer = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False, default='autosave')  # autosave | manual | restore
    snapshot = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    student_user = db.relationship('User', foreign_keys=[student_user_id])
    student_ref = db.relationship('Student', foreign_keys=[student_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])
    answer_ref = db.relationship('Answer', foreign_keys=[answer_id])

    __table_args__ = (
        Index('ix_code_workspace_version_lookup', 'context_type', 'context_id', 'task_id', 'created_at'),
    )

    def __repr__(self):
        return f'<CodeWorkspaceVersion {self.version_id}: {self.context_type}#{self.context_id}, task {self.task_id}>'


class SubmissionAttempt(db.Model):
    """
    Попытка сдачи работы (Submission) в новой системе Assignments.

    MVP: фиксируем факт сдачи и итог (когда есть), чтобы пересдачи не затирали историю.
    """
    __tablename__ = 'SubmissionAttempts'

    attempt_id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id'), nullable=False, index=True)
    attempt_no = db.Column(db.Integer, nullable=False, default=1, index=True)

    submitted_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    graded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(50), nullable=True)  # SUBMITTED/NEEDS_MANUAL_REVIEW/GRADED/RETURNED

    total_score = db.Column(db.Integer, nullable=True)
    max_score = db.Column(db.Integer, nullable=True)
    percentage = db.Column(db.Float, nullable=True)
    teacher_feedback = db.Column(db.Text, nullable=True)

    submission = db.relationship('Submission', back_populates='attempts')

    __table_args__ = (
        Index('ix_submission_attempt_unique', 'submission_id', 'attempt_no', unique=True),
    )


class SubmissionComment(db.Model):
    """
    Комментарии к сдаче работы (чат учитель-ученик)
    """
    __tablename__ = 'SubmissionComments'
    
    comment_id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    assignment_task_id = db.Column(db.Integer, db.ForeignKey('AssignmentTasks.assignment_task_id'), nullable=True)
    
    text = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    submission = db.relationship('Submission', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))
    author = db.relationship('User')
    assignment_task = db.relationship('AssignmentTask')
    
    def __repr__(self):
        return f'<Comment {self.comment_id}: submission {self.submission_id} by {self.author_id}>'


class SubmissionCommentThreadRead(db.Model):
    """
    До какого comment_id пользователь просмотрел чат по конкретному заданию в сдаче.
    Используется для точек «непрочитано» и сброса после открытия ветки (GET списка сообщений).
    """
    __tablename__ = 'SubmissionCommentThreadReads'

    read_id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id', ondelete='CASCADE'), nullable=False, index=True)
    assignment_task_id = db.Column(db.Integer, db.ForeignKey('AssignmentTasks.assignment_task_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    last_read_comment_id = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint('submission_id', 'assignment_task_id', 'user_id', name='uq_submission_comment_thread_read'),
    )

    def __repr__(self):
        return f'<ThreadRead sub={self.submission_id} task={self.assignment_task_id} user={self.user_id} up_to={self.last_read_comment_id}>'


class GradebookEntry(db.Model):
    """
    Запись журнала оценок (единая сущность).

    Использование:
    - manual: ручная запись (без привязки)
    - lesson: итог по уроку (lesson_id)
    - assignment: итог по работе/сдаче (submission_id)

    score/max_score можно хранить как баллы; percentage — вычислять на UI.
    """
    __tablename__ = 'GradebookEntries'

    entry_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)

    kind = db.Column(db.String(20), nullable=False, default='manual', index=True)  # manual|lesson|assignment
    category = db.Column(db.String(50), nullable=True, index=True)  # homework|classwork|exam|test|...

    title = db.Column(db.String(500), nullable=False)
    comment = db.Column(db.Text, nullable=True)

    score = db.Column(db.Integer, nullable=True)
    max_score = db.Column(db.Integer, nullable=True)
    grade_text = db.Column(db.String(50), nullable=True)  # например "5", "зачёт", "A"
    weight = db.Column(db.Integer, default=1, nullable=False)

    lesson_id = db.Column(db.Integer, db.ForeignKey('Lessons.lesson_id'), nullable=True, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id'), nullable=True, index=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id], backref=db.backref('gradebook_entries', lazy=True, cascade='all, delete-orphan'))
    lesson = db.relationship('Lesson', foreign_keys=[lesson_id])
    submission = db.relationship('Submission', foreign_keys=[submission_id])
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index('ix_gradebook_student_kind', 'student_id', 'kind'),
    )


# --- Модуль аналитики (Knowledge Graph, рейтинги, прогноз балла) ---

class Subject(db.Model):
    """Предмет (корень графа знаний): Информатика КЕГЭ, Математика и т.д."""
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    nodes = db.relationship('KnowledgeNode', back_populates='subject', lazy=True)


class KnowledgeNode(db.Model):
    """Узел знаний (тема/навык). Связь с заданием по task_number или через Tasks.knowledge_node_id."""
    __tablename__ = 'knowledge_nodes'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('knowledge_nodes.id'), nullable=True, index=True)

    name = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(32), nullable=False, index=True)

    base_rating = db.Column(db.Integer, default=1000)
    exam_points = db.Column(db.Integer, default=1)
    complexity_tier = db.Column(db.String(32), nullable=True)

    created_at = db.Column(db.DateTime, default=moscow_now)

    subject = db.relationship('Subject', back_populates='nodes')
    parent = db.relationship('KnowledgeNode', remote_side=[id])

    __table_args__ = (
        Index('ix_knowledge_nodes_subject_code', 'subject_id', 'code', unique=True),
    )


class UserMastery(db.Model):
    """Текущий рейтинг ученика по узлу знаний. Обновляется после каждого решения."""
    __tablename__ = 'user_mastery'
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('knowledge_nodes.id', ondelete='CASCADE'), primary_key=True)

    rating = db.Column(db.Float, default=1000.0, nullable=False)
    volatility = db.Column(db.Float, default=350.0, nullable=False)
    streak_days = db.Column(db.Integer, default=0, nullable=False)
    last_practiced_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=True)
    # MMR concept fields (per task type calibration state)
    solved_count = db.Column(db.Integer, default=0, nullable=False)
    calibration_done = db.Column(db.Boolean, default=False, nullable=False)

    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = db.relationship('User', foreign_keys=[user_id])
    node = db.relationship('KnowledgeNode', foreign_keys=[node_id])

    __table_args__ = (
        Index('ix_user_mastery_user_id', 'user_id'),
    )


class AnalyticsEvent(db.Model):
    """Журнал событий аналитики для аудита и пересчёта при смене алгоритма."""
    __tablename__ = 'analytics_events'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    # NULL — задание без привязки к графу знаний (старый банк, кастомные темы); см. AnalyticsEngine._resolve_task_knowledge_node
    node_id = db.Column(db.Integer, db.ForeignKey('knowledge_nodes.id', ondelete='CASCADE'), nullable=True, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id', ondelete='SET NULL'), nullable=True, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('Submissions.submission_id', ondelete='SET NULL'), nullable=True, index=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('Answers.answer_id', ondelete='SET NULL'), nullable=True, index=True)

    is_correct = db.Column(db.Boolean, nullable=False)
    task_difficulty = db.Column(db.Integer, nullable=True)   # difficulty_level задачи
    old_rating = db.Column(db.Float, nullable=True)
    new_rating = db.Column(db.Float, nullable=True)
    mmr_delta = db.Column(db.Float, nullable=True)
    task_type = db.Column(db.Integer, nullable=True, index=True)
    attempt_no = db.Column(db.Integer, nullable=True)
    mode = db.Column(db.String(32), nullable=True)
    time_spent_sec = db.Column(db.Integer, nullable=True)    # сколько секунд потратил ученик
    behavior_flags = db.Column(JSONBCompat, nullable=True)   # в PostgreSQL — JSONB; {"fast_fail": true, "fast_success_hard": true, ...}
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        Index('ix_analytics_events_user_timestamp', 'user_id', 'timestamp'),
        Index('ix_analytics_events_node_timestamp', 'node_id', 'timestamp'),
    )


class UserTaskMMR(db.Model):
    """
    Per-user per-task-type MMR snapshot used by trainer auto-match and dashboards.
    """
    __tablename__ = 'user_task_mmr'
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), primary_key=True)
    task_type = db.Column(db.Integer, primary_key=True)
    mmr = db.Column(db.Float, nullable=False, default=1000.0)
    solved_count = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        Index('ix_user_task_mmr_user', 'user_id'),
    )


class RematchQueue(db.Model):
    """
    Spaced repetition queue ("Реванш") with deferred review windows.
    """
    __tablename__ = 'rematch_queue'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id', ondelete='CASCADE'), nullable=False, index=True)
    task_type = db.Column(db.Integer, nullable=False, index=True)
    due_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    attempt_stage = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index('ix_rematch_queue_user_due', 'user_id', 'due_at'),
    )

class QATask(db.Model):
    __tablename__ = 'qa_tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='todo')  # todo, in_progress, review, done
    priority = db.Column(db.String(50), default='medium')  # low, medium, high, critical

    # task = задача Creator→Tester (на доске); bug_report = баг от тестера (отдельный список, Creator управляет)
    task_type = db.Column(db.String(30), default='task', nullable=False, index=True)

    reporter_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    assignee_ids = db.Column(db.JSON, nullable=True)  # список id исполнителей (главный тестер + тестеры)

    context_url = db.Column(db.String(500), nullable=True)
    target_user_id = db.Column(db.Integer, nullable=True)
    screenshot_path = db.Column(db.String(500), nullable=True)

    deadline = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    reporter = db.relationship('User', foreign_keys=[reporter_id])
    assignee = db.relationship('User', foreign_keys=[assignee_id])

class QAComment(db.Model):
    __tablename__ = 'qa_comments'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('qa_tasks.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    author = db.relationship('User', foreign_keys=[author_id])


class TheoryBlock(db.Model):
    """Теоретический блок по заданию экзамена (привязан к course_id + task_number)."""
    __tablename__ = 'TheoryBlocks'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('TheoryGroups.id', ondelete='SET NULL'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.String(500), nullable=True)
    read_minutes = db.Column(db.Integer, nullable=False, default=5, server_default='5')
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0', index=True)
    content = db.Column(db.Text, nullable=True)
    pdf_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)

    course = db.relationship('Course', foreign_keys=[course_id])
    group = db.relationship('TheoryGroup', foreign_keys=[group_id], back_populates='blocks')
    author = db.relationship('User', foreign_keys=[author_id])

    __table_args__ = (
        db.UniqueConstraint('course_id', 'task_number', name='uq_theory_course_task'),
    )


class StudentTheoryAccess(db.Model):
    """Запрет/разрешение просмотра теории по номеру задания для конкретного ученика.
    Если записи нет — доступ разрешён (по умолчанию). can_view=False — запретить просмотр."""
    __tablename__ = 'StudentTheoryAccess'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)
    can_view = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', 'task_number', name='uq_student_theory_access'),)

    student = db.relationship('Student', foreign_keys=[student_id])
    course = db.relationship('Course', foreign_keys=[course_id])


class TheoryGroup(db.Model):
    """Группа теории в рамках курса (например, Алгебра логики)."""
    __tablename__ = 'TheoryGroups'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id', ondelete='CASCADE'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0', index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    course = db.relationship('Course', foreign_keys=[course_id])
    creator = db.relationship('User', foreign_keys=[created_by])
    blocks = db.relationship('TheoryBlock', back_populates='group', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('course_id', 'name', name='uq_theory_group_course_name'),
    )


class StudentTheoryState(db.Model):
    """Состояние теории для ученика: закладки/прочитано."""
    __tablename__ = 'StudentTheoryState'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)

    is_bookmarked = db.Column(db.Boolean, default=False, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    reading_progress = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    last_position = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    last_opened_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', 'task_number', name='uq_student_theory_state'),)

    student = db.relationship('Student', foreign_keys=[student_id])
    course = db.relationship('Course', foreign_keys=[course_id])


class TheoryCheckpointAttempt(db.Model):
    """Ответ ученика на микро-проверку внутри теоретического блока."""
    __tablename__ = 'TheoryCheckpointAttempts'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    block_id = db.Column(db.Integer, db.ForeignKey('TheoryBlocks.id', ondelete='CASCADE'), nullable=False, index=True)
    checkpoint_key = db.Column(db.String(80), nullable=False)
    selected_answer = db.Column(db.String(500), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    attempts_count = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    answered_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    student = db.relationship('Student', foreign_keys=[student_id])
    block = db.relationship('TheoryBlock', foreign_keys=[block_id])

    __table_args__ = (
        db.UniqueConstraint('student_id', 'block_id', 'checkpoint_key', name='uq_theory_checkpoint_attempt'),
    )


class StudentTheoryNote(db.Model):
    """Личная заметка ученика к отдельному материалу теории."""
    __tablename__ = 'StudentTheoryNotes'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    block_id = db.Column(db.Integer, db.ForeignKey('TheoryBlocks.id', ondelete='CASCADE'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id])
    block = db.relationship('TheoryBlock', foreign_keys=[block_id])

    __table_args__ = (
        db.UniqueConstraint('student_id', 'block_id', name='uq_student_theory_note'),
    )


class TheoryStudyAssignment(db.Model):
    """Адресное назначение материала преподавателем для повторения или изучения."""
    __tablename__ = 'TheoryStudyAssignments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    block_id = db.Column(db.Integer, db.ForeignKey('TheoryBlocks.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_by_user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    message = db.Column(db.String(1000), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='assigned', server_default='assigned', index=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship('Student', foreign_keys=[student_id])
    block = db.relationship('TheoryBlock', foreign_keys=[block_id])
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_user_id])

    __table_args__ = (
        db.UniqueConstraint('student_id', 'block_id', name='uq_theory_study_assignment'),
    )


class TheoryFeedback(db.Model):
    """Фидбек ученика по статье теории: оценка + комментарий."""
    __tablename__ = 'TheoryFeedback'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)

    rating = db.Column(db.Integer, nullable=True)  # 1..5
    comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now, nullable=False)

    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', 'task_number', name='uq_theory_feedback'),)

    student = db.relationship('Student', foreign_keys=[student_id])
    user = db.relationship('User', foreign_keys=[user_id])
    course = db.relationship('Course', foreign_keys=[course_id])


class TheoryFeedbackHistory(db.Model):
    """История комментариев/оценок по теории для аналитики преподавателя."""
    __tablename__ = 'TheoryFeedbackHistory'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=True, index=True)
    task_number = db.Column(db.Integer, nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False, index=True)

    student = db.relationship('Student', foreign_keys=[student_id])
    user = db.relationship('User', foreign_keys=[user_id])
    course = db.relationship('Course', foreign_keys=[course_id])


class StudentCourseEnrollment(db.Model):
    """Подписка ученика на программу подготовки (тип экзамена)."""
    __tablename__ = 'StudentCourseEnrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Students.student_id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    enrolled_at = db.Column(db.DateTime, default=moscow_now)

    student = db.relationship('Student', foreign_keys=[student_id], backref='course_enrollments')
    course = db.relationship('Course', back_populates='enrollments')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id', name='uq_student_course_enrollment'),
    )

    def __repr__(self):
        return f'<Enrollment student={self.student_id} course={self.course_id}>'


class GradingScale(db.Model):
    """Шкала перевода первичных баллов (ЕГЭ: 0-100, ОГЭ: 2-5)."""
    __tablename__ = 'GradingScales'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=False, index=True)
    min_primary = db.Column(db.Integer, nullable=False)
    max_primary = db.Column(db.Integer, nullable=False)
    final_grade = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(50), nullable=True)

    course = db.relationship('Course', back_populates='grading_scales')

    def __repr__(self):
        return f'<GradingScale course={self.course_id} {self.min_primary}-{self.max_primary}={self.final_grade}>'


class StudentWorkspaceFile(db.Model):
    """Файл в мини-хранилище ученика, привязанный к конкретному заданию."""
    __tablename__ = 'StudentWorkspaceFiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id', ondelete='CASCADE'), nullable=False, index=True)
    context_type = db.Column(db.String(32), nullable=False, default='submission')
    context_id = db.Column(db.Integer, nullable=True, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    current_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(128), nullable=True)
    is_from_task = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    user = db.relationship('User', foreign_keys=[user_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'task_id': self.task_id,
            'context_type': self.context_type,
            'context_id': self.context_id,
            'original_filename': self.original_filename,
            'current_filename': self.current_filename,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'is_from_task': self.is_from_task,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TaskCanvasDrawing(db.Model):
    """Холст рисования поверх интерфейса — привязан к заданию, пользователю и контексту."""
    __tablename__ = 'TaskCanvasDrawings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('Tasks.task_id', ondelete='CASCADE'), nullable=False, index=True)
    context_type = db.Column(db.String(32), nullable=False, default='submission')
    context_id = db.Column(db.Integer, nullable=True, index=True)
    strokes_json = db.Column(db.Text, nullable=False, default='[]')
    thumbnail_url = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    __table_args__ = (
        db.Index('ix_canvas_user_task_ctx', 'user_id', 'task_id', 'context_type', 'context_id'),
    )

    user = db.relationship('User', foreign_keys=[user_id])
    task = db.relationship('Tasks', foreign_keys=[task_id])

    def to_dict(self, include_strokes=False):
        d = {
            'id': self.id,
            'user_id': self.user_id,
            'task_id': self.task_id,
            'context_type': self.context_type,
            'context_id': self.context_id,
            'thumbnail_url': self.thumbnail_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_strokes:
            d['strokes'] = self.strokes_json
        return d


class PlatformBugReport(db.Model):
    """Bug reports from users via the platform."""
    __tablename__ = 'PlatformBugReports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    url_context = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='new', nullable=False, index=True) # new, in_progress, resolved
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    user = db.relationship('User', foreign_keys=[user_id])


AssignmentTemplate = TaskTemplate
ScheduleLesson = Lesson



class LibraryMaterial(db.Model):
    """Модель учебного материала в единой библиотеке материалов V2"""
    __tablename__ = 'LibraryMaterials'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    formatted_size = db.Column(db.String(64), nullable=True)
    file_extension = db.Column(db.String(32), nullable=True)
    category = db.Column(db.String(64), nullable=False, default='materials')
    tags = db.Column(db.Text, nullable=True)
    is_visible_to_students = db.Column(db.Boolean, default=False, nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id])

    def to_dict(self):
        tags_list = [t.strip() for t in (self.tags or '').split(',') if t.strip()]
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description or '',
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'formatted_size': self.formatted_size or '',
            'file_extension': (self.file_extension or '').lower(),
            'category': self.category,
            'tags': tags_list,
            'tags_raw': self.tags or '',
            'is_visible_to_students': self.is_visible_to_students,
            'teacher_id': self.teacher_id,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M') if self.created_at else ''
        }


# =========================================================================
# V2 MENTOR / TEACHER PROFILE & SHOWCASE MODELS
# =========================================================================
class TeacherProfile(db.Model):
    __tablename__ = 'TeacherProfiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), unique=True, nullable=False, index=True)
    bio = db.Column(db.Text, nullable=True)
    university = db.Column(db.String(200), nullable=True)
    experience_years = db.Column(db.Integer, default=0, nullable=True)
    specialization = db.Column(db.String(200), nullable=True)
    tags = db.Column(db.Text, nullable=True)  # JSON-encoded list or comma-separated strings
    methodology_highlights = db.Column(db.Text, nullable=True)  # JSON-encoded list of dicts [{'title':..., 'description':..., 'icon':...}]
    created_at = db.Column(db.DateTime, default=moscow_now)
    updated_at = db.Column(db.DateTime, default=moscow_now, onupdate=moscow_now)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('teacher_profile', uselist=False))

    def get_tags_list(self):
        if not self.tags:
            return []
        try:
            val = json.loads(self.tags)
            if isinstance(val, list):
                return val
        except Exception:
            pass
        return [t.strip() for t in str(self.tags).split(',') if t.strip()]

    def get_methodology_list(self):
        if not self.methodology_highlights:
            return []
        try:
            val = json.loads(self.methodology_highlights)
            if isinstance(val, list):
                return val
        except Exception:
            pass
        return []


class TeacherProgram(db.Model):
    __tablename__ = 'TeacherPrograms'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    program_type = db.Column(db.String(50), default='ГОДОВОЙ КУРС', nullable=False)
    group_size_info = db.Column(db.String(100), default='Группа до 10 чел.', nullable=True)
    description = db.Column(db.Text, nullable=True)
    seats_left = db.Column(db.Integer, default=5, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('teacher_programs', lazy='dynamic'))


class TeacherResult(db.Model):
    __tablename__ = 'TeacherResults'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    student_name = db.Column(db.String(150), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    target_university = db.Column(db.String(200), nullable=True)
    subject = db.Column(db.String(100), default='Информатика', nullable=True)
    year = db.Column(db.Integer, default=2025, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('teacher_results', lazy='dynamic'))


class TeacherWebinar(db.Model):
    __tablename__ = 'TeacherWebinars'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=90, nullable=True)
    room_id = db.Column(db.String(100), nullable=True)
    is_live = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('teacher_webinars', lazy='dynamic'))


class TeacherReview(db.Model):
    """Отзыв ученика о преподавателе."""
    __tablename__ = 'TeacherReviews'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True, index=True)
    student_name = db.Column(db.String(120), nullable=False)
    rating = db.Column(db.Float, nullable=False, default=5.0)
    text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('teacher_reviews', lazy='dynamic'))


class CourseTimelineBlock(db.Model):
    __tablename__ = 'CourseTimelineBlocks'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('ExamCourses.id'), nullable=False)
    lesson_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=True)
    content = db.Column(db.Text, nullable=True)
    pdf_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=moscow_now)

    course = db.relationship('Course', backref=db.backref('timeline_blocks', lazy='dynamic', cascade='all, delete-orphan'))
