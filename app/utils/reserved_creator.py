"""Неприкосновенный локальный системный аккаунт создателя."""

from werkzeug.security import generate_password_hash

from app.models import User, UserProfile, UserRole, db


RESERVED_CREATOR_USERNAME = 'creator'
RESERVED_CREATOR_PASSWORD = 'creator123'
RESERVED_CREATOR_EMAIL = 'creator@boostudy.ru'


def ensure_reserved_creator() -> User:
    """Создаёт или восстанавливает системного creator и его базовые связи."""
    user = User.query.filter_by(username=RESERVED_CREATOR_USERNAME).first()
    if user is None:
        user = User(
            username=RESERVED_CREATOR_USERNAME,
            email=RESERVED_CREATOR_EMAIL,
            role='creator',
            password_hash=generate_password_hash(RESERVED_CREATOR_PASSWORD),
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()

    user.username = RESERVED_CREATOR_USERNAME
    user.email = RESERVED_CREATOR_EMAIL
    user.role = 'creator'
    user.is_active = True
    user.password_hash = generate_password_hash(RESERVED_CREATOR_PASSWORD)

    role_link = UserRole.query.filter_by(user_id=user.id, role='creator').first()
    if role_link is None:
        db.session.add(UserRole(user_id=user.id, role='creator'))
    if user.profile is None:
        db.session.add(UserProfile(user_id=user.id, first_name='Creator'))

    db.session.commit()
    return user


def is_reserved_creator(user: User | None) -> bool:
    return bool(user and user.username == RESERVED_CREATOR_USERNAME)
