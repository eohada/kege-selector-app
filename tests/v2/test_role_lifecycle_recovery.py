from datetime import timedelta
from pathlib import Path

import pytest

def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def test_live_layouts_use_neutral_local_avatar_fallbacks():
    project_root = Path(__file__).resolve().parents[2]
    for layout_name in (
        'layout_teacher.html', 'layout_admin.html', 'layout_parent.html',
        'layout_preview.html', 'components/dev_switcher.html',
        'assignment_detail.html', 'students.html', 'teacher_dashboard.html',
        'mentor_profile.html', 'parents_dashboard.html', 'preparation.html',
        '_dev_role_switcher.html', 'admin/users.html', 'admin/testers.html',
        'profile/_parent_body.html',
        '../assignment_view.html', '../groups_list.html', '../review_queue.html',
    ):
        content = (project_root / 'templates' / 'sandbox' / layout_name).resolve().read_text(encoding='utf-8')
        assert "images/default-avatar.svg" in content
        assert "api.dicebear.com" not in content


def test_active_v2_navigation_layouts_do_not_reference_sandbox_routes():
    project_root = Path(__file__).resolve().parents[2]
    active_templates = (
        'layout_student.html', 'layout_teacher.html', 'layout_admin.html',
        'profile.html', 'task_detail.html', 'theory.html',
        'task_generator.html', 'trainer.html', 'course_map.html',
        'parents_faq.html',
        'admin/tester_entities.html', 'admin/topics.html', 'admin/users.html',
        'admin/audit.html', 'admin/qa_dashboard.html', 'admin/promocodes.html',
        'admin/task_formator.html', 'admin/diagnostics.html',
    )
    for template_name in active_templates:
        content = (project_root / 'templates' / 'sandbox' / template_name).read_text(encoding='utf-8')
        assert '/sandbox/' not in content, template_name


def test_first_step_achievement_matches_its_real_trigger():
    from app.utils.achievement_service import ACHIEVEMENTS_REGISTRY

    first_step = ACHIEVEMENTS_REGISTRY['first_step']
    assert first_step['category'] == 'tasks'
    assert 'работ' in first_step['desc'].lower()


def test_dynamic_achievements_use_persisted_student_values(app, role_users):
    from app import db
    from app.models import Student, UserAchievement
    from app.utils.achievement_service import check_and_grant_dynamic_achievements

    with app.app_context():
        student = db.session.get(Student, role_users['student_id'])
        student.streak_days = 3
        student.level = 5
        student.xp = 1000
        db.session.commit()

        check_and_grant_dynamic_achievements(student)
        unlocked = {
            row.achievement_key
            for row in UserAchievement.query.filter_by(student_id=student.student_id).all()
        }

    assert {'streak_3', 'lvl_5', 'xp_1000'} <= unlocked


def test_legacy_compatibility_entries_redirect_to_v2_surfaces(app, client, role_users):
    login_as(client, role_users['student_user_id'], 'student')
    lesson_mode = client.get(f"/student/{role_users['student_id']}/lesson-mode", follow_redirects=False)
    assert lesson_mode.status_code == 302
    assert f"/students/{role_users['student_id']}" in lesson_mode.headers['Location']

    public_profile = client.get(f"/user/{role_users['tutor_id']}", follow_redirects=False)
    assert public_profile.status_code == 302
    assert f"/workspace/people/{role_users['tutor_id']}" in public_profile.headers['Location']

    anonymous_index = app.test_client().get('/index', follow_redirects=False)
    assert anonymous_index.status_code == 302
    assert anonymous_index.headers['Location'] in {'/landing', '/dashboard'}


def test_classwork_compatibility_route_redirects_to_the_v2_lesson_room(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get(f"/lesson/{role_users['student_id']}/classwork-tasks", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f"/lesson/{role_users['student_id']}/room?pane=work")


def test_homework_compatibility_route_sends_student_to_v2_submissions(client, role_users):
    lesson_id = role_users['student_id']

    login_as(client, role_users['student_user_id'], 'student')
    student_response = client.get(f'/lesson/{lesson_id}/homework-tasks', follow_redirects=False)
    assert student_response.status_code == 302
    assert student_response.headers['Location'].endswith('/submissions')


def test_homework_compatibility_route_sends_tutor_to_v2_assignment_creation(client, role_users):
    lesson_id = role_users['student_id']
    login_as(client, role_users['tutor_id'], 'tutor')
    tutor_response = client.get(f'/lesson/{lesson_id}/homework-tasks', follow_redirects=False)
    assert tutor_response.status_code == 302
    assert '/assignments/create?' in tutor_response.headers['Location']
    assert 'assignment_type=homework' in tutor_response.headers['Location']


def test_teacher_grading_uses_the_v2_teacher_layout():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'submission_grade.html').read_text(encoding='utf-8')
    assert "{% extends 'sandbox/layout_teacher.html' %}" in content
    assert "{% block sandbox_content %}" in content


