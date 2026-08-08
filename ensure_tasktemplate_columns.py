from app import create_app
from core.db_models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    conn = db.engine.connect()
    columns = [row[1] for row in conn.execute(text("PRAGMA table_info(TaskTemplates)")).fetchall()]
    
    if 'estimated_time' not in columns:
        print("Adding estimated_time column to TaskTemplates...")
        conn.execute(text("ALTER TABLE TaskTemplates ADD COLUMN estimated_time INTEGER DEFAULT 45"))
    if 'course_id' not in columns:
        print("Adding course_id column to TaskTemplates...")
        conn.execute(text("ALTER TABLE TaskTemplates ADD COLUMN course_id INTEGER"))
    
    conn.commit()
    print("Database schema migration for TaskTemplates verified successfully!")
