import os
import sys
import time
import subprocess
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash

# Clear proxy variables for local loopback testing
for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

# Set environment before any app imports
PG_URL = "postgresql://postgres@/boostudy_test?host=/tmp/pg_socket&port=54329"
os.environ["DATABASE_URL"] = PG_URL
os.environ["BOOSTUDY_ALLOW_TEST_POSTGRES"] = "1"
os.environ["BOOSTUDY_SKIP_DATABASE_BOOTSTRAP"] = "1"
os.environ["BOOSTUDY_BACKGROUND_WORKERS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "acceptance-secret-key-sprint231"
os.environ["ENVIRONMENT"] = "local"
os.environ["RATELIMIT_ENABLED"] = "false"
os.environ["LD_LIBRARY_PATH"] = "/tmp/pgsql/usr/lib"

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root)

SCREENSHOT_DIR = os.path.join(root, "docs", "schedule_sprint2_3_1_acceptance", "key_review")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

from app import create_app, db
from app.models import User, Student, Enrollment, UserProfile
from sqlalchemy import text


def seed_acceptance_database():
    """Seeds clean acceptance testing data into PostgreSQL."""
    print("[1/6] Seeding clean PostgreSQL test data...")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": PG_URL,
    })
    with app.app_context():
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        db.session.execute(text('TRUNCATE TABLE "Lessons", "Enrollments", "Students", "UserProfiles", "Users" RESTART IDENTITY CASCADE'))
        db.session.commit()

        # Teacher A (Ivan - CS)
        ivan = User(
            username="tutor_ivan_acc",
            email="ivan_acc@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Иван Сергеевич",
            is_active=True,
        )
        # Teacher B (Elena - Math)
        elena = User(
            username="tutor_elena_acc",
            email="elena_acc@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Елена Дмитриевна",
            is_active=True,
        )
        # Admin
        admin = User(
            username="admin_acc",
            email="admin_acc@example.com",
            password_hash=generate_password_hash("pass123"),
            role="creator",
            full_name="Главный Администратор",
            is_active=True,
        )
        # Student 1 (Alice - shared)
        alice_u = User(
            username="alice_acc",
            email="alice_acc@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Алиса Тестова",
            is_active=True,
        )
        # Student 2 (Bob - Ivan only)
        bob_u = User(
            username="bob_acc",
            email="bob_acc@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Боб Смирнов",
            is_active=True,
        )
        db.session.add_all([ivan, elena, admin, alice_u, bob_u])
        db.session.flush()

        alice_st = Student(
            user_id=alice_u.id,
            name="Алиса Тестова",
            lessons_balance=10,
            is_active=True,
        )
        bob_st = Student(
            user_id=bob_u.id,
            name="Боб Смирнов",
            mentor_id=ivan.id,
            lessons_balance=5,
            is_active=True,
        )
        db.session.add_all([alice_st, bob_st])
        db.session.flush()

        # Alice enrolled in CS with Ivan, Math with Elena
        enr_alice_cs = Enrollment(student_id=alice_u.id, tutor_id=ivan.id, subject="Информатика", status="active")
        enr_alice_math = Enrollment(student_id=alice_u.id, tutor_id=elena.id, subject="Математика", status="active")
        # Bob enrolled in CS with Ivan
        enr_bob_cs = Enrollment(student_id=bob_u.id, tutor_id=ivan.id, subject="Информатика", status="active")
        db.session.add_all([enr_alice_cs, enr_alice_math, enr_bob_cs])

        now_utc = datetime.now(timezone.utc)
        db.session.execute(
            text("INSERT INTO teacher_students (teacher_id, student_id, status, created_at) VALUES (:t1, :s1, :st, :c), (:t2, :s1, :st, :c), (:t1, :s2, :st, :c)"),
            {"t1": ivan.id, "t2": elena.id, "s1": alice_u.id, "s2": bob_u.id, "st": "active", "c": now_utc}
        )
        ivan_id = ivan.id
        elena_id = elena.id
        alice_st_id = alice_st.student_id
        bob_st_id = bob_st.student_id
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
        print("✓ Database seeded successfully!")
        return {
            "ivan_id": ivan_id,
            "elena_id": elena_id,
            "alice_st_id": alice_st_id,
            "bob_st_id": bob_st_id,
        }