def test_teacher_student_dashboard_links_to_the_real_analytics_surface():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'sandbox' / 'teacher_dashboard.html').read_text(encoding='utf-8')

    assert "url_for('students.student_analytics', student_id=student.student_id)" in content
    assert 'Траектории и детальный радар находятся в разработке' not in content


def test_parent_faq_is_a_real_v2_help_surface_not_a_development_placeholder():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'sandbox' / 'parents_faq.html').read_text(encoding='utf-8')

    assert 'Раздел FAQ находится в разработке' not in content
    assert "url_for('main.parents_dashboard')" in content
    assert "url_for('main.parents_schedule')" in content


def test_student_info_activity_uses_server_summary_not_a_development_placeholder():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'student_info.html').read_text(encoding='utf-8')

    assert 'Активность в разработке' not in content
    assert 'activity_summary.completed_lessons' in content
    assert 'activity_summary.submitted_works' in content
    assert 'activity_summary.graded_works' in content


def test_student_info_activity_summary_renders_for_the_assigned_tutor(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get(f"/student/{role_users['student_id']}/info")

    assert response.status_code == 200
    assert 'Активность в разработке'.encode('utf-8') not in response.data


def test_student_management_auxiliary_screens_use_v2_shells():
    project_root = Path(__file__).resolve().parents[2]
    teacher_templates = (
        'student_form.html', 'lesson_form.html', 'student_chat.html',
        'student_call_request.html', 'student_info.html',
        'student_learning_plan.html', 'student_gradebook.html',
        'student_diagnostics.html',
    )
    for template_name in teacher_templates:
        content = (project_root / 'templates' / template_name).read_text(encoding='utf-8')
        assert "{% extends 'sandbox/layout_teacher.html' %}" in content
        assert "{% extends 'base.html' %}" not in content

    notifications = (project_root / 'templates' / 'notifications.html').read_text(encoding='utf-8')
    assert "{% extends 'base.html' %}" not in notifications
    assert "sandbox/layout_student.html" in notifications
    assert "{% extends 'base.html' %}" not in content


def test_lesson_homework_uses_v2_layouts_for_every_role():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'lesson_homework.html').read_text(encoding='utf-8')
    assert '"sandbox/layout_student.html" if (is_student_view or is_parent_view) else "sandbox/layout_teacher.html"' in content
    assert "{% block extra_head %}" in content
    assert "{% extends \"base.html\" %}" not in content


def test_library_materials_and_templates_use_the_v2_teacher_layout():
    project_root = Path(__file__).resolve().parents[2]
    for template_name in ('library_materials.html', 'library_lesson_templates.html'):
        content = (project_root / 'templates' / template_name).read_text(encoding='utf-8')
        assert "{% extends 'sandbox/layout_teacher.html' %}" in content
        assert "{% block sandbox_content %}" in content
        assert "{% extends 'base.html' %}" not in content


def test_billing_management_screens_use_the_v2_admin_layout():
    project_root = Path(__file__).resolve().parents[2]
    for template_name in ('billing_plans.html', 'billing_subscriptions.html'):
        content = (project_root / 'templates' / template_name).read_text(encoding='utf-8')
        assert "{% extends 'sandbox/layout_admin.html' %}" in content
        assert "{% block sandbox_content %}" in content
        assert "{% extends 'base.html' %}" not in content


def test_assignment_management_list_uses_the_v2_teacher_layout():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'assignments_list.html').read_text(encoding='utf-8')
    assert "{% extends 'sandbox/layout_teacher.html' %}" in content
    assert "{% block sandbox_content %}" in content
    assert "{% block extra_scripts %}" in content
    assert "{% extends 'base.html' %}" not in content


def test_assignment_management_create_edit_and_view_use_the_v2_teacher_layout():
    project_root = Path(__file__).resolve().parents[2]
    for template_name in ('assignment_create.html', 'assignment_edit.html', 'assignment_view.html'):
        content = (project_root / 'templates' / template_name).read_text(encoding='utf-8')
        assert "{% extends 'sandbox/layout_teacher.html' %}" in content
        assert "{% block sandbox_content %}" in content
        assert "{% block extra_scripts %}" in content
        assert "{% extends 'base.html' %}" not in content


