"""
BooStudy / ORISTERA — Student Schedule Sprint 2.0.1
Automated Acceptance & Data Integrity Diagnostics Runner for `/schedule`.
Uses Playwright Chromium and Isolated Test SQLite Database.

Verifies:
1. Single Teacher attribution (mentor name shown on lesson card).
2. Multi-Teacher isolation (neutral fallback "Преподаватель курса" when student has 2+ tutors).
3. Materials isolation (only attached materials rendered, no leakage from other lessons).
4. Notes isolation (teacher advice container only rendered when note exists).
5. Cancelled lesson semantics ("Отменено" slate pill, excluded from completion base).
6. Homework lifecycle statuses (ASSIGNED, IN_PROGRESS, RETURNED, SUBMITTED).
7. Empty week state with mascot Boo.
8. Viewport geometry and zero horizontal scroll on mobile (390x844).
"""
import os
import sys
import time
import json
import threading
from datetime import datetime, timedelta, timezone as dt_timezone
from werkzeug.serving import make_server

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

ISOLATED_DB_PATH = '/tmp/test_schedule_sprint2_0_1.db'
if os.path.exists(ISOLATED_DB_PATH):
    try:
        os.remove(ISOLATED_DB_PATH)
    except Exception:
        pass

os.environ['DATABASE_URL'] = f'sqlite:///{ISOLATED_DB_PATH}'
os.environ['SQLITE_DB_PATH'] = ISOLATED_DB_PATH
os.environ['BOOSTUDY_SKIP_DATABASE_BOOTSTRAP'] = '1'
os.environ['BOOSTUDY_BACKGROUND_WORKERS_ENABLED'] = '0'
os.environ['SECRET_KEY'] = 'test-e2e-secret-key-sprint-2-0-1'
os.environ['WTF_CSRF_ENABLED'] = 'false'
os.environ['TESTING'] = '1'

from app import create_app, db
from core.db_models import User, Student, Lesson, Assignment, Submission, Enrollment
from werkzeug.security import generate_password_hash
from flask import jsonify, request, session
from flask_login import login_user

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{ISOLATED_DB_PATH}'

@app.route('/api/internal/test_login', methods=['POST'])
def test_login():
    data = request.get_json(force=True) or {}
    user_id = data.get('user_id')
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    login_user(user)
    session['_user_id'] = str(user.id)
    session['_fresh'] = True
    session['sandbox_role'] = 'student'
    return jsonify({'status': 'ok', 'user_id': user.id, 'role': user.role})


