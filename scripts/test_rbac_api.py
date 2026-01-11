#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для тестирования API endpoints системы авторизации
Проверяет доступность и базовую функциональность endpoints
"""
import sys
import os
import io

# Настраиваем кодировку для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем корневую директорию в путь
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models import User, UserProfile, FamilyTie, Enrollment
from werkzeug.security import generate_password_hash

def test_api_endpoints_registered():
    """Тест: Проверка регистрации API endpoints"""
    print("=" * 60)
    print("ТЕСТ: Регистрация API endpoints")
    print("=" * 60)
    
    try:
        app = create_app()
        
        with app.app_context():
            # Получаем список всех зарегистрированных routes
            routes = []
            for rule in app.url_map.iter_rules():
                if rule.endpoint.startswith('admin.'):
                    routes.append(rule.rule)
            
            # Проверяем наличие нужных endpoints
            required_endpoints = [
                '/api/users',
                '/api/users/<int:user_id>',
                '/api/users/<int:user_id>/reset-password',
                '/api/users/<int:user_id>/activate',
                '/api/family-ties',
                '/api/family-ties/<int:tie_id>',
                '/api/family-ties/<int:tie_id>/confirm',
                '/api/enrollments',
                '/api/enrollments/<int:enrollment_id>',
            ]
            
            found_endpoints = []
            missing_endpoints = []
            
            for endpoint in required_endpoints:
                # Проверяем наличие endpoint в списке routes
                found = False
                for route in routes:
                    # Упрощенная проверка (без учета параметров)
                    if endpoint.split('<')[0] in route:
                        found = True
                        break
                
                if found:
                    found_endpoints.append(endpoint)
                    print(f"[OK] Endpoint найден: {endpoint}")
                else:
                    missing_endpoints.append(endpoint)
                    print(f"[WARN] Endpoint не найден: {endpoint}")
            
            if missing_endpoints:
                print(f"\n[WARN] Не найдено endpoints: {len(missing_endpoints)}")
                return False
            else:
                print(f"\n[OK] Все endpoints зарегистрированы ({len(found_endpoints)})")
                return True
                
    except Exception as e:
        print(f"[ERROR] Ошибка при проверке endpoints: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_models_relationships():
    """Тест: Проверка связей между моделями"""
    print("\n" + "=" * 60)
    print("ТЕСТ: Связи между моделями")
    print("=" * 60)
    
    try:
        app = create_app()
        
        with app.app_context():
            # Проверяем, что модели имеют правильные связи
            # backref создается динамически, поэтому проверяем через __mapper__
            user_mapper = User.__mapper__
            
            print("[OK] Проверка связей User -> UserProfile")
            assert 'profile' in [rel.key for rel in user_mapper.relationships], "User должен иметь связь profile"
            
            print("[OK] Проверка связей User -> FamilyTie (parent)")
            assert 'parent_children' in [rel.key for rel in user_mapper.relationships], "User должен иметь связь parent_children"
            
            print("[OK] Проверка связей User -> FamilyTie (student)")
            assert 'student_parents' in [rel.key for rel in user_mapper.relationships], "User должен иметь связь student_parents"
            
            print("[OK] Проверка связей User -> Enrollment (student)")
            assert 'student_enrollments' in [rel.key for rel in user_mapper.relationships], "User должен иметь связь student_enrollments"
            
            print("[OK] Проверка связей User -> Enrollment (tutor)")
            assert 'tutor_enrollments' in [rel.key for rel in user_mapper.relationships], "User должен иметь связь tutor_enrollments"
            
            print("\n[OK] Все связи проверены успешно")
            return True
            
    except Exception as e:
        print(f"[ERROR] Ошибка при проверке связей: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Главная функция тестирования"""
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ API ENDPOINTS СИСТЕМЫ АВТОРИЗАЦИИ")
    print("=" * 60 + "\n")
    
    results = []
    
    # Тест 1: Регистрация endpoints
    results.append(("Регистрация API endpoints", test_api_endpoints_registered()))
    
    # Тест 2: Связи моделей
    results.append(("Связи между моделями", test_models_relationships()))
    
    # Итоговый отчет
    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS] ПРОЙДЕН" if result else "[FAIL] ПРОВАЛЕН"
        print(f"{status}: {test_name}")
    
    print(f"\nВсего тестов: {total}")
    print(f"Пройдено: {passed}")
    print(f"Провалено: {total - passed}")
    
    if passed == total:
        print("\n[SUCCESS] Все тесты пройдены успешно!")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} тест(ов) провалено")
        return 1


if __name__ == "__main__":
    sys.exit(main())
