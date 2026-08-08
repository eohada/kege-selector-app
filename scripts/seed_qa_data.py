import os
import sys

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from core.db_models import db, QATestCase, QAReport, QAReportHistory, User

app = create_app()

def seed_qa_data():
    with app.app_context():
        print("Очистка старых QA данных...")
        QAReportHistory.query.delete()
        QAReport.query.delete()
        QATestCase.query.delete()
        db.session.commit()

        # 1. Создаем тест-кейсы по категориям
        print("Создание тест-кейсов...")
        test_cases_data = [
            # Авторизация
            {"title": "Вход с неверным паролем", "area": "Авторизация и доступ", "role": "Все", "expected_result": "Появляется красное уведомление 'Неверный логин или пароль'. Авторизация не происходит.", "steps": ["Открыть страницу логина", "Ввести существующий email", "Ввести неверный пароль", "Нажать 'Войти'"]},
            {"title": "Восстановление пароля (сброс)", "area": "Авторизация и доступ", "role": "Все", "expected_result": "На почту приходит письмо со ссылкой. Переход по ссылке открывает форму установки нового пароля.", "steps": ["Нажать 'Забыли пароль?'", "Ввести email", "Проверить почту", "Перейти по ссылке"]},
            
            # Песочница
            {"title": "Запуск Python-кода с SyntaxError", "area": "Песочница (Sandbox)", "role": "student", "expected_result": "Выводится красное сообщение с деталями SyntaxError и номером строки. Приложение не падает.", "steps": ["Открыть песочницу", "Ввести код: print('Hello)", "Нажать 'Запустить'"]},
            {"title": "Бесконечный цикл (Timeout)", "area": "Песочница (Sandbox)", "role": "student", "expected_result": "Через 5 секунд процесс убивается, выводится сообщение 'Время выполнения превышено (Timeout)'.", "steps": ["Ввести код: while True: pass", "Нажать 'Запустить'"]},
            
            # Workspace
            {"title": "Загрузка файла > 50 МБ", "area": "Workspace", "role": "student", "expected_result": "Браузер блокирует загрузку, выводится уведомление 'Файл слишком большой. Максимум 50MB.'", "steps": ["Открыть Workspace", "Нажать 'Загрузить файл'", "Выбрать файл размером 60 МБ"]},
            {"title": "Создание пустой папки", "area": "Workspace", "role": "student", "expected_result": "Папка появляется в дереве файлов слева.", "steps": ["Клик правой кнопкой в файловом менеджере", "Выбрать 'Новая папка'", "Ввести имя 'test_dir'", "Нажать Enter"]},
            
            # Генератор задач
            {"title": "Генерация варианта из 5 задач", "area": "Генератор задач", "role": "tutor", "expected_result": "Создается вариант с 5 задачами. Можно скопировать ссылку для учеников.", "steps": ["Выбрать 5 случайных тем в генераторе", "Нажать 'Собрать вариант'", "Проверить страницу варианта"]},
            
            # Telegram
            {"title": "Привязка Telegram-аккаунта", "area": "Telegram", "role": "student", "expected_result": "Бот отвечает 'Аккаунт успешно привязан'. В профиле появляется галочка.", "steps": ["Зайти в профиль", "Нажать 'Привязать Telegram'", "Перейти в бота и нажать /start"]},
        ]

        test_cases = []
        for data in test_cases_data:
            tc = QATestCase(
                title=data["title"],
                area=data["area"],
                role=data["role"],
                steps=data["steps"],
                expected_result=data["expected_result"],
                is_active=True
            )
            db.session.add(tc)
            test_cases.append(tc)
        
        db.session.commit()
        print(f"Создано {len(test_cases)} тест-кейсов.")

        # Получаем админа и тестировщика (первые попавшиеся, или создаем фейковых, если база пустая)
        tester = User.query.filter(User.role.in_(['tester', 'chief_tester', 'creator'])).first()
        admin = User.query.filter(User.role.in_(['admin', 'creator', 'chief_admin'])).first()

        if not tester or not admin:
            print("В базе нет пользователей для назначения репортов. Пропускаю создание багов.")
            return

        print("Создание баг-репортов...")
        # 2. Создаем баг-репорты в разных статусах
        
        # Баг 1: Pending (Новый)
        r1 = QAReport(
            test_id=test_cases[0].id,
            reporter_id=tester.id,
            area=test_cases[0].area,
            status="pending",
            verdict="minor",
            comment="Уведомление зеленого цвета вместо красного.",
            page_url="http://localhost:5000/auth/login",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            attachments=[{"url": "https://placehold.co/600x400?text=Fake+Screenshot", "type": "image", "filename": "fake.png"}]
        )
        db.session.add(r1)

        # Баг 2: In Progress (В работе)
        r2 = QAReport(
            test_id=None, # Ad-hoc
            reporter_id=tester.id,
            area="Мобильная версия",
            status="in_progress",
            verdict="critical",
            comment="На iPhone меню съезжает вправо, перекрывая контент.\n\n--- Консоль (HAR) ---\nFailed to load resource: net::ERR_CONNECTION_REFUSED",
            page_url="http://localhost:5000/dashboard",
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
        )
        db.session.add(r2)
        
        db.session.flush() # Получаем ID для истории
        
        # Добавляем историю для In Progress
        h2 = QAReportHistory(report_id=r2.id, author_id=admin.id, old_status="pending", new_status="in_progress", comment="Взял в работу, чиню CSS.")
        db.session.add(h2)

        # Баг 3: Retest (На ретесте - ждет реакции тестировщика)
        r3 = QAReport(
            test_id=test_cases[2].id,
            reporter_id=tester.id,
            area=test_cases[2].area,
            status="retest",
            verdict="minor",
            comment="При SyntaxError кнопка 'Запустить' блокируется навсегда, приходится обновлять страницу.",
            page_url="http://localhost:5000/sandbox",
            user_agent="Chrome 115.0",
        )
        db.session.add(r3)
        db.session.flush()

        h3_1 = QAReportHistory(report_id=r3.id, author_id=admin.id, old_status="pending", new_status="in_progress", comment="Вижу проблему, сейчас сниму disable с кнопки.")
        h3_2 = QAReportHistory(report_id=r3.id, author_id=admin.id, old_status="in_progress", new_status="retest", comment="Исправил, залил. Проверь, пожалуйста, разблокируется ли кнопка теперь.")
        db.session.add_all([h3_1, h3_2])

        # Баг 4: Resolved (Закрыт)
        r4 = QAReport(
            test_id=test_cases[4].id,
            reporter_id=tester.id,
            area=test_cases[4].area,
            status="resolved",
            verdict="success", # Успешное прохождение теста
            comment="Все работает корректно, лимит 50 МБ соблюдается.",
            page_url="http://localhost:5000/workspace",
            user_agent="Chrome 115.0",
        )
        db.session.add(r4)

        db.session.commit()
        print("Тестовые баги и история созданы успешно!")

if __name__ == "__main__":
    seed_qa_data()
