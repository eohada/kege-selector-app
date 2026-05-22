#!/usr/bin/env python3
"""
Проверяет таблицу UserRoles напрямую.
"""
from app import create_app
from app.models import db, User, UserRole

app = create_app()
with app.app_context():
    print("=" * 80)
    print("🔍 ПРЯМАЯ ПРОВЕРКА ТАБЛИЦЫ UserRoles")
    print("=" * 80)
    
    # Все записи в UserRoles
    all_roles = UserRole.query.all()
    print(f"\nВсего записей в UserRoles: {len(all_roles)}\n")
    
    for ur in all_roles:
        user = User.query.get(ur.user_id)
        print(f"User ID {ur.user_id} ({user.username if user else 'N/A'}): {ur.role}")
    
    # Специально ищем creator
    print(f"\n{'=' * 80}")
    print("🎯 ПОИСК CREATOR:")
    
    creators = UserRole.query.filter_by(role='creator').all()
    if creators:
        print(f"✅ Найдено {len(creators)} записей с ролью 'creator':")
        for cr in creators:
            user = User.query.get(cr.user_id)
            print(f"   User: {user.username} (ID {user.id})")
    else:
        print("❌ Роць 'creator' не найдена в UserRoles")
    
    # Ищем в основной роли Users.role
    print(f"\n{'=' * 80}")
    print("🎯 ПОИСК CREATOR В Users.role:")
    
    creator_users = User.query.filter_by(role='creator').all()
    if creator_users:
        print(f"✅ Найдено {len(creator_users)} пользователей с основной ролью 'creator':")
        for u in creator_users:
            print(f"   {u.username} (ID {u.id})")
    else:
        print("❌ Creator'ов не найдено в Users.role")
    
    # Все админы
    print(f"\n{'=' * 80}")
    print("🎯 ВСЕ АДМИНИСТРАТОРЫ (из обеих мест):")
    
    admin_ids = set()
    
    # Из основной роли
    basic = User.query.filter(User.role.in_(['creator', 'chief_admin', 'admin'])).all()
    for u in basic:
        admin_ids.add(u.id)
        print(f"   {u.username} (ID {u.id}) - основная роль: {u.role}")
    
    # Из UserRoles
    additional = UserRole.query.filter(UserRole.role.in_(['creator', 'chief_admin', 'admin'])).all()
    for ur in additional:
        if ur.user_id not in admin_ids:
            user = User.query.get(ur.user_id)
            admin_ids.add(ur.user_id)
            print(f"   {user.username} (ID {user.id}) - доп. роль: {ur.role}")
    
    if not admin_ids:
        print("   ❌ Нет администраторов!")
