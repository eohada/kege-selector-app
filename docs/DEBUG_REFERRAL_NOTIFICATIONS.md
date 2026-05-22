# 🔍 ОТЛАДКА СИСТЕМЫ УВЕДОМЛЕНИЙ О РЕФЕРАЛАХ
# 
# Используйте этот файл для диагностики в интерпретаторе Python или через скрипты
#
# ========================================
# ШАГИ ОТЛАДКИ:
# ========================================
#
# 1️⃣  ПРОВЕРЬТЕ, СОЗДАН ЛИ BotAdmin:
# 
#    SELECT * FROM "BotAdmins" WHERE is_active = TRUE;
#    
#    - Если нет результатов: нужно создать запись BotAdmin
#    - Если есть: переход к шагу 2
#
# ========================================
#
# 2️⃣  ПРОВЕРЬТЕ ПРИВЯЗКУ TELEGRAM У АДМИНИСТРАТОРА:
#
#    SELECT 
#      ba.user_id,
#      u.username,
#      up.telegram_chat_id,
#      up.telegram_notifications_enabled,
#      up.tg_notify_referral_used
#    FROM "BotAdmins" ba
#    JOIN "Users" u ON u.id = ba.user_id
#    LEFT JOIN "UserProfiles" up ON up.user_id = ba.user_id
#    WHERE ba.is_active = TRUE;
#
#    Результат должен показать:
#    - telegram_chat_id: НЕ NULL (если NULL - администратор не привязал Telegram)
#    - telegram_notifications_enabled: TRUE (если FALSE - уведомления отключены)
#    - tg_notify_referral_used: TRUE (если FALSE - отключены уведомления о рефералах)
#
# ========================================
#
# 3️⃣  ПРОВЕРЬТЕ, СОЗДАНЫ ЛИ УВЕДОМЛЕНИЯ В БД:
#
#    SELECT 
#      notification_id,
#      user_id,
#      kind,
#      title,
#      telegram_sent,
#      created_at
#    FROM "UserNotifications"
#    WHERE kind = 'referral_used'
#    ORDER BY created_at DESC
#    LIMIT 10;
#
#    Результат должен показать:
#    - Если нет строк: уведомления вообще не создаются (проверьте, что код был выполнен)
#    - Если есть строки с telegram_sent=FALSE: они ждут отправки (нужен urep_bot)
#    - Если все telegram_sent=TRUE: сервис отправил (но может быть ошибка в доставке)
#
# ========================================
#
# 4️⃣  ПРОВЕРЬТЕ СТАТУС urep_bot:
#
#    - Запущен ли процесс? Например: ps aux | grep urep_bot
#    - Работает ли асинхронная задача отправки уведомлений?
#    - Есть ли ошибки в логах?
#
# ========================================
#
# 🟢 КАК СОЗДАТЬ BotAdmin ВРУЧНУЮ:
#
#    from app.models import db, BotAdmin
#    from app import create_app
#
#    app = create_app()
#    with app.app_context():
#        # Предположим, user_id администратора = 1
#        admin = BotAdmin(user_id=1, is_active=True)
#        db.session.add(admin)
#        db.session.commit()
#        print("BotAdmin создан!")
#
# ========================================
#
# 🔗 КАК ПРИВЯЗАТЬ TELEGRAM:
#
#    Администратор должен:
#    1. Зайти в личный кабинет на сайте
#    2. Открыть профиль
#    3. Нажать "Generate Telegram Link Code"
#    4. Скопировать КОД
#    5. Отправить боту: /link КОД
#
#    После этого:
#    - telegram_chat_id будет заполнен
#    - Уведомления начнут приходить
#
# ========================================
