from __future__ import annotations

import json
from flask import render_template, redirect, url_for, flash, request, abort, jsonify, g
from datetime import date, timedelta
from flask_login import login_required, current_user
from sqlalchemy import or_, func

from app.courses import courses_bp
from app.courses.forms import CourseForm, CourseModuleForm, CourseLessonForm
from app.models import db, Student, Lesson, LessonTask, Tasks, LearningTrajectory, TrajectoryModule, User, LearningItem, LessonOutcome, ExamSkill, StudentSkill, LearningTrajectoryVersion, StudentDiagnosticCheckpoint, LearningError, LearningTrajectoryTemplate, LearningTrajectoryTemplateModule, LearningTrajectoryTemplateItem
from core.db_models import utc_now
from app.auth.rbac_utils import get_active_role, get_user_scope
from app.utils.datetime_utc import effective_timezone_name
from app.utils.lesson_time import parse_local_lesson_datetime, lesson_storage_to_local


def _get_student_user(student: Student) -> User | None:
    if not student:
        return None
    if getattr(student, 'user_id', None):
        u = User.query.get(student.user_id)
        if u:
            return u
    try:
        u = User.query.get(student.student_id)
        if u and u.role == 'student':
            return u
    except Exception:
        pass
    return None


def _course_viewer_is_read_only() -> bool:
    """Возвращает режим текущей сессии, включая локальную имперсонацию."""
    active_role = (get_active_role() or '').lower()
    return active_role in {'student', 'parent'} or current_user.is_student() or current_user.is_parent()


def _course_viewer_can_manage() -> bool:
    return not _course_viewer_is_read_only()


def _can_access_student(student: Student) -> bool:
    if not current_user.is_authenticated:
        return False

    if getattr(current_user, 'is_creator', None) and current_user.is_creator():
        return True
    if getattr(current_user, 'is_admin', None) and current_user.is_admin():
        return True

    if getattr(current_user, 'is_student', None) and current_user.is_student():
        if getattr(student, 'user_id', None) == current_user.id:
            return True
        if student.student_id == current_user.id:
            return True
        if getattr(student, 'platform_id', None) and current_user.username and str(student.platform_id).strip() == str(current_user.username).strip():
            return True
        return False

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    st_user = _get_student_user(student)
    if st_user and st_user.id in scope.get('student_ids', []):
        return True

    try:
        return student.student_id in scope.get('student_ids', [])
    except Exception:
        return False


def _guard_student(student_id: int) -> Student:
    student = Student.query.get_or_404(student_id)
    if not _can_access_student(student):
        abort(403)
    return student


def _guard_course(course_id: int) -> LearningTrajectory:
    course = LearningTrajectory.query.get_or_404(course_id)
    student = Student.query.get_or_404(course.student_id)
    if not _can_access_student(student):
        abort(403)
    return course


def _snapshot_course(course: LearningTrajectory, reason: str) -> None:
    """Фиксирует версию маршрута перед изменением без удаления истории."""
    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).order_by(TrajectoryModule.order_index.asc()).all()
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(Lesson.course_order_index.asc()).all()
    # Номер версии берём из БД, а не только из кэша объекта курса: это
    # защищает историю от коллизий после параллельного редактирования.
    latest_version = db.session.query(func.max(LearningTrajectoryVersion.version_number)).filter_by(course_id=course.course_id).scalar()
    version_no = max(int(course.current_version or 1), int(latest_version or 0) + 1)
    db.session.add(LearningTrajectoryVersion(
        course_id=course.course_id,
        version_number=version_no,
        reason=reason,
        created_by_user_id=current_user.id,
        snapshot={
            'title': course.title,
            'subject': course.subject,
            'learning_goal': course.learning_goal,
            'expected_result': course.expected_result,
            'modules': [{'id': m.module_id, 'title': m.title, 'order': m.order_index} for m in modules],
            'lessons': [{'id': l.lesson_id, 'topic': l.topic, 'status': l.status, 'module_id': l.course_module_id} for l in lessons],
        },
    ))
    course.current_version = version_no + 1


@courses_bp.route('/student/<int:student_id>/courses')
@login_required
def student_courses(student_id: int):
    student = _guard_student(student_id)
    courses = LearningTrajectory.query.filter_by(student_id=student.student_id).order_by(LearningTrajectory.updated_at.desc(), LearningTrajectory.created_at.desc()).all()
    return render_template(
        'courses_list.html',
        student=student,
        courses=courses,
        viewer_is_student=_course_viewer_is_read_only(),
        can_manage=_course_viewer_can_manage(),
    )


@courses_bp.route('/student/<int:student_id>/courses/new', methods=['GET', 'POST'])
@login_required
def course_new(student_id: int):
    student = _guard_student(student_id)
    if not _course_viewer_can_manage():
        abort(403)

    form = CourseForm()
    if form.validate_on_submit():
        course = LearningTrajectory(
            student_id=student.student_id,
            created_by_user_id=current_user.id,
            title=form.title.data.strip(),
            subject=form.subject.data.strip() if form.subject.data else None,
            description=form.description.data.strip() if form.description.data else None,
            learning_goal=form.learning_goal.data.strip() if form.learning_goal.data else None,
            expected_result=form.expected_result.data.strip() if form.expected_result.data else None,
            target_score=form.target_score.data,
            exam_date=form.exam_date.data,
            default_lesson_duration=form.default_lesson_duration.data,
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
    student = _require_course_manager(course)

    form = CourseForm(obj=course)
    if form.validate_on_submit():
        _snapshot_course(course, 'manual_edit')
        course.title = form.title.data.strip()
        course.subject = form.subject.data.strip() if form.subject.data else None
        course.description = form.description.data.strip() if form.description.data else None
        course.learning_goal = form.learning_goal.data.strip() if form.learning_goal.data else None
        course.expected_result = form.expected_result.data.strip() if form.expected_result.data else None
        course.target_score = form.target_score.data
        course.exam_date = form.exam_date.data
        course.default_lesson_duration = form.default_lesson_duration.data
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
    can_manage = _course_viewer_can_manage()

    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).order_by(TrajectoryModule.order_index.asc(), TrajectoryModule.module_id.asc()).all()
    module_ids = [m.module_id for m in modules]

    course_lesson_filter = Lesson.learning_trajectory_id == course.course_id
    if module_ids:
        course_lesson_filter = or_(course_lesson_filter, Lesson.course_module_id.in_(module_ids))
    lessons = Lesson.query.filter(
        Lesson.student_id == student.student_id,
        course_lesson_filter,
    ).order_by(
        Lesson.course_order_index.asc(), Lesson.lesson_date.asc().nullslast(), Lesson.lesson_id.asc()
    ).all()
    lessons_by_module = {}
    unassigned_lessons = []
    viewer_timezone = effective_timezone_name(current_user)
    for l in lessons:
        l.course_display_date = lesson_storage_to_local(l.lesson_date, viewer_timezone)
        if l.course_module_id and l.course_module_id in module_ids:
            lessons_by_module.setdefault(l.course_module_id, []).append(l)
        else:
            unassigned_lessons.append(l)

    course_lessons = [lesson for module_lessons in lessons_by_module.values() for lesson in module_lessons] + unassigned_lessons
    total_lessons = len(course_lessons)
    completed_lessons = sum(1 for l in course_lessons if (l.status or '').lower() == 'completed')
    planned_lessons = sum(1 for l in course_lessons if (l.status or '').lower() == 'planned')
    running_lessons = sum(1 for l in course_lessons if (l.status or '').lower() == 'in_progress')
    completed_items = sum(1 for item in LearningItem.query.filter_by(course_id=course.course_id, status='done').all())
    total_items = LearningItem.query.filter_by(course_id=course.course_id).count()
    mastery_percent = round(sum((getattr(item.skill, 'mastery_percent', 0) or 0) for item in LearningItem.query.filter_by(course_id=course.course_id).all() if item.skill) / max(total_items, 1)) if total_items else 0
    course_skills = []
    if course.exam_course_id:
        course_skills = ExamSkill.query.filter_by(exam_course_id=course.exam_course_id, is_active=True).order_by(ExamSkill.topic.asc(), ExamSkill.task_number.asc()).all()
    skill_rows = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=student.student_id).all()}
    route_items = LearningItem.query.filter_by(course_id=course.course_id).filter(
        LearningItem.status.in_(['planned', 'in_progress', 'overdue'])
    ).order_by(LearningItem.due_at.asc(), LearningItem.order_index.asc()).limit(8).all()
    forecast_target = course.target_score or 0
    forecast_value = course.current_forecast
    forecast_range = (course.forecast_low, course.forecast_high)
    if forecast_value is None and course_skills:
        weights = sum(float(skill.weight or 1) for skill in course_skills) or 1
        weighted_mastery = sum((skill_rows.get(skill.skill_id).mastery_percent if skill_rows.get(skill.skill_id) else 0) * float(skill.weight or 1) for skill in course_skills)
        mastery_value = round(weighted_mastery / weights)
        forecast_value = round(mastery_value * forecast_target / 100) if forecast_target else mastery_value
        forecast_range = (max(0, forecast_value - 5), min(100, forecast_value + 5))
    attention_counts = None
    if can_manage:
        now = utc_now()
        attention_counts = {
            'errors': LearningError.query.filter_by(student_id=student.student_id).filter(LearningError.resolved_at.is_(None)).count(),
            'reviews': StudentSkill.query.filter_by(student_id=student.student_id).filter(StudentSkill.next_review_at.isnot(None), StudentSkill.next_review_at <= now).count(),
            'overdue': LearningItem.query.filter_by(course_id=course.course_id).filter(LearningItem.status.in_(['planned', 'overdue']), LearningItem.due_at.isnot(None), LearningItem.due_at < now).count(),
        }
    milestone_items = LearningItem.query.filter_by(course_id=course.course_id).all()
    milestone_completed = sum(1 for item in milestone_items if item.status == 'done')
    milestones = [
        {'title': 'Первый урок', 'achieved': completed_lessons >= 1},
        {'title': '25% маршрута', 'achieved': bool(milestone_items) and milestone_completed / len(milestone_items) >= .25},
        {'title': '60% mastery', 'achieved': mastery_percent >= 60},
        {'title': '85% mastery', 'achieved': mastery_percent >= 85},
    ]

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
        running_lessons=running_lessons,
        completed_items=completed_items,
        total_items=total_items,
        mastery_percent=mastery_percent,
        course_skills=course_skills,
        skill_rows=skill_rows,
        route_items=route_items,
        forecast_value=forecast_value,
        forecast_range=forecast_range,
        attention_counts=attention_counts,
        milestones=milestones,
        viewer_is_student=_course_viewer_is_read_only(),
        can_manage=can_manage,
    )


