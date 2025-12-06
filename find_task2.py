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
from bs4 import BeautifulSoup

def find_task():
    """Поиск задания по характерным фразам"""
    
    # Характерные фразы из задачи
    search_phrases = [
        "¬(x → w) ∨ (y ≡ z) ∨ y",
        "¬(x→w)∨(y≡z)∨y",
        "x → w",
        "y ≡ z",
        "Миша заполнял таблицу истинности логической функции"
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
        
        if tasks_found:
            print(f"\nНайдено заданий: {len(tasks_found)}\n")
            print("="*80)
            
            for task in tasks_found:
                print(f"\nЗадание ID: {task.task_id}")
                print(f"Номер задания: {task.task_number}")
                print(f"Site Task ID: {task.site_task_id}")
                print(f"URL: {task.source_url}")
                print(f"\nСодержимое (первые 800 символов):")
                print("-"*80)
                if task.content_html:
                    # Убираем HTML теги для читаемости
                    soup = BeautifulSoup(task.content_html, 'html.parser')
                    text = soup.get_text()[:800]
                    print(text)
                print("-"*80)
                print()
        else:
            print("\nЗадание не найдено в базе данных.")

if __name__ == "__main__":
    find_task()



