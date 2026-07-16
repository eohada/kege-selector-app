"""
API маршруты
"""
import json
import logging
import os
import secrets
from flask import request, jsonify, url_for
from flask_login import login_required
from sqlalchemy import or_, func

from app.api import api_bp
from app import csrf
from app.models import Student, Lesson, Tasks, db, User, Enrollment, UserProfile, Course
from app.notifications.service import notify_student_and_parents
from app.students.forms import normalize_school_class
from app.utils.student_id_manager import assign_platform_id_if_needed
from app.auth.rbac_utils import get_user_scope
from flask_login import current_user
from core.audit_logger import audit_logger
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _absolute_app_url(path: str) -> str:
    base = (os.environ.get('APP_URL') or '').rstrip('/')
    if base:
        return f'{base}{path}'
    return path

@api_bp.route('/api/audit-log', methods=['POST'])
@login_required
def api_audit_log():
    """API для логирования действий"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        audit_logger.log(
            action=data.get('action', 'unknown'),
            entity=data.get('entity'),
            entity_id=data.get('entity_id'),
            status=data.get('status', 'success'),
            metadata=data.get('metadata', {}),
            duration_ms=data.get('duration_ms')
        )

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f'Error processing audit log: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/telemetry/batch', methods=['POST'])
@csrf.exempt
@login_required
def api_telemetry_batch():
    """Batch telemetry intake for hidden tracking."""
    try:
        data = request.get_json(silent=True) or {}
        events = data.get('events') if isinstance(data, dict) else None
        if not isinstance(events, list):
            return jsonify({'success': False, 'error': 'events must be array'}), 400
        accepted = 0
        event_types = []
        for ev in events[:500]:
            if not isinstance(ev, dict):
                continue
            accepted += 1
            et = ev.get('event_type')
            if et and len(event_types) < 20:
                event_types.append(str(et))
        if accepted:
            audit_logger.log(
                action='telemetry_event',
                entity='Telemetry',
                entity_id=None,
                status='success',
                metadata={
                    'accepted': accepted,
                    'event_types': event_types,
                    'page': request.path,
                },
            )
        return jsonify({'success': True, 'accepted': accepted})
    except Exception as e:
        logger.error(f'Error processing telemetry batch: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/api/user/<int:user_id>/lessons-remaining', methods=['POST'])
@login_required
def api_update_lessons_remaining(user_id):
    """Изменение количества оставшихся уроков"""
    from app.auth.rbac_utils import has_permission
    if not (current_user.is_creator() or current_user.is_tutor() or has_permission(current_user, 'tools.admin')):
        return jsonify({'success': False, 'error': 'Нет прав'}), 403
        
    data = request.get_json() or {}
    delta = data.get('delta')
    set_to = data.get('set_to')
    reason = (data.get('reason') or '').strip()
    
    has_delta = isinstance(delta, int)
    has_set_to = isinstance(set_to, int)
    if not has_delta and not has_set_to:
        return jsonify({'success': False, 'error': 'Укажите новое количество уроков или изменение delta'}), 400
    if not reason:
        return jsonify({'success': False, 'error': 'Укажите причину изменения количества уроков'}), 400
        
    from app.models import UserSubscription
    sub = UserSubscription.query.filter_by(user_id=user_id, status='active').order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc()).first()
    if not sub:
        sub = UserSubscription(
            user_id=user_id,
            plan_id=None,
            status='active',
            started_at=datetime.utcnow(),
            lessons_remaining=0,
        )
        db.session.add(sub)
        db.session.flush()
        
    before = sub.lessons_remaining
    if before is None:
        before = 0
        sub.lessons_remaining = 0
    if has_set_to:
        sub.lessons_remaining = max(0, int(set_to))
    else:
        sub.lessons_remaining += int(delta)
    if sub.lessons_remaining < 0:
        sub.lessons_remaining = 0
        
    try:
        db.session.commit()
        try:
            from app.telegram.notifications import notify_lesson_balance_changed
            notify_lesson_balance_changed(
                student_user_id=int(user_id),
                before=before,
                after=sub.lessons_remaining,
                reason=reason,
                source='manual',
            )
        except Exception:
            logger.warning('Failed to notify lesson balance change for user %s', user_id, exc_info=True)
        return jsonify({'success': True, 'new_count': sub.lessons_remaining})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/api/student/create', methods=['POST'])
@login_required
def api_student_create():
    """API для создания студента"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        school_class_value = normalize_school_class(data.get('school_class'))
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None
        
        student = Student(
            name=data.get('name'),
            platform_id=platform_id,
            target_score=int(data.get('target_score')) if data.get('target_score') else None,
            deadline=data.get('deadline'),
            diagnostic_level=data.get('diagnostic_level'),
            preferences=data.get('preferences'),
            strengths=data.get('strengths'),
            weaknesses=data.get('weaknesses'),
            overall_rating=data.get('overall_rating'),
            description=data.get('description'),
            notes=data.get('notes'),
            category=data.get('category') if data.get('category') else None,
            school_class=school_class_value,
            goal_text=goal_text_value,
            programming_language=programming_language_value
        )
        
        if not platform_id:
            assign_platform_id_if_needed(student)
        
        db.session.add(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student.name} успешно добавлен!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category,
                'school_class': student.school_class,
                'goal_text': student.goal_text,
                'programming_language': student.programming_language
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании студента: {str(e)}'}), 500

