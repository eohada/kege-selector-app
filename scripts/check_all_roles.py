#!/usr/bin/env python3
"""Проверим всех админов и их роли."""
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
from app.models import db, User, UserRole

app = create_app()

with app.app_context():
    print("=" * 80)
    print("🔍 ВСЕ ПОЛЬЗОВАТЕЛИ И ИХ РОЛИ:")
    print("=" * 80)
    
    all_users = User.query.all()
    print(f"\nВсего пользователей в Users: {len(all_users)}")
    for u in all_users[:20]:
        print(f"  {u.id:3d} | {u.username:20s} | Users.role='{u.role}'")
    
    print("\n" + "=" * 80)
    print("🔍 ВСЕ ЗАПИСИ В USERROLES:")
    print("=" * 80)
    
    all_roles = UserRole.query.all()
    print(f"\nВсего записей в UserRoles: {len(all_roles)}")
    for role in all_roles[:30]:
        user = User.query.get(role.user_id)
        print(f"  User_{role.user_id:3d} ({user.username if user else '???':20s}) -> role='{role.role}'")
    
    print("\n" + "=" * 80)
    print("🔍 АДМИНЫ (БЕЗ ФИЛЬТРА):")
    print("=" * 80)
    
    # Найдем админов по-другому
    admins_by_role = User.query.filter(User.role.in_(['admin', 'creator', 'chief_admin', 'chief_tester'])).all()
    print(f"\nПользователи с admin-like ролью:")
    for u in admins_by_role:
        print(f"  {u.id:3d} | {u.username:20s} | role='{u.role}'")
