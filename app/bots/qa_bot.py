import logging
import os
from flask import current_app
from core.db_models import db, User, QATestCase, BugReport, TelegramStartLead, moscow_now
from app.services.telegram_notifications import send_telegram_message

logger = logging.getLogger(__name__)

ALLOWED_QA_ROLES = {'tester', 'chief_tester', 'admin', 'creator', 'chief_admin', 'tutor', 'teacher'}

# In-memory FSM state for wizard interactions (chat_id -> state_dict)
QA_FSM_STATE = {}

def _get_app_url():
    return (os.environ.get('TELEGRAM_WEBHOOK_BASE_URL') or os.environ.get('APP_URL') or 'https://boostudy.ru').rstrip('/')

def get_qa_keyboard(user: User = None):
    app_url = _get_app_url()
    is_creator = user and (user.is_creator() or user.role in ('creator', 'chief_admin'))
    
    if is_creator:
        return {
            "keyboard": [
                [{"text": "📱 Входящие лиды & Привязка"}, {"text": "👥 Список Тестировщиков"}],
                [{"text": "➕ Создать новый Тест"}, {"text": "📋 Управление Тестами"}],
                [{"text": "🎯 Назначить Тесты"}, {"text": "📢 Рассылка Тестерам"}],
                [{"text": "📊 Статистика QA"}, {"text": "🛠️ Панель Управления QA", "web_app": {"url": f"{app_url}/admin/qa/tests"}}]
            ],
            "resize_keyboard": True
        }

    return {
        "keyboard": [
            [{"text": "👤 Мой профиль"}, {"text": "📋 Мои Тесты", "web_app": {"url": f"{app_url}/tma/qa/checklist"}}],
            [{"text": "📂 Категории Тестов"}, {"text": "🐞 Мои Баг-Репорты"}],
            [{"text": "📊 Статистика QA"}]
        ],
        "resize_keyboard": True
    }

