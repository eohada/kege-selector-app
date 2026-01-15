#!/usr/bin/env python3
"""
Скрипт для проверки подключения к remote-admin API
Проверяет, что токены правильно настроены и endpoints доступны
"""
import os
import sys
import requests
import hmac

def test_connection(env_name, url, token):
    """Тестирует подключение к remote-admin API"""
    print(f"\n{'='*60}")
    print(f"Тестирование {env_name}")
    print(f"URL: {url}")
    print(f"Token: {token[:10]}...{token[-5:] if len(token) > 15 else ''}")
    print(f"{'='*60}")
    
    if not url or not token:
        print("❌ URL или токен не настроены")
        return False
    
    # Тестируем endpoint /internal/remote-admin/status
    test_url = f"{url.rstrip('/')}/internal/remote-admin/status"
    headers = {
        'X-Admin-Token': token,
        'User-Agent': 'Remote-Admin-Test/1.0',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    try:
        print(f"Запрос к: {test_url}")
        resp = requests.get(test_url, headers=headers, timeout=10, allow_redirects=False)
        
        print(f"Status Code: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
        print(f"Response Headers: {dict(resp.headers)}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                print(f"✅ Успешно! Ответ: {data}")
                return True
            except ValueError as e:
                print(f"❌ Ошибка парсинга JSON: {e}")
                print(f"Response body (первые 500 символов):")
                print(resp.text[:500])
                return False
        elif resp.status_code == 401:
            print("❌ 401 Unauthorized - токен не принят")
            print(f"Response body: {resp.text[:200]}")
            return False
        elif resp.status_code == 302 or resp.status_code == 301:
            print(f"❌ Редирект на {resp.headers.get('Location', 'unknown')} - возможно, требуется авторизация")
            return False
        else:
            print(f"❌ Неожиданный статус: {resp.status_code}")
            print(f"Response body (первые 500 символов):")
            print(resp.text[:500])
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")
        return False

if __name__ == '__main__':
    print("Проверка подключения к Remote Admin API")
    print("=" * 60)
    
    # Проверяем production
    prod_url = os.environ.get('PRODUCTION_URL', '').strip()
    prod_token = os.environ.get('PRODUCTION_ADMIN_TOKEN', '').strip()
    if prod_url and prod_token:
        test_connection('Production', prod_url, prod_token)
    
    # Проверяем sandbox
    sandbox_url = os.environ.get('SANDBOX_URL', '').strip()
    sandbox_token = os.environ.get('SANDBOX_ADMIN_TOKEN', '').strip()
    if sandbox_url and sandbox_token:
        test_connection('Sandbox', sandbox_url, sandbox_token)
    
    # Проверяем admin
    admin_url = os.environ.get('ADMIN_URL', '').strip()
    admin_token = os.environ.get('ADMIN_ADMIN_TOKEN', '').strip()
    if admin_url and admin_token:
        test_connection('Admin', admin_url, admin_token)
    
    print("\n" + "=" * 60)
    print("Проверка завершена")
