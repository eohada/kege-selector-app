"""
Скрипт для создания таблиц TaskTemplates и TemplateTasks в базе данных
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from core.db_models import TaskTemplate, TemplateTask

def create_tables():
    """Создает таблицы для шаблонов в базе данных"""
    with app.app_context():
        try:
            db.create_all()
            print("✅ Таблицы созданы успешно!")
            
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'TaskTemplates' in tables or 'tasktemplates' in tables.lower():
                print("✅ Таблица TaskTemplates существует")
            else:
                print("⚠️  Таблица TaskTemplates не найдена")
            
            if 'TemplateTasks' in tables or 'templatetasks' in tables.lower():
                print("✅ Таблица TemplateTasks существует")
            else:
                print("⚠️  Таблица TemplateTasks не найдена")
                
            print(f"\n📊 Всего таблиц в БД: {len(tables)}")
            
        except Exception as e:
            print(f"❌ Ошибка при создании таблиц: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return True

if __name__ == '__main__':
    print("🔧 Создание таблиц для библиотеки шаблонов...")
    print("=" * 50)
    success = create_tables()
    print("=" * 50)
    if success:
        print("✅ Готово!")
    else:
        print("❌ Произошла ошибка")
        sys.exit(1)