@courses_bp.route('/courses/<int:course_id>/skills', methods=['GET'])
@login_required
def course_skills(course_id: int):
    """Карта навыков программы: единый источник для V2 аналитики и рекомендаций."""
    course = _guard_course(course_id)
    skills_query = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        skills_query = skills_query.filter(ExamSkill.exam_course_id == course.exam_course_id)
    skills = skills_query.order_by(ExamSkill.topic.asc(), ExamSkill.task_number.asc(), ExamSkill.skill_id.asc()).all()
    mastery = {
        row.skill_id: row
        for row in StudentSkill.query.filter_by(student_id=course.student_id).all()
    }
    payload = []
    for skill in skills:
        row = mastery.get(skill.skill_id)
        prerequisite = mastery.get(skill.prerequisite_skill_id) if skill.prerequisite_skill_id else None
        payload.append({
            'id': skill.skill_id,
            'task_number': skill.task_number,
            'title': skill.title,
            'topic': skill.topic,
            'subtopic': skill.subtopic,
            'mastery_percent': int(row.mastery_percent if row else 0),
            'state': row.state if row else 'not_started',
            'theory_done': bool(row.theory_done) if row else False,
            'practice_done': bool(row.practice_done) if row else False,
            'next_review_at': row.next_review_at.isoformat() if row and row.next_review_at else None,
            'prerequisite_id': skill.prerequisite_skill_id,
            'prerequisite_mastery_percent': int(prerequisite.mastery_percent if prerequisite else 0) if skill.prerequisite_skill_id else None,
            'prerequisite_ready': (not skill.prerequisite_skill_id) or bool(prerequisite and prerequisite.mastery_percent >= 60),
        })
    if request.args.get('view') == '1':
        return render_template('course_skills.html', course=course, skills=skills, mastery=mastery)
    return jsonify({'course_id': course.course_id, 'student_id': course.student_id, 'skills': payload})


