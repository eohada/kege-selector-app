"""
BooStudy / ORISTERA — Student Schedule Sprint 2.0
Automated Functional, Visual, and Geometry Diagnostics Runner for Live `/schedule`.
Uses Playwright Chromium and Isolated Test SQLite Database.
Verifies Concept D (Phase 0.6) integrated into templates/sandbox/student_schedule.html.
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

ISOLATED_DB_PATH = '/tmp/test_schedule_sprint2_0.db'
if os.path.exists(ISOLATED_DB_PATH):
    try:
        os.remove(ISOLATED_DB_PATH)
    except Exception:
        pass

os.environ['DATABASE_URL'] = f'sqlite:///{ISOLATED_DB_PATH}'
os.environ['SQLITE_DB_PATH'] = ISOLATED_DB_PATH
os.environ['BOOSTUDY_SKIP_DATABASE_BOOTSTRAP'] = '1'
os.environ['BOOSTUDY_BACKGROUND_WORKERS_ENABLED'] = '0'
os.environ['SECRET_KEY'] = 'test-e2e-secret-key-sprint-2-0'
os.environ['WTF_CSRF_ENABLED'] = 'false'
os.environ['TESTING'] = '1'

from app import create_app, db
from core.db_models import User, Student, Lesson, Assignment, Submission
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

        # Mentor
        mentor = User(id=99, username='e2e_mentor', email='m@test.com', password_hash=generate_password_hash('p'), role='teacher', full_name='Виктор Сергеевич (Преподаватель)')
        db.session.add(mentor)
        db.session.commit()

        # Persona 1: Empty Student
        u_empty = User(id=101, username='e2e_empty', email='empty@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Илья Пустой')
        db.session.add(u_empty)
        db.session.commit()
        st_empty = Student(student_id=101, user_id=101, name='Илья Пустой', mentor_id=99, is_active=True)
        db.session.add(st_empty)

        # Persona 2: Standard Student (Mixed: completed, planned, homeworks)
        u_std = User(id=102, username='e2e_std', email='std@test.com', password_hash=generate_password_hash('p'), role='student', full_name='София Стандартная')
        db.session.add(u_std)
        db.session.commit()
        st_std = Student(student_id=102, user_id=102, name='София Стандартная', mentor_id=99, is_active=True)
        db.session.add(st_std)

        # Persona 3: Multi-Event Heavy Student
        u_heavy = User(id=103, username='e2e_heavy', email='heavy@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Максим Мультизадачный')
        db.session.add(u_heavy)
        db.session.commit()
        st_heavy = Student(student_id=103, user_id=103, name='Максим Мультизадачный', mentor_id=99, is_active=True)
        db.session.add(st_heavy)

        # Persona 4: Long strings Resilience
        u_long = User(id=104, username='e2e_long', email='long@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Константин Длиннотекстовый')
        db.session.add(u_long)
        db.session.commit()
        st_long = Student(student_id=104, user_id=104, name='Константин Длиннотекстовый', mentor_id=99, is_active=True)
        db.session.add(st_long)

        # Persona 5: Single Lesson Week
        u_single = User(id=105, username='e2e_single', email='single@test.com', password_hash=generate_password_hash('p'), role='student', full_name='Дмитрий Одиночный')
        db.session.add(u_single)
        db.session.commit()
        st_single = Student(student_id=105, user_id=105, name='Дмитрий Одиночный', mentor_id=99, is_active=True)
        db.session.add(st_single)

        db.session.commit()

        # Seed lessons and assignments for Persona 2 (Standard)
        now_utc = datetime.now(dt_timezone.utc)
        monday_utc = (now_utc - timedelta(days=now_utc.weekday())).replace(hour=14, minute=0, second=0, microsecond=0)

        # Monday: Completed Lesson
        l_mon = Lesson(student_id=102, lesson_date=monday_utc, duration=60, status='completed', topic='Рекурсивные алгоритмы и стек вызовов', notes='Отлично справился с базовыми задачами. Повтори стек вызовов.')
        # Wednesday: Planned Lesson
        l_wed = Lesson(student_id=102, lesson_date=monday_utc + timedelta(days=2), duration=90, status='planned', topic='Динамическое программирование: одномерные таблицы', notes='Подготовь тетрадь и повтори задачу о кузнечике.')
        # Friday: Planned Lesson
        l_fri = Lesson(student_id=102, lesson_date=monday_utc + timedelta(days=4), duration=60, status='planned', topic='Теория графов и матрицы смежности')
        db.session.add_all([l_mon, l_wed, l_fri])

        # Monday Homework: SUBMITTED
        a_mon = Assignment(title='ДЗ 1: Рекурсия и числа Фибоначчи', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(hours=6), is_active=True)
        # Wednesday Homework: IN_PROGRESS
        a_wed = Assignment(title='ДЗ 2: Кузнечик и динамика', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(days=2, hours=6), is_active=True)
        # Friday Homework: ASSIGNED
        a_fri = Assignment(title='ДЗ 3: Поиск путей в графе', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(days=4, hours=6), is_active=True)
        db.session.add_all([a_mon, a_wed, a_fri])
        db.session.commit()

        s_mon = Submission(assignment_id=a_mon.assignment_id, student_id=102, status='SUBMITTED')
        s_wed = Submission(assignment_id=a_wed.assignment_id, student_id=102, status='IN_PROGRESS')
        s_fri = Submission(assignment_id=a_fri.assignment_id, student_id=102, status='ASSIGNED')
        db.session.add_all([s_mon, s_wed, s_fri])

        # Seed lessons and assignments for Persona 3 (Heavy: 2 lessons + homework on Tuesday)
        tue_utc = monday_utc + timedelta(days=1)
        l_tue1 = Lesson(student_id=103, lesson_date=tue_utc.replace(hour=15), duration=60, status='planned', topic='Информатика: Практикум ЕГЭ №24 (Строки)')
        l_tue2 = Lesson(student_id=103, lesson_date=tue_utc.replace(hour=18), duration=90, status='planned', topic='Математика: Стереометрия и векторы в пространстве')
        a_tue1 = Assignment(title='ДЗ А: Строковые алгоритмы и срезы в Python', assignment_type='homework', created_by_id=99, deadline=tue_utc.replace(hour=23, minute=59), is_active=True)
        db.session.add_all([l_tue1, l_tue2, a_tue1])
        db.session.commit()
        s_tue1 = Submission(assignment_id=a_tue1.assignment_id, student_id=103, status='IN_PROGRESS')
        db.session.add(s_tue1)

        # Seed lesson for Persona 4 (Long string resilience)
        long_topic = 'Сверхсложная комплексная тема: Анализ больших текстовых файлов, регулярные выражения, конечные автоматы и оптимизация памяти O(1) в компьютерном ЕГЭ'
        long_notes = 'Обрати персональное внимание: не считывай весь файл .read() целиком в оперативную память при обработке 100 МБ данных, используй построчную итерацию for line in f: и генераторы!'
        l_long = Lesson(student_id=104, lesson_date=monday_utc + timedelta(days=2), duration=120, status='planned', topic=long_topic, notes=long_notes)
        db.session.add(l_long)

        # Seed lesson for Persona 5 (Single Lesson)
        l_single = Lesson(student_id=105, lesson_date=monday_utc + timedelta(days=1), duration=60, status='planned', topic='Базовые типы данных и условные операторы')
        db.session.add(l_single)

        db.session.commit()
        print('Isolated test database seeded successfully.')


class ServerThread(threading.Thread):
    def __init__(self, port=5577):
        super().__init__(daemon=True)
        self.port = port
        self.server = make_server('127.0.0.1', port, app.wsgi_app, threaded=True)

    def run(self):
        print(f'Test server started on http://127.0.0.1:{self.port}')
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def run_e2e_diagnostics():
    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR = os.path.join(ROOT_DIR, 'docs', 'schedule_sprint2_0_screenshots')
    KEY_REVIEW_DIR = os.path.join(SCREENSHOT_DIR, 'key_review')
    VIEWPORTS_DIR = os.path.join(SCREENSHOT_DIR, 'viewports')
    SCENARIOS_DIR = os.path.join(SCREENSHOT_DIR, 'scenarios')

    for d in [SCREENSHOT_DIR, KEY_REVIEW_DIR, VIEWPORTS_DIR, SCENARIOS_DIR]:
        os.makedirs(d, exist_ok=True)

    server = ServerThread(port=5577)
    server.start()
    time.sleep(1.0)

    results = {
        'functional_checks': {},
        'geometry_matrix': [],
        'console_errors': [],
        'network_failures': [],
        'audit_summary': {}
    }

    VIEWPORTS = [
        {'name': 'Desktop 1440x900', 'width': 1440, 'height': 900, 'category': 'desktop'},
        {'name': 'Desktop 1920x1080', 'width': 1920, 'height': 1080, 'category': 'desktop'},
        {'name': 'Tablet 768x1024', 'width': 768, 'height': 1024, 'category': 'tablet'},
        {'name': 'Mobile 390x844', 'width': 390, 'height': 844, 'category': 'mobile'},
    ]

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

        // 3. Mobile primary action CTA check (visible on first screen without scrolling)
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

        // 4. Equal peer cards grid check
        const peerCards = document.querySelectorAll('.peer-event-card');
        if (peerCards.length > 0) {
            passes.push('peer-cards-rendered');
        }

        return { viewport, findings, passes };
    })()
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def auth_session(context, user_id):
            page = context.new_page()
            resp = page.request.post('http://127.0.0.1:5577/api/internal/test_login', data=json.dumps({'user_id': user_id}), headers={'Content-Type': 'application/json'})
            assert resp.status == 200
            page.close()

        # =========================================================================
        # 1. FUNCTIONAL CHECKS (Desktop 1440x900, Persona 2 Standard)
        # =========================================================================
        print('\n--- Running Functional Checks on Live /schedule ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 102)
        page = context.new_page()

        page.goto('http://127.0.0.1:5577/schedule')
        page.wait_for_selector('#schedule-data', state='attached')

        # Check 1: 7 tabs exist
        tabs_count = page.locator('.unified-day-tab').count()
        results['functional_checks']['day_tabs_count_is_7'] = (tabs_count == 7)
        print(f"Check: 7 Day tabs count = {tabs_count} (Expected: 7)")

        # Check 2: Click Wednesday (index 2)
        page.click('#unified-tab-2')
        page.wait_for_timeout(200)
        tab_2_class = page.locator('#unified-tab-2').get_attribute('class') or ''
        is_tab_2_active = 'is-active' in tab_2_class
        results['functional_checks']['day_click_activates_tab'] = is_tab_2_active
        print(f"Check: Clicking Wednesday activates tab: {is_tab_2_active}")

        # Check 3: Peer event card topic
        grid_text = page.locator('#unified-events-grid').text_content() or ''
        has_topic = 'Динамическое программирование' in grid_text
        results['functional_checks']['peer_card_topic_displayed'] = has_topic
        print(f"Check: Topic displayed: {has_topic}")

        # Check 4: Teacher name displayed
        has_teacher = 'Виктор Сергеевич' in grid_text or 'Преподаватель курса' in grid_text
        results['functional_checks']['teacher_displayed'] = has_teacher
        print(f"Check: Teacher displayed: {has_teacher}")

        page.close()
        context.close()

        # =========================================================================
        # 2. VIEWPORT MATRIX CAPTURES & AUDIT
        # =========================================================================
        print('\n--- Running Viewport Matrix Captures ---')
        for vp in VIEWPORTS:
            context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']})
            auth_session(context, 102)
            page = context.new_page()
            page.goto('http://127.0.0.1:5577/schedule')
            page.wait_for_selector('#schedule-data', state='attached')
            page.wait_for_timeout(400)

            # Click Wednesday to show planned lesson with full details
            page.click('#unified-tab-2')
            page.wait_for_timeout(200)

            vp_filename = f"live_schedule_{vp['category']}_{vp['width']}x{vp['height']}.png"
            vp_path = os.path.join(VIEWPORTS_DIR, vp_filename)
            page.screenshot(path=vp_path, full_page=True)

            # Key review numbered shortcuts
            if vp['width'] == 1440 and vp['height'] == 900:
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, '01_live_schedule_desktop_1440x900.png'), full_page=False)
            elif vp['width'] == 1920 and vp['height'] == 1080:
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, '02_live_schedule_desktop_1920x1080.png'), full_page=False)
            elif vp['width'] == 390 and vp['height'] == 844:
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, '03_live_schedule_mobile_390x844.png'), full_page=True)
                # Pure first screen
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, '03b_live_schedule_mobile_first_screen_390x844.png'), full_page=False)
            elif vp['width'] == 768 and vp['height'] == 1024:
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, '04_live_schedule_tablet_768x1024.png'), full_page=True)

            audit_res = page.evaluate(GEOMETRY_EVAL_SCRIPT)
            audit_res['viewport_name'] = vp['name']
            audit_res['screenshot'] = vp_path
            results['geometry_matrix'].append(audit_res)
            print(f"Viewport {vp['name']}: {len(audit_res['findings'])} findings, {len(audit_res['passes'])} passes")

            page.close()
            context.close()

        # =========================================================================
        # 3. SCENARIO MATRIX CAPTURES (Key personas & edge cases)
        # =========================================================================
        print('\n--- Running Scenario Matrix Captures ---')
        scenarios = [
            {'name': 'scenario_multi_event_density', 'user_id': 103, 'click_tab': 1, 'key_file': '05_live_schedule_multi_event_density.png', 'desc': 'Multi-Event Density (2 lessons + compact HW)'},
            {'name': 'scenario_single_lesson_balance', 'user_id': 105, 'click_tab': 1, 'key_file': '06_live_schedule_single_lesson_balance.png', 'desc': 'Single Lesson Balance (1 lesson week)'},
            {'name': 'scenario_empty_week_boo', 'user_id': 101, 'click_tab': 0, 'key_file': '07_live_schedule_empty_week_with_boo.png', 'desc': 'Vacation / Empty week with Boo mascot'},
            {'name': 'scenario_stress_long_titles', 'user_id': 104, 'click_tab': 2, 'key_file': '08_live_schedule_stress_long_titles.png', 'desc': 'Stress test: Long titles and teacher notes'},
        ]

        for sc in scenarios:
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            auth_session(context, sc['user_id'])
            page = context.new_page()
            page.goto('http://127.0.0.1:5577/schedule')
            page.wait_for_selector('#schedule-data', state='attached')
            page.wait_for_timeout(300)

            if sc['click_tab'] is not None:
                page.click(f"#unified-tab-{sc['click_tab']}")
                page.wait_for_timeout(200)

            sc_path = os.path.join(SCENARIOS_DIR, f"{sc['name']}.png")
            page.screenshot(path=sc_path, full_page=True)

            if sc.get('key_file'):
                page.screenshot(path=os.path.join(KEY_REVIEW_DIR, sc['key_file']), full_page=True)

            print(f"Scenario [{sc['desc']}] captured -> {sc.get('key_file') or sc['name']}")

            page.close()
            context.close()

        browser.close()

    server.shutdown()

    # Save report
    report_path = os.path.join(SCREENSHOT_DIR, 'diagnostics_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nAll diagnostics and screenshots saved to {SCREENSHOT_DIR}")
    print(f"Key Review screenshots saved to {KEY_REVIEW_DIR}")


if __name__ == '__main__':
    seed_database()
    run_e2e_diagnostics()
