#!/usr/bin/env python3
"""
Скрипт для удаления пользователя
Использование: python scripts/delete_user.py <username>
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from core.db_models import User

def delete_user(username):
    """Удаляет пользователя по логину"""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        
        if not user:
            print(f"❌ Пользователь '{username}' не найден")
            return
        
        user_id = user.id
        user_role = user.role
        db.session.delete(user)
        db.session.commit()
        
        print(f"✅ Пользователь '{username}' (ID: {user_id}, роль: {user_role}) успешно удален")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python scripts/delete_user.py <username>")
        print("Пример: python scripts/delete_user.py tester")
        sys.exit(1)
    
    username = sys.argv[1]
    delete_user(username)

