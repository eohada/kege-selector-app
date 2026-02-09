"""Скрипт для обновления БД под новый RBAC (RolePermissions, custom_permissions)"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import RolePermission
from sqlalchemy import text
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS

def update_db():
    app = create_app()
    with app.app_context():
        print("Начинаем обновление БД...")
        
        db.create_all()
        print("Tables synchronized (RolePermissions should be created)")
        
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('Users')]
            
            if 'custom_permissions' not in columns:
                print("Adding field 'custom_permissions' to Users table...")
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                
                if 'postgresql' in db_url or 'postgres' in db_url:
                    db.session.execute(text('ALTER TABLE "Users" ADD COLUMN custom_permissions JSON'))
                else:
                    db.session.execute(text('ALTER TABLE Users ADD COLUMN custom_permissions JSON'))
                
                db.session.commit()
                print("Field 'custom_permissions' successfully added")
            else:
                print("Field 'custom_permissions' already exists")
                
        except Exception as e:
            db.session.rollback()
            print(f"Error adding custom_permissions field: {e}")

        print("Filling default permissions...")
        try:
            count = 0
            for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                for perm_name in perms:
                    exists = RolePermission.query.filter_by(role=role, permission_name=perm_name).first()
                    if not exists:
                        rp = RolePermission(role=role, permission_name=perm_name, is_enabled=True)
                        db.session.add(rp)
                        count += 1
            
            db.session.commit()
            print(f"Added {count} default permission records")
        except Exception as e:
            db.session.rollback()
            print(f"Error filling permissions: {e}")

if __name__ == '__main__':
    update_db()
