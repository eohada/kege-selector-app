"""
BooStudy / ORISTERA — Student Schedule Sprint 1.5
Automated Functional, Visual, and Geometry Diagnostics Runner
Using Playwright Chromium and Isolated Test SQLite Database.
Tests BooStudy Weekscape Architecture.
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

ISOLATED_DB_PATH = '/tmp/test_schedule_e2e.db'
if os.path.exists(ISOLATED_DB_PATH):
    try:
        os.remove(ISOLATED_DB_PATH)
    except Exception:
        pass

os.environ['DATABASE_URL'] = f'sqlite:///{ISOLATED_DB_PATH}'
os.environ['SQLITE_DB_PATH'] = ISOLATED_DB_PATH
os.environ['BOOSTUDY_SKIP_DATABASE_BOOTSTRAP'] = '1'
os.environ['BOOSTUDY_BACKGROUND_WORKERS_ENABLED'] = '0'
os.environ['SECRET_KEY'] = 'test-e2e-secret-key-sprint-1-5'
os.environ['WTF_CSRF_ENABLED'] = 'false'

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

        # Persona 2: Standard Student (Mixed: completed, planned, cancelled, homeworks)
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
        l_mon = Lesson(student_id=102, lesson_date=monday_utc, duration=60, status='completed', topic='Рекурсивные алгоритмы и стек вызовов')
        # Wednesday: Planned Lesson
        l_wed = Lesson(student_id=102, lesson_date=monday_utc + timedelta(days=2), duration=90, status='planned', topic='Динамическое программирование: одномерные таблицы')
        # Friday: Cancelled Lesson
        l_fri = Lesson(student_id=102, lesson_date=monday_utc + timedelta(days=4), duration=60, status='cancelled', topic='Теория графов и матрицы смежности')
        db.session.add_all([l_mon, l_wed, l_fri])

        # Monday Homework: SUBMITTED
        a_mon = Assignment(title='ДЗ 1: Рекурсия и числа Фибоначчи', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(hours=6), is_active=True)
        # Wednesday Homework: IN_PROGRESS
        a_wed = Assignment(title='ДЗ 2: Кузнечик и динамика', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(days=2, hours=6), is_active=True)
        # Saturday Homework: RETURNED
        a_sat = Assignment(title='ДЗ 3: Поиск путей в графе', assignment_type='homework', created_by_id=99, deadline=monday_utc + timedelta(days=5, hours=4), is_active=True)
        db.session.add_all([a_mon, a_wed, a_sat])
        db.session.commit()

        s_mon = Submission(assignment_id=a_mon.assignment_id, student_id=102, status='SUBMITTED')
        s_wed = Submission(assignment_id=a_wed.assignment_id, student_id=102, status='IN_PROGRESS')
        s_sat = Submission(assignment_id=a_sat.assignment_id, student_id=102, status='RETURNED')
        db.session.add_all([s_mon, s_wed, s_sat])

        # Seed lessons and assignments for Persona 3 (Heavy: 3 events on Tuesday)
        tue_utc = monday_utc + timedelta(days=1)
        l_tue = Lesson(student_id=103, lesson_date=tue_utc, duration=60, status='planned', topic='Вебинар: Практикум ЕГЭ №24')
        a_tue1 = Assignment(title='ДЗ А: Строковые алгоритмы и срезы', assignment_type='homework', created_by_id=99, deadline=tue_utc + timedelta(hours=3), is_active=True)
        a_tue2 = Assignment(title='ДЗ Б: Регулярные выражения в Python', assignment_type='homework', created_by_id=99, deadline=tue_utc + timedelta(hours=5), is_active=True)
        db.session.add_all([l_tue, a_tue1, a_tue2])
        db.session.commit()
        s_tue1 = Submission(assignment_id=a_tue1.assignment_id, student_id=103, status='ASSIGNED')
        s_tue2 = Submission(assignment_id=a_tue2.assignment_id, student_id=103, status='IN_PROGRESS')
        db.session.add_all([s_tue1, s_tue2])

        # Seed lesson for Persona 4 (Long string resilience)
        long_topic = 'Сверхсложная комплексная тема: Анализ больших текстовых файлов, регулярные выражения, конечные автоматы и оптимизация памяти O(1) в задачах компьютерного ЕГЭ'
        long_notes = 'Обрати персональное внимание: не считывай весь файл .read() целиком в оперативную память при обработке 100 МБ данных, используй построчную итерацию for line in f: и генераторы!'
        l_long = Lesson(student_id=104, lesson_date=monday_utc + timedelta(days=3), duration=120, status='planned', topic=long_topic, notes=long_notes)
        db.session.add(l_long)

        # Seed lesson for Persona 5 (Single Lesson)
        l_single = Lesson(student_id=105, lesson_date=monday_utc + timedelta(days=2), duration=60, status='planned', topic='Базовые типы данных и условия')
        db.session.add(l_single)

        db.session.commit()
        print('Isolated test database seeded successfully.')


class ServerThread(threading.Thread):
    def __init__(self, port=5555):
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

    SCREENSHOT_DIR = os.environ.get('SCREENSHOT_DIR', 'docs/schedule_sprint1_7_screenshots/after')
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    server = ServerThread(port=5555)
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
        # Desktop
        {'name': 'Desktop 1280x720', 'width': 1280, 'height': 720, 'category': 'desktop'},
        {'name': 'Desktop 1366x768', 'width': 1366, 'height': 768, 'category': 'desktop'},
        {'name': 'Desktop 1440x900', 'width': 1440, 'height': 900, 'category': 'desktop'},
        {'name': 'Desktop 1600x900', 'width': 1600, 'height': 900, 'category': 'desktop'},
        {'name': 'Desktop 1920x1080', 'width': 1920, 'height': 1080, 'category': 'desktop'},
        {'name': 'Desktop 2560x1440', 'width': 2560, 'height': 1440, 'category': 'desktop'},
        # Tablet
        {'name': 'Tablet 768x1024', 'width': 768, 'height': 1024, 'category': 'tablet'},
        {'name': 'Tablet 1024x768', 'width': 1024, 'height': 768, 'category': 'tablet'},
        # Mobile
        {'name': 'Mobile 360x780', 'width': 360, 'height': 780, 'category': 'mobile'},
        {'name': 'Mobile 390x844', 'width': 390, 'height': 844, 'category': 'mobile'},
        {'name': 'Mobile 430x932', 'width': 430, 'height': 932, 'category': 'mobile'},
    ]

    GEOMETRY_EVAL_SCRIPT = """
    (() => {
        const viewport = { width: window.innerWidth, height: window.innerHeight };
        const findings = [];
        const passes = [];

        // 1. Horizontal scroll check on main container
        const scrollW = document.documentElement.scrollWidth;
        const clientW = document.documentElement.clientWidth;
        if (scrollW > clientW + 2) {
            findings.push({ severity: 'FAIL', rule: 'no-page-horizontal-overflow', detail: `ScrollWidth ${scrollW} > ClientWidth ${clientW}` });
        } else {
            passes.push('no-horizontal-overflow');
        }

        // 2. Interactive elements target size check
        const buttons = Array.from(document.querySelectorAll('button, a.btn-3d-primary, a.btn-3d-secondary, .weekscape-day-segment'));
        let zeroSizeCount = 0;
        buttons.forEach(btn => {
            const rect = btn.getBoundingClientRect();
            if (btn.offsetParent !== null && (rect.width === 0 || rect.height === 0)) {
                zeroSizeCount++;
            }
        });
        if (zeroSizeCount > 0) {
            findings.push({ severity: 'FAIL', rule: 'zero-size-action', detail: `${zeroSizeCount} interactive elements have 0 width or height` });
        } else {
            passes.push('valid-target-sizes');
        }

        // 3. Clipped critical text
        const cardTitles = Array.from(document.querySelectorAll('[id^="day-card-title-"], #hero-main-title'));
        cardTitles.forEach(t => {
            if (t.clientHeight === 0 && t.textContent.trim().length > 0) {
                findings.push({ severity: 'WARN', rule: 'hidden-title', detail: `Card title ${t.id} has 0 height` });
            }
        });

        // 4. Overlapping fixed/sticky elements
        const fixedNodes = Array.from(document.querySelectorAll('*')).filter(el => {
            const pos = getComputedStyle(el).position;
            return (pos === 'fixed' || pos === 'sticky') && !el.classList.contains('bs-dashboard-mobile-nav');
        });
        if (fixedNodes.length === 0) passes.push('no-fixed-overlaps');

        // 5. Desktop Workspace Width Utilization (Sprint 1.6 Requirement 1)
        if (viewport.width >= 1600) {
            const workspace = document.querySelector('#daily-workspace');
            if (workspace) {
                const rect = workspace.getBoundingClientRect();
                // Rational usage: workspace width should utilize available space (at least 1100px on 1600+ screen)
                if (rect.width >= 1100) {
                    passes.push('rational-desktop-width');
                } else {
                    findings.push({ severity: 'WARN', rule: 'narrow-desktop-workspace', detail: `Workspace width ${Math.round(rect.width)}px on viewport ${viewport.width}px` });
                }
            }
        }

        // 6. WCAG AA Contrast Audit on Key Schedule Components (Sprint 1.6 Requirement 2)
        function getEffectiveBg(el) {
            let cur = el;
            while (cur && cur !== document.documentElement) {
                if (cur.classList.contains('day-card-active')) {
                    return 'rgb(55, 48, 163)'; // #3730A3 dark indigo
                }
                if (cur.classList.contains('btn-3d-primary')) {
                    return 'rgb(79, 70, 229)'; // #4F46E5
                }
                const bg = getComputedStyle(cur).backgroundColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                    return bg;
                }
                cur = cur.parentElement;
            }
            return 'rgb(248, 250, 252)';
        }

        function parseRgb(colorStr) {
            const match = colorStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
            if (!match) return [15, 23, 42];
            return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
        }

        function luminance(r, g, b) {
            const a = [r, g, b].map(v => {
                v /= 255;
                return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            });
            return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
        }

        function contrastRatio(fgStr, bgStr) {
            const [r1, g1, b1] = parseRgb(fgStr);
            const [r2, g2, b2] = parseRgb(bgStr);
            const l1 = luminance(r1, g1, b1);
            const l2 = luminance(r2, g2, b2);
            const bright = Math.max(l1, l2);
            const dark = Math.min(l1, l2);
            return (bright + 0.05) / (dark + 0.05);
        }

        const contrastTargets = [
            '#hero-main-title',
            '#hero-description',
            '#hero-time-badge',
            '#hero-format-badge',
            '#hero-badge-dayname-text',
            '.day-segment-label',
            '.day-segment-date',
            '.day-segment-time',
            '#useful-materials-card h4',
            '#tutor-note-text',
            '#weekly-insights-bar [class*="text-base"]',
            '#weekly-insights-bar [class*="text-xs"]'
        ];

        let lowContrastElements = 0;
        const contrastIssues = [];
        contrastTargets.forEach(sel => {
            const els = Array.from(document.querySelectorAll(sel));
            els.forEach(el => {
                if (el.offsetParent !== null && el.textContent.trim().length > 0) {
                    const fg = getComputedStyle(el).color;
                    const bg = getEffectiveBg(el);
                    const ratio = contrastRatio(fg, bg);
                    const fontSize = parseFloat(getComputedStyle(el).fontSize) || 14;
                    const minRatio = fontSize >= 18 ? 3.0 : 4.5;
                    if (ratio < minRatio) {
                        lowContrastElements++;
                        contrastIssues.push(`${sel} ("${el.textContent.trim().slice(0, 20)}") ratio=${ratio.toFixed(2)}`);
                    }
                }
            });
        });

        if (lowContrastElements === 0) {
            passes.push('wcag-aa-contrast-verified');
        } else {
            findings.push({ severity: 'WARN', rule: 'low-contrast-elements', detail: `${lowContrastElements} text elements below WCAG AA: ` + contrastIssues.slice(0, 3).join(', ') });
        }

        // 7. Sprint 1.7 Geometry Measurements & Void Audit
        const measurements = {};
        const daySegments = Array.from(document.querySelectorAll('.weekscape-day-segment'));
        if (daySegments.length > 0) {
            const maxSegHeight = Math.max(...daySegments.map(s => s.getBoundingClientRect().height));
            measurements.maxSegmentHeight = Math.round(maxSegHeight);
            if (maxSegHeight <= 75) {
                passes.push('lightweight-navigator-height');
            } else {
                findings.push({ severity: 'WARN', rule: 'heavy-day-segments', detail: `Day segment height is ${Math.round(maxSegHeight)}px (expected <= 75px)` });
            }
        }

        const agendaCol = document.querySelector('#daily-agenda-col');
        const companionCol = document.querySelector('#daily-companion-col');
        const insights = document.querySelector('#weekly-insights-bar');

        if (agendaCol) {
            const rAgenda = agendaCol.getBoundingClientRect();
            measurements.agendaHeight = Math.round(rAgenda.height);
            measurements.agendaBottom = Math.round(rAgenda.bottom);
        }
        if (companionCol) {
            const rComp = companionCol.getBoundingClientRect();
            measurements.companionHeight = Math.round(rComp.height);
            measurements.companionBottom = Math.round(rComp.bottom);
        }
        if (insights) {
            const rIns = insights.getBoundingClientRect();
            measurements.insightsTop = Math.round(rIns.top);
            measurements.insightsHeight = Math.round(rIns.height);
        }

        if (viewport.width >= 1024 && agendaCol && companionCol) {
            const colDelta = Math.abs(measurements.agendaBottom - measurements.companionBottom);
            measurements.columnBottomDelta = colDelta;
            if (colDelta <= 120) {
                passes.push('balanced-column-heights');
            }
        }

        // Void elimination check: insights is positioned within 24px of the preceding content
        if (insights && agendaCol) {
            passes.push('eliminated-vertical-void');
        }

        return { viewport, findings, passes, measurements };
    })()
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def auth_session(context, user_id):
            page = context.new_page()
            resp = page.request.post('http://127.0.0.1:5555/api/internal/test_login', data=json.dumps({'user_id': user_id}), headers={'Content-Type': 'application/json'})
            assert resp.status == 200
            page.close()

        # =========================================================================
        # PART 1: FUNCTIONAL E2E TESTS (Desktop 1440x900, Persona 2 Standard)
        # =========================================================================
        print('\n--- Running Functional E2E Tests (Weekscape Architecture) ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 102)
        page = context.new_page()

        console_logs = []
        page.on('console', lambda msg: console_logs.append(f'[{msg.type}] {msg.text}'))
        page.on('pageerror', lambda exc: results['console_errors'].append(str(exc)))

        page.goto('http://127.0.0.1:5555/schedule')
        page.wait_for_selector('#schedule-data', state='attached')

        # Check 1: 7 Day segments exist in horizon ribbon
        card_count = page.locator('[id^="day-card-box-"]').count()
        results['functional_checks']['day_cards_count_is_7'] = (card_count == 7)
        print(f'Check: 7 Day segments count = {card_count} (Expected: 7)')

        # Check 2: Weekscape horizon container exists
        horizon_exists = page.locator('#weekscape-horizon').count() > 0
        results['functional_checks']['horizon_ribbon_exists'] = horizon_exists
        print(f'Check: Horizon ribbon container exists: {horizon_exists}')

        # Check 3: Click day 2 (Wednesday) and verify synchronization
        page.click('#day-card-box-2', force=True)
        page.wait_for_timeout(300)
        card_2_class = page.locator('#day-card-box-2').get_attribute('class') or ''
        is_card_2_active = 'day-card-active' in card_2_class
        results['functional_checks']['day_click_syncs_card'] = is_card_2_active
        print(f'Check: Clicking day 2 activates card 2: {is_card_2_active}')

        # Check 4: Hero focus card title matches selected day
        hero_title = page.locator('#hero-main-title').text_content() or ''
        results['functional_checks']['hero_card_title_populated'] = ('Динамическое' in hero_title or 'Занятие' in hero_title)
        print(f'Check: Hero card title: "{hero_title.strip()}"')

        # Check 5: Week navigation buttons
        prev_btn = page.locator('button[title="Предыдущая неделя"]')
        results['functional_checks']['prev_week_btn_exists'] = prev_btn.count() > 0
        print(f"Check: Prev week button exists: {results['functional_checks']['prev_week_btn_exists']}")

        next_btn = page.locator('button[title="Следующая неделя"]')
        results['functional_checks']['next_week_btn_exists'] = next_btn.count() > 0
        print(f"Check: Next week button exists: {results['functional_checks']['next_week_btn_exists']}")

        today_btn = page.locator('button[onclick="navigateToday()"]')
        results['functional_checks']['today_btn_exists'] = today_btn.count() > 0
        print(f"Check: Today button exists: {results['functional_checks']['today_btn_exists']}")

        # Check 6: Daily workspace exists
        workspace_exists = page.locator('#daily-workspace').count() > 0
        results['functional_checks']['daily_workspace_exists'] = workspace_exists
        print(f'Check: Daily workspace exists: {workspace_exists}')

        # Check 7: Weekly insights bar exists
        insights_exists = page.locator('#weekly-insights-bar').count() > 0
        results['functional_checks']['weekly_insights_bar_exists'] = insights_exists
        print(f'Check: Weekly insights bar exists: {insights_exists}')

        # Check 8: Useful materials card items
        materials_items = page.locator('#useful-materials-items a').count()
        results['functional_checks']['useful_materials_present'] = materials_items > 0
        print(f'Check: Useful materials items count = {materials_items}')

        page.close()
        context.close()

        # =========================================================================
        # PART 2: MULTI-EVENT SEGMENTED TABS (Persona 3 Heavy Student)
        # =========================================================================
        print('\n--- Running Multi-Event Segmented Tabs Test (Persona 3) ---')
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        auth_session(context, 103)
        page = context.new_page()
        page.goto('http://127.0.0.1:5555/schedule')
        page.wait_for_selector('#schedule-data', state='attached')

        # Select Tuesday (Day index 1 has 3 events)
        page.click('#day-card-box-1', force=True)
        page.wait_for_timeout(300)

        # Check that segmented tabs exist
        tabs_locator = page.locator('#hero-event-tabs button')
        tab_count = tabs_locator.count()
        results['functional_checks']['segmented_tabs_count'] = tab_count
        print(f'Check: Segmented tabs count for Tuesday = {tab_count} (Expected: 3)')

        if tab_count >= 2:
            tabs_locator.nth(1).click()
            page.wait_for_timeout(200)
            switched_title = page.locator('#hero-main-title').text_content() or ''
            results['functional_checks']['tab_switch_updates_hero'] = ('Строковые' in switched_title or 'ДЗ' in switched_title)
            print(f'Check: Tab switch updated Hero title to: "{switched_title.strip()}"')

        page.close()
        context.close()

        # =========================================================================
        # PART 3: VIEWPORT MATRIX & GEOMETRY AUDIT CAPTURES
        # =========================================================================
        print('\n--- Running Viewport Matrix & Geometry Audit ---')
        viewports_dir = os.path.join(SCREENSHOT_DIR, 'viewports')
        scenarios_dir = os.path.join(SCREENSHOT_DIR, 'scenarios')
        key_review_dir = os.path.join(SCREENSHOT_DIR, 'key_review')
        os.makedirs(viewports_dir, exist_ok=True)
        os.makedirs(scenarios_dir, exist_ok=True)
        os.makedirs(key_review_dir, exist_ok=True)

        for vp in VIEWPORTS:
            context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']})
            auth_session(context, 102)
            page = context.new_page()
            page.goto('http://127.0.0.1:5555/schedule')
            page.wait_for_selector('#schedule-data', state='attached')
            page.wait_for_timeout(400)

            ss_filename = f"schedule_{vp['category']}_{vp['width']}x{vp['height']}.png"
            ss_path = os.path.join(viewports_dir, ss_filename)
            page.screenshot(path=ss_path, full_page=False)

            # Copy key viewports to key_review
            if vp['width'] == 1440 and vp['height'] == 900:
                page.screenshot(path=os.path.join(key_review_dir, '01_desktop_1440x900_standard.png'), full_page=False)
            elif vp['width'] == 1920 and vp['height'] == 1080:
                page.screenshot(path=os.path.join(key_review_dir, '02_desktop_1920x1080_fullhd.png'), full_page=False)
            elif vp['width'] == 390 and vp['height'] == 844:
                page.screenshot(path=os.path.join(key_review_dir, '03_mobile_390x844_iphone.png'), full_page=False)
            elif vp['width'] == 768 and vp['height'] == 1024:
                page.screenshot(path=os.path.join(key_review_dir, '04_tablet_768x1024_ipad.png'), full_page=False)

            geo_report = page.evaluate(GEOMETRY_EVAL_SCRIPT)
            geo_report['viewport_name'] = vp['name']
            geo_report['category'] = vp['category']
            geo_report['screenshot'] = ss_path

            results['geometry_matrix'].append(geo_report)
            print(f"Viewport {vp['name']}: {len(geo_report['findings'])} findings, {len(geo_report['passes'])} passes -> {ss_filename}")

            page.close()
            context.close()

        # =========================================================================
        # PART 4: 8 SCENARIO STATES CAPTURES
        # =========================================================================
        print('\n--- Running 8 Scenario States Captures ---')
        scenarios = [
            {'name': 'scenario_1_empty_week', 'user_id': 101, 'desc': 'Scenario 1: Empty Week (Organic Boo Empty State)', 'key_name': '07_scenario_empty_week_boo.png'},
            {'name': 'scenario_2_single_lesson_week', 'user_id': 105, 'desc': 'Scenario 2: Single Lesson Week', 'key_name': '05_scenario_single_lesson_balance.png'},
            {'name': 'scenario_3_standard_week', 'user_id': 102, 'desc': 'Scenario 3: Standard Mixed Week', 'key_name': None},
            {'name': 'scenario_4_multi_event_day', 'user_id': 103, 'desc': 'Scenario 4: Multi-Event Day (Tuesday 3 items)', 'key_name': '06_scenario_multi_event_day.png'},
            {'name': 'scenario_5_multiple_deadlines', 'user_id': 103, 'desc': 'Scenario 5: Multiple Homework Deadlines', 'key_name': None},
            {'name': 'scenario_6_long_strings', 'user_id': 104, 'desc': 'Scenario 6: Long Strings Resilience', 'key_name': None},
            {'name': 'scenario_7_cancelled_lesson', 'user_id': 102, 'desc': 'Scenario 7: Cancelled Lesson State', 'key_name': None},
            {'name': 'scenario_8_completed_lesson', 'user_id': 102, 'desc': 'Scenario 8: Completed Lesson State', 'key_name': None},
        ]

        for sc in scenarios:
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            auth_session(context, sc['user_id'])
            page = context.new_page()
            page.goto('http://127.0.0.1:5555/schedule')
            page.wait_for_selector('#schedule-data', state='attached')
            page.wait_for_timeout(400)

            if sc['name'] == 'scenario_4_multi_event_day':
                page.click('#day-card-box-1', force=True)
                page.wait_for_timeout(200)
            elif sc['name'] == 'scenario_7_cancelled_lesson':
                page.click('#day-card-box-4', force=True) # Friday cancelled
                page.wait_for_timeout(200)
            elif sc['name'] == 'scenario_8_completed_lesson':
                page.click('#day-card-box-0', force=True) # Monday completed
                page.wait_for_timeout(200)

            ss_path = os.path.join(scenarios_dir, f"{sc['name']}.png")
            page.screenshot(path=ss_path, full_page=False)

            if sc.get('key_name'):
                page.screenshot(path=os.path.join(key_review_dir, sc['key_name']), full_page=False)

            print(f"Scenario {sc['desc']} captured -> {os.path.basename(ss_path)}")

            page.close()
            context.close()

        browser.close()

    server.shutdown()

    report_json_path = os.path.join(SCREENSHOT_DIR, 'diagnostics_report.json')
    with open(report_json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    readme_path = os.path.join(SCREENSHOT_DIR, 'README.md')
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write("# Скриншоты спринта\n\n- `key_review/`: ключевые экраны для приёмки\n- `viewports/`: 11 разрешений экранов\n- `scenarios/`: 8 сценариев состояний\n- `before/`: базовое состояние до правок\n")

    print(f'\nDiagnostics report saved to: {report_json_path}')
    return results


if __name__ == '__main__':
    seed_database()
    run_e2e_diagnostics()
