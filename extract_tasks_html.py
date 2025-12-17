#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для извлечения HTML кодов заданий из базы данных
Извлекает по 10 заданий каждого типа (1-27) и сохраняет в JSON файл
"""
import os
import sys
import json
from datetime import datetime

# Добавляем корневую директорию проекта в путь
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from app import create_app
from core.db_models import Tasks, db

def extract_tasks_html():
    """Извлекает HTML коды заданий из базы данных"""
    app = create_app()
    
    with app.app_context():
        # Словарь для хранения заданий по номерам
        tasks_by_number = {}
        
        # Получаем по 10 заданий для каждого номера (1-27)
        for task_number in range(1, 28):
            tasks = Tasks.query.filter_by(task_number=task_number)\
                              .order_by(Tasks.task_id.desc())\
                              .limit(10)\
                              .all()
            
            tasks_list = []
            for task in tasks:
                tasks_list.append({
                    'task_id': task.task_id,
                    'task_number': task.task_number,
                    'site_task_id': task.site_task_id,
                    'source_url': task.source_url,
                    'content_html': task.content_html,
                    'answer': task.answer,
                    'attached_files': task.attached_files,
                    'last_scraped': task.last_scraped.isoformat() if task.last_scraped else None
                })
            
            tasks_by_number[task_number] = {
                'count': len(tasks_list),
                'tasks': tasks_list
            }
            
            print(f"Задание {task_number}: извлечено {len(tasks_list)} заданий")
        
        # Сохраняем в JSON файл
        output_file = f'tasks_html_samples_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(tasks_by_number, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] Данные сохранены в файл: {output_file}")
        
        # Выводим статистику
        total_tasks = sum(data['count'] for data in tasks_by_number.values())
        print(f"[STAT] Всего извлечено заданий: {total_tasks}")
        print(f"[STAT] По номерам:")
        for num in range(1, 28):
            count = tasks_by_number[num]['count']
            if count > 0:
                print(f"   Задание {num}: {count} заданий")
        
        return output_file

if __name__ == '__main__':
    try:
        extract_tasks_html()
    except Exception as e:
        print(f"[ERROR] Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

