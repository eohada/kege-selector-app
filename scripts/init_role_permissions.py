"""
Скрипт для инициализации прав ролей из DEFAULT_ROLE_PERMISSIONS
Запускать на production и sandbox серверах для заполнения прав по умолчанию
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import RolePermission
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, ALL_PERMISSIONS

def init_role_permissions():
    """Инициализирует права ролей из DEFAULT_ROLE_PERMISSIONS"""
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("Инициализация прав ролей из DEFAULT_ROLE_PERMISSIONS")
        print("=" * 60)
        
        try:
            count_before = RolePermission.query.count()
            print(f"Текущее количество записей в RolePermissions: {count_before}")
        except Exception as e:
            print(f"Ошибка при проверке таблицы: {e}")
            print("Создаем таблицу...")
            db.create_all()
        
        print("\nЗаполняем права по умолчанию...")
        added_count = 0
        updated_count = 0
        
        try:
            for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                print(f"\nРоль: {role}")
                print(f"  Права по умолчанию: {len(perms)}")
                
                for perm_name in perms:
                    if perm_name not in ALL_PERMISSIONS:
                        print(f"  ⚠️  Предупреждение: право '{perm_name}' не найдено в ALL_PERMISSIONS, пропускаем")
                        continue
                    
                    existing = RolePermission.query.filter_by(
                        role=role, 
                        permission_name=perm_name
                    ).first()
                    
                    if not existing:
                        rp = RolePermission(
                            role=role, 
                            permission_name=perm_name, 
                            is_enabled=True
                        )
                        db.session.add(rp)
                        added_count += 1
                        print(f"  ✅ Добавлено: {perm_name}")
                    else:
                        if not existing.is_enabled:
                            existing.is_enabled = True
                            updated_count += 1
                            print(f"  🔄 Включено: {perm_name}")
                        else:
                            print(f"  ⏭️  Уже существует: {perm_name}")
            
            db.session.commit()
            print("\n" + "=" * 60)
            print(f"✅ Инициализация завершена!")
            print(f"   Добавлено новых записей: {added_count}")
            print(f"   Обновлено записей: {updated_count}")
            
            count_after = RolePermission.query.count()
            print(f"   Всего записей в БД: {count_after}")
            print("=" * 60)
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Ошибка при инициализации: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        return True

if __name__ == '__main__':
    success = init_role_permissions()
    sys.exit(0 if success else 1)
