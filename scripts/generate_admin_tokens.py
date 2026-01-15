"""
Скрипт для генерации токенов для удаленной админки
Генерирует безопасные случайные токены для каждого окружения
"""
import secrets
import sys
import io

# Исправление кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def generate_token(length=64):
    """Генерирует безопасный случайный токен"""
    # Используем secrets для криптографически стойкой генерации
    return secrets.token_urlsafe(length)

def main():
    """Генерирует токены для всех окружений"""
    print("=" * 60)
    print("Генерация токенов для удаленной админки")
    print("=" * 60)
    print()
    
    # Генерируем токены
    production_token = generate_token()
    sandbox_token = generate_token()
    admin_token = generate_token()
    
    print("Скопируйте эти токены в переменные окружения:")
    print()
    print("-" * 60)
    print("ДЛЯ ADMIN СЕРВИСА (удаленная админка):")
    print("-" * 60)
    print(f"PRODUCTION_ADMIN_TOKEN={production_token}")
    print(f"SANDBOX_ADMIN_TOKEN={sandbox_token}")
    print(f"ADMIN_ADMIN_TOKEN={admin_token}")
    print()
    
    print("-" * 60)
    print("ДЛЯ PRODUCTION СЕРВИСА:")
    print("-" * 60)
    print(f"PRODUCTION_ADMIN_TOKEN={production_token}")
    print()
    
    print("-" * 60)
    print("ДЛЯ SANDBOX СЕРВИСА:")
    print("-" * 60)
    print(f"SANDBOX_ADMIN_TOKEN={sandbox_token}")
    print()
    
    print("-" * 60)
    print("ДЛЯ ADMIN СЕРВИСА (если нужно управлять самим собой):")
    print("-" * 60)
    print(f"ADMIN_ADMIN_TOKEN={admin_token}")
    print()
    
    print("=" * 60)
    print("ВАЖНО!")
    print("=" * 60)
    print("1. Токены должны быть ОДИНАКОВЫМИ в двух местах:")
    print("   - В admin сервисе (чтобы отправлять запросы)")
    print("   - В целевом окружении (чтобы принимать запросы)")
    print()
    print("2. Например:")
    print("   PRODUCTION_ADMIN_TOKEN в admin = PRODUCTION_ADMIN_TOKEN в production")
    print("   SANDBOX_ADMIN_TOKEN в admin = SANDBOX_ADMIN_TOKEN в sandbox")
    print()
    print("3. Сохраните токены в безопасном месте!")
    print("=" * 60)
    
    # Сохраняем в файл для удобства
    output_file = "admin_tokens.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("Токены для удаленной админки\n")
        f.write("=" * 60 + "\n\n")
        f.write("ДЛЯ ADMIN СЕРВИСА:\n")
        f.write(f"PRODUCTION_ADMIN_TOKEN={production_token}\n")
        f.write(f"SANDBOX_ADMIN_TOKEN={sandbox_token}\n")
        f.write(f"ADMIN_ADMIN_TOKEN={admin_token}\n\n")
        f.write("ДЛЯ PRODUCTION СЕРВИСА:\n")
        f.write(f"PRODUCTION_ADMIN_TOKEN={production_token}\n\n")
        f.write("ДЛЯ SANDBOX СЕРВИСА:\n")
        f.write(f"SANDBOX_ADMIN_TOKEN={sandbox_token}\n\n")
        f.write("ДЛЯ ADMIN СЕРВИСА (если нужно управлять самим собой):\n")
        f.write(f"ADMIN_ADMIN_TOKEN={admin_token}\n")
    
    print(f"\nТокены также сохранены в файл: {output_file}")
    print("ВНИМАНИЕ: Удалите этот файл после использования!")

if __name__ == '__main__':
    main()