@courses_bp.route('/courses/<int:course_id>/skills/manage', methods=['GET', 'POST'])
@login_required
def course_skills_manage(course_id: int):
    """Настройка атомарных тем, на которых строится персональный маршрут."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)

    skills_query = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        skills_query = skills_query.filter(ExamSkill.exam_course_id == course.exam_course_id)
    skills = skills_query.order_by(ExamSkill.topic.asc(), ExamSkill.task_number.asc(), ExamSkill.skill_id.asc()).all()

    if request.method == 'POST':
        title = str(request.form.get('title') or '').strip()
        topic = str(request.form.get('topic') or '').strip()
        subtopic = str(request.form.get('subtopic') or '').strip()
        task_number_raw = str(request.form.get('task_number') or '').strip()
        prerequisite_raw = str(request.form.get('prerequisite_skill_id') or '').strip()

        if not title:
            flash('Укажите название навыка.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))
        if len(title) > 300 or len(topic) > 200 or len(subtopic) > 200:
            flash('Название или раздел слишком длинные.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))
        try:
            task_number = int(task_number_raw) if task_number_raw else None
            if task_number is not None and task_number < 1:
                raise ValueError
        except ValueError:
            flash('Номер задания должен быть положительным числом.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))

        prerequisite_skill_id = None
        if prerequisite_raw:
            try:
                prerequisite_skill_id = int(prerequisite_raw)
            except ValueError:
                abort(400)
            prerequisite = next((skill for skill in skills if skill.skill_id == prerequisite_skill_id), None)
            if prerequisite is None:
                flash('Базовый навык должен принадлежать этой программе.', 'error')
                return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))

        db.session.add(ExamSkill(
            exam_course_id=course.exam_course_id,
            task_number=task_number,
            title=title,
            subject=(course.subject or '').strip()[:120] or None,
            topic=topic or None,
            subtopic=subtopic or None,
            prerequisite_skill_id=prerequisite_skill_id,
            is_active=True,
        ))
        db.session.commit()
        flash('Навык добавлен в программу. Теперь его можно включить в маршрут.', 'success')
        return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))

    return render_template('course_skills_manage.html', course=course, skills=skills)


@courses_bp.route('/courses/<int:course_id>/versions', methods=['GET'])
@login_required
def course_versions(course_id: int):
    course = _guard_course(course_id)
    versions = LearningTrajectoryVersion.query.filter_by(course_id=course.course_id).order_by(LearningTrajectoryVersion.version_number.desc()).all()
    if request.args.get('view') == '1':
        compare_ids = [value for value in (request.args.get('compare_a', type=int), request.args.get('compare_b', type=int)) if value]
        diff = []
        if len(compare_ids) == 2:
            left = LearningTrajectoryVersion.query.get(compare_ids[0])
            right = LearningTrajectoryVersion.query.get(compare_ids[1])
            if left and right and left.course_id == course.course_id and right.course_id == course.course_id:
                left_snapshot = left.snapshot or {}
                right_snapshot = right.snapshot or {}
                for key in sorted(set(left_snapshot) | set(right_snapshot)):
                    if left_snapshot.get(key) != right_snapshot.get(key):
                        diff.append({'key': key, 'before': left_snapshot.get(key), 'after': right_snapshot.get(key)})
        return render_template('course_versions.html', course=course, versions=versions, diff=diff)
    return jsonify({'course_id': course.course_id, 'current_version': course.current_version or 1, 'versions': [
        {'id': version.version_id, 'number': version.version_number, 'reason': version.reason, 'created_at': version.created_at.isoformat() if version.created_at else None, 'snapshot': version.snapshot}
        for version in versions
    ]})


@courses_bp.route('/courses/<int:course_id>/milestones', methods=['GET'])
@login_required
def course_milestones(course_id: int):
    """Вычисляемые достижения маршрута: только из текущих уроков/items/мастерства."""
    course = _guard_course(course_id)
    items = LearningItem.query.filter_by(course_id=course.course_id).all()
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).all()
    skills = [item.skill_id for item in items if item.skill_id]
    rows = StudentSkill.query.filter(StudentSkill.student_id == course.student_id, StudentSkill.skill_id.in_(skills)).all() if skills else []
    mastery = round(sum(int(row.mastery_percent or 0) for row in rows) / max(len(skills), 1)) if skills else 0
    completed_lessons = sum(1 for lesson in lessons if lesson.status == 'completed')
    completed_items = sum(1 for item in items if item.status == 'done')
    milestones = [
        {'key': 'first_lesson', 'title': 'Первый урок', 'description': 'Завершить первое занятие маршрута.', 'achieved': completed_lessons >= 1},
        {'key': 'quarter_route', 'title': 'Четверть маршрута', 'description': 'Завершить 25% учебных элементов.', 'achieved': bool(items) and completed_items / len(items) >= .25},
        {'key': 'mastery_60', 'title': 'Уверенная база', 'description': 'Достичь 60% среднего mastery.', 'achieved': mastery >= 60},
        {'key': 'mastery_85', 'title': 'Готовность', 'description': 'Достичь 85% среднего mastery.', 'achieved': mastery >= 85},
    ]
    return jsonify({'course_id': course.course_id, 'mastery_percent': mastery, 'completed_lessons': completed_lessons, 'completed_items': completed_items, 'milestones': milestones})


@courses_bp.route('/courses/<int:course_id>/items', methods=['GET', 'POST'])
@login_required
def course_learning_items(course_id: int):
    """Управление универсальными элементами программы без копирования контента."""
    course = _guard_course(course_id)
    if request.method == 'GET':
        items = LearningItem.query.filter_by(course_id=course.course_id).order_by(LearningItem.order_index.asc(), LearningItem.item_id.asc()).all()
        return jsonify({'course_id': course.course_id, 'items': [
            {'id': item.item_id, 'type': item.item_type, 'title': item.title, 'status': item.status,
             'module_id': item.module_id, 'lesson_id': item.lesson_id, 'skill_id': item.skill_id,
             'due_at': item.due_at.isoformat() if item.due_at else None, 'why_now': item.why_now,
             'order_index': item.order_index}
            for item in items
        ]})
    if not _course_viewer_can_manage():
        abort(403)
    data = request.get_json(silent=True) or {}
    item_type = (data.get('type') or 'lesson').strip().lower()
    if item_type not in {'theory', 'practice', 'lesson', 'homework', 'review', 'control'}:
        return jsonify({'success': False, 'error': 'Недопустимый тип учебного элемента'}), 400
    title = str(data.get('title') or '').strip()
    if not title or len(title) > 300:
        return jsonify({'success': False, 'error': 'Название элемента обязательно'}), 400
    module_id = data.get('module_id')
    if module_id and not TrajectoryModule.query.filter_by(module_id=module_id, course_id=course.course_id).first():
        return jsonify({'success': False, 'error': 'Модуль не принадлежит программе'}), 400
    item = LearningItem(course_id=course.course_id, module_id=module_id or None, item_type=item_type, title=title[:300],
                        status='planned', why_now=str(data.get('why_now') or '').strip()[:2000] or None,
                        order_index=int(data.get('order_index') or 0))
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'item_id': item.item_id, 'type': item.item_type, 'status': item.status}), 201


@courses_bp.route('/courses/<int:course_id>/plan/generate', methods=['POST'])
@login_required
def course_plan_generate(course_id: int):
    """Мастер генерации персонального маршрута из цели и диагностики."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    data = request.get_json(silent=True) or request.form
    target = data.get('target_score')
    try:
        if target not in (None, ''):
            course.target_score = max(1, min(100, int(target)))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Целевой балл должен быть числом'}), 400
    exam_date_raw = str(data.get('exam_date') or '').strip()
    if exam_date_raw:
        try:
            course.exam_date = date.fromisoformat(exam_date_raw)
        except ValueError:
            return jsonify({'success': False, 'error': 'Дата экзамена должна быть в формате YYYY-MM-DD'}), 400
    def _bounded_int(name, minimum, maximum, current=None):
        raw = data.get(name)
        if raw in (None, ''):
            return current
        try:
            return max(minimum, min(maximum, int(raw)))
        except (TypeError, ValueError):
            raise ValueError(name)

    try:
        course.lessons_per_week = _bounded_int('lessons_per_week', 1, 14, course.lessons_per_week)
        course.lesson_duration_minutes = _bounded_int('lesson_duration_minutes', 15, 240, course.lesson_duration_minutes or course.default_lesson_duration)
        homework_raw = data.get('homework_hours_per_week')
        if homework_raw not in (None, ''):
            course.homework_hours_per_week = max(0, min(40, float(homework_raw)))
        diagnostic_mode = str(data.get('diagnostic_mode') or course.diagnostic_mode or 'manual').strip().lower()
        if diagnostic_mode not in {'test', 'manual'}:
            return jsonify({'success': False, 'error': 'Способ диагностики должен быть test или manual'}), 400
        course.diagnostic_mode = diagnostic_mode
        course.starting_forecast = _bounded_int('starting_forecast', 0, 100, course.starting_forecast)
    except ValueError as exc:
        return jsonify({'success': False, 'error': f'Некорректное значение параметра {exc.args[0]}'}), 400
    course.current_forecast = int(data.get('current_forecast') or course.current_forecast or 0)
    course.forecast_low = int(data.get('forecast_low') or course.forecast_low or course.current_forecast)
    course.forecast_high = int(data.get('forecast_high') or course.forecast_high or course.current_forecast)

    diagnostic = data.get('diagnostic') if isinstance(data.get('diagnostic'), dict) else {}
    skills_query = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        skills_query = skills_query.filter(ExamSkill.exam_course_id == course.exam_course_id)
    skills = skills_query.order_by(ExamSkill.topic.asc(), ExamSkill.task_number.asc(), ExamSkill.skill_id.asc()).all()
    if not skills:
        return jsonify({
            'success': False,
            'error': 'Для выбранной экзаменационной программы ещё нет навыков.',
            'manage_url': url_for('courses.course_skills_manage', course_id=course.course_id),
        }), 409

    # Персонализация: уже освоенные навыки не получают лишний элемент; слабые получают повторение.
    generated = []
    prerequisite_warnings = []
    for index, skill in enumerate(skills, start=1):
        try:
            percent = max(0, min(100, int(diagnostic.get(str(skill.skill_id), diagnostic.get(skill.skill_id, 0)) or 0)))
        except (TypeError, ValueError):
            percent = 0
        mastery = StudentSkill.query.filter_by(student_id=course.student_id, skill_id=skill.skill_id).first()
        if not mastery:
            mastery = StudentSkill(student_id=course.student_id, skill_id=skill.skill_id, source='diagnostic')
            db.session.add(mastery)
        mastery.mastery_percent = percent
        mastery.state = 'mastered' if percent >= 85 else ('reinforcing' if percent >= 50 else 'learning')
        mastery.last_checked_at = utc_now()
        if skill.prerequisite_skill_id:
            prerequisite = StudentSkill.query.filter_by(student_id=course.student_id, skill_id=skill.prerequisite_skill_id).first()
            prerequisite_percent = int(prerequisite.mastery_percent if prerequisite else 0)
            if prerequisite_percent < 60:
                prerequisite_warnings.append({'skill_id': skill.skill_id, 'prerequisite_id': skill.prerequisite_skill_id, 'mastery_percent': prerequisite_percent})
        item_type = 'review' if percent < 50 and percent > 0 else ('practice' if percent < 85 else 'control')
        item = LearningItem.query.filter_by(course_id=course.course_id, skill_id=skill.skill_id).first()
        if not item:
            item = LearningItem(course_id=course.course_id, skill_id=skill.skill_id)
            db.session.add(item)
        item.item_type = item_type
        item.title = skill.title
        item.status = 'done' if percent >= 85 else 'planned'
        item.why_now = ('Сначала укрепить prerequisite-навык' if skill.prerequisite_skill_id and any(w['skill_id'] == skill.skill_id for w in prerequisite_warnings) else ('Закрепить слабое место по диагностике' if percent < 50 else ('Проверить устойчивость навыка' if percent >= 85 else 'Перевести навык из изучения в закрепление')))
        item.order_index = index * 10
        generated.append({'skill_id': skill.skill_id, 'item_type': item_type, 'mastery_percent': percent})
    if diagnostic:
        db.session.add(StudentDiagnosticCheckpoint(
            student_id=course.student_id,
            created_by_user_id=current_user.id,
            kind='baseline',
            note=str(data.get('diagnostic_note') or '').strip()[:4000] or None,
            metrics={'skills': generated, 'course_id': course.course_id},
            problem_topics=[entry['skill_id'] for entry in generated if entry['mastery_percent'] < 50],
            recommendations=[entry['skill_id'] for entry in generated if entry['item_type'] == 'review'],
        ))
    db.session.commit()
    available_lessons = None
    if course.exam_date and course.lessons_per_week:
        days = max(0, (course.exam_date - date.today()).days)
        available_lessons = round(days / 7 * course.lessons_per_week)
    return jsonify({'success': True, 'course_id': course.course_id, 'generated': generated, 'prerequisite_warnings': prerequisite_warnings,
                    'target_score': course.target_score, 'exam_date': course.exam_date.isoformat() if course.exam_date else None,
                    'mode': {'lessons_per_week': course.lessons_per_week, 'lesson_duration_minutes': course.lesson_duration_minutes,
                             'homework_hours_per_week': float(course.homework_hours_per_week) if course.homework_hours_per_week is not None else None,
                             'diagnostic_mode': course.diagnostic_mode, 'starting_forecast': course.starting_forecast,
                             'available_lessons': available_lessons},
                    'mock_diff': getattr(g, 'course_mock_diff', None)})


