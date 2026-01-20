from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
import logging

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from app.onboarding import onboarding_bp
from app.models import db, InviteLink, User, UserProfile, Student, moscow_now
from app.auth.rbac_utils import has_permission
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _find_invite_by_token(token: str) -> InviteLink | None:
    token_hash = _hash_token(token)
    invite = InviteLink.query.filter_by(token_hash=token_hash).first()
    if not invite:
        return None
    # extra safety: constant-time compare
    if not hmac.compare_digest(invite.token_hash, token_hash):
        return None
    return invite


@onboarding_bp.route('/onboarding/invites')
@login_required
def invites_list():
    if not has_permission(current_user, 'onboarding.view'):
        abort(403)
    invites = InviteLink.query.order_by(InviteLink.created_at.desc(), InviteLink.invite_id.desc()).limit(200).all()
    return render_template('onboarding_invites.html', invites=invites)


@onboarding_bp.route('/onboarding/invites/create', methods=['POST'])
@login_required
def invites_create():
    if not has_permission(current_user, 'onboarding.invite'):
        abort(403)

    email = (request.form.get('email') or '').strip().lower()
    role = (request.form.get('role') or 'student').strip().lower()
    note = (request.form.get('note') or '').strip() or None
    student_id = request.form.get('student_id', type=int)

    if not email or '@' not in email:
        flash('Укажите корректный email.', 'danger')
        return redirect(url_for('onboarding.invites_list'))

    valid_roles = {'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer', 'creator'}
    if role not in valid_roles:
        role = 'student'

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)

    invite = InviteLink(
        token_hash=token_hash,
        email=email,
        role=role,
        note=note,
        student_id=student_id or None,
        created_by_user_id=current_user.id,
        created_at=moscow_now(),
        expires_at=(moscow_now() + timedelta(days=7)).replace(tzinfo=None),
    )
    db.session.add(invite)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='create_invite', entity='InviteLink', error=str(e))
        flash('Не удалось создать приглашение.', 'danger')
        return redirect(url_for('onboarding.invites_list'))

    try:
        audit_logger.log(
            action='create_invite',
            entity='InviteLink',
            entity_id=invite.invite_id,
            status='success',
            metadata={
                'email': invite.email,
                'role': invite.role,
                'student_id': invite.student_id,
                'expires_at': invite.expires_at.isoformat() if invite.expires_at else None,
            },
        )
    except Exception:
        pass

    accept_url = url_for('onboarding.invite_accept', token=token, _external=True)
    flash(f'Приглашение создано. Ссылка: {accept_url}', 'success')
    return redirect(url_for('onboarding.invites_list'))


@onboarding_bp.route('/invite/<token>', methods=['GET', 'POST'])
def invite_accept(token: str):
    invite = _find_invite_by_token(token)
    if not invite:
        flash('Ссылка приглашения недействительна.', 'danger')
        return render_template('invite_accept.html', invite=None), 404

    # Проверка срока
    try:
        if invite.expires_at and moscow_now().replace(tzinfo=None) > invite.expires_at:
            flash('Срок действия приглашения истёк.', 'danger')
            return render_template('invite_accept.html', invite=None), 410
    except Exception:
        pass

    if invite.used_at:
        flash('Приглашение уже использовано. Войдите в систему.', 'info')
        return redirect(url_for('auth.login'))

    if request.method == 'GET':
        return render_template('invite_accept.html', invite=invite, token=token)

    password = (request.form.get('password') or '')
    password2 = (request.form.get('password2') or '')
    username = (request.form.get('username') or '').strip()

    if len(password) < 8:
        flash('Пароль должен быть не короче 8 символов.', 'danger')
        return render_template('invite_accept.html', invite=invite, token=token), 400
    if password != password2:
        flash('Пароли не совпадают.', 'danger')
        return render_template('invite_accept.html', invite=invite, token=token), 400

    # Username по умолчанию
    if not username:
        username = invite.email.split('@')[0][:40]
    username = username.strip()
    if not username:
        username = f"user{secrets.randbelow(100000)}"

    # Уникальность username/email
    if User.query.filter_by(email=invite.email).first():
        flash('Пользователь с этим email уже существует. Войдите.', 'warning')
        return redirect(url_for('auth.login'))

    base = username
    suffix = 1
    while User.query.filter_by(username=username).first():
        suffix += 1
        username = f"{base}{suffix}"
        if len(username) > 80:
            username = f"{base[:70]}{suffix}"

    user = User(
        username=username,
        email=invite.email,
        password_hash=generate_password_hash(password),
        role=invite.role,
        is_active=True,
        created_at=moscow_now(),
    )
    db.session.add(user)
    db.session.flush()

    # Профиль (минимальный)
    try:
        prof = UserProfile(user_id=user.id, timezone='Europe/Moscow')
        db.session.add(prof)
    except Exception:
        pass

    # Если приглашение связано со Student — проставим email, если пусто
    try:
        if invite.student_id and invite.role == 'student':
            st = Student.query.get(invite.student_id)
            if st and not (st.email or '').strip():
                st.email = invite.email
    except Exception as e:
        logger.warning(f"Failed to link invite to Student: {e}")

    invite.used_at = moscow_now().replace(tzinfo=None)
    invite.used_by_user_id = user.id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Здесь пользователь ещё не залогинен, поэтому обычный audit_logger может не записать событие.
        # Но error лог важен для диагностики (в tester-mode тоже отработает).
        audit_logger.log_error(action='invite_accept', entity='InviteLink', entity_id=invite.invite_id, error=str(e))
        flash('Не удалось создать аккаунт. Попробуйте ещё раз.', 'danger')
        return render_template('invite_accept.html', invite=invite, token=token), 500

    flash('Аккаунт создан. Теперь войдите.', 'success')
    return redirect(url_for('auth.login'))

