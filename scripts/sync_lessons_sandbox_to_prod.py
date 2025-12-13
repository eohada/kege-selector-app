#!/usr/bin/env python3
"""
Скрипт для синхронизации уроков, домашних и классных работ из песочницы в прод.

Использование:
    # Через переменные окружения:
    export SANDBOX_DATABASE_URL="postgresql://..."
    export PROD_DATABASE_URL="postgresql://..."
    python scripts/sync_lessons_sandbox_to_prod.py
    
    # Или через аргументы командной строки:
    python scripts/sync_lessons_sandbox_to_prod.py --sandbox-url "postgresql://..." --prod-url "postgresql://..."

Требования:
    - Переменные окружения для подключения к базам данных:
      SANDBOX_DATABASE_URL - URL базы данных песочницы
      PROD_DATABASE_URL - URL базы данных продакшена
    - Или аргументы командной строки: --sandbox-url и --prod-url
"""

import os
import sys
import argparse
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_db_connection(database_url):
    """Создает подключение к базе данных"""
    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine

def is_lesson_filled(lesson_data):
    """Проверяет, заполнен ли урок (есть ли данные помимо базовых)"""
    # Урок считается заполненным, если есть:
    # - topic
    # - notes
    # - homework
    # - homework_result_percent или homework_result_notes
    # - или есть связанные LessonTask
    
    if lesson_data.get('topic'):
        return True
    if lesson_data.get('notes'):
        return True
    if lesson_data.get('homework'):
        return True
    if lesson_data.get('homework_result_percent') is not None:
        return True
    if lesson_data.get('homework_result_notes'):
        return True
    
    return False

def get_lesson_tasks(session, lesson_id):
    """Получает все задания урока (домашние и классные работы)"""
    query = text("""
        SELECT lesson_task_id, lesson_id, task_id, date_assigned, notes, 
               student_answer, assignment_type, student_submission, submission_correct
        FROM "LessonTasks"
        WHERE lesson_id = :lesson_id
    """)
    result = session.execute(query, {'lesson_id': lesson_id})
    return [dict(row._mapping) for row in result]

def find_matching_lesson(session, student_id, lesson_date, duration):
    """Находит урок в базе по student_id, lesson_date и duration"""
    query = text("""
        SELECT lesson_id, student_id, lesson_type, lesson_date, duration, status,
               topic, notes, homework, homework_status, homework_result_percent, 
               homework_result_notes, created_at, updated_at
        FROM "Lessons"
        WHERE student_id = :student_id 
          AND lesson_date = :lesson_date
          AND duration = :duration
        LIMIT 1
    """)
    result = session.execute(query, {
        'student_id': student_id,
        'lesson_date': lesson_date,
        'duration': duration
    })
    row = result.fetchone()
    if row:
        return dict(row._mapping)
    return None

def get_student_by_platform_id(session, platform_id):
    """Находит ученика по platform_id"""
    query = text("""
        SELECT student_id, name, platform_id
        FROM "Students"
        WHERE platform_id = :platform_id
        LIMIT 1
    """)
    result = session.execute(query, {'platform_id': platform_id})
    row = result.fetchone()
    if row:
        return dict(row._mapping)
    return None

def copy_lesson(sandbox_session, prod_session, sandbox_lesson, prod_student_id):
    """Копирует урок из песочницы в прод"""
    # Создаем новый урок в проде
    insert_query = text("""
        INSERT INTO "Lessons" 
        (student_id, lesson_type, lesson_date, duration, status, topic, notes, 
         homework, homework_status, homework_result_percent, homework_result_notes, 
         created_at, updated_at)
        VALUES 
        (:student_id, :lesson_type, :lesson_date, :duration, :status, :topic, :notes,
         :homework, :homework_status, :homework_result_percent, :homework_result_notes,
         :created_at, :updated_at)
        RETURNING lesson_id
    """)
    
    result = prod_session.execute(insert_query, {
        'student_id': prod_student_id,
        'lesson_type': sandbox_lesson['lesson_type'],
        'lesson_date': sandbox_lesson['lesson_date'],
        'duration': sandbox_lesson['duration'],
        'status': sandbox_lesson['status'],
        'topic': sandbox_lesson.get('topic'),
        'notes': sandbox_lesson.get('notes'),
        'homework': sandbox_lesson.get('homework'),
        'homework_status': sandbox_lesson.get('homework_status', 'not_assigned'),
        'homework_result_percent': sandbox_lesson.get('homework_result_percent'),
        'homework_result_notes': sandbox_lesson.get('homework_result_notes'),
        'created_at': sandbox_lesson.get('created_at', datetime.now()),
        'updated_at': sandbox_lesson.get('updated_at', datetime.now())
    })
    
    new_lesson_id = result.fetchone()[0]
    prod_session.commit()
    
    return new_lesson_id

