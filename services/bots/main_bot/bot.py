"""
Telegram бот для трекинга репортов от тестировщиков

Функционал:
- Мониторинг группы по тегам (#BUG, #UIFIX, #FEATURE, #ADM)
- Пересылка репортов в личку админу
- Управление статусами репортов через inline-кнопки
- Отправка обновлений статуса в группу
"""
import os
import logging
from typing import Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from telegram_bot.models import ReportDatabase

log_level = os.getenv('TELEGRAM_BOT_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, log_level, logging.INFO)
)
logger = logging.getLogger(__name__)

TRACKED_TAGS = ['#BUG', '#UIFIX', '#FEATURE', '#ADM']

STATUSES = {
    'new': '🆕 Новый',
    'in_progress': '🔄 В работе',
    'resolved': '✅ Решено',
    'rejected': '❌ Отклонено'
}

db_path = os.getenv('REPORTS_DB_PATH', 'data/reports.db')
db = ReportDatabase(db_path=db_path)


def generate_report_id(group_chat_id: int, message_id: int) -> str:
    """
    Генерация уникального ID репорта (внутренний идентификатор)
    
    Args:
        group_chat_id: ID чата группы
        message_id: ID сообщения
        
    Returns:
        Уникальный идентификатор репорта (для внутреннего использования)
    """
    return f"{group_chat_id}_{message_id}"


def extract_tags(text: str) -> list:
    """
    Извлечение тегов из текста сообщения
    
    Args:
        text: Текст сообщения
        
    Returns:
        Список найденных тегов
    """
    found_tags = []
    text_upper = text.upper()
    
    for tag in TRACKED_TAGS:
        if tag.upper() in text_upper:
            found_tags.append(tag)
    
    return found_tags


def is_main_tester(user_id: int) -> bool:
    """
    Проверка, является ли пользователь главным тестировщиком (первым или вторым)
    
    Args:
        user_id: ID пользователя
        
    Returns:
        True если пользователь главный тестировщик
    """
    main_tester_id = os.getenv('TELEGRAM_MAIN_TESTER_ID')
    if main_tester_id:
        try:
            if int(main_tester_id) == user_id:
                return True
        except ValueError:
            pass
    
    main_tester_id_2 = os.getenv('TELEGRAM_MAIN_TESTER_ID_2')
    if main_tester_id_2:
        try:
            if int(main_tester_id_2) == user_id:
                return True
        except ValueError:
            pass
    
    return False


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик сообщений из группы тестировщиков
    
    Проверяет наличие тегов и пересылает репорты админу
    """
    if update.message:
        message_thread_id = getattr(update.message, 'message_thread_id', None)
        logger.info(f"Получено сообщение: chat_id={update.message.chat.id}, chat_type={update.message.chat.type}, message_id={update.message.message_id}, thread_id={message_thread_id}")
    
    if not update.message:
        return
    
    chat_type = update.message.chat.type
    chat_id = update.message.chat.id
    
    logger.info(f"Получено сообщение: chat_id={chat_id}, chat_type={chat_type}")
    
    if chat_type not in ['group', 'supergroup']:
        logger.info(f"Сообщение проигнорировано: не из группы (тип: {chat_type})")
        return
    
    group_id = os.getenv('TELEGRAM_GROUP_ID')
    if not group_id:
        logger.error("TELEGRAM_GROUP_ID не установлен! Бот не будет обрабатывать сообщения из групп.")
        return
    
    try:
        expected_group_id = int(group_id)
        if chat_id != expected_group_id:
            logger.info(f"Сообщение проигнорировано: не из нужной группы (chat_id={chat_id}, ожидался {expected_group_id})")
            return
        logger.info(f"Сообщение из правильной группы: {chat_id}")
    except ValueError:
        logger.error(f"TELEGRAM_GROUP_ID имеет неверный формат: {group_id}")
        return
    
    message = update.message
    
    text = message.text or message.caption or ""
    
    if message.reply_to_message:
        logger.info(f"Это reply-сообщение на message_id={message.reply_to_message.message_id}")
    
    logger.info(f"Текст сообщения (первые 200 символов): {text[:200]}")
    
    if not text:
        logger.info("Сообщение проигнорировано: нет текста")
        return
    
    tags = extract_tags(text)
    logger.info(f"Найденные теги в сообщении: {tags}")
    
    if not tags:
        logger.info("Сообщение проигнорировано: нет отслеживаемых тегов")
        return
    
    tag = tags[0]
    logger.info(f"Обработка репорта с тегом {tag} из группы {message.chat.id}")
    
    report_id = generate_report_id(message.chat.id, message.message_id)
    logger.debug(f"Сгенерирован report_id: {report_id}")
    
    author = message.from_user
    author_id = author.id
    author_username = author.username
    author_first_name = author.first_name
    
    logger.info(f"Автор сообщения: ID={author_id}, username={author_username}, first_name={author_first_name}")
    
    if is_main_tester(author_id) and tag == '#ADM':
        logger.info(f"Репорт #ADM от главного тестировщика (ID: {author_id}), пропускаем обработку из группы")
        logger.info(f"💡 Главный тестировщик должен отправлять репорты #ADM через личку боту, а не в группу")
        return
    
    logger.info(f"Продолжаем обработку репорта (тег: {tag}, автор: {author_id})")
    
    content = text
    if not content and message.caption:
        content = message.caption
    
    added = db.add_report(
        report_id=report_id,
        group_message_id=message.message_id,
        group_chat_id=message.chat.id,
        author_id=author_id,
        author_username=author_username,
        author_first_name=author_first_name,
        tag=tag,
        content=content
    )
    
    if not added:
        logger.info(f"Репорт {report_id} уже существует, пропускаем")
        return
    
    report_data = db.get_report(report_id)
    numeric_id = report_data.get('numeric_id') or report_data.get('id') if report_data else None
    
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    if not admin_id:
        logger.error("TELEGRAM_ADMIN_ID не установлен в переменных окружения")
        return
    
    try:
        admin_id = int(admin_id)
        logger.debug(f"ID админа: {admin_id}")
    except ValueError:
        logger.error(f"TELEGRAM_ADMIN_ID должен быть числом, получено: {admin_id}")
        return
    
    media_type = ""
    if message.photo:
        media_type = "📷 Фото"
    elif message.video:
        media_type = "🎥 Видео"
    elif message.document:
        media_type = "📄 Документ"
    elif message.audio:
        media_type = "🎵 Аудио"
    elif message.voice:
        media_type = "🎤 Голосовое"
    elif message.video_note:
        media_type = "📹 Видеосообщение"
    elif message.sticker:
        media_type = "😀 Стикер"
    
    media_info = f"\n📎 <b>Тип:</b> {media_type}" if media_type else ""
    display_id = f"#{numeric_id}" if numeric_id else f"<code>{report_id}</code>"
    admin_message = f"""
{tag} <b>Новый репорт</b> {display_id}

