import os
import sys
import time
import subprocess
from datetime import datetime, timezone, timedelta, date, time as dt_time
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
os.environ["SECRET_KEY"] = "acceptance-secret-key-sprint24"
os.environ["ENVIRONMENT"] = "local"
os.environ["RATELIMIT_ENABLED"] = "false"
os.environ["LD_LIBRARY_PATH"] = "/tmp/pgsql/usr/lib"

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root)

SCREENSHOT_DIR = os.path.join(root, "docs", "schedule_sprint2_4", "key_review")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

from app import create_app, db
from app.models import (
    User, Student, Enrollment, UserProfile,
    RecurringLessonSlot, TeacherWeeklyAvailability, TeacherScheduleException, Lesson
)
from app.schedule.recurrence_service import create_recurring_series, set_teacher_weekly_availability, add_teacher_schedule_exception
from sqlalchemy import text


def seed_acceptance_database():
    """Seeds clean acceptance testing data into PostgreSQL."""
    print("[1/6] Seeding clean PostgreSQL test data for Sprint 2.4...")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": PG_URL,
    })
    with app.app_context():
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        db.session.execute(text('TRUNCATE TABLE "Lessons", "RecurringLessonSlots", "RecurringSlotExceptions", "TeacherWeeklyAvailabilities", "TeacherScheduleExceptions", "Enrollments", "Students", "UserProfiles", "Users" RESTART IDENTITY CASCADE'))
        db.session.commit()

        # Teacher A (Ivan - CS)
        ivan = User(
            username="tutor_ivan_s24",
            email="ivan_s24@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Иван Сергеевич",
            is_active=True,
        )
        # Teacher B (Elena - Math)
        elena = User(
            username="tutor_elena_s24",
            email="elena_s24@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Елена Дмитриевна",
            is_active=True,
        )
        # Student 1 (Alice - shared)
        alice_u = User(
            username="alice_s24",
            email="alice_s24@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Алиса Тестова",
            is_active=True,
        )
        # Student 2 (Bob - Ivan only)
        bob_u = User(
            username="bob_s24",
            email="bob_s24@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Боб Смирнов",
            is_active=True,
        )
        db.session.add_all([ivan, elena, alice_u, bob_u])
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

        # Enrollments
        enr_alice_cs = Enrollment(student_id=alice_u.id, tutor_id=ivan.id, subject="Информатика", status="active")
        enr_alice_math = Enrollment(student_id=alice_u.id, tutor_id=elena.id, subject="Математика", status="active")
        enr_bob_cs = Enrollment(student_id=bob_u.id, tutor_id=ivan.id, subject="Информатика", status="active")
        db.session.add_all([enr_alice_cs, enr_alice_math, enr_bob_cs])

        now_utc = datetime.now(timezone.utc)
        db.session.execute(
            text("INSERT INTO teacher_students (teacher_id, student_id, status, created_at) VALUES (:t1, :s1, :st, :c), (:t2, :s1, :st, :c), (:t1, :s2, :st, :c)"),
            {"t1": ivan.id, "t2": elena.id, "s1": alice_u.id, "s2": bob_u.id, "st": "active", "c": now_utc}
        )
        db.session.commit()

        # Configure Weekly Availability for Ivan: Mon-Fri 14:00 - 20:00
        intervals = [
            {"weekday": d, "start_time": "14:00", "end_time": "20:00"} for d in range(5)
        ]
        set_teacher_weekly_availability(ivan.id, intervals)

        # Configure Holiday Exception for Ivan: Next Friday is Day Off
        today = date.today()
        next_friday = today + timedelta(days=(4 - today.weekday()) % 7 + 7)
        add_teacher_schedule_exception(
            teacher_id=ivan.id,
            exc_date=next_friday,
            exception_type="unavailable",
            reason="Государственный праздник / Выходной",
        )

        # Create Recurring Series for Elena: Thursdays at 16:00 (Math)
        thursday_wd = 3  # Thursday (0=Mon, 3=Thu)
        slot_elena, lessons_elena = create_recurring_series(
            teacher_id=elena.id,
            student_id=alice_st.student_id,
            subject="Математика",
            weekday=thursday_wd,
            start_time="16:00",
            duration_minutes=60,
            topic="Математика — Профиль (Серия)",
            start_date=today - timedelta(days=today.weekday()),
            horizon_days=28,
        )

        ivan_id = ivan.id
        elena_id = elena.id
        alice_st_id = alice_st.student_id
        bob_st_id = bob_st.student_id
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
        print("✓ Database seeded successfully with multi-teacher recurring data and availability!")
        return {
            "ivan_id": ivan_id,
            "elena_id": elena_id,
            "alice_st_id": alice_st_id,
            "bob_st_id": bob_st_id,
            "next_friday": next_friday,
        }