def run_playwright_acceptance(fixtures):
    """Executes full Playwright browser acceptance scenarios and saves 10 screenshots."""
    from playwright.sync_api import sync_playwright

    server_process = None
    try:
        print("[2/6] Starting test server on http://127.0.0.1:5005...")
        env = os.environ.copy()
        server_log = open('/tmp/acceptance_server.log', 'w')
        server_process = subprocess.Popen(
            [sys.executable, "-c", """
import os
os.environ['RATELIMIT_ENABLED'] = 'false'
from app import create_app
app = create_app()
socketio = getattr(app, 'socketio', None)
if socketio:
    socketio.run(app, host='127.0.0.1', port=5005, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
else:
    app.run(host='127.0.0.1', port=5005, debug=False, use_reloader=False)
"""],
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            cwd=root,
        )

        import urllib.request
        started = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:5005/login", timeout=2)
                if resp.status == 200:
                    started = True
                    break
            except Exception:
                pass

        if not started:
            server_process.terminate()
            with open('/tmp/acceptance_server.log') as f_log:
                log_content = f_log.read()
            raise RuntimeError(f"Server failed to start on 5005:\nLOG:\n{log_content}")

        print("✓ Test server is live on http://127.0.0.1:5005!")

        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        tuesday_str = (monday + timedelta(days=1)).strftime("%Y-%m-%d")
        wednesday_str = (monday + timedelta(days=2)).strftime("%Y-%m-%d")
        print(f"Target week: Monday {monday}, Tuesday {tuesday_str}, Wednesday {wednesday_str}")

        with sync_playwright() as p:
            print("[3/6] Launching Playwright Chromium...")
            browser = p.chromium.launch(headless=True, args=['--no-proxy-server'])

            # ==============================================================
            # SCENARIO A: Teacher A (Ivan) logs in, opens modal, creates lesson
            # ==============================================================
            print("[4/6] Scenario A: Teacher A (Ivan) session & lesson creation...")
            context_a = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_a = context_a.new_page()

            page_a.goto("http://127.0.0.1:5005/login")
            page_a.fill('input[name="username"]', "tutor_ivan_acc")
            page_a.fill('input[name="password"]', "pass123")
            page_a.click('button[type="submit"]')
            page_a.wait_for_load_state("networkidle")
            page_a.goto("http://127.0.0.1:5005/schedule")
            page_a.wait_for_load_state("networkidle")
            time.sleep(1)

            # Click "Запланировать урок"
            page_a.click('button[onclick="openNewLessonModal()"]')
            page_a.wait_for_selector("#modal-new-lesson:not(.hidden)", state="visible")
            time.sleep(0.5)

            # Screenshot 04: Modal create lesson
            shot_04 = os.path.join(SCREENSHOT_DIR, "04_modal_create_lesson.png")
            page_a.screenshot(path=shot_04)
            print(f"✓ Saved: {shot_04}")

            # Select Alice
            page_a.select_option("#input-student-id", value=str(fixtures["alice_st_id"]))
            time.sleep(0.5)

            # Screenshot 05: Student and subject selector
            shot_05 = os.path.join(SCREENSHOT_DIR, "05_student_and_subject_selector.png")
            page_a.screenshot(path=shot_05)
            print(f"✓ Saved: {shot_05}")

            # Fill rest of form: Tuesday 17:00, 60m, Topic: Разбор задач №24 и №26
            page_a.fill("#input-topic", "Разбор задач №24 и №26")
            page_a.fill("#input-lesson-date", tuesday_str)
            page_a.fill("#input-start-time", "17:00")
            page_a.select_option("#input-duration", value="60")
            page_a.select_option("#input-status", value="planned")

            # Submit
            page_a.click('#modal-new-lesson button[type="submit"]')
            time.sleep(1.5)
            page_a.goto("http://127.0.0.1:5005/schedule")
            page_a.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 01: Teacher A week schedule with lesson
            shot_01 = os.path.join(SCREENSHOT_DIR, "01_teacher_a_week_schedule.png")
            page_a.screenshot(path=shot_01)
            print(f"✓ Saved: {shot_01}")

            # ==============================================================
            # SCENARIO B: Teacher B (Elena) logs in, tests isolation & conflict
            # ==============================================================
            print("[5/6] Scenario B: Teacher B (Elena) isolation & conflict detection...")
            context_b = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_b = context_b.new_page()

            page_b.goto("http://127.0.0.1:5005/login")
            page_b.fill('input[name="username"]', "tutor_elena_acc")
            page_b.fill('input[name="password"]', "pass123")
            page_b.click('button[type="submit"]')
            page_b.wait_for_load_state("networkidle")
            page_b.goto("http://127.0.0.1:5005/schedule")
            page_b.wait_for_load_state("networkidle")
            time.sleep(1)

            # Verification: Ivan's lesson must NOT be visible on Elena's board
            content_b = page_b.content()
            assert "Разбор задач №24 и №26" not in content_b, "CRITICAL: Cross-teacher leakage! Ivan's lesson appeared on Elena's schedule!"

            # Try to book conflicting lesson for Alice at Tuesday 17:00
            page_b.click('button[onclick="openNewLessonModal()"]')
            page_b.wait_for_selector("#modal-new-lesson:not(.hidden)", state="visible")
            time.sleep(0.5)

            page_b.select_option("#input-student-id", value=str(fixtures["alice_st_id"]))
            page_b.fill("#input-topic", "Конфликтный урок геометрии")
            page_b.fill("#input-lesson-date", tuesday_str)
            page_b.fill("#input-start-time", "17:00")
            page_b.select_option("#input-duration", value="60")
            page_b.click('#modal-new-lesson button[type="submit"]')

            # Wait for toast
            time.sleep(1)
            # Screenshot 06: Time conflict notification
            shot_06 = os.path.join(SCREENSHOT_DIR, "06_time_conflict_notification.png")
            page_b.screenshot(path=shot_06)
            print(f"✓ Saved: {shot_06}")

            # Change time to 19:00 (non-conflicting) and book
            page_b.fill("#input-topic", "Стереометрия и векторы")
            page_b.fill("#input-start-time", "19:00")
            page_b.click('#modal-new-lesson button[type="submit"]')
            time.sleep(1.5)
            page_b.goto("http://127.0.0.1:5005/schedule")
            page_b.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 02: Teacher B week schedule
            shot_02 = os.path.join(SCREENSHOT_DIR, "02_teacher_b_week_schedule.png")
            page_b.screenshot(path=shot_02)
            print(f"✓ Saved: {shot_02}")

            # ==============================================================
            # SCENARIO C: Student 1 (Alice) Concept D view
            # ==============================================================
            print("[6/6] Scenario C: Student 1 (Alice) Concept D view...")
            context_c = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_c = context_c.new_page()

            page_c.goto("http://127.0.0.1:5005/login")
            page_c.fill('input[name="username"]', "alice_acc")
            page_c.fill('input[name="password"]', "pass123")
            page_c.click('button[type="submit"]')
            page_c.wait_for_load_state("networkidle")
            page_c.goto("http://127.0.0.1:5005/schedule")
            page_c.wait_for_load_state("networkidle")
            time.sleep(1.5)

            # Click Tuesday in Concept D day selector
            tue_tab = page_c.query_selector('#unified-tab-1, [data-day-index="1"]')
            if tue_tab:
                tue_tab.click()
                time.sleep(1)

            # Screenshot 03: Shared student Concept D view
            shot_03 = os.path.join(SCREENSHOT_DIR, "03_shared_student_concept_d.png")
            page_c.screenshot(path=shot_03)
            print(f"✓ Saved: {shot_03}")

            # ==============================================================
            # SCENARIO D: Teacher A reschedules Tuesday lesson to Wednesday
            # ==============================================================
            print("Scenario D: Rescheduling Tuesday lesson to Wednesday...")
            page_a.goto("http://127.0.0.1:5005/schedule")
            page_a.wait_for_load_state("networkidle")
            time.sleep(1)
            lesson_el = page_a.query_selector('.lesson-card, [data-lesson-id]')
            if lesson_el:
                lesson_id = lesson_el.get_attribute('data-lesson-id')
                if lesson_id:
                    resched_resp = page_a.request.post(
                        f"http://127.0.0.1:5005/schedule/reschedule/{lesson_id}",
                        data={"new_date": wednesday_str, "new_time": "17:00"}
                    )
                    print(f"Reschedule response: {resched_resp.status}")
                page_a.reload()
                time.sleep(1.5)

            # Screenshot 09: Schedule after reschedule
            shot_09 = os.path.join(SCREENSHOT_DIR, "09_schedule_after_reschedule.png")
            page_a.screenshot(path=shot_09)
            print(f"✓ Saved: {shot_09}")

            # ==============================================================
            # SCENARIO E: Cancelled lesson view, Month view, Mobile view
            # ==============================================================
            print("Scenario E: Cancelled lesson view, Month view & Mobile view...")
            thursday_str = (monday + timedelta(days=3)).strftime("%Y-%m-%d")
            res = page_a.evaluate("""async (payload) => {
                const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                const resp = await fetch('/api/schedule/create_lesson', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
                    body: JSON.stringify(payload)
                });
                return resp.status;
            }""", {
                "student_id": fixtures["bob_st_id"],
                "subject": "Информатика",
                "topic": "Отмененный урок с Бобом",
                "lesson_date": thursday_str,
                "time": "16:00",
                "duration": 60,
                "status": "cancelled",
            })
            print(f"Created cancelled lesson via fetch: {res}")
            page_a.reload()
            time.sleep(1)

            # Screenshot 10: Cancelled lesson view
            shot_10 = os.path.join(SCREENSHOT_DIR, "10_cancelled_lesson_view.png")
            page_a.screenshot(path=shot_10)
            print(f"✓ Saved: {shot_10}")

            # Month view
            page_a.click('#btn-view-month')
            time.sleep(1)
            # Screenshot 07: Month view
            shot_07 = os.path.join(SCREENSHOT_DIR, "07_month_view_multiple_lessons.png")
            page_a.screenshot(path=shot_07)
            print(f"✓ Saved: {shot_07}")

            # Mobile view (viewport 390x844)
            page_a.click('#btn-view-week')
            time.sleep(0.5)
            page_a.set_viewport_size({"width": 390, "height": 844})
            time.sleep(1)
            # Screenshot 08: Mobile teacher schedule 390x844
            shot_08 = os.path.join(SCREENSHOT_DIR, "08_mobile_teacher_schedule_390x844.png")
            page_a.screenshot(path=shot_08)
            print(f"✓ Saved: {shot_08}")

            browser.close()
            print("✓ All 10 screenshots successfully captured!")

    finally:
        if server_process:
            print("Stopping test server...")
            server_process.terminate()
            server_process.wait(timeout=5)
            print("✓ Test server stopped.")


if __name__ == "__main__":
    fixtures = seed_acceptance_database()
    run_playwright_acceptance(fixtures)