def test_generator_review_lists_use_the_v2_teacher_layout():
    project_root = Path(__file__).resolve().parents[2]
    for template_name in ('accepted.html', 'skipped.html'):
        content = (project_root / 'templates' / template_name).read_text(encoding='utf-8')
        assert "{% extends 'sandbox/layout_teacher.html' %}" in content
        assert "{% block sandbox_content %}" in content
        assert "{% block extra_scripts %}" in content
        assert "{% extends 'base.html' %}" not in content


def test_generator_results_use_v2_and_continue_in_canonical_assignment_wizard():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'results.html').read_text(encoding='utf-8')
    assert "{% extends 'sandbox/layout_teacher.html' %}" in content
    assert "{% block sandbox_content %}" in content
    assert "ASSIGNMENT_CREATE_URL" in content
    assert "source: 'generator'" in content
    assert "{% extends 'base.html' %}" not in content


def test_manual_generator_starts_without_demo_task_data():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'sandbox' / 'task_generator.html').read_text(encoding='utf-8')

    assert 'value="Демоверсия ФИПИ"' not in content
    assert 'value="Поразрядная конъюнкция и логика"' not in content
    assert 'value="12"' not in content
    assert 'return (x & 29 != 0)' not in content
    assert 'id="manual-content" rows="4" required' in content
    assert 'id="manual-answer" required' in content


def test_student_profile_progress_uses_real_xp_without_demo_fallbacks():
    project_root = Path(__file__).resolve().parents[2]
    profile_body = (project_root / 'templates' / 'sandbox' / 'profile' / '_student_body.html').read_text(encoding='utf-8')
    routes = (project_root / 'app' / 'main' / 'routes.py').read_text(encoding='utf-8')
    assert 'else 3450' not in profile_body
    assert 'else 4000' not in profile_body
    assert 'width: 86%' not in profile_body
    assert "'level': 1" in profile_body
    assert "student_stats = student_stats or" in profile_body
    assert "all_achievements|length if all_achievements is defined else 0" in profile_body
    assert 'student_stats.xp_progress_pct' in profile_body
    assert "'xp_progress_pct'" in routes


def test_schedule_uses_the_correct_v2_role_layout():
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / 'templates' / 'schedule.html').read_text(encoding='utf-8')
    assert "sandbox/layout_teacher.html" in content
    assert "sandbox/layout_student.html" in content
    assert "sandbox/layout_parent.html" in content
    assert "{% block sandbox_content %}" in content
    assert "{% block extra_scripts %}" in content
    assert "{% extends 'base.html' %}" not in content


def test_groups_route_is_owned_by_the_v2_groups_blueprint(app):
    matching_endpoints = [
        rule.endpoint for rule in app.url_map.iter_rules()
        if rule.rule == '/groups' and 'GET' in rule.methods
    ]

    assert matching_endpoints == ['groups.groups_list']


