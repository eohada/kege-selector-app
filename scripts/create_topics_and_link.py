"""
Скрипт для создания тем из списка и связывания их с заданиями по номерам
"""
import sys
import os

# Исправляем кодировку для Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Topic, Tasks, task_topics

# Маппинг номеров заданий на темы (из скриншотов)
# Примечание: задания 19, 20, 21 все хранятся в базе под номером 19
# Все записи отсортированы по возрастанию номеров заданий (1-27)
TASK_TOPIC_MAPPING = {
    1: "Анализ информационных моделей",  # Задание №1
    2: "Таблицы истинности логических выражений",  # Задание №2
    3: "Поиск и сортировка в базах данных",  # Задание №3
    4: "Кодирование и декодирование данных. Условие Фано",  # Задание №4
    5: "Анализ алгоритмов для исполнителей",  # Задание №5
    6: "Циклические алгоритмы для Исполнителя",  # Задание №6
    7: "Кодирование графической и звуковой информации",  # Задание №7
    8: "Комбинаторика",  # Задание №8
    9: "Обработка числовой информации в электронных таблицах",  # Задание №9
    10: "Поиск слова в текстовом документе",  # Задание №10
    11: "Вычисление количества информации",  # Задание №11
    12: "Машина Тьюринга",  # Задание №12
    13: "IP адреса и маски",  # Задание №13
    14: "Позиционные системы счисления",  # Задание №14
    15: "Истинность логического выражения",  # Задание №15
    16: "Вычисление значения рекурсивной функции",  # Задание №16
    17: "Обработка целочисленных данных. Проверка делимости",  # Задание №17
    18: "Динамическое программирование в электронных таблицах",  # Задание №18
    19: "Теория игр",  # Задания №19, 20, 21 (все хранятся под номером 19 в базе)
    22: "Многопоточные вычисления",  # Задание №22
    23: "Динамическое программирование (количество программ)",  # Задание №23
    24: "Обработка символьных строк",  # Задание №24
    25: "Обработка целочисленных данных. Поиск делителей",  # Задание №25
    26: "Обработка данных с помощью сортировки",  # Задание №26
    27: "Анализ данных"  # Задание №27
}

def create_topics_and_link():
    """Создает темы и связывает их с заданиями"""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("Создание тем и связывание с заданиями")
        print("=" * 60)
        
        # ШАГ 1: Создаем уникальные темы
        unique_topics = set(TASK_TOPIC_MAPPING.values())
        topics_dict = {}
        created_count = 0
        existing_count = 0
        
        print(f"\n[1/2] Создание {len(unique_topics)} уникальных тем...")
        
        for i, topic_name in enumerate(sorted(unique_topics), 1):
            topic = Topic.query.filter_by(name=topic_name).first()
            
            if not topic:
                topic = Topic(name=topic_name)
                db.session.add(topic)
                created_count += 1
                print(f"  [{i}/{len(unique_topics)}] Создана: {topic_name}")
            else:
                existing_count += 1
            
            topics_dict[topic_name] = topic
        
        db.session.commit()
        print(f"\n  Создано новых тем: {created_count}")
        print(f"  Существующих тем: {existing_count}")
        
        # ШАГ 2: Связываем задания с темами
        print(f"\n[2/2] Связывание заданий с темами...")
        
        # Загружаем все существующие связи одним запросом для оптимизации
        print("  Загрузка существующих связей...", flush=True)
        existing_links_query = db.session.query(task_topics).all()
        existing_links_set = {(link.task_id, link.topic_id) for link in existing_links_query}
        print(f"  Найдено существующих связей: {len(existing_links_set)}", flush=True)
        
        # Обрабатываем каждый номер задания отдельно
        total_linked = 0
        total_skipped = 0
        tasks_not_found = set()
        links_to_create = []
        
        print("  Обработка номеров заданий...", flush=True)
        for task_number, topic_name in TASK_TOPIC_MAPPING.items():
            topic = topics_dict[topic_name]
            
            # Находим все задания с этим номером
            tasks = Tasks.query.filter_by(task_number=task_number).all()
            
            if not tasks:
                tasks_not_found.add(task_number)
                continue
            
            # Для каждого задания проверяем и собираем связи для создания
            for task in tasks:
                link_key = (task.task_id, topic.topic_id)
                if link_key not in existing_links_set:
                    links_to_create.append({
                        'task_id': task.task_id,
                        'topic_id': topic.topic_id
                    })
                else:
                    total_skipped += 1
            
            if task_number % 5 == 0:
                print(f"    Обработано номеров: {task_number}, собрано связей: {len(links_to_create)}", flush=True)
        
        print(f"\n  Всего связей для создания: {len(links_to_create)}", flush=True)
        print(f"  Уже существует: {total_skipped}", flush=True)
        
        # Создаем связи батчами с обработкой дубликатов через ON CONFLICT
        if links_to_create:
            print(f"\n  Создание связей батчами по 500...", flush=True)
            batch_size = 500
            total_batches = (len(links_to_create) + batch_size - 1) // batch_size
            
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            
            for i in range(0, len(links_to_create), batch_size):
                batch = links_to_create[i:i + batch_size]
                batch_num = i // batch_size + 1
                
                # Используем PostgreSQL ON CONFLICT для пропуска дубликатов
                stmt = pg_insert(task_topics).values(batch)
                stmt = stmt.on_conflict_do_nothing(index_elements=['task_id', 'topic_id'])
                result = db.session.execute(stmt)
                total_linked += result.rowcount
                db.session.commit()
                
                if batch_num % 5 == 0 or batch_num == total_batches:
                    print(f"    Батч {batch_num}/{total_batches}: создано {total_linked} связей", flush=True)
            
            print(f"  Готово! Всего создано: {total_linked}", flush=True)
        else:
            print("  Все связи уже существуют, ничего создавать не нужно.", flush=True)
        
        print(f"\n" + "=" * 60)
        print("РЕЗУЛЬТАТЫ:")
        print(f"  Создано новых тем: {created_count}")
        print(f"  Существующих тем: {existing_count}")
        print(f"  Создано новых связей: {total_linked}")
        print(f"  Пропущено (уже существуют): {total_skipped}")
        if tasks_not_found:
            print(f"  Заданий не найдено для номеров: {sorted(tasks_not_found)}")
        print("=" * 60)
        print("\nГотово!")

if __name__ == '__main__':
    try:
        create_topics_and_link()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
