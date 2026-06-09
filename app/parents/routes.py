"""
Маршруты для родителей (Parent role)
Дашборд с информацией о детях, статистикой и финансами
"""
import logging
from flask import render_template, request, jsonify, flash
from flask_login import login_required, current_user

from app.parents import parents_bp
from app.models import db, User, FamilyTie, Student, Lesson, Enrollment, Submission, Assignment, UserProfile
from app.students.stats_service import StatsService
from app.auth.rbac_utils import require_parent, get_user_scope
from core.audit_logger import audit_logger
from core.db_models import moscow_now
from sqlalchemy.orm import joinedload
from app.utils.relationship_scope import get_family_ties_for_parent, get_family_tie_status_label

logger = logging.getLogger(__name__)


def _resolve_student_for_user(student_user):
    """Найти Student для user по user_id."""
    if not student_user:
        return None

    student = Student.query.filter_by(user_id=student_user.id).first()
    return student


@parents_bp.route('/parent/dashboard')
@parents_bp.route('/dashboard')
@require_parent
def parent_dashboard():
    """Дашборд родителя с информацией о детях"""
    try:
        family_ties = get_family_ties_for_parent(current_user.id, include_pending=True)
        confirmed_ties = [tie for tie in family_ties if tie.is_confirmed]
        pending_ties = [tie for tie in family_ties if not tie.is_confirmed]
        
        if not family_ties:
            return render_template('parent_dashboard.html',
                                 children=[],
                                 pending_children=[],
                                 selected_child=None,
                                 selected_child_user=None,
                                 selected_tie=None,
                                 child_stats=None,
                                 upcoming_lessons=[],
                                 recent_lessons=[],
                                 pending_assignments=[],
                                 recent_submissions=[],
                                 financial_data={'lessons_remaining': 0, 'total_paid': 0, 'can_topup': False})
        
        selected_student_id = request.args.get('student_id', type=int)

        selected_tie = next((ft for ft in confirmed_ties if ft.student_id == selected_student_id), None)
        if not selected_tie and confirmed_ties:
            selected_tie = confirmed_ties[0]
            selected_student_id = selected_tie.student_id
        elif not selected_tie:
            selected_student_id = None
        
        children_data = []
        for tie in confirmed_ties:
            student_user = User.query.get(tie.student_id)
            if not student_user:
                continue
            
            student = _resolve_student_for_user(student_user)
            
            student_name = student_user.username
            if student_user.profile:
                if student_user.profile.first_name and student_user.profile.last_name:
                    student_name = f"{student_user.profile.first_name} {student_user.profile.last_name}"
                elif student_user.profile.first_name:
                    student_name = student_user.profile.first_name
            elif student:
                student_name = student.name
            
            children_data.append({
                'user_id': student_user.id,
                'username': student_user.username,
                'student_id': student.student_id if student else None,
                'student_name': student_name,
                'access_level': tie.access_level,
                'is_selected': tie.student_id == selected_student_id,
                'tie_status': get_family_tie_status_label(tie),
                'telegram_linked': bool(student_user.profile and student_user.profile.telegram_chat_id),
            })

        pending_children = []
        for tie in pending_ties:
            student_user = User.query.get(tie.student_id)
            if not student_user:
                continue
            student = _resolve_student_for_user(student_user)
            pending_children.append({
                'user_id': student_user.id,
                'username': student_user.username,
                'student_id': student.student_id if student else None,
                'student_name': student.name if student else student_user.username,
                'access_level': tie.access_level,
                'tie_status': get_family_tie_status_label(tie),
            })
        
        child_stats = None
        upcoming_lessons = []
        recent_lessons = []
        pending_assignments = []
        recent_submissions = []
        
        selected_student = None
        selected_student_user = User.query.get(selected_student_id) if selected_student_id else None
        
        if selected_student_user:
            selected_student = _resolve_student_for_user(selected_student_user)
        
        if selected_student:
            stats = StatsService(selected_student.student_id)
            metrics = stats.get_summary_metrics()
            problem_topics = stats.get_problem_topics(threshold=60)
            
            gpa_data = stats.get_gpa_trend(period_days=7)  # За последнюю неделю
            
            lessons = Lesson.query.filter_by(student_id=selected_student.student_id).all()
            tasks_solved_week = 0
            now_dt = moscow_now().replace(tzinfo=None)
            for lesson in lessons:
                if lesson.lesson_date and (now_dt - lesson.lesson_date).days <= 7:
                    for hw_task in lesson.homework_tasks:
                        if hw_task.submission_correct is not None:
                            tasks_solved_week += 1
            
            ai_summary = {
                'tasks_solved_week': tasks_solved_week,
                'problem_topic': problem_topics[0].name if problem_topics else None,
                'gpa_trend': gpa_data['scores'][-1] if gpa_data['scores'] else None,
                'gpa_forecast': round(gpa_data['scores'][-1] * 0.8, 1) if gpa_data['scores'] else None  # Простой прогноз
            }
            
            child_stats = {
                'metrics': metrics,
                'problem_topics': problem_topics,
                'ai_summary': ai_summary
            }
            
            try:
                all_submissions = Submission.query.join(
                    Assignment, Assignment.assignment_id == Submission.assignment_id
                ).filter(
                    Submission.student_id == selected_student.student_id,
                    Assignment.is_active == True,  # noqa: E712  скрываем архивные
                ).options(
                    joinedload(Submission.assignment)
                ).order_by(Submission.assigned_at.desc()).all()
                
                for sub in all_submissions:
                    if sub.status in ['ASSIGNED', 'IN_PROGRESS', 'RETURNED']:
                        pending_assignments.append(sub)
                    elif sub.status in ['SUBMITTED', 'GRADED'] and len(recent_submissions) < 5:
                        recent_submissions.append(sub)
            except Exception as e:
                logger.error(f"Error loading submissions for parent dashboard: {e}")
            
            from datetime import timedelta
            week_later_dt = now_dt + timedelta(days=7)
            
            upcoming_lessons = Lesson.query.filter(
                Lesson.student_id == selected_student.student_id,
                Lesson.lesson_date >= now_dt,
                Lesson.lesson_date <= week_later_dt
            ).order_by(Lesson.lesson_date.asc()).all()
            
            month_ago_dt = now_dt - timedelta(days=30)
            recent_lessons = Lesson.query.filter(
                Lesson.student_id == selected_student.student_id,
                Lesson.lesson_date >= month_ago_dt,
                Lesson.lesson_date < now_dt
            ).order_by(Lesson.lesson_date.desc()).limit(10).all()
        
        lessons_remaining_val = 0
        try:
            from app.models import UserSubscription
            student_user_id = selected_student.user_id if selected_student else (selected_student_user.id if selected_student_user else None)
            if student_user_id:
                active_sub = UserSubscription.query.filter_by(
                    user_id=student_user_id, status='active'
                ).order_by(UserSubscription.ends_at.desc().nullslast()).first()
                if active_sub and active_sub.lessons_remaining is not None:
                    lessons_remaining_val = active_sub.lessons_remaining
        except Exception as e:
            logger.warning(f"Could not fetch lessons_remaining for parent dashboard: {e}")

        financial_data = {
            'lessons_remaining': lessons_remaining_val,
            'total_paid': 0,
            'can_topup': bool(selected_tie and selected_tie.access_level in ['full', 'financial_only'])
        }
        
        selected_child_name = None
        if selected_student:
            selected_child_name = selected_student.name
        elif selected_student_user:
            if selected_student_user.profile:
                if selected_student_user.profile.first_name and selected_student_user.profile.last_name:
                    selected_child_name = f"{selected_student_user.profile.first_name} {selected_student_user.profile.last_name}"
                elif selected_student_user.profile.first_name:
                    selected_child_name = selected_student_user.profile.first_name
            if not selected_child_name:
                selected_child_name = selected_student_user.username
        
        return render_template('parent_dashboard.html',
                             children=children_data,
                             pending_children=pending_children,
                             selected_child=selected_student,
                             selected_child_user=selected_student_user,
                             selected_tie=selected_tie,
                             selected_child_name=selected_child_name,
                             selected_child_user_id=selected_student_id,
                             child_stats=child_stats,
                             financial_data=financial_data,
                             upcoming_lessons=upcoming_lessons,
                             recent_lessons=recent_lessons,
                             pending_assignments=pending_assignments,
                             recent_submissions=recent_submissions,
                             access_level=selected_tie.access_level if selected_tie else None)
        
    except Exception as e:
        logger.error(f"Error in parent_dashboard: {e}", exc_info=True)
        try:
            flash('Ошибка при загрузке дашборда', 'error')
        except Exception:
            pass
        return render_template('parent_dashboard.html',
                             children=[],
                             pending_children=[],
                             selected_child=None,
                             selected_child_user=None,
                             selected_tie=None,
                             child_stats=None,
                             upcoming_lessons=[],
                             recent_lessons=[],
                             pending_assignments=[],
                             recent_submissions=[],
                             financial_data={'lessons_remaining': 0, 'total_paid': 0, 'can_topup': False})


@parents_bp.route('/api/parent/children', methods=['GET'])
@require_parent
def api_parent_children():
    """API: Список детей родителя"""
    try:
        family_ties = get_family_ties_for_parent(current_user.id, include_pending=True)
        
        children_data = []
        for tie in family_ties:
            student_user = User.query.get(tie.student_id)
            if not student_user:
                continue
            
            student = _resolve_student_for_user(student_user)
            
            children_data.append({
                'user_id': student_user.id,
                'username': student_user.username,
                'student_id': student.student_id if student else None,
                'student_name': student.name if student else student_user.username,
                'access_level': tie.access_level
            })
        
        return jsonify({
            'success': True,
            'children': children_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error in api_parent_children: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
