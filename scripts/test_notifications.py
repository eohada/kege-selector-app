from app import create_app
from app.models import db, UserNotification, BotAdmin

app = create_app()
with app.app_context():
    # Проверим BotAdmin'ов
    admins = BotAdmin.query.filter_by(is_active=True).all()
    print(f"BotAdmins: {len(admins)}")
    
    # Проверим уведомления
    notifs = UserNotification.query.filter_by(kind='referral_used').order_by(UserNotification.created_at.desc()).limit(3).all()
    for n in notifs:
        print(f"Notification: {n.title}, sent: {n.telegram_sent}")