@courses_bp.route('/courses/<int:course_id>/mock-replan', methods=['POST'])
@login_required
def course_mock_replan(course_id: int):
    """Пересобирает маршрут после пробника, используя новые результаты диагностики."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    data = request.get_json(silent=True) or {}
    diagnostic = data.get('diagnostic')
    if not isinstance(diagnostic, dict) or not diagnostic:
        return jsonify({'success': False, 'error': 'Передайте diagnostic с результатами пробника'}), 400
    previous = StudentDiagnosticCheckpoint.query.filter_by(student_id=course.student_id).filter(
        StudentDiagnosticCheckpoint.kind.in_(['mock_test', 'baseline'])
    ).order_by(StudentDiagnosticCheckpoint.created_at.desc()).first()
    previous_values = ((previous.metrics or {}).get('diagnostic') or {}) if previous else {}
    diff = []
    for key, value in diagnostic.items():
        try:
            new_value = int(value)
            old_value = int(previous_values.get(str(key), previous_values.get(key, 0)))
        except (TypeError, ValueError):
            continue
        if new_value != old_value:
            skill = ExamSkill.query.get(int(key)) if str(key).isdigit() else None
            diff.append({'skill_id': int(key) if str(key).isdigit() else key,
                         'title': skill.title if skill else str(key), 'before': old_value, 'after': new_value,
                         'delta': new_value - old_value,
                         'recommendation': 'усилить практику' if new_value < old_value else 'сократить повторение'})
    g.course_mock_diff = diff
    # Сохраняем контрольную точку до пересборки, после чего используем тот же
    # проверенный генератор, что и мастер первичного маршрута.
    db.session.add(StudentDiagnosticCheckpoint(student_id=course.student_id, kind='mock_test',
        note=str(data.get('note') or 'Результаты пробного экзамена').strip()[:4000],
        metrics={'course_id': course.course_id, 'diagnostic': diagnostic},
        problem_topics=[str(key) for key, value in diagnostic.items() if str(value).isdigit() and int(value) < 50],
        recommendations=[]))
    db.session.commit()
    return course_plan_generate(course_id)


@courses_bp.route('/courses/<int:course_id>/adaptation/actions', methods=['POST'])
@login_required
def course_adaptation_action(course_id: int):
    """Apply a teacher decision to an adaptive-route recommendation.

    Recommendations are deliberately not auto-applied: the teacher chooses
    whether to add a lesson/homework, ignore the signal, or shorten the route.
    The decision is represented by LearningItem status/type so dashboards and
    future regeneration can reason over the same source of truth.
    """
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    payload = request.get_json(silent=True) or request.form
    wants_json = request.is_json or 'application/json' in (request.headers.get('Accept') or '').lower()

    def respond(data, status=200):
        if not wants_json:
            flash('Адаптивное решение сохранено.', 'success')
            return redirect(url_for('courses.course_attention', course_id=course.course_id, view=1))
        return jsonify(data), status

    action = str(payload.get('action') or '').strip().lower()
    if action not in {'add_lesson', 'add_homework', 'ignore', 'shorten'}:
        return jsonify({'success': False, 'error': 'Неизвестное действие адаптации'}), 400
    try:
        skill_id = int(payload.get('skill_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Укажите навык рекомендации'}), 400
    skill = ExamSkill.query.filter_by(skill_id=skill_id, is_active=True).first()
    if not skill or (course.exam_course_id and skill.exam_course_id != course.exam_course_id):
        return jsonify({'success': False, 'error': 'Навык не относится к экзаменационной программе'}), 400
    existing = LearningItem.query.filter_by(course_id=course.course_id, skill_id=skill.skill_id).order_by(LearningItem.item_id.asc()).all()
    if action in {'add_lesson', 'add_homework'}:
        desired_type = 'lesson' if action == 'add_lesson' else 'homework'
        item = next((row for row in existing if row.item_type == desired_type and row.status not in {'skipped', 'cancelled'}), None)
        if item is None:
            max_order = db.session.query(db.func.max(LearningItem.order_index)).filter_by(course_id=course.course_id).scalar() or 0
            item = LearningItem(course_id=course.course_id, skill_id=skill.skill_id, item_type=desired_type,
                                title=skill.title, status='planned', order_index=int(max_order) + 10,
                                why_now='Добавлено преподавателем по адаптивной рекомендации')
            db.session.add(item)
            db.session.commit()
            created = True
        else:
            created = False
        return respond({'success': True, 'action': action, 'created': created, 'item': {
            'id': item.item_id, 'type': item.item_type, 'status': item.status, 'skill_id': item.skill_id,
        }})
    changed = 0
    for item in existing:
        if item.status in {'planned', 'in_progress'}:
            item.status = 'skipped'
            item.why_now = ('Рекомендация проигнорирована преподавателем' if action == 'ignore'
                            else 'Элемент сокращён преподавателем после проверки освоения')
            changed += 1
    if not existing and action == 'ignore':
        item = LearningItem(course_id=course.course_id, skill_id=skill.skill_id, item_type='review',
                            title=skill.title, status='skipped', why_now='Рекомендация проигнорирована преподавателем')
        db.session.add(item)
        changed = 1
    db.session.commit()
    return respond({'success': True, 'action': action, 'changed': changed, 'skill_id': skill.skill_id})


@courses_bp.route('/courses/<int:course_id>/plan/wizard')
@login_required
def course_plan_wizard(course_id: int):
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    skills_query = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        skills_query = skills_query.filter(ExamSkill.exam_course_id == course.exam_course_id)
    skills = skills_query.order_by(ExamSkill.topic.asc(), ExamSkill.task_number.asc()).all()
    mastery = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=course.student_id).all()}
    return render_template(
        'course_plan_wizard.html',
        course=course,
        skills=skills,
        mastery=mastery,
        skills_manage_url=url_for('courses.course_skills_manage', course_id=course.course_id),
    )


@courses_bp.route('/course-templates', methods=['GET', 'POST'])
@login_required
def course_templates():
    """Каталог шаблонов индивидуальных программ."""
    if request.method == 'GET':
        templates = LearningTrajectoryTemplate.query.filter_by(is_active=True).order_by(LearningTrajectoryTemplate.updated_at.desc()).all()
        if request.args.get('view') == '1':
            if not _course_viewer_can_manage():
                abort(403)
            return render_template('course_templates.html', templates=templates, editor=request.args.get('editor') == '1')
        return jsonify({'templates': [
            {'id': item.template_id, 'title': item.title, 'description': item.description, 'target_score': item.target_score,
             'estimated_lessons': item.estimated_lessons, 'modules': len(item.modules)} for item in templates
        ]})
    if not _course_viewer_can_manage():
        abort(403)
    is_json = request.is_json
    data = request.get_json(silent=True) if is_json else request.form.to_dict()
    data = data or {}
    if not is_json:
        try:
            data['modules'] = json.loads(data.get('modules_json') or '[]')
        except (TypeError, ValueError):
            return render_template('course_templates.html', templates=LearningTrajectoryTemplate.query.filter_by(is_active=True).all(), editor=True, form_error='Модули должны быть валидным JSON-массивом.'), 400
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'Название шаблона обязательно'}), 400
    template = LearningTrajectoryTemplate(owner_user_id=current_user.id, title=title[:240], description=str(data.get('description') or '').strip()[:5000] or None,
                                         target_score=data.get('target_score') or None, estimated_lessons=data.get('estimated_lessons') or None,
                                         exam_course_id=data.get('exam_course_id') or None)
    db.session.add(template)
    for module_index, module_data in enumerate(data.get('modules') or [], start=1):
        module_title = str(module_data.get('title') or '').strip()
        if not module_title:
            continue
        module = LearningTrajectoryTemplateModule(template=template, title=module_title[:240], description=str(module_data.get('description') or '').strip()[:3000] or None,
                                                  order_index=module_data.get('order_index') or module_index)
        db.session.add(module)
        for item_index, item_data in enumerate(module_data.get('items') or [], start=1):
            item_title = str(item_data.get('title') or '').strip()
            if not item_title:
                continue
            db.session.add(LearningTrajectoryTemplateItem(module=module, skill_id=item_data.get('skill_id') or None,
                                                          item_type=str(item_data.get('type') or 'practice')[:30], title=item_title[:300],
                                                          duration_minutes=item_data.get('duration_minutes') or None,
                                                          order_index=item_data.get('order_index') or item_index,
                                                          metadata_json=item_data.get('metadata') if isinstance(item_data.get('metadata'), dict) else None))
    db.session.commit()
    if not is_json:
        flash('Шаблон программы создан.', 'success')
        return redirect(url_for('courses.course_templates', view=1, editor=1, course_id=request.args.get('course_id')))
    return jsonify({'success': True, 'template_id': template.template_id}), 201


@courses_bp.route('/courses/<int:course_id>/apply-template/<int:template_id>', methods=['POST'])
@login_required
def course_apply_template(course_id: int, template_id: int):
    """Персонализирует шаблон: создаёт модули/items, сохраняя живые ссылки на навыки."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    template = LearningTrajectoryTemplate.query.filter_by(template_id=template_id, is_active=True).first_or_404()
    _snapshot_course(course, 'apply_template')
    if template.target_score and not course.target_score:
        course.target_score = template.target_score
    created = 0
    for template_module in sorted(template.modules, key=lambda row: (row.order_index, row.template_module_id)):
        module = TrajectoryModule(course_id=course.course_id, title=template_module.title, description=template_module.description,
                                  order_index=template_module.order_index)
        db.session.add(module)
        db.session.flush()
        for template_item in sorted(template_module.items, key=lambda row: (row.order_index, row.template_item_id)):
            item = LearningItem(course_id=course.course_id, module_id=module.module_id, skill_id=template_item.skill_id,
                                item_type=template_item.item_type, title=template_item.title, order_index=template_item.order_index,
                                metadata_json=dict(template_item.metadata_json or {}), status='planned')
            db.session.add(item)
            created += 1
    db.session.commit()
    return jsonify({'success': True, 'course_id': course.course_id, 'items_created': created, 'version': course.current_version})


