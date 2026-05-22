#!/usr/bin/env python3
"""
Создает тестовое уведомление о реферале для проверки работы системы.
Запустите на сервере: python create_test_referral_notification.py
"""
import os
import sys

# Настройка пути (если нужно)
# sys.path.insert(0, '/path/to/app')

from app import create_app
from app.models import db, User, UserNotification

def create_test_notification():
    """Создает тестовое уведомление для первого админа системы."""
    app = create_app()
    with app.app_context():
        # Найдем первого админа системы (creator, chief_admin или admin)
        admin = User.query.filter(User.role.in_(['creator', 'chief_admin', 'admin'])).first()
        if not admin:
            print("❌ Нет админов в системе!")
            return False

        print(f"📤 Создаю тестовое уведомление для админа: {admin.username} (ID {admin.id})")

        # Создаем тестовое уведомление
        notif = UserNotification(
            user_id=admin.id,
            kind='referral_used',
            title='🧪 Тестовое уведомление о реферале',
            body='Это тестовое уведомление для проверки работы системы уведомлений.',
            meta={'test': True, 'created_by_script': True},
            telegram_sent=False
        )

        db.session.add(notif)
        db.session.commit()

        print(f"✅ Уведомление создано! ID: {notif.notification_id}")
        print("⏳ Подождите 30-60 секунд и проверьте Telegram...")
        print(f"🔍 Проверьте статус: SELECT telegram_sent FROM \"UserNotifications\" WHERE notification_id = {notif.notification_id};")

        return True

if __name__ == '__main__':
    try:
        success = create_test_notification()
        if success:
            print("\n🎉 Тестовое уведомление отправлено!")
        else:
            print("\n❌ Не удалось создать уведомление")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()