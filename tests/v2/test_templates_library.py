import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Tasks
from core.db_models import TaskTemplate, TemplateTask

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['DEBUG'] = True
app.config['TESTING'] = True

def run_templates_library_tests():
    with app.app_context():
        # Setup test tutor
        tutor_user = User(
            username=f'tutor_tpl_{uuid.uuid4().hex[:4]}',
            email=f'tutor_tpl_{uuid.uuid4().hex[:4]}@test.com',
            role='tutor',
            password_hash='hash',
            is_active=True
        )
        db.session.add(tutor_user)
        db.session.commit()

        # Setup test task
        task = Tasks(
            task_number=24,
            content_html='Найти максимальную длину подстроки одинаковых символов.',
            answer='142',
            max_score=1
        )
        db.session.add(task)
        db.session.commit()

        # Setup test template
        template = TaskTemplate(
            name='Тестовый пробник ЕГЭ №1',
            description='Комплексный пробный вариант для проверки базового уровня',
            template_type='mock_exam',
            category='ЕГЭ',
            estimated_time=120,
            created_by=tutor_user.id,
            is_active=True
        )
        db.session.add(template)
        db.session.commit()

        # Attach task
        tt = TemplateTask(
            template_id=template.template_id,
            task_id=task.task_id,
            order=0
        )
        db.session.add(tt)
        db.session.commit()

        tutor_id = tutor_user.id
        template_id = template.template_id

    client = app.test_client()

    print("\n--- TEST 1: GET /templates_library as Tutor ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'tutor'

    res1 = client.get('/templates_library')
    assert res1.status_code == 200, f"Expected 200 for GET /templates_library, got {res1.status_code}"
    html1 = res1.get_data(as_text=True)
    assert 'Библиотека шаблонов' in html1, "Page title 'Библиотека шаблонов' should be present"
    assert 'Тестовый пробник ЕГЭ №1' in html1, "Template name should be rendered on page"
    print("SUCCESS: GET /templates_library returned 200 OK (V2 Templates Library Loaded!)")

    print("\n--- TEST 2: GET /teacher/templates/new (Create Template View) ---")
    res2_new = client.get('/teacher/templates/new', follow_redirects=True)
    assert res2_new.status_code == 200, f"Expected 200 for GET /teacher/templates/new, got {res2_new.status_code}"
    html_new = res2_new.get_data(as_text=True)
    assert 'Конструктор шаблона' in html_new or 'шаблон' in html_new.lower(), "Template constructor page should be rendered"
    print("SUCCESS: GET /teacher/templates/new returned 200 OK (Constructor Loaded!)")

    print("\n--- TEST 3: GET /teacher/templates/<id>/edit (Edit Template View) ---")
    res3_edit = client.get(f'/teacher/templates/{template_id}/edit', follow_redirects=True)
    assert res3_edit.status_code == 200, f"Expected 200 for GET /teacher/templates/<id>/edit, got {res3_edit.status_code}"
    print(f"SUCCESS: GET /teacher/templates/{template_id}/edit returned 200 OK (Constructor Edit Loaded!)")

    print("\n--- TEST 4: GET /api/teacher/templates/<id>/preview (Preview Tasks API) ---")
    res2 = client.get(f'/api/teacher/templates/{template_id}/preview')
    assert res2.status_code == 200, f"Expected 200 for GET preview, got {res2.status_code}"
    data2 = res2.get_json()
    assert data2['status'] == 'success', f"Expected status 'success', got {data2}"
    assert data2['title'] == 'Тестовый пробник ЕГЭ №1'
    assert len(data2['tasks']) == 1, f"Expected 1 task in preview, got {len(data2['tasks'])}"
    assert data2['tasks'][0]['answer'] == '142'
    print(f"SUCCESS: GET preview API returned task list correctly for template {template_id}!")

    print("\n--- TEST 5: DELETE /api/teacher/templates/<id> (Delete Template API) ---")
    res3 = client.delete(f'/api/teacher/templates/{template_id}')
    assert res3.status_code == 200, f"Expected 200 for DELETE, got {res3.status_code}"
    data3 = res3.get_json()
    assert data3['status'] == 'success', f"Expected status 'success', got {data3}"

    with app.app_context():
        deleted = TaskTemplate.query.get(template_id)
        assert deleted is None, "Template should be deleted from DB"
    print("SUCCESS: DELETE /api/teacher/templates/<id> removed template from DB!")

    print("\n--- TEST 6: Attempt GET /templates_library as Student (Soft Redirect) ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'student'

    res4 = client.get('/templates_library', follow_redirects=False)
    assert res4.status_code == 302, f"Expected 302 redirect for student, got {res4.status_code}"
    loc4 = res4.headers.get('Location')
    assert loc4 == '/dashboard', f"Expected redirect to '/dashboard', got '{loc4}'"
    print("SUCCESS: Student access to /templates_library smoothly redirected to /dashboard!")

    print("\nALL TEMPLATES LIBRARY V2 QA TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    run_templates_library_tests()
