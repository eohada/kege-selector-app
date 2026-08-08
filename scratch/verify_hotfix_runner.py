import sys
import os
sys.path.insert(0, os.path.abspath('e:/projects/kege_selector_app_current'))

from wsgi import app
from core.db_models import User

app.config['WTF_CSRF_ENABLED'] = False
client = app.test_client()

with app.app_context():
    teacher = User.query.filter_by(role='tutor').first() or User.query.filter_by(role='teacher').first() or User.query.first()
    assert teacher is not None, "Teacher user not found"

    print(f"[1] Testing as User ID {teacher.id} (role={teacher.role})...")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['sandbox_role'] = 'teacher'
        sess['_fresh'] = True

    # 1. GET /schedule
    r_sched = client.get('/schedule')
    print(f"  GET /schedule -> {r_sched.status_code}")
    assert r_sched.status_code == 200, f"Expected 200, got {r_sched.status_code}"
    html_sched = r_sched.data.decode('utf-8')
    assert 'hour-rows' in html_sched, "hour-rows container missing from /schedule"
    assert 'days-header' in html_sched, "days-header missing from /schedule"
    assert 'time-marker' in html_sched, "time-marker missing from /schedule"
    assert 'modal-new-lesson' in html_sched, "modal-new-lesson missing from /schedule"
    print("  ✓ /schedule HTML & grid structure validated successfully!")

    # 2. GET /sandbox/teacher_schedule
    r_tsched = client.get('/sandbox/teacher_schedule')
    print(f"  GET /sandbox/teacher_schedule -> {r_tsched.status_code}")
    assert r_tsched.status_code == 200, f"Expected 200, got {r_tsched.status_code}"
    print("  ✓ /sandbox/teacher_schedule returns 200 OK!")

    # 3. GET /sandbox/student_schedule
    with client.session_transaction() as sess:
        sess['sandbox_role'] = 'student'
    r_ssched = client.get('/sandbox/student_schedule')
    print(f"  GET /sandbox/student_schedule -> {r_ssched.status_code}")
    assert r_ssched.status_code == 200, f"Expected 200, got {r_ssched.status_code}"
    print("  ✓ /sandbox/student_schedule returns 200 OK!")

    # 4. GET /sandbox/api/impersonate/users
    r_imp_users = client.get('/sandbox/api/impersonate/users')
    print(f"  GET /sandbox/api/impersonate/users -> {r_imp_users.status_code}")
    assert r_imp_users.status_code == 200, f"Expected 200, got {r_imp_users.status_code}"
    imp_json = r_imp_users.get_json()
    assert 'users' in imp_json, "'users' key missing from impersonate users API response"
    print(f"  ✓ Impersonate users API returned {len(imp_json.get('users', []))} users!")

    # 5. Check Dev Role Switcher script in layout
    assert 'dev-role-switcher-widget' in html_sched or '_dev_role_switcher' in html_sched or 'toggleDevRoleSwitcher' in html_sched or 'KeyI' in html_sched, "Dev switcher script missing from template"
    print("  ✓ Dev Role Switcher widget and shortcut script verified in layout!")

print("\n🎉 ALL CRITICAL HOTFIX TESTS PASSED 100% PERFECTLY!")
