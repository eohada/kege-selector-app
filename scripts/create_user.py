#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания первого пользователя через API
Использование:
    python scripts/create_user.py
    python scripts/create_user.py admin MyPassword123 creator
"""
import sys
import requests

# Параметры по умолчанию
username = sys.argv[1] if len(sys.argv) > 1 else 'admin'
password = sys.argv[2] if len(sys.argv) > 2 else 'admin123'
role = sys.argv[3] if len(sys.argv) > 3 else 'creator'
email = sys.argv[4] if len(sys.argv) > 4 else 'admin@example.com'

# URL вашего сервиса (измените на свой)
url = 'https://kege-selector-staging-sandbox.up.railway.app/setup/first-user'

print("=" * 60)
print("СОЗДАНИЕ ПЕРВОГО ПОЛЬЗОВАТЕЛЯ")
print("=" * 60)
print(f"URL: {url}")
print(f"Username: {username}")
print(f"Role: {role}")
print(f"Email: {email}")
print()

try:
    response = requests.post(
        url,
        json={
            'username': username,
            'password': password,
            'role': role,
            'email': email
        },
        timeout=30
    )
    
    print(f"Status Code: {response.status_code}")
    print()
    
    # Показываем текст ответа для отладки
    print("Response Text:")
    print(response.text[:500])  # Первые 500 символов
    print()
    
    # Пытаемся распарсить JSON
    try:
        result = response.json()
        print("=" * 60)
        print("РЕЗУЛЬТАТ:")
        print("=" * 60)
        print(result)
        
        if result.get('success'):
            print()
            print("✅ Пользователь создан успешно!")
            print(f"   Логин: {username}")
            print(f"   Пароль: {password}")
            print(f"   Роль: {role}")
            print()
            print("Теперь вы можете войти в систему:")
            print(f"   {url.replace('/setup/first-user', '/login')}")
        else:
            print()
            print(f"❌ Ошибка: {result.get('error', 'Unknown error')}")
            
    except ValueError as e:
        print("=" * 60)
        print("ОШИБКА: Ответ не является валидным JSON")
        print("=" * 60)
        print(f"Это может означать:")
        print("  1. Endpoint еще не задеплоился (подождите 1-2 минуты)")
        print("  2. Сервер вернул HTML вместо JSON (проверьте логи)")
        print("  3. Ошибка на сервере (500)")
        print()
        print(f"Полный ответ ({len(response.text)} символов):")
        if len(response.text) > 1000:
            print(response.text[:1000] + "...")
        else:
            print(response.text)
        
except requests.exceptions.RequestException as e:
    print("=" * 60)
    print("ОШИБКА ПОДКЛЮЧЕНИЯ")
    print("=" * 60)
    print(f"Не удалось подключиться к серверу: {e}")
    print()
    print("Проверьте:")
    print("  1. Правильность URL")
    print("  2. Что сервис запущен и доступен")
    print("  3. Что endpoint задеплоился")
