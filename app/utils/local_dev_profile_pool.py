"""Идемпотентный пул локальных профилей для ручной проверки ролей.

Этот модуль намеренно запускается только в локальной разработке. Он не
создаёт и не изменяет тестовые личности в production.
"""

import os
from app.models import FamilyTie, Lesson, Student, TeacherStudent, User, UserProfile, UserRole, db


LOCAL_PROFILE_POOL = (
    ('creator', 'creator', 'creator@boostudy.ru', 'Создатель'),
    ('chief_admin', 'chief_admin', 'chief_admin@boostudy.ru', 'Главный администратор'),
    ('demo_admin_1', 'admin', 'demo_admin_1@boostudy.ru', 'Администратор демо'),
    ('qa_pool_teacher_1', 'teacher', 'teacher1@boostudy.ru', 'Преподаватель QA'),
    ('demo_teacher_2', 'teacher', 'teacher2@boostudy.ru', 'Преподаватель демо'),
    ('demo_tutor_1', 'tutor', 'tutor1@boostudy.ru', 'Тьютор демо'),
    ('demo_student_1', 'student', 'student1@boostudy.ru', 'Ученик 11 класса'),
    ('demo_student_2', 'student', 'student2@boostudy.ru', 'Ученик 10 класса'),
    ('demo_student_3', 'student', 'student3@boostudy.ru', 'Ученик 9 класса'),
    ('demo_parent_1', 'parent', 'parent1@boostudy.ru', 'Родитель ученика 1'),
    ('demo_parent_2', 'parent', 'parent2@boostudy.ru', 'Родитель ученика 2'),
    ('demo_parent_3', 'parent', 'parent3@boostudy.ru', 'Родитель ученика 3'),
    ('qa_pool_admin_2', 'chief_tester', 'chief_tester@boostudy.ru', 'Главный тестировщик'),
    ('qa_pool_student_4', 'tester', 'tester4@boostudy.ru', 'Тестировщик QA'),
    ('demo_auditor', 'admin', 'auditor@boostudy.ru', 'Аудитор демо'),
)

LOCAL_TEACHER_STUDENT_PAIRS = (
    ('qa_pool_teacher_1', 'demo_student_1'),
    ('demo_teacher_2', 'demo_student_1'),
    ('demo_teacher_2', 'demo_student_2'),
    ('qa_pool_teacher_1', 'demo_student_2'),
    ('demo_tutor_1', 'demo_student_3'),
    ('demo_teacher_2', 'demo_student_3'),
)

LOCAL_PARENT_STUDENT_PAIRS = (
    ('demo_parent_1', 'demo_student_1'),
    ('demo_parent_2', 'demo_student_2'),
    ('demo_parent_3', 'demo_student_3'),
)


def ensure_local_dev_profile_pool() -> None:
    """Восстанавливает только отсутствующие локальные demo-профили и связи.
    Строго заблокировано в production.
    """
    env = (os.environ.get('ENVIRONMENT') or '').strip().lower()
    flask_env = (os.environ.get('FLASK_ENV') or '').strip().lower()
    if env == 'production' or flask_env == 'production':
        return

    users_by_username = {
        user.username: user
        for user in User.query.filter(User.username.in_([row[0] for row in LOCAL_PROFILE_POOL])).all()
    }

    for username, role, email, display_name in LOCAL_PROFILE_POOL:
        user = users_by_username.get(username)
        if user is None:
            user = User(username=username, email=email, role=role, is_active=True)
            user.set_password('creator123' if username == 'creator' else 'demo123pass')
            db.session.add(user)
            db.session.flush()
            users_by_username[username] = user
        else:
            user.is_active = True
            if not user.email:
                user.email = email
            if not getattr(user, 'password_hash', None):
                user.set_password('creator123' if username == 'creator' else 'demo123pass')

        if not UserRole.query.filter_by(user_id=user.id, role=role).first():
            db.session.add(UserRole(user_id=user.id, role=role))
        if user.profile is None:
            db.session.add(UserProfile(user_id=user.id, first_name=display_name))

    db.session.flush()

    for teacher_username, student_username in LOCAL_TEACHER_STUDENT_PAIRS:
        teacher = users_by_username.get(teacher_username)
        student_user = users_by_username.get(student_username)
        if not teacher or not student_user:
            continue
        student = Student.query.filter_by(user_id=student_user.id).first()
        if student is None:
            student = Student(
                user_id=student_user.id,
                name=student_user.username,
                email=student_user.email,
                mentor_id=teacher.id,
                category='ЕГЭ',
                school_class=11,
                is_active=True,
            )
            db.session.add(student)
            db.session.flush()
        else:
            student.is_active = True
            if student.mentor_id is None:
                student.mentor_id = teacher.id

        if not TeacherStudent.query.filter_by(teacher_id=teacher.id, student_id=student_user.id).first():
            db.session.add(TeacherStudent(teacher_id=teacher.id, student_id=student_user.id, status='active'))

    for parent_username, student_username in LOCAL_PARENT_STUDENT_PAIRS:
        parent = users_by_username.get(parent_username)
        student_user = users_by_username.get(student_username)
        if not parent or not student_user:
            continue
        if not FamilyTie.query.filter_by(parent_id=parent.id, student_id=student_user.id).first():
            db.session.add(FamilyTie(parent_id=parent.id, student_id=student_user.id, is_confirmed=True))

    # Обеспечиваем активный demo-урок (status='in_progress') для demo_student_1 (штатный урок 89)
    student_1_user = users_by_username.get('demo_student_1')
    if student_1_user:
        st1 = Student.query.filter_by(user_id=student_1_user.id).first()
        if st1:
            lesson_89 = db.session.get(Lesson, 89)
            if lesson_89 and lesson_89.student_id == st1.id:
                lesson_89.status = 'in_progress'
                if not lesson_89.topic:
                    lesson_89.topic = 'Индивидуальный урок: Demo QA'
            elif not lesson_89:
                lesson_89 = Lesson(
                    lesson_id=89,
                    student_id=st1.id,
                    status='in_progress',
                    topic='Индивидуальный урок: Demo QA',
                    lesson_format='individual',
                    duration=60,
                )
                db.session.add(lesson_89)

    db.session.commit()
