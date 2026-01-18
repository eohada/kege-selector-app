import os
import sys
from sqlalchemy import create_engine, text, inspect

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def fix_schema():
    app = create_app()
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        
        table_name = 'lessons'
        if not inspector.has_table(table_name):
            print(f"Table {table_name} does not exist!")
            return

        columns = [col['name'] for col in inspector.get_columns(table_name)]
        print(f"Current columns in {table_name}: {columns}")

        with engine.connect() as conn:
            # 1. content
            if 'content' not in columns:
                print("Adding 'content' column...")
                try:
                    conn.execute(text("ALTER TABLE lessons ADD COLUMN content TEXT"))
                    print("Added 'content'.")
                except Exception as e:
                    print(f"Error adding 'content': {e}")
            else:
                print("'content' already exists.")

            # 2. student_notes
            if 'student_notes' not in columns:
                print("Adding 'student_notes' column...")
                try:
                    conn.execute(text("ALTER TABLE lessons ADD COLUMN student_notes TEXT"))
                    print("Added 'student_notes'.")
                except Exception as e:
                    print(f"Error adding 'student_notes': {e}")
            else:
                print("'student_notes' already exists.")

            # 3. materials
            if 'materials' not in columns:
                print("Adding 'materials' column...")
                try:
                    conn.execute(text("ALTER TABLE lessons ADD COLUMN materials JSON"))
                    print("Added 'materials'.")
                except Exception as e:
                    print(f"Error adding 'materials': {e}")
            else:
                print("'materials' already exists.")
            
            conn.commit()
            print("Schema check/fix completed.")

if __name__ == "__main__":
    fix_schema()
