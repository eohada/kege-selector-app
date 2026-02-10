"""
Создаёт тестового ученика, привязанного к creator, и накидывает много «решений»
(вызовы AnalyticsEngine.process_submission) для проверки аналитики: радар, прогноз балла.

Требования:
  - Запустить перед этим seed аналитики: python scripts/seed_analytics_kege.py
  - В БД должен быть хотя бы один пользователь с ролью creator

Запуск на хосте:
  python scripts/create_test_student_for_analytics.py

Опции:
  --count N     количество решений (по умолчанию 120)
  --correct P   доля правильных 0.0-1.0 (по умолчанию 0.7)
  --username U  логин тестового пользователя (по умолчанию test_analytics_demo)
  --password P  пароль (по умолчанию test_analytics_123)
"""
import os
import sys
import random
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db
from core.db_models import User, Student, Enrollment, Tasks
from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser(description='Тестовый ученик для проверки аналитики')
    parser.add_argument('--count', type=int, default=120, help='Количество решений')
    parser.add_argument('--correct', type=float, default=0.7, help='Доля правильных (0.0-1.0)')
    parser.add_argument('--username', type=str, default='test_analytics_demo', help='Логин ученика')
    parser.add_argument('--password', type=str, default='test_analytics_123', help='Пароль ученика')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        creator = User.query.filter(User.role == 'creator').first()
        if not creator:
            print('Ошибка: в БД нет пользователя с ролью creator.')
            return 1

        tasks_with_node = Tasks.query.filter(Tasks.knowledge_node_id.isnot(None)).all()
        if not tasks_with_node:
            print('Ошибка: нет заданий с привязкой к узлам знаний.')
            print('Сначала выполните: python scripts/seed_analytics_kege.py')
            return 1

        existing = User.query.filter_by(username=args.username).first()
        if existing:
            test_user = existing
            test_student = Student.query.filter_by(user_id=test_user.id).first()
            if not test_student:
                print(f'Пользователь {args.username} есть, но не привязан к ученику. Создаём ученика.')
                test_student = Student(
                    user_id=test_user.id,
                    name=f'Тест Аналитика ({args.username})',
                )
                db.session.add(test_student)
                db.session.flush()
            else:
                print(f'Используем существующего ученика: {test_student.name} (student_id={test_student.student_id})')
        else:
            test_user = User(
                username=args.username,
                role='student',
                is_active=True,
                password_hash=generate_password_hash(args.password),
            )
            db.session.add(test_user)
            db.session.flush()
            test_student = Student(
                user_id=test_user.id,
                name=f'Тест Аналитика ({args.username})',
            )
            db.session.add(test_student)
            db.session.flush()
            print(f'Создан пользователь {args.username} и ученик (student_id={test_student.student_id})')

        enrollment = Enrollment.query.filter_by(
            student_id=test_user.id,
            tutor_id=creator.id,
        ).first()
        if not enrollment:
            enrollment = Enrollment(
                student_id=test_user.id,
                tutor_id=creator.id,
                subject='Информатика',
                status='active',
            )
            db.session.add(enrollment)
            print('Добавлено зачисление к creator.')
        else:
            print('Зачисление к creator уже есть.')

        db.session.commit()

        from app.analytics import AnalyticsEngine

        n = args.count
        correct_rate = max(0.0, min(1.0, args.correct))
        correct_count = 0
        for i in range(n):
            task = random.choice(tasks_with_node)
            is_correct = random.random() < correct_rate
            if is_correct:
                correct_count += 1
            time_sec = random.randint(5, 300) if random.random() < 0.85 else random.randint(1, 9)
            try:
                AnalyticsEngine.process_submission(
                    user_id=test_user.id,
                    task_id=task.task_id,
                    is_correct=is_correct,
                    time_spent_sec=time_sec,
                )
            except Exception as e:
                print(f'Предупреждение: process_submission для task_id={task.task_id}: {e}')
            if (i + 1) % 30 == 0:
                db.session.commit()
                print(f'  Обработано {i + 1}/{n} решений...')
        db.session.commit()

        predicted = AnalyticsEngine.predict_exam_score(test_user.id, None)
        print('')
        print('Готово.')
        print(f'  Ученик: {test_student.name} (student_id={test_student.student_id})')
        print(f'  Логин:  {args.username}')
        print(f'  Пароль: {args.password}')
        print(f'  Решений: {n} (правильных: {correct_count})')
        print(f'  Прогноз первичного балла: {predicted}')
        print('')
        print('Проверка: откройте статистику этого ученика и вкладку «Аналитика ЕГЭ».')
        return 0


if __name__ == '__main__':
    sys.exit(main())
