import os
import sys
import json

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root)

from app import create_app
from core.db_models import db, QATestCase, QAReport, User

app = create_app()

def migrate():
    with app.app_context():
        # Убедимся, что таблицы созданы
        db.create_all()

        json_path = os.path.join(root, 'tester_assistant_app', 'tests_db.json')
        if not os.path.exists(json_path):
            print(f"Error: {json_path} not found")
            return
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        added = 0
        for test in data.get('available', []):
            # Проверяем, есть ли уже такой тест
            existing = QATestCase.query.filter_by(title=test.get('title')).first()
            if existing:
                continue
                
            new_test = QATestCase(
                title=test.get('title'),
                area=test.get('area', 'Общая'),
                role=test.get('role', 'Любой'),
                steps=test.get('steps', []),
                expected_result=test.get('expected', '')
            )
            db.session.add(new_test)
            added += 1
            
        db.session.commit()
        print(f"Migration complete. Added {added} new test cases.")

if __name__ == '__main__':
    migrate()
