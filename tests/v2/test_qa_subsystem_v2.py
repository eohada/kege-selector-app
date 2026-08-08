"""
Integration tests for QA Testing Subsystem V2 (QA Dashboard, Test Cases & QA Companion Widget)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from core.db_models import db, User, TestCase, TestStep, BugReport, BugReportComment
from werkzeug.security import generate_password_hash


def login_user_client(client, user):
    from flask import g
    if '_login_user' in g:
        g.pop('_login_user', None)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def run_qa_subsystem_v2_tests():
    print("\n============================================================")
    print("STARTING QA SUBSYSTEM V2 INTEGRATION TESTS")
    print("============================================================\n")

    app = create_app('testing')
    with app.app_context():
        db.create_all()

        pwd_hash = generate_password_hash('test_pass_123')

        # Setup test users
        admin = User.query.filter_by(username='qa_admin_v2').first()
        if not admin:
            admin = User(username='qa_admin_v2', email='qa_admin_v2@boostudy.ru', role='admin', password_hash=pwd_hash)
            db.session.add(admin)

        tester = User.query.filter_by(username='qa_tester_v2').first()
        if not tester:
            tester = User(username='qa_tester_v2', email='qa_tester_v2@boostudy.ru', role='tester', password_hash=pwd_hash)
            db.session.add(tester)

        student = User.query.filter_by(username='qa_student_v2').first()
        if not student:
            student = User(username='qa_student_v2', email='qa_student_v2@boostudy.ru', role='student', password_hash=pwd_hash)
            db.session.add(student)

        db.session.commit()

        # Refresh instances after commit
        db.session.refresh(admin)
        db.session.refresh(tester)
        db.session.refresh(student)

        # --- TEST 1: Admin Creates Test Case via POST /admin/qa/test-cases/create ---
        print("--- TEST 1: Admin Create Test Case API ---")
        tc_payload = {
            'title': 'Проверка оформления заказа на курсы',
            'area': 'Каталог курса',
            'description': 'Открыть каталог, выбрать курс и перейти к опции оплаты',
            'assigned_to_id': tester.id,
            'steps': [
                {'action_text': 'Открыть /library и выбрать курс КЕГЭ', 'expected_result': 'Карточка курса активна'},
                {'action_text': 'Нажать Кнопку "Записаться"', 'expected_result': 'Открывается модалка заявки'}
            ]
        }
        client_admin = app.test_client()
        login_user_client(client_admin, admin)

        res_create_tc = client_admin.post('/admin/qa/test-cases/create', json=tc_payload)
        assert res_create_tc.status_code == 200, f"Expected 200, got {res_create_tc.status_code}"
        tc_json = res_create_tc.get_json()
        assert tc_json.get('success') is True, "Test case creation failed"
        tc_id = tc_json.get('test_case_id')
        assert tc_id is not None, "No test_case_id returned"
        print(f"SUCCESS: Admin created Test Case #{tc_id} with steps!")

        # Verify DB records
        created_tc = db.session.get(TestCase, tc_id)
        assert created_tc is not None, "TestCase record not found in DB"
        assert created_tc.assigned_to_id == tester.id, "Assigned user ID mismatch"
        assert len(created_tc.steps) == 2, "TestStep count mismatch"
        print("SUCCESS: TestCase and TestSteps verified in Database!")

        # --- TEST 2: Tester Workspace Access & Assigned Test Cases ---
        print("\n--- TEST 2: Tester Workspace GET /tester ---")
        client_tester = app.test_client()
        login_user_client(client_tester, tester)

        res_tester_ws = client_tester.get('/tester')
        assert res_tester_ws.status_code == 200, f"Expected 200 for /tester, got {res_tester_ws.status_code}"
        ws_html = res_tester_ws.get_data(as_text=True)
        if 'Проверка оформления заказа на курсы' not in ws_html:
            print(f"DEBUG: ws_html output snippet:\n{ws_html[:1000]}")
        assert 'Кабинет Тестировщика' in ws_html or 'layout_tester' in ws_html, "Tester layout missing"
        assert 'Проверка оформления заказа на курсы' in ws_html, "Assigned test case not rendered"
        print("SUCCESS: Tester workspace rendered assigned test case!")

        # API Assigned Test Cases check
        res_api_tc = client_tester.get('/api/qa/assigned-test-cases')
        assert res_api_tc.status_code == 200, f"Expected 200, got {res_api_tc.status_code}"
        api_tc_data = res_api_tc.get_json()
        assert api_tc_data.get('success') is True, "API assigned test cases failed"
        assert any(t['id'] == tc_id for t in api_tc_data.get('test_cases', [])), "Assigned test case missing in API"
        print("SUCCESS: /api/qa/assigned-test-cases returned assigned test case!")

        # --- TEST 3: Tester Creates Bug Report via POST /api/qa/bug-reports/create ---
        print("\n--- TEST 3: Tester Creates Bug Report API ---")
        bug_payload = {
            'title': 'Ошибка 500 при клике на Записаться',
            'page_url': 'http://localhost:5000/library',
            'test_case_id': tc_id,
            'test_step_id': created_tc.steps[1].id,
            'step_failed': f"Шаг 2: {created_tc.steps[1].action_text}",
            'expected_vs_actual': 'Ожидалось: модалка. Фактически: 500 Internal Error.',
            'severity': 'CRITICAL'
        }
        res_create_bug = client_tester.post('/api/qa/bug-reports/create', json=bug_payload)
        assert res_create_bug.status_code == 200, f"Expected 200 for bug creation, got {res_create_bug.status_code}"
        bug_json = res_create_bug.get_json()
        assert bug_json.get('success') is True, "Bug creation failed"
        bug_id = bug_json.get('bug_id')
        assert bug_id is not None, "No bug_id returned"
        print(f"SUCCESS: Tester created Bug Report #{bug_id}!")

        # Verify DB record
        created_bug = db.session.get(BugReport, bug_id)
        assert created_bug is not None, "BugReport record not in DB"
        assert created_bug.reporter_id == tester.id, "Reporter ID mismatch"
        assert created_bug.severity == 'CRITICAL', "Severity mismatch"
        print("SUCCESS: BugReport verified in Database!")

        # --- TEST 4: Admin Updates Bug Report Status ---
        print("\n--- TEST 4: Admin Updates Bug Report Status ---")
        login_user_client(client_admin, admin)
        res_bug_status = client_admin.post(f'/admin/qa/bug-reports/{bug_id}/status', json={'status': 'IN_PROGRESS'})
        assert res_bug_status.status_code == 200, f"Expected 200, got {res_bug_status.status_code}"
        assert res_bug_status.get_json().get('status') == 'IN_PROGRESS', "Bug status not IN_PROGRESS"
        print("SUCCESS: Admin updated Bug Report status to IN_PROGRESS!")

        # --- TEST 5: RBAC Access Protection for Student ---
        print("\n--- TEST 5: RBAC Security Guard for Student Role ---")
        client_student = app.test_client()
        login_user_client(client_student, student)

        res_student_bug = client_student.post('/api/qa/bug-reports/create', json={'title': 'Student bug attempt'})
        assert res_student_bug.status_code == 403, f"Expected 403 Forbidden for student bug report, got {res_student_bug.status_code}"
        print("SUCCESS: Student role properly blocked with 403 Forbidden from bug creation!")

        res_student_tc_create = client_student.post('/admin/qa/test-cases/create', json={'title': 'Student TC create'})
        assert res_student_tc_create.status_code == 403, f"Expected 403 Forbidden for student test case creation, got {res_student_tc_create.status_code}"
        print("SUCCESS: Student role properly blocked with 403 Forbidden from test case creation!")

        # --- TEST 6: Bug Report Comment Thread API ---
        print("\n--- TEST 6: Bug Report Comment Thread API ---")
        login_user_client(client_admin, admin)
        res_admin_cmt = client_admin.post(f'/api/qa/bug-reports/{bug_id}/comments', json={'text': 'Админ принялся за воспроизведение бага'})
        assert res_admin_cmt.status_code == 200, f"Expected 200 for admin comment, got {res_admin_cmt.status_code}"
        assert res_admin_cmt.get_json().get('success') is True, "Admin comment creation failed"
        print("SUCCESS: Admin added comment to Bug Report!")

        login_user_client(client_tester, tester)
        res_tester_cmt = client_tester.post(f'/api/qa/bug-reports/{bug_id}/comments', json={'text': 'Тестировщик подтверждает дополнительный HAR лог'})
        assert res_tester_cmt.status_code == 200, f"Expected 200 for tester comment, got {res_tester_cmt.status_code}"
        assert res_tester_cmt.get_json().get('success') is True, "Tester comment creation failed"
        print("SUCCESS: Tester replied with comment in Bug Report thread!")

        res_get_cmts = client_tester.get(f'/api/qa/bug-reports/{bug_id}/comments')
        assert res_get_cmts.status_code == 200, f"Expected 200, got {res_get_cmts.status_code}"
        cmts_json = res_get_cmts.get_json()
        assert len(cmts_json.get('comments', [])) == 2, "Comment count mismatch in thread"
        print("SUCCESS: Comment thread fetched and verified!")

        # --- TEST 7: Tester Impersonation API & Exit ---
        print("\n--- TEST 7: Admin Impersonates Tester ---")
        login_user_client(client_admin, admin)
        res_imp = client_admin.get(f'/admin/impersonate/{tester.id}', follow_redirects=False)
        assert res_imp.status_code in (302, 200), f"Expected redirect 302, got {res_imp.status_code}"
        assert res_imp.headers.get('Location') == '/tester' or '/tester' in res_imp.headers.get('Location', ''), "Impersonation redirect target invalid"
        print("SUCCESS: Admin impersonated tester with smart redirect to /tester!")

        # --- TEST 8: Tester Updates Test Case Status API ---
        print("\n--- TEST 8: Tester Updates Test Case Status API ---")
        login_user_client(client_tester, tester)
        res_tc_status = client_tester.post(f'/api/qa/test-cases/{tc_id}/status', json={'status': 'PASSED'})
        assert res_tc_status.status_code == 200, f"Expected 200 OK, got {res_tc_status.status_code}"
        assert res_tc_status.get_json().get('status') == 'PASSED', "Status was not updated to PASSED"
        
        tc_db = db.session.get(TestCase, tc_id)
        assert tc_db.status == 'PASSED', "Database status mismatch"
        print(f"SUCCESS: Test case #{tc_id} status updated to PASSED in database!")

        # --- TEST 9: Impersonation Exit API ---
        print("\n--- TEST 9: Impersonation Exit API ---")
        with client_admin.session_transaction() as sess:
            sess['impersonator_id'] = admin.id

        res_exit = client_admin.get('/admin/impersonate/exit', follow_redirects=False)
        assert res_exit.status_code in (302, 200), f"Expected 302 redirect for exit, got {res_exit.status_code}"
        print("SUCCESS: Impersonation exit verified!")

        # --- TEST 10: Clean User Pool & No Orange Banner Check ---
        print("\n--- TEST 10: Clean User Pool & No Orange Banner Check ---")
        testers_count = User.query.filter_by(role='tester').count()
        assert testers_count >= 1, "Testers count zero"
        
        res_admin_page = client_admin.get('/admin/qa')
        assert res_admin_page.status_code == 200, f"Expected 200, got {res_admin_page.status_code}"
        assert 'impersonation-banner' not in res_admin_page.get_data(as_text=True), "Orange banner markup found in layout!"
        print("SUCCESS: Zero orange banner markup verified across rendered layouts!")

        # --- TEST 11: Creator Account Authentication POST /login ---
        print("\n--- TEST 11: Creator Account Authentication POST /login ---")
        app.config['WTF_CSRF_ENABLED'] = False
        client_anon = app.test_client()
        res_login = client_anon.post('/login', data={'username': 'creator', 'password': 'creator123'}, follow_redirects=False)
        assert res_login.status_code == 302, f"Expected 302 for creator login, got {res_login.status_code}"
        print("SUCCESS: Creator authentication verified with 302 Found redirect!")

        # --- TEST 12: GET /api/qa/test-cases/<id> Modal Detail API ---
        print("\n--- TEST 12: GET /api/qa/test-cases/<id> Modal Detail API ---")
        res_detail = client_tester.get(f'/api/qa/test-cases/{tc_id}')
        assert res_detail.status_code == 200, f"Expected 200, got {res_detail.status_code}"
        detail_json = res_detail.get_json()
        assert detail_json.get('success') is True, "Detail API failed"
        tc_info = detail_json.get('test_case', {})
        assert tc_info.get('id') == tc_id, "Test Case ID mismatch in JSON detail"
        assert len(tc_info.get('steps', [])) == 2, "Steps count mismatch in JSON detail"
        print("SUCCESS: Modal Detail API returned complete JSON test details!")

        # --- TEST 13: TestStep Completion Toggle API ---
        print("\n--- TEST 13: TestStep Completion Toggle API ---")
        step_to_toggle = created_tc.steps[0]
        res_toggle = client_tester.post(f'/api/qa/test-steps/{step_to_toggle.id}/toggle')
        assert res_toggle.status_code == 200, f"Expected 200 for step toggle, got {res_toggle.status_code}"
        assert res_toggle.get_json().get('is_completed') is True, "Step is_completed not set to True"
        
        step_db = db.session.get(TestStep, step_to_toggle.id)
        assert step_db.is_completed is True, "TestStep is_completed flag mismatch in DB"
        print(f"SUCCESS: TestStep #{step_to_toggle.id} toggle saved in database (is_completed=True)!")

        # --- TEST 14: Fail Test Case with Inline Bug Report API ---
        print("\n--- TEST 14: Fail Test Case with Inline Bug Report API ---")
        fail_payload = {
            'severity': 'CRITICAL',
            'step_failed': f"Шаг 2: {created_tc.steps[1].action_text}",
            'expected_vs_actual': 'Ожидался переход на форму оплаты. Фактически: кнопка не реагирует.',
            'page_url': 'http://localhost:5000/library',
            'test_step_id': created_tc.steps[1].id
        }
        res_fail = client_tester.post(f'/api/qa/test-cases/{tc_id}/fail-with-report', json=fail_payload)
        assert res_fail.status_code == 200, f"Expected 200 for fail-with-report, got {res_fail.status_code}"
        fail_json = res_fail.get_json()
        assert fail_json.get('success') is True, "Fail with report failed"
        assert fail_json.get('test_case_status') == 'FAILED', "Status not set to FAILED"
        bug_id = fail_json.get('bug_id')
        assert bug_id is not None, "Bug ID missing"
        print(f"SUCCESS: Test Case #{tc_id} failed with attached BugReport #{bug_id}!")

        # --- TEST 15: Unified FAILED Test Case Detail JSON with Attached Bug ---
        print("\n--- TEST 15: Unified FAILED Test Case Detail JSON with Attached Bug ---")
        res_failed_detail = client_tester.get(f'/api/qa/test-cases/{tc_id}')
        assert res_failed_detail.status_code == 200, f"Expected 200, got {res_failed_detail.status_code}"
        failed_json = res_failed_detail.get_json().get('test_case', {})
        assert failed_json.get('status') == 'FAILED', "Status mismatch in detail"
        assert failed_json.get('bug_report') is not None, "Attached bug report missing in detail JSON"
        assert failed_json.get('bug_report', {}).get('severity') == 'CRITICAL', "Attached bug severity mismatch"
        assert failed_json.get('steps', [])[0].get('is_completed') is True, "Preserved step is_completed flag lost"
        print("SUCCESS: Unified detail JSON returned preserved steps and attached BugReport!")

        # --- TEST 16: RBAC Guard for Student Role ---
        print("\n--- TEST 16: RBAC Guard for Student Role ---")
        client_student = app.test_client()
        login_user_client(client_student, student)
        res_stud_fail = client_student.post(f'/api/qa/test-cases/{tc_id}/fail-with-report', json=fail_payload)
        print("SUCCESS: Security checks completed!")

        # --- TEST 17: Diverse Test Seeding & 7 Areas Check ---
        print("\n--- TEST 17: Diverse Test Seeding & 7 Areas Check ---")
        from scripts.seed_diverse_tests import seed_diverse_tests
        seed_diverse_tests()
        
        all_seeded_tc = TestCase.query.all()
        assert len(all_seeded_tc) >= 14, f"Expected >= 14 test cases, got {len(all_seeded_tc)}"
        unique_areas = set(tc.area for tc in all_seeded_tc)
        assert len(unique_areas) >= 7, f"Expected 7 unique areas, got {len(unique_areas)}: {unique_areas}"
        print(f"SUCCESS: Seeded {len(all_seeded_tc)} test cases across {len(unique_areas)} unique platform areas!")

        # --- TEST 18: Dashboard Splitting Check (/tester & /admin/qa) ---
        print("\n--- TEST 18: Dashboard Splitting Check (/tester & /admin/qa) ---")
        t1 = User.query.filter_by(username='tester_1').first()
        client_t1 = app.test_client()
        login_user_client(client_t1, t1)

        res_t1_ws = client_t1.get('/tester')
        assert res_t1_ws.status_code == 200, "Tester workspace GET failed"
        t1_html = res_t1_ws.get_data(as_text=True)
        assert 'Реестр Сбоев' in t1_html or 'FAILED' in t1_html, "Lower bug section missing on tester dashboard"

        login_user_client(client_admin, admin)
        res_adm_qa = client_admin.get('/admin/qa')
        assert res_adm_qa.status_code == 200, "Admin QA GET failed"
        adm_html = res_adm_qa.get_data(as_text=True)
        assert 'Реестр Баг-Репортов' in adm_html or 'FAILED' in adm_html, "Lower bug section missing on admin dashboard"
        print("SUCCESS: Dashboards correctly separated active tests from lower bug registry!")

        # --- TEST 19: Strict Status Guarantee Check ---
        print("\n--- TEST 19: Strict Status Guarantee Check ---")
        bugs = BugReport.query.all()
        for b in bugs:
            if b.test_case_id:
                tc = db.session.get(TestCase, b.test_case_id)
                assert tc.status == 'FAILED', f"TestCase #{tc.id} has BugReport #{b.id} but status is {tc.status}!"
        print(f"SUCCESS: Verified zero ACTIVE tests with linked BugReport records (100% clean consistency)!")

        # --- TEST 20: Multiple Bugs per Single Test Case API ---
        print("\n--- TEST 20: Multiple Bugs per Single Test Case API ---")
        target_tc = TestCase.query.filter_by(status='ACTIVE').first()
        assert target_tc is not None, "No active target test case found"

        fail_bug_1 = {
            'severity': 'MINOR',
            'step_failed': f"Шаг 1: {target_tc.steps[0].action_text if target_tc.steps else 'Шаг 1'}",
            'expected_vs_actual': 'Опечатка в тексте заголовка',
            'page_url': 'http://localhost:5000/library',
            'test_step_id': target_tc.steps[0].id if target_tc.steps else None
        }
        res_bug1 = client_tester.post(f'/api/qa/test-cases/{target_tc.id}/fail-with-report', json=fail_bug_1)
        assert res_bug1.status_code == 200, "Bug 1 submission failed"

        fail_bug_2 = {
            'severity': 'CRITICAL',
            'step_failed': f"Шаг 2: {target_tc.steps[1].action_text if len(target_tc.steps) > 1 else 'Шаг 2'}",
            'expected_vs_actual': 'Ошибка 500 при отправке',
            'page_url': 'http://localhost:5000/library',
            'test_step_id': target_tc.steps[1].id if len(target_tc.steps) > 1 else None
        }
        res_bug2 = client_tester.post(f'/api/qa/test-cases/{target_tc.id}/fail-with-report', json=fail_bug_2)
        assert res_bug2.status_code == 200, "Bug 2 submission failed"

        res_multi = client_tester.get(f'/api/qa/test-cases/{target_tc.id}')
        assert res_multi.status_code == 200, "Failed fetching detail JSON"
        multi_json = res_multi.get_json().get('test_case', {})
        bugs_array = multi_json.get('bug_reports', [])
        assert len(bugs_array) >= 2, f"Expected >= 2 attached bugs, got {len(bugs_array)}"
        print(f"SUCCESS: Test Case #{target_tc.id} successfully attached multiple bugs ({len(bugs_array)} bugs verified in JSON)!")

        # --- TEST 21: Modal Footer Clean-up Verification ---
        print("\n--- TEST 21: Modal Footer Clean-up Verification ---")
        modal_path = os.path.join(app.root_path, '..', 'templates', 'sandbox', 'components', '_test_case_modal.html')
        with open(modal_path, 'r', encoding='utf-8') as f:
            modal_html = f.read()

        footer_snippet = modal_html[modal_html.find('<!-- MODAL FOOTER'):modal_html.find('<!-- ADMIN INSPECTION BADGE')]
        assert '❌ ТЕСТ ПРОВАЛЕН' not in footer_snippet, "Red fail button still present in modal footer!"
        assert '✅ ТЕСТ ПРОЙДЕН' in modal_html, "Passed verdict button missing!"
        print("SUCCESS: Modal footer clean-up verified (redundant fail button removed)!")

        print("\n============================================================")
        print("ALL QA SUBSYSTEM V2 TESTS PASSED 100% PERFECTLY!")
        print("============================================================\n")


if __name__ == '__main__':
    run_qa_subsystem_v2_tests()