def run_playwright_acceptance(fixtures):
    """Executes full Playwright browser acceptance scenarios and saves 10 screenshots."""
    from playwright.sync_api import sync_playwright

    server_process = None
    try:
        print("[2/6] Starting test server on http://127.0.0.1:5005...")
        env = os.environ.copy()
        server_log = open('/tmp/acceptance_server_s24.log', 'w')
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
            with open('/tmp/acceptance_server_s24.log') as f_log:
                log_content = f_log.read()
            raise RuntimeError(f"Server failed to start on 5005:\nLOG:\n{log_content}")

        print("✓ Test server is live on http://127.0.0.1:5005!")

        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        tuesday_str = (monday + timedelta(days=1)).strftime("%Y-%m-%d")

        with sync_playwright() as p:
            print("[3/6] Launching Playwright Chromium...")
            browser = p.chromium.launch(headless=True, args=['--no-proxy-server'])

            # ==============================================================
            # SCENARIO 1: Teacher Ivan opens modal to create Recurring Series
            # ==============================================================
            print("[4/6] Scenario 1: Teacher Ivan login & recurring series creation...")
            context_ivan = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_ivan = context_ivan.new_page()

            page_ivan.goto("http://127.0.0.1:5005/login")
            page_ivan.fill('input[name="username"]', "tutor_ivan_s24")
            page_ivan.fill('input[name="password"]', "pass123")
            page_ivan.click('button[type="submit"]')
            page_ivan.wait_for_load_state("networkidle")
            page_ivan.goto("http://127.0.0.1:5005/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Open New Lesson Modal
            page_ivan.click('button[onclick="openNewLessonModal()"]')
            page_ivan.wait_for_selector("#modal-new-lesson:not(.hidden)", state="visible")
            time.sleep(0.5)

            # Switch to Recurring Tab
            page_ivan.click('#tab-recurring-lesson')
            time.sleep(0.5)

            # Select Alice, Subject: Информатика, Tuesday, 17:00, 60m
            page_ivan.select_option("#input-student-id", value=str(fixtures["alice_st_id"]))
            page_ivan.select_option("#input-recurring-weekday", value="1") # Tuesday
            page_ivan.fill("#input-topic", "Информатика — Регулярная серия (ЕГЭ)")
            page_ivan.fill("#input-lesson-date", tuesday_str)
            page_ivan.fill("#input-start-time", "17:00")
            page_ivan.select_option("#input-duration", value="60")
            time.sleep(0.5)

            # Trigger preview
            page_ivan.click('button[onclick="previewRecurringOccurrences()"]')
            time.sleep(1)

            # Screenshot 01: Modal Create Recurring Series
            shot_01 = os.path.join(SCREENSHOT_DIR, "01_teacher_create_recurring_series_modal.png")
            page_ivan.screenshot(path=shot_01)
            print(f"✓ Saved: {shot_01}")

            # Submit Recurring Series
            page_ivan.click('#modal-new-lesson button[type="submit"]')
            time.sleep(1.5)
            page_ivan.goto("http://127.0.0.1:5005/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 02: Teacher Weekly Schedule with Recurring Badges
            shot_02 = os.path.join(SCREENSHOT_DIR, "02_teacher_weekly_schedule_recurring_badges.png")
            page_ivan.screenshot(path=shot_02)
            print(f"✓ Saved: {shot_02}")

            # ==============================================================
            # SCENARIO 2: Teacher Ivan Availability Management Modal
            # ==============================================================
            print("Scenario 2: Teacher Availability management...")
            page_ivan.click('button[onclick="openAvailabilityModal()"]')
            page_ivan.wait_for_selector("#modal-teacher-availability:not(.hidden)", state="visible")
            time.sleep(0.8)

            # Screenshot 03: Manage Working Hours Availability
            shot_03 = os.path.join(SCREENSHOT_DIR, "03_teacher_manage_working_hours_availability.png")
            page_ivan.screenshot(path=shot_03)
            print(f"✓ Saved: {shot_03}")

            # Switch to exceptions tab
            page_ivan.click('#tab-avail-exceptions-btn')
            time.sleep(0.8)

            # Screenshot 04: Holiday Schedule Exception
            shot_04 = os.path.join(SCREENSHOT_DIR, "04_teacher_schedule_holiday_exception.png")
            page_ivan.screenshot(path=shot_04)
            print(f"✓ Saved: {shot_04}")

            # Close Availability Modal
            page_ivan.click('button[onclick="closeAvailabilityModal()"]')
            time.sleep(0.5)

            # ==============================================================
            # SCENARIO 3: Reschedule and Cancel Single Recurring Instance
            # ==============================================================
            print("Scenario 3: Reschedule / cancel single recurring instance...")
            # Click on recurring lesson card
            lesson_card = page_ivan.query_selector('.lesson-card')
            if lesson_card:
                lesson_card.click(force=True)
                time.sleep(0.8)

                # Open Edit Modal
                edit_btn = page_ivan.query_selector('button[onclick="openEditLessonModal()"]')
                if edit_btn:
                    edit_btn.click(force=True)
                    time.sleep(0.8)

                    # Series action modal opens asking scope (single vs future vs all)
                    scope_modal = page_ivan.query_selector('#modal-series-action:not(.hidden)')
                    if scope_modal:
                        shot_05 = os.path.join(SCREENSHOT_DIR, "05_teacher_reschedule_single_instance_modal.png")
                        page_ivan.screenshot(path=shot_05)
                        print(f"✓ Saved: {shot_05}")
                        # Close series modal
                        page_ivan.click('button[onclick="closeSeriesActionModal()"]')
                        time.sleep(0.5)

                # Test Cancel scope
                del_btn = page_ivan.query_selector('button[onclick="deleteCurrentLesson()"]')
                if del_btn:
                    del_btn.click(force=True)
                    time.sleep(0.8)
                    shot_06 = os.path.join(SCREENSHOT_DIR, "06_teacher_cancel_single_instance_modal.png")
                    page_ivan.screenshot(path=shot_06)
                    print(f"✓ Saved: {shot_06}")
                    # Close modal
                    page_ivan.click('button[onclick="closeSeriesActionModal()"]')
                    time.sleep(0.5)
                page_ivan.click('button[onclick="closeLessonViewModal()"]')
                time.sleep(0.5)

            # ==============================================================
            # SCENARIO 4: Student Alice Concept D Multi-Teacher Recurring
            # ==============================================================
            print("[5/6] Scenario 4: Student Alice Concept D view...")
            context_alice = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_alice = context_alice.new_page()

            page_alice.goto("http://127.0.0.1:5005/login")
            page_alice.fill('input[name="username"]', "alice_s24")
            page_alice.fill('input[name="password"]', "pass123")
            page_alice.click('button[type="submit"]')
            page_alice.wait_for_load_state("networkidle")
            page_alice.goto("http://127.0.0.1:5005/schedule")
            page_alice.wait_for_load_state("networkidle")
            time.sleep(1.5)

            # Screenshot 07: Shared Student Concept D Multi-Teacher Recurring
            shot_07 = os.path.join(SCREENSHOT_DIR, "07_student_concept_d_multi_teacher_recurring.png")
            page_alice.screenshot(path=shot_07)
            print(f"✓ Saved: {shot_07}")

            # Click Tuesday or Thursday tab in Concept D
            tue_tab = page_alice.query_selector('#unified-tab-1, [data-day-index="1"]')
            if tue_tab:
                tue_tab.click()
                time.sleep(0.8)

            # Screenshot 08: Student Concept D Rescheduled / Day Reflection
            shot_08 = os.path.join(SCREENSHOT_DIR, "08_student_concept_d_rescheduled_reflection.png")
            page_alice.screenshot(path=shot_08)
            print(f"✓ Saved: {shot_08}")

            # ==============================================================
            # SCENARIO 5: Mobile Viewports (390x844)
            # ==============================================================
            print("[6/6] Scenario 5: Mobile viewports (390x844)...")
            # Teacher Ivan Mobile
            context_ivan_mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
            )
            page_ivan_mobile = context_ivan_mobile.new_page()
            page_ivan_mobile.goto("http://127.0.0.1:5005/login")
            page_ivan_mobile.fill('input[name="username"]', "tutor_ivan_s24")
            page_ivan_mobile.fill('input[name="password"]', "pass123")
            page_ivan_mobile.click('button[type="submit"]')
            page_ivan_mobile.wait_for_load_state("networkidle")
            page_ivan_mobile.goto("http://127.0.0.1:5005/schedule")
            page_ivan_mobile.wait_for_load_state("networkidle")
            time.sleep(1.5)

            shot_09 = os.path.join(SCREENSHOT_DIR, "09_teacher_mobile_recurring_schedule_390x844.png")
            page_ivan_mobile.screenshot(path=shot_09)
            print(f"✓ Saved: {shot_09}")

            # Student Alice Mobile
            context_alice_mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
            )
            page_alice_mobile = context_alice_mobile.new_page()
            page_alice_mobile.goto("http://127.0.0.1:5005/login")
            page_alice_mobile.fill('input[name="username"]', "alice_s24")
            page_alice_mobile.fill('input[name="password"]', "pass123")
            page_alice_mobile.click('button[type="submit"]')
            page_alice_mobile.wait_for_load_state("networkidle")
            page_alice_mobile.goto("http://127.0.0.1:5005/schedule")
            page_alice_mobile.wait_for_load_state("networkidle")
            time.sleep(1.5)

            shot_10 = os.path.join(SCREENSHOT_DIR, "10_student_mobile_concept_d_schedule_390x844.png")
            page_alice_mobile.screenshot(path=shot_10)
            print(f"✓ Saved: {shot_10}")

            browser.close()
            print("✓ All 10 screenshots generated successfully!")

    finally:
        if server_process:
            print("Stopping test server...")
            server_process.terminate()
            server_process.wait()


if __name__ == "__main__":
    fixtures = seed_acceptance_database()
    run_playwright_acceptance(fixtures)
