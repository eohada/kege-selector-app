from __future__ import annotations

import os
import json
from datetime import date, datetime, time, timedelta, timezone
from flask import render_template, redirect, url_for, flash, request, abort, jsonify, g, current_app, Response
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from sqlalchemy import or_, func, cast, String

from app import csrf
from app.courses import courses_bp
from app.courses.sequence import (
    course_sequence_state,
    lesson_is_deferred,
    record_course_sequence_decision,
    select_next_course_lesson,
    unresolved_preceding_lessons,
)
from app.lessons.lifecycle import LessonLifecycleError, transition_lesson_status
from app.courses.course_io import import_course_from_data, export_course_to_dict
from app.courses.forms import CourseForm, CourseModuleForm, CourseLessonForm
from app.models import (
    db, Student, Lesson, LessonTask, Tasks, LearningTrajectory, TrajectoryModule,
    User, LearningItem, LessonOutcome, ExamSkill, StudentSkill, LearningTrajectoryVersion,
    StudentDiagnosticCheckpoint, LearningError, LearningTrajectoryTemplate,
    LearningTrajectoryTemplateModule, LearningTrajectoryTemplateItem,
    LessonAttachment, lesson_skills
)
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
    if active_role in {'student', 'parent'}:
        return True
    if active_role:
        return False
    return current_user.is_student() or current_user.is_parent()


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
    if course.is_template or not course.student_id:
        if not _course_viewer_can_manage():
            abort(403)
        return course
    student = Student.query.get_or_404(course.student_id)
    if not _can_access_student(student):
        abort(403)
    return course


def _snapshot_course(course: LearningTrajectory, reason: str) -> None:
    """Фиксирует версию маршрута перед изменением без удаления истории."""
    if course.is_template or not course.student_id:
        return
    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).order_by(TrajectoryModule.order_index.asc()).all()
    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(Lesson.course_order_index.asc()).all()
    lesson_ids = [int(lesson.lesson_id) for lesson in lessons]
    task_links_by_lesson: dict[int, list[LessonTask]] = {lesson_id: [] for lesson_id in lesson_ids}
    if lesson_ids:
        for link in LessonTask.query.filter(LessonTask.lesson_id.in_(lesson_ids)).order_by(LessonTask.lesson_task_id.asc()).all():
            task_links_by_lesson.setdefault(int(link.lesson_id), []).append(link)
    # Номер версии берём из БД, а не только из кэша объекта курса: это
    # защищает историю от коллизий после параллельного редактирования.
    latest_version = db.session.query(func.max(LearningTrajectoryVersion.version_number)).filter_by(course_id=course.course_id).scalar()
    version_no = max(int(course.current_version or 1), int(latest_version or 0) + 1)
    source_version = int(course.current_version or 1)

    def lesson_pedagogy_snapshot(lesson: Lesson) -> dict | None:
        contract = (lesson.review_summaries or {}).get('_tutor_core_pedagogy')
        if isinstance(contract, dict):
            return contract
        try:
            import json
            legacy = json.loads(str(lesson.studio_scenario or ''))
            return legacy if isinstance(legacy, dict) and legacy.get('contract') == 'boostudy.lesson-pedagogy.v1' else None
        except (TypeError, ValueError):
            return None

    snapshot = {
        'snapshot_of_course_version': source_version,
        'title': course.title,
        'subject': course.subject,
        'learning_goal': course.learning_goal,
        'expected_result': course.expected_result,
        'modules': [{'id': m.module_id, 'title': m.title, 'order': m.order_index} for m in modules],
        'lessons': [
            {
                'id': l.lesson_id,
                'topic': l.topic,
                'status': l.status,
                'course_order_index': l.course_order_index,
                'duration': l.duration,
                'lesson_format': l.lesson_format,
                'content': l.content,
                'homework': l.homework,
                'module_id': l.course_module_id,
                'pedagogical_structure': lesson_pedagogy_snapshot(l),
                'sequence_decision': course_sequence_state(l.review_summaries),
                'teacher_change_history': (
                    list((l.review_summaries or {}).get('_teacher_manual_plan_changes') or [])
                    if isinstance((l.review_summaries or {}).get('_teacher_manual_plan_changes') or [], list)
                    else []
                ),
                'task_links': [
                    {
                        'task_id': int(link.task_id),
                        'assignment_type': link.assignment_type,
                        'status': link.status,
                        'notes': link.notes,
                    }
                    for link in task_links_by_lesson.get(int(l.lesson_id), [])
                ],
                'pedagogical_review_history': (
                    list((l.review_summaries or {}).get('_tutor_core_pedagogy_review_history') or [])
                    if isinstance((l.review_summaries or {}).get('_tutor_core_pedagogy_review_history') or [], list)
                    else []
                ),
            }
            for l in lessons
        ],
        'learning_items': [
            {
                'id': item.item_id,
                'skill_id': item.skill_id,
                'type': item.item_type,
                'title': item.title,
                'status': item.status,
                'order': item.order_index,
                'why_now': item.why_now,
            }
            for item in LearningItem.query.filter_by(course_id=course.course_id)
            .order_by(LearningItem.order_index.asc(), LearningItem.item_id.asc()).all()
        ],
    }

    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.course_adapter import _allowed_copy_ids, _course_evidence_semantics_by_lesson
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids

    if has_verified_safe_ai_lab_db() and int(course.course_id) in _allowed_copy_ids():
        if not _allowlisted_task_author_ids():
            raise ValueError('Нельзя изменить synthetic-копию: отсутствует allowlist авторов для снимка учебных доказательств.')
        evidence_semantics = _course_evidence_semantics_by_lesson(
            course_id=int(course.course_id), course_version=source_version,
        )
        expected_lesson_count = Lesson.query.filter_by(
            learning_trajectory_id=course.course_id, student_id=course.student_id,
        ).count()
        if len(evidence_semantics) != expected_lesson_count:
            raise ValueError('Нельзя изменить synthetic-копию: не удалось сохранить семантику каждого урока.')
        snapshot['evidence_semantics_by_lesson'] = evidence_semantics
        snapshot['evidence_semantics_coverage_complete'] = True

    db.session.add(LearningTrajectoryVersion(
        course_id=course.course_id,
        version_number=version_no,
        reason=reason,
        created_by_user_id=current_user.id,
        snapshot=snapshot,
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
@courses_bp.route('/courses/<int:course_id>/student/<int:student_id>')
@login_required
def course_view(course_id: int, student_id: int | None = None):
    course = _guard_course(course_id)
    is_master = bool(course.is_template or not course.student_id)
    can_manage = _course_viewer_can_manage()
    student = None
    if not is_master and course.student_id:
        student = Student.query.get(course.student_id)
    elif student_id:
        student = Student.query.get(student_id)

    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).order_by(TrajectoryModule.order_index.asc(), TrajectoryModule.module_id.asc()).all()
    module_ids = [m.module_id for m in modules]

    course_lesson_filter = Lesson.learning_trajectory_id == course.course_id
    if module_ids:
        course_lesson_filter = or_(course_lesson_filter, Lesson.course_module_id.in_(module_ids))

    if is_master:
        lessons = Lesson.query.filter(course_lesson_filter).order_by(
            Lesson.course_order_index.asc(), Lesson.lesson_id.asc()
        ).all()
    else:
        lessons = Lesson.query.filter(course_lesson_filter).order_by(
            Lesson.course_order_index.asc(), Lesson.lesson_date.asc().nullslast(), Lesson.lesson_id.asc()
        ).all()

    lessons_by_module = {}
    unassigned_lessons = []
    viewer_timezone = effective_timezone_name(current_user)
    for l in lessons:
        l.course_display_date = lesson_storage_to_local(l.lesson_date, viewer_timezone)
        l.sequence_state = course_sequence_state(l.review_summaries)
        if l.course_module_id and l.course_module_id in module_ids:
            lessons_by_module.setdefault(l.course_module_id, []).append(l)
        else:
            unassigned_lessons.append(l)

    course_lessons = [lesson for module_lessons in lessons_by_module.values() for lesson in module_lessons] + unassigned_lessons
    sequence_summary = {'active': [], 'waiting': [], 'deferred': []}
    for row in course_lessons:
        lesson_row = {
            'lesson_id': int(row.lesson_id),
            'order': int(row.course_order_index or 0),
            'topic': str(row.topic or 'Без названия'),
            'status': str(row.status or 'planned'),
            'reason': str(row.sequence_state.get('reason') or ''),
        }
        if row.status == 'in_progress':
            sequence_summary['active'].append(lesson_row)
        elif row.sequence_state.get('state') == 'deferred':
            sequence_summary['deferred'].append(lesson_row)
        elif row.status in {'planned', 'draft', 'scheduled'}:
            sequence_summary['waiting'].append(lesson_row)
    for rows in sequence_summary.values():
        rows.sort(key=lambda row: (row['order'], row['lesson_id']))
    next_lesson, next_issue, next_blockers = select_next_course_lesson(course_lessons) if not is_master else (None, None, [])
    sequence_summary['next'] = ({
        'lesson_id': int(next_lesson.lesson_id),
        'order': int(next_lesson.course_order_index or 0),
        'topic': str(next_lesson.topic or 'Без названия'),
    } if next_lesson else None)
    sequence_summary['next_issue'] = next_issue
    sequence_summary['next_blockers'] = [
        {'order': int(row.course_order_index or 0), 'topic': str(row.topic or 'Без названия')}
        for row in next_blockers
    ]
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
    else:
        course_skills = ExamSkill.query.filter_by(is_active=True).order_by(ExamSkill.task_number.asc(), ExamSkill.topic.asc()).all()
    course_skills_count = len(course_skills)

    skill_rows = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=student.student_id).all()} if student else {}
    route_items = LearningItem.query.filter_by(course_id=course.course_id).filter(
        LearningItem.status.in_(['planned', 'in_progress', 'overdue'])
    ).order_by(LearningItem.due_at.asc(), LearningItem.order_index.asc()).limit(8).all()
    forecast_target = course.target_score or 0
    forecast_value = course.current_forecast
    forecast_range = (course.forecast_low, course.forecast_high)
    if forecast_value is None and course_skills and student:
        weights = sum(float(skill.weight or 1) for skill in course_skills) or 1
        weighted_mastery = sum((skill_rows.get(skill.skill_id).mastery_percent if skill_rows.get(skill.skill_id) else 0) * float(skill.weight or 1) for skill in course_skills)
        mastery_value = round(weighted_mastery / weights)
        forecast_value = round(mastery_value * forecast_target / 100) if forecast_target else mastery_value
        forecast_range = (max(0, forecast_value - 5), min(100, forecast_value + 5))
    attention_counts = None
    if can_manage and student:
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

    latest_adaptive_outcome = None
    latest_adaptive_lesson = None
    course_lesson_ids = [lesson.lesson_id for lesson in course_lessons]
    student_homework_previews = {}
    if student and not can_manage and course_lesson_ids:
        from core.db_models import Assignment, AssignmentTask, Submission

        visible_homework_links = (
            db.session.query(LessonTask)
            .join(Assignment, Assignment.lesson_id == LessonTask.lesson_id)
            .join(AssignmentTask, (AssignmentTask.assignment_id == Assignment.assignment_id)
                  & (AssignmentTask.task_id == LessonTask.task_id))
            .join(Submission, Submission.assignment_id == Assignment.assignment_id)
            .filter(
                LessonTask.lesson_id.in_(course_lesson_ids),
                LessonTask.assignment_type == 'homework',
                LessonTask.is_visible_to_student.is_(True),
                Assignment.assignment_type == 'homework',
                Assignment.is_active.is_(True),
                Submission.student_id == int(student.student_id),
                Submission.status != 'REVOKED',
            )
            .distinct()
            .order_by(LessonTask.lesson_task_id.asc())
            .all()
        )
        task_ids = {int(link.task_id) for link in visible_homework_links}
        visible_tasks = {
            int(task.task_id): task
            for task in Tasks.query.filter(Tasks.task_id.in_(task_ids), Tasks.is_active.is_(True)).all()
        } if task_ids else {}
        for link in visible_homework_links:
            task = visible_tasks.get(int(link.task_id))
            if not task:
                continue
            student_homework_previews.setdefault(int(link.lesson_id), []).append({
                'task_number': int(task.task_number or task.task_id),
                'content_html': task.content_html or '',
            })
    if course_lesson_ids:
        latest_outcome = LessonOutcome.query.filter(
            LessonOutcome.lesson_id.in_(course_lesson_ids),
            LessonOutcome.adaptive_diff_summary.isnot(None)
        ).order_by(LessonOutcome.outcome_id.desc()).first()
        if latest_outcome and latest_outcome.adaptive_diff_summary:
            latest_adaptive_outcome = latest_outcome
            latest_adaptive_lesson = next(
                (lesson for lesson in course_lessons if lesson.lesson_id == latest_outcome.lesson_id),
                None,
            )

    all_students = Student.query.order_by(Student.name.asc()).all() if can_manage else []

    return render_template(
        'course_view.html',
        student=student,
        course=course,
        is_master=is_master,
        modules=modules,
        lessons_by_module=lessons_by_module,
        unassigned_lessons=unassigned_lessons,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons,
        planned_lessons=planned_lessons,
        running_lessons=running_lessons,
        sequence_summary=sequence_summary,
        completed_items=completed_items,
        total_items=total_items,
        mastery_percent=mastery_percent,
        course_skills=course_skills,
        course_skills_count=course_skills_count,
        skill_rows=skill_rows,
        route_items=route_items,
        forecast_value=forecast_value,
        forecast_range=forecast_range,
        attention_counts=attention_counts,
        milestones=milestones,
        latest_adaptive_outcome=latest_adaptive_outcome,
        latest_adaptive_lesson=latest_adaptive_lesson,
        student_homework_previews=student_homework_previews,
        viewer_is_student=_course_viewer_is_read_only(),
        can_manage=can_manage,
        all_students=all_students,
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
    } if course.student_id else {}
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
    skills = skills_query.order_by(ExamSkill.task_number.asc().nullslast(), ExamSkill.topic.asc(), ExamSkill.skill_id.asc()).all()

    if request.method == 'POST':
        title = str(request.form.get('title') or '').strip()
        topic = str(request.form.get('topic') or '').strip()
        subtopic = str(request.form.get('subtopic') or '').strip()
        task_number_raw = str(request.form.get('task_number') or '').strip()
        topic_code = str(request.form.get('topic_code') or '').strip().upper()[:100]
        prerequisite_raw = str(request.form.get('prerequisite_skill_id') or '').strip()
        prerequisite_ids = [int(pid) for pid in request.form.getlist('prerequisite_ids') if pid.isdigit()]
        if not prerequisite_ids and prerequisite_raw and prerequisite_raw.isdigit():
            prerequisite_ids = [int(prerequisite_raw)]

        if not title:
            flash('Укажите название навыка.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))
        if len(title) > 300 or len(topic) > 200 or len(subtopic) > 200:
            flash('Название или раздел слишком длинные.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))
        try:
            task_number = int(task_number_raw) if task_number_raw else None
            if task_number is not None and (task_number < 1 or task_number > 27):
                raise ValueError
        except ValueError:
            flash('Номер задания должен быть числом от 1 до 27.', 'error')
            return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))

        if not topic_code:
            # Fallback auto-code
            topic_code = f"SKILL-T{task_number or 0}-{title[:10].upper().replace(' ', '_')}"

        prerequisite_skill_id = prerequisite_ids[0] if prerequisite_ids else None

        skill = ExamSkill(
            exam_course_id=course.exam_course_id,
            task_number=task_number,
            title=title,
            subject=(course.subject or '').strip()[:120] or None,
            topic=topic or None,
            subtopic=subtopic or None,
            topic_code=topic_code,
            prerequisite_skill_id=prerequisite_skill_id,
            prerequisite_ids=prerequisite_ids or None,
            is_active=True,
        )
        db.session.add(skill)
        db.session.commit()
        flash(f'Навык «{skill.title}» ({skill.topic_code}) добавлен в банк программы.', 'success')
        return redirect(url_for('courses.course_skills_manage', course_id=course.course_id))

    return render_template(
        'course_skills_manage.html',
        course=course,
        skills=skills,
        exam_tasks=list(range(1, 28)),
    )


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
    rows = StudentSkill.query.filter(StudentSkill.student_id == course.student_id, StudentSkill.skill_id.in_(skills)).all() if (skills and course.student_id) else []
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
    if course.is_template or not course.student_id:
        return jsonify({'success': False, 'error': 'Мастер генерации маршрута доступен только для индивидуального курса ученика'}), 400
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
    if course.is_template or not course.student_id:
        return jsonify({'success': False, 'error': 'Доступно только для индивидуального курса ученика'}), 400
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
    """Apply a teacher's manual plan edit from the legacy attention view.

    This legacy action is separate from evidence-backed Tutor Core decisions.
    Keep it teacher-confirmed and versioned so it cannot silently overwrite the
    individual plan or be mistaken for a Tutor Core recommendation.
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
            _snapshot_course(course, 'manual_attention_plan_edit')
            max_order = db.session.query(db.func.max(LearningItem.order_index)).filter_by(course_id=course.course_id).scalar() or 0
            item = LearningItem(course_id=course.course_id, skill_id=skill.skill_id, item_type=desired_type,
                                title=skill.title, status='planned', order_index=int(max_order) + 10,
                                why_now='Добавлено преподавателем вручную из центра внимания')
            db.session.add(item)
            db.session.commit()
            created = True
        else:
            created = False
        return respond({'success': True, 'action': action, 'created': created, 'item': {
            'id': item.item_id, 'type': item.item_type, 'status': item.status, 'skill_id': item.skill_id,
        }})
    changed = 0
    mutable_items = [item for item in existing if item.status in {'planned', 'in_progress'}]
    add_manual_ignore = not existing and action == 'ignore'
    if mutable_items or add_manual_ignore:
        _snapshot_course(course, 'manual_attention_plan_edit')
    for item in mutable_items:
        item.status = 'skipped'
        item.why_now = ('Пропущено преподавателем вручную из центра внимания' if action == 'ignore'
                        else 'Элемент сокращён преподавателем вручную из центра внимания')
        changed += 1
    if add_manual_ignore:
        item = LearningItem(course_id=course.course_id, skill_id=skill.skill_id, item_type='review',
                            title=skill.title, status='skipped', why_now='Пропущено преподавателем вручную из центра внимания')
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
    mastery = {row.skill_id: row for row in StudentSkill.query.filter_by(student_id=course.student_id).all()} if course.student_id else {}
    return render_template(
        'course_plan_wizard.html',
        course=course,
        skills=skills,
        mastery=mastery,
        skills_manage_url=url_for('courses.course_skills_manage', course_id=course.course_id),
    )


@courses_bp.route('/courses', methods=['GET'])
@courses_bp.route('/courses/templates', methods=['GET', 'POST'])
@login_required
def courses_catalog():
    """Каталог базовых программ (Мастер-курсов) и курсов учеников."""
    if not _course_viewer_can_manage():
        if getattr(current_user, 'is_student', None) and current_user.is_student():
            st = Student.query.filter_by(user_id=current_user.id).first()
            if st:
                return redirect(url_for('courses.student_courses', student_id=st.student_id))
        abort(403)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Название базовой программы обязательно.', 'error')
            return redirect(url_for('courses.courses_catalog', tab='templates'))

        target_score_raw = request.form.get('target_score')
        target_score = int(target_score_raw) if target_score_raw and target_score_raw.isdigit() else None
        duration = int(request.form.get('default_lesson_duration') or 60)

        master_course = LearningTrajectory(
            is_template=True,
            student_id=None,
            created_by_user_id=current_user.id,
            title=title,
            subject=(request.form.get('subject') or '').strip() or 'Информатика',
            description=(request.form.get('description') or '').strip() or None,
            learning_goal=(request.form.get('learning_goal') or '').strip() or None,
            expected_result=(request.form.get('expected_result') or '').strip() or None,
            target_score=target_score,
            default_lesson_duration=duration,
            status='active',
        )
        db.session.add(master_course)
        db.session.commit()
        flash(f'Базовый курс «{master_course.title}» успешно создан.', 'success')
        return redirect(url_for('courses.course_view', course_id=master_course.course_id))

    active_tab = request.args.get('tab', 'templates')
    template_courses = LearningTrajectory.query.filter_by(is_template=True).order_by(LearningTrajectory.updated_at.desc()).all()
    student_courses = LearningTrajectory.query.filter(
        LearningTrajectory.is_template == False,
        LearningTrajectory.student_id.isnot(None)
    ).order_by(LearningTrajectory.updated_at.desc()).all()
    if not (current_user.is_creator() or current_user.is_admin()):
        student_courses = [row for row in student_courses
                           if row.student_id and _can_access_student(Student.query.get(row.student_id))]
    all_students = [student for student in Student.query.order_by(Student.name.asc()).all()
                    if _can_access_student(student)]

    return render_template(
        'sandbox/courses_catalog.html',
        template_courses=template_courses,
        student_courses=student_courses,
        all_students=all_students,
        active_tab=active_tab,
        can_manage=True,
    )


@courses_bp.route('/course-templates', methods=['GET', 'POST'])
@login_required
def course_templates():
    """Каталог шаблонов индивидуальных программ (legacy)."""
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



@courses_bp.route('/courses/<int:course_id>/duplicate', methods=['POST'])
@login_required
def course_duplicate(course_id: int):
    """Дублирует базовый шаблон курса со всеми модулями, уроками, навыками и вложениями."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)

    new_course = LearningTrajectory(
        is_template=True,
        student_id=None,
        parent_course_id=course.course_id,
        created_by_user_id=current_user.id,
        title=f"{course.title} (Копия)",
        subject=course.subject,
        description=course.description,
        learning_goal=course.learning_goal,
        expected_result=course.expected_result,
        exam_course_id=course.exam_course_id,
        target_score=course.target_score,
        default_lesson_duration=course.default_lesson_duration,
        status='active',
    )
    db.session.add(new_course)
    db.session.flush()

    module_map = {}
    for mod in course.modules:
        new_mod = TrajectoryModule(
            course_id=new_course.course_id,
            title=mod.title,
            description=mod.description,
            learning_result=mod.learning_result,
            order_index=mod.order_index,
            is_control_exam=mod.is_control_exam,
        )
        db.session.add(new_mod)
        db.session.flush()
        module_map[mod.module_id] = new_mod.module_id

    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(Lesson.course_order_index.asc()).all()
    for l in lessons:
        new_lesson = Lesson(
            student_id=None,
            learning_trajectory_id=new_course.course_id,
            course_module_id=module_map.get(l.course_module_id),
            exam_course_id=l.exam_course_id,
            lesson_type=l.lesson_type,
            lesson_format=l.lesson_format,
            duration=l.duration,
            course_order_index=l.course_order_index,
            status='planned',
            topic=l.topic,
            notes=l.notes,
            content=l.content,
            studio_scenario=l.studio_scenario,
            homework=l.homework,
            review_summaries=l.review_summaries,
        )
        new_lesson.skills = list(l.skills)
        db.session.add(new_lesson)
        db.session.flush()

        for att in (l.attachments or []):
            new_att = LessonAttachment(
                lesson_id=new_lesson.lesson_id,
                file_name=att.file_name,
                file_path=att.file_path,
                file_size=att.file_size,
                target=att.target,
            )
            db.session.add(new_att)

        _ensure_lesson_learning_item(new_course, new_lesson)

    db.session.commit()
    flash(f'Копия шаблона «{new_course.title}» успешно создана.', 'success')
    return redirect(url_for('courses.course_view', course_id=new_course.course_id))


