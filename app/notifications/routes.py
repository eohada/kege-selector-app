from __future__ import annotations

import logging

from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user

from app.notifications import notifications_bp
from app.models import db, UserNotification
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


@notifications_bp.route('/notifications')
@login_required
def notifications_list():
    show_all = (request.args.get('all') or '').strip() in ('1', 'true', 'yes', 'on')
    q = UserNotification.query.filter_by(user_id=current_user.id)
    if not show_all:
        q = q.filter_by(is_read=False)
    notifications = q.order_by(UserNotification.created_at.desc(), UserNotification.notification_id.desc()).limit(200).all()

    unread_count = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return render_template('notifications.html', notifications=notifications, unread_count=unread_count, show_all=show_all)


@notifications_bp.route('/notifications/unread-count')
@login_required
def notifications_unread_count():
    cnt = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'success': True, 'unread_count': cnt})


@notifications_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notification_mark_read(notification_id: int):
    n = UserNotification.query.filter_by(notification_id=notification_id, user_id=current_user.id).first()
    if not n:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    n.is_read = True
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='notification_mark_read', entity='UserNotification', entity_id=notification_id, error=str(e))
        return jsonify({'success': False, 'error': 'DB error'}), 500

    try:
        audit_logger.log(
            action='notification_mark_read',
            entity='UserNotification',
            entity_id=notification_id,
            status='success',
        )
    except Exception:
        pass
    return jsonify({'success': True})


@notifications_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_mark_all_read():
    try:
        updated = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        try:
            audit_logger.log(
                action='notifications_mark_all_read',
                entity='UserNotification',
                status='success',
                metadata={'updated': int(updated or 0)},
            )
        except Exception:
            pass
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to mark all notifications read: {e}", exc_info=True)
        audit_logger.log_error(action='notifications_mark_all_read', entity='UserNotification', error=str(e))
        flash('Не удалось отметить уведомления прочитанными.', 'danger')
        return redirect(url_for('notifications.notifications_list'))

    flash('Уведомления отмечены как прочитанные.', 'success')
    return redirect(url_for('notifications.notifications_list'))

