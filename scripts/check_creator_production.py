#!/usr/bin/env python3
"""Проверим что происходит с creator'ом в production."""
import os, sys
root = os.path.abspath('.')
sys.path.insert(0, root)
os.chdir(root)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(root, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
except ImportError:
    pass

from app import create_app
from app.models import db, User, UserRole, UserProfile

app = create_app()

with app.app_context():
    print("=" * 80)
    print("🔍 ПРОВЕРКА CREATOR'А В PRODUCTION БД")
    print("=" * 80)

    # Найдем creator'а
    creator = User.query.filter_by(username='creator').first()
    if not creator:
        print("❌ CREATOR НЕ НАЙДЕН!")
        sys.exit(1)

    print(f"✅ Creator найден: ID {creator.id}, username '{creator.username}'")
    print(f"   Users.role: '{creator.role}'")

    # Проверим его роли в UserRoles
    roles = UserRole.query.filter_by(user_id=creator.id).all()
    print(f"   Ролей в UserRoles: {len(roles)}")
    for role in roles:
        print(f"   - role: '{role.role}'")

    # Проверим профиль
    profile = UserProfile.query.filter_by(user_id=creator.id).first()
    if profile:
        print(f"   Профиль: ✅ найден")
        print(f"   Telegram chat_id: {profile.telegram_chat_id}")
        print(f"   Telegram notifications: {getattr(profile, 'telegram_notifications_enabled', 'N/A')}")
        print(f"   Referral notifications: {getattr(profile, 'tg_notify_referral_used', 'N/A')}")
    else:
        print(f"   Профиль: ❌ НЕ НАЙДЕН")

    # Проверим логику поиска админов как в routes.py
    print("\n" + "=" * 80)
    print("🔍 ТЕСТИРОВАНИЕ ЛОГИКИ ПОИСКА АДМИНОВ")
    print("=" * 80)

    admin_roles = ['creator', 'chief_admin', 'admin', 'chief_tester']
    admin_users_set = set()

    # Сначала проверим основную роль
    basic_admins = User.query.filter(User.role.in_(admin_roles)).all()
    print(f"Админы по основной роли (Users.role): {len(basic_admins)}")
    for admin in basic_admins:
        admin_users_set.add(admin.id)
        print(f"  - {admin.username} (ID {admin.id}, role='{admin.role}')")

    # Затем проверим дополнительные роли
    role_admins = db.session.query(User).join(UserRole).filter(
        UserRole.role.in_(admin_roles)
    ).all()
    print(f"Админы по дополнительным ролям (UserRoles): {len(role_admins)}")
    for admin in role_admins:
        admin_users_set.add(admin.id)
        print(f"  - {admin.username} (ID {admin.id})")

    print(f"\nИтого уникальных админов: {len(admin_users_set)}")
    print(f"IDs: {sorted(admin_users_set)}")

    # Проверим creator'а в списке
    if creator.id in admin_users_set:
        print(f"✅ CREATOR (ID {creator.id}) ПОПАДАЕТ В СПИСОК АДМИНОВ")
    else:
        print(f"❌ CREATOR (ID {creator.id}) НЕ ПОПАДАЕТ В СПИСОК АДМИНОВ!")

    print("\n" + "=" * 80)
    print("🔍 ПРОВЕРКА ВСЕХ ПОЛЬЗОВАТЕЛЕЙ С АДМИН-РОЛЯМИ")
    print("=" * 80)

    all_admins = User.query.filter(User.role.in_(admin_roles)).all()
    print(f"Все пользователи с админ-ролями: {len(all_admins)}")
    for u in all_admins:
        print(f"  {u.id:3d} | {u.username:20s} | role='{u.role}'")