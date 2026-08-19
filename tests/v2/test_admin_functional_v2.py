import json
from datetime import datetime, timezone
from io import BytesIO

from app import db
from app.auth.rbac_utils import has_permission
from app.models import Course, Enrollment, FamilyTie, Lesson, MaintenanceMode, PromoCode, PromoCodeUsage, RolePermission, Student, TaskReview, Tasks, Tester as QaEntity, Topic, User, UserRole
from core.db_models import BugReport as QaBugReport, TestCase as QaTestCase

def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def _admin(app):
    with app.app_context():
        user = User(username='admin_functional_v2', email='admin_functional_v2@example.test', role='admin', is_active=True)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserRole(user_id=user.id, role='admin'))
        db.session.commit()
        return user.id


def test_permissions_matrix_reads_and_persists_real_role_permissions(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    page = client.get('/admin/permissions')
    assert page.status_code == 200
    assert 'RolePermissions' in page.get_data(as_text=True)

    response = client.post('/admin/permissions/toggle', json={
        'permission_key': 'trainer.use', 'role': 'tester', 'enabled': True,
    })
    assert response.status_code == 200
    with app.app_context():
        record = RolePermission.query.filter_by(role='tester', permission_name='trainer.use').one()
        assert record.is_enabled is True


def test_permissions_matrix_rejects_invalid_toggle_payload(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    response = client.post('/admin/permissions/toggle', json={
        'permission_key': 'unknown.permission', 'role': 'admin', 'enabled': 'true',
    })
    assert response.status_code == 400
    assert response.get_json()['success'] is False


def test_data_export_import_preserves_student_lesson_relation(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    payload = {
        'export_schema_version': 2,
        'students': [{
            'student_source_id': 901,
            'student_key': 'student:901',
            'name': 'Imported relation student',
            'platform_id': 'imported-relation-student',
            'school_class': 11,
        }],
        'lessons': [{
            'student_source_id': 901,
            'student_key': 'student:901',
            'student_id': 901,
            'lesson_type': 'regular',
            'lesson_date': '2026-08-17T12:00:00',
            'duration': 60,
            'status': 'planned',
            'topic': 'Связанный импорт',
        }],
    }
    imported = client.post(
        '/import-data',
        data={'file': (BytesIO(json.dumps(payload).encode('utf-8')), 'export.json')},
        content_type='multipart/form-data',
    )
    assert imported.status_code == 302

    with app.app_context():
        student = Student.query.filter_by(platform_id='imported-relation-student').one()
        lesson = Lesson.query.filter_by(topic='Связанный импорт').one()
        assert lesson.student_id == student.student_id


def test_data_export_keeps_archived_student_for_historical_lessons(app, client):
    admin_id = _admin(app)
    with app.app_context():
        student = Student(
            name='Archived export student',
            platform_id='archived-export-student',
            is_active=False,
        )
        db.session.add(student)
        db.session.flush()
        db.session.add(Lesson(
            student_id=student.student_id,
            lesson_type='regular',
            topic='Исторический урок архивного ученика',
            lesson_date=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        ))
        db.session.commit()

    login_as(client, admin_id, 'admin')
    response = client.get('/export-data')
    assert response.status_code == 200
    exported = json.loads(response.get_data(as_text=True))
    archived_student = next(
        item for item in exported['students']
        if item['platform_id'] == 'archived-export-student'
    )
    historical_lesson = next(
        item for item in exported['lessons']
        if item['topic'] == 'Исторический урок архивного ученика'
    )
    assert archived_student['is_active'] is False
    assert historical_lesson['student_key'] == archived_student['student_key']


def test_explicit_permission_denial_overrides_role_default(app):
    with app.app_context():
        user = User(username='tutor_permission_v2', email='tutor_permission_v2@example.test', role='tutor', is_active=True)
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.add(UserRole(user_id=user.id, role='tutor'))
        rp = RolePermission.query.filter_by(role='tutor', permission_name='trainer.use').first()
        if rp:
            rp.is_enabled = False
        else:
            db.session.add(RolePermission(role='tutor', permission_name='trainer.use', is_enabled=False))
        db.session.commit()
        assert has_permission(db.session.get(User, user_id), 'trainer.use') is False


def test_diagnostics_and_export_use_real_platform_data(app, client):
    admin_id = _admin(app)
    with app.app_context():
        db.session.add(Course(title='Export V2 course', slug='export-v2-course'))
        db.session.commit()
    login_as(client, admin_id, 'admin')

    toggle = client.post('/admin/maintenance/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert toggle.status_code == 200
    assert toggle.get_json()['success'] is True
    page = client.get('/admin/diagnostics')
    assert page.status_code == 200
    with app.app_context():
        assert MaintenanceMode.get_status().is_enabled is True

    exported = client.get('/admin/export_db_json')
    assert exported.status_code == 200
    payload = exported.get_json()
    assert payload['export_schema_version'] == 2
    assert any(course['slug'] == 'export-v2-course' for course in payload['courses'])
    assert {'users', 'lessons', 'tasks', 'system_settings'} <= payload.keys()


def test_qa_case_steps_and_bug_status_are_persisted(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    created = client.post('/admin/qa/test-cases/create', data={
        'title': 'V2 QA form case',
        'area': 'admin',
        'steps': '[{"action_text":"Open admin panel","expected_result":"Dashboard opens"}]',
    })
    assert created.status_code == 200
    case_id = created.get_json()['test_case_id']
    with app.app_context():
        case = db.session.get(QaTestCase, case_id)
        assert case is not None
        assert len(case.steps) == 1
        assert case.steps[0].expected_result == 'Dashboard opens'
        bug = QaBugReport(title='V2 QA bug', reporter_id=admin_id, status='NEW')
        db.session.add(bug)
        db.session.flush()
        bug_id = bug.id
        db.session.commit()

    updated = client.post(f'/admin/qa/bug-reports/{bug_id}/status', json={'status': 'resolved'})
    assert updated.status_code == 200
    assert updated.get_json()['status'] == 'RESOLVED'
    with app.app_context():
        assert db.session.get(QaBugReport, bug_id).status == 'RESOLVED'


def test_topic_form_submission_and_task_review_are_persisted(app, client):
    admin_id = _admin(app)
    with app.app_context():
        task = Tasks(task_number=1, content_html='<p>Task</p>', answer='1')
        db.session.add(task)
        db.session.commit()
        task_id = task.task_id
    login_as(client, admin_id, 'admin')

    topic_response = client.post('/admin/topics/create', data={'name': 'V2 audit topic', 'description': 'created from form'})
    assert topic_response.status_code == 200
    with app.app_context():
        assert Topic.query.filter_by(name='V2 audit topic').one().description == 'created from form'

    review_response = client.post('/admin/task-formator/status', json={'task_id': task_id, 'status': 'needs_fix'})
    assert review_response.status_code == 200
    with app.app_context():
        review = TaskReview.query.filter_by(task_id=task_id).one()
        assert review.status == 'needs_fix'
        assert review.reviewer_user_id == admin_id


def test_bento_user_modal_returns_json_and_updates_profile(app, client):
    admin_id = _admin(app)
    with app.app_context():
        user = User(username='editable_v2', email='editable_v2@example.test', role='student', is_active=True)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserRole(user_id=user.id, role='student'))
        db.session.commit()
        user_id = user.id
    login_as(client, admin_id, 'admin')

    response = client.post(f'/admin/users/{user_id}/edit', data={
        'full_name': 'Updated V2 User', 'email': 'updated_v2@example.test',
        'role': 'student', 'is_active': 'false',
    }, headers={'Accept': 'application/json'})
    assert response.status_code == 200
    assert response.get_json()['success'] is True
    with app.app_context():
        updated = db.session.get(User, user_id)
        assert updated.email == 'updated_v2@example.test'
        assert updated.is_active is False
        assert updated.profile.first_name == 'Updated'


def test_bento_user_creation_obeys_role_boundaries(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    blocked = client.post('/admin/users/create', data={
        'full_name': 'Escalation attempt', 'username': 'creator_attempt_v2',
        'email': 'creator_attempt_v2@example.test', 'password': 'StrongPass123', 'role': 'creator',
    })
    assert blocked.status_code == 403

    created = client.post('/admin/users/create', data={
        'full_name': 'Created Student', 'username': 'created_student_v2',
        'email': 'created_student_v2@example.test', 'password': 'StrongPass123', 'role': 'student',
    })
    assert created.status_code == 201
    user_id = created.get_json()['user_id']
    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.role == 'student'
        assert user.profile.first_name == 'Created'
        assert UserRole.query.filter_by(user_id=user_id, role='student').one()

    deleted = client.post(f'/admin/users/{user_id}/delete', json={}, headers={'Accept': 'application/json'})
    assert deleted.status_code == 200
    assert deleted.get_json()['success'] is True
    with app.app_context():
        assert db.session.get(User, user_id) is None
        assert UserRole.query.filter_by(user_id=user_id).count() == 0


def test_admin_graph_reflects_family_and_enrollment_links(app, client):
    admin_id = _admin(app)
    with app.app_context():
        parent = User(username='graph_parent_v2', email='graph_parent_v2@example.test', role='parent', is_active=True)
        tutor = User(username='graph_tutor_v2', email='graph_tutor_v2@example.test', role='tutor', is_active=True)
        student = User(username='graph_student_v2', email='graph_student_v2@example.test', role='student', is_active=True)
        db.session.add_all([parent, tutor, student])
        db.session.flush()
        db.session.add_all([
            FamilyTie(parent_id=parent.id, student_id=student.id, is_confirmed=True),
            Enrollment(tutor_id=tutor.id, student_id=student.id, subject='informatics', status='active'),
        ])
        db.session.commit()
        parent_id, tutor_id, student_id = parent.id, tutor.id, student.id
    login_as(client, admin_id, 'admin')

    graph = client.get('/admin/users/graph_data')
    assert graph.status_code == 200
    payload = graph.get_json()
    assert {parent_id, tutor_id, student_id} <= {node['id'] for node in payload['nodes']}
    assert any(edge['from'] == parent_id and edge['to'] == student_id and edge['label'] == 'PARENT' for edge in payload['edges'])
    assert any(edge['from'] == tutor_id and edge['to'] == student_id and edge['label'] == 'TEACHER' for edge in payload['edges'])

    audit = client.get('/admin/audit?source=db&action=toggle_permission&status=success')
    assert audit.status_code == 200


def test_all_bento_admin_sections_render_for_admin(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    for path in (
        '/admin/users',
        '/admin/permissions',
        '/admin/audit?source=db',
        '/admin/qa',
        '/admin/tester-entities',
        '/admin/topics',
        '/admin/task-formator',
        '/admin/diagnostics',
        '/admin/promocodes',
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_admin_promocode_lifecycle_is_persisted_and_used_codes_are_not_deleted(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    created = client.post('/admin/promocodes', data={
        'code': 'release_2026', 'discount_percent': '25', 'is_active': 'on',
    })
    assert created.status_code == 302
    with app.app_context():
        promo = PromoCode.query.filter_by(code='RELEASE_2026').one()
        promo_id = promo.id
        assert promo.discount_percent == 25
        assert promo.is_active is True

    updated = client.post(f'/admin/promocodes/{promo_id}', data={
        'code': 'release_2026', 'bonus_days': '14', 'usage_limit': '3',
    })
    assert updated.status_code == 302
    with app.app_context():
        promo = db.session.get(PromoCode, promo_id)
        assert promo.bonus_days == 14
        assert promo.usage_limit == 3
        db.session.add(PromoCodeUsage(promocode_id=promo_id, user_id=admin_id))
        db.session.commit()

    deleted = client.post(f'/admin/promocodes/{promo_id}/delete')
    assert deleted.status_code == 302
    with app.app_context():
        retained = db.session.get(PromoCode, promo_id)
        assert retained is not None
        assert retained.is_active is False

    invalid = client.post('/admin/promocodes', data={'code': 'bad code', 'discount_percent': '20'})
    assert invalid.status_code == 302
    with app.app_context():
        assert PromoCode.query.filter_by(code='BAD CODE').count() == 0


def test_tester_entity_created_from_bento_form_is_active(app, client):
    admin_id = _admin(app)
    login_as(client, admin_id, 'admin')

    response = client.post('/admin/tester-entities/create', data={'name': 'Bento QA entity'})
    assert response.status_code == 302
    with app.app_context():
        tester = QaEntity.query.filter_by(name='Bento QA entity').one()
        assert tester.is_active is True
        tester_id = tester.tester_id

    deleted = client.post(f'/admin/tester-entities/{tester_id}/delete')
    assert deleted.status_code == 302
    with app.app_context():
        assert db.session.get(QaEntity, tester_id) is None
