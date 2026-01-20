"""
Маршруты для родителей (Parent role)
Дашборд с информацией о детях, статистикой и финансами
"""
import logging
from flask import render_template, request, jsonify, flash
from flask_login import login_required, current_user

from app.parents import parents_bp
from app.models import db, User, FamilyTie, Student, Lesson, Enrollment, Submission, Assignment
from app.students.stats_service import StatsService
from app.auth.rbac_utils import require_parent, get_user_scope
from core.audit_logger import audit_logger
from core.db_models import moscow_now
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


@parents_bp.route('/parent/dashboard')
@require_parent
def parent_dashboard():
    """Дашборд родителя с информацией о детях"""
    try:
        # Получаем всех детей родителя.
        # В проде подтверждение связи может быть не настроено/не проставлено,
        # из-за чего родитель "не видит" уже привязанных детей.
        family_ties = FamilyTie.query.filter_by(parent_id=current_user.id).all()
        
        if not family_ties:
            # Нет привязанных детей
            return render_template('parent_dashboard.html',
                                 children=[],
                                 selected_child=None,
                                 child_stats=None,
                                 upcoming_lessons=[],
                                 recent_lessons=[])
        
        # Получаем ID выбранного ребенка из параметра
        selected_student_id = request.args.get('student_id', type=int)
        
        # Если не указан, берем первого ребенка
        if not selected_student_id:
            selected_student_id = family_ties[0].student_id
        
        # Проверяем, что выбранный ребенок действительно принадлежит родителю
        selected_tie = next((ft for ft in family_ties if ft.student_id == selected_student_id), None)
        if not selected_tie:
            selected_student_id = family_ties[0].student_id
            selected_tie = family_ties[0]
        
        # Собираем информацию о детях
        children_data = []
        for tie in family_ties:
            student_user = User.query.get(tie.student_id)
            if not student_user:
                continue
            
            # Находим связанного Student (по email)
            # В будущем можно добавить прямую связь user_id в Student
            student = None
            if student_user.email:
                student = Student.query.filter_by(email=student_user.email).first()
            
            # Формируем имя для отображения
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
                'is_selected': tie.student_id == selected_student_id
            })
        
        # Получаем статистику для выбранного ребенка
        child_stats = None
        upcoming_lessons = []
        recent_lessons = []
        pending_assignments = []
        recent_submissions = []
        
        selected_student = None
        selected_student_user = User.query.get(selected_student_id)
        
        # Находим связанного Student для выбранного User
        if selected_student_user:
            if selected_student_user.email:
                selected_student = Student.query.filter_by(email=selected_student_user.email).first()
        
        if selected_student:
            # Статистика через StatsService
            stats = StatsService(selected_student.student_id)
            metrics = stats.get_summary_metrics()
            problem_topics = stats.get_problem_topics(threshold=60)
            
            # Получаем GPA тренд для AI Summary
            gpa_data = stats.get_gpa_trend(period_days=7)  # За последнюю неделю
            
            # Подсчитываем решенные задачи за неделю
            lessons = Lesson.query.filter_by(student_id=selected_student.student_id).all()
            tasks_solved_week = 0
            # Важно: Lesson.lesson_date хранится как naive datetime (MSK), а moscow_now() timezone-aware.
            # Приводим "сейчас" к naive, иначе будет TypeError и 500.
            now_dt = moscow_now().replace(tzinfo=None)
            for lesson in lessons:
                # lesson.lesson_date обычно datetime; сравниваем datetime с datetime (иначе TypeError и 500)
                if lesson.lesson_date and (now_dt - lesson.lesson_date).days <= 7:
                    for hw_task in lesson.homework_tasks:
                        if hw_task.submission_correct is not None:
                            tasks_solved_week += 1
            
            # Формируем AI Summary
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
            
            # Загружаем задания (Assignments)
            try:
                all_submissions = Submission.query.filter(
                    Submission.student_id == selected_student.student_id
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
            
            # Предстоящие уроки (ближайшие 7 дней)
            from datetime import timedelta
            # повторно используем naive now_dt для корректных сравнений с Lesson.lesson_date
            week_later_dt = now_dt + timedelta(days=7)
            
            upcoming_lessons = Lesson.query.filter(
                Lesson.student_id == selected_student.student_id,
                Lesson.lesson_date >= now_dt,
                Lesson.lesson_date <= week_later_dt
            ).order_by(Lesson.lesson_date.asc()).all()
            
            # Последние уроки (за последние 30 дней)
            month_ago_dt = now_dt - timedelta(days=30)
            recent_lessons = Lesson.query.filter(
                Lesson.student_id == selected_student.student_id,
                Lesson.lesson_date >= month_ago_dt,
                Lesson.lesson_date < now_dt
            ).order_by(Lesson.lesson_date.desc()).limit(10).all()
        
        # Финансы (пока заглушка - нужно будет добавить модель для баланса)
        # Можно использовать количество активных enrollments как "оплаченные уроки"
        financial_data = {
            'lessons_remaining': 0,  # TODO: реализовать систему баланса
            'total_paid': 0,
            'can_topup': selected_tie.access_level in ['full', 'financial_only']
        }
        
        # Формируем имя выбранного ребенка
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
                             selected_child=selected_student,
                             selected_child_name=selected_child_name,
                             selected_child_user_id=selected_student_id,
                             child_stats=child_stats,
                             financial_data=financial_data,
                             upcoming_lessons=upcoming_lessons,
                             recent_lessons=recent_lessons,
                             pending_assignments=pending_assignments,
                             recent_submissions=recent_submissions,
                             access_level=selected_tie.access_level)
        
    except Exception as e:
        logger.error(f"Error in parent_dashboard: {e}", exc_info=True)
        try:
            flash('Ошибка при загрузке дашборда', 'error')
        except Exception:
            pass
        return render_template('parent_dashboard.html',
                             children=[],
                             selected_child=None,
                             child_stats=None,
                             upcoming_lessons=[],
                             recent_lessons=[],
                             pending_assignments=[],
                             recent_submissions=[])


@parents_bp.route('/api/parent/children', methods=['GET'])
@require_parent
def api_parent_children():
    """API: Список детей родителя"""
    try:
        family_ties = FamilyTie.query.filter_by(parent_id=current_user.id).all()
        
        children_data = []
        for tie in family_ties:
            student_user = User.query.get(tie.student_id)
            if not student_user:
                continue
            
            # Находим связанного Student
            student = None
            if student_user.email:
                student = Student.query.filter_by(email=student_user.email).first()
            
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
