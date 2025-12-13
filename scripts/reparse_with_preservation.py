#!/usr/bin/env python3
"""
Скрипт для безопасного перепарсинга заданий с сохранением всех данных:
- Пропущенные задания (SkippedTasks)
- Черный список (BlacklistTasks)
- История использования (UsageHistory)
- Задания в уроках (LessonTasks)
"""

import os
import sys
import json
from datetime import datetime

# Добавляем корневую директорию в путь
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from app import app, db
from core.db_models import Tasks, SkippedTasks, BlacklistTasks, UsageHistory, LessonTask, moscow_now
from scraper.playwright_parser import run_parser

def backup_related_data():
    """Сохраняет все данные, связанные с заданиями"""
    print("\n" + "="*60)
    print("ШАГ 1: Сохранение связанных данных")
    print("="*60)
    
    # Сохраняем пропущенные задания
    skipped_backup = []
    skipped_tasks = SkippedTasks.query.all()
    for st in skipped_tasks:
        task = db.session.get(Tasks, st.task_fk)
        if task:
            skipped_backup.append({
                'task_fk': st.task_fk,
                'site_task_id': task.site_task_id,
                'source_url': task.source_url,
                'date_skipped': st.date_skipped.isoformat() if st.date_skipped else None,
                'session_tag': st.session_tag
            })
    print(f"✓ Сохранено {len(skipped_backup)} пропущенных заданий")
    
    # Сохраняем черный список
    blacklist_backup = []
    blacklist_tasks = BlacklistTasks.query.all()
    for bt in blacklist_tasks:
        task = db.session.get(Tasks, bt.task_fk)
        if task:
            blacklist_backup.append({
                'task_fk': bt.task_fk,
                'site_task_id': task.site_task_id,
                'source_url': task.source_url,
                'date_added': bt.date_added.isoformat() if bt.date_added else None,
                'reason': bt.reason
            })
    print(f"✓ Сохранено {len(blacklist_backup)} заданий в черном списке")
    
    # Сохраняем историю использования
    usage_backup = []
    usage_history = UsageHistory.query.all()
    for uh in usage_history:
        task = db.session.get(Tasks, uh.task_fk)
        if task:
            usage_backup.append({
                'task_fk': uh.task_fk,
                'site_task_id': task.site_task_id,
                'source_url': task.source_url,
                'date_issued': uh.date_issued.isoformat() if uh.date_issued else None,
                'session_tag': uh.session_tag
            })
    print(f"✓ Сохранено {len(usage_backup)} записей истории использования")
    
    # Сохраняем задания в уроках
    lesson_tasks_backup = []
    lesson_tasks = LessonTask.query.all()
    for lt in lesson_tasks:
        task = db.session.get(Tasks, lt.task_id)
        if task:
            lesson_tasks_backup.append({
                'lesson_task_id': lt.lesson_task_id,
                'lesson_id': lt.lesson_id,
                'task_id': lt.task_id,
                'site_task_id': task.site_task_id,
                'source_url': task.source_url,
                'date_assigned': lt.date_assigned.isoformat() if lt.date_assigned else None,
                'notes': lt.notes,
                'student_answer': lt.student_answer,
                'assignment_type': lt.assignment_type,
                'student_submission': lt.student_submission
            })
    print(f"✓ Сохранено {len(lesson_tasks_backup)} заданий в уроках")
    
    # Сохраняем в файл для подстраховки
    backup_data = {
        'timestamp': datetime.now().isoformat(),
        'skipped': skipped_backup,
        'blacklist': blacklist_backup,
        'usage_history': usage_backup,
        'lesson_tasks': lesson_tasks_backup
    }
    
    backup_file = os.path.join(project_root, 'data', f'backup_before_reparse_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(backup_file), exist_ok=True)
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    print(f"✓ Резервная копия сохранена в: {backup_file}")
    
    return backup_data

def restore_related_data(backup_data):
    """Восстанавливает связи заданий после перепарсинга (если нужно)"""
    print("\n" + "="*60)
    print("ШАГ 3: Проверка и восстановление связей")
    print("="*60)
    
    # Создаем индекс заданий по source_url для быстрого поиска
    all_tasks = Tasks.query.all()
    tasks_by_url = {task.source_url: task for task in all_tasks if task.source_url}
    tasks_by_site_id = {task.site_task_id: task for task in all_tasks if task.site_task_id}
    
    restored_skipped = 0
    restored_blacklist = 0
    restored_usage = 0
    restored_lesson_tasks = 0
    
    # Восстанавливаем пропущенные задания
    for skipped_data in backup_data['skipped']:
        # Ищем задание по source_url или site_task_id
        task = None
        if skipped_data.get('source_url'):
            task = tasks_by_url.get(skipped_data['source_url'])
        if not task and skipped_data.get('site_task_id'):
            task = tasks_by_site_id.get(skipped_data['site_task_id'])
        
        if task:
            # Проверяем, существует ли уже запись
            existing = SkippedTasks.query.filter_by(task_fk=task.task_id).first()
            if not existing:
                # Восстанавливаем только если записи нет
                new_skipped = SkippedTasks(
                    task_fk=task.task_id,
                    date_skipped=datetime.fromisoformat(skipped_data['date_skipped']) if skipped_data.get('date_skipped') else moscow_now(),
                    session_tag=skipped_data.get('session_tag')
                )
                db.session.add(new_skipped)
                restored_skipped += 1
    
    # Восстанавливаем черный список
    for blacklist_data in backup_data['blacklist']:
        task = None
        if blacklist_data.get('source_url'):
            task = tasks_by_url.get(blacklist_data['source_url'])
        if not task and blacklist_data.get('site_task_id'):
            task = tasks_by_site_id.get(blacklist_data['site_task_id'])
        
        if task:
            existing = BlacklistTasks.query.filter_by(task_fk=task.task_id).first()
            if not existing:
                new_blacklist = BlacklistTasks(
                    task_fk=task.task_id,
                    date_added=datetime.fromisoformat(blacklist_data['date_added']) if blacklist_data.get('date_added') else moscow_now(),
                    reason=blacklist_data.get('reason')
                )
                db.session.add(new_blacklist)
                restored_blacklist += 1
    
    # Восстанавливаем историю использования (опционально, обычно не нужно)
    for usage_data in backup_data['usage_history']:
        task = None
        if usage_data.get('source_url'):
            task = tasks_by_url.get(usage_data['source_url'])
        if not task and usage_data.get('site_task_id'):
            task = tasks_by_site_id.get(usage_data['site_task_id'])
        
        if task:
            existing = UsageHistory.query.filter_by(
                task_fk=task.task_id,
                session_tag=usage_data.get('session_tag')
            ).first()
            if not existing:
                new_usage = UsageHistory(
                    task_fk=task.task_id,
                    date_issued=datetime.fromisoformat(usage_data['date_issued']) if usage_data.get('date_issued') else moscow_now(),
                    session_tag=usage_data.get('session_tag')
                )
                db.session.add(new_usage)
                restored_usage += 1
    
    # Восстанавливаем задания в уроках (обновляем task_id, если изменился)
    for lt_data in backup_data['lesson_tasks']:
        task = None
        if lt_data.get('source_url'):
            task = tasks_by_url.get(lt_data['source_url'])
        if not task and lt_data.get('site_task_id'):
            task = tasks_by_site_id.get(lt_data['site_task_id'])
        
        if task:
            # Находим существующую запись LessonTask
            existing_lt = db.session.get(LessonTask, lt_data['lesson_task_id'])
            if existing_lt and existing_lt.task_id != task.task_id:
                # Обновляем task_id, если он изменился
                existing_lt.task_id = task.task_id
                restored_lesson_tasks += 1
    
    if restored_skipped > 0 or restored_blacklist > 0 or restored_usage > 0 or restored_lesson_tasks > 0:
        db.session.commit()
        print(f"✓ Восстановлено: пропущенных={restored_skipped}, черный список={restored_blacklist}, история={restored_usage}, уроки={restored_lesson_tasks}")
    else:
        print("✓ Все связи сохранены, восстановление не требуется")
    
    # Финальная проверка
    final_skipped = SkippedTasks.query.count()
    final_blacklist = BlacklistTasks.query.count()
    final_usage = UsageHistory.query.count()
    final_lesson_tasks = LessonTask.query.count()
    
    print(f"\nФинальная статистика:")
    print(f"  Пропущенные задания: {final_skipped} (было {len(backup_data['skipped'])})")
    print(f"  Черный список: {final_blacklist} (было {len(backup_data['blacklist'])})")
    print(f"  История использования: {final_usage} (было {len(backup_data['usage_history'])})")
    print(f"  Задания в уроках: {final_lesson_tasks} (было {len(backup_data['lesson_tasks'])})")

def main():
    """Основная функция перепарсинга"""
    print("\n" + "="*60)
    print("ПЕРЕПАРСИНГ ЗАДАНИЙ С СОХРАНЕНИЕМ ДАННЫХ")
    print("="*60)
    print(f"Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    with app.app_context():
        try:
            # Шаг 1: Сохраняем все связанные данные
            backup_data = backup_related_data()
            
            # Шаг 2: Запускаем парсер
            print("\n" + "="*60)
            print("ШАГ 2: Запуск парсера")
            print("="*60)
            print("Парсер обновит содержимое заданий, сохраняя task_id...")
            run_parser()
            print("✓ Парсинг завершен")
            
            # Шаг 3: Проверяем и восстанавливаем связи (если нужно)
            restore_related_data(backup_data)
            
            print("\n" + "="*60)
            print("✓ ПЕРЕПАРСИНГ УСПЕШНО ЗАВЕРШЕН")
            print("="*60)
            print(f"Время окончания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
        except Exception as e:
            print(f"\n❌ ОШИБКА при перепарсинге: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            sys.exit(1)

if __name__ == "__main__":
    main()

