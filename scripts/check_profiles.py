#!/usr/bin/env python3
"""Проверка профилей в БД"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, UserProfile

app = create_app()
with app.app_context():
    users_count = User.query.count()
    profiles_count = UserProfile.query.count()
    
    print(f"Пользователей в БД: {users_count}")
    print(f"Профилей в БД: {profiles_count}")
    
    if profiles_count > 0:
        print("\nПрофили:")
        profiles = UserProfile.query.all()
        for profile in profiles:
            user = User.query.get(profile.user_id)
            print(f"  - {profile.first_name} {profile.last_name} (user_id: {profile.user_id}, username: {user.username if user else 'N/A'})")
    else:
        print("\n⚠️  Профилей не найдено!")
        print("\nПользователи без профилей:")
        users = User.query.all()
        for user in users:
            profile = UserProfile.query.filter_by(user_id=user.id).first()
            if not profile:
                print(f"  - {user.username} (id: {user.id}, role: {user.role})")