@courses_bp.route('/courses/<int:course_id>/assign-to-student', methods=['POST'])
@login_required
def course_assign_to_student(course_id: int):
    """Форк мастер-курса в индивидуальный курс ученика с авто-генерацией дат уроков по слотам."""
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)
    if not course.is_template or course.student_id is not None:
        return jsonify({'success': False, 'error': 'Назначить ученику можно только базовый курс-шаблон.'}), 400

    student_id = request.form.get('student_id', type=int)
    if not student_id:
        flash('Выберите ученика.', 'error')
        return redirect(request.referrer or url_for('courses.courses_catalog'))

    student = _guard_student(student_id)
    existing_copy = LearningTrajectory.query.filter_by(
        student_id=student.student_id, parent_course_id=course.course_id,
        is_template=False, status='active',
    ).first()
    if existing_copy:
        return jsonify({'success': False, 'error': 'Этот базовый курс уже назначен ученику.'}), 409

    without_schedule = request.form.get('without_schedule') == '1'
    if without_schedule:
        start_dt = None
        slots = []
    else:
        start_date_str = request.form.get('start_date')
        start_dt = None
        if start_date_str:
            try:
                if 'T' in start_date_str:
                    start_dt = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
                else:
                    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
            except Exception:
                start_dt = None

        if not start_dt:
            start_dt = datetime.now()

        slot_weekdays = request.form.getlist('slot_weekday')
        slot_times = request.form.getlist('slot_time')

        slots = []
        if slot_weekdays:
            for idx, sw in enumerate(slot_weekdays):
                try:
                    w_int = int(sw)
                    t_str = slot_times[idx] if idx < len(slot_times) else '18:00'
                    t_hour, t_minute = map(int, t_str.split(':'))
                    slots.append({'weekday': w_int, 'hour': t_hour, 'minute': t_minute})
                except Exception:
                    pass

        if not slots:
            slots.append({'weekday': start_dt.weekday(), 'hour': start_dt.hour or 18, 'minute': start_dt.minute or 0})

    slots.sort(key=lambda s: (s['weekday'], s['hour'], s['minute']))

    student_course = LearningTrajectory(
        is_template=False,
        student_id=student.student_id,
        parent_course_id=course.course_id,
        created_by_user_id=current_user.id,
        title=course.title,
        subject=course.subject,
        description=course.description,
        learning_goal=course.learning_goal,
        expected_result=course.expected_result,
        exam_course_id=course.exam_course_id,
        target_score=course.target_score,
        default_lesson_duration=course.default_lesson_duration,
        status='active',
    )
    db.session.add(student_course)
    db.session.flush()

    module_map = {}
    for mod in course.modules:
        new_mod = TrajectoryModule(
            course_id=student_course.course_id,
            title=mod.title,
            description=mod.description,
            learning_result=mod.learning_result,
            order_index=mod.order_index,
            is_control_exam=mod.is_control_exam,
        )
        db.session.add(new_mod)
        db.session.flush()
        module_map[mod.module_id] = new_mod.module_id

    lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).order_by(
        Lesson.course_order_index.asc(), Lesson.lesson_id.asc()
    ).all()

    tz_name = effective_timezone_name(current_user)

    def get_slot_dates(num_lessons, from_dt, active_slots):
        generated = []
        d = from_dt.date()
        while len(generated) < num_lessons:
            day_of_week = d.weekday()
            day_slots = [s for s in active_slots if s['weekday'] == day_of_week]
            for s in day_slots:
                slot_dt = datetime.combine(d, time(s['hour'], s['minute']))
                if slot_dt >= from_dt:
                    generated.append(slot_dt)
                    if len(generated) >= num_lessons:
                        break
            d += timedelta(days=1)
        return generated

    scheduled_dates = [None] * len(lessons) if without_schedule else get_slot_dates(len(lessons), start_dt, slots)

    for idx, l in enumerate(lessons):
        assigned_dt = scheduled_dates[idx] if idx < len(scheduled_dates) else None
        storage_dt = None
        if assigned_dt:
            storage_dt = parse_local_lesson_datetime(
                assigned_dt.strftime('%Y-%m-%d'), assigned_dt.strftime('%H:%M'), tz_name
            )

        new_lesson = Lesson(
            student_id=student.student_id,
            learning_trajectory_id=student_course.course_id,
            course_module_id=module_map.get(l.course_module_id),
            exam_course_id=l.exam_course_id,
            lesson_type=l.lesson_type,
            lesson_format=l.lesson_format,
            lesson_date=storage_dt,
            duration=l.duration,
            course_order_index=l.course_order_index,
            status='planned',
            topic=l.topic,
            notes=l.notes,
            content=l.content,
            studio_scenario=l.studio_scenario,
            homework=l.homework,
            homework_status='assigned_not_done' if l.homework else 'not_assigned',
            review_summaries=l.review_summaries,
        )
        new_lesson.skills = list(l.skills)
        db.session.add(new_lesson)
        db.session.flush()

        for att in (l.attachments or []):
            new_att = LessonAttachment(
                lesson_id=new_lesson.lesson_id,
                file_name=att.file_name,
                file_path=att.file_path,
                file_size=att.file_size,
                target=att.target,
            )
            db.session.add(new_att)

        for source_task in LessonTask.query.filter_by(lesson_id=l.lesson_id).order_by(LessonTask.lesson_task_id.asc()).all():
            db.session.add(LessonTask(
                lesson_id=new_lesson.lesson_id,
                task_id=source_task.task_id,
                date_assigned=storage_dt or source_task.date_assigned,
                notes=source_task.notes,
                assignment_type=source_task.assignment_type,
                is_error_review=bool(source_task.is_error_review),
                is_visible_to_student=bool(source_task.is_visible_to_student),
                is_answer_visible_to_student=bool(source_task.is_answer_visible_to_student),
                status='pending',
                difficulty_level=source_task.difficulty_level,
                max_attempts=source_task.max_attempts,
            ))

        _ensure_lesson_learning_item(student_course, new_lesson)

    db.session.commit()
    if without_schedule:
        flash(f'Индивидуальный план назначен ученику {student.name} без дат занятий. Создано {len(lessons)} уроков.', 'success')
    else:
        flash(f'Курс назначен ученику {student.name}. Создано {len(lessons)} уроков по расписанию.', 'success')
    return redirect(url_for('courses.course_view', course_id=student_course.course_id, student_id=student.student_id))


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
    if not form.is_submitted():
        max_order = db.session.query(func.coalesce(func.max(TrajectoryModule.order_index), 0)).filter_by(course_id=course.course_id).scalar() or 0
        form.order_index.data = max_order + 10

    if form.validate_on_submit():
        module = TrajectoryModule(
            course_id=course.course_id,
            title=form.title.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            learning_result=form.learning_result.data.strip() if form.learning_result.data else None,
            order_index=form.order_index.data or 0,
            is_control_exam=bool(form.is_control_exam.data),
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
        module.is_control_exam = bool(form.is_control_exam.data)
        db.session.commit()
        flash('Модуль обновлён.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'module-{module.module_id}'))
    return render_template('course_module_form.html', form=form, student=student, course=course, module=module, title='Редактировать модуль')


def _require_course_manager(course: LearningTrajectory) -> Student | None:
    if not _course_viewer_can_manage():
        abort(403)
    if course.is_template or not course.student_id:
        return None
    return Student.query.get_or_404(course.student_id)


def _adaptive_v2_course_editor_requested() -> bool:
    return request.values.get('adaptive_v2') == '1'


def _require_adaptive_v2_course_editor(course: LearningTrajectory) -> bool:
    if not _adaptive_v2_course_editor_requested():
        return False
    from app.ai_lab.course_adapter import _allowed_copy_ids
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_user_ids
    from app.ai_lab.provider import is_local_ai_lab_enabled

    student = Student.query.filter_by(student_id=int(course.student_id or 0)).first()
    learner = User.query.filter_by(id=int(student.user_id or 0)).first() if student and student.user_id else None
    allowed = bool(
        has_verified_safe_ai_lab_db()
        and is_local_ai_lab_enabled()
        and not course.is_template
        and course.parent_course_id
        and int(course.course_id) in _allowed_copy_ids()
        and int(current_user.id) in _allowlisted_actor_ids()
        and learner and learner.role == 'student'
        and int(learner.id) in _allowlisted_user_ids()
    )
    if not allowed:
        abort(404)
    return True


def _render_course_lesson_form(adaptive_editor: bool, **context):
    template = 'sandbox/adaptive_course_lesson_form.html' if adaptive_editor else 'course_lesson_form.html'
    return render_template(template, adaptive_editor=adaptive_editor, **context)


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
        scenario_text = lesson.studio_scenario or ''
        if scenario_text:
            try:
                import json
                legacy_contract = json.loads(scenario_text)
                if isinstance(legacy_contract, dict) and legacy_contract.get('contract') == 'boostudy.lesson-pedagogy.v1':
                    scenario_text = '\n'.join(
                        f"{segment.get('minutes') or 0} мин — {str(segment.get('title') or '').strip()}"
                        for segment in legacy_contract.get('segments', [])
                        if isinstance(segment, dict) and str(segment.get('title') or '').strip()
                    )
            except (TypeError, ValueError):
                pass
        form.studio_scenario.data = scenario_text or '\n'.join(
            str(item.get('title') or '').strip()
            for item in ((lesson.review_summaries or {}).get('_studio') or {}).get('agenda', [])
            if isinstance(item, dict) and str(item.get('title') or '').strip()
        )
        form.lesson_format.data = lesson.lesson_format or 'Теория + Практика'
        form.teacher_note.data = lesson.notes or ''
    return form


def _course_task_binding(task: Tasks, skill: ExamSkill, criterion_id: str, course: LearningTrajectory, lesson: Lesson) -> tuple[dict | None, str | None]:
    raw_spec = task.answer_spec
    if isinstance(raw_spec, dict):
        spec = raw_spec
    else:
        try:
            spec = json.loads(str(raw_spec or '{}'))
        except (TypeError, ValueError):
            return None, 'Не удалось прочитать способ проверки задания.'
    if not isinstance(spec, dict):
        return None, 'У задания нет структурированной спецификации проверки.'

    binding = spec.get('synthetic_course_skill_binding') or spec.get('course_skill_binding')
    if not isinstance(binding, dict):
        return None, 'Нет подтверждённой привязки задания к навыку и критерию.'
    if not str(binding.get('contract') or '').strip():
        return None, 'У привязки задания нет версии контракта происхождения.'
    valid_skill_ids = {f'exam-skill:{int(skill.skill_id)}', str(int(skill.skill_id))}
    if str(binding.get('skill_id') or '') not in valid_skill_ids:
        return None, 'Указан другой навык.'
    if skill.topic_code and str(binding.get('topic_code') or '') != str(skill.topic_code):
        return None, 'Код темы задания не совпадает с навыком урока.'
    from app.ai_lab.tutor_core import _structured_mastery_criteria
    valid_criteria = {str(item.get('key') or '') for item in _structured_mastery_criteria(skill) if item.get('key')}
    if criterion_id not in valid_criteria or str(binding.get('criterion_id') or '') != criterion_id:
        return None, 'Задание связано с другим критерием.'
    if not str(binding.get('task_fingerprint') or '').strip():
        return None, 'Нет отпечатка исходного задания.'
    if getattr(task, 'task_id', None) is not None:
        from app.ai_lab.platform_homework import _task_fingerprint
        if str(binding.get('task_fingerprint')) != _task_fingerprint(task):
            return None, 'Содержимое задания изменилось после фиксации происхождения; требуется повторная проверка материала.'

    grading_mode = str(spec.get('grading_mode') or '').casefold()
    if grading_mode not in {'exact', 'auto'} or task.answer is None:
        return None, 'Для задания не подтверждён поддерживаемый автоматический проверяющий механизм.'

    source_course_id = binding.get('source_course_id', binding.get('course_id'))
    source_version = binding.get('source_course_version', binding.get('course_version'))
    source_lesson_id = binding.get('source_lesson_id', binding.get('lesson_id'))
    if not all(str(value or '').isdigit() for value in (source_course_id, source_version, source_lesson_id)):
        return None, 'Не сохранены исходные курс, версия и урок задания.'
    source_course_id, source_version, source_lesson_id = map(int, (source_course_id, source_version, source_lesson_id))
    if getattr(task, 'task_id', None) is not None:
        source_course = LearningTrajectory.query.filter_by(course_id=source_course_id).first()
        source_lesson = Lesson.query.filter_by(lesson_id=source_lesson_id).first()
        source_link = LessonTask.query.filter_by(lesson_id=source_lesson_id, task_id=task.task_id).first()
        if (not source_course or not source_lesson or not source_link
                or int(source_lesson.learning_trajectory_id or 0) != source_course_id
                or source_version > int(source_course.current_version or 1)):
            return None, 'Связь с исходным курсом, версией или уроком не подтверждена.'

    same_context = (
        source_course_id == int(course.course_id)
        and source_version == int(course.current_version or 1)
        and source_lesson_id == int(lesson.lesson_id)
    )
    return {
        'binding': binding,
        'grading_mode': grading_mode,
        'source_course_id': source_course_id,
        'source_course_version': source_version,
        'source_lesson_id': source_lesson_id,
        'same_context': same_context,
        'provenance_verified': True,
        'pedagogical_status': str(binding.get('pedagogical_status') or getattr(task, 'prototype_status', None) or 'unknown'),
    }, None


def _course_task_independent_allowed(binding: dict, usage: dict) -> bool:
    # Cross-course material may be attached for teaching, but a task from a
    # different course/version is not a fresh diagnostic for this lesson.
    return bool(binding.get('same_context') and binding.get('provenance_verified') and not usage.get('previously_used'))


def _course_task_bank_context(course: LearningTrajectory, lesson: Lesson | None, selected_skills: list[ExamSkill]) -> dict:
    from html import unescape
    import re
    from app.ai_lab.tutor_core import _exercise_usage, _structured_mastery_criteria

    result = {'bank_task_candidates': [], 'bank_task_notice': None, 'bank_task_excluded_count': 0}
    if not lesson or not lesson.lesson_id:
        result['bank_task_notice'] = 'Сначала сохраните урок. После этого можно выбрать задание из банка по навыку и критерию.'
        return result
    if len(selected_skills) != 1:
        result['bank_task_notice'] = 'Для точного подбора выберите ровно один активный навык урока.'
        return result

    skill = selected_skills[0]
    criterion_rows = [item for item in _structured_mastery_criteria(skill) if item.get('key')]
    criteria = [str(item.get('key') or '') for item in criterion_rows]
    criterion_labels = {str(item.get('key')): str(item.get('label') or item.get('title') or item.get('key')) for item in criterion_rows}
    if not criteria or not skill.topic_code:
        result['bank_task_notice'] = 'У навыка нет проверяемых критериев или topic_code; точная привязка задания сейчас невозможна.'
        return result

    topic_query = cast(Tasks.answer_spec, String).contains(str(skill.topic_code))
    skill_query = cast(Tasks.answer_spec, String).contains(f'exam-skill:{int(skill.skill_id)}')
    raw_tasks = (Tasks.query.filter(Tasks.is_active.is_(True))
                 .filter(or_(topic_query, skill_query))
                 .order_by(Tasks.task_id.desc()).limit(100).all())
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    safe_database = has_verified_safe_ai_lab_db()
    allowed_authors: set[int] = set()
    if safe_database:
        from app.ai_lab.platform_homework import _allowlisted_task_author_ids
        allowed_authors = {int(value) for value in (_allowlisted_task_author_ids() or [])}

    plain = {}
    for task in raw_tasks:
        value = re.sub(r'<h[1-6]\b[^>]*>.*?</h[1-6]>', ' ', str(task.content_html or ''), flags=re.I | re.S)
        value = unescape(re.sub(r'<[^>]+>', ' ', value))
        plain[int(task.task_id)] = re.sub(r'\s+', ' ', value).strip()[:220]

    candidates = []
    excluded = 0
    for task in raw_tasks:
        available_bindings = []
        for criterion_id in criteria:
            checked, error = _course_task_binding(task, skill, criterion_id, course, lesson)
            if checked:
                available_bindings.append((criterion_id, checked))
        if not available_bindings:
            excluded += 1
            continue
        if safe_database and int(task.created_by_id or 0) not in allowed_authors:
            excluded += 1
            continue
        if not safe_database and str(task.prototype_status or '').casefold() not in {'approved', 'expert_approved', 'reviewed'}:
            excluded += 1
            continue

        usage = _exercise_usage(int(task.task_id), int(lesson.student_id or 0))
        previously_used = bool(usage.get('previously_used'))
        criterion_id, checked = available_bindings[0]
        candidates.append({
            'task_id': int(task.task_id),
            'criterion_id': criterion_id,
            'criterion_label': criterion_labels.get(criterion_id, criterion_id),
            'preview': plain[int(task.task_id)],
            'grading_mode': checked['grading_mode'],
            'source_course_id': checked['source_course_id'],
            'source_course_version': checked['source_course_version'],
            'source_lesson_id': checked['source_lesson_id'],
            'same_context': checked['same_context'],
            'pedagogical_status': checked['pedagogical_status'],
            'difficulty': (task.difficulty_label if task.difficulty_level is not None else 'не размечена'),
            'task_fingerprint': str(checked['binding'].get('task_fingerprint') or ''),
            'previously_used': previously_used,
            'usage_status': str(usage.get('status') or 'unknown'),
            'independent_allowed': _course_task_independent_allowed(checked, usage),
            'purpose_label': (
                'Доступно для проверки в этом уроке'
                if checked['same_context'] and not previously_used
                else 'Только разбор/повторение: независимость не подтверждена'
            ),
        })

    result['bank_task_candidates'] = candidates[:20]
    result['bank_task_excluded_count'] = excluded
    if not candidates:
        result['bank_task_notice'] = 'Для этого навыка нет заданий с одновременно подтверждённой привязкой к критерию, исходной версией и поддерживаемым проверяющим механизмом.'
    elif not any(item['independent_allowed'] for item in candidates):
        result['bank_task_notice'] = 'Подходящие задания найдены, но независимость в этом уроке не подтверждена. Их можно включить в классную или домашнюю работу после проверки преподавателем; повторный материал не считается новой диагностикой.'
    return result


def _course_lesson_pedagogy_editor_context(
    course: LearningTrajectory,
    lesson: Lesson | None,
    selected_skill_ids: list[int],
    initial_override: dict | None = None,
) -> dict:
    from app.ai_lab.tutor_core import _exercise_usage, _structured_mastery_criteria
    from core.db_models import LessonTask

    selected_skills = (ExamSkill.query.filter(ExamSkill.skill_id.in_(selected_skill_ids)).all()
                       if selected_skill_ids else [])
    criteria = []
    if len(selected_skills) == 1:
        criteria = [
            {
                'id': str(item.get('key') or ''),
                'label': str(item.get('label') or item.get('title') or item.get('key') or ''),
                'description': str(item.get('description') or item.get('evidence') or ''),
            }
            for item in _structured_mastery_criteria(selected_skills[0])
            if str(item.get('key') or '').strip()
        ]

    summaries = dict(getattr(lesson, 'review_summaries', None) or {}) if lesson else {}
    contract = initial_override if isinstance(initial_override, dict) else summaries.get('_tutor_core_pedagogy')
    if not isinstance(contract, dict) and lesson:
        try:
            import json
            legacy = json.loads(str(lesson.studio_scenario or ''))
            contract = legacy if isinstance(legacy, dict) and legacy.get('contract') == 'boostudy.lesson-pedagogy.v1' else None
        except (TypeError, ValueError):
            contract = None

    tasks = []
    task_by_id = {}
    exercise_criteria_by_task = {}
    lesson_task_by_id = {}

    def task_workflow_state(link):
        if not link:
            return 'Материал найден в каталоге · ещё не добавлен в урок'
        status = str(link.status or 'pending').casefold()
        if status == 'graded':
            return 'Работа проверена'
        if status == 'returned':
            return 'Отправлено · ожидает доработки'
        if status == 'submitted':
            return 'Ответ отправлен · ожидает проверки'
        if status == 'assigned':
            return 'Назначено · условие доступно ученику'
        if link.is_visible_to_student:
            return 'Показ разрешён, но без Assignment условие скрыто'
        return 'Подготовлено · условие скрыто от ученика'

    if isinstance(contract, dict):
        for exercise in contract.get('exercises', []):
            if not isinstance(exercise, dict) or exercise.get('source_type') != 'platform_task':
                continue
            try:
                task_id = int(exercise.get('task_id') or 0)
            except (TypeError, ValueError):
                continue
            if task_id:
                exercise_criteria_by_task.setdefault(task_id, set()).update(
                    str(value) for value in exercise.get('criterion_ids', []) if str(value).strip()
                )
    if lesson and lesson.lesson_id:
        lesson_task_by_id = {
            int(link.task_id): link
            for link in LessonTask.query.filter_by(lesson_id=lesson.lesson_id).all()
        }
        for link in lesson_task_by_id.values():
            task_id = int(link.task_id)
            if task_id in task_by_id:
                continue
            usage = _exercise_usage(int(link.task_id), int(lesson.student_id or 0))
            task_by_id[task_id] = {
                'id': task_id,
                'previously_used': bool(usage.get('previously_used')),
                'usage_status': str(usage.get('status') or 'unknown'),
                'criterion_ids': sorted(exercise_criteria_by_task.get(task_id, set())),
                'workflow_state': task_workflow_state(link),
            }
            tasks.append(task_by_id[task_id])

    bank_context = _course_task_bank_context(course, lesson, selected_skills)
    for candidate in bank_context['bank_task_candidates']:
        task_id = int(candidate['task_id'])
        task = task_by_id.get(task_id)
        if task is None:
            task = {
                'id': task_id,
                'previously_used': bool(candidate['previously_used']),
                'usage_status': str(candidate['usage_status']),
                'criterion_ids': [],
                'workflow_state': task_workflow_state(lesson_task_by_id.get(task_id)),
            }
            task_by_id[task_id] = task
            tasks.append(task)
        task['criterion_ids'] = sorted(set(task['criterion_ids']) | {str(candidate['criterion_id'])})
        candidate['workflow_state'] = task['workflow_state']
    return {
        'pedagogy_criteria': criteria,
        'pedagogy_tasks': tasks,
        'pedagogy_initial': contract if isinstance(contract, dict) else {},
        'pedagogy_skill_ready': len(selected_skills) == 1 and bool(criteria),
        'pedagogy_teacher_confirmation_enabled': _synthetic_course_review_enabled(course),
        'pedagogy_teacher_confirmation_checked': _pedagogy_review_is_current(
            lesson, contract if isinstance(contract, dict) else {}, selected_skills[0] if len(selected_skills) == 1 else None,
        ),
        **bank_context,
    }


def _adaptive_manual_editor_context(
    course: LearningTrajectory,
    lesson: Lesson | None,
    selected_skill_ids: list[int],
    available_skills: list[ExamSkill],
) -> dict:
    from app.ai_lab.tutor_core import _structured_mastery_criteria

    context = _course_lesson_pedagogy_editor_context(course, lesson, selected_skill_ids)
    selected_skills = [skill for skill in available_skills if int(skill.skill_id) in set(selected_skill_ids)]
    context['manual_skill_options'] = [{
        'id': int(skill.skill_id),
        'label': str(skill.topic or getattr(skill, 'title', None) or f'Навык #{skill.skill_id}'),
        'topic_code': str(skill.topic_code or ''),
        'criteria': _structured_mastery_criteria(skill),
    } for skill in available_skills]
    context['manual_selected_skill_id'] = int(selected_skills[0].skill_id) if len(selected_skills) == 1 else None
    context['manual_selected_criteria'] = _structured_mastery_criteria(selected_skills[0]) if len(selected_skills) == 1 else []

    if lesson and lesson.lesson_id:
        return context
    if len(selected_skills) != 1:
        context['bank_task_notice'] = 'Выберите один активный навык, чтобы найти упражнения с проверенной привязкой.'
        return context

    skill = selected_skills[0]
    source_lessons = (Lesson.query.join(Lesson.skills)
                      .filter(Lesson.learning_trajectory_id == int(course.course_id),
                              ExamSkill.skill_id == int(skill.skill_id))
                      .order_by(Lesson.course_order_index.desc(), Lesson.lesson_id.desc()).all())
    for source_lesson in source_lessons:
        bank_context = _course_task_bank_context(course, source_lesson, [skill])
        if not bank_context.get('bank_task_candidates'):
            continue
        candidates = []
        for candidate in bank_context['bank_task_candidates']:
            candidates.append({
                **candidate,
                'independent_allowed': False,
                'purpose_label': 'Материал из другого/предыдущего занятия; повторное решение не считается независимой проверкой.',
            })
        context['bank_task_candidates'] = candidates
        context['bank_task_notice'] = (
            'Для нового занятия доступны упражнения с подтверждённым навыком и проверяющим способом. '
            'Они перенесены из существующей истории и будут отмечены как повторный разбор, а не новая независимая диагностика.'
        )
        return context
    context['bank_task_notice'] = 'Для выбранного навыка нет упражнения с одновременно проверенной привязкой и способом проверки.'
    return context


def _synthetic_course_review_enabled(course: LearningTrajectory | None) -> bool:
    """Expose teacher mapping confirmation only for allowlisted local synthetic copies."""
    if not course or not course.student_id:
        return False
    from app.ai_lab.course_adapter import _allowed_copy_ids
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_user_ids
    from app.ai_lab.provider import is_local_ai_lab_enabled

    actor_id = int(getattr(current_user, 'id', 0) or 0)
    student = Student.query.filter_by(student_id=int(course.student_id)).first()
    learner = User.query.filter_by(id=int(student.user_id or 0)).first() if student and student.user_id else None
    return bool(
        has_verified_safe_ai_lab_db()
        and is_local_ai_lab_enabled()
        and int(course.course_id) in _allowed_copy_ids()
        and actor_id in _allowlisted_actor_ids()
        and learner and learner.role == 'student'
        and int(learner.id) in _allowlisted_user_ids()
    )


def _course_pedagogy_review_bindings(
    lesson: Lesson | None,
    pedagogy: dict,
    skill: ExamSkill | None,
) -> tuple[list[dict], str | None]:
    """Build exact task-to-criterion bindings without exposing answer values."""
    import json
    from app.ai_lab.course_evidence import course_task_checker_fingerprint
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint
    from core.db_models import LessonTask, Tasks

    if not lesson or not lesson.lesson_id or not skill or not isinstance(pedagogy, dict):
        return [], 'Нужно сохранить урок и выбрать один навык, прежде чем подтверждать сопоставление.'
    criteria = {str(item.get('id') or '') for item in pedagogy.get('criteria', []) if isinstance(item, dict)}
    exercises = [item for item in pedagogy.get('exercises', []) if isinstance(item, dict)]
    if not exercises:
        return [], 'Добавьте хотя бы одно связанное упражнение.'

    allowed_authors = _allowlisted_task_author_ids()
    rows = []
    for exercise in exercises:
        if exercise.get('source_type') != 'platform_task' or exercise.get('assessment_method') != 'platform_exact_answer':
            return [], 'Подтверждение доступно только для синтетических заданий с точной проверкой ответа.'
        try:
            task_id = int(exercise.get('task_id'))
        except (TypeError, ValueError):
            return [], 'В сопоставлении есть упражнение без действительного идентификатора.'
        task = db.session.get(Tasks, task_id)
        link = LessonTask.query.filter_by(lesson_id=int(lesson.lesson_id), task_id=task_id).first()
        spec = task.answer_spec if task and isinstance(task.answer_spec, dict) else {}
        if (
            not task or not task.is_active or task.bank_category != 'synthetic_adaptive_draft'
            or not str(task.source_key or '').startswith('boostudy.synthetic.adaptive-v1/')
            or int(task.created_by_id or 0) not in allowed_authors
            or spec.get('type') != 'short_answer' or spec.get('grading_mode') != 'exact'
            or not str(task.answer or '').strip() or not link or bool(link.is_answer_visible_to_student)
        ):
            return [], f'Задание #{task_id} не прошло проверку synthetic-происхождения и точного скрытого ответа.'
        criterion_ids = sorted({str(value) for value in exercise.get('criterion_ids', [])})
        if not criterion_ids or any(value not in criteria for value in criterion_ids):
            return [], f'У задания #{task_id} нет связанного критерия этого урока.'
        expected_answer = link.student_answer if link.student_answer is not None else task.answer
        maximum = task.max_score if isinstance(task.max_score, (int, float)) and task.max_score > 0 else 1
        task_fingerprint = _task_fingerprint(task)
        checker_fingerprints = {
            method: course_task_checker_fingerprint(
                answer_spec=spec,
                answer=task.answer,
                expected_answer=expected_answer,
                assessment_method=method,
                max_score=maximum,
            )
            for method in ('automatic_answer_checker', 'exact_answer_check')
        }
        rows.extend({
            'task_id': task_id,
            'skill_id': f'exam-skill:{int(skill.skill_id)}',
            'topic_code': str(skill.topic_code or ''),
            'criterion_id': criterion_id,
            'assessment_method': 'platform_exact_answer',
            'task_fingerprint': task_fingerprint,
            'checker_fingerprints': checker_fingerprints,
        } for criterion_id in criterion_ids)
    rows.sort(key=lambda item: (item['task_id'], item['criterion_id']))
    return rows, None


def _pedagogy_review_fingerprint(bindings: list[dict]) -> str:
    import hashlib
    import json
    canonical = json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _pedagogy_review_is_current(
    lesson: Lesson | None,
    pedagogy: dict,
    skill: ExamSkill | None,
) -> bool:
    if not lesson:
        return False
    history = (lesson.review_summaries or {}).get('_tutor_core_pedagogy_review_history') or []
    latest = history[-1] if history and isinstance(history[-1], dict) else {}
    if latest.get('status') != 'teacher_confirmed':
        return False
    bindings, error = _course_pedagogy_review_bindings(lesson, pedagogy, skill)
    return bool(not error and latest.get('binding_fingerprint') == _pedagogy_review_fingerprint(bindings))


def _new_course_pedagogy_review(
    course: LearningTrajectory,
    lesson: Lesson,
    pedagogy: dict,
    selected_skill_ids: list[int],
) -> tuple[dict | None, str | None]:
    import datetime as dt
    if not _synthetic_course_review_enabled(course):
        return None, 'Подтверждение сопоставления разрешено только в изолированной synthetic-среде.'
    skills = ExamSkill.query.filter(ExamSkill.skill_id.in_(selected_skill_ids), ExamSkill.is_active.is_(True)).all()
    if len(skills) != 1:
        return None, 'Для подтверждения выберите ровно один активный навык.'
    bindings, error = _course_pedagogy_review_bindings(lesson, pedagogy, skills[0])
    if error:
        return None, error
    return {
        'contract': 'boostudy.teacher-course-task-review.v1',
        'status': 'teacher_confirmed',
        'course_id': int(course.course_id),
        'lesson_id': int(lesson.lesson_id),
        'confirmed_by_user_id': int(current_user.id),
        'confirmed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'effective_course_version': 0,
        'binding_fingerprint': _pedagogy_review_fingerprint(bindings),
        'bindings': bindings,
    }, None


def _pedagogy_contract_from_request(
    lesson: Lesson | None,
    duration: int,
    selected_skill_ids: list[int],
) -> tuple[dict | None, list[str], dict | None]:
    import json
    from app.ai_lab.tutor_core import _structured_mastery_criteria, _validate_lesson_pedagogical_structure
    from core.db_models import LessonTask

    raw = str(request.form.get('pedagogy_contract_json') or '').strip()
    if not raw:
        return None, [], None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None, ['Не удалось прочитать структуру занятия. Заполните её заново и сохраните.'], None
    if not isinstance(payload, dict):
        return None, ['Структура занятия должна содержать объект с целью, этапами и критериями.'], None

    skills = ExamSkill.query.filter(ExamSkill.skill_id.in_(selected_skill_ids)).all() if selected_skill_ids else []
    mastery_criteria = _structured_mastery_criteria(skills[0]) if len(skills) == 1 else []
    skill_ids = [f'exam-skill:{int(skill.skill_id)}' for skill in skills if skill.is_active]
    normalized, errors = _validate_lesson_pedagogical_structure(
        json.dumps(payload, ensure_ascii=False),
        duration=int(duration or 0),
        skill_ids=skill_ids,
        mastery_criteria=mastery_criteria,
    )
    if normalized:
        linked_task_ids = ({int(row.task_id) for row in LessonTask.query.filter_by(lesson_id=lesson.lesson_id).all()}
                           if lesson and lesson.lesson_id else set())
        if request.form.get('bank_tasks_confirmed') == '1':
            linked_task_ids.update(
                int(value) for value in request.form.getlist('bank_task_ids') if str(value).isdigit()
            )
        for exercise in normalized.get('exercises', []):
            if exercise.get('source_type') == 'platform_task' and int(exercise.get('task_id') or 0) not in linked_task_ids:
                errors.append(f"Задание #{exercise.get('task_id')} не привязано к этому уроку. Сначала добавьте его в обычный план урока.")
    return (normalized if not errors else None), list(dict.fromkeys(errors)), payload


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

    scenario_text = (form.studio_scenario.data or '').strip()
    agenda = []
    for index, raw_title in enumerate(scenario_text.splitlines(), start=1):
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
    lesson.lesson_format = form.lesson_format.data or 'Теория + Практика'
    lesson.lesson_type = form.lesson_type.data or 'regular'
    try:
        transition_lesson_status(
            lesson, form.status.data,
            source="course_lesson_edit_form",
            reason="teacher_saved_course_lesson_status",
            actor_user_id=getattr(current_user, "id", None),
        )
    except LessonLifecycleError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(request.url)
    lesson.studio_scenario = scenario_text or None
    lesson.content = form.content.data.strip() if form.content.data else None
    lesson.homework = form.homework.data.strip() if form.homework.data else None
    lesson.homework_status = 'assigned_not_done' if lesson.homework else 'not_assigned'
    lesson.notes = form.teacher_note.data.strip() if form.teacher_note.data else None
    lesson.review_summaries = summaries

    # Save skills from request
    skill_ids = [int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
    if skill_ids:
        lesson.skills = ExamSkill.query.filter(ExamSkill.skill_id.in_(skill_ids)).all()
    else:
        lesson.skills = []


def _ensure_lesson_learning_item(course: LearningTrajectory, lesson: Lesson) -> None:
    """Каждое занятие из программы имеет единый item для будущих элементов обучения."""
    linked_skill_ids = {
        int(skill.skill_id)
        for skill in (lesson.skills or [])
        if skill.skill_id is not None and bool(skill.is_active)
    }
    skill_id = next(iter(linked_skill_ids)) if len(linked_skill_ids) == 1 else None
    item_status = {
        'planned': 'planned',
        'scheduled': 'planned',
        'in_progress': 'in_progress',
        'completed': 'done',
    }.get(str(lesson.status or '').casefold())
    item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).first()
    if not item:
        item = LearningItem(
            course_id=course.course_id,
            module_id=lesson.course_module_id,
            lesson_id=lesson.lesson_id,
            skill_id=skill_id,
            item_type='lesson',
            title=lesson.topic or 'Занятие',
            status=item_status or 'planned',
            order_index=lesson.course_order_index or 0,
        )
        db.session.add(item)
    else:
        item.module_id = lesson.course_module_id
        item.skill_id = skill_id
        item.title = lesson.topic or item.title
        if item_status:
            item.status = item_status


def _next_course_lesson_order(course: LearningTrajectory) -> int:
    current_max = (
        db.session.query(func.coalesce(func.max(Lesson.course_order_index), 0))
        .filter(Lesson.learning_trajectory_id == course.course_id)
        .scalar()
        or 0
    )
    return int(current_max) + 10


@courses_bp.route('/courses/<int:course_id>/lessons/new', methods=['GET', 'POST'])
@login_required
def course_lesson_new(course_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)
    adaptive_editor = _require_adaptive_v2_course_editor(course)

    available_skills = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        available_skills = available_skills.filter_by(exam_course_id=course.exam_course_id)
    available_skills = available_skills.order_by(ExamSkill.task_number.asc().nullslast(), ExamSkill.topic.asc()).all()

    req_prev_order = request.args.get('prev_order', type=int)
    if course.student_id and not course.is_template:
        default_order = _next_course_lesson_order(course)
    else:
        default_order = (req_prev_order + 10) if req_prev_order is not None else _next_course_lesson_order(course)

    lesson = Lesson(
        student_id=student.student_id if student else None,
        learning_trajectory_id=course.course_id,
        duration=request.args.get('duration', type=int) or course.default_lesson_duration or 60,
        status='planned',
        lesson_format=request.args.get('format') or 'Теория + Практика',
        course_order_index=default_order,
    )
    form = _course_lesson_form(course)
    if not form.is_submitted():
        form.duration.data = lesson.duration
        form.lesson_format.data = lesson.lesson_format
        form.course_order_index.data = lesson.course_order_index
        if adaptive_editor:
            form.status.data = 'planned'
            form.lesson_type.data = 'regular'
            previous_lesson = (Lesson.query.filter_by(learning_trajectory_id=int(course.course_id))
                               .order_by(Lesson.course_order_index.desc(), Lesson.lesson_id.desc()).first())
            if previous_lesson:
                previous_skills = [skill for skill in previous_lesson.skills if skill.is_active]
                if len(previous_skills) == 1:
                    request_skill_id = int(previous_skills[0].skill_id)
                    selected_skill_ids = [request_skill_id]
                else:
                    selected_skill_ids = []
            else:
                selected_skill_ids = []
        else:
            selected_skill_ids = []
        requested_module_id = request.args.get('module_id', type=int)
        if requested_module_id and any(module_id == requested_module_id for module_id, _ in form.module_id.choices):
            form.module_id.data = requested_module_id
            mod = TrajectoryModule.query.get(requested_module_id)
            if mod and mod.is_control_exam:
                form.lesson_format.data = 'Контрольный урок / Пробник'

    if form.validate_on_submit():
        if course.student_id and not course.is_template:
            form.course_order_index.data = default_order
        selected_skill_ids = [int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
        expected_version = request.form.get('expected_course_version', type=int)
        if adaptive_editor and (expected_version is None or expected_version != int(course.current_version or 1)):
            form_error = 'Версия программы изменилась. Обновите страницу и перепроверьте план.'
            context = _adaptive_manual_editor_context(course, None, selected_skill_ids, available_skills)
            return _render_course_lesson_form(
                True, form=form, course=course, student=student, lesson=None,
                available_skills=available_skills, selected_skill_ids=selected_skill_ids,
                title='Добавить занятие в индивидуальную программу', pedagogy_errors=[],
                manual_change_error=form_error, **context,
            ), 409
        pedagogy, pedagogy_errors, submitted_pedagogy = _pedagogy_contract_from_request(
            lesson, int(form.duration.data or 0), selected_skill_ids,
        )
        change_reason = str(request.form.get('program_change_reason') or '').strip()
        if adaptive_editor and len(change_reason) < 10:
            pedagogy_errors.append('Укажите педагогическое основание изменения (не менее 10 символов).')
        if pedagogy_errors:
            context = (_adaptive_manual_editor_context(course, None, selected_skill_ids, available_skills)
                       if adaptive_editor else _course_lesson_pedagogy_editor_context(
                           course, None, selected_skill_ids, submitted_pedagogy,
                       ))
            return _render_course_lesson_form(
                adaptive_editor, form=form, course=course, student=student,
                lesson=None, available_skills=available_skills,
                selected_skill_ids=selected_skill_ids, title='Добавить урок',
                pedagogy_errors=pedagogy_errors,
                manual_change_error=None,
                **context,
            )

        selected_task_ids = list(dict.fromkeys(
            int(value) for value in request.form.getlist('bank_task_ids') if str(value).isdigit()
        )) if adaptive_editor else []
        bank_assignment_type = str(request.form.get('bank_assignment_type') or 'classwork').strip().lower()
        selected_bank_tasks = []
        if selected_task_ids:
            if (request.form.get('bank_tasks_confirmed') != '1'
                    or bank_assignment_type not in {'classwork', 'homework'}
                    or len(selected_task_ids) > 1 or len(selected_skill_ids) != 1):
                pedagogy_errors.append('Для нового занятия выберите один материал, один навык и классную или домашнюю работу; подтвердите просмотр условия.')
            else:
                candidate_context = _adaptive_manual_editor_context(course, None, selected_skill_ids, available_skills)
                allowed_candidate_ids = {int(item['task_id']) for item in candidate_context.get('bank_task_candidates', [])}
                skill = ExamSkill.query.filter(ExamSkill.skill_id == selected_skill_ids[0], ExamSkill.is_active.is_(True)).first()
                criterion_id = str(request.form.get(f'bank_task_criterion_{selected_task_ids[0]}') or '').strip()
                task = Tasks.query.filter_by(task_id=selected_task_ids[0], is_active=True).first()
                from types import SimpleNamespace
                from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
                safe_database = has_verified_safe_ai_lab_db()
                checked, binding_error = _course_task_binding(
                    task, skill, criterion_id, course, SimpleNamespace(lesson_id=0),
                ) if task and skill and criterion_id else (None, 'Нет точной привязки материала к навыку и критерию.')
                allowed_authors = set()
                if safe_database:
                    from app.ai_lab.platform_homework import _allowlisted_task_author_ids
                    allowed_authors = {int(value) for value in (_allowlisted_task_author_ids() or [])}
                if selected_task_ids[0] not in allowed_candidate_ids:
                    pedagogy_errors.append('Выбранное упражнение больше не входит в проверенный список для этого навыка.')
                elif binding_error:
                    pedagogy_errors.append(binding_error)
                elif safe_database and int(task.created_by_id or 0) not in allowed_authors:
                    pedagogy_errors.append('Автор материала не входит в synthetic allowlist.')
                elif not checked:
                    pedagogy_errors.append('Не удалось подтвердить источник и способ проверки упражнения.')
                else:
                    from app.ai_lab.tutor_core import _exercise_usage
                    selected_bank_tasks.append({
                        'task': task, 'criterion_id': criterion_id, 'checked': checked,
                        'usage': _exercise_usage(int(task.task_id), int(student.student_id)),
                    })
        if pedagogy_errors:
            context = _adaptive_manual_editor_context(course, None, selected_skill_ids, available_skills)
            return _render_course_lesson_form(
                adaptive_editor, form=form, course=course, student=student, lesson=None,
                available_skills=available_skills, selected_skill_ids=selected_skill_ids,
                title='Добавить урок', pedagogy_errors=pedagogy_errors,
                **context,
            ), 400

        source_course_version = int(course.current_version or 1)
        _snapshot_course(course, 'teacher_manual_future_lesson_create' if adaptive_editor else 'lesson_create')
        _save_course_lesson_from_form(course, lesson, form)
        if pedagogy:
            summaries = dict(lesson.review_summaries or {})
            summaries['_tutor_core_pedagogy'] = pedagogy
            lesson.review_summaries = summaries
        db.session.add(lesson)
        db.session.flush()
        if selected_bank_tasks:
            import datetime as dt
            from app.ai_lab.platform_homework import _task_fingerprint
            for selected in selected_bank_tasks:
                task = selected['task']
                checked = selected['checked']
                binding = checked['binding']
                note = {
                    'contract': 'boostudy.teacher-course-task-selection.v1',
                    'source': 'teacher_manual_task_bank_selection',
                    'purpose': 'shared_review',
                    'criterion_id': selected['criterion_id'],
                    'skill_id': f'exam-skill:{int(selected_skill_ids[0])}',
                    'source_provenance': {
                        'course_id': checked['source_course_id'],
                        'course_version': checked['source_course_version'],
                        'lesson_id': checked['source_lesson_id'],
                        'task_fingerprint': binding.get('task_fingerprint') or _task_fingerprint(task),
                    },
                    'selected_by_user_id': int(current_user.id),
                    'teacher_reason': change_reason,
                    'pedagogical_status': checked['pedagogical_status'],
                    'usage_status_at_selection': selected['usage'].get('status'),
                    'independent_verification_allowed': False,
                    'selected_at': dt.datetime.now(timezone.utc).isoformat(),
                }
                db.session.add(LessonTask(
                    lesson_id=int(lesson.lesson_id), task_id=int(task.task_id),
                    assignment_type=bank_assignment_type, status='pending',
                    notes=json.dumps(note, ensure_ascii=False),
                    is_visible_to_student=False, is_answer_visible_to_student=False,
                ))
        if adaptive_editor:
            summaries = dict(lesson.review_summaries or {})
            history = list(summaries.get('_teacher_manual_plan_changes') or [])
            history.append({
                'contract': 'boostudy.course-manual-change.v1',
                'source': 'teacher_manual',
                'decision': 'teacher_created_future_lesson',
                'reason': change_reason,
                'changed_fields': ['lesson_added', 'topic', 'content', 'pedagogical_structure', 'exercise_selection'],
                'before_plan': None,
                'after_plan': {
                    'topic': lesson.topic,
                    'duration': int(lesson.duration or 0),
                    'content': lesson.content or '',
                    'structure': (lesson.review_summaries or {}).get('_tutor_core_pedagogy') or {},
                    'task_ids': [int(item['task'].task_id) for item in selected_bank_tasks],
                },
                'actor_user_id': int(current_user.id),
                'source_course_version': source_course_version,
                'effective_course_version': int(course.current_version or 1),
                'created_at': datetime.now(timezone.utc).isoformat(),
            })
            summaries['_teacher_manual_plan_changes'] = history
            lesson.review_summaries = summaries
        _ensure_lesson_learning_item(course, lesson)
        db.session.commit()

        if adaptive_editor and student and student.user_id:
            flash('План будущего занятия сохранён как ручное изменение преподавателя; курс и расписание не запускаются автоматически.', 'success')
            return redirect(url_for('main.universal_profile_view', user_id=int(student.user_id), _anchor='adaptive-learning-summary'))
        if request.form.get('submit_action') == 'save_and_next':
            flash(f'Урок «{lesson.topic}» успешно сохранён. Заполните следующий.', 'success')
            return redirect(url_for(
                'courses.course_lesson_new',
                course_id=course.course_id,
                module_id=lesson.course_module_id or 0,
                prev_order=lesson.course_order_index,
                duration=lesson.duration,
                format=lesson.lesson_format,
            ))

        flash('Урок добавлен в программу курса.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    selected_skill_ids = ([int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
                          if form.is_submitted() else locals().get('selected_skill_ids', []))
    context = (_adaptive_manual_editor_context(course, None, selected_skill_ids, available_skills)
               if adaptive_editor else _course_lesson_pedagogy_editor_context(course, None, selected_skill_ids))
    return _render_course_lesson_form(
        adaptive_editor,
        form=form,
        course=course,
        student=student,
        lesson=None,
        available_skills=available_skills,
        selected_skill_ids=selected_skill_ids,
        title='Добавить урок',
        pedagogy_errors=[],
        expected_course_version=int(course.current_version or 1),
        **context,
    )


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
def course_lesson_edit(course_id: int, lesson_id: int):
    course = _guard_course(course_id)
    student = _require_course_manager(course)
    lesson = Lesson.query.filter_by(lesson_id=lesson_id).first_or_404()
    if lesson.learning_trajectory_id != course.course_id:
        abort(404)

    available_skills = ExamSkill.query.filter_by(is_active=True)
    if course.exam_course_id:
        available_skills = available_skills.filter_by(exam_course_id=course.exam_course_id)
    available_skills = available_skills.order_by(ExamSkill.task_number.asc().nullslast(), ExamSkill.topic.asc()).all()

    form = _course_lesson_form(course, lesson)
    if request.method == 'POST' and course.student_id and not course.is_template:
        db.session.refresh(course)
        expected_version = request.form.get('expected_course_version', type=int)
        if expected_version is None or expected_version != int(course.current_version or 1):
            selected_ids = [int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
            return render_template(
                'course_lesson_form.html', form=form, course=course, student=student,
                lesson=lesson, available_skills=available_skills,
                selected_skill_ids=selected_ids or [s.skill_id for s in lesson.skills],
                title='Редактировать урок', pedagogy_errors=[],
                course_version_error=(
                    'Версия программы изменилась после открытия формы. Обновите страницу и повторно проверьте план перед сохранением.'
                    if expected_version is not None else
                    'В форме отсутствует версия программы. Обновите страницу и сохраните изменения из актуального редактора.'
                ),
                **_course_lesson_pedagogy_editor_context(course, lesson, selected_ids or [s.skill_id for s in lesson.skills]),
            ), 409
    if form.validate_on_submit():
        selected_skill_ids = [int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
        if course.student_id and not course.is_template and int(form.course_order_index.data or 0) != int(lesson.course_order_index or 0):
            flash('Порядок уроков сейчас нельзя менять числом: в этой версии программы не проверяются все предпосылки перестановки. Используйте действие «Отложить урок» с обоснованием или восстановите его в очередь.', 'warning')
            return redirect(request.url)
        pedagogy, pedagogy_errors, submitted_pedagogy = _pedagogy_contract_from_request(
            lesson, int(form.duration.data or 0), selected_skill_ids,
        )
        review_requested = request.form.get('pedagogy_teacher_confirmation') == '1'
        review_event = None
        if review_requested:
            review_event, review_error = _new_course_pedagogy_review(
                course, lesson, pedagogy or {}, selected_skill_ids,
            )
            if review_error:
                pedagogy_errors.append(review_error)
        if pedagogy_errors:
            return render_template(
                'course_lesson_form.html', form=form, course=course, student=student,
                lesson=lesson, available_skills=available_skills,
                selected_skill_ids=selected_skill_ids, title='Редактировать урок',
                pedagogy_errors=pedagogy_errors,
                **_course_lesson_pedagogy_editor_context(course, lesson, selected_skill_ids, submitted_pedagogy),
            )
        selected_task_ids = list(dict.fromkeys(
            int(value) for value in request.form.getlist('bank_task_ids') if str(value).isdigit()
        ))
        bank_tasks_to_attach = []
        bank_task_errors = []
        existing_task_ids = {int(link.task_id) for link in LessonTask.query.filter_by(lesson_id=lesson.lesson_id).all()}
        selected_skills = ExamSkill.query.filter(ExamSkill.skill_id.in_(selected_skill_ids)).all() if selected_skill_ids else []
        from app.ai_lab.tutor_core import _exercise_usage
        bank_assignment_type = str(request.form.get('bank_assignment_type') or 'classwork').strip().lower()
        if selected_task_ids and bank_assignment_type not in {'classwork', 'homework'}:
            bank_task_errors.append('Выберите обычную классную или домашнюю работу.')
        if selected_task_ids and len(selected_skills) != 1:
            bank_task_errors.append('Выберите ровно один активный навык, чтобы привязать задания из банка.')
        if selected_task_ids and request.form.get('bank_tasks_confirmed') != '1':
            bank_task_errors.append('Подтвердите, что просмотрели условия и способ проверки выбранных заданий.')
        task_reason = str(request.form.get('program_change_reason') or '').strip()
        from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
        safe_database = has_verified_safe_ai_lab_db()
        allowed_task_authors: set[int] = set()
        if safe_database:
            from app.ai_lab.platform_homework import _allowlisted_task_author_ids
            allowed_task_authors = {int(value) for value in (_allowlisted_task_author_ids() or [])}
        for task_id in selected_task_ids:
            task = Tasks.query.filter_by(task_id=task_id, is_active=True).first()
            if not task or len(selected_skills) != 1:
                bank_task_errors.append(f'Задание #{task_id} недоступно для привязки к выбранному навыку.')
                continue
            criterion_id = str(request.form.get(f'bank_task_criterion_{task_id}') or '').strip()
            checked, binding_error = _course_task_binding(task, selected_skills[0], criterion_id, course, lesson)
            if binding_error:
                bank_task_errors.append(f'Задание #{task_id}: {binding_error}')
                continue
            if safe_database and int(task.created_by_id or 0) not in allowed_task_authors:
                bank_task_errors.append(f'Задание #{task_id} создано автором вне synthetic allowlist.')
                continue
            if not safe_database and str(task.prototype_status or '').casefold() not in {'approved', 'expert_approved', 'reviewed'}:
                bank_task_errors.append(f'Задание #{task_id} не прошло экспертную проверку и не может попасть в рабочий план.')
                continue
            usage = _exercise_usage(task_id, int(lesson.student_id or 0))
            purpose = str(request.form.get(f'bank_task_purpose_{task_id}') or 'independent').strip().lower()
            independent_allowed = _course_task_independent_allowed(checked, usage)
            if purpose not in {'independent', 'shared_review'}:
                bank_task_errors.append(f'Задание #{task_id}: неизвестный режим использования.')
                continue
            if purpose == 'independent' and not independent_allowed:
                bank_task_errors.append(f'Задание #{task_id} нельзя считать независимой проверкой: оно уже предъявлялось или относится к другой версии/уроку.')
                continue
            bank_tasks_to_attach.append({
                'task': task,
                'purpose': purpose,
                'criterion_id': criterion_id,
                'checked': checked,
                'existing_link': LessonTask.query.filter_by(lesson_id=lesson.lesson_id, task_id=task_id).first(),
            })
        if bank_task_errors:
            return render_template(
                'course_lesson_form.html', form=form, course=course, student=student,
                lesson=lesson, available_skills=available_skills,
                selected_skill_ids=selected_skill_ids, title='Редактировать урок',
                pedagogy_errors=[], bank_task_errors=bank_task_errors,
                **_course_lesson_pedagogy_editor_context(course, lesson, selected_skill_ids, submitted_pedagogy),
            )

        def _selection_note(selected):
            checked = selected['checked']
            binding = checked['binding']
            return {
                'contract': 'boostudy.teacher-course-task-selection.v1',
                'source': 'teacher_manual_task_bank_selection',
                'purpose': selected['purpose'],
                'criterion_id': selected['criterion_id'],
                'skill_id': f'exam-skill:{selected_skills[0].skill_id}',
                'source_provenance': {
                    'course_id': checked['source_course_id'],
                    'course_version': checked['source_course_version'],
                    'lesson_id': checked['source_lesson_id'],
                    'task_fingerprint': binding.get('task_fingerprint'),
                },
                'selected_by_user_id': int(current_user.id),
                'teacher_reason': task_reason,
                'pedagogical_status': checked['pedagogical_status'],
            }

        active_assigned_homework_task_ids = set()
        if bank_assignment_type == 'homework' and selected_task_ids:
            from core.db_models import Assignment, AssignmentTask, Submission
            active_assigned_homework_task_ids = {
                int(task_id) for task_id, in (
                    db.session.query(AssignmentTask.task_id)
                    .join(Assignment, Assignment.assignment_id == AssignmentTask.assignment_id)
                    .join(Submission, Submission.assignment_id == Assignment.assignment_id)
                    .filter(
                        Assignment.lesson_id == lesson.lesson_id,
                        Assignment.assignment_type == 'homework',
                        Assignment.is_active.is_(True),
                        Submission.student_id == int(lesson.student_id or 0),
                        Submission.status != 'REVOKED',
                        AssignmentTask.task_id.in_(selected_task_ids),
                    ).distinct().all()
                )
            }

        bank_task_changed_ids = set()
        for selected in bank_tasks_to_attach:
            link = selected.get('existing_link')
            if not link or link.assignment_type != bank_assignment_type:
                bank_task_changed_ids.add(int(selected['task'].task_id))
                continue
            try:
                saved_note = json.loads(link.notes or '{}')
            except (TypeError, ValueError):
                saved_note = {}
            expected_note = _selection_note(selected)
            if any(saved_note.get(key) != value for key, value in expected_note.items()):
                bank_task_changed_ids.add(int(selected['task'].task_id))

        changed_fields = []
        comparisons = (
            ('topic', lesson.topic, form.topic.data.strip()),
            ('duration', lesson.duration, form.duration.data),
            ('lesson_format', lesson.lesson_format or 'Теория + Практика', form.lesson_format.data or 'Теория + Практика'),
            ('status', lesson.status or 'planned', form.status.data or 'planned'),
            ('module', lesson.course_module_id, form.module_id.data or None),
            ('content', lesson.content or '', form.content.data.strip() if form.content.data else ''),
            ('homework', lesson.homework or '', form.homework.data.strip() if form.homework.data else ''),
            ('studio_scenario', lesson.studio_scenario or '', form.studio_scenario.data.strip() if form.studio_scenario.data else ''),
            ('teacher_note', lesson.notes or '', form.teacher_note.data.strip() if form.teacher_note.data else ''),
        )
        changed_fields.extend(name for name, before, after in comparisons if before != after)
        current_skill_ids = {int(skill.skill_id) for skill in lesson.skills if skill.is_active}
        if set(selected_skill_ids) != current_skill_ids:
            changed_fields.append('skills')
        current_pedagogy = dict((lesson.review_summaries or {}).get('_tutor_core_pedagogy') or {})
        if pedagogy and pedagogy != current_pedagogy:
            changed_fields.append('pedagogical_structure')
        if bank_task_changed_ids:
            changed_fields.append('lesson_tasks')
        is_individual_copy = bool(not course.is_template and course.student_id)
        change_reason = str(request.form.get('program_change_reason') or '').strip()
        manual_change_error = None
        if is_individual_copy and changed_fields and len(change_reason) < 10:
            manual_change_error = 'Для ручного изменения индивидуальной программы укажите педагогическое основание (не менее 10 символов). Tutor Core не будет записывать это как собственную рекомендацию.'
        if manual_change_error:
            return render_template(
                'course_lesson_form.html', form=form, course=course, student=student,
                lesson=lesson, available_skills=available_skills,
                selected_skill_ids=selected_skill_ids, title='Редактировать урок',
                pedagogy_errors=[], manual_change_error=manual_change_error,
                **_course_lesson_pedagogy_editor_context(course, lesson, selected_skill_ids, submitted_pedagogy),
            )
        source_course_version = int(course.current_version or 1)
        before_plan = {
            'topic': lesson.topic or '',
            'duration': int(lesson.duration or 0),
            'content': lesson.content or '',
            'homework': lesson.homework or '',
            'structure': current_pedagogy,
            'task_ids': sorted(existing_task_ids),
        }
        if changed_fields and is_individual_copy:
            _snapshot_course(course, 'teacher_manual_lesson_edit')
        _save_course_lesson_from_form(course, lesson, form)
        if pedagogy:
            summaries = dict(lesson.review_summaries or {})
            summaries['_tutor_core_pedagogy'] = pedagogy
            lesson.review_summaries = summaries
        if bank_tasks_to_attach:
            for selected in bank_tasks_to_attach:
                task = selected['task']
                note = _selection_note(selected)
                link = selected.get('existing_link')
                if link:
                    if int(task.task_id) in bank_task_changed_ids:
                        link.assignment_type = bank_assignment_type
                        link.notes = json.dumps({**note, 'selected_at': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
                    if bank_assignment_type == 'homework':
                        is_assigned = int(task.task_id) in active_assigned_homework_task_ids
                        if not is_assigned and link.is_visible_to_student:
                            publication_history = saved_note.get('publication_history')
                            if not isinstance(publication_history, list):
                                publication_history = []
                            publication_history.append({
                                'state': 'prepared_hidden',
                                'changed_by_user_id': int(current_user.id),
                                'changed_at': datetime.now(timezone.utc).isoformat(),
                                'reason': 'Сохранение плана не публикует условия домашней работы.',
                            })
                            note['publication_history'] = publication_history[-10:]
                        link.is_visible_to_student = is_assigned
                        link.is_answer_visible_to_student = False
                else:
                    db.session.add(LessonTask(
                        lesson=lesson,
                        task_id=int(task.task_id),
                        assignment_type=bank_assignment_type,
                        status='pending',
                        notes=json.dumps({**note, 'selected_at': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
                        is_visible_to_student=False,
                        is_answer_visible_to_student=False,
                    ))
                if int(task.task_id) not in existing_task_ids:
                    existing_task_ids.add(int(task.task_id))
        if safe_database and _synthetic_course_review_enabled(course):
            from core.db_models import Assignment, AssignmentTask, Submission

            assigned_homework_task_ids = {
                int(task_id) for task_id, in (
                    db.session.query(AssignmentTask.task_id)
                    .join(Assignment, Assignment.assignment_id == AssignmentTask.assignment_id)
                    .join(Submission, Submission.assignment_id == Assignment.assignment_id)
                    .filter(
                        Assignment.lesson_id == lesson.lesson_id,
                        Assignment.assignment_type == 'homework',
                        Assignment.is_active.is_(True),
                        Submission.student_id == int(lesson.student_id or 0),
                        Submission.status != 'REVOKED',
                    ).distinct().all()
                )
            }
            for link in LessonTask.query.filter_by(lesson_id=lesson.lesson_id).all():
                if str(link.assignment_type or 'homework').casefold() != 'homework':
                    continue
                is_assigned = int(link.task_id) in assigned_homework_task_ids
                if bool(link.is_visible_to_student) == is_assigned and not bool(link.is_answer_visible_to_student):
                    continue
                try:
                    saved_note = json.loads(str(link.notes or '{}'))
                except (TypeError, ValueError):
                    saved_note = {'preparation_note': str(link.notes or '')} if link.notes else {}
                if not isinstance(saved_note, dict):
                    saved_note = {}
                if not is_assigned and link.is_visible_to_student:
                    history = saved_note.get('publication_history')
                    if not isinstance(history, list):
                        history = []
                    history.append({
                        'state': 'prepared_hidden',
                        'changed_by_user_id': int(current_user.id),
                        'changed_at': datetime.now(timezone.utc).isoformat(),
                        'reason': 'Сохранение плана не публикует условия домашней работы.',
                    })
                    saved_note['publication_history'] = history[-10:]
                    link.notes = json.dumps(saved_note, ensure_ascii=False)
                link.is_visible_to_student = is_assigned
                link.is_answer_visible_to_student = False
        summaries = dict(lesson.review_summaries or {})
        review_history = list(summaries.get('_tutor_core_pedagogy_review_history') or [])
        if review_event:
            review_event['effective_course_version'] = int(course.current_version or 1)
            review_history.append(review_event)
        elif (not review_requested and review_history
              and isinstance(review_history[-1], dict)
              and review_history[-1].get('status') == 'teacher_confirmed'):
            import datetime as dt
            review_history.append({
                'contract': 'boostudy.teacher-course-task-review.v1',
                'status': 'revoked',
                'course_id': int(course.course_id),
                'lesson_id': int(lesson.lesson_id),
                'revoked_by_user_id': int(current_user.id),
                'revoked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'effective_course_version': int(course.current_version or 1),
                'reason': 'teacher_unchecked_confirmation',
            })
        if review_history:
            summaries['_tutor_core_pedagogy_review_history'] = review_history
            lesson.review_summaries = summaries
        if is_individual_copy and changed_fields:
            summaries = dict(lesson.review_summaries or {})
            manual_history = list(summaries.get('_teacher_manual_plan_changes') or [])
            after_task_ids = sorted(existing_task_ids | {int(item['task'].task_id) for item in bank_tasks_to_attach})
            after_plan = {
                'topic': lesson.topic or '',
                'duration': int(lesson.duration or 0),
                'content': lesson.content or '',
                'homework': lesson.homework or '',
                'structure': (lesson.review_summaries or {}).get('_tutor_core_pedagogy') or {},
                'task_ids': after_task_ids,
            }
            manual_history.append({
                'contract': 'boostudy.course-manual-change.v1',
                'source': 'teacher_manual',
                'decision': 'teacher_created_plan_change',
                'reason': change_reason,
                'changed_fields': changed_fields,
                'before_plan': before_plan,
                'after_plan': after_plan,
                'actor_user_id': int(current_user.id),
                'source_course_version': source_course_version,
                'effective_course_version': int(course.current_version or 1),
                'created_at': datetime.now().astimezone().isoformat(),
            })
            summaries['_teacher_manual_plan_changes'] = manual_history
            lesson.review_summaries = summaries
        _ensure_lesson_learning_item(course, lesson)
        db.session.commit()

        if request.form.get('submit_action') == 'save_and_next':
            flash(f'Урок «{lesson.topic}» обновлён. Заполните следующий.', 'success')
            return redirect(url_for(
                'courses.course_lesson_new',
                course_id=course.course_id,
                module_id=lesson.course_module_id or 0,
                prev_order=lesson.course_order_index,
                duration=lesson.duration,
                format=lesson.lesson_format,
            ))

        flash('План урока обновлён.', 'success')
        return redirect(url_for('courses.course_view', course_id=course.course_id))

    selected_skill_ids = ([int(sid) for sid in request.form.getlist('skill_ids') if sid.isdigit()]
                          if form.is_submitted() else [s.skill_id for s in lesson.skills])
    return render_template(
        'course_lesson_form.html',
        form=form,
        course=course,
        student=student,
        lesson=lesson,
        available_skills=available_skills,
        selected_skill_ids=selected_skill_ids,
        title='Редактировать урок',
        pedagogy_errors=[],
        **_course_lesson_pedagogy_editor_context(course, lesson, selected_skill_ids),
    )


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/clone', methods=['POST'])
@login_required
def course_lesson_clone(course_id: int, lesson_id: int):
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        abort(403)

    lesson = Lesson.query.filter_by(lesson_id=lesson_id).first_or_404()
    if lesson.learning_trajectory_id != course.course_id:
        abort(404)

    next_order = (lesson.course_order_index or 0) + 10

    new_lesson = Lesson(
        student_id=lesson.student_id,
        learning_trajectory_id=course.course_id,
        course_module_id=lesson.course_module_id,
        exam_course_id=lesson.exam_course_id,
        lesson_type=lesson.lesson_type,
        lesson_format=lesson.lesson_format,
        duration=lesson.duration,
        course_order_index=next_order,
        status='planned',
        topic=f"{lesson.topic} (Копия)",
        notes=lesson.notes,
        content=lesson.content,
        studio_scenario=lesson.studio_scenario,
        homework=lesson.homework,
        homework_status='assigned_not_done' if lesson.homework else 'not_assigned',
        review_summaries=lesson.review_summaries,
    )
    new_lesson.skills = list(lesson.skills)
    db.session.add(new_lesson)
    db.session.flush()

    for att in (lesson.attachments or []):
        new_att = LessonAttachment(
            lesson_id=new_lesson.lesson_id,
            file_name=att.file_name,
            file_path=att.file_path,
            file_size=att.file_size,
            target=att.target,
        )
        db.session.add(new_att)

    _ensure_lesson_learning_item(course, new_lesson)
    db.session.commit()
    flash(f'Урок «{lesson.topic}» успешно клонирован.', 'success')
    return redirect(url_for('courses.course_view', course_id=course.course_id))


ALLOWED_LESSON_FILE_EXTENSIONS = {'xlsx', 'xls', 'csv', 'txt', 'docx', 'pdf', 'py'}

def _allowed_lesson_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LESSON_FILE_EXTENSIONS


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/attachments/upload', methods=['POST'])
@login_required
def upload_lesson_attachment(course_id: int, lesson_id: int):
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

    lesson = Lesson.query.filter_by(lesson_id=lesson_id).first_or_404()
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Пустое имя файла'}), 400

    if not _allowed_lesson_file(file.filename):
        return jsonify({'success': False, 'error': 'Недопустимый формат файла. Разрешены: .xlsx, .xls, .csv, .txt, .docx, .pdf, .py'}), 400

    original_filename = secure_filename(file.filename) or 'attachment'
    upload_folder = os.path.join(current_app.static_folder, 'uploads', 'courses', str(course_id), 'lessons', str(lesson_id))
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, original_filename)
    file.save(file_path)
    file_size = os.path.getsize(file_path)

    relative_url = f"/static/uploads/courses/{course_id}/lessons/{lesson_id}/{original_filename}"
    target = request.form.get('target', 'theory')
    if target not in ('theory', 'homework'):
        target = 'theory'

    attachment = LessonAttachment(
        lesson_id=lesson.lesson_id,
        file_name=original_filename,
        file_path=relative_url,
        file_size=file_size,
        target=target,
    )
    db.session.add(attachment)
    db.session.commit()

    return jsonify({
        'success': True,
        'attachment': {
            'id': attachment.id,
            'file_name': attachment.file_name,
            'file_path': attachment.file_path,
            'file_size': attachment.file_size,
            'target': attachment.target,
        }
    })


@courses_bp.route('/courses/<int:course_id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_lesson_attachment(course_id: int, attachment_id: int, lesson_id: int | None = None):
    course = _guard_course(course_id)
    if not _course_viewer_can_manage():
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

    attachment = LessonAttachment.query.get_or_404(attachment_id)
    lesson = Lesson.query.get(attachment.lesson_id)
    if not lesson or lesson.learning_trajectory_id != course.course_id:
        return jsonify({'success': False, 'error': 'Файл не найден'}), 404

    try:
        full_path = os.path.join(current_app.root_path, attachment.file_path.lstrip('/'))
        if os.path.isfile(full_path):
            os.remove(full_path)
    except Exception:
        pass

    db.session.delete(attachment)
    db.session.commit()
    return jsonify({'success': True})


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/start', methods=['POST'])
@login_required
def course_lesson_start(course_id: int, lesson_id: int):
    """Явно запускает занятие из учебного плана и открывает V2 Studio."""
    course = _guard_course(course_id)
    _require_course_manager(course)
    if course.is_template or not course.student_id:
        abort(400)
    db.session.refresh(course)
    payload = request.get_json(silent=True) or {}
    expected_version = request.form.get('expected_course_version', type=int) or payload.get('expected_course_version')
    try:
        expected_version = int(expected_version) if expected_version is not None else None
    except (TypeError, ValueError):
        expected_version = None
    if expected_version is None or expected_version != int(course.current_version or 1):
        flash('Программа изменилась после открытия страницы. Обновите её и проверьте порядок уроков перед запуском.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson_id}'))
    lesson = Lesson.query.filter_by(lesson_id=lesson_id, student_id=course.student_id).first_or_404()
    if lesson.learning_trajectory_id != course.course_id and not TrajectoryModule.query.filter_by(module_id=lesson.course_module_id, course_id=course.course_id).first():
        abort(404)
    course_lessons = Lesson.query.filter_by(
        learning_trajectory_id=course.course_id, student_id=course.student_id,
    ).all()
    other_active = [row for row in course_lessons if row.status == 'in_progress' and row.lesson_id != lesson.lesson_id]
    if lesson.status in {'planned', 'draft', 'scheduled'} and other_active:
        flash(f'Сначала продолжите активный урок «{other_active[0].topic or "Без названия"}». В индивидуальной программе допускается одно активное занятие.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))
    preceding = unresolved_preceding_lessons(course_lessons, lesson)
    if lesson.status in {'planned', 'draft', 'scheduled'} and preceding:
        names = ', '.join(f'№{row.course_order_index} «{row.topic or "Без названия"}»' for row in preceding[:3])
        flash(f'Перед запуском есть более ранние уроки без решения: {names}. Завершите их или явно отложите с основанием и подтверждением проверки предпосылок.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))
    if lesson.status in {'planned', 'draft', 'scheduled'}:
        transition_lesson_status(
            lesson, "in_progress",
            source="course_lesson_start",
            reason="teacher_started_course_lesson",
            actor_user_id=getattr(current_user, "id", None),
            started_at=lesson.started_at or utc_now(),
        )
        lesson.published_at = lesson.published_at or utc_now()
    for link in LessonTask.query.filter_by(lesson_id=lesson.lesson_id).all():
        try:
            selection_note = json.loads(str(link.notes or '{}'))
        except (TypeError, ValueError):
            selection_note = {}
        if (isinstance(selection_note, dict)
                and selection_note.get('contract') == 'boostudy.teacher-course-task-selection.v1'
                and str(link.assignment_type or '').casefold() == 'classwork'):
            link.is_visible_to_student = True
            link.is_answer_visible_to_student = False
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


@courses_bp.route('/courses/<int:course_id>/lessons/<int:lesson_id>/sequence-decision', methods=['POST'])
@login_required
def course_lesson_sequence_decision(course_id: int, lesson_id: int):
    """Откладывает/возвращает будущий урок с явным решением преподавателя."""
    course = _guard_course(course_id)
    _require_course_manager(course)
    if course.is_template or not course.student_id:
        abort(400)
    db.session.refresh(course)
    expected_version = request.form.get('expected_course_version', type=int)
    if expected_version is None or expected_version != int(course.current_version or 1):
        if request.is_json:
            return jsonify({'success': False, 'error': 'Программа изменилась. Обновите страницу и повторите решение.'}), 409
        flash('Программа изменилась. Обновите страницу и повторите решение по актуальной версии.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson_id}'))
    lesson = Lesson.query.filter_by(
        lesson_id=lesson_id, learning_trajectory_id=course.course_id, student_id=course.student_id,
    ).first_or_404()
    if lesson.status not in {'planned', 'draft', 'scheduled'}:
        flash('Менять очередь можно только у ещё не начатого урока.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))

    action = str(request.form.get('action') or '').strip().lower()
    reason = str(request.form.get('reason') or '').strip()
    prerequisite_reviewed = request.form.get('prerequisite_reviewed') == '1'
    if action not in {'defer', 'restore'}:
        abort(400)
    if len(reason) < 10:
        flash('Укажите основание решения (не менее 10 символов).', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))
    if not prerequisite_reviewed:
        flash('Подтвердите, что проверили обязательные предпосылки и ограничения программы.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))

    was_deferred = lesson_is_deferred(lesson)
    if (action == 'defer' and was_deferred) or (action == 'restore' and not was_deferred):
        flash('Очередь уже находится в выбранном состоянии; изменений не внесено.', 'info')
        return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))

    _snapshot_course(course, f'teacher_manual_sequence_{action}')
    record_course_sequence_decision(
        lesson,
        action=action,
        reason=reason,
        actor_user_id=int(current_user.id),
        effective_course_version=int(course.current_version or 1),
    )
    db.session.commit()
    flash(
        'Урок отложен по решению преподавателя; статус проведения, работы и баланс не менялись.'
        if action == 'defer' else 'Урок возвращён в очередь по решению преподавателя; статус и баланс не менялись.',
        'success',
    )
    return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))


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

    linked_skill_ids = {int(skill.skill_id) for skill in lesson.skills if skill.is_active}
    item_skill_id = int(item.skill_id) if item and item.skill_id else None
    if item_skill_id and linked_skill_ids and item_skill_id not in linked_skill_ids:
        skill = None
    elif item_skill_id:
        skill = ExamSkill.query.filter_by(skill_id=item_skill_id, is_active=True).first()
    elif len(linked_skill_ids) == 1:
        _ensure_lesson_learning_item(course, lesson)
        item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).first()
        skill = item.skill if item else None
    else:
        skill = None

    if not skill or not skill.task_number:
        if not request.is_json:
            flash('Для автоподбора выберите один однозначный активный навык урока с номером задания.', 'warning')
            return redirect(url_for('courses.course_view', course_id=course.course_id, _anchor=f'lesson-{lesson.lesson_id}'))
        return jsonify({'success': False, 'error': 'Нельзя однозначно определить навык урока. Выберите один активный навык с номером задания.'}), 409

    replace = bool((request.get_json(silent=True) or {}).get('replace'))
    if replace:
        for linked in list(lesson.homework_tasks):
            if (linked.notes or '').startswith('auto:'):
                db.session.delete(linked)
    used_ids = {linked.task_id for linked in lesson.homework_tasks}
    specs = [('warmup', 2, 1), ('practice', 5, 2), ('advanced', 2, 3), ('control', 2, 2), ('homework', 6, 2)]
    created = []
    for category, count, difficulty in specs:
        query = Tasks.query.filter_by(task_number=skill.task_number, is_active=True).filter(Tasks.task_id.notin_(used_ids))
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

    # Новые адаптивные метрики
    try:
        cs = data.get('comprehension_score')
        outcome.comprehension_score = max(1, min(5, int(cs))) if cs is not None and str(cs).strip() else None
    except (ValueError, TypeError):
        outcome.comprehension_score = None

    outcome.independence_level = (data.get('independence_level') or '').strip() or None
    outcome.pacing = (data.get('pacing') or '').strip() or None

    # Ошибки и затруднения
    raw_errors = data.get('identified_errors')
    if isinstance(raw_errors, str) and raw_errors.strip():
        try:
            raw_errors = json.loads(raw_errors)
        except Exception:
            raw_errors = [{'error_type': 'Затруднение', 'description': raw_errors.strip()}]
    elif not isinstance(raw_errors, list):
        # Если из формы пришли строковые поля
        err_type = (data.get('new_error_type') or '').strip()
        err_desc = (data.get('new_error_description') or '').strip()
        if err_type or err_desc:
            raw_errors = [{'error_type': err_type or 'Ошибка', 'description': err_desc}]
        else:
            raw_errors = []
    outcome.identified_errors = raw_errors

    outcome.content_snapshot = {
        'topic': lesson.topic,
        'content': lesson.content,
        'content_blocks': lesson.content_blocks,
        'materials': lesson.materials,
        'review_summaries': lesson.review_summaries,
        'task_ids': [item.task_id for item in lesson.homework_tasks],
    }
    # Saving a pedagogical outcome is not proof that the session took place.
    # Completion and balance deduction belong to the lesson lifecycle routes.
    _ensure_lesson_learning_item(course, lesson)
    db.session.flush()

    # Запуск интеллектуальной адаптации курса
    from app.courses.adaptive_engine import CourseAdaptiveEngine
    diff_summary = CourseAdaptiveEngine.apply_lesson_adaptation(
        course=course,
        lesson=lesson,
        outcome=outcome,
        trigger_replan=False,
    )

    db.session.commit()
    if request.is_json:
        return jsonify({
            'success': True,
            'lesson_id': lesson.lesson_id,
            'status': lesson.status,
            'adaptive_diff': diff_summary,
        })
    flash('Итог занятия сохранён. Аналитика обновлена; учебный план остаётся без изменений до решения преподавателя в Tutor Core.', 'success')
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
    """Открывает ближайший существующий урок индивидуального курса для подготовки."""
    course = _guard_course(course_id)
    _require_course_manager(course)
    if course.is_template or not course.student_id:
        abort(400)
    db.session.refresh(course)
    payload = request.get_json(silent=True) or {}
    expected_version = request.form.get('expected_course_version', type=int) or payload.get('expected_course_version')
    try:
        expected_version = int(expected_version) if expected_version is not None else None
    except (TypeError, ValueError):
        expected_version = None
    if expected_version is None or expected_version != int(course.current_version or 1):
        if request.is_json:
            return jsonify({'success': False, 'error': 'Программа изменилась. Обновите страницу перед подготовкой урока.'}), 409
        flash('Программа изменилась. Обновите страницу перед подготовкой урока.', 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id))
    lessons = Lesson.query.filter_by(
        learning_trajectory_id=course.course_id, student_id=course.student_id,
    ).all()
    target, issue, blockers = select_next_course_lesson(lessons)
    if issue:
        messages = {
            'multiple_active_lessons': 'В программе несколько активных уроков. Сначала разрешите эту неоднозначность.',
            'unresolved_preceding_lessons': 'Перед следующим уроком остаются более ранние занятия без решения: '
                + ', '.join(f'№{row.course_order_index} «{row.topic or "Без названия"}»' for row in blockers[:4])
                + '. Завершите их или отложите с обоснованием.',
            'no_upcoming_lesson': 'В программе нет существующего следующего незавершённого урока. Добавьте его отдельно, если это действительно нужно.',
        }
        message = messages.get(issue, 'Не удалось однозначно выбрать следующий урок.')
        if request.is_json:
            return jsonify({'success': False, 'error': message, 'issue': issue}), 409
        flash(message, 'warning')
        return redirect(url_for('courses.course_view', course_id=course.course_id))
    if not target:
        abort(409)
    if request.is_json:
        return jsonify({
            'success': True, 'lesson_id': int(target.lesson_id), 'status': target.status,
            'topic': target.topic, 'course_version': int(course.current_version or 1), 'created': False,
        })
    flash(f'Открыт существующий урок «{target.topic}» для подготовки. Новый урок и результаты не создавались.', 'success')
    return redirect(url_for('courses.course_lesson_edit', course_id=course.course_id, lesson_id=target.lesson_id))


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

    is_template = bool(course.is_template or not course.student_id)
    student_id = course.student_id

    # 1. Clean up version snapshots & learning items to prevent FK errors
    LearningTrajectoryVersion.query.filter_by(course_id=course.course_id).delete(synchronize_session=False)
    LearningItem.query.filter_by(course_id=course.course_id).delete(synchronize_session=False)

    modules = TrajectoryModule.query.filter_by(course_id=course.course_id).all()
    module_ids = [m.module_id for m in modules]

    if is_template:
        template_lessons = Lesson.query.filter_by(learning_trajectory_id=course.course_id).all()
        for tl in template_lessons:
            db.session.delete(tl)
        db.session.flush()
        TrajectoryModule.query.filter_by(course_id=course.course_id).delete(synchronize_session=False)
    else:
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
    if is_template or not student_id:
        return redirect(url_for('courses.courses_catalog', tab='templates'))
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


@courses_bp.route('/courses/import', methods=['POST'])
@csrf.exempt
@login_required
def course_import():
    """Импорт структуры курса из JSON-файла или текста."""
    if not _course_viewer_can_manage():
        abort(403)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

    json_data = None
    if request.is_json:
        json_data = request.get_json()
    elif 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        try:
            content = file.read().decode('utf-8')
            json_data = json.loads(content)
        except Exception as e:
            if is_ajax:
                return jsonify({'success': False, 'error': f'Ошибка чтения JSON-файла: {str(e)}'}), 400
            flash(f'Ошибка чтения JSON-файла: {str(e)}', 'error')
            return redirect(url_for('courses.courses_catalog', tab='templates'))
    elif request.form.get('json_content'):
        try:
            json_data = json.loads(request.form.get('json_content'))
        except Exception as e:
            if is_ajax:
                return jsonify({'success': False, 'error': f'Некорректный синтаксис JSON: {str(e)}'}), 400
            flash(f'Некорректный синтаксис JSON: {str(e)}', 'error')
            return redirect(url_for('courses.courses_catalog', tab='templates'))

    if not json_data:
        msg = 'Данные для импорта не предоставлены (загрузите файл .json или вставьте JSON-текст).'
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('courses.courses_catalog', tab='templates'))

    try:
        trajectory, stats = import_course_from_data(json_data, user_id=current_user.id)
    except Exception as e:
        logger.error(f"Error importing course: {e}", exc_info=True)
        db.session.rollback()
        err_msg = str(e)
        if "duplicate key" in err_msg.lower() or "unique constraint" in err_msg.lower():
            err_msg = "Конфликт первичных ключей в базе данных при импорте. Последовательности БД были синхронизированы, повторите попытку."
        elif "foreign key" in err_msg.lower():
            err_msg = "Ошибка связей в базе данных: указан некорректный ID курса или темы."
        elif "not-null" in err_msg.lower() or "null value" in err_msg.lower():
            err_msg = "Ошибка структуры данных: одно из обязательных полей курса не заполнено."
        if is_ajax:
            return jsonify({'success': False, 'error': f'Ошибка при создании курса: {err_msg}'}), 400
        flash(f'Ошибка при создании курса: {err_msg}', 'error')
        return redirect(url_for('courses.courses_catalog', tab='templates'))

    success_msg = f'Курс «{trajectory.title}» успешно импортирован (модулей: {stats["modules"]}, уроков: {stats["lessons"]}, навыков: {stats["skills"]}).'
    if is_ajax:
        return jsonify({
            'success': True,
            'course_id': trajectory.course_id,
            'message': success_msg,
            'redirect_url': url_for('courses.course_view', course_id=trajectory.course_id)
        })

    flash(success_msg, 'success')
    return redirect(url_for('courses.course_view', course_id=trajectory.course_id))


@courses_bp.route('/courses/<int:course_id>/export/json', methods=['GET'])
@login_required
def course_export_json(course_id: int):
    """Экспорт структуры курса в каноничный JSON-формат."""
    course = _guard_course(course_id)
    payload = export_course_to_dict(course)
    data_str = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = secure_filename(f"course_{course.course_id}_{course.title}")[:50] or f"course_{course.course_id}"
    return Response(
        data_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename={filename}.json"}
    )
