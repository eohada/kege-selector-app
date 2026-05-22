#!/usr/bin/env python3
"""Проверяем реальные роли creator'а в БД."""
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
    creator = User.query.filter_by(username='creator').first()
    
    print("=" * 60)
    print("🔍 CREATOR В USERS TABLE:")
    print(f"  ID: {creator.id}")
    print(f"  Username: {creator.username}")
    print(f"  Users.role: '{creator.role}'")
    
    print("\n🔍 CREATOR В USERROLES TABLE:")
    roles = UserRole.query.filter_by(user_id=creator.id).all()
    if roles:
        for role in roles:
            print(f"  role: '{role.role}'")
    else:
        print("  (нет записей)")
    
    print("\n🔍 ВСЕ ЮЗЕРЫ С РОЛЬЮ 'CREATOR' В USERS:")
    users_creator = User.query.filter_by(role='creator').all()
    for u in users_creator:
        print(f"  {u.username} (ID {u.id})")
    
    print("\n🔍 ВСЕ ЮЗЕРЫ С РОЛЬЮ 'CREATOR' В USERROLES:")
    roles_creator = db.session.query(User).join(UserRole).filter(UserRole.role=='creator').all()
    for u in roles_creator:
        print(f"  {u.username} (ID {u.id})")
