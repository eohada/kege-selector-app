#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import psycopg2
from urllib.parse import urlparse
from flask import Flask

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from core.db_models import db

def create_all_tables_via_sqlalchemy(database_url):
    print('\n Создание всех таблиц через SQLAlchemy...')
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            print(' Все таблицы успешно созданы через SQLAlchemy')
            return True
        except Exception as e:
            print(f' Ошибка при создании таблиц: {e}')
            import traceback
            traceback.print_exc()
            return False

REQUIRED_TABLES = ['Tasks', 'UsageHistory', 'SkippedTasks', 'BlacklistTasks', 'Students', 'Lessons', 'LessonTasks', 'Users', 'TaskTemplates', 'TemplateTasks', 'Testers', 'AuditLog']

def get_connection(database_url):
    if not database_url:
        print(' SANDBOX_DATABASE_URL не установлен')
        return None
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    try:
        parsed = urlparse(database_url)
        conn = psycopg2.connect(host=parsed.hostname, port=parsed.port or 5432, user=parsed.username, password=parsed.password, database=parsed.path[1:] if parsed.path.startswith('/') else parsed.path)
        return conn
    except Exception as e:
        print(f' Ошибка подключения: {e}')
        return None

def get_existing_tables(cursor):
    cursor.execute('SELECT table_name FROM information_schema.tables WHERE table_schema = \'public\' AND table_type = \'BASE TABLE\' ORDER BY table_name;')
    return [row[0] for row in cursor.fetchall()]

def check_database_health(conn):
    print('\n Проверка состояния базы данных...')
    cursor = conn.cursor()
    try:
        existing_tables = get_existing_tables(cursor)
        print(f'\n Существующие таблицы ({len(existing_tables)}):')
        for table in existing_tables:
            print(f'    {table}')
        missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]
        if missing_tables:
            print(f'\n Отсутствующие таблицы ({len(missing_tables)}):')
            for table in missing_tables:
                print(f'    {table}')
            return False, missing_tables
        else:
            print('\n Все необходимые таблицы присутствуют!')
            return True, []
    except Exception as e:
        print(f' Ошибка при проверке базы данных: {e}')
        import traceback
        traceback.print_exc()
        return False, []
    finally:
        cursor.close()

def main():
    print(' Проверка и исправление Sandbox базы данных')
    print('=' * 60)
    sandbox_url = os.environ.get('SANDBOX_DATABASE_URL')
    if not sandbox_url:
        print(' Переменная окружения SANDBOX_DATABASE_URL не установлена')
        sys.exit(1)
    conn = get_connection(sandbox_url)
    if not conn:
        sys.exit(1)
    try:
        is_healthy, missing_tables = check_database_health(conn)
        if not is_healthy:
            print(f'\n Создание {len(missing_tables)} отсутствующих таблиц...')
            success = create_all_tables_via_sqlalchemy(sandbox_url)
            if success:
                print('\n Повторная проверка...')
                is_healthy, still_missing = check_database_health(conn)
                if is_healthy:
                    print('\n База данных успешно исправлена!')
                else:
                    print(f'\n  Все еще отсутствуют таблицы: {still_missing}')
            else:
                sys.exit(1)
        else:
            print('\n База данных в порядке, все таблицы на месте!')
    except Exception as e:
        print(f'\n Критическая ошибка: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()
    print('\n' + '=' * 60)
    print(' Готово!')

if __name__ == '__main__':
    main()