def test_role_switcher_user_list_is_admin_only_and_never_seeds_demo_users(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')
    assert client.get('/api/dev/users').status_code == 403

    login_as(client, role_users['creator_id'], 'creator')
    response = client.get('/api/dev/users')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert {user['username'] for user in payload['users']} == {
        'v2_creator', 'v2_student', 'v2_tutor'
    }
    assert all('/static/images/default-avatar.svg' == user['avatar'] or user['avatar'] for user in payload['users'])


def test_dev_switcher_rejects_student_and_anonymous_impersonation(app, client, role_users):
    anonymous = app.test_client().get(
        f"/sandbox/impersonate/{role_users['student_user_id']}",
        follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert '/login' in anonymous.headers['Location']

    login_as(client, role_users['student_user_id'], 'student')
    denied = client.get(
        f"/sandbox/impersonate/{role_users['tutor_id']}",
        follow_redirects=False,
    )
    assert denied.status_code in {302, 403}
    if denied.status_code == 302:
        assert '/login' in denied.headers['Location']
    role_change = client.post('/api/dev/switch_role', json={'role': 'admin'})
    assert role_change.status_code in {302, 403}
    if role_change.status_code == 302:
        assert '/login' in role_change.headers['Location']


def test_student_cannot_open_teacher_assignment_list(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    response = client.get('/assignments')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/submissions') or response.headers['Location'].endswith('/dashboard')


def test_dev_impersonation_opens_student_v2_dashboard_and_assignments(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get(f"/sandbox/impersonate/{role_users['student_user_id']}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')

    assert client.get('/dashboard').status_code == 200
    assert client.get('/submissions').status_code == 200


def test_admin_impersonation_redirects_student_to_v2_dashboard(client, role_users):
    login_as(client, role_users['creator_id'], 'creator')

    response = client.get(f"/admin/impersonate/{role_users['student_user_id']}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')


def test_student_cannot_change_xp_or_achievements_through_debug_endpoints(client, role_users):
    """Debug-механика не является пользовательской функцией даже в тестовом приложении."""
    login_as(client, role_users['student_user_id'], 'student')

    xp_response = client.post(
        f"/api/student/{role_users['student_id']}/debug-xp",
        json={'xp': 999999},
    )
    achievement_response = client.post(
        f"/api/student/{role_users['student_id']}/debug-achievements",
        json={'achievement_key': 'xp_10000', 'action': 'grant'},
    )
    streak_response = client.post(
        f"/api/student/{role_users['student_id']}/debug-streak",
        json={'streak_days': 999},
    )

    assert xp_response.status_code == 403
    assert achievement_response.status_code == 403
    assert streak_response.status_code == 403


def test_enrollment_student_is_visible_in_tutor_roster(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get('/students')

    assert response.status_code == 200
    assert 'V2 Fixture Student' in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ('role', 'routes'),
    (
        ('student', ('/dashboard', '/schedule', '/submissions', '/theory', '/workspace/profile')),
        ('tutor', ('/students', '/schedule', '/assignments', '/library', '/analytics')),
        ('creator', ('/dashboard', '/workspace/profile')),
        ('admin', ('/admin/users', '/admin/permissions', '/admin/promocodes', '/admin/qa')),
    ),
)
def test_core_v2_entry_points_render_for_each_platform_role(app, role_users, role, routes):
    from app import db
    from app.models import Course, User, UserRole

    with app.app_context():
        admin = User(
            username='v2_release_admin', email='v2_release_admin@example.test',
            role='admin', is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        db.session.add(UserRole(user_id=admin.id, role='admin'))
        db.session.add(Course(title='V2 release theory course', slug='v2-release-theory'))
        db.session.commit()
        admin_id = admin.id

    user_ids = {
        'student': role_users['student_user_id'],
        'tutor': role_users['tutor_id'],
        'creator': role_users['creator_id'],
        'admin': admin_id,
    }
    role_client = app.test_client()
    login_as(role_client, user_ids[role], role)
    for route in routes:
        response = role_client.get(route)
        assert response.status_code == 200, f'{role}: {route} returned {response.status_code}'


def test_parent_v2_entry_points_and_child_link_lifecycle(app, role_users):
    from app import db
    from app.models import User
    from core.db_models import FamilyTie

    with app.app_context():
        parent = User(
            username='v2_release_parent', email='v2_release_parent@example.test',
            role='parent', is_active=True,
        )
        db.session.add(parent)
        db.session.flush()
        parent_id = parent.id
        db.session.commit()

    parent_client = app.test_client()
    login_as(parent_client, parent_id, 'parent')
    linked = parent_client.post(
        '/api/parent/link_child',
        json={'student_code_or_email': 'v2_student'},
    )
    assert linked.status_code == 200, linked.get_data(as_text=True)

    for route in ('/parents/dashboard', '/parents/schedule', '/parents/faq', '/workspace/profile'):
        response = parent_client.get(route)
        assert response.status_code == 200, f'parent: {route} returned {response.status_code}'

    unlinked = parent_client.delete(f"/api/parent/unlink_child/{role_users['student_user_id']}")
    assert unlinked.status_code == 200, unlinked.get_data(as_text=True)

    with app.app_context():
        assert FamilyTie.query.filter_by(
            parent_id=parent_id,
            student_id=role_users['student_user_id'],
        ).first() is None


def test_legacy_student_pages_redirect_to_live_controllers(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    expected = {
        '/sandbox/theory': '/theory',
        '/sandbox/trainer': '/dashboard',
        '/sandbox/schedule': '/schedule',
        '/sandbox/profile': '/workspace/profile',
        '/sandbox/student_dashboard': '/dashboard',
    }
    for legacy_url, canonical_url in expected.items():
        response = client.get(legacy_url)
        assert response.status_code == 302
        assert response.headers['Location'].endswith(canonical_url)

    trainer_response = client.get('/trainer/v2')
    assert trainer_response.status_code == 404


def test_legacy_generator_url_redirects_to_canonical_v2(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get('/sandbox/task_generator?assignment_type=classwork')

    assert response.status_code == 302
    assert '/task-generator' in response.headers['Location']
    assert 'assignment_type=classwork' in response.headers['Location']


def test_legacy_assignment_task_detail_api_is_not_exposed(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    response = client.post('/sandbox/api/task_detail/1/submit_assignment', json={'answers': {}})
    assert response.status_code in {404, 405}


def test_profile_uses_canonical_api_and_legacy_api_only_redirects(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    updated = client.post('/api/profile/edit', json={'about_me': 'Мой собственный текст'})
    assert updated.status_code == 200
    assert updated.get_json()['success'] is True

    created = client.post('/api/profile/goal/add', json={'title': 'Решить вариант'})
    assert created.status_code == 201

    legacy = client.post('/sandbox/api/profile/goal/add', json={'title': 'Не потерять запрос'}, follow_redirects=False)
    assert legacy.status_code == 307
    assert legacy.headers['Location'].endswith('/api/profile/goal/add')


def test_profile_uploads_are_persisted_and_served_from_configured_roots(app, client, role_users, tmp_path):
    import io

    avatar_root = tmp_path / 'avatars'
    cover_root = tmp_path / 'covers'
    app.config.update(AVATAR_UPLOAD_ROOT=str(avatar_root), COVER_UPLOAD_ROOT=str(cover_root))
    login_as(client, role_users['student_user_id'], 'student')
    image = b'\x89PNG\r\n\x1a\n' + b'profile-image'

    response = client.post(
        '/api/profile/edit',
        data={
            'avatar_file': (io.BytesIO(image), 'avatar.png'),
            'cover_file': (io.BytesIO(image), 'cover.png'),
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200

    with app.app_context():
        from app import db
        from app.models import User
        user = db.session.get(User, role_users['student_user_id'])
        avatar_url, cover_url = user.avatar_url, user.cover_url

    assert avatar_url and cover_url
    assert client.get(avatar_url).status_code == 200
    assert client.get(cover_url).status_code == 200


def test_profile_edit_never_persists_the_neutral_avatar_as_user_data(app, client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    response = client.post(
        '/api/profile/edit',
        json={'avatar_url': '/static/images/default-avatar.svg', 'about_me': 'Без фальшивой аватарки'},
    )
    assert response.status_code == 200

    with app.app_context():
        from app import db
        from app.models import User
        user = db.session.get(User, role_users['student_user_id'])
        assert user.avatar_url in (None, '')
        assert user.about_me == 'Без фальшивой аватарки'


def test_profile_upload_rejects_non_image_extension(client, role_users):
    import io

    login_as(client, role_users['student_user_id'], 'student')
    response = client.post(
        '/api/profile/edit',
        data={'avatar_file': (io.BytesIO(b'not an image'), 'avatar.txt')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 400
    assert response.get_json()['success'] is False


def test_legacy_profile_media_names_remain_available_after_v2_upgrade(app, client, role_users, tmp_path):
    avatar_root = tmp_path / 'avatars'
    cover_root = tmp_path / 'covers'
    avatar_root.mkdir()
    cover_root.mkdir()
    (avatar_root / 'avatar 120 1786431010.jpg').write_bytes(b'legacy-avatar')
    (cover_root / 'cover 120 1786431010.jpg').write_bytes(b'legacy-cover')
    app.config.update(AVATAR_UPLOAD_ROOT=str(avatar_root), COVER_UPLOAD_ROOT=str(cover_root))

    assert client.get('/avatars/avatar%20120%201786431010.jpg').status_code == 200
    assert client.get('/covers/cover%20120%201786431010.jpg').status_code == 200


def test_profile_metrics_are_derived_from_submissions(app, client, role_users):
    from app import db
    from core.db_models import Assignment, Submission, utc_now

    with app.app_context():
        db.session.query(Submission).delete(synchronize_session=False)
        db.session.commit()
        from core.db_models import Student
        stud_rec = Student.query.filter_by(user_id=role_users['student_user_id']).first()
        actual_student_id = stud_rec.student_id if stud_rec else role_users['student_id']
        assignment = Assignment(
            title='Fixture assignment',
            assignment_type='homework',
            deadline=utc_now() + timedelta(days=1),
            created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(Submission(
            assignment_id=assignment.assignment_id,
            student_id=actual_student_id,
            status='GRADED',
            total_score=7,
            max_score=10,
            percentage=70,
        ))
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    response = client.get('/workspace/profile')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '/' in html
    assert '70' in html
    assert 'Виктор Менторов' not in html
    assert 'Анна Сергеева' not in html


def test_tutor_student_assignment_lifecycle_end_to_end(app, client, role_users):
    from app import db
    from core.db_models import AssignmentTask, Student, Submission, Tasks, UserAchievement, utc_now

    with app.app_context():
        task = Tasks(task_number=1, content_html='<p>Release task</p>', answer='42')
        db.session.add(task)
        db.session.commit()
        task_id = task.task_id

    login_as(client, role_users['tutor_id'], 'tutor')
    distributed = client.post('/assignments/distribute', json={
        'title': 'Release lifecycle assignment',
        'type': 'homework',
        'deadline': (utc_now() + timedelta(days=1)).isoformat(),
        'tasks': [{'task_id': task_id, 'max_score': 1}],
        'recipientIds': [role_users['student_id']],
    })
    assert distributed.status_code == 201, distributed.get_json()
    assignment_id = distributed.get_json()['assignment_id']
    with app.app_context():
        submission = Submission.query.filter_by(assignment_id=assignment_id, student_id=role_users['student_id']).one()
        submission_id = submission.submission_id
        assignment_task_id = AssignmentTask.query.filter_by(assignment_id=assignment_id).one().assignment_task_id

    login_as(client, role_users['student_user_id'], 'student')
    assert client.get('/submissions').status_code == 200
    assert client.post(f'/submissions/{submission_id}/start').status_code == 200
    saved = client.put(f'/submissions/{submission_id}/autosave', json={
        'answers': [{'assignment_task_id': assignment_task_id, 'value': '42'}],
    })
    assert saved.status_code == 200
    submitted = client.post(f'/submissions/{submission_id}/submit', json={
        'task_times': {str(assignment_task_id): 15},
    })
    assert submitted.status_code == 200, submitted.get_json()
    assert submitted.get_json()['awarded_xp'] == 15

    repeated_submit = client.post(f'/submissions/{submission_id}/submit', json={
        'task_times': {str(assignment_task_id): 15},
    })
    assert repeated_submit.status_code == 400

    login_as(client, role_users['tutor_id'], 'tutor')
    impersonated = client.get(
        f"/sandbox/impersonate/{role_users['student_user_id']}",
        follow_redirects=False,
    )
    assert impersonated.status_code == 302
    assert client.get(f'/submissions/{submission_id}').status_code == 200

    with app.app_context():
        rewarded_student = db.session.get(Student, role_users['student_id'])
        assert rewarded_student.xp == 15
        assert rewarded_student.streak_days == 1
        assert {
            item.achievement_key
            for item in UserAchievement.query.filter_by(student_id=rewarded_student.student_id).all()
        } == {'first_step'}

    reverted = client.get('/sandbox/impersonate/revert', follow_redirects=False)
    assert reverted.status_code == 302
    graded = client.post(f'/submissions/{submission_id}/grade', json={
        'scores': [{'assignment_task_id': assignment_task_id, 'score': 1, 'comment': 'Верно'}],
        'teacher_feedback': 'Отличная работа',
        'status': 'GRADED',
    })
    assert graded.status_code == 200, graded.get_json()

    login_as(client, role_users['student_user_id'], 'student')
    result = client.get(f'/submissions/{submission_id}')
    assert result.status_code == 200
    result_html = result.get_data(as_text=True)
    assert '/task-workspace/?context_type=submission_task' in result_html
    assert '/sandbox/workspace/' not in result_html
    assert '/sandbox/api/task_detail/' not in result_html
    assert '/sandbox/api/assignment/' not in result_html
    assert '/sandbox/tasks' not in result_html
    assert 'function submissionUrl(path)' in result_html
    assert "submissionUrl('autosave')" in result_html
    assert "submissionUrl('submit-task')" in result_html
    assert "submissionUrl('comments')" in result_html
    with app.app_context():
        final_submission = db.session.get(Submission, submission_id)
        assert final_submission.status == 'GRADED'
        assert final_submission.total_score == 1
        assert final_submission.percentage == 100


def test_returned_submission_only_reopens_selected_tasks(app, role_users):
    """A teacher can return one task without reopening unrelated answers."""
    from app import db
    from core.db_models import Answer, Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        first_task = Tasks(task_number=6, content_html='<p>First revision task</p>', answer='11')
        second_task = Tasks(task_number=7, content_html='<p>Second locked task</p>', answer='22')
        db.session.add_all([first_task, second_task])
        db.session.flush()
        assignment = Assignment(
            title='Selective revision assignment',
            assignment_type='manual_review',
            deadline=utc_now() + timedelta(days=1),
            created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        first_assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=first_task.task_id,
            max_score=1,
            requires_manual_grading=True,
        )
        second_assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=second_task.task_id,
            max_score=1,
            requires_manual_grading=True,
        )
        db.session.add_all([first_assignment_task, second_assignment_task])
        db.session.flush()
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=role_users['student_id'],
            status='SUBMITTED',
            started_at=utc_now(),
            submitted_at=utc_now(),
        )
        db.session.add(submission)
        db.session.flush()
        db.session.add_all([
            Answer(
                submission_id=submission.submission_id,
                assignment_task_id=first_assignment_task.assignment_task_id,
                value='old first answer',
                max_score=1,
            ),
            Answer(
                submission_id=submission.submission_id,
                assignment_task_id=second_assignment_task.assignment_task_id,
                value='old second answer',
                max_score=1,
            ),
        ])
        db.session.commit()
        submission_id = submission.submission_id
        first_assignment_task_id = first_assignment_task.assignment_task_id
        second_assignment_task_id = second_assignment_task.assignment_task_id

    tutor_client = app.test_client()
    login_as(tutor_client, role_users['tutor_id'], 'tutor')
    returned = tutor_client.post(f'/submissions/{submission_id}/grade', json={
        'status': 'RETURNED',
        'teacher_feedback': 'Please revise only the first task.',
        'return_assignment_task_ids': [first_assignment_task_id],
        'scores': [
            {'assignment_task_id': first_assignment_task_id, 'score': 0},
            {'assignment_task_id': second_assignment_task_id, 'score': 1},
        ],
    })
    assert returned.status_code == 200, returned.get_json()
    with app.app_context():
        returned_answers = {
            answer.assignment_task_id: answer
            for answer in Answer.query.filter_by(submission_id=submission_id).all()
        }
        assert returned_answers[first_assignment_task_id].needs_revision is True
        assert returned_answers[second_assignment_task_id].needs_revision is False

    student_client = app.test_client()
    login_as(student_client, role_users['student_user_id'], 'student')
    first_workspace_query = {
        'context_type': 'submission_task',
        'context_id': submission_id,
        'assignment_task_id': first_assignment_task_id,
    }
    second_workspace_query = {
        'context_type': 'submission_task',
        'context_id': submission_id,
        'assignment_task_id': second_assignment_task_id,
    }
    assert student_client.get('/task-workspace/', query_string=first_workspace_query).status_code == 200
    assert student_client.post('/task-workspace/api/save', json={
        **first_workspace_query,
        'code': 'print("revised")',
        'answer': 'revised first answer',
    }).status_code == 200
    assert student_client.get('/task-workspace/', query_string=second_workspace_query).status_code == 200
    assert student_client.post('/task-workspace/api/save', json={
        **second_workspace_query,
        'code': 'print("blocked")',
        'answer': 'attempted workspace overwrite',
    }).status_code == 403
    autosaved = student_client.put(f'/submissions/{submission_id}/autosave', json={
        'answers': [
            {'assignment_task_id': first_assignment_task_id, 'value': 'revised first answer'},
            {'assignment_task_id': second_assignment_task_id, 'value': 'attempted overwrite'},
        ],
    })
    assert autosaved.status_code == 200, autosaved.get_json()
    resubmitted = student_client.post(f'/submissions/{submission_id}/submit', json={})
    assert resubmitted.status_code == 200, resubmitted.get_json()

    with app.app_context():
        submission = db.session.get(Submission, submission_id)
        answers = {
            answer.assignment_task_id: answer
            for answer in Answer.query.filter_by(submission_id=submission_id).all()
        }
        assert submission.status == 'SUBMITTED'
        assert answers[first_assignment_task_id].needs_revision is True
        assert answers[first_assignment_task_id].value == 'revised first answer'
        assert answers[second_assignment_task_id].needs_revision is False
        assert answers[second_assignment_task_id].value == 'old second answer'


def test_workspace_persists_versions_and_playback_history(app, role_users):
    """Ordinary autosaves keep the student's existing replay history intact."""
    from app import db
    from app.models import Student, User
    from core.db_models import Answer, Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks(task_number=2, content_html='<p>Workspace release task</p>', answer='7')
        db.session.add(task)
        db.session.flush()
        assignment = Assignment(
            title='Workspace lifecycle assignment',
            assignment_type='homework',
            deadline=utc_now() + timedelta(days=1),
            created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(assignment_id=assignment.assignment_id, task_id=task.task_id, max_score=1)
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=role_users['student_id'],
            status='IN_PROGRESS',
            started_at=utc_now(),
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.submission_id
        assignment_task_id = assignment_task.assignment_task_id

    student_client = app.test_client()
    login_as(student_client, role_users['student_user_id'], 'student')
    workspace_query = {
        'context_type': 'submission_task',
        'context_id': submission_id,
        'assignment_task_id': assignment_task_id,
    }
    assert student_client.get('/task-workspace/', query_string=workspace_query).status_code == 200
    first_save = student_client.post('/task-workspace/api/save', json={
        **workspace_query,
        'code': 'print(7)',
        'answer': '7',
        'playback_frames': [{'line': 1, 'at': 1}],
    })
    assert first_save.status_code == 200, first_save.get_json()
    versions = first_save.get_json()['versions']
    assert versions['count'] == 1
    version_id = versions['items'][0]['version_id']

    second_save = student_client.post('/task-workspace/api/save', json={
        **workspace_query,
        'code': 'print(8)',
        'answer': '8',
    })
    assert second_save.status_code == 200
    state = student_client.get('/task-workspace/api/state', query_string=workspace_query)
    assert state.status_code == 200
    assert state.get_json()['state']['code'] == 'print(8)'
    assert state.get_json()['state']['playback']['frame_count'] == 1

    restored = student_client.post(f'/task-workspace/api/versions/{version_id}/restore', json=workspace_query)
    assert restored.status_code == 200
    assert restored.get_json()['code'] == 'print(7)'
    with app.app_context():
        answer = Answer.query.filter_by(submission_id=submission_id, assignment_task_id=assignment_task_id).one()
        assert answer.student_code == 'print(7)'


def test_workspace_allows_tutor_review_but_not_mutation(app, role_users):
    from app import db
    from core.db_models import Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks(task_number=3, content_html='<p>Tutor review workspace</p>')
        db.session.add(task)
        db.session.flush()
        assignment = Assignment(
            title='Tutor review workspace', assignment_type='homework',
            deadline=utc_now() + timedelta(days=1), created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(assignment_id=assignment.assignment_id, task_id=task.task_id, max_score=1)
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(assignment_id=assignment.assignment_id, student_id=role_users['student_id'], status='IN_PROGRESS')
        db.session.add(submission)
        db.session.commit()
        workspace_query = {
            'context_type': 'submission_task',
            'context_id': submission.submission_id,
            'assignment_task_id': assignment_task.assignment_task_id,
        }

    tutor_client = app.test_client()
    login_as(tutor_client, role_users['tutor_id'], 'tutor')
    page = tutor_client.get('/task-workspace/', query_string=workspace_query)
    assert page.status_code == 200
    assert '"can_edit": false' in page.get_data(as_text=True).lower()
    denied = tutor_client.post('/task-workspace/api/save', json={**workspace_query, 'code': 'print(999)'})
    assert denied.status_code == 403


def test_workspace_rejects_unrelated_student(app, role_users):
    from app import db
    from app.models import Student, User
    from core.db_models import Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        outsider = User(username='workspace_access_denied', email='workspace_access_denied@example.test', role='student', is_active=True)
        task = Tasks(task_number=4, content_html='<p>Private workspace</p>')
        db.session.add_all([outsider, task])
        db.session.flush()
        db.session.add(Student(name='Workspace access denied', user_id=outsider.id, is_active=True))
        assignment = Assignment(
            title='Private workspace', assignment_type='homework',
            deadline=utc_now() + timedelta(days=1), created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(assignment_id=assignment.assignment_id, task_id=task.task_id, max_score=1)
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(assignment_id=assignment.assignment_id, student_id=role_users['student_id'], status='IN_PROGRESS')
        db.session.add(submission)
        db.session.commit()
        workspace_query = {
            'context_type': 'submission_task',
            'context_id': submission.submission_id,
            'assignment_task_id': assignment_task.assignment_task_id,
        }
        outsider_id = outsider.id

    outsider_client = app.test_client()
    login_as(outsider_client, outsider_id, 'student')
    assert outsider_client.get('/task-workspace/api/state', query_string=workspace_query).status_code == 403