def seed_database():
    with app.app_context():
        db.create_all()

        now_utc = datetime.now(dt_timezone.utc)
        monday_utc = (now_utc - timedelta(days=now_utc.weekday())).replace(hour=14, minute=0, second=0, microsecond=0)

        # Teachers (username is persistent in SQLite, full_name falls back to username)
        tutor_ivan = User(id=91, username='Иван Сергеевич (Информатика)', email='ivan@test.com', password_hash=generate_password_hash('p'), role='tutor')
        tutor_elena = User(id=92, username='Елена Дмитриевна (Математика)', email='elena@test.com', password_hash=generate_password_hash('p'), role='tutor')
        db.session.add_all([tutor_ivan, tutor_elena])
        db.session.commit()

        # Persona 1: Single Teacher Student (mentor = Ivan)
        u_single_t = User(id=201, username='student_single_teacher', email='s1@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Алексей Однонаставников')
        db.session.add(u_single_t)
        db.session.commit()
        st_single_t = Student(student_id=201, user_id=201, name='Алексей Однонаставников', mentor_id=91, streak_days=4, is_active=True)
        db.session.add(st_single_t)

        l_single_t = Lesson(student_id=201, lesson_date=monday_utc + timedelta(days=1), duration=60, status='planned', topic='Графы и матрицы смежности')
        db.session.add(l_single_t)

        # Persona 2: Multi-Teacher Student (Enrollments with both Ivan and Elena)
        u_multi_t = User(id=202, username='student_multi_teacher', email='s2@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Мария Разнопредметная')
        db.session.add(u_multi_t)
        db.session.commit()
        st_multi_t = Student(student_id=202, user_id=202, name='Мария Разнопредметная', mentor_id=None, streak_days=2, is_active=True)
        db.session.add(st_multi_t)

        enr1 = Enrollment(student_id=202, tutor_id=91, subject='Информатика')
        enr2 = Enrollment(student_id=202, tutor_id=92, subject='Математика')
        db.session.add_all([enr1, enr2])

        l_multi_1 = Lesson(student_id=202, lesson_date=monday_utc + timedelta(days=1, hours=0), duration=60, status='planned', topic='Информатика: Динамика')
        l_multi_2 = Lesson(student_id=202, lesson_date=monday_utc + timedelta(days=1, hours=3), duration=60, status='planned', topic='Математика: Производные')
        db.session.add_all([l_multi_1, l_multi_2])

        # Persona 3: Materials & Notes Isolation
        u_mat = User(id=203, username='student_mat_notes', email='s3@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Даниил Изоляционный')
        db.session.add(u_mat)
        db.session.commit()
        st_mat = Student(student_id=203, user_id=203, name='Даниил Изоляционный', mentor_id=91, streak_days=0, is_active=True)
        db.session.add(st_mat)

        # Lesson A with specific materials and notes
        l_mat_a = Lesson(
            student_id=203,
            lesson_date=monday_utc + timedelta(days=2),
            duration=60,
            status='planned',
            topic='Теория чисел и остатки',
            student_notes='Повтори алгоритм Евклида перед началом занятия!',
            materials=[{'title': 'Алгоритм Евклида.pdf', 'url': '/docs/euclid.pdf', 'pages': '2 стр'}]
        )
        # Lesson B with NO materials and NO notes on the same day
        l_mat_b = Lesson(
            student_id=203,
            lesson_date=monday_utc + timedelta(days=2, hours=3),
            duration=60,
            status='planned',
            topic='Практикум: Разбор быстрых задач',
            student_notes='',
            notes='',
            materials=[]
        )
        db.session.add_all([l_mat_a, l_mat_b])

        # Persona 4: Cancelled, Completed, and Rescheduled Semantics
        u_status = User(id=204, username='student_statuses', email='s4@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Екатерина Статусная')
        db.session.add(u_status)
        db.session.commit()
        st_status = Student(student_id=204, user_id=204, name='Екатерина Статусная', mentor_id=91, streak_days=7, is_active=True)
        db.session.add(st_status)

        l_completed = Lesson(student_id=204, lesson_date=monday_utc + timedelta(days=0), duration=60, status='completed', topic='Стек вызовов и структуры данных')
        l_planned = Lesson(student_id=204, lesson_date=monday_utc + timedelta(days=1), duration=60, status='planned', topic='Очереди с приоритетом и куча')
        l_cancelled = Lesson(student_id=204, lesson_date=monday_utc + timedelta(days=3), duration=60, status='cancelled', topic='Отмененный урок по болезни')
        db.session.add_all([l_completed, l_planned, l_cancelled])

        # Persona 5: Homework Lifecycle Statuses
        u_hw = User(id=205, username='student_hw_lifecycle', email='s5@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Тимофей Дедлайнов')
        db.session.add(u_hw)
        db.session.commit()
        st_hw = Student(student_id=205, user_id=205, name='Тимофей Дедлайнов', mentor_id=91, streak_days=5, is_active=True)
        db.session.add(st_hw)

        a_assigned = Assignment(title='ДЗ: Позиционные системы счисления', assignment_type='homework', created_by_id=91, deadline=monday_utc + timedelta(days=1, hours=8), is_active=True)
        a_in_prog = Assignment(title='ДЗ: Логические выражения и таблицы истинности', assignment_type='homework', created_by_id=91, deadline=monday_utc + timedelta(days=2, hours=8), is_active=True)
        a_returned = Assignment(title='ДЗ: Поиск путей в графе (доработка)', assignment_type='homework', created_by_id=91, deadline=monday_utc + timedelta(days=3, hours=8), is_active=True)
        a_submitted = Assignment(title='ДЗ: Сортировка массивов и списков', assignment_type='homework', created_by_id=91, deadline=monday_utc + timedelta(days=4, hours=8), is_active=True)
        db.session.add_all([a_assigned, a_in_prog, a_returned, a_submitted])
        db.session.commit()

        s_assigned = Submission(assignment_id=a_assigned.assignment_id, student_id=205, status='ASSIGNED')
        s_in_prog = Submission(assignment_id=a_in_prog.assignment_id, student_id=205, status='IN_PROGRESS')
        s_returned = Submission(assignment_id=a_returned.assignment_id, student_id=205, status='RETURNED')
        s_submitted = Submission(assignment_id=a_submitted.assignment_id, student_id=205, status='SUBMITTED')
        db.session.add_all([s_assigned, s_in_prog, s_returned, s_submitted])

        # Persona 6: Empty Week Student
        u_empty = User(id=206, username='student_empty_vacation', email='s6@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Полина Каникулярная')
        db.session.add(u_empty)
        db.session.commit()
        st_empty = Student(student_id=206, user_id=206, name='Полина Каникулярная', mentor_id=91, streak_days=0, is_active=True)
        db.session.add(st_empty)

        db.session.commit()
        print('Sprint 2.0.1 acceptance database seeded successfully.')


