"""Role and relation helpers shared by Telegram bot and platform admin UI."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models import db, User, UserRole, UserProfile, FamilyTie, Enrollment, UserSubscription
from app.telegram.notifications import send_telegram_message

logger = logging.getLogger(__name__)


ROLE_LABELS = {
    'creator': 'Создатель',
    'chief_admin': 'Старший администратор',
    'admin': 'Администратор',
    'tutor': 'Преподаватель',
    'parent': 'Родитель',
    'student': 'Ученик',
    'content_maker': 'Контент-мейкер',
    'designer': 'Графический дизайнер',
    'tester': 'Тестировщик',
    'chief_tester': 'Старший тестировщик',
}

MAIN_BOT_ROLES = ('creator', 'chief_admin', 'admin', 'tutor', 'parent', 'student', 'designer')
ADMIN_ROLES = {'creator', 'chief_admin', 'admin'}


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(role or '', role or 'Без роли')


def actor_can_assign_role(actor: User, target: User, new_role: str) -> tuple[bool, str]:
    """Return whether actor may set target to new_role."""
    actor_role = actor.role
    old_role = target.role

    if actor.id == target.id and new_role != old_role:
        return False, 'Свою роль менять нельзя. Так случайно можно закрыть себе доступ.'

    if actor_role == 'creator':
        return True, ''

    if actor_role == 'chief_admin':
        if old_role == 'creator' or new_role == 'creator':
            return False, 'Создателя может менять только создатель.'
        if old_role == 'chief_admin' or new_role == 'chief_admin':
            return False, 'Старших администраторов может менять только создатель.'
        return True, ''

    if actor_role == 'admin':
        if old_role in ADMIN_ROLES or new_role in ADMIN_ROLES:
            return False, 'Обычный администратор не может назначать или снимать администраторов.'
        return new_role in {'tutor', 'parent', 'student', 'designer'}, 'Администратор может назначать только преподавателя, родителя, ученика или графического дизайнера.'

    return False, 'Недостаточно прав.'


def set_single_role(user: User, new_role: str) -> str:
    """Set one primary role and mirror it into UserRoles."""
    old_role = user.role
    user.role = new_role
    UserRole.query.filter_by(user_id=user.id).delete()
    db.session.add(UserRole(user_id=user.id, role=new_role))
    return old_role


def user_display_name(user: User | None) -> str:
    if not user:
        return 'Пользователь'
    profile = getattr(user, 'profile', None)
    full_name = ''
    if profile:
        full_name = f'{profile.first_name or ""} {profile.last_name or ""}'.strip()
    return full_name or user.username or f'ID {user.id}'


def relation_summary(user: User, role: str | None = None) -> str:
    """Human-readable attachment text for role-change notifications."""
    role = role or user.role
    if role == 'parent':
        ties = FamilyTie.query.filter_by(parent_id=user.id).all()
        names = [user_display_name(t.student) for t in ties if t.student]
        return 'Прикреплен к ученику: ' + ', '.join(names) if names else 'Пока не прикреплен к ученику.'
    if role == 'tutor':
        enrollments = Enrollment.query.filter_by(tutor_id=user.id, status='active').all()
        names = [user_display_name(e.student) for e in enrollments if e.student]
        return 'Прикреплен к ученикам: ' + ', '.join(names[:8]) if names else 'Пока не прикреплен к ученикам.'
    if role == 'student':
        parents = FamilyTie.query.filter_by(student_id=user.id).all()
        tutors = Enrollment.query.filter_by(student_id=user.id, status='active').all()
        parts = []
        parent_names = [user_display_name(t.parent) for t in parents if t.parent]
        tutor_names = [user_display_name(e.tutor) for e in tutors if e.tutor]
        if parent_names:
            parts.append('родители: ' + ', '.join(parent_names[:5]))
        if tutor_names:
            parts.append('преподаватели: ' + ', '.join(tutor_names[:5]))
        return 'Связи: ' + '; '.join(parts) if parts else 'Пока нет прикрепленных родителей или преподавателей.'
    return 'Профиль не требует отдельного прикрепления.'


def notify_role_changed(user: User, old_role: str, new_role: str, *, actor: User | None = None) -> bool:
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile or not profile.telegram_chat_id:
        return False

    actor_line = f'\nИзменил: {user_display_name(actor)}' if actor else ''
    if new_role == 'designer':
        msg = (
            'Ваша роль в BooStudy изменена.\n\n'
            f'Старая роль: {role_label(old_role)}\n'
            f'Новая роль: {role_label(new_role)}\n'
            'Эта роль - пустышка(пока что), просто наслаждайся своим новым статусом.'
            f'{actor_line}\n\n'
            'Если это ошибка, напишите администратору.'
        )
    else:
        msg = (
            'Ваша роль в BooStudy изменена.\n\n'
            f'Старая роль: {role_label(old_role)}\n'
            f'Новая роль: {role_label(new_role)}\n'
            f'{relation_summary(user, new_role)}'
            f'{actor_line}\n\n'
            'Если это ошибка, напишите администратору.'
        )
    result = send_telegram_message(int(profile.telegram_chat_id), msg, parse_mode=None)
    return bool(result and result.get('ok'))


def notify_relations_changed(user: User, *, actor: User | None = None) -> bool:
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile or not profile.telegram_chat_id:
        return False
    actor_line = f'\nИзменил: {user_display_name(actor)}' if actor else ''
    msg = (
        'Ваши связи в BooStudy обновлены.\n\n'
        f'Роль: {role_label(user.role)}\n'
        f'{relation_summary(user)}'
        f'{actor_line}'
    )
    result = send_telegram_message(int(profile.telegram_chat_id), msg, parse_mode=None)
    return bool(result and result.get('ok'))


@dataclass
class SubscriptionSummary:
    plan_title: str
    status: str
    lessons_remaining: str
    ends_at: str


def subscription_summary_for_user(user_id: int) -> SubscriptionSummary:
    sub = (
        UserSubscription.query
        .filter_by(user_id=user_id)
        .order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc())
        .first()
    )
    if not sub:
        return SubscriptionSummary('Тариф не назначен', 'нет активной записи', 'не указано', 'не указано')
    plan_title = sub.plan.title if sub.plan else 'Без названия'
    lessons = 'без лимита' if sub.lessons_remaining is None else str(sub.lessons_remaining)
    ends = sub.ends_at.strftime('%d.%m.%Y') if sub.ends_at else 'не указано'
    return SubscriptionSummary(plan_title, sub.status or 'не указан', lessons, ends)
