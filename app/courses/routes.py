from __future__ import annotations

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.courses import courses_bp
from app.courses.forms import CourseForm, CourseModuleForm
from app.models import db, Student, Lesson, Course, CourseModule, User
from app.auth.rbac_utils import get_user_scope


def _get_student_user(student: Student) -> User | None:
    if not student or not getattr(student, 'email', None):
        return None
    return User.query.filter_by(email=student.email).first()


def _can_access_student(student: Student) -> bool:
    if not current_user.is_authenticated:
        return False

    if getattr(current_user, 'is_creator', None) and current_user.is_creator():
        return True
    if getattr(current_user, 'is_admin', None) and current_user.is_admin():
        return True

    if getattr(current_user, 'is_student', None) and current_user.is_student():
        return bool(student.email and current_user.email and student.email.strip().lower() == current_user.email.strip().lower())

    # Tutor/прочие роли — через data scope (по user_id ученика)
    scope = get_user_scope(current_user)
    if getattr(scope, 'can_see_all', False):
        return True
    st_user = _get_student_user(student)
    if not st_user:
        return False
    return st_user.id in getattr(scope, 'student_ids', set())


def _guard_student(student_id: int) -> Student:
    student = Student.query.get_or_404(student_id)
    if not _can_access_student(student):
        abort(403)
    return student


def _guard_course(course_id: int) -> Course:
    course = Course.query.get_or_404(course_id)
    student = Student.query.get_or_404(course.student_id)
    if not _can_access_student(student):
        abort(403)
    return course


@courses_bp.route('/student/<int:student_id>/courses')
@login_required
def student_courses(student_id: int):
    student = _guard_student(student_id)
    courses = Course.query.filter_by(student_id=student.student_id).order_by(Course.updated_at.desc(), Course.created_at.desc()).all()
    return render_template('courses_list.html', student=student, courses=courses)


@courses_bp.route('/student/<int:student_id>/courses/new', methods=['GET', 'POST'])
@login_required
def course_new(student_id: int):
    student = _guard_student(student_id)
    if current_user.is_student():
        flash('Ученик не может создавать курсы.', 'danger')
        return redirect(url_for('courses.student_courses', student_id=student.student_id))

    form = CourseForm()
    if form.validate_on_submit():
        course = Course(
            student_id=student.student_id,
            created_by_user_id=current_user.id,
            title=form.title.data.strip(),
            subject=form.subject.data.strip() if form.subject.data else None,
            description=form.description.data.strip() if form.description.data else None,
            status=form.status.data,
        )
        db.session.add(course)
        db.session.commit()
        flash('Курс создан.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    return render_template('course_form.html', form=form, student=student, title='Создать курс', is_new=True)


@courses_bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
def course_edit(course_id: int):
    course = _guard_course(course_id)
    student = Student.query.get_or_404(course.student_id)
    if current_user.is_student():
        flash('Ученик не может редактировать курс.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    form = CourseForm(obj=course)
    if form.validate_on_submit():
        course.title = form.title.data.strip()
        course.subject = form.subject.data.strip() if form.subject.data else None
        course.description = form.description.data.strip() if form.description.data else None
        course.status = form.status.data
        db.session.commit()
        flash('Курс обновлён.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    return render_template('course_form.html', form=form, student=student, course=course, title='Редактировать курс', is_new=False)


@courses_bp.route('/courses/<int:course_id>')
@login_required
def course_view(course_id: int):
    course = _guard_course(course_id)
    student = Student.query.get_or_404(course.student_id)

    modules = CourseModule.query.filter_by(course_id=course.course_id).order_by(CourseModule.order_index.asc(), CourseModule.module_id.asc()).all()
    module_ids = [m.module_id for m in modules]

    lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).all()
    lessons_by_module = {}
    unassigned_lessons = []
    for l in lessons:
        if l.course_module_id and l.course_module_id in module_ids:
            lessons_by_module.setdefault(l.course_module_id, []).append(l)
        else:
            unassigned_lessons.append(l)

    total_lessons = len(lessons)
    completed_lessons = sum(1 for l in lessons if (l.status or '').lower() == 'completed')
    planned_lessons = sum(1 for l in lessons if (l.status or '').lower() == 'planned')

    return render_template(
        'course_view.html',
        student=student,
        course=course,
        modules=modules,
        lessons_by_module=lessons_by_module,
        unassigned_lessons=unassigned_lessons,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons,
        planned_lessons=planned_lessons,
    )


@courses_bp.route('/courses/<int:course_id>/modules/new', methods=['GET', 'POST'])
@login_required
def module_new(course_id: int):
    course = _guard_course(course_id)
    student = Student.query.get_or_404(course.student_id)
    if current_user.is_student():
        flash('Ученик не может создавать модули.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    form = CourseModuleForm()
    if form.validate_on_submit():
        module = CourseModule(
            course_id=course.course_id,
            title=form.title.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            order_index=form.order_index.data or 0,
        )
        db.session.add(module)
        db.session.commit()
        flash('Модуль добавлен.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    return render_template('course_module_form.html', form=form, student=student, course=course, title='Добавить модуль')


@courses_bp.route('/courses/<int:course_id>/assign-lesson', methods=['POST'])
@login_required
def course_assign_lesson(course_id: int):
    course = _guard_course(course_id)
    student = Student.query.get_or_404(course.student_id)
    if current_user.is_student():
        abort(403)

    lesson_id = request.form.get('lesson_id', type=int)
    module_id = request.form.get('module_id', type=int)
    if not lesson_id or not module_id:
        flash('Выберите урок и модуль.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    module = CourseModule.query.filter_by(module_id=module_id, course_id=course.course_id).first()
    if not module:
        flash('Модуль не найден.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    lesson = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
    if not lesson:
        flash('Урок не найден.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    lesson.course_module_id = module.module_id
    db.session.commit()
    flash('Урок привязан к модулю.', 'success')
    return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'module-{module.module_id}'))