class ServerThread(threading.Thread):
    def __init__(self, port=5578):
        super().__init__(daemon=True)
        self.port = port
        self.server = make_server('127.0.0.1', port, app.wsgi_app, threaded=True)

    def run(self):
        print(f'Test server started on http://127.0.0.1:{self.port}')
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def run_sprint_2_0_1_acceptance():
    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR = os.path.join(ROOT_DIR, 'docs', 'schedule_sprint2_0_1_screenshots')
    KEY_REVIEW_DIR = os.path.join(SCREENSHOT_DIR, 'key_review')
    VIEWPORTS_DIR = os.path.join(SCREENSHOT_DIR, 'viewports')
    SCENARIOS_DIR = os.path.join(SCREENSHOT_DIR, 'scenarios')

    for d in [SCREENSHOT_DIR, KEY_REVIEW_DIR, VIEWPORTS_DIR, SCENARIOS_DIR]:
        os.makedirs(d, exist_ok=True)

    server = ServerThread(port=5578)
    server.start()
    time.sleep(1.0)

    results = {
        'acceptance_criteria': {},
        'geometry_matrix': [],
        'key_screenshots': []
    }

    GEOMETRY_EVAL_SCRIPT = """
    (() => {
        const viewport = { width: window.innerWidth, height: window.innerHeight };
        const findings = [];
        const passes = [];

        // 1. Horizontal scroll check
        const scrollWidth = document.documentElement.scrollWidth;
        const clientWidth = document.documentElement.clientWidth;
        if (scrollWidth <= clientWidth + 2) {
            passes.push('zero-horizontal-scroll');
        } else {
            findings.push({ severity: 'ERROR', rule: 'horizontal-scroll', detail: `scrollWidth (${scrollWidth}) > clientWidth (${clientWidth})` });
        }

        // 2. 7-day ribbon tabs check
        const tabs = document.querySelectorAll('.unified-day-tab');
        if (tabs.length === 7) {
            passes.push('7-day-ribbon-complete');
        } else {
            findings.push({ severity: 'ERROR', rule: 'missing-tabs', detail: `Found ${tabs.length} tabs, expected 7` });
        }

        // 3. Mobile primary action CTA check
        if (viewport.width <= 430) {
            const primaryBtn = document.querySelector('.peer-event-card .btn-3d-primary') || document.querySelector('.peer-event-card a');
            if (primaryBtn) {
                const rect = primaryBtn.getBoundingClientRect();
                if (rect.bottom <= viewport.height) {
                    passes.push('mobile-action-cta-on-first-screen');
                } else {
                    findings.push({ severity: 'WARN', rule: 'mobile-cta-cutoff', detail: `Primary CTA bottom is ${Math.round(rect.bottom)}px, viewport height is ${viewport.height}px` });
                }
            }
        }

        return { viewport, findings, passes };
    })()
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def auth_session(context, user_id):
            page = context.new_page()
            resp = page.request.post('http://127.0.0.1:5578/api/internal/test_login', data=json.dumps({'user_id': user_id}), headers={'Content-Type': 'application/json'})
            assert resp.status == 200
            page.close()

        # =====================================================================
        # SCENARIO 1: Single Teacher Assigned (Persona 1, user_id=201)
        # =====================================================================
        print('\n--- Verifying Scenario 1: Single Teacher Assigned ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 201)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.click('#unified-tab-1')
        page.wait_for_timeout(300)

        card_text = page.locator('#unified-events-grid').text_content() or ''
        has_ivan = 'Иван Сергеевич' in card_text
        results['acceptance_criteria']['single_teacher_attributed_correctly'] = has_ivan
        print(f"Scenario 1: Mentor Ivan Sergeyevich shown: {has_ivan}")

        path_01 = os.path.join(KEY_REVIEW_DIR, '01_single_teacher_assigned.png')
        page.screenshot(path=path_01, full_page=False)
        results['key_screenshots'].append(path_01)
        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 2: Multi-Teacher Isolation (Persona 2, user_id=202)
        # =====================================================================
        print('\n--- Verifying Scenario 2: Multi-Teacher Neutral Fallback ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 202)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.click('#unified-tab-1')
        page.wait_for_timeout(300)

        card_text_multi = page.locator('#unified-events-grid').text_content() or ''
        has_neutral_fallback = 'Преподаватель курса' in card_text_multi
        results['acceptance_criteria']['multi_teacher_neutral_fallback'] = has_neutral_fallback
        print(f"Scenario 2: Neutral label 'Преподаватель курса' used (no false attribution): {has_neutral_fallback}")

        path_02 = os.path.join(KEY_REVIEW_DIR, '02_multi_teacher_neutral_fallback.png')
        page.screenshot(path=path_02, full_page=False)
        results['key_screenshots'].append(path_02)
        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 3: Materials & Notes Strict Isolation (Persona 3, user_id=203)
        # =====================================================================
        print('\n--- Verifying Scenario 3: Materials & Notes Strict Isolation ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 203)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.click('#unified-tab-2')
        page.wait_for_timeout(300)

        raw_data = page.evaluate("() => JSON.parse(document.getElementById('schedule-data').textContent)")
        wed_events = raw_data['weekdays'][2]['events']
        ev_a = [e for e in wed_events if e.get('title') == 'Теория чисел и остатки'][0]
        ev_b = [e for e in wed_events if e.get('title') == 'Практикум: Разбор быстрых задач'][0]

        mat_isolated = (len(ev_a['materials']) == 1 and ev_b['materials'] == [])
        notes_isolated = (bool(ev_a['notes']) and ev_b['notes'] == '')
        results['acceptance_criteria']['materials_isolated_without_leakage'] = mat_isolated
        results['acceptance_criteria']['notes_isolated_without_leakage'] = notes_isolated
        print(f"Scenario 3: Materials isolated without leakage: {mat_isolated}")
        print(f"Scenario 3: Notes isolated without leakage: {notes_isolated}")

        path_03 = os.path.join(KEY_REVIEW_DIR, '03_materials_and_notes_isolated.png')
        page.screenshot(path=path_03, full_page=False)
        results['key_screenshots'].append(path_03)
        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 4: Cancelled & Completed Semantics (Persona 4, user_id=204)
        # =====================================================================
        print('\n--- Verifying Scenario 4: Cancelled & Completed Semantics ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 204)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.click('#unified-tab-3')  # Thursday has cancelled lesson
        page.wait_for_timeout(300)

        card_text_canc = page.locator('#unified-events-grid').text_content() or ''
        has_cancelled_badge = 'Отменено' in card_text_canc

        stats_data = page.evaluate("() => JSON.parse(document.getElementById('schedule-data').textContent).weekly_stats")
        canc_excluded = (stats_data['conducted'] == 1 and stats_data['planned'] == 1 and stats_data['cancelled'] == 1 and stats_data['conducted_and_planned'] == 2 and stats_data['percent'] == 50)

        results['acceptance_criteria']['cancelled_lesson_badge_rendered'] = has_cancelled_badge
        results['acceptance_criteria']['cancelled_lesson_excluded_from_base'] = canc_excluded
        print(f"Scenario 4: Cancelled badge rendered: {has_cancelled_badge}")
        print(f"Scenario 4: Cancelled excluded from progress base (50% progress): {canc_excluded}")

        path_04 = os.path.join(KEY_REVIEW_DIR, '04_cancelled_and_completed_semantics.png')
        page.screenshot(path=path_04, full_page=False)
        results['key_screenshots'].append(path_04)
        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 5: Homework Lifecycle Statuses (Persona 5, user_id=205)
        # =====================================================================
        print('\n--- Verifying Scenario 5: Homework Lifecycle Statuses ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 205)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')

        # Check Wednesday (tab 2, ASSIGNED)
        page.click('#unified-tab-2')
        page.wait_for_timeout(200)
        t_assigned = page.locator('#unified-events-grid').text_content() or ''

        # Check Thursday (tab 3, IN_PROGRESS)
        page.click('#unified-tab-3')
        page.wait_for_timeout(200)
        t_in_progress = page.locator('#unified-events-grid').text_content() or ''

        # Check Friday (tab 4, RETURNED)
        page.click('#unified-tab-4')
        page.wait_for_timeout(200)
        t_returned = page.locator('#unified-events-grid').text_content() or ''

        # Check Saturday (tab 5, SUBMITTED)
        page.click('#unified-tab-5')
        page.wait_for_timeout(200)
        t_submitted = page.locator('#unified-events-grid').text_content() or ''

        hw_lifecycle_valid = ('Домашнее задание' in t_assigned and 'В процессе' in t_in_progress and 'На доработке' in t_returned and 'ДЗ сдано' in t_submitted)
        results['acceptance_criteria']['homework_lifecycle_statuses_accurate'] = hw_lifecycle_valid
        print(f"Scenario 5: Homework lifecycle badges (ASSIGNED, IN_PROGRESS, RETURNED, SUBMITTED): {hw_lifecycle_valid}")

        path_05 = os.path.join(KEY_REVIEW_DIR, '05_homework_lifecycle_statuses.png')
        page.screenshot(path=path_05, full_page=False)
        results['key_screenshots'].append(path_05)
        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 6: Mobile 390x844 Geometry & First-Screen CTA
        # =====================================================================
        print('\n--- Verifying Scenario 6: Mobile 390x844 Geometry & CTA ---')
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        auth_session(context, 201)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.click('#unified-tab-1')
        page.wait_for_timeout(300)

        geom = page.evaluate(GEOMETRY_EVAL_SCRIPT)
        results['geometry_matrix'].append(geom)

        has_no_hscroll = ('zero-horizontal-scroll' in geom['passes'])
        results['acceptance_criteria']['mobile_zero_horizontal_scroll'] = has_no_hscroll
        print(f"Scenario 6: Mobile zero horizontal scroll: {has_no_hscroll}")

        path_06 = os.path.join(KEY_REVIEW_DIR, '06_mobile_390x844_first_screen.png')
        page.screenshot(path=path_06, full_page=False)
        results['key_screenshots'].append(path_06)

        path_06_full = os.path.join(VIEWPORTS_DIR, 'mobile_390x844_full_page.png')
        page.screenshot(path=path_06_full, full_page=True)

        page.close()
        context.close()

        # =====================================================================
        # SCENARIO 7: Empty Week Vacation State with Mascot Boo
        # =====================================================================
        print('\n--- Verifying Scenario 7: Empty Week Vacation State ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 206)
        page = context.new_page()
        page.goto('http://127.0.0.1:5578/schedule')
        page.wait_for_selector('#schedule-data', state='attached')
        page.wait_for_timeout(300)

        empty_text = page.locator('#unified-events-grid').text_content() or ''
        has_vacation = ('Свободный учебный день' in empty_text or 'отдохнуть' in empty_text.lower() or 'отдых' in empty_text.lower())
        results['acceptance_criteria']['empty_week_friendly_state'] = has_vacation
        print(f"Scenario 7: Empty week friendly state rendered: {has_vacation}")

        path_07 = os.path.join(SCENARIOS_DIR, 'empty_week_vacation_boo.png')
        page.screenshot(path=path_07, full_page=False)
        page.close()
        context.close()

        browser.close()

    server.shutdown()

    report_path = os.path.join(SCREENSHOT_DIR, 'acceptance_integrity_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nAll Sprint 2.0.1 acceptance checks completed!")
    print(f"Key Review screenshots (5-6 items) saved to:\n  {KEY_REVIEW_DIR}")
    for k in results['key_screenshots']:
        print(f"  - {k}")


if __name__ == '__main__':
    seed_database()
    run_sprint_2_0_1_acceptance()
