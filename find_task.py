#!/usr/bin/env python3
"""
Скрипт для поиска задания в базе данных по содержимому
"""

import os
import sys

# Добавляем корневую директорию в путь
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from app import app, db
from core.db_models import Tasks
from sqlalchemy import or_

def find_task():
    """Поиск задания по характерным фразам"""
    
    # Характерные фразы из задачи
    search_phrases = [
        "Миша заполнял таблицу истинности",
        "¬(z ∧ ¬w) ∨ ((z → w) ≡ (x → y))",
        "три различные строки",
        "z ∧ ¬w",
        "z → w",
        "x → y"
    ]
    
    with app.app_context():
        print("Поиск задания по характерным фразам...\n")
        
        # Ищем задания, содержащие хотя бы одну из фраз
        tasks_found = []
        
        for phrase in search_phrases:
            print(f"Поиск по фразе: '{phrase}'...")
            tasks = Tasks.query.filter(
                Tasks.content_html.ilike(f'%{phrase}%')
            ).all()
            
            for task in tasks:
                if task not in tasks_found:
                    tasks_found.append(task)
        
        if not tasks_found:
            print("\nЗадание не найдено. Попробуем более широкий поиск...")
            # Попробуем поиск по отдельным словам
            keywords = ["Миша", "таблицу истинности", "w, x, y, z", "w x y z"]
            for keyword in keywords:
                tasks = Tasks.query.filter(
                    Tasks.content_html.ilike(f'%{keyword}%')
                ).limit(20).all()
                
                for task in tasks:
                    if task not in tasks_found:
                        tasks_found.append(task)
        
        if tasks_found:
            print(f"\nНайдено заданий: {len(tasks_found)}\n")
            print("="*80)
            
            for task in tasks_found:
                print(f"\nЗадание ID: {task.task_id}")
                print(f"Номер задания: {task.task_number}")
                print(f"Site Task ID: {task.site_task_id}")
                print(f"URL: {task.source_url}")
                print(f"\nСодержимое (первые 500 символов):")
                print("-"*80)
                if task.content_html:
                    # Убираем HTML теги для читаемости
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(task.content_html, 'html.parser')
                    text = soup.get_text()[:500]
                    print(text)
                print("-"*80)
                print()
        else:
            print("\nЗадание не найдено в базе данных.")
            print("\nПопробуем поиск по номеру задания 2 (логические выражения обычно там)...")
            tasks_2 = Tasks.query.filter(Tasks.task_number == 2).limit(10).all()
            if tasks_2:
                print(f"Найдено заданий типа 2: {len(tasks_2)}")
                print("Проверьте их вручную.")

if __name__ == "__main__":
    find_task()





