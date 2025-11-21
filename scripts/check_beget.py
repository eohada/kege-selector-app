#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для проверки возможностей Beget сервера
Запусти этот скрипт на сервере Beget через SSH
"""

import sys
import subprocess
import os

def check_python():
    """Проверяет наличие и версию Python"""
    print("🐍 Проверка Python...")
    try:
        result = subprocess.run(['python3', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    try:
        result = subprocess.run(['python', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("  ❌ Python не найден")
    return False

def check_pip():
    """Проверяет наличие pip"""
    print("\n📦 Проверка pip...")
    try:
        result = subprocess.run(['pip3', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    try:
        result = subprocess.run(['pip', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("  ❌ pip не найден")
    return False

def check_postgresql():
    """Проверяет наличие PostgreSQL клиента"""
    print("\n🐘 Проверка PostgreSQL...")
    try:
        result = subprocess.run(['psql', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("  ⚠️  PostgreSQL клиент не найден (может быть установлен на сервере)")
    return False

def check_git():
    """Проверяет наличие git"""
    print("\n📂 Проверка git...")
    try:
        result = subprocess.run(['git', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("  ⚠️  git не найден (можно установить)")
    return False

def check_disk_space():
    """Проверяет свободное место на диске"""
    print("\n💾 Проверка дискового пространства...")
    try:
        result = subprocess.run(['df', '-h', '.'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout)
            return True
    except FileNotFoundError:
        pass
    
    print("  ⚠️  Не удалось проверить дисковое пространство")
    return False

def check_environment():
    """Проверяет переменные окружения"""
    print("\n🔧 Проверка переменных окружения...")
    important_vars = ['PATH', 'HOME', 'USER']
    for var in important_vars:
        value = os.environ.get(var, 'не установлена')
        print(f"  {var}: {value}")

def main():
    print("=" * 50)
    print("🔍 Проверка возможностей Beget сервера")
    print("=" * 50)
    
    results = {
        'Python': check_python(),
        'pip': check_pip(),
        'PostgreSQL': check_postgresql(),
        'git': check_git(),
    }
    
    check_disk_space()
    check_environment()
    
    print("\n" + "=" * 50)
    print("📊 Итоги:")
    print("=" * 50)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    if results['Python'] and results['pip']:
        print("\n✅ Сервер готов для размещения Flask приложения!")
    else:
        print("\n❌ Сервер не готов. Нужно установить Python и pip.")
        print("Обратись в поддержку Beget или установи вручную.")

if __name__ == '__main__':
    main()



