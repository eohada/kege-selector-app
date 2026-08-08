import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Course, Student

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False

def run_tests():
    with app.app_context():
        # Setup test data
        import uuid
        test_slug = f"ege-inf-{uuid.uuid4().hex[:8]}"
        tutor = User(username=f'test_tutor_{uuid.uuid4().hex[:4]}', email=f'tutor_{uuid.uuid4().hex[:4]}@test.com', role='tutor', password_hash='hash', is_active=True)
        course = Course(title='ЕГЭ Информатика', slug=test_slug, is_active=True)
        db.session.add(tutor)
        db.session.add(course)
        db.session.commit()
        
        tutor_id = tutor.id
        course_id = course.id

    client = app.test_client()

    print("Running test_teacher_students_page_access...")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
    
    response = client.get('/teacher/students')
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    print("Running test_generate_invite...")
    with app.app_context():
        import uuid
        test_slug2 = f"oge-mat-{uuid.uuid4().hex[:8]}"
        tutor2 = User(username=f'test_tutor_{uuid.uuid4().hex[:4]}', email=f'tutor2_{uuid.uuid4().hex[:4]}@test.com', role='tutor', password_hash='hash', is_active=True)
        course2 = Course(title='ОГЭ Математика', slug=test_slug2, is_active=True)
        db.session.add_all([tutor2, course2])
        db.session.commit()
        tutor2_id = tutor2.id
        course2_id = course2.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor2_id)
        sess['_fresh'] = True

    response = client.post('/api/teacher/generate_invite', json={'course_id': course2_id})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.get_json()
    assert (data.get('success') is True) or (data.get('status') == 'success')
    assert 'invite' in data['invite_url'] or 'code' in data['invite_url'] or 'tutor_id' in data['invite_url']
    
    print("All tests passed!")

if __name__ == '__main__':
    run_tests()
