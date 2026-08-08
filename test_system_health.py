# test_system_health.py
import sys
from app import create_app, db
from app.models import User, Lesson, Student

app = create_app()

with app.app_context():
    print("\n--- CHECK 1: User Pool Alt+I ---")
    users = User.query.all()
    print(f"Total users in DB: {len(users)}")
    if len(users) < 15:
        print("[FAIL] ERROR: DB contains less than 15 users!")
    else:
        print("[SUCCESS] SUCCESS: DB contains 15+ users.")

    print("\n--- CHECK 2: Impersonation Endpoints ---")
    client = app.test_client()
    res = client.get('/sandbox/api/impersonate/users')
    print(f"GET /sandbox/api/impersonate/users -> Code: {res.status_code}")
    if res.status_code == 200:
        data = res.get_json()
        sample = data.get('users', [])[:2] if isinstance(data, dict) else []
        print(f"Payload user count: {len(data.get('users', []))}")
        print("[SUCCESS] SUCCESS: Impersonation endpoint returned 200 OK and users.")
    else:
        print(f"[FAIL] ERROR API: {res.data.decode('utf-8', errors='ignore')}")

    print("\n--- CHECK 3: Test Lesson Creation ---")
    try:
        student = Student.query.first()
        if not student:
            user = User.query.filter_by(role='student').first() or User.query.first()
            student = Student(name="Test Student", user_id=user.id if user else None)
            db.session.add(student)
            db.session.commit()
            
        test_lesson = Lesson(
            student_id=student.student_id,
            topic="Self-diagnosis test lesson",
            lesson_date=db.func.now()
        )
        db.session.add(test_lesson)
        db.session.commit()
        print(f"[SUCCESS] SUCCESS: Lesson recorded in DB! Lesson ID={test_lesson.lesson_id}")
        
        db.session.delete(test_lesson)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[FAIL] ERROR LESSON PERSISTENCE: {str(e)}")

print("\n--- TESTING COMPLETE ---\n")