def reply_qa_bot(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    return send_telegram_message(chat_id, text, reply_markup=reply_markup, bot_type='qa')

def format_bug_report_card(bug: BugReport) -> tuple[str, dict]:
    title = getattr(bug, 'title', None) or f"Баг #{bug.id}"
    severity = getattr(bug, 'severity', 'MAJOR')
    status = bug.status or 'NEW'
    step = getattr(bug, 'step_failed', None) or '—'
    
    text = (
        f"🐛 <b>Баг-Репорт #{bug.id}</b>\n\n"
        f"📌 <b>Название:</b> {title}\n"
        f"⚠️ <b>Важность:</b> {severity}\n"
        f"📊 <b>Текущий статус:</b> {status}\n"
        f"👣 <b>Шаг сбоя:</b> {step}\n"
    )

    inline_keyboard = [
        [
            {"text": "👨‍💻 В работу", "callback_data": f"qa_status:in_progress:{bug.id}"},
            {"text": "✅ Исправлено", "callback_data": f"qa_status:resolved:{bug.id}"},
            {"text": "🚫 Отклонить", "callback_data": f"qa_status:rejected:{bug.id}"}
        ]
    ]

    return text, {"inline_keyboard": inline_keyboard}

def process_qa_bot_update(update: dict) -> dict:
    """Processes updates for QA & Tester Bot (@boostudy_qa_bot / @bstd_ts_bot)."""
    if not update:
        return {"ok": True, "status": "ok"}

    # 1. Handle Callback Query (Inline buttons)
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb.get("id")
        cb_data = cb.get("data") or ""
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        from_user_id = cb.get("from", {}).get("id")

        user = User.query.filter(
            (User.telegram_id == from_user_id) | 
            (User.telegram_chat_id == chat_id)
        ).first()

        user_role = (user.role or 'student').lower() if user else None
        if not user or user_role not in ALLOWED_QA_ROLES:
            return {
                "ok": True,
                "status": "ok",
                "method": "answerCallbackQuery",
                "callback_query_id": cb_id,
                "text": "🔒 Доступ запрещен. Необходимы права тестировщика.",
                "show_alert": True
            }

        kb = get_qa_keyboard(user)

        # A. Bug Report Status Update
        if cb_data.startswith("qa_status:"):
            parts = cb_data.split(":")
            if len(parts) == 3:
                action = parts[1]
                report_id = int(parts[2])

                new_status = {"in_progress": "IN_PROGRESS", "resolved": "RESOLVED", "rejected": "REJECTED"}.get(action, "IN_PROGRESS")
                bug = BugReport.query.get(report_id)
                if bug:
                    bug.status = new_status
                    db.session.commit()

                    if bug.reporter and bug.reporter.telegram_chat_id:
                        status_ru = {"IN_PROGRESS": "В работе", "RESOLVED": "Исправлено", "REJECTED": "Отклонено"}.get(new_status, new_status)
                        send_telegram_message(
                            bug.reporter.telegram_chat_id,
                            f"🔔 <b>Статус вашего баг-репорта #{bug.id} изменен!</b>\nНовый статус: <b>{status_ru}</b>",
                            bot_type='qa'
                        )

                    return {
                        "ok": True, "status": "ok", "method": "answerCallbackQuery",
                        "callback_query_id": cb_id, "text": f"Статус обновлен на {new_status}"
                    }

        # B. Interactive Lead Binding (Step 1: Choose Account to bind to Chat ID)
        if cb_data.startswith("bind_lead:"):
            target_cid = int(cb_data.split(":")[1])
            users_list = User.query.filter(User.role.in_(['tester', 'chief_tester', 'admin', 'student', 'creator'])).all()
            
            inline_rows = []
            for u in users_list:
                status_icon = "🟢" if (u.telegram_chat_id == target_cid or u.telegram_id == target_cid) else "👤"
                inline_rows.append([{"text": f"{status_icon} {u.username} ({u.role.upper()})", "callback_data": f"do_bind:{u.id}:{target_cid}"}])
            inline_rows.append([{"text": "➕ Создать быстро аккаунт Тестировщика", "callback_data": f"create_tester_user:{target_cid}"}])
            
            reply_qa_bot(chat_id, f"🔗 <b>Выберите аккаунт платформы для привязки к Telegram Chat ID <code>{target_cid}</code>:</b>", {"inline_keyboard": inline_rows})
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Выберите пользователя"}

        # C. Confirm Lead Binding Execution
        if cb_data.startswith("do_bind:"):
            parts = cb_data.split(":")
            u_id, target_cid = int(parts[1]), int(parts[2])
            target_u = User.query.get(u_id)
            if target_u:
                target_u.telegram_chat_id = target_cid
                target_u.telegram_id = target_cid
                db.session.commit()
                reply_qa_bot(chat_id, f"✅ Аккаунт <b>{target_u.username}</b> (#<b>{target_u.id}</b>) успешно привязан к TG Chat ID <code>{target_cid}</code>!", kb)
                return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Привязано!"}

        # D. Fast-Create Tester Account
        if cb_data.startswith("create_tester_user:"):
            target_cid = int(cb_data.split(":")[1])
            from werkzeug.security import generate_password_hash
            from core.db_models import UserRole, UserProfile
            
            lead = TelegramStartLead.query.filter_by(telegram_chat_id=target_cid).first()
            uname_base = (lead.telegram_username if lead and lead.telegram_username else f"tester_{target_cid % 10000}").lower()
            
            # Check unique username
            count = 1
            final_uname = uname_base
            while User.query.filter_by(username=final_uname).first():
                final_uname = f"{uname_base}_{count}"
                count += 1

            new_u = User(
                username=final_uname,
                email=f"{final_uname}@boostudy.ru",
                password_hash=generate_password_hash("BooStudyTester2026!"),
                role="tester",
                telegram_id=target_cid,
                telegram_chat_id=target_cid,
                is_active=True
            )
            db.session.add(new_u)
            db.session.flush()
            db.session.add(UserRole(user_id=new_u.id, role="tester"))
            db.session.add(UserProfile(user_id=new_u.id, first_name=lead.first_name if lead else final_uname, timezone="Europe/Moscow"))
            db.session.commit()

            reply_qa_bot(chat_id, f"🎉 <b>Создан новый аккаунт Тестировщика!</b>\n\n• Логин: <b>{new_u.username}</b>\n• Пароль: <code>BooStudyTester2026!</code>\n• TG Chat ID: <code>{target_cid}</code> привязан мгновенно!", kb)
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Тестировщик создан!"}

        # E. Interactive Test Case Creation Wizard - Category Selection
        if cb_data.startswith("newtest_cat:"):
            cat = cb_data.replace("newtest_cat:", "", 1)
            QA_FSM_STATE[chat_id] = {"step": "WAITING_TEST_TITLE", "area": cat}
            reply_qa_bot(chat_id, f"📝 Категория: <b>{cat}</b>\n\n<b>Шаг 2/2: Введите название и описание нового теста</b> (одним сообщением в чат):")
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Категория выбрана"}

        # F. Delete Test Case Inline Action
        if cb_data.startswith("del_test_case:"):
            t_id = int(cb_data.split(":")[1])
            tc = QATestCase.query.get(t_id)
            if tc:
                db.session.delete(tc)
                db.session.commit()
                reply_qa_bot(chat_id, f"🗑️ Тест-кейс #{t_id} успешно удален!", kb)
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Тест удален"}

        # G. Assign Test Step 1 (Select Test)
        if cb_data.startswith("assign_sel_test:"):
            t_id = int(cb_data.split(":")[1])
            testers = User.query.filter(User.role.in_(['tester', 'chief_tester', 'admin'])).all()
            inline_rows = []
            for t in testers:
                inline_rows.append([{"text": f"👤 {t.username} ({t.role.upper()})", "callback_data": f"do_assign:{t_id}:{t.id}"}])
            reply_qa_bot(chat_id, f"🎯 <b>Выберите исполнителя для теста #{t_id}:</b>", {"inline_keyboard": inline_rows})
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Выберите тестера"}

        # H. Assign Test Step 2 (Execute Assignment)
        if cb_data.startswith("do_assign:"):
            parts = cb_data.split(":")
            t_id, tester_user_id = int(parts[1]), int(parts[2])
            tc = QATestCase.query.get(t_id)
            target_u = User.query.get(tester_user_id)
            if tc and target_u:
                tc.assigned_to_id = target_u.id
                db.session.commit()
                from app.services.telegram_notifications import notify_qa_test_assigned
                notify_qa_test_assigned(target_u.id, tc.title or f"Тест #{tc.id}", tc.area or 'Общая', 'assigned')
                reply_qa_bot(chat_id, f"✅ Тест #{tc.id} («{tc.title}») успешно назначен на <b>{target_u.username}</b>!", kb)
            return {"ok": True, "status": "ok", "method": "answerCallbackQuery", "callback_query_id": cb_id, "text": "Тест назначен!"}

        return {
            "ok": True,
            "status": "ok",
            "method": "answerCallbackQuery",
            "callback_query_id": cb_id,
            "text": "Обработано"
        }

    # 2. Handle Message
    if "message" not in update:
        return {"ok": True, "status": "ok"}

    msg = update["message"]
    chat_id = msg.get("chat", {}).get("id")
    from_user = msg.get("from", {})
    tg_user_id = from_user.get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id:
        return {"ok": True, "status": "ok"}

    # Auto-register/update Telegram lead in database for all incoming interactions
    try:
        lead = TelegramStartLead.query.filter_by(telegram_chat_id=chat_id).first()
        if not lead:
            lead = TelegramStartLead(
                telegram_chat_id=chat_id,
                telegram_username=from_user.get("username"),
                first_name=from_user.get("first_name"),
                last_name=from_user.get("last_name")
            )
            db.session.add(lead)
        else:
            lead.telegram_username = from_user.get("username") or lead.telegram_username
            lead.first_name = from_user.get("first_name") or lead.first_name
            lead.last_name = from_user.get("last_name") or lead.last_name
            lead.last_seen_at = moscow_now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Failed to record TelegramStartLead: {e}")

    # Handle Creator secret auto-bind (/start 777)
    if text.startswith("/start 777") or text == "777":
        creator_user = User.query.filter((User.username == 'creator') | (User.role == 'creator')).first()
        if not creator_user:
            creator_user = User.query.order_by(User.id.asc()).first()
        if creator_user:
            creator_user.telegram_id = tg_user_id
            creator_user.telegram_chat_id = chat_id
            db.session.commit()
            user = creator_user
            kb = get_qa_keyboard(user)
            msg_text = (
                f"👑 <b>САКРАЛЬНАЯ АВТОРИЗАЦИЯ СОЗДАТЕЛЯ УСПЕШНА!</b>\n\n"
                f"Ваш Telegram (Chat ID: <code>{chat_id}</code>) мгновенно привязан к аккаунту <b>{user.username}</b> (Role: <b>CREATOR</b>).\n\n"
                f"Вам открыт 100% God-Mode доступ ко всем функциям бота и рассылкам."
            )
            reply_qa_bot(chat_id, msg_text, kb)
            return {"ok": True, "status": "ok"}

    # Authorization Check
    user = User.query.filter(
        (User.telegram_id == tg_user_id) | 
        (User.telegram_chat_id == chat_id)
    ).first()

    user_role = (user.role or 'student').lower() if user else None

    if not user or user_role not in ALLOWED_QA_ROLES:
        msg_text = (
            "🔒 <b>Доступ к QA-боту ограничен</b>\n\n"
            "Запрос отправлен администрации. Пожалуйста, ожидайте подтверждения доступа."
        )
        app_url = _get_app_url()
        inline_kb = {"inline_keyboard": [[{"text": "📱 Войти на BooStudy", "url": f"{app_url}/profile"}]]}
        reply_qa_bot(chat_id, msg_text, inline_kb)
        return {
            "ok": True,
            "status": "ok",
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": msg_text,
            "reply_markup": inline_kb,
            "parse_mode": "HTML"
        }

    kb = get_qa_keyboard(user)

    # Check FSM Wizard state for Creator text inputs
    state = QA_FSM_STATE.get(chat_id)
    if state and state.get("step") == "WAITING_TEST_TITLE":
        area = state.get("area", "1. Вход и деньги")
        title = text.strip()
        new_tc = QATestCase(area=area, title=title, is_active=True)
        db.session.add(new_tc)
        db.session.commit()
        QA_FSM_STATE.pop(chat_id, None)
        reply_qa_bot(chat_id, f"🎉 <b>Новый тест-кейс успешно создан!</b>\n\n• Категория: <b>{area}</b>\n• Название: <b>{title}</b>", kb)
        return {"ok": True, "status": "ok"}

    if text.startswith("/start"):
        msg_text = (
            f"🛡️ <b>QA Tester Bot (BooStudy)</b>\n\n"
            f"Приветствуем, <b>{user.username}</b> ({user.role.upper()})!\n"
            f"Бот отслеживания баг-репортов, назначения тестов и уведомлений о фиксах.\n\n"
            f"Используйте удобное интерактивное меню ниже."
        )
        reply_qa_bot(chat_id, msg_text, kb)
        return {
            "ok": True, "status": "ok", "method": "sendMessage",
            "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"
        }

    # --- 1. Interactive Incoming Leads & One-Click Inline Binding ---
    if text in ("📱 Входящие лиды & Привязка", "📱 Входящие лиды / Chat ID"):
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}
        
        leads = TelegramStartLead.query.order_by(TelegramStartLead.lead_id.desc()).limit(15).all()
        if not leads:
            reply_qa_bot(chat_id, "📱 <b>История обращения пользователей пуста.</b>", kb)
            return {"ok": True, "status": "ok"}

        reply_qa_bot(chat_id, f"📱 <b>Последние {len(leads)} обращений пользователей:</b>", kb)
        for lead in leads:
            cid = lead.telegram_chat_id
            uname = f"@{lead.telegram_username}" if lead.telegram_username else (lead.first_name or "Без ника")
            
            linked_user = User.query.filter((User.telegram_id == cid) | (User.telegram_chat_id == cid)).first()
            if linked_user:
                card_text = (
                    f"👤 <b>{uname}</b> (Chat ID: <code>{cid}</code>)\n"
                    f"Статус: 🟢 <b>АВТОРИЗОВАН</b> (#{linked_user.id} <b>{linked_user.username}</b> — {linked_user.role.upper()})"
                )
                inline_rows = [[{"text": "⚙️ Сменить привязку", "callback_data": f"bind_lead:{cid}"}]]
            else:
                card_text = (
                    f"👤 <b>{uname}</b> (Chat ID: <code>{cid}</code>)\n"
                    f"Статус: 🔴 <b>НЕ АВТОРИЗОВАН</b>"
                )
                inline_rows = [[{"text": "🔗 Привязать в 1 клик", "callback_data": f"bind_lead:{cid}"}]]

            reply_qa_bot(chat_id, card_text, {"inline_keyboard": inline_rows})
        return {"ok": True, "status": "ok"}

    # --- 2. Interactive Test Case Creation Wizard (Step 1: Choose Category) ---
    if text == "➕ Создать новый Тест":
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}

        from app.qa.routes import QA_AREAS
        inline_rows = []
        for cat in QA_AREAS:
            inline_rows.append([{"text": f"📂 {cat}", "callback_data": f"newtest_cat:{cat}"}])
        
        reply_qa_bot(chat_id, "➕ <b>Создание нового Теста</b>\n\n<b>Шаг 1/2: Выберите категорию тестирования:</b>", {"inline_keyboard": inline_rows})
        return {"ok": True, "status": "ok"}

    # --- 3. Interactive Test Case Management (List & Delete via Inline Buttons) ---
    if text in ("📋 Управление Тестами", "✏️ Редактировать / Удалить Тесты"):
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}

        test_cases = QATestCase.query.filter_by(is_active=True).order_by(QATestCase.id.desc()).limit(15).all()
        if not test_cases:
            reply_qa_bot(chat_id, "📋 <b>Тест-кейсы не найдены.</b>", kb)
            return {"ok": True, "status": "ok"}

        reply_qa_bot(chat_id, f"📋 <b>Активные Тест-кейсы ({len(test_cases)}):</b>", kb)
        for tc in test_cases:
            assignee = User.query.get(tc.assigned_to_id) if getattr(tc, 'assigned_to_id', None) else None
            assign_str = f"👤 {assignee.username}" if assignee else "⚠️ Не назначен"
            card_text = (
                f"📝 <b>Тест #{tc.id}</b>\n"
                f"📂 Категория: <b>{tc.area}</b>\n"
                f"📌 Название: <b>{tc.title}</b>\n"
                f"🎯 Исполнитель: <b>{assign_str}</b>"
            )
            inline_rows = [
                [
                    {"text": "🎯 Назначить", "callback_data": f"assign_sel_test:{tc.id}"},
                    {"text": "🗑️ Удалить", "callback_data": f"del_test_case:{tc.id}"}
                ]
            ]
            reply_qa_bot(chat_id, card_text, {"inline_keyboard": inline_rows})
        return {"ok": True, "status": "ok"}

    # --- 4. Interactive Test Assignment ---
    if text in ("🎯 Назначить Тесты", "➕ Назначить / Переназначить"):
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}

        test_cases = QATestCase.query.filter_by(is_active=True).order_by(QATestCase.id.desc()).limit(10).all()
        if not test_cases:
            reply_qa_bot(chat_id, "🎯 <b>Нет доступных тестов для назначения.</b>", kb)
            return {"ok": True, "status": "ok"}

        inline_rows = []
        for tc in test_cases:
            inline_rows.append([{"text": f"#{tc.id} [{tc.area}] {tc.title[:30]}", "callback_data": f"assign_sel_test:{tc.id}"}])

        reply_qa_bot(chat_id, "🎯 <b>Выберите тест для назначения исполнителя:</b>", {"inline_keyboard": inline_rows})
        return {"ok": True, "status": "ok"}

    # --- 5. Tester List ---
    if text == "👥 Список Тестировщиков":
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}
        testers = User.query.filter(User.role.in_(['tester', 'chief_tester', 'admin'])).all()
        if not testers:
            reply_qa_bot(chat_id, "👥 <b>Тестировщики не найдены.</b>", kb)
            return {"ok": True, "status": "ok"}
        msg_lines = ["👥 <b>Реестр тестировщиков BooStudy:</b>\n"]
        for t in testers:
            tg_status = f"<code>{t.telegram_chat_id or t.telegram_id}</code>" if (t.telegram_chat_id or t.telegram_id) else "⚠️ НЕ ПРИВЯЗАН"
            msg_lines.append(f"• ID #{t.id} | <b>{t.username}</b> ({t.role.upper()}) | TG: {tg_status}")
        reply_qa_bot(chat_id, "\n".join(msg_lines), kb)
        return {"ok": True, "status": "ok"}

    if text == "👤 Мой профиль":
        profile_text = (
            f"👤 <b>Профиль Тестировщика</b>\n\n"
            f"• <b>Логин:</b> {user.username}\n"
            f"• <b>Роль:</b> {user.role.upper()}\n"
            f"• <b>Telegram ID:</b> <code>{tg_user_id}</code>\n"
            f"• <b>Статус аккаунта:</b> {'🟢 Активен' if user.is_active else '🔴 Заблокирован'}\n"
        )
        reply_qa_bot(chat_id, profile_text, kb)
        return {"ok": True, "status": "ok"}

    if text == "📢 Рассылка Тестерам":
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}
        msg_text = (
            "📢 <b>Рассылка для Тестировщиков</b>\n\n"
            "Введите команду:\n"
            "<code>/broadcast Ваш текст сообщения</code>"
        )
        reply_qa_bot(chat_id, msg_text, kb)
        return {"ok": True, "status": "ok"}

    if text.startswith("/broadcast "):
        if not (user.is_creator() or user.role in ('creator', 'chief_admin')):
            reply_qa_bot(chat_id, "⛔ Доступно только Создателю.", kb)
            return {"ok": True, "status": "ok"}
        broadcast_content = text.replace("/broadcast ", "", 1).strip()
        testers = User.query.filter(User.role.in_(['tester', 'chief_tester', 'admin'])).all()
        sent_count = 0
        for t in testers:
            cid = t.telegram_chat_id or getattr(t, 'telegram_id', None)
            if cid and send_telegram_message(cid, f"📢 <b>Объявление от Создателя:</b>\n\n{broadcast_content}", bot_type='qa'):
                sent_count += 1
        reply_qa_bot(chat_id, f"✅ Сообщение успешно доставлено <b>{sent_count}</b> тестировщикам!", kb)
        return {"ok": True, "status": "ok"}


    if text == "🐞 Мои Баг-Репорты":
        reports = BugReport.query.filter(
            (BugReport.reporter_id == user.id) | (BugReport.assigned_to_id == user.id)
        ).order_by(BugReport.id.desc()).limit(5).all()

        if not reports:
            reports = BugReport.query.order_by(BugReport.id.desc()).limit(5).all()

        if not reports:
            msg_text = "🎉 <b>Активных баг-репортов в базе данных не найдено!</b> Все тесты пройдены."
            reply_qa_bot(chat_id, msg_text, kb)
            return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}
        
        reply_qa_bot(chat_id, f"📋 <b>Последние {len(reports)} баг-репортов:</b>", kb)
        for bug in reports:
            card_text, inline_kb = format_bug_report_card(bug)
            reply_qa_bot(chat_id, card_text, inline_kb)
        return {"ok": True, "status": "ok"}

    if text == "📊 Статистика QA":
        new_cnt = BugReport.query.filter_by(status='NEW').count()
        prog_cnt = BugReport.query.filter_by(status='IN_PROGRESS').count()
        res_cnt = BugReport.query.filter_by(status='RESOLVED').count()
        tot_cnt = BugReport.query.count()
        test_cases_cnt = QATestCase.query.filter_by(is_active=True).count()

        msg_text = (
            "📊 <b>Статистика QA & Bug Tracking (PostgreSQL):</b>\n\n"
            f"• 📋 Активных тест-кейсов: <b>{test_cases_cnt}</b>\n"
            f"• 🔴 Новые баги: <b>{new_cnt}</b>\n"
            f"• 🟡 В работе: <b>{prog_cnt}</b>\n"
            f"• 🟢 Исправлено: <b>{res_cnt}</b>\n"
            f"• 📦 Всего отчетов: <b>{tot_cnt}</b>"
        )
        reply_qa_bot(chat_id, msg_text, kb)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}

    msg_text = f"QA Bot получил запрос: {text}"
    reply_qa_bot(chat_id, msg_text, kb)
    return {
        "ok": True,
        "status": "ok",
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": msg_text,
        "reply_markup": kb
    }
