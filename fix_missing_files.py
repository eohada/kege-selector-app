#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Скрипт для создания всех отсутствующих файлов, отслеживаемых Git"""

import subprocess
import os

# Список известных удаленных файлов
known_deleted = [
    'init_db_complete.py',
    'debug_parser.py',
    'check_content.py',
    'update_tasks.py',
    'reparse_tasks.py',
    'quick_check.py',
    'test_parse.py',
    'check_display.py',
    'find_broken_tasks.py',
    'reset_and_reparse.py',
    'diagnose.py',
    'templates/test_katex.html',
    'download_katex.py',
    'templates/simple_test.html',
    'static/test.txt',
    'templates/raw_content.html',
    'full_reset.py',
    'check_task_content.py',
    'full_reparse_fixed.py',
    'delete_broken_tasks.py',
    'check_tasks_19_22.py',
    'reparse_tasks_19_22.py',
    'update_db_schema.py',
    'test_answers_parser.py',
    'reset_db_and_parse.py',
    'check_data.py',
    'reparse_all.py',
    'reparse_fix.py',
    'final_fix.py',
    'parse_with_answers.py',
]

# Получаем список всех файлов, отслеживаемых Git
result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, encoding='utf-8', errors='ignore')
tracked_files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

# Находим отсутствующие файлы
missing_files = []
for file_path in tracked_files:
    # Убираем кавычки, если есть
    file_path = file_path.strip('"').strip("'")
    if file_path and not os.path.exists(file_path):
        missing_files.append(file_path)

# Добавляем известные удаленные файлы, если они отслеживаются Git
for file_path in known_deleted:
    if file_path in tracked_files and not os.path.exists(file_path):
        if file_path not in missing_files:
            missing_files.append(file_path)

if not missing_files:
    print("All files exist!")
else:
    print(f"\nCreating {len(missing_files)} missing files...")
    
    created = 0
    for file_path in missing_files:
        try:
            # Создаем директорию, если нужно
            dir_path = os.path.dirname(file_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            
            # Определяем тип файла по расширению
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.py':
                content = "# This file was deleted and is no longer used\n# File created for Git worktree compatibility\n"
            elif ext in ['.html', '.htm']:
                content = "<!-- This file was deleted and is no longer used -->\n<!-- File created for Git worktree compatibility -->\n"
            elif ext == '.txt':
                content = "# This file was deleted and is no longer used\n# File created for Git worktree compatibility\n"
            else:
                content = "# This file was deleted and is no longer used\n# File created for Git worktree compatibility\n"
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"Created: {file_path}")
            created += 1
        except Exception as e:
            print(f"Error creating {file_path}: {e}")
    
    print(f"\nDone! Created {created} files.")
    print("Now run: git add . && git commit -m 'Add missing placeholder files'")

