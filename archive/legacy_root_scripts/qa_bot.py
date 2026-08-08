import os
import sys
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Добавляем корневую директорию в PYTHONPATH для корректных импортов
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from core.db_models import db, User

TOKEN = "8992987768:AAGMSCNlX4l4a2IRdWuY54PlM8SprAWea6A"
ADMIN_TG_ID = 854161398

bot = telebot.TeleBot(TOKEN)
app = create_app()

@bot.message_handler(commands=['start'])
def handle_start(message):
    parts = message.text.split()
    if len(parts) > 1:
        key = parts[1]
        with app.app_context():
            user = User.query.filter_by(tg_auth_key=key).first()
            if user:
                user.tg_id = message.chat.id
                db.session.commit()
                
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("✅ Я на связи и готов тестить", callback_data=f"ping_admin_{user.id}"))
                
                bot.send_message(
                    message.chat.id, 
                    "Привет! Я бот QA-отдела BooStudy. Твой аккаунт успешно привязан. Нажми кнопку ниже, чтобы мы убедились, что связь работает.",
                    reply_markup=markup
                )
            else:
                bot.send_message(message.chat.id, "❌ Неверный или устаревший ключ привязки.")
    else:
        bot.send_message(message.chat.id, "Привет! Для привязки аккаунта перейди по специальной ссылке из платформы.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('ping_admin_'))
def handle_ping_admin(call):
    user_id = call.data.split('_')[-1]
    
    with app.app_context():
        user = User.query.get(user_id)
        if user:
            bot.edit_message_text(
                "Супер! Теперь сюда будут прилетать уведомления о твоих багах.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            
            bot.send_message(
                ADMIN_TG_ID, 
                f"🚨 Тестировщик [{user.username}] успешно подключил уведомления и готов к работе!"
            )
            bot.answer_callback_query(call.id)

if __name__ == '__main__':
    print("Бот запущен...")
    bot.polling(none_stop=True)