@api_bp.route('/api/student/<int:student_id>/update', methods=['POST', 'PUT'])
@login_required
def api_student_update(student_id):
    """API для обновления студента"""
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student and existing_student.student_id != student_id:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        school_class_value = normalize_school_class(data.get('school_class'))
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None
        
        student.name = data.get('name')
        student.platform_id = platform_id
        student.target_score = int(data.get('target_score')) if data.get('target_score') else None
        student.deadline = data.get('deadline')
        student.diagnostic_level = data.get('diagnostic_level')
        student.preferences = data.get('preferences')
        student.strengths = data.get('strengths')
        student.weaknesses = data.get('weaknesses')
        student.overall_rating = data.get('overall_rating')
        student.description = data.get('description')
        student.notes = data.get('notes')
        student.category = data.get('category') if data.get('category') else None
        student.school_class = school_class_value
        student.goal_text = goal_text_value
        student.programming_language = programming_language_value

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Данные ученика {student.name} обновлены!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category,
                'school_class': student.school_class,
                'goal_text': student.goal_text,
                'programming_language': student.programming_language
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при обновлении студента: {str(e)}'}), 500

@api_bp.route('/api/student/<int:student_id>/delete', methods=['POST', 'DELETE'])
@login_required
def api_student_delete(student_id):
    """API для удаления студента"""
    try:
        student = Student.query.get_or_404(student_id)
        student_name = student.name
        db.session.delete(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student_name} удален'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при удалении студента: {str(e)}'}), 500

