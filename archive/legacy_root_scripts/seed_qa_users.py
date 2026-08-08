from wsgi import app
from core.db_models import db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    roles = {
        'student': 'student',
        'tutor': 'tutor',
        'parent': 'parent',
        'admin': 'admin'
    }
    
    for role_key, role_val in roles.items():
        for i in range(1, 4):
            username = f"qa_{role_key}_{i}"
            if not User.query.filter_by(username=username).first():
                user = User(
                    username=username,
                    password_hash=generate_password_hash("qa123"),
                    role=role_val,
                    is_active=True
                )
                db.session.add(user)
                print(f"Created {username}")
    db.session.commit()
    print("QA users seeded successfully")