@courses_bp.route('/courses/<int:course_id>/reviews', methods=['GET', 'POST'])
@login_required
def course_reviews(course_id: int):
    """Интервальное повторение навыков и очередь проблемных тем."""
    course = _guard_course(course_id)
    rows = StudentSkill.query.filter_by(student_id=course.student_id).filter(StudentSkill.next_review_at.isnot(None)).order_by(StudentSkill.next_review_at.asc()).all()
    if request.method == 'GET':
        now = utc_now()
        return jsonify({'course_id': course.course_id, 'due': [
            {'skill_id': row.skill_id, 'title': row.skill.title if row.skill else None, 'mastery_percent': row.mastery_percent,
             'state': row.state, 'next_review_at': row.next_review_at.isoformat(), 'is_due': row.next_review_at <= now}
            for row in rows
        ]})
    if not _course_viewer_can_manage():
        abort(403)
    data = request.get_json(silent=True) or {}
    skill_id = data.get('skill_id')
    row = StudentSkill.query.filter_by(student_id=course.student_id, skill_id=skill_id).first_or_404()
    try:
        result = max(0, min(100, int(data.get('mastery_percent', row.mastery_percent))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректный результат повторения'}), 400
    row.mastery_percent = result
    row.state = 'mastered' if result >= 85 else ('reinforcing' if result >= 50 else 'needs_review')
    interval_days = 60 if result >= 85 else (21 if result >= 50 else 7)
    row.next_review_at = utc_now() + timedelta(days=interval_days)
    row.last_checked_at = utc_now()
    review_item = LearningItem.query.filter_by(course_id=course.course_id, skill_id=row.skill_id, item_type='review').filter(
        LearningItem.status.notin_(['done', 'skipped', 'cancelled'])
    ).order_by(LearningItem.item_id.asc()).first()
    if not review_item:
        review_item = LearningItem(course_id=course.course_id, skill_id=row.skill_id, item_type='review',
                                   title=row.skill.title if row.skill else 'Повторение навыка', status='planned', order_index=9000)
        db.session.add(review_item)
    review_item.due_at = row.next_review_at
    review_item.why_now = f'Интервальное закрепление: следующий контроль через {interval_days} дн.'
    db.session.commit()
    return jsonify({'success': True, 'skill_id': row.skill_id, 'mastery_percent': row.mastery_percent, 'next_review_at': row.next_review_at.isoformat(), 'interval_days': interval_days, 'review_item_id': review_item.item_id})


@courses_bp.route('/courses/<int:course_id>/weekly-plan')
@login_required
def course_weekly_plan(course_id: int):
    """Единый календарный срез маршрута для ученика, преподавателя и родителя."""
    course = _guard_course(course_id)
    start = date.today()
    end = start + timedelta(days=7)
    items = LearningItem.query.filter_by(course_id=course.course_id).filter(
        LearningItem.status.in_(['planned', 'in_progress', 'overdue'])
    ).order_by(LearningItem.due_at.asc(), LearningItem.order_index.asc()).all()
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(Lesson.lesson_date.asc().nullslast(), Lesson.lesson_id.asc()).all()
    payload = []
    for item in items:
        due = item.due_at
        state = 'overdue' if due is not None and due.date() < start else ('this_week' if due is not None and due.date() <= end else 'backlog')
        payload.append({'id': item.item_id, 'type': item.item_type, 'title': item.title, 'status': item.status,
                        'state': state, 'due_at': due.isoformat() if due else None, 'why_now': item.why_now,
                        'skill_id': item.skill_id, 'lesson_id': item.lesson_id})
    for lesson in lessons:
        if lesson.lesson_date and start <= lesson.lesson_date.date() <= end:
            payload.append({'id': f'lesson-{lesson.lesson_id}', 'type': 'lesson', 'title': lesson.topic,
                            'status': lesson.status, 'state': 'this_week', 'due_at': lesson.lesson_date.isoformat(),
                            'why_now': 'Запланированное занятие', 'skill_id': None, 'lesson_id': lesson.lesson_id})
    payload.sort(key=lambda row: (row['due_at'] or '9999', str(row['id'])))
    counts = {'this_week': sum(row['state'] == 'this_week' for row in payload),
              'overdue': sum(row['state'] == 'overdue' for row in payload),
              'backlog': sum(row['state'] == 'backlog' for row in payload)}
    if request.args.get('view') == '1':
        return render_template('course_weekly_plan.html', course=course, items=payload, counts=counts, student=Student.query.get_or_404(course.student_id))
    return jsonify({'course_id': course.course_id, 'range': {'from': start.isoformat(), 'to': end.isoformat()}, 'items': payload, 'counts': counts})


@courses_bp.route('/courses/<int:course_id>/attention')
@login_required
def course_attention(course_id: int):
    """Центр внимания: конкретные причины, требующие действия преподавателя."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    now = utc_now()
    errors = LearningError.query.filter_by(student_id=course.student_id).filter(LearningError.resolved_at.is_(None)).order_by(LearningError.last_seen_at.desc()).limit(50).all()
    due_reviews = StudentSkill.query.filter_by(student_id=course.student_id).filter(StudentSkill.next_review_at.isnot(None), StudentSkill.next_review_at <= now).all()
    overdue_items = LearningItem.query.filter_by(course_id=course.course_id).filter(LearningItem.status.in_(['planned', 'overdue']), LearningItem.due_at.isnot(None), LearningItem.due_at < now).order_by(LearningItem.due_at.asc()).limit(50).all()
    unfinished = Lesson.query.filter_by(learning_trajectory_id=course.course_id).filter(Lesson.status.in_(['in_progress', 'scheduled'])).order_by(Lesson.lesson_date.asc().nullslast(), Lesson.lesson_id.asc()).all()
    attention = {
        'errors': [{'id': row.error_id, 'skill_id': row.skill_id, 'type': row.error_type, 'description': row.description, 'occurrences': row.occurrences, 'last_seen_at': row.last_seen_at.isoformat() if row.last_seen_at else None} for row in errors],
        'reviews_due': [{'skill_id': row.skill_id, 'title': row.skill.title if row.skill else None, 'mastery_percent': row.mastery_percent} for row in due_reviews],
        'overdue_items': [{'id': row.item_id, 'title': row.title, 'type': row.item_type, 'due_at': row.due_at.isoformat()} for row in overdue_items],
        'unfinished_lessons': [{'id': row.lesson_id, 'topic': row.topic, 'status': row.status} for row in unfinished]}
    if request.args.get('view') == '1':
        return render_template('course_attention.html', course=course, attention=attention, student=Student.query.get_or_404(course.student_id))
    return jsonify({'course_id': course.course_id, 'attention': attention})


@courses_bp.route('/courses/attention', methods=['GET'])
@login_required
def courses_attention_overview():
    """Общий V2-центр внимания преподавателя по всем доступным маршрутам."""
    if not _course_viewer_can_manage():
        abort(403)
    scope = get_user_scope(current_user)
    query = LearningTrajectory.query.filter(LearningTrajectory.status == 'active')
    courses = query.order_by(LearningTrajectory.updated_at.desc()).all()
    if not scope.get('can_see_all') and not (current_user.is_creator() or current_user.is_admin()):
        courses = [course for course in courses if _can_access_student(Student.query.get(course.student_id))]
    now = utc_now()
    rows = []
    for course in courses:
        student = Student.query.get(course.student_id)
        if not student:
            continue
        open_errors = LearningError.query.filter_by(student_id=student.student_id).filter(LearningError.resolved_at.is_(None)).count()
        due_reviews = StudentSkill.query.filter_by(student_id=student.student_id).filter(
            StudentSkill.next_review_at.isnot(None), StudentSkill.next_review_at <= now
        ).count()
        overdue = LearningItem.query.filter_by(course_id=course.course_id).filter(
            LearningItem.status.in_(['planned', 'overdue']), LearningItem.due_at.isnot(None), LearningItem.due_at < now
        ).count()
        unfinished = Lesson.query.filter_by(learning_trajectory_id=course.course_id).filter(
            Lesson.status.in_(['draft', 'planned', 'scheduled', 'in_progress'])
        ).count()
        total = open_errors + due_reviews + overdue + unfinished
        if total:
            rows.append({'course_id': course.course_id, 'student_id': student.student_id,
                         'student_name': student.name, 'course_title': course.title,
                         'errors': open_errors, 'reviews_due': due_reviews, 'overdue_items': overdue,
                         'unfinished_lessons': unfinished, 'total': total})
    rows.sort(key=lambda row: (-row['total'], row['student_name'] or ''))
    payload = {'courses': rows, 'totals': {
        'students': len(rows), 'errors': sum(row['errors'] for row in rows),
        'reviews_due': sum(row['reviews_due'] for row in rows), 'overdue_items': sum(row['overdue_items'] for row in rows),
        'unfinished_lessons': sum(row['unfinished_lessons'] for row in rows),
    }}
    if request.args.get('view') == '1':
        return render_template('course_attention_overview.html', payload=payload)
    return jsonify(payload)


@courses_bp.route('/courses/<int:course_id>/parent-summary')
@login_required
def course_parent_summary(course_id: int):
    """Read-only сводка курса для связанного родителя."""
    course = _guard_course(course_id)
    if not current_user.is_parent():
        abort(403)
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).all()
    skills = ExamSkill.query.filter_by(exam_course_id=course.exam_course_id, is_active=True).all() if course.exam_course_id else []
    rows = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=course.student_id).all()}
    mastery = [rows[s.skill_id].mastery_percent for s in skills if s.skill_id in rows]
    completed = sum((lesson.status or '').lower() == 'completed' for lesson in lessons)
    next_item = LearningItem.query.filter_by(course_id=course.course_id, status='planned').order_by(LearningItem.due_at.asc()).first()
    return jsonify({'course_id': course.course_id, 'title': course.title, 'status': course.status, 'target_score': course.target_score,
                    'forecast': {'value': course.current_forecast, 'low': course.forecast_low, 'high': course.forecast_high},
                    'progress': {'completed_lessons': completed, 'total_lessons': len(lessons), 'mastery_percent': round(sum(mastery) / len(mastery)) if mastery else None},
                    'next_step': next_item.title if next_item else None})


@courses_bp.route('/courses/<int:course_id>/errors', methods=['GET', 'POST'])
@login_required
def course_errors(course_id: int):
    course = _guard_course(course_id)
    if request.method == 'GET':
        errors = LearningError.query.filter_by(student_id=course.student_id).order_by(LearningError.last_seen_at.desc()).all()
        return jsonify({'course_id': course.course_id, 'errors': [
            {'id': error.error_id, 'skill_id': error.skill_id, 'task_id': error.task_id, 'type': error.error_type,
             'description': error.description, 'occurrences': error.occurrences, 'last_seen_at': error.last_seen_at.isoformat() if error.last_seen_at else None,
             'next_review_at': error.next_review_at.isoformat() if error.next_review_at else None, 'resolved': bool(error.resolved_at)}
            for error in errors
        ]})
    if not _course_viewer_can_manage():
        abort(403)
    data = request.get_json(silent=True) or {}
    error_type = str(data.get('type') or '').strip()[:120]
    if not error_type:
        return jsonify({'success': False, 'error': 'Укажите тип ошибки'}), 400
    skill_id = data.get('skill_id') or None
    existing = LearningError.query.filter_by(student_id=course.student_id, skill_id=skill_id, error_type=error_type, resolved_at=None).first()
    if existing:
        existing.occurrences += 1
        existing.description = str(data.get('description') or existing.description or '').strip()[:4000] or None
        existing.last_seen_at = utc_now()
    else:
        existing = LearningError(student_id=course.student_id, skill_id=skill_id, lesson_id=data.get('lesson_id') or None,
                                 task_id=data.get('task_id') or None, error_type=error_type,
                                 description=str(data.get('description') or '').strip()[:4000] or None, next_review_at=utc_now() + timedelta(days=7))
        db.session.add(existing)
    if skill_id:
        review_item = LearningItem.query.filter_by(course_id=course.course_id, skill_id=skill_id, item_type='review').filter(
            LearningItem.status.notin_(['done', 'skipped', 'cancelled'])
        ).order_by(LearningItem.item_id.asc()).first()
        if not review_item:
            review_item = LearningItem(course_id=course.course_id, skill_id=skill_id, item_type='review',
                                       title='Повторение после ошибки', status='planned', order_index=9000)
            db.session.add(review_item)
        review_item.due_at = existing.next_review_at
        review_item.why_now = f'Повторить после ошибки: {error_type}'
    db.session.commit()
    return jsonify({'success': True, 'error_id': existing.error_id, 'occurrences': existing.occurrences,
                    'review_item_id': review_item.item_id if skill_id else None})


@courses_bp.route('/courses/<int:course_id>/forecast')
@login_required
def course_forecast(course_id: int):
    """Ориентировочный прогноз по текущему mastery; не выдаёт ложную точность."""
    course = _guard_course(course_id)
    skills = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        skills = skills.filter(ExamSkill.exam_course_id == course.exam_course_id)
    skills = skills.all()
    rows = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=course.student_id).all()}
    total_weight = sum(float(skill.weight or 1) for skill in skills) or 1
    weighted = sum((rows.get(skill.skill_id).mastery_percent if rows.get(skill.skill_id) else 0) * float(skill.weight or 1) for skill in skills)
    mastery = round(weighted / total_weight)
    target = course.target_score or 0
    forecast = round(mastery * (target / 100)) if target else mastery
    low, high = max(0, forecast - 5), min(100, forecast + 5)
    return jsonify({'course_id': course.course_id, 'mastery_percent': mastery, 'forecast': forecast, 'range': [low, high], 'target_score': target, 'disclaimer': 'Ориентировочный прогноз, а не точный результат экзамена.'})


@courses_bp.route('/courses/<int:course_id>/skills/<int:skill_id>', methods=['POST'])
@login_required
def course_skill_update(course_id: int, skill_id: int):
    """Сохраняет подтверждённый преподавателем уровень навыка ученика."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    skill = ExamSkill.query.filter_by(skill_id=skill_id, is_active=True).first_or_404()
    if course.exam_course_id and skill.exam_course_id not in (None, course.exam_course_id):
        abort(404)
    data = request.get_json(silent=True) or request.form
    try:
        mastery_percent = max(0, min(100, int(data.get('mastery_percent', 0))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'mastery_percent должен быть числом от 0 до 100'}), 400
    state = (data.get('state') or '').strip() or ('mastered' if mastery_percent >= 85 else ('reinforcing' if mastery_percent >= 50 else 'learning'))
    if state not in {'not_started', 'learning', 'reinforcing', 'mastered', 'needs_review'}:
        return jsonify({'success': False, 'error': 'Недопустимое состояние навыка'}), 400
    row = StudentSkill.query.filter_by(student_id=course.student_id, skill_id=skill.skill_id).first()
    if not row:
        row = StudentSkill(student_id=course.student_id, skill_id=skill.skill_id)
        db.session.add(row)
    row.mastery_percent = mastery_percent
    row.state = state
    row.theory_done = bool(data.get('theory_done', row.theory_done))
    row.practice_done = bool(data.get('practice_done', row.practice_done))
    row.source = 'teacher'
    row.last_checked_at = utc_now()
    db.session.commit()
    return jsonify({'success': True, 'skill_id': skill.skill_id, 'mastery_percent': row.mastery_percent, 'state': row.state})


@courses_bp.route('/courses/<int:course_id>/modules/new', methods=['GET', 'POST'])
@login_required
def module_new(course_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)

    form = CourseModuleForm()
    if form.validate_on_submit():
        module = TrajectoryModule(
            course_id=course.course_id,
            title=form.title.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            learning_result=form.learning_result.data.strip() if form.learning_result.data else None,
            order_index=form.order_index.data or 0,
        )
        db.session.add(module)
        db.session.commit()
        flash('Модуль добавлен.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    return render_template('course_module_form.html', form=form, student=student, course=course, title='Добавить модуль')


@courses_bp.route('/courses/<int:course_id>/modules/<int:module_id>/edit', methods=['GET', 'POST'])
@login_required
def module_edit(course_id: int, module_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)
    module = TrajectoryModule.query.filter_by(module_id=module_id, course_id=course.course_id).first_or_404()
    form = CourseModuleForm(obj=module)
    if form.validate_on_submit():
        _snapshot_course(course, 'module_edit')
        module.title = form.title.data.strip()
        module.description = form.description.data.strip() if form.description.data else None
        module.learning_result = form.learning_result.data.strip() if form.learning_result.data else None
        module.order_index = form.order_index.data or 0
        db.session.commit()
        flash('Модуль обновлён.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'module-{module.module_id}'))
    return render_template('course_module_form.html', form=form, student=student, course=course, module=module, title='Редактировать модуль')


def _require_course_manager(course: LearningTrajectory) -> Student:
    student = Student.query.get_or_404(course.student_id)
    if not _course_viewer_can_manage():
        abort(403)
    return student


def _course_lesson_form(course: LearningTrajectory, lesson: Lesson | None = None) -> CourseLessonForm:
    form = CourseLessonForm(obj=lesson)
    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).order_by(
        TrajectoryModule.order_index.asc(), TrajectoryModule.module_id.asc()
    ).all()
    form.module_id.choices = [(0, 'Без модуля — добавить позже')] + [(module.module_id, module.title) for module in modules]
    if lesson and not form.is_submitted():
        form.module_id.data = lesson.course_module_id or 0
        local_date = lesson_storage_to_local(lesson.lesson_date, effective_timezone_name(current_user))
        form.lesson_date.data = local_date.replace(tzinfo=None) if local_date else None
        form.scenario.data = '\n'.join(
            str(item.get('title') or '').strip()
            for item in ((lesson.review_summaries or {}).get('_studio') or {}).get('agenda', [])
            if isinstance(item, dict) and str(item.get('title') or '').strip()
        )
        form.teacher_note.data = lesson.notes or ''
    return form


def _save_course_lesson_from_form(course: LearningTrajectory, lesson: Lesson, form: CourseLessonForm) -> None:
    module_id = form.module_id.data or None
    if module_id and not TrajectoryModule.query.filter_by(module_id=module_id, course_id=course.course_id).first():
        abort(400)

    local_date = form.lesson_date.data
    if local_date:
        lesson.lesson_date = parse_local_lesson_datetime(
            local_date.strftime('%Y-%m-%d'), local_date.strftime('%H:%M'), effective_timezone_name(current_user)
        )
    else:
        lesson.lesson_date = None

    agenda = []
    for index, raw_title in enumerate((form.scenario.data or '').splitlines(), start=1):
        title = raw_title.strip(' -•\t')
        if title:
            agenda.append({'id': f'course-step-{index}', 'title': title[:300], 'done': False})

    summaries = dict(lesson.review_summaries or {})
    studio_state = dict(summaries.get('_studio') or {})
    studio_state['agenda'] = agenda
    summaries['_studio'] = studio_state

    lesson.course_module_id = module_id
    lesson.learning_trajectory_id = course.course_id
    lesson.topic = form.topic.data.strip()
    lesson.course_order_index = form.course_order_index.data
    lesson.duration = form.duration.data
    lesson.lesson_type = form.lesson_type.data
    lesson.status = form.status.data
    lesson.content = form.content.data.strip() if form.content.data else None
    lesson.homework = form.homework.data.strip() if form.homework.data else None
    lesson.homework_status = 'assigned_not_done' if lesson.homework else 'not_assigned'
    lesson.notes = form.teacher_note.data.strip() if form.teacher_note.data else None
    lesson.review_summaries = summaries


def _ensure_lesson_learning_item(course: LearningTrajectory, lesson: Lesson) -> None:
    """Каждое занятие из программы имеет единый item для будущих элементов обучения."""
    item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).first()
    if not item:
        item = LearningItem(
            course_id=course.course_id,
            module_id=lesson.course_module_id,
            lesson_id=lesson.lesson_id,
            item_type='lesson',
            title=lesson.topic or 'Занятие',
            status='done' if lesson.status == 'completed' else ('in_progress' if lesson.status == 'in_progress' else 'planned'),
            order_index=lesson.course_order_index or 0,
        )
        db.session.add(item)
    else:
        item.module_id = lesson.course_module_id
        item.title = lesson.topic or item.title
        item.status = 'done' if lesson.status == 'completed' else ('in_progress' if lesson.status == 'in_progress' else item.status)


def _next_course_lesson_order(course: LearningTrajectory) -> int:
    module_ids = [
        row.module_id
        for row in TrajectoryModule.query.with_entities(TrajectoryModule.module_id).filter_by(course_id=course.course_id).all()
    ]
    belongs_to_course = Lesson.learning_trajectory_id == course.course_id
    if module_ids:
        belongs_to_course = or_(belongs_to_course, Lesson.course_module_id.in_(module_ids))
    current_max = (
        db.session.query(db.func.coalesce(db.func.max(Lesson.course_order_index), 0))
        .filter(Lesson.student_id == course.student_id, belongs_to_course)
        .scalar()
        or 0
    )
    return int(current_max) + 10


@courses_bp.route('/courses/<int:course_id>/lessons/new', methods=['GET', 'POST'])
@login_required
def course_lesson_new(course_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)
    lesson = Lesson(
        student_id=student.student_id,
        learning_trajectory_id=course.course_id,
        duration=course.default_lesson_duration or 60,
        status='planned',
        lesson_type='regular',
        course_order_index=_next_course_lesson_order(course),
    )
    form = _course_lesson_form(course)
    if not form.is_submitted():
        form.duration.data = course.default_lesson_duration or 60
        form.course_order_index.data = lesson.course_order_index
        requested_module_id = request.args.get('module_id', type=int)
        if requested_module_id and any(module_id == requested_module_id for module_id, _ in form.module_id.choices):
            form.module_id.data = requested_module_id
    if form.validate_on_submit():
        _save_course_lesson_from_form(course, lesson, form)
        db.session.add(lesson)
        db.session.commit()
        _ensure_lesson_learning_item(course, lesson)
        db.session.commit()
        flash('Урок добавлен в программу курса.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))
    return render_template('course_lesson_form.html', form=form, course=course, student=student, lesson=None, title='Добавить урок')


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
def course_lesson_edit(course_id: int, lesson_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first_or_404()
    belongs_to_course = lesson.learning_trajectory_id == course.course_id
    if lesson.course_module_id:
        module = TrajectoryModule.query.filter_by(module_id=lesson.course_module_id, course_id=course.course_id).first()
        if not module:
            abort(404)
        belongs_to_course = True
    if not belongs_to_course:
        abort(404)
    form = _course_lesson_form(course, lesson)
    if form.validate_on_submit():
        _snapshot_course(course, 'lesson_edit')
        _save_course_lesson_from_form(course, lesson, form)
        _ensure_lesson_learning_item(course, lesson)
        db.session.commit()
        flash('План урока обновлён.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))
    return render_template('course_lesson_form.html', form=form, course=course, student=student, lesson=lesson, title='Редактировать урок')


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/start', methods=['POST'])
@login_required
def course_lesson_start(course_id: int, lesson_id: int):
    """Явно запускает занятие из учебного плана и открывает V2 Studio."""
    course = _guard_course(course_id)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, student_id=course.student_id).first_or_404()
    if lesson.learning_trajectory_id != course.course_id and not TrajectoryModule.query.filter_by(module_id=lesson.course_module_id, course_id=course.course_id).first():
        abort(404)
    if lesson.status in {'planned', 'draft', 'scheduled'}:
        lesson.status = 'in_progress'
        lesson.started_at = lesson.started_at or utc_now()
        lesson.published_at = lesson.published_at or utc_now()
    # Связываем занятие с живым маршрутом: Studio получает agenda из item/навыка,
    # а банк задач — только одну активную задачу нужного номера, если её ещё нет.
    item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).first()
    if not item:
        item = LearningItem.query.filter_by(course_id=course.course_id, status='in_progress').order_by(LearningItem.order_index.asc()).first()
    if item:
        summaries = dict(lesson.review_summaries or {})
        studio = dict(summaries.get('_studio') or {})
        if not studio.get('agenda'):
            studio['agenda'] = [
                {'id': 'course-item', 'title': item.title or (item.skill.title if item.skill else lesson.topic or 'Занятие'), 'done': False},
                {'id': 'course-practice', 'title': 'Практика и проверка понимания', 'done': False},
            ]
        studio['learning_item_id'] = item.item_id
        studio['skill_id'] = item.skill_id
        summaries['_studio'] = studio
        lesson.review_summaries = summaries
        if not lesson.content and item.skill:
            lesson.content = f"Тема: {item.skill.title}\n\nЦель: {item.why_now or 'закрепить навык на практике.'}"
        if item.skill and not lesson.homework_tasks:
            candidate = Tasks.query.filter_by(task_number=item.skill.task_number, is_active=True).order_by(Tasks.task_id.asc()).first()
            if candidate:
                db.session.add(LessonTask(lesson=lesson, task_id=candidate.task_id, assignment_type='classwork', status='pending'))
    _ensure_lesson_learning_item(course, lesson)
    db.session.commit()
    flash('Занятие запущено в Studio.', 'success')
    return redirect(url_for('lessons.lesson_interactive_room', lesson_id=lesson.lesson_id, pane='work'))


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/auto-tasks', methods=['POST'])
@login_required
def course_lesson_auto_tasks(course_id: int, lesson_id: int):
    """Собирает пакет задач для Studio по навыку занятия.

    Автоматические задачи помечаются в notes, поэтому повторный подбор удаляет
    только свой предыдущий пакет и никогда не трогает ручные задания преподавателя.
    """
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, learning_trajectory_id=course.course_id).first_or_404()
    item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).first()
    if not item or not item.skill:
        return jsonify({'success': False, 'error': 'Для занятия не выбран навык'}), 409
    replace = bool((request.get_json(silent=True) or {}).get('replace'))
    if replace:
        for linked in list(lesson.homework_tasks):
            if (linked.notes or '').startswith('auto:'):
                db.session.delete(linked)
    used_ids = {linked.task_id for linked in lesson.homework_tasks}
    specs = [('warmup', 2, 1), ('practice', 5, 2), ('advanced', 2, 3), ('control', 2, 2), ('homework', 6, 2)]
    created = []
    for category, count, difficulty in specs:
        query = Tasks.query.filter_by(task_number=item.skill.task_number, is_active=True).filter(Tasks.task_id.notin_(used_ids))
        exact = query.filter(Tasks.difficulty_level == difficulty).order_by(Tasks.task_id.asc()).all()
        fallback = query.order_by(Tasks.task_id.asc()).all()
        candidates = exact + [task for task in fallback if task.task_id not in {row.task_id for row in exact}]
        for task in candidates[:count]:
            linked = LessonTask(lesson=lesson, task_id=task.task_id, assignment_type='homework' if category == 'homework' else 'classwork', status='pending', notes=f'auto:{category}')
            db.session.add(linked)
            used_ids.add(task.task_id)
            created.append({'task_id': task.task_id, 'category': category, 'difficulty': task.difficulty_level or difficulty})
    db.session.commit()
    payload = {'success': True, 'lesson_id': lesson.lesson_id, 'created': created, 'count': len(created)}
    if not request.is_json:
        flash(f'Подобрано задач: {len(created)}.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))
    return jsonify(payload)


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/outcome', methods=['GET', 'POST'])
@login_required
def course_lesson_outcome(course_id: int, lesson_id: int):
    """Показывает и сохраняет структурированный итог занятия."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, learning_trajectory_id=course.course_id).first_or_404()
    if request.method == 'GET':
        outcome = LessonOutcome.query.filter_by(lesson_id=lesson.lesson_id).first()
        skills = (ExamSkill.query
                  .join(LearningItem, LearningItem.skill_id == ExamSkill.skill_id)
                  .filter(LearningItem.course_id == course.course_id)
                  .order_by(ExamSkill.task_number.asc(), ExamSkill.skill_id.asc())
                  .distinct().all())
        covered = set((outcome.covered or []) if outcome else [])
        return render_template('course_lesson_outcome.html', course=course, lesson=lesson,
                               outcome=outcome, skills=skills, covered=covered)
    data = request.get_json(silent=True) or request.form
    outcome = LessonOutcome.query.filter_by(lesson_id=lesson.lesson_id).first()
    if not outcome:
        outcome = LessonOutcome(lesson_id=lesson.lesson_id, created_by_user_id=current_user.id)
        db.session.add(outcome)
    if request.is_json:
        covered = data.get('covered') if isinstance(data.get('covered'), (list, dict)) else []
    else:
        covered = request.form.getlist('covered')
    outcome.covered = covered
    outcome.mastery = (data.get('mastery') or '').strip() or None
    outcome.next_action = (data.get('next_action') or '').strip() or None
    outcome.homework_assigned = str(data.get('homework_assigned', '')).lower() in {'1', 'true', 'on', 'yes'}
    outcome.teacher_note = (data.get('teacher_note') or '').strip() or None
    outcome.content_snapshot = {
        'topic': lesson.topic,
        'content': lesson.content,
        'content_blocks': lesson.content_blocks,
        'materials': lesson.materials,
        'review_summaries': lesson.review_summaries,
        'task_ids': [item.task_id for item in lesson.homework_tasks],
    }
    lesson.status = 'completed'
    _ensure_lesson_learning_item(course, lesson)
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True, 'lesson_id': lesson.lesson_id, 'status': lesson.status})
    flash('Итог занятия сохранён.', 'success')
    return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/snapshot', methods=['GET'])
@login_required
def course_lesson_snapshot(course_id: int, lesson_id: int):
    """Показывает зафиксированную версию материалов завершённого занятия."""
    course = _guard_course(course_id)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, learning_trajectory_id=course.course_id).first_or_404()
    outcome = LessonOutcome.query.filter_by(lesson_id=lesson.lesson_id).first()
    if not outcome or not outcome.content_snapshot:
        if request.args.get('view') == '1':
            return render_template('course_lesson_snapshot.html', course=course, lesson=lesson, outcome=None, snapshot={})
        return jsonify({'success': False, 'error': 'Для занятия ещё не сохранён snapshot'}), 404
    snapshot = outcome.content_snapshot or {}
    payload = {'success': True, 'course_id': course.course_id, 'lesson_id': lesson.lesson_id,
               'captured_at': outcome.updated_at.isoformat() if outcome.updated_at else None,
               'snapshot': snapshot}
    if request.args.get('view') == '1':
        return render_template('course_lesson_snapshot.html', course=course, lesson=lesson, outcome=outcome, snapshot=snapshot)
    return jsonify(payload)


@courses_bp.route('/courses/<int:course_id>/status-analytics', methods=['GET'])
@login_required
def course_status_analytics(course_id: int):
    """Раздельная аналитика жизненного цикла занятий курса."""
    course = _guard_course(course_id)
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).all()
    statuses = ('draft', 'planned', 'scheduled', 'in_progress', 'completed', 'rescheduled', 'skipped', 'cancelled')
    counts = {status: sum(1 for lesson in lessons if (lesson.status or 'draft') == status) for status in statuses}
    payload = {'course_id': course.course_id, 'total': len(lessons), 'counts': counts}
    if request.args.get('view') == '1':
        return render_template('course_status_analytics.html', course=course, counts=counts, total=len(lessons))
    return jsonify(payload)


@courses_bp.route('/courses/<int:course_id>/lessons/prepare-next', methods=['POST'])
@login_required
def course_prepare_next_lesson(course_id: int):
    """Готовит черновик следующего занятия по фактическому результату маршрута."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    last_lesson = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(Lesson.lesson_date.desc().nullslast(), Lesson.lesson_id.desc()).first()
    outcome = LessonOutcome.query.filter_by(lesson_id=last_lesson.lesson_id).first() if last_lesson else None
    errors = LearningError.query.filter_by(student_id=course.student_id).filter(LearningError.resolved_at.is_(None)).order_by(LearningError.occurrences.desc(), LearningError.last_seen_at.desc()).limit(3).all()
    next_item = LearningItem.query.filter_by(course_id=course.course_id, status='planned').order_by(LearningItem.due_at.asc(), LearningItem.order_index.asc()).first()
    focus = next_item.title if next_item else (errors[0].description if errors else 'Закрепление текущей темы')
    error_lines = [f"{error.error_type}: {error.description or 'разобрать типовую ошибку'}" for error in errors]
    agenda = ['Короткая проверка предыдущего результата', f'Основная тема: {focus}', 'Практика и контроль понимания']
    if error_lines:
        agenda.insert(1, 'Работа над ошибками: ' + '; '.join(error_lines))
    lesson = Lesson(student_id=course.student_id, learning_trajectory_id=course.course_id,
                    course_module_id=next_item.module_id if next_item else None,
                    topic=f'Продолжение: {focus}'[:300], status='draft', duration=course.default_lesson_duration or 60,
                    lesson_type='regular', content='\n'.join(f'- {line}' for line in agenda),
                    review_summaries={'_studio': {'agenda': [{'title': line} for line in agenda], 'generated_from': {
                        'lesson_id': last_lesson.lesson_id if last_lesson else None,
                        'outcome_id': outcome.outcome_id if outcome else None,
                        'error_ids': [error.error_id for error in errors],
                        'learning_item_id': next_item.item_id if next_item else None}}},
                    notes='Черновик создан автоматически. Проверьте и отредактируйте перед запуском.')
    db.session.add(lesson)
    db.session.flush()
    _ensure_lesson_learning_item(course, lesson)
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True, 'lesson_id': lesson.lesson_id, 'status': lesson.status, 'focus': focus, 'agenda': agenda}), 201
    flash('Черновик следующего занятия подготовлен.', 'success')
    return redirect(url_for('courses.course_lesson_edit', course_id=course.course_id, lesson_id=lesson.lesson_id))