@api_bp.route('/api/global-search', methods=['GET'])
@login_required
def api_global_search():
    """Глобальный поиск по всем сущностям: ученики, уроки, задания"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({
            'success': False,
            'error': 'Минимум 2 символа для поиска'
        }), 400
    
    results = {
        'students': [],
        'lessons': [],
        'tasks': []
    }
    
    try:
        search_pattern = f'%{query}%'
        filters = [
            Student.name.ilike(search_pattern),
            Student.category.ilike(search_pattern)
        ]
        
        if query.startswith('#'):
            platform_id_query = query[1:].strip()
            if platform_id_query:
                filters.append(Student.platform_id.ilike(f'%{platform_id_query}%'))
        else:
            filters.append(Student.platform_id.ilike(search_pattern))
            try:
                student_id_num = int(query)
                if current_user.id != student_id_num:
                    filters.append(Student.student_id == student_id_num)
            except ValueError:
                pass
        
        students = Student.query.filter(or_(*filters)).limit(10).all()
        
        for student in students:
            results['students'].append({
                'id': student.student_id,
                'name': student.name,
                'category': student.category,
                'platform_id': student.platform_id,
                'is_active': student.is_active,
                'url': url_for('students.student_profile', student_id=student.student_id)
            })
        
        try:
            lesson_id = int(query)
            lessons = Lesson.query.filter(Lesson.lesson_id == lesson_id).limit(5).all()
        except ValueError:
            lessons = Lesson.query.filter(
                or_(
                    Lesson.topic.ilike(search_pattern),
                    Lesson.notes.ilike(search_pattern),
                    Lesson.homework.ilike(search_pattern)
                )
            ).limit(5).all()
        
        for lesson in lessons:
            results['lessons'].append({
                'id': lesson.lesson_id,
                'student_name': lesson.student.name if lesson.student else 'Неизвестно',
                'student_id': lesson.student_id,
                'topic': lesson.topic,
                'date': lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else None,
                'status': lesson.status,
                'url': url_for('lessons.lesson_edit', lesson_id=lesson.lesson_id)
            })
        
        try:
            task_id = int(query)
            tasks = Tasks.query.filter(
                or_(
                    Tasks.task_id == task_id,
                    Tasks.site_task_id == task_id
                )
            ).limit(5).all()
        except ValueError:
            tasks = Tasks.query.filter(
                Tasks.content_html.ilike(search_pattern)
            ).limit(5).all()
        
        for task in tasks:
            results['tasks'].append({
                'id': task.task_id,
                'site_task_id': task.site_task_id,
                'task_number': task.task_number,
                'content_preview': task.content_html[:200] + '...' if task.content_html and len(task.content_html) > 200 else (task.content_html or ''),
                'url': url_for('task_generator.generate_results', task_id=task.task_id)
            })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results['students']) + len(results['lessons']) + len(results['tasks'])
        })
    
    except Exception as e:
        logger.error(f"Ошибка при глобальном поиске: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route('/api/lesson/create', methods=['POST'])
@login_required
def api_lesson_create():
    """API для создания урока"""
    if current_user.is_student():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('student_id'):
            return jsonify({'success': False, 'error': 'ID студента обязателен'}), 400
        if not data.get('lesson_date'):
            return jsonify({'success': False, 'error': 'Дата урока обязательна'}), 400

        try:
            if isinstance(data.get('lesson_date'), str):
                lesson_date = datetime.fromisoformat(data['lesson_date'].replace('Z', '+00:00'))
            else:
                lesson_date = data.get('lesson_date')
        except Exception as e:
            return jsonify({'success': False, 'error': f'Неверный формат даты: {str(e)}'}), 400

        from app.lessons.forms import ensure_introductory_without_homework
        from app.models import MOSCOW_TZ
        
        lesson_type = data.get('lesson_type', 'regular')
        homework_status_value = data.get('homework_status', 'not_assigned')
        homework_value = data.get('homework')
        if lesson_type == 'introductory':
            homework_value = ''
            homework_status_value = 'not_assigned'

        lesson = Lesson(
            student_id=int(data.get('student_id')),
            lesson_type=lesson_type,
            lesson_date=lesson_date,
            duration=int(data.get('duration', 60)),
            status=data.get('status', 'planned'),
            topic=data.get('topic'),
            notes=data.get('notes'),
            homework=homework_value,
            homework_status=homework_status_value
        )
        db.session.add(lesson)
        db.session.commit()

        try:
            student = Student.query.get(lesson.student_id)
            if student and lesson.status == 'planned':
                date_str = lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else ''
                notify_student_and_parents(
                    student,
                    kind='lesson_scheduled',
                    title='Новый урок запланирован',
                    body=(lesson.topic or '').strip() or None,
                    link_url=_absolute_app_url(url_for('lessons.lesson_view', lesson_id=lesson.lesson_id)),
                    meta={'lesson_id': lesson.lesson_id, 'date': date_str, 'topic': lesson.topic or ''},
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson_scheduled notification (api): {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson_scheduled (api_lesson_create): {e}")

        return jsonify({
            'success': True,
            'message': 'Урок успешно создан!',
            'lesson': {
                'id': lesson.lesson_id,
                'student_id': lesson.student_id,
                'lesson_date': lesson.lesson_date.isoformat() if lesson.lesson_date else None,
                'duration': lesson.duration,
                'status': lesson.status
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании урока через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании урока: {str(e)}'}), 500

@api_bp.route('/api/templates', methods=['GET'])
@login_required
def api_templates():
    """API для получения списка шаблонов"""
    try:
        from app.models import TaskTemplate
        
        template_type = request.args.get('type', '')
        category = request.args.get('category', '')
        
        query = TaskTemplate.query.filter_by(is_active=True)
        
        if template_type:
            query = query.filter_by(template_type=template_type)
        
        if category:
            query = query.filter_by(category=category)
        
        templates = query.options(
            db.joinedload(TaskTemplate.template_tasks)
        ).order_by(TaskTemplate.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'templates': [{
                'id': t.template_id,
                'name': t.name,
                'description': t.description,
                'type': t.template_type,
                'category': t.category,
                'task_count': len(t.template_tasks) if t.template_tasks else 0
            } for t in templates]
        })
    except Exception as e:
        logger.error(f'Ошибка при получении шаблонов через API: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500



def _telegram_bot_username() -> str:
    return (os.environ.get('TELEGRAM_BOT_USERNAME') or '').strip().lstrip('@')


@api_bp.route('/api/telegram/link-code', methods=['POST'])
@login_required
def api_telegram_link_code():
    """Генерация одноразового кода и deep-link токена для привязки Telegram аккаунта"""
    try:
        profile = current_user.profile
        if not profile:
            profile = UserProfile(user_id=current_user.id)
            db.session.add(profile)
        
        code = secrets.token_hex(3).upper()  # 6 символов, например A1B2C3
        # До 64 символов для параметра ?start= (Telegram)
        link_token = secrets.token_hex(24)  # 48 hex
        profile.telegram_link_code = code
        profile.telegram_link_code_expires = datetime.utcnow() + timedelta(minutes=15)
        profile.telegram_link_token = link_token
        profile.telegram_link_token_expires = datetime.utcnow() + timedelta(minutes=15)
        
        db.session.commit()

        bot_username = _telegram_bot_username()
        deep_link = (
            f'https://t.me/{bot_username}?start={link_token}' if bot_username else None
        )
        
        return jsonify({
            'success': True,
            'code': code,
            'link_token': link_token,
            'deep_link': deep_link,
            'bot_username': bot_username or None,
            'expires_in': 900  # 15 минут в секундах
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при генерации Telegram кода: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/telegram/link-bot', methods=['POST'])
def api_telegram_link_bot():
    """Привязка Telegram аккаунта ботом по коду /link или по deep-link токену ?start="""
    try:
        expected = (os.environ.get('BOT_INTERNAL_TOKEN') or '').strip()
        provided = (request.headers.get('X-Bot-Token') or '').strip()
        if expected:
            if not secrets.compare_digest(provided, expected):
                return jsonify({'success': False, 'error': 'unauthorized'}), 401
        else:
            logger.warning("BOT_INTERNAL_TOKEN не задан, привязка бота доступна без токена")

        data = request.get_json() or {}
        code = (data.get('code') or '').strip().upper()
        link_token = (data.get('link_token') or data.get('start_payload') or '').strip()
        chat_id = data.get('chat_id')
        telegram_id = (data.get('telegram_id') or '').strip() or None
        force = bool(data.get('force'))

        if chat_id is None:
            return jsonify({'success': False, 'error': 'invalid_payload'}), 400
        if not code and not link_token:
            return jsonify({'success': False, 'error': 'invalid_payload'}), 400

        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'invalid_chat_id'}), 400

        existing = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if existing:
            user = getattr(existing, 'user', None)
            if user and getattr(user, 'is_active', True) and not force:
                return jsonify({'success': False, 'error': 'already_linked'}), 409
            existing.telegram_chat_id = None
            existing.telegram_id = None
            existing.telegram_link_code = None
            existing.telegram_link_code_expires = None
            existing.telegram_link_token = None
            existing.telegram_link_token_expires = None
            db.session.flush()

        profile = None
        if link_token:
            profile = UserProfile.query.filter_by(telegram_link_token=link_token).first()
            if not profile:
                return jsonify({'success': False, 'error': 'invalid_code'}), 404
            if profile.telegram_link_token_expires and profile.telegram_link_token_expires < datetime.utcnow():
                return jsonify({'success': False, 'error': 'expired_code'}), 410
        else:
            profile = UserProfile.query.filter(
                func.upper(UserProfile.telegram_link_code) == code
            ).first()
            if not profile:
                return jsonify({'success': False, 'error': 'invalid_code'}), 404

            if profile.telegram_link_code_expires and profile.telegram_link_code_expires < datetime.utcnow():
                return jsonify({'success': False, 'error': 'expired_code'}), 410

        logger.info("api_telegram_link_bot: linking chat_id=%s (int) to user_id=%s profile_id=%s", chat_id, profile.user_id, profile.profile_id)
        profile.telegram_chat_id = chat_id
        profile.telegram_link_code = None
        profile.telegram_link_code_expires = None
        profile.telegram_link_token = None
        profile.telegram_link_token_expires = None
        if telegram_id and not profile.telegram_id:
            profile.telegram_id = telegram_id

        db.session.commit()

        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при привязке Telegram ботом: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/telegram/unlink', methods=['POST'])
@login_required
def api_telegram_unlink():
    """Отвязка Telegram аккаунта"""
    try:
        profile = current_user.profile
        if not profile:
            return jsonify({'success': False, 'error': 'Профиль не найден'}), 404
        
        if not profile.telegram_chat_id:
            return jsonify({'success': False, 'error': 'Telegram не привязан'}), 400
        
        profile.telegram_chat_id = None
        profile.telegram_link_code = None
        profile.telegram_link_code_expires = None
        profile.telegram_link_token = None
        profile.telegram_link_token_expires = None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Telegram отвязан'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при отвязке Telegram: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/telegram/toggle-notifications', methods=['POST'])
@login_required
def api_telegram_toggle_notifications():
    """Включение/выключение Telegram уведомлений"""
    try:
        profile = current_user.profile
        if not profile:
            return jsonify({'success': False, 'error': 'Профиль не найден'}), 404
        
        data = request.get_json() or {}
        enabled = data.get('enabled', not profile.telegram_notifications_enabled)
        
        profile.telegram_notifications_enabled = bool(enabled)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'enabled': profile.telegram_notifications_enabled
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при переключении уведомлений: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/telegram/status', methods=['GET'])
@login_required
def api_telegram_status():
    """Получение статуса привязки Telegram"""
    try:
        profile = current_user.profile
        
        if not profile:
            return jsonify({
                'success': True,
                'linked': False,
                'notifications_enabled': True
            })
        
        return jsonify({
            'success': True,
            'linked': profile.telegram_chat_id is not None,
            'chat_id': profile.telegram_chat_id,
            'notifications_enabled': profile.telegram_notifications_enabled if profile.telegram_notifications_enabled is not None else True
        })
    except Exception as e:
        logger.error(f'Ошибка при получении статуса Telegram: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/analytics/summary')
@login_required
def api_analytics_summary():
    """
    Рейтинги по узлам знаний и прогноз первичного балла ЕГЭ для текущего пользователя
    (или для ученика, если передан student_id и есть доступ).
    """
    def _safe_isoformat(dt):
        return dt.isoformat() if (dt and hasattr(dt, 'isoformat')) else None

    try:
        from app.analytics import AnalyticsEngine
        from app.analytics.mmr_config import get_mmr_config
        from core.db_models import UserMastery, KnowledgeNode, Subject, Tasks, UserTaskMMR, RematchQueue

        user_id = current_user.id
        student_id = request.args.get('student_id', type=int)
        if student_id:
            scope = get_user_scope(current_user)
            if not scope['can_see_all']:
                # scope['student_ids'] — это User.id учеников; нужны Student.student_id
                allowed_user_ids = scope.get('student_ids') or []
                allowed_student_ids = [s.student_id for s in Student.query.filter(Student.user_id.in_(allowed_user_ids)).all()]
                if student_id not in allowed_student_ids:
                    return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
            student = Student.query.get(student_id)
            if not student or not student.user_id:
                return jsonify({'success': False, 'error': 'Ученик не найден или не привязан к пользователю'}), 404
            user_id = student.user_id

        course_id = request.args.get('course_id', type=int)
        if course_id:
            course = Course.query.get(course_id)
            if course:
                subject = AnalyticsEngine._subject_from_course(course_id)
            else:
                subject = None
        else:
            subject = None
        if not subject:
            subject = Subject.query.filter_by(slug='kege').first()
        if not subject:
            return jsonify({
                'success': True,
                'nodes': [],
                'predicted_primary_score': 0,
                'subject': None,
            })

        all_nodes = KnowledgeNode.query.filter_by(subject_id=subject.id).order_by(KnowledgeNode.id).all()
        node_ids = [n.id for n in all_nodes]
        task_numbers_by_node = {}
        if node_ids:
            for t in Tasks.query.filter(
                Tasks.knowledge_node_id.in_(node_ids),
                Tasks.is_active.is_(True),
            ).all():
                if t.knowledge_node_id and t.knowledge_node_id not in task_numbers_by_node:
                    task_numbers_by_node[t.knowledge_node_id] = t.task_number
        code_to_task = {}
        try:
            data_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'analytics_kege_difficulty.json')
            if os.path.isfile(data_path):
                with open(data_path, 'r', encoding='utf-8') as f:
                    for row in json.load(f):
                        code_to_task[row.get('node_code')] = row.get('task_number')
        except Exception:
            pass
        masteries = {m.node_id: m for m in UserMastery.query.filter_by(user_id=user_id).all()}
        task_mmr = {m.task_type: m for m in UserTaskMMR.query.filter_by(user_id=user_id).all()}
        calibration_cfg = (get_mmr_config() or {}).get('calibration', {})
        first_stage_tasks = int(calibration_cfg.get('first_stage_tasks', 5))
        second_stage_tasks = int(calibration_cfg.get('second_stage_tasks', 10))
        first_stage_multiplier = float(calibration_cfg.get('first_stage_multiplier', 3.0))
        second_stage_multiplier = float(calibration_cfg.get('second_stage_multiplier', 2.0))
        rematch_by_type = {}
        for rq in RematchQueue.query.filter_by(user_id=user_id, status='pending').all():
            rematch_by_type[int(rq.task_type or 0)] = rematch_by_type.get(int(rq.task_type or 0), 0) + 1
        by_node = []
        for n in all_nodes:
            m = masteries.get(n.id)
            task_num = task_numbers_by_node.get(n.id) or code_to_task.get(n.code)
            mmr_for_task = task_mmr.get(int(task_num or 0))
            solved_count = int(mmr_for_task.solved_count or 0) if mmr_for_task else 0
            if solved_count < first_stage_tasks:
                calibration_multiplier = first_stage_multiplier
            elif solved_count < second_stage_tasks:
                calibration_multiplier = second_stage_multiplier
            else:
                calibration_multiplier = 1.0
            calibration_remaining = max(0, second_stage_tasks - solved_count)
            by_node.append({
                'node_code': n.code,
                'node_name': n.name,
                'task_number': task_num,
                'base_rating': n.base_rating,
                'exam_points': n.exam_points,
                'rating': round(m.rating, 1) if m else AnalyticsEngine.INITIAL_RATING,
                'task_mmr': round(mmr_for_task.mmr, 1) if mmr_for_task else AnalyticsEngine.INITIAL_RATING,
                'calibration_multiplier': calibration_multiplier,
                'calibration_remaining': calibration_remaining,
                'calibration_solved_count': solved_count,
                'rematch_pending': int(rematch_by_type.get(int(task_num or 0), 0)),
                'volatility': round(m.volatility, 1) if m else 350.0,
                'streak_days': (m.streak_days or 0) if m else 0,
                'last_practiced_at': _safe_isoformat(m.last_practiced_at if m else None),
            })

        # Fallback: if analytics nodes are not seeded in DB, still build a full 1..27 view
        # from available tasks and per-task MMR so UI is never empty.
        if not by_node:
            task_numbers = []
            tn_rows = (
                db.session.query(Tasks.task_number)
                .filter(Tasks.is_active.is_(True), Tasks.task_number.isnot(None))
                .distinct()
                .order_by(Tasks.task_number.asc())
                .all()
            )
            task_numbers = [int(r[0]) for r in tn_rows if r and r[0] is not None]
            for task_num in task_numbers:
                mmr_for_task = task_mmr.get(int(task_num))
                solved_count = int(mmr_for_task.solved_count or 0) if mmr_for_task else 0
                if solved_count < first_stage_tasks:
                    calibration_multiplier = first_stage_multiplier
                elif solved_count < second_stage_tasks:
                    calibration_multiplier = second_stage_multiplier
                else:
                    calibration_multiplier = 1.0
                calibration_remaining = max(0, second_stage_tasks - solved_count)
                by_node.append({
                    'node_code': f'TASK-{task_num}',
                    'node_name': f'Задание {task_num}',
                    'task_number': task_num,
                    'base_rating': 1500,
                    'exam_points': 1,
                    'rating': round(mmr_for_task.mmr, 1) if mmr_for_task else AnalyticsEngine.INITIAL_RATING,
                    'task_mmr': round(mmr_for_task.mmr, 1) if mmr_for_task else AnalyticsEngine.INITIAL_RATING,
                    'calibration_multiplier': calibration_multiplier,
                    'calibration_remaining': calibration_remaining,
                    'calibration_solved_count': solved_count,
                    'rematch_pending': int(rematch_by_type.get(int(task_num), 0)),
                    'volatility': 350.0,
                    'streak_days': 0,
                    'last_practiced_at': None,
                })
        by_node.sort(key=lambda x: (x['task_number'] is None, x['task_number'] or 0))
        predicted = AnalyticsEngine.predict_exam_score(user_id, subject_id=subject.id, course_id=course_id)

        grading_info = None
        course_slug = None
        if course_id:
            course_obj = Course.query.get(course_id)
            if course_obj:
                course_slug = course_obj.slug
            from app.models import GradingScale
            scales = GradingScale.query.filter_by(course_id=course_id).order_by(GradingScale.min_primary).all()
            if scales:
                grading_info = {
                    'scales': [{'min': s.min_primary, 'max': s.max_primary, 'grade': s.final_grade, 'label': s.label} for s in scales],
                    'max_primary': max(s.max_primary for s in scales),
                }

        return jsonify({
            'success': True,
            'subject': {'id': subject.id, 'slug': subject.slug, 'name': subject.name},
            'nodes': by_node,
            'predicted_primary_score': predicted,
            'grading': grading_info,
            'course_slug': course_slug,
        })
    except Exception as e:
        logger.error(f'Ошибка api/analytics/summary: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/analytics/calibration/reset', methods=['POST'])
@login_required
def api_analytics_calibration_reset():
    """Reset per-task calibration progress without changing current MMR."""
    try:
        from app.analytics import AnalyticsEngine
        from app.analytics.mmr_config import get_mmr_config
        from core.db_models import UserTaskMMR

        data = request.get_json(silent=True) or {}
        student_id = data.get('student_id', None)
        task_number = data.get('task_number', None)
        if student_id is None or task_number is None:
            return jsonify({'success': False, 'error': 'student_id и task_number обязательны'}), 400
        try:
            student_id = int(student_id)
            task_number = int(task_number)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректные student_id/task_number'}), 400

        scope = get_user_scope(current_user)
        if not scope['can_see_all']:
            allowed_user_ids = scope.get('student_ids') or []
            allowed_student_ids = [s.student_id for s in Student.query.filter(Student.user_id.in_(allowed_user_ids)).all()]
            if student_id not in allowed_student_ids:
                return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

        student = Student.query.get(student_id)
        if not student or not student.user_id:
            return jsonify({'success': False, 'error': 'Ученик не найден'}), 404

        user_id = int(student.user_id)
        row = UserTaskMMR.query.filter_by(user_id=user_id, task_type=task_number).first()
        if not row:
            row = UserTaskMMR(
                user_id=user_id,
                task_type=task_number,
                mmr=float(AnalyticsEngine.INITIAL_RATING),
                solved_count=0,
            )
            db.session.add(row)
        else:
            row.solved_count = 0

        db.session.commit()

        calibration_cfg = (get_mmr_config() or {}).get('calibration', {})
        first_stage_multiplier = float(calibration_cfg.get('first_stage_multiplier', 3.0))
        second_stage_tasks = int(calibration_cfg.get('second_stage_tasks', 10))
        return jsonify({
            'success': True,
            'task_number': task_number,
            'calibration_multiplier': first_stage_multiplier,
            'calibration_remaining': second_stage_tasks,
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка /api/analytics/calibration/reset: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/me/timezone', methods=['POST'])
@login_required
def api_me_timezone():
    """Сохранить режим часового пояса и/или IANA; при auto — обновить UserProfiles.timezone из браузера."""
    try:
        from zoneinfo import ZoneInfo
        from app.utils.datetime_utc import effective_timezone_name

        data = request.get_json(silent=True) or {}
        browser = (data.get('browser_iana') or '').strip()
        mode = (data.get('timezone_mode') or '').strip().lower()
        iana = (data.get('timezone_iana') or '').strip()

        if mode in ('auto', 'manual'):
            current_user.timezone_mode = mode
        if iana:
            try:
                ZoneInfo(iana)
                current_user.timezone_iana = iana[:64]
            except Exception:
                return jsonify({'success': False, 'error': 'Некорректный часовой пояс IANA'}), 400
        elif mode == 'auto':
            current_user.timezone_iana = None

        if browser:
            try:
                ZoneInfo(browser)
                prof = UserProfile.query.filter_by(user_id=current_user.id).first()
                if prof:
                    prof.timezone = browser[:50]
            except Exception:
                pass

        db.session.commit()
        return jsonify({'success': True, 'effective': effective_timezone_name(current_user)})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка /api/me/timezone: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/analytics/history')
@login_required
def api_analytics_history():
    """Detailed rating history for student and teacher analytics views."""
    try:
        from core.db_models import AnalyticsEvent, Submission, Answer

        user_id = current_user.id
        student_id = request.args.get('student_id', type=int)
        if student_id:
            scope = get_user_scope(current_user)
            if not scope['can_see_all']:
                allowed_user_ids = scope.get('student_ids') or []
                allowed_student_ids = [s.student_id for s in Student.query.filter(Student.user_id.in_(allowed_user_ids)).all()]
                if student_id not in allowed_student_ids:
                    return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
            student = Student.query.get(student_id)
            if not student or not student.user_id:
                return jsonify({'success': False, 'error': 'Ученик не найден'}), 404
            user_id = student.user_id

        rows = (
            db.session.query(
                AnalyticsEvent,
                Tasks.task_number,
                Submission.assignment_id,
                Answer.assignment_task_id,
            )
            .outerjoin(Tasks, AnalyticsEvent.task_id == Tasks.task_id)
            .outerjoin(Submission, AnalyticsEvent.submission_id == Submission.submission_id)
            .outerjoin(Answer, AnalyticsEvent.answer_id == Answer.answer_id)
            .filter(AnalyticsEvent.user_id == user_id)
            .order_by(AnalyticsEvent.timestamp.desc(), AnalyticsEvent.id.desc())
            .limit(200)
            .all()
        )
        history = []
        for ev, task_number, assignment_id, assignment_task_id in rows:
            flags = ev.behavior_flags or {}
            difficulty = ev.task_difficulty
            if difficulty == 1:
                difficulty_label = 'База'
            elif difficulty == 3:
                difficulty_label = 'Хард'
            else:
                difficulty_label = 'Стандарт'

            sid = int(ev.submission_id) if ev.submission_id is not None else None
            atid = int(assignment_task_id) if assignment_task_id is not None else None
            urls = {'submission': None, 'submission_task': None, 'grade': None}
            if sid is not None:
                base = f'/submissions/{sid}'
                focus = f'?focus_at={atid}' if atid is not None else ''
                urls['submission'] = base
                urls['submission_task'] = f'{base}{focus}' if atid is not None else base
                urls['grade'] = f'{base}/grade{focus}' if atid is not None else f'{base}/grade'

            history.append({
                'event_id': ev.id,
                'timestamp': ev.timestamp.isoformat() if ev.timestamp else None,
                'task_number': int(task_number) if task_number is not None else (int(ev.task_type) if ev.task_type else None),
                'is_correct': bool(ev.is_correct),
                'mmr_delta': round(float(ev.mmr_delta or 0.0), 2),
                'old_rating': round(float(ev.old_rating or 0.0), 2) if ev.old_rating is not None else None,
                'new_rating': round(float(ev.new_rating or 0.0), 2) if ev.new_rating is not None else None,
                'difficulty_label': flags.get('difficulty_label') or difficulty_label,
                'time_spent_sec': ev.time_spent_sec,
                'time_coeff': flags.get('time_coeff'),
                'attempt_coeff': flags.get('attempt_coeff'),
                'calibration_multiplier': flags.get('calibration_multiplier'),
                'time_band': flags.get('time_band'),
                'mode': ev.mode,
                'attempt_no': ev.attempt_no,
                'submission_id': sid,
                'answer_id': int(ev.answer_id) if ev.answer_id is not None else None,
                'task_id': int(ev.task_id) if ev.task_id is not None else None,
                'assignment_id': int(assignment_id) if assignment_id is not None else None,
                'assignment_task_id': atid,
                'urls': urls,
                'rating_comment': flags.get('rating_comment'),
                'teacher_adjusted': bool(flags.get('teacher_adjusted')),
                'mmr_rating_source': 'manual' if flags.get('teacher_adjusted') else 'auto',
            })
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        logger.error(f'Ошибка /api/analytics/history: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def _internal_telegram_token_ok() -> bool:
    secret = (os.environ.get('TELEGRAM_INTERNAL_API_SECRET') or os.environ.get('BOT_INTERNAL_TOKEN') or '').strip()
    if not secret:
        logger.warning('internal telegram: no TELEGRAM_INTERNAL_API_SECRET / BOT_INTERNAL_TOKEN')
        return False
    provided = (request.headers.get('X-Internal-Token') or request.headers.get('X-Bot-Token') or '').strip()
    return secrets.compare_digest(provided, secret)


@api_bp.route('/api/internal/telegram/dispatch', methods=['POST'])
def api_internal_telegram_dispatch():
    """
    Внутренний API: поставить в очередь отправку пользователю в Telegram.
    Заголовок: X-Internal-Token (или X-Bot-Token) = BOT_INTERNAL_TOKEN или TELEGRAM_INTERNAL_API_SECRET.
    """
    if not _internal_telegram_token_ok():
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    event = (data.get('event') or '').strip()
    payload = data.get('payload') or {}
    if event != 'send_to_user':
        return jsonify({'success': False, 'error': 'unknown_event'}), 400
    uid = payload.get('user_id')
    text = (payload.get('text') or '').strip()
    kind = (payload.get('kind') or '').strip() or None
    if uid is None or not text:
        return jsonify({'success': False, 'error': 'invalid_payload'}), 400
    try:
        from app.tasks.telegram_dispatch import telegram_notify_user_task

        telegram_notify_user_task.apply_async(
            args=[int(uid), text, kind],
            retry=False
        )
        return jsonify({'success': True, 'queued': True})
    except Exception as e:
        logger.error('api_internal_telegram_dispatch: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/bug_report', methods=['POST'])
@login_required
def api_bug_report():
    """Сохранение баг-репорта от пользователя платформы"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        description = (data.get('description') or '').strip()
        url_context = (data.get('url_context') or '').strip()

        if not description:
            return jsonify({'success': False, 'error': 'Описание ошибки обязательно'}), 400

        from app.models import PlatformBugReport, UserProfile
        report = PlatformBugReport(
            user_id=current_user.id,
            url_context=url_context[:500] if url_context else None,
            description=description,
            status='new'
        )
        db.session.add(report)
        db.session.commit()

        # Уведомить TG всех создателей/главных администраторов
        try:
            creator_users = User.query.filter(User.role.in_(['creator', 'chief_admin'])).all()
            tg_text = (
                f"🐛 Новый баг-репорт #{report.id}\n"
                f"От: {current_user.username}\n"
            )
            if url_context:
                tg_text += f"Страница: {url_context[:200]}\n"
            tg_text += f"\n{description[:500]}"
            if len(description) > 500:
                tg_text += "..."

            from app.telegram.user_notify import notify_user_by_id
            for cu in creator_users:
                try:
                    notify_user_by_id(cu.id, tg_text, kind='system_errors')
                except Exception:
                    pass
        except Exception as tg_err:
            logger.warning('Bug report TG notify failed: %s', tg_err)

        return jsonify({'success': True, 'message': 'Спасибо! Отчет об ошибке успешно отправлен.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при сохранении баг-репорта: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/bug_reports', methods=['GET'])
@login_required
def api_bug_reports_list():
    """Список всех баг-репортов для создателя/администратора"""
    if not (current_user.is_creator() or current_user.is_admin() or current_user.is_chief_admin()):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    try:
        from app.models import PlatformBugReport
        status_filter = request.args.get('status')
        q = PlatformBugReport.query.order_by(PlatformBugReport.created_at.desc())
        if status_filter and status_filter != 'all':
            q = q.filter(PlatformBugReport.status == status_filter)
        reports = q.limit(200).all()
        result = []
        for r in reports:
            user_info = None
            if r.user:
                user_info = {'id': r.user.id, 'username': r.user.username}
            result.append({
                'id': r.id,
                'user': user_info,
                'url_context': r.url_context,
                'description': r.description,
                'status': r.status,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'updated_at': r.updated_at.isoformat() if r.updated_at else None,
            })
        return jsonify({'success': True, 'reports': result})
    except Exception as e:
        logger.error(f'Ошибка при выборке баг-репортов: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/api/bug_reports/<int:report_id>/status', methods=['POST'])
@login_required
def api_bug_report_set_status(report_id):
    """Смена статуса баг-репорта. Только creator/admin."""
    if not (current_user.is_creator() or current_user.is_admin() or current_user.is_chief_admin()):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    try:
        from app.models import PlatformBugReport
        report = PlatformBugReport.query.get_or_404(report_id)
        data = request.get_json(silent=True) or {}
        new_status = (data.get('status') or '').strip()
        if new_status not in ('new', 'in_progress', 'resolved'):
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        report.status = new_status
        db.session.commit()
        return jsonify({'success': True, 'status': new_status})
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка смены статуса баг-репорта: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