def copy_lesson_tasks(sandbox_session, prod_session, sandbox_lesson_id, prod_lesson_id, dry_run=False):
    """Копирует задания урока (домашние и классные работы)"""
    tasks = get_lesson_tasks(sandbox_session, sandbox_lesson_id)
    
    if not tasks:
        return 0
    
    if dry_run:
        return len(tasks)
    
    copied_count = 0
    for task in tasks:
        # Проверяем, существует ли task_id в проде
        check_task_query = text("SELECT task_id FROM \"Tasks\" WHERE task_id = :task_id")
        task_exists = prod_session.execute(check_task_query, {'task_id': task['task_id']}).fetchone()
        
        if not task_exists:
            print(f"  ⚠️  Задание {task['task_id']} не найдено в проде, пропускаем")
            continue
        
        # Копируем задание
        insert_query = text("""
            INSERT INTO "LessonTasks"
            (lesson_id, task_id, date_assigned, notes, student_answer, 
             assignment_type, student_submission, submission_correct)
            VALUES
            (:lesson_id, :task_id, :date_assigned, :notes, :student_answer,
             :assignment_type, :student_submission, :submission_correct)
        """)
        
        prod_session.execute(insert_query, {
            'lesson_id': prod_lesson_id,
            'task_id': task['task_id'],
            'date_assigned': task.get('date_assigned', datetime.now()),
            'notes': task.get('notes'),
            'student_answer': task.get('student_answer'),
            'assignment_type': task.get('assignment_type', 'homework'),
            'student_submission': task.get('student_submission'),
            'submission_correct': task.get('submission_correct')
        })
        copied_count += 1
    
    prod_session.commit()
    return copied_count

