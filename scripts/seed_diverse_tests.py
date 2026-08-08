"""
Скрипт полной очистки и генерации плотного банка из 28 реалистичных тест-кейсов V2
для 7 основных областей платформы BooStudy.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from core.db_models import db, User, TestCase, TestStep, BugReport, BugReportComment

def seed_diverse_tests():
    app = create_app()
    with app.app_context():
        print("=== НАЧАЛО СБРОСА И СЕДИРОВАНИЯ БАНКА ТЕСТ-КЕЙСОВ (28 ТЕСТОВ) ===")
        db.create_all()

        # 1. Очистка таблиц подсистемы тестирования
        try:
            BugReportComment.query.delete()
            BugReport.query.delete()
            TestStep.query.delete()
            TestCase.query.delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            db.create_all()
            BugReportComment.query.delete()
            BugReport.query.delete()
            TestStep.query.delete()
            TestCase.query.delete()
            db.session.commit()

        print("✓ Таблицы TestCase, TestStep, BugReport, BugReportComment очищены!")

        # 2. Поиск тестеров для распределения
        testers = User.query.filter(User.role.in_(['tester', 'chief_tester'])).order_by(User.id).all()
        if not testers:
            from werkzeug.security import generate_password_hash
            pwd_hash = generate_password_hash('tester123')
            tester_1 = User(username='tester_1', email='tester_1@boostudy.ru', role='tester', password_hash=pwd_hash)
            tester_2 = User(username='tester_2', email='tester_2@boostudy.ru', role='tester', password_hash=pwd_hash)
            tester_3 = User(username='tester_3', email='tester_3@boostudy.ru', role='tester', password_hash=pwd_hash)
            db.session.add_all([tester_1, tester_2, tester_3])
            db.session.commit()
            testers = [tester_1, tester_2, tester_3]

        print(f"✓ Найдено {len(testers)} тестеров: {[t.username for t in testers]}")

        admin = User.query.filter(User.role.in_(['admin', 'creator'])).first()
        admin_id = admin.id if admin else None

        # 3. 28 уникальных тест-кейсов по 7 областям (по 4 теста на область)
        test_cases_data = [
            # 1. Каталог Курсов (4 теста)
            {
                'title': 'Выбор тарифа КЕГЭ Информатика 2026 и открытие формы оплаты',
                'area': 'Каталог курса',
                'description': 'Открыть /library, выбрать курс КЕГЭ Информатика 2026, выбрать тариф "Стандарт" и открыть модалку покупки.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Перейти на страницу /library', 'expected_result': 'Карточки курсов отображаются'},
                    {'step_number': 2, 'action_text': 'Нажать на карту курса КЕГЭ Информатика 2026', 'expected_result': 'Открывается карточка курса'},
                    {'step_number': 3, 'action_text': 'Выбрать тариф "Стандарт" и нажать Записаться', 'expected_result': 'Открывается модалка заявки'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Применение промокода BOO2026 в модалке оформления курса',
                'area': 'Каталог курса',
                'description': 'Проверить скидку 15% при вводе промокода BOO2026.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть форму покупки курса', 'expected_result': 'Поле промокода активно'},
                    {'step_number': 2, 'action_text': 'Ввести BOO2026 и нажать Применить', 'expected_result': 'Сумма пересчитана со скидкой'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Фильтрация каталога по предмету Математика Профиль',
                'area': 'Каталог курса',
                'description': 'Проверить работу табов предметов на странице библиотеки курсов.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать таб Математика Профиль', 'expected_result': 'Остаются только курсы по математике'},
                    {'step_number': 2, 'action_text': 'Сбросить фильтр кнопкой Все курсы', 'expected_result': 'Полный список курсов восстановлен'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Просмотр демо-урока курса без авторизации',
                'area': 'Каталог курса',
                'description': 'Проверить доступность бесплатных вводных уроков для гостей.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть карточку курса в режиме инкогнито', 'expected_result': 'Кнопка Смотреть демо доступна'},
                    {'step_number': 2, 'action_text': 'Кликнуть на демо-урок', 'expected_result': 'Запускается плеер вводного видео'}
                ],
                'status': 'ACTIVE'
            },

            # 2. Тренажёр КЕГЭ (4 теста)
            {
                'title': 'Автопроверка задачи №24 (строки Python) при некорректном формате',
                'area': 'Генератор задач',
                'description': 'Проверить валидацию ответа в задаче №24 при пустом вводе.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть задачу №24 в генераторе', 'expected_result': 'Условие и файл прикреплены'},
                    {'step_number': 2, 'action_text': 'Оставить поле ответа пустым и нажать Отправить', 'expected_result': 'Тост предупреждения'},
                    {'step_number': 3, 'action_text': 'Ввести ответ с пробелами " 1420 "', 'expected_result': 'Ответ корректно зачитан'}
                ],
                'status': 'FAILED',
                'bugs': [
                    {
                        'title': 'Ошибка 500 при отправке пустого ответа в задаче №24',
                        'severity': 'CRITICAL',
                        'step_failed': 'Шаг 2: Оставить поле ответа пустым и нажать Отправить',
                        'expected_vs_actual': 'Ожидался Bento Toast. Фактически: 500 Internal Error.',
                        'page_url': 'http://localhost:5000/generator/task/24',
                        'comments': [('admin_1', 'admin', 'Исправляем валидацию в api/tasks.py.')]
                    },
                    {
                        'title': 'Опечатка в тексте подсказки к задаче №24',
                        'severity': 'MINOR',
                        'step_failed': 'Шаг 1: Открыть задачу №24 в генераторе',
                        'expected_vs_actual': 'Пропущена запятая в первом предложении.',
                        'page_url': 'http://localhost:5000/generator/task/24',
                        'comments': []
                    }
                ]
            },
            {
                'title': 'Генерация вариации задания №15 (Поразрядная конъюнкция)',
                'area': 'Генератор задач',
                'description': 'Проверить кнопку Сгенерировать аналогичную задачу.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть задачу №15', 'expected_result': 'Условие загружено'},
                    {'step_number': 2, 'action_text': 'Нажать Другой вариант', 'expected_result': 'Числа в условии обновились'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Отправка ответа в задаче №27 (Динамика/Кластеризация)',
                'area': 'Генератор задач',
                'description': 'Проверить ввод пары чисел файла A и файла B.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Ввести ответы для файла A и файла B', 'expected_result': 'Оба поля активны'},
                    {'step_number': 2, 'action_text': 'Нажать Проверить ответы', 'expected_result': 'Отображается разбор решения'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Просмотр эталонного кода Python для задачи №19-21 (Игры)',
                'area': 'Генератор задач',
                'description': 'Проверить раскрытие спойлера Решение кодом.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Показать решение кодом', 'expected_result': 'Раскрывается рекурсивная функция на Python'}
                ],
                'status': 'ACTIVE'
            },

            # 3. Расписание & Календарь (4 теста)
            {
                'title': 'Переключение учебных недель и подсвечивание дедлайнов',
                'area': 'Мобильная версия',
                'description': 'Проверить работу календаря при смене недели.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Перейти в /schedule', 'expected_result': 'Календарь загружен'},
                    {'step_number': 2, 'action_text': 'Нажать Следующая неделя', 'expected_result': 'Даты смещены на +7 дней'},
                    {'step_number': 3, 'action_text': 'Проверить чип дедлайна ДЗ', 'expected_result': 'Чип подсвечен красным'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Фильтрация вебинаров по предмету Информатика',
                'area': 'Мобильная версия',
                'description': 'Проверить таб-фильтр предметов в расписании.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Выбрать Информатика', 'expected_result': 'Только вебинары по информатике'},
                    {'step_number': 2, 'action_text': 'Выбрать Все предметы', 'expected_result': 'Полная сетка восстановлена'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Быстрый переход к записи прошедшего вебинара',
                'area': 'Мобильная версия',
                'description': 'Проверить ссылку Смотреть запись на карточке прошедшего урока.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Найти завершенный вебинар', 'expected_result': 'Кнопка Смотреть запись активна'},
                    {'step_number': 2, 'action_text': 'Кликнуть по кнопке записи', 'expected_result': 'Открывается видеоплеер с таймкодами'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Синхронизация дедлайна ДЗ с Google Calendar / iCal',
                'area': 'Мобильная версия',
                'description': 'Проверить экспорт файла календаря .ics.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Экспорт в Календарь', 'expected_result': 'Скачивается файл boostudy_schedule.ics'}
                ],
                'status': 'ACTIVE'
            },

            # 4. Проверка ДЗ (4 теста)
            {
                'title': 'Загрузка файла .py в модальном окне и отправка наставнику',
                'area': 'Библиотека',
                'description': 'Загрузить файл .py к домашнему заданию.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть страницу ДЗ', 'expected_result': 'Форма сдачи активна'},
                    {'step_number': 2, 'action_text': 'Прикрепить solution_task26.py', 'expected_result': 'Файл отображается в списке'},
                    {'step_number': 3, 'action_text': 'Нажать Сдать ДЗ', 'expected_result': 'Статус меняется на На проверке'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Валидация запрещенных типов файлов (.exe, .bat) при сдаче ДЗ',
                'area': 'Библиотека',
                'description': 'Проверить блокировку исполнимых файлов.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Попробовать загрузить malware.exe', 'expected_result': 'Выводится Bento Toast о запрете'},
                    {'step_number': 2, 'action_text': 'Проверить кнопку отправки', 'expected_result': 'Кнопка остается неактивной'}
                ],
                'status': 'PASSED'
            },
            {
                'title': 'Добавление текстового комментария ученика к сдаче ДЗ',
                'area': 'Библиотека',
                'description': 'Проверить поле Заметка для наставника.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Ввести текст комментария к решению', 'expected_result': 'Текст сохраняется при отправке'},
                    {'step_number': 2, 'action_text': 'Убедиться в отображении заметки в карточке ДЗ', 'expected_result': 'Заметка видна наставнику'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Отображение баллов и критериев проверки наставника',
                'area': 'Библиотека',
                'description': 'Проверить отображение разбора проверенного ДЗ.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть проверенное ДЗ со статусом Зачтено', 'expected_result': 'Отображается балл 100/100 и отзыв наставника'}
                ],
                'status': 'ACTIVE'
            },

            # 5. Привязка Родителя (4 теста)
            {
                'title': 'Генерация 6-значного кода привязки и валидация у родителя',
                'area': 'Авторизация и доступ',
                'description': 'Ученик генерирует код привязки, родитель вводит его.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Сгенерировать код родителя', 'expected_result': 'Пин-код выведен'},
                    {'step_number': 2, 'action_text': 'Ввести код в кабинете родителя', 'expected_result': 'Модалка Ученик привязан'},
                    {'step_number': 3, 'action_text': 'Проверить появление карточки ученика', 'expected_result': 'Статистика отображается'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Проверка срока жизни (TTL) одноразового кода привязки',
                'area': 'Авторизация и доступ',
                'description': 'Проверить недействительный код привязки.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Ввести неверный код 000000', 'expected_result': 'Тост об ошибке кода'},
                    {'step_number': 2, 'action_text': 'Проверить связи в БД', 'expected_result': 'Связь не создана'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Отвязка родительского аккаунта в настройках профиля ученика',
                'area': 'Авторизация и доступ',
                'description': 'Проверить кнопку Отвязать родителя.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Отвязать напротив профиля родителя', 'expected_result': 'Подтверждение в модалке'},
                    {'step_number': 2, 'action_text': 'Подтвердить действие', 'expected_result': 'Родительский аккаунт удален из списка'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Просмотр недельного отчета успеваемости в кабинете родителя',
                'area': 'Авторизация и доступ',
                'description': 'Проверить графики посещаемости и выполненных ДЗ.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Открыть вкладку Успеваемость ученика', 'expected_result': 'Диаграммы посещаемости за 7 дней загружены'}
                ],
                'status': 'ACTIVE'
            },

            # 6. Профиль & Настройки (4 теста)
            {
                'title': 'Смена аватарки профиля и сохранение часового пояса',
                'area': 'Песочница (Sandbox)',
                'description': 'Редактирование профиля пользователя.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Загрузить PNG аватар', 'expected_result': 'Превью обновлено'},
                    {'step_number': 2, 'action_text': 'Выбрать часовой пояс UTC+5', 'expected_result': 'Сохранено'},
                    {'step_number': 3, 'action_text': 'Перезагрузить страницу', 'expected_result': 'Данные сохранены'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Смена пароля с проверкой старого пароля',
                'area': 'Песочница (Sandbox)',
                'description': 'Проверить форму смены пароля.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Ввести неверный старый пароль', 'expected_result': 'Ошибка пароля'},
                    {'step_number': 2, 'action_text': 'Ввести верный старый и новый пароль', 'expected_result': 'Пароль изменен'}
                ],
                'status': 'FAILED',
                'bugs': [
                    {
                        'title': 'Рассинхрон валидатора длины пароля на фронтенде и бэкенде',
                        'severity': 'MAJOR',
                        'step_failed': 'Шаг 2: Ввести верный старый и новый пароль',
                        'expected_vs_actual': 'Фронтенд пропускает 6 символов, а бэкенд требует 8, вызывая 400 Bad Request.',
                        'page_url': 'http://localhost:5000/profile/security',
                        'comments': [('admin_2', 'admin', 'Поправим валидацию.')]
                    }
                ]
            },
            {
                'title': 'Переключение темы оформления (Dark Mode / Light Mode)',
                'area': 'Песочница (Sandbox)',
                'description': 'Проверить переключатель темы интерфейса.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Кликнуть переключатель Тёмная тема', 'expected_result': 'Цветовая схема меняется на тёмную Bento'},
                    {'step_number': 2, 'action_text': 'Перезагрузить страницу', 'expected_result': 'Выбранная тема сохранена в localStorage'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Привязка Telegram аккаунта через бота авторизации',
                'area': 'Песочница (Sandbox)',
                'description': 'Проверить интеграцию с Telegram ботом уведомлений.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Привязать Telegram', 'expected_result': 'Генерируется глубокая ссылка tg://resolve'},
                    {'step_number': 2, 'action_text': 'Перейти по ссылке и запустить бота', 'expected_result': 'Выводится уведомление Telegram привязан'}
                ],
                'status': 'ACTIVE'
            },

            # 7. Панель Администратора (4 теста)
            {
                'title': 'Переключение режима Технических Работ и скачивание JSON-дампа БД',
                'area': 'Админка',
                'description': 'Проверить режим тех. работ и экспорт бэкапа.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Перейти в /admin/diagnostics', 'expected_result': 'Статус доступен'},
                    {'step_number': 2, 'action_text': 'Включить Режим Тех. Работ', 'expected_result': 'Тост подтверждения'},
                    {'step_number': 3, 'action_text': 'Скачать Бэкап БД', 'expected_result': 'Файл JSON скачан'}
                ],
                'status': 'PASSED'
            },
            {
                'title': 'Назначение прав и ролей в матрице доступов /admin/permissions',
                'area': 'Админка',
                'description': 'Проверить матрицу прав.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Перейти в /admin/permissions', 'expected_result': 'Матрица загружена'},
                    {'step_number': 2, 'action_text': 'Изменить право Редактирование задач', 'expected_result': 'Изменение сохранено'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Фильтрация логов аудита по роли пользователя в /admin/audit',
                'area': 'Админка',
                'description': 'Проверить фильтр системного журнала аудита.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Выбрать фильтр Роль: Admin', 'expected_result': 'Остаются только действия администраторов'},
                    {'step_number': 2, 'action_text': 'Экспортировать логи в CSV', 'expected_result': 'Файл audit_logs.csv загружен'}
                ],
                'status': 'ACTIVE'
            },
            {
                'title': 'Имперсонация тестировщика из панели управления /admin/testers',
                'area': 'Админка',
                'description': 'Проверить быструю имперсонацию под учёткой tester_1.',
                'steps': [
                    {'step_number': 1, 'action_text': 'Нажать Войти под тестером напротив tester_1', 'expected_result': 'Редирект на /tester в режиме имперсонации'},
                    {'step_number': 2, 'action_text': 'Нажать Выйти из имперсонации', 'expected_result': 'Возврат в сессию администратора'}
                ],
                'status': 'ACTIVE'
            }
        ]

        # 4. Сохранение в БД с равномерной привязкой к тестерам
        created_count = 0
        for idx, item in enumerate(test_cases_data):
            assigned_tester = testers[idx % len(testers)]
            
            tc = TestCase(
                title=item['title'],
                area=item['area'],
                description=item['description'],
                assigned_to_id=assigned_tester.id,
                created_by_id=admin_id,
                status=item['status']
            )
            db.session.add(tc)
            db.session.flush()

            for s_data in item['steps']:
                step = TestStep(
                    test_case_id=tc.id,
                    step_number=s_data['step_number'],
                    action_text=s_data['action_text'],
                    expected_result=s_data['expected_result'],
                    is_completed=(item['status'] == 'PASSED')
                )
                db.session.add(step)

            # Если заданы баг-репорты — создаем каждый из них (one-to-many)
            if 'bugs' in item:
                for bug_info in item['bugs']:
                    bug = BugReport(
                        test_case_id=tc.id,
                        reporter_id=assigned_tester.id,
                        title=bug_info['title'],
                        description=bug_info['expected_vs_actual'],
                        page_url=bug_info['page_url'],
                        step_failed=bug_info['step_failed'],
                        expected_vs_actual=bug_info['expected_vs_actual'],
                        severity=bug_info['severity'],
                        status='NEW'
                    )
                    db.session.add(bug)
                    db.session.flush()

                    for author_uname, role, comment_text in bug_info.get('comments', []):
                        author_user = User.query.filter_by(username=author_uname).first()
                        author_id = author_user.id if author_user else admin_id
                        c = BugReportComment(
                            bug_report_id=bug.id,
                            author_id=author_id,
                            text=comment_text
                        )
                        db.session.add(c)

            created_count += 1

        db.session.commit()
        print(f"✓ Успешно сгенерировано {created_count} реалистичных тест-кейсов по 7 областям!")
        print("=== СЕДИРОВАНИЕ ЗАВЕРШЕНО 100% УСПЕШНО ===")

if __name__ == '__main__':
    seed_diverse_tests()
