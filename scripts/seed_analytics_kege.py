"""
Сид данных для модуля аналитики: предмет КЕГЭ (Информатика), узлы знаний по матрице сложности,
привязка заданий (Tasks) к узлам по task_number.

Запуск:
  python scripts/seed_analytics_kege.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db
from core.db_models import Subject, KnowledgeNode, Tasks

def main():
    app = create_app()
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    json_path = os.path.join(base_dir, 'data', 'analytics_kege_difficulty.json')
    if not os.path.isfile(json_path):
        print(f"Файл не найден: {json_path}")
        return 1
    with open(json_path, 'r', encoding='utf-8') as f:
        matrix = json.load(f)
    with app.app_context():
        subject = Subject.query.filter_by(slug='kege').first()
        if not subject:
            subject = Subject(slug='kege', name='Информатика (КЕГЭ)')
            db.session.add(subject)
            db.session.flush()
            print("Создан предмет: kege (Информатика КЕГЭ)")
        else:
            print("Предмет kege уже существует")
        task_number_to_node_id = {}
        for row in matrix:
            task_number = row['task_number']
            code = row['node_code']
            name = row.get('topic', code)
            base_rating = int(row.get('base_rating', 1000))
            exam_points = int(row.get('exam_points', 1))
            complexity_tier = row.get('complexity_tier')
            node = KnowledgeNode.query.filter_by(subject_id=subject.id, code=code).first()
            if not node:
                node = KnowledgeNode(
                    subject_id=subject.id,
                    name=name,
                    code=code,
                    base_rating=base_rating,
                    exam_points=exam_points,
                    complexity_tier=complexity_tier,
                )
                db.session.add(node)
                db.session.flush()
                print(f"  Узел: {code} ({name})")
            task_number_to_node_id[task_number] = node.id
        db.session.commit()
        updated = 0
        for task_number, node_id in task_number_to_node_id.items():
            for task in Tasks.query.filter_by(task_number=task_number).all():
                task.knowledge_node_id = node_id
                updated += 1
        db.session.commit()
        print(f"Обновлено заданий (Tasks) по task_number: {updated}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