def sync_lessons(sandbox_url=None, prod_url=None, dry_run=False):
    """Основная функция синхронизации"""
    # Получаем URL баз данных из аргументов или переменных окружения
    if not sandbox_url:
        sandbox_url = os.environ.get('SANDBOX_DATABASE_URL')
    if not prod_url:
        prod_url = os.environ.get('PROD_DATABASE_URL')
    
    if not sandbox_url:
        print("❌ Ошибка: URL базы данных песочницы не указан")
        print("   Используйте --sandbox-url или установите SANDBOX_DATABASE_URL")
        return
    
    if not prod_url:
        print("❌ Ошибка: URL базы данных продакшена не указан")
        print("   Используйте --prod-url или установите PROD_DATABASE_URL")
        return
    
    # Нормализуем URL (заменяем postgres:// на postgresql://)
    if sandbox_url.startswith('postgres://'):
        sandbox_url = sandbox_url.replace('postgres://', 'postgresql://', 1)
    if prod_url.startswith('postgres://'):
        prod_url = prod_url.replace('postgres://', 'postgresql://', 1)
    
    print("🔌 Подключаюсь к базам данных...")
    sandbox_session, _ = get_db_connection(sandbox_url)
    prod_session, _ = get_db_connection(prod_url)
    
    try:
        # Получаем все уроки из песочницы
        print("📚 Получаю уроки из песочницы...")
        query = text("""
            SELECT l.lesson_id, l.student_id, l.lesson_type, l.lesson_date, l.duration, l.status,
                   l.topic, l.notes, l.homework, l.homework_status, l.homework_result_percent,
                   l.homework_result_notes, l.created_at, l.updated_at,
                   s.platform_id, s.name as student_name
            FROM "Lessons" l
            JOIN "Students" s ON l.student_id = s.student_id
            ORDER BY l.lesson_date DESC
        """)
        
        sandbox_lessons = sandbox_session.execute(query)
        sandbox_lessons_list = [dict(row._mapping) for row in sandbox_lessons]
        
        print(f"📊 Найдено {len(sandbox_lessons_list)} уроков в песочнице")
        
        synced_count = 0
        skipped_count = 0
        error_count = 0
        
        for sandbox_lesson in sandbox_lessons_list:
            platform_id = sandbox_lesson['platform_id']
            lesson_date = sandbox_lesson['lesson_date']
            duration = sandbox_lesson['duration']
            
            print(f"\n📝 Обрабатываю урок от {lesson_date} для ученика {sandbox_lesson['student_name']} (ID: {platform_id})")
            
            # Находим ученика в проде по platform_id
            prod_student = get_student_by_platform_id(prod_session, platform_id)
            if not prod_student:
                print(f"  ⚠️  Ученик с platform_id={platform_id} не найден в проде, пропускаем")
                skipped_count += 1
                continue
            
            # Проверяем, есть ли такой урок в проде
            prod_lesson = find_matching_lesson(
                prod_session, 
                prod_student['student_id'], 
                lesson_date, 
                duration
            )
            
            if prod_lesson:
                # Урок существует - проверяем, заполнен ли он
                if is_lesson_filled(prod_lesson):
                    print(f"  ✅ Урок уже существует и заполнен в проде, пропускаем")
                    skipped_count += 1
                    continue
                else:
                    print(f"  🔄 Урок существует, но не заполнен - обновляю данные")
                    if dry_run:
                        print(f"  [DRY-RUN] Будет обновлен урок {prod_lesson['lesson_id']}")
                        synced_count += 1
                    else:
                        # Обновляем существующий урок
                        update_query = text("""
                            UPDATE "Lessons"
                            SET topic = :topic, notes = :notes, homework = :homework,
                                homework_status = :homework_status,
                                homework_result_percent = :homework_result_percent,
                                homework_result_notes = :homework_result_notes,
                                updated_at = :updated_at
                            WHERE lesson_id = :lesson_id
                        """)
                        
                        prod_session.execute(update_query, {
                            'lesson_id': prod_lesson['lesson_id'],
                            'topic': sandbox_lesson.get('topic'),
                            'notes': sandbox_lesson.get('notes'),
                            'homework': sandbox_lesson.get('homework'),
                            'homework_status': sandbox_lesson.get('homework_status', 'not_assigned'),
                            'homework_result_percent': sandbox_lesson.get('homework_result_percent'),
                            'homework_result_notes': sandbox_lesson.get('homework_result_notes'),
                            'updated_at': datetime.now()
                        })
                        prod_session.commit()
                        
                        # Копируем задания урока
                        tasks_count = copy_lesson_tasks(
                            sandbox_session, 
                            prod_session, 
                            sandbox_lesson['lesson_id'], 
                            prod_lesson['lesson_id'],
                            dry_run=dry_run
                        )
                        print(f"  ✅ Обновлен урок и скопировано {tasks_count} заданий")
                        synced_count += 1
            else:
                # Урока нет - создаем новый
                print(f"  ➕ Урок не найден в проде - создаю новый")
                if dry_run:
                    print(f"  [DRY-RUN] Будет создан новый урок для ученика {prod_student['name']}")
                    synced_count += 1
                else:
                    try:
                        new_lesson_id = copy_lesson(
                            sandbox_session, 
                            prod_session, 
                            sandbox_lesson, 
                            prod_student['student_id']
                        )
                        
                        # Копируем задания урока
                        tasks_count = copy_lesson_tasks(
                            sandbox_session, 
                            prod_session, 
                            sandbox_lesson['lesson_id'], 
                            new_lesson_id,
                            dry_run=dry_run
                        )
                        print(f"  ✅ Создан урок и скопировано {tasks_count} заданий")
                        synced_count += 1
                    except Exception as e:
                        print(f"  ❌ Ошибка при копировании урока: {e}")
                        error_count += 1
                        prod_session.rollback()
        
        print(f"\n{'='*60}")
        print(f"📊 Итоги синхронизации:")
        print(f"  ✅ Синхронизировано: {synced_count}")
        print(f"  ⏭️  Пропущено: {skipped_count}")
        print(f"  ❌ Ошибок: {error_count}")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sandbox_session.close()
        prod_session.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Синхронизация уроков из песочницы в прод')
    parser.add_argument('--sandbox-url', help='URL базы данных песочницы')
    parser.add_argument('--prod-url', help='URL базы данных продакшена')
    parser.add_argument('--dry-run', action='store_true', help='Только показать, что будет сделано, без реальных изменений')
    
    args = parser.parse_args()
    
    print("🚀 Запуск синхронизации уроков из песочницы в прод")
    print("="*60)
    
    if args.dry_run:
        print("⚠️  РЕЖИМ ПРОВЕРКИ (dry-run) - изменения не будут применены")
        print("="*60)
    
    sync_lessons(sandbox_url=args.sandbox_url, prod_url=args.prod_url, dry_run=args.dry_run)