@courses_bp.route('/courses/<int:course_id>/assign-lesson', methods=['POST'])
@login_required
def course_assign_lesson(course_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)

    lesson_id = request.form.get('lesson_id', type=int)
    module_id = request.form.get('module_id', type=int)
    if not lesson_id or not module_id:
        flash('Выберите урок и модуль.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    module = TrajectoryModule.query.filter_by(module_id=module_id, course_id=course.course_id).first()
    if not module:
        flash('Модуль не найден.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    lesson = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
    if not lesson:
        flash('Урок не найден.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    if lesson.learning_trajectory_id and lesson.learning_trajectory_id != course.course_id:
        flash('Этот урок уже относится к другой программе. Сначала откройте нужный курс.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    lesson.course_module_id = module.module_id
    lesson.learning_trajectory_id = course.course_id
    db.session.commit()
    flash('Урок привязан к модулю.', 'success')
    return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'module-{module.module_id}'))


@courses_bp.route('/courses/<int:course_id>/delete', methods=['POST'])
@login_required
def course_delete(course_id: int):
    course = _guard_course(course_id)
    _require_course_manager(course)

    student_id = course.student_id
    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).all()
    module_ids = [m.module_id for m in modules]

    if module_ids:
        Lesson.query.filter(Lesson.course_module_id.in_(module_ids)).update(
            {Lesson.course_module_id: None}, synchronize_session=False
        )
        TrajectoryModule.query.filter_by(course_id=course.course_id).delete(synchronize_session=False)

    Lesson.query.filter_by(learning_trajectory_id=course.course_id).update(
        {Lesson.learning_trajectory_id: None}, synchronize_session=False
    )

    db.session.delete(course)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash('Не удалось удалить курс.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course_id))

    flash('Курс удалён.', 'success')
    return redirect(url_for('courses.student_courses', student_id=student_id))


@courses_bp.route('/courses/<int:course_id>/modules/<int:module_id>/delete', methods=['POST'])
@login_required
def module_delete(course_id: int, module_id: int):
    course = _guard_course(course_id)
    _require_course_manager(course)

    module = TrajectoryModule.query.filter_by(module_id=module_id, course_id=course.course_id).first_or_404()

    Lesson.query.filter_by(course_module_id=module.module_id).update(
        {Lesson.course_module_id: None}, synchronize_session=False
    )
    db.session.delete(module)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash('Не удалось удалить модуль.', 'danger')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    flash('Модуль удалён.', 'success')
    return redirect(url_for('courses.course_view', course_id=course.course_id))