👤 <b>Автор:</b> {author_first_name or 'Неизвестно'}
{'@' + author_username if author_username else ''}{media_info}

📝 <b>Содержание:</b>
{content[:500]}{'...' if len(content) > 500 else ''}

🆔 <b>ID:</b> {display_id}
📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 В работе", callback_data=f"status_{report_id}_in_progress"),
            InlineKeyboardButton("✅ Решено", callback_data=f"status_{report_id}_resolved")
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"status_{report_id}_rejected"),
            InlineKeyboardButton("📋 Детали", callback_data=f"details_{report_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if message.photo:
            photo = message.photo[-1]
            sent_message = await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.video:
            sent_message = await context.bot.send_video(
                chat_id=admin_id,
                video=message.video.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.document:
            sent_message = await context.bot.send_document(
                chat_id=admin_id,
                document=message.document.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.audio:
            sent_message = await context.bot.send_audio(
                chat_id=admin_id,
                audio=message.audio.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.voice:
            sent_message = await context.bot.send_voice(
                chat_id=admin_id,
                voice=message.voice.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            sent_message = await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        
        db.update_status(
            report_id=report_id,
            status='new',
            admin_message_id=sent_message.message_id,
            admin_chat_id=admin_id
        )
        
        logger.info(f"Репорт {report_id} отправлен админу {admin_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке репорта админу: {e}", exc_info=True)


async def handle_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатий на кнопки изменения статуса
    
    Обновляет статус репорта и отправляет уведомление в группу
    """
    query = update.callback_query
    logger.info(f"[CALLBACK] Получен callback: {query.data}")
    
    await query.answer()
    
    data = query.data
    
    if not data.startswith('status_'):
        logger.warning(f"[CALLBACK] Неизвестный callback: {data}")
        return
    
    data_without_prefix = data[7:]  # "status_" = 7 символов
    
    found_status = None
    found_status_suffix = None
    
    for status in ['in_progress', 'resolved', 'rejected', 'new']:
        status_suffix = f"_{status}"
        if data_without_prefix.endswith(status_suffix):
            found_status = status
            found_status_suffix = status_suffix
            break
    
    if not found_status:
        logger.error(f"[CALLBACK] Неизвестный статус в callback_data: {data}")
        return
    
    report_id = data_without_prefix[:-len(found_status_suffix)]
    new_status = found_status
    
    logger.info(f"[CALLBACK] Парсинг: data={data}, report_id={report_id}, status={new_status}")
    logger.info(f"[CALLBACK] Обработка: report_id={report_id}, new_status={new_status}")
    
    report = db.get_report(report_id)
    if not report:
        logger.error(f"[CALLBACK] Репорт {report_id} не найден в базе данных")
        await query.edit_message_text("❌ Репорт не найден")
        return
    
    logger.info(f"[CALLBACK] Репорт найден: {report_id}, текущий статус: {report['status']}")
    
    db.update_status(report_id=report_id, status=new_status)
    logger.info(f"[CALLBACK] Статус обновлен в БД: {new_status}")
    
    numeric_id = report.get('numeric_id') or report.get('id', '?')
    
    status_text = STATUSES.get(new_status, new_status)
    status_message = f"""
{report['tag']} <b>Статус обновлен</b> #{numeric_id}

📝 <b>Репорт:</b> {report['content'][:200]}{'...' if len(report['content']) > 200 else ''}

{status_text}

🆔 <b>ID:</b> #{numeric_id}
"""
    
    author_id = report.get('author_id')
    is_from_main_tester = author_id and is_main_tester(author_id)
    
    try:
        if is_from_main_tester:
            main_tester_id = os.getenv('TELEGRAM_MAIN_TESTER_ID')
            main_tester_id_2 = os.getenv('TELEGRAM_MAIN_TESTER_ID_2')
            
            if main_tester_id:
                try:
                    tester_id = int(main_tester_id)
                    if tester_id == author_id:  # Отправляем только тому, кто создал репорт
                        logger.info(f"[CALLBACK] Репорт от главного тестировщика, отправка в личку {tester_id}")
                        sent_message = await context.bot.send_message(
                            chat_id=tester_id,
                            text=status_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"[CALLBACK] Сообщение отправлено главному тестировщику в личку: message_id={sent_message.message_id}")
                except ValueError:
                    logger.error(f"[CALLBACK] TELEGRAM_MAIN_TESTER_ID имеет неверный формат")
                except Exception as e:
                    logger.error(f"[CALLBACK] Ошибка при отправке сообщения главному тестировщику: {e}")
            
            if main_tester_id_2:
                try:
                    tester_id_2 = int(main_tester_id_2)
                    if tester_id_2 == author_id:  # Отправляем только тому, кто создал репорт
                        logger.info(f"[CALLBACK] Репорт от второго главного тестировщика, отправка в личку {tester_id_2}")
                        sent_message = await context.bot.send_message(
                            chat_id=tester_id_2,
                            text=status_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"[CALLBACK] Сообщение отправлено второму главному тестировщику в личку: message_id={sent_message.message_id}")
                except ValueError:
                    logger.error(f"[CALLBACK] TELEGRAM_MAIN_TESTER_ID_2 имеет неверный формат")
                except Exception as e:
                    logger.error(f"[CALLBACK] Ошибка при отправке сообщения второму главному тестировщику: {e}")
            
            if not main_tester_id and not main_tester_id_2:
                logger.warning(f"[CALLBACK] TELEGRAM_MAIN_TESTER_ID и TELEGRAM_MAIN_TESTER_ID_2 не установлены, не могу отправить уведомление")
        else:
            topic_id = os.getenv('TELEGRAM_TOPIC_ID')
            message_thread_id = None
            
            if topic_id:
                try:
                    message_thread_id = int(topic_id)
                    logger.info(f"[CALLBACK] Отправка сообщения в топик {message_thread_id}")
                except ValueError:
                    logger.warning(f"[CALLBACK] TELEGRAM_TOPIC_ID имеет неверный формат: {topic_id}")
            else:
                logger.info(f"[CALLBACK] TELEGRAM_TOPIC_ID не установлен, отправка в основной чат")
            
            send_params = {
                'chat_id': report['group_chat_id'],
                'text': status_message,
                'parse_mode': 'HTML'
            }
            
            if message_thread_id:
                send_params['message_thread_id'] = message_thread_id
                logger.info(f"[CALLBACK] Параметры отправки: chat_id={send_params['chat_id']}, thread_id={message_thread_id}")
            else:
                send_params['reply_to_message_id'] = report['group_message_id']
                logger.info(f"[CALLBACK] Параметры отправки: chat_id={send_params['chat_id']}, без топика, reply_to={report['group_message_id']}")
            
            logger.info(f"[CALLBACK] Отправка сообщения с параметрами: {send_params}")
            sent_message = await context.bot.send_message(**send_params)
            logger.info(f"[CALLBACK] Сообщение отправлено в группу: message_id={sent_message.message_id}")
        
        current_text = query.message.text or query.message.caption or ""
        new_text = current_text + f"\n\n✅ <b>Статус изменен на:</b> {status_text}"
        
        await query.edit_message_text(
            new_text,
            parse_mode='HTML'
        )
        logger.info(f"[CALLBACK] Сообщение в личке админа обновлено")
        
        logger.info(f"[CALLBACK] ✅ Статус репорта {report_id} успешно изменен на {new_status}")
        
    except Exception as e:
        logger.error(f"[CALLBACK] ❌ Ошибка при обновлении статуса: {e}", exc_info=True)
        try:
            await query.edit_message_text("❌ Ошибка при отправке обновления в группу")
        except:
            pass


async def handle_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик кнопки "Детали" - показывает полную информацию о репорте
    """
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if not data.startswith('details_'):
        return
    
    report_id = data.replace('details_', '')
    
    report = db.get_report(report_id)
    if not report:
        await query.edit_message_text("❌ Репорт не найден")
        return
    
    numeric_id = report.get('numeric_id') or report.get('id', '?')
    
    details_message = f"""
{report['tag']} <b>Детали репорта</b> #{numeric_id}

👤 <b>Автор:</b> {report['author_first_name'] or 'Неизвестно'}
{'@' + report['author_username'] if report['author_username'] else ''}

📝 <b>Полное содержание:</b>
{report['content']}

📊 <b>Статус:</b> {STATUSES.get(report['status'], report['status'])}
🆔 <b>ID:</b> #{numeric_id}
📅 <b>Создан:</b> {report['created_at']}
🔄 <b>Обновлен:</b> {report['updated_at']}
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 В работе", callback_data=f"status_{report_id}_in_progress"),
            InlineKeyboardButton("✅ Решено", callback_data=f"status_{report_id}_resolved")
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"status_{report_id}_rejected"),
            InlineKeyboardButton("◀️ Назад", callback_data=f"back_{report_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        details_message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def handle_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик кнопки "Назад" - возвращает к краткому виду репорта
    """
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if not data.startswith('back_'):
        return
    
    report_id = data.replace('back_', '')
    
    report = db.get_report(report_id)
    if not report:
        await query.edit_message_text("❌ Репорт не найден")
        return
    
    numeric_id = report.get('numeric_id') or report.get('id', '?')
    
    admin_message = f"""
{report['tag']} <b>Репорт</b> #{numeric_id}

👤 <b>Автор:</b> {report['author_first_name'] or 'Неизвестно'}
{'@' + report['author_username'] if report['author_username'] else ''}

📝 <b>Содержание:</b>
{report['content'][:500]}{'...' if len(report['content']) > 500 else ''}

🆔 <b>ID:</b> #{numeric_id}
📅 <b>Дата:</b> {report['created_at']}
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 В работе", callback_data=f"status_{report_id}_in_progress"),
            InlineKeyboardButton("✅ Решено", callback_data=f"status_{report_id}_resolved")
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"status_{report_id}_rejected"),
            InlineKeyboardButton("📋 Детали", callback_data=f"details_{report_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        admin_message,
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    logger.info(f"[COMMAND] /start вызван в chat_id={update.message.chat.id}, type={update.message.chat.type}")
    
    user_id = update.effective_user.id
    
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    is_admin = admin_id and str(user_id) == admin_id
    
    is_main_tester_user = is_main_tester(user_id)
    
    message = "🤖 Бот-трекер репортов запущен!\n\n"
    message += "Бот отслеживает сообщения в группе тестировщиков по тегам:\n"
    message += "• #BUG - ошибка функционала\n"
    message += "• #UIFIX - ошибка интерфейса/верстки\n"
    message += "• #FEATURE - предложение по функционалу\n"
    message += "• #ADM - административные вопросы\n\n"
    
    if is_main_tester_user:
        message += "✅ Вы главный тестировщик!\n"
        message += "Вы можете отправлять репорты прямо в эту личку.\n"
        message += "Просто напишите сообщение с тегом (#BUG, #UIFIX, #FEATURE или #ADM).\n\n"
        message += "Репорты будут автоматически отправлены администратору."
    else:
        message += "Репорты автоматически пересылаются админу в личку."
    
    if is_admin:
        message += "\n\n📋 <b>Команды:</b>\n"
        message += "/list - список всех репортов\n"
        message += "/list bug - список репортов #BUG\n"
        message += "/list uifix - список репортов #UIFIX\n"
        message += "/list feature - список репортов #FEATURE\n"
        message += "/list adm - список репортов #ADM\n"
        message += "/stats - статистика репортов"
    
    await update.message.reply_text(message, parse_mode='HTML')


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик сообщений из лички от главного тестировщика
    
    Позволяет главному тестировщику отправлять репорты прямо в личку боту
    """
    if not update.message:
        return
    
    if update.message.chat.type != 'private':
        return
    
    user_id = update.effective_user.id
    
    if not is_main_tester(user_id):
        return
    
    message = update.message
    
    text = message.text or message.caption or ""
    
    if not text:
        return
    
    tags = extract_tags(text)
    
    if not tags:
        return
    
    tag = tags[0]
    logger.info(f"Получен репорт от главного тестировщика с тегом {tag}")
    
    report_id = generate_report_id(message.chat.id, message.message_id)
    
    author = message.from_user
    author_id = author.id
    author_username = author.username
    author_first_name = author.first_name
    
    content = text
    if not content and message.caption:
        content = message.caption
    
    added = db.add_report(
        report_id=report_id,
        group_message_id=message.message_id,
        group_chat_id=message.chat.id,  # ID лички (положительное число)
        author_id=author_id,
        author_username=author_username,
        author_first_name=author_first_name,
        tag=tag,
        content=content
    )
    
    if not added:
        logger.info(f"Репорт {report_id} уже существует, пропускаем")
        await update.message.reply_text("✅ Репорт уже был обработан ранее")
        return
    
    report_data = db.get_report(report_id)
    numeric_id = report_data.get('numeric_id') or report_data.get('id') if report_data else None
    
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    if not admin_id:
        logger.error("TELEGRAM_ADMIN_ID не установлен в переменных окружения")
        await update.message.reply_text("❌ Ошибка: ID администратора не настроен")
        return
    
    try:
        admin_id = int(admin_id)
    except ValueError:
        logger.error(f"TELEGRAM_ADMIN_ID должен быть числом, получено: {admin_id}")
        await update.message.reply_text("❌ Ошибка конфигурации")
        return
    
    media_type = ""
    if message.photo:
        media_type = "📷 Фото"
    elif message.video:
        media_type = "🎥 Видео"
    elif message.document:
        media_type = "📄 Документ"
    elif message.audio:
        media_type = "🎵 Аудио"
    elif message.voice:
        media_type = "🎤 Голосовое"
    elif message.video_note:
        media_type = "📹 Видеосообщение"
    elif message.sticker:
        media_type = "😀 Стикер"
    
    media_info = f"\n📎 <b>Тип:</b> {media_type}" if media_type else ""
    display_id = f"#{numeric_id}" if numeric_id else f"<code>{report_id}</code>"
    admin_message = f"""
{tag} <b>Новый репорт</b> {display_id} <i>(от главного тестировщика)</i>

👤 <b>Автор:</b> {author_first_name or 'Неизвестно'}
{'@' + author_username if author_username else ''}{media_info}

📝 <b>Содержание:</b>
{content[:500]}{'...' if len(content) > 500 else ''}

🆔 <b>ID:</b> {display_id}
📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 В работе", callback_data=f"status_{report_id}_in_progress"),
            InlineKeyboardButton("✅ Решено", callback_data=f"status_{report_id}_resolved")
        ],
        [
            InlineKeyboardButton("❌ Отклонено", callback_data=f"status_{report_id}_rejected"),
            InlineKeyboardButton("📋 Детали", callback_data=f"details_{report_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if message.photo:
            photo = message.photo[-1]
            sent_message = await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.video:
            sent_message = await context.bot.send_video(
                chat_id=admin_id,
                video=message.video.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.document:
            sent_message = await context.bot.send_document(
                chat_id=admin_id,
                document=message.document.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.audio:
            sent_message = await context.bot.send_audio(
                chat_id=admin_id,
                audio=message.audio.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message.voice:
            sent_message = await context.bot.send_voice(
                chat_id=admin_id,
                voice=message.voice.file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            sent_message = await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        
        db.update_status(
            report_id=report_id,
            status='new',
            admin_message_id=sent_message.message_id,
            admin_chat_id=admin_id
        )
        
        await update.message.reply_text(f"✅ Репорт {display_id} отправлен администратору")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке репорта админу: {e}")
        await update.message.reply_text("❌ Ошибка при отправке репорта. Попробуйте позже.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats - показывает статистику репортов"""
    user_id = update.effective_user.id
    
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    if not admin_id or str(user_id) != admin_id:
        await update.message.reply_text("❌ Эта команда доступна только администратору")
        return
    
    if is_main_tester(user_id):
        await update.message.reply_text("❌ Эта команда недоступна")
        return
    
    stats = {}
    for status in STATUSES.keys():
        reports = db.get_reports_by_status(status)
        stats[status] = len(reports)
    
    stats_message = f"""
📊 <b>Статистика репортов</b>

🆕 Новые: {stats.get('new', 0)}
🔄 В работе: {stats.get('in_progress', 0)}
✅ Решено: {stats.get('resolved', 0)}
❌ Отклонено: {stats.get('rejected', 0)}

<b>Всего:</b> {sum(stats.values())}
"""
    
    await update.message.reply_text(stats_message, parse_mode='HTML')


async def list_reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /list - показывает список репортов"""
    user_id = update.effective_user.id
    
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    if not admin_id or str(user_id) != admin_id:
        await update.message.reply_text("❌ Эта команда доступна только администратору")
        return
    
    if is_main_tester(user_id):
        await update.message.reply_text("❌ Эта команда недоступна")
        return
    
    tag_filter = None
    if context.args and len(context.args) > 0:
        tag_arg = context.args[0].upper()
        if tag_arg in ['BUG', 'UIFIX', 'FEATURE', 'ADM']:
            tag_filter = f"#{tag_arg}"
    
    reports = db.get_all_reports(tag=tag_filter, limit=10, offset=0)
    total_count = db.count_reports(tag=tag_filter)
    
    if not reports:
        filter_text = f" с тегом {tag_filter}" if tag_filter else ""
        await update.message.reply_text(f"📋 Репортов{filter_text} не найдено")
        return
    
    filter_text = f" ({tag_filter})" if tag_filter else ""
    message_text = f"📋 <b>Список репортов</b>{filter_text}\n\n"
    
    for report in reports:
        numeric_id = report.get('numeric_id') or report.get('id', '?')
        status_emoji = {
            'new': '🆕',
            'in_progress': '🔄',
            'resolved': '✅',
            'rejected': '❌'
        }.get(report['status'], '❓')
        
        status_text = STATUSES.get(report['status'], report['status'])
        content_preview = report['content'][:60].replace('\n', ' ') + ('...' if len(report['content']) > 60 else '')
        
        message_text += f"{status_emoji} <b>#{numeric_id}</b> {report['tag']} - {status_text}\n"
        message_text += f"   {content_preview}\n\n"
    
    message_text += f"<i>Показано {len(reports)} из {total_count}</i>"
    
    keyboard = []
    
    filter_row = []
    if tag_filter != '#BUG':
        filter_row.append(InlineKeyboardButton("🐛 #BUG", callback_data="list_tag_#BUG"))
    if tag_filter != '#UIFIX':
        filter_row.append(InlineKeyboardButton("🎨 #UIFIX", callback_data="list_tag_#UIFIX"))
    if tag_filter != '#FEATURE':
        filter_row.append(InlineKeyboardButton("✨ #FEATURE", callback_data="list_tag_#FEATURE"))
    if tag_filter != '#ADM':
        filter_row.append(InlineKeyboardButton("⚙️ #ADM", callback_data="list_tag_#ADM"))
    if filter_row:
        keyboard.append(filter_row)
    
    if tag_filter:
        keyboard.append([InlineKeyboardButton("📋 Все репорты", callback_data="list_all")])
    
    view_row = []
    for i, report in enumerate(reports[:5]):
        numeric_id = report.get('numeric_id') or report.get('id', '?')
        view_row.append(InlineKeyboardButton(f"#{numeric_id}", callback_data=f"view_{report['report_id']}"))
        if len(view_row) == 2:  # По 2 кнопки в ряд
            keyboard.append(view_row)
            view_row = []
    if view_row:
        keyboard.append(view_row)
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(message_text, parse_mode='HTML', reply_markup=reply_markup)


async def handle_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для списка репортов"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('list_tag_'):
        tag = data.replace('list_tag_', '')
        reports = db.get_all_reports(tag=tag, limit=10, offset=0)
        total_count = db.count_reports(tag=tag)
        
        if not reports:
            await query.edit_message_text(f"📋 Репортов с тегом {tag} не найдено")
            return
        
        message_text = f"📋 <b>Список репортов</b> ({tag})\n\n"
        
        for report in reports:
            numeric_id = report.get('numeric_id') or report.get('id', '?')
            status_emoji = {
                'new': '🆕',
                'in_progress': '🔄',
                'resolved': '✅',
                'rejected': '❌'
            }.get(report['status'], '❓')
            
            status_text = STATUSES.get(report['status'], report['status'])
            content_preview = report['content'][:60].replace('\n', ' ') + ('...' if len(report['content']) > 60 else '')
            
            message_text += f"{status_emoji} <b>#{numeric_id}</b> {report['tag']} - {status_text}\n"
            message_text += f"   {content_preview}\n\n"
        
        message_text += f"<i>Показано {len(reports)} из {total_count}</i>"
        
        keyboard = []
        filter_row = []
        if tag != '#BUG':
            filter_row.append(InlineKeyboardButton("🐛 #BUG", callback_data="list_tag_#BUG"))
        if tag != '#UIFIX':
            filter_row.append(InlineKeyboardButton("🎨 #UIFIX", callback_data="list_tag_#UIFIX"))
        if tag != '#FEATURE':
            filter_row.append(InlineKeyboardButton("✨ #FEATURE", callback_data="list_tag_#FEATURE"))
        if tag != '#ADM':
            filter_row.append(InlineKeyboardButton("⚙️ #ADM", callback_data="list_tag_#ADM"))
        if filter_row:
            keyboard.append(filter_row)
        
        keyboard.append([InlineKeyboardButton("📋 Все репорты", callback_data="list_all")])
        
        view_row = []
        for i, report in enumerate(reports[:5]):
            numeric_id = report.get('numeric_id') or report.get('id', '?')
            view_row.append(InlineKeyboardButton(f"#{numeric_id}", callback_data=f"view_{report['report_id']}"))
            if len(view_row) == 2:
                keyboard.append(view_row)
                view_row = []
        if view_row:
            keyboard.append(view_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await query.edit_message_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
        
    elif data == 'list_all':
        reports = db.get_all_reports(limit=10, offset=0)
        total_count = db.count_reports()
        
        if not reports:
            await query.edit_message_text("📋 Репортов не найдено")
            return
        
        message_text = f"📋 <b>Список всех репортов</b>\n\n"
        
        for report in reports:
            numeric_id = report.get('numeric_id') or report.get('id', '?')
            status_emoji = {
                'new': '🆕',
                'in_progress': '🔄',
                'resolved': '✅',
                'rejected': '❌'
            }.get(report['status'], '❓')
            
            status_text = STATUSES.get(report['status'], report['status'])
            content_preview = report['content'][:60].replace('\n', ' ') + ('...' if len(report['content']) > 60 else '')
            
            message_text += f"{status_emoji} <b>#{numeric_id}</b> {report['tag']} - {status_text}\n"
            message_text += f"   {content_preview}\n\n"
        
        message_text += f"<i>Показано {len(reports)} из {total_count}</i>"
        
        keyboard = [
            [
                InlineKeyboardButton("🐛 #BUG", callback_data="list_tag_#BUG"),
                InlineKeyboardButton("🎨 #UIFIX", callback_data="list_tag_#UIFIX")
            ],
            [
                InlineKeyboardButton("✨ #FEATURE", callback_data="list_tag_#FEATURE"),
                InlineKeyboardButton("⚙️ #ADM", callback_data="list_tag_#ADM")
            ]
        ]
        
        view_row = []
        for i, report in enumerate(reports[:5]):
            numeric_id = report.get('numeric_id') or report.get('id', '?')
            view_row.append(InlineKeyboardButton(f"#{numeric_id}", callback_data=f"view_{report['report_id']}"))
            if len(view_row) == 2:
                keyboard.append(view_row)
                view_row = []
        if view_row:
            keyboard.append(view_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await query.edit_message_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
    
    elif data.startswith('view_'):
        report_id = data.replace('view_', '')
        report = db.get_report(report_id)
        
        if not report:
            await query.edit_message_text("❌ Репорт не найден")
            return
        
        numeric_id = report.get('numeric_id') or report.get('id', '?')
        status_text = STATUSES.get(report['status'], report['status'])
        
        view_message = f"""
{report['tag']} <b>Репорт #{numeric_id}</b>

👤 <b>Автор:</b> {report['author_first_name'] or 'Неизвестно'}
{'@' + report['author_username'] if report['author_username'] else ''}

📝 <b>Содержание:</b>
{report['content']}

📊 <b>Статус:</b> {status_text}
📅 <b>Создан:</b> {report['created_at']}
🔄 <b>Обновлен:</b> {report['updated_at']}
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 В работе", callback_data=f"status_{report_id}_in_progress"),
                InlineKeyboardButton("✅ Решено", callback_data=f"status_{report_id}_resolved")
            ],
            [
                InlineKeyboardButton("❌ Отклонено", callback_data=f"status_{report_id}_rejected"),
                InlineKeyboardButton("◀️ Назад к списку", callback_data="list_all")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(view_message, parse_mode='HTML', reply_markup=reply_markup)


async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getid - показывает ID чата (для настройки)"""
    chat_id = update.message.chat.id
    chat_type = update.message.chat.type
    chat_title = update.message.chat.title or "Личный чат"
    message_thread_id = getattr(update.message, 'message_thread_id', None)
    
    logger.info(f"[COMMAND] /getid вызван в chat_id={chat_id}, type={chat_type}, thread_id={message_thread_id}")
    
    message = f"""
📋 <b>Информация о чате</b>

🆔 <b>ID чата:</b> <code>{chat_id}</code>
📝 <b>Тип:</b> {chat_type}
🏷️ <b>Название:</b> {chat_title}
{f'🧵 <b>Топик ID:</b> <code>{message_thread_id}</code>' if message_thread_id else ''}

<b>Для настройки бота установите:</b>
<code>TELEGRAM_GROUP_ID="{chat_id}"</code>
"""
    
    await update.message.reply_text(message, parse_mode='HTML')


def main():
    """
    Основная функция запуска бота
    """
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
    
    application = ApplicationBuilder().token(bot_token).build()
    
    async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Временный обработчик для отладки - показывает все входящие сообщения"""
        if update.message:
            message_thread_id = getattr(update.message, 'message_thread_id', None)
            text_preview = (update.message.text or update.message.caption or 'N/A')[:100]
            logger.info(f"[DEBUG] ВСЕ сообщения: chat_id={update.message.chat.id}, type={update.message.chat.type}, thread_id={message_thread_id}, text={text_preview}")
            if message_thread_id:
                logger.warning(f"[DEBUG] ⚠️ Сообщение в топике (thread_id={message_thread_id})! Бот может не получать сообщения из топиков.")
        elif update.edited_message:
            text_preview = (update.edited_message.text or update.edited_message.caption or 'N/A')[:100]
            logger.info(f"[DEBUG] Отредактированное сообщение: chat_id={update.edited_message.chat.id}, type={update.edited_message.chat.type}, text={text_preview}")
        else:
            logger.info(f"[DEBUG] Update без message: update_id={update.update_id}, type={type(update)}")
    
    application.add_handler(CommandHandler("start", start_command), group=0)
    application.add_handler(CommandHandler("stats", stats_command), group=0)
    application.add_handler(CommandHandler("getid", getid_command), group=0)  # Команда для получения ID чата
    application.add_handler(CommandHandler("list", list_reports_command), group=0)  # Команда для просмотра списка репортов
    
    application.add_handler(MessageHandler(filters.ALL, debug_handler), group=1)
    
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message
        ),
        group=2
    )
    
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND,
            handle_group_message
        ),
        group=3
    )
    
    async def debug_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик для отладки всех callback-запросов"""
        if update.callback_query:
            logger.info(f"[CALLBACK DEBUG] Получен callback_query: data={update.callback_query.data}, from_user={update.callback_query.from_user.id}")
    
    application.add_handler(CallbackQueryHandler(debug_callback_handler), group=0)
    
    application.add_handler(CallbackQueryHandler(handle_list_callback, pattern="^(list_|view_)"), group=1)  # Обработчик списка репортов
    application.add_handler(CallbackQueryHandler(handle_status_callback, pattern="^status_"), group=1)
    application.add_handler(CallbackQueryHandler(handle_details_callback, pattern="^details_"), group=1)
    application.add_handler(CallbackQueryHandler(handle_back_callback, pattern="^back_"), group=1)
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_id = os.getenv('TELEGRAM_ADMIN_ID')
    group_id = os.getenv('TELEGRAM_GROUP_ID')
    topic_id = os.getenv('TELEGRAM_TOPIC_ID')
    
    main_tester_id = os.getenv('TELEGRAM_MAIN_TESTER_ID')
    main_tester_id_2 = os.getenv('TELEGRAM_MAIN_TESTER_ID_2')
    
    logger.info("=" * 50)
    logger.info("Настройки бота:")
    logger.info(f"  TELEGRAM_BOT_TOKEN: {'✓ установлен' if bot_token else '✗ НЕ УСТАНОВЛЕН'}")
    logger.info(f"  TELEGRAM_ADMIN_ID: {'✓ установлен' if admin_id else '✗ НЕ УСТАНОВЛЕН'}")
    logger.info(f"  TELEGRAM_GROUP_ID: {'✓ установлен (' + group_id + ')' if group_id else '✗ НЕ УСТАНОВЛЕН (бот не будет обрабатывать сообщения!)'}")
    logger.info(f"  TELEGRAM_TOPIC_ID: {'✓ установлен (' + topic_id + ')' if topic_id else '○ не установлен (ответы будут в основной чат)'}")
    logger.info(f"  TELEGRAM_MAIN_TESTER_ID: {'✓ установлен (' + main_tester_id + ')' if main_tester_id else '○ не установлен (главный тестировщик не настроен)'}")
    logger.info(f"  TELEGRAM_MAIN_TESTER_ID_2: {'✓ установлен (' + main_tester_id_2 + ')' if main_tester_id_2 else '○ не установлен (второй главный тестировщик не настроен)'}")
    logger.info("=" * 50)
    
    if not group_id:
        logger.warning("⚠️  ВНИМАНИЕ: TELEGRAM_GROUP_ID не установлен!")
        logger.warning("   Бот не будет обрабатывать сообщения из групп.")
        logger.warning("   Используйте команду /getid в группе, чтобы узнать ID.")
    
    logger.info("Бот запущен и готов к работе")
    logger.info("Ожидание сообщений...")
    logger.info("")
    logger.info("💡 СОВЕТ: Если бот не видит сообщения из группы:")
    logger.info("   1. Убедитесь, что бот добавлен в группу")
    logger.info("   2. Проверьте, что группа является супергруппой (не обычной группой)")
    logger.info("   3. Если группа использует топики - бот должен быть добавлен в нужный топик")
    logger.info("   4. Попробуйте отправить /start боту в личке - это проверит, работает ли бот вообще")
    logger.info("")
    
    logger.info("Запуск polling...")
    logger.warning("⚠️  ВАЖНО: Если группа использует топики, бот может не получать сообщения!")
    logger.warning("   Решения:")
    logger.warning("   1. Отключить топики в группе (если возможно)")
    logger.warning("   2. Отправлять сообщения в основной топик (General)")
    logger.warning("   3. Использовать обычную группу вместо супергруппы с топиками")
    logger.info("")
    
    async def check_group_info(app):
        """Проверка информации о группе"""
        try:
            bot_info = await app.bot.get_me()
            logger.info(f"Бот: @{bot_info.username} (ID: {bot_info.id})")
            
            group_id = os.getenv('TELEGRAM_GROUP_ID')
            if group_id:
                try:
                    chat = await app.bot.get_chat(int(group_id))
                    logger.info(f"Группа: {chat.title} (ID: {chat.id}, тип: {chat.type})")
                    if hasattr(chat, 'is_forum') and chat.is_forum:
                        logger.warning(f"⚠️  Группа использует топики (forum mode)!")
                        logger.warning(f"   Бот может не получать сообщения из топиков.")
                except Exception as e:
                    logger.error(f"Не удалось получить информацию о группе: {e}")
        except Exception as e:
            logger.error(f"Ошибка при проверке информации: {e}")
    
    application.post_init = check_group_info
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,  # Получаем все типы обновлений
        drop_pending_updates=True,  # Игнорируем старые обновления при запуске
        close_loop=False
    )


if __name__ == '__main__':
    main()