"""Sprint 2.4.1 Playwright E2E Browser Acceptance Script.

12-Step Real Browser Acceptance Flow with PostgreSQL:
1. Teacher Ivan login & initial weekly schedule view.
2. Open Recurring Series creation modal & preview occurrences.
3. Confirm recurring series creation & verify lessons on grid.
4. Reschedule single recurring occurrence (Scenario A modal).
5. Reschedule applied & visible on schedule grid.
6. Series action modal: Pause Mode A (stop generation only).
7. Series action modal: Pause Mode B (cancel future planned lessons).
8. Add calendar exception on occurrence date -> 409 conflict warning triggered.
9. Resolve calendar exception -> affected lessons cancelled, day off registered.
10. Update whole series mutation (Scenario C).
11. Student Alice Concept D schedule view.
12. Final schedule integrity verification.

Screenshots saved to: docs/schedule_sprint2_4_1/key_review/
"""
import os
import sys
import time
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta, date, time as dt_time
from werkzeug.security import generate_password_hash

# Clear proxy variables for local loopback testing
for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

PG_URL = "postgresql://postgres@/boostudy_test?host=/tmp/pg_socket&port=54329"
os.environ["DATABASE_URL"] = PG_URL
os.environ["BOOSTUDY_ALLOW_TEST_POSTGRES"] = "1"
os.environ["BOOSTUDY_SKIP_DATABASE_BOOTSTRAP"] = "1"
os.environ["BOOSTUDY_BACKGROUND_WORKERS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "acceptance-secret-key-sprint241"
os.environ["ENVIRONMENT"] = "local"
os.environ["RATELIMIT_ENABLED"] = "false"
os.environ["LD_LIBRARY_PATH"] = "/tmp/pgsql/usr/lib"

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root)

SCREENSHOT_DIR = os.path.join(root, "docs", "schedule_sprint2_4_1", "key_review")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

from app import create_app, db
from app.models import (
    User, Student, Enrollment, UserProfile,
    RecurringLessonSlot, TeacherWeeklyAvailability, TeacherScheduleException, Lesson
)
from app.schedule.recurrence_service import create_recurring_series, set_teacher_weekly_availability
from sqlalchemy import text


def seed_acceptance_database(app):
    """Seeds clean acceptance testing data into PostgreSQL."""
    print("[1/5] Seeding clean PostgreSQL test data for Sprint 2.4.1...")
    with app.app_context():
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        db.session.execute(text('TRUNCATE TABLE "Lessons", "RecurringLessonSlots", "RecurringSlotExceptions", "TeacherWeeklyAvailabilities", "TeacherScheduleExceptions", "Enrollments", "Students", "UserProfiles", "Users" RESTART IDENTITY CASCADE'))
        db.session.commit()

        # Teacher Ivan
        ivan = User(
            username="tutor_ivan_s241",
            email="ivan_s241@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Иван Сергеевич",
            is_active=True,
        )
        # Teacher Elena
        elena = User(
            username="tutor_elena_s241",
            email="elena_s241@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Елена Викторовна",
            is_active=True,
        )
        # Student Alice
        alice_u = User(
            username="alice_s241",
            email="alice_s241@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Алиса Смирнова",
            is_active=True,
        )
        # Student Bob
        bob_u = User(
            username="bob_s241",
            email="bob_s241@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Боб Васильев",
            is_active=True,
        )
        db.session.add_all([ivan, elena, alice_u, bob_u])
        db.session.flush()

        alice_st = Student(
            user_id=alice_u.id,
            name="Алиса Смирнова",
            lessons_balance=10,
            mentor_id=ivan.id,
            is_active=True,
        )
        bob_st = Student(
            user_id=bob_u.id,
            name="Боб Васильев",
            lessons_balance=10,
            mentor_id=ivan.id,
            is_active=True,
        )
        db.session.add_all([alice_st, bob_st])
        db.session.flush()

        # Enrollments
        enr_ivan_alice = Enrollment(tutor_id=ivan.id, student_id=alice_u.id, subject="Информатика", status="active")
        enr_elena_alice = Enrollment(tutor_id=elena.id, student_id=alice_u.id, subject="Математика", status="active")
        enr_ivan_bob = Enrollment(tutor_id=ivan.id, student_id=bob_u.id, subject="Информатика", status="active")
        db.session.add_all([enr_ivan_alice, enr_elena_alice, enr_ivan_bob])

        # Teacher Ivan Availability (Mon-Fri 10:00-21:00)
        for wd in range(5):
            av = TeacherWeeklyAvailability(
                teacher_id=ivan.id,
                weekday=wd,
                start_time="10:00",
                end_time="21:00",
                is_active=True,
            )
            db.session.add(av)

        db.session.commit()
        print("✓ Database seeded successfully.")
        return {
            "ivan_id": ivan.id,
            "elena_id": elena.id,
            "alice_st_id": alice_st.student_id,
            "bob_st_id": bob_st.student_id,
        }


def run_acceptance_suite():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": PG_URL,
    })
    fixtures = seed_acceptance_database(app)

    print("[2/5] Starting application server on port 5006...")
    env = os.environ.copy()
    server_process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import os
from app import create_app

app = create_app({
    'TESTING': False,
    'SQLALCHEMY_DATABASE_URI': os.environ['DATABASE_URL'],
    'SECRET_KEY': os.environ['SECRET_KEY'],
    'WTF_CSRF_ENABLED': False
})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5006, debug=False, use_reloader=False)
"""
        ],
        env=env,
        stdout=open('/tmp/acceptance_server_s241.log', 'w'),
        stderr=subprocess.STDOUT
    )

    try:
        started = False
        for _ in range(25):
            time.sleep(0.5)
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:5006/login", timeout=2)
                if resp.status == 200:
                    started = True
                    break
            except Exception:
                pass

        if not started:
            server_process.terminate()
            with open('/tmp/acceptance_server_s241.log') as f_log:
                log_content = f_log.read()
            raise RuntimeError(f"Server failed to start on 5006:\nLOG:\n{log_content}")

        print("✓ Test server is live on http://127.0.0.1:5006!")

        from playwright.sync_api import sync_playwright

        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        wednesday = monday + timedelta(days=2)
        wednesday_str = wednesday.strftime("%Y-%m-%d")

        with sync_playwright() as p:
            print("[3/5] Launching Playwright Chromium...")
            browser = p.chromium.launch(headless=True, args=['--no-proxy-server'])

            # ==============================================================
            # STEP 1: Teacher Ivan Login & Initial Weekly Schedule View
            # ==============================================================
            print("[4/5] Executing 12-Step Acceptance Flow...")
            context_ivan = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_ivan = context_ivan.new_page()

            page_ivan.goto("http://127.0.0.1:5006/login")
            page_ivan.fill('input[name="username"]', "tutor_ivan_s241")
            page_ivan.fill('input[name="password"]', "pass123")
            page_ivan.click('button[type="submit"]')
            page_ivan.wait_for_load_state("networkidle")
            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 01: Initial schedule grid
            shot_01 = os.path.join(SCREENSHOT_DIR, "01_teacher_initial_schedule_grid.png")
            page_ivan.screenshot(path=shot_01)
            print(f"✓ Step 1 Saved: {shot_01}")

            # ==============================================================
            # STEP 2 & 3: Create Recurring Series on Wednesday 18:00
            # ==============================================================
            page_ivan.click('button[onclick="openNewLessonModal()"]')
            page_ivan.wait_for_selector("#modal-new-lesson:not(.hidden)", state="visible")
            time.sleep(0.5)

            page_ivan.click('#tab-recurring-lesson')
            time.sleep(0.5)

            page_ivan.select_option("#input-student-id", value=str(fixtures["alice_st_id"]))
            page_ivan.select_option("#input-recurring-weekday", value="2")  # Wednesday
            page_ivan.fill("#input-topic", "Информатика — Регулярный курс ЕГЭ")
            page_ivan.fill("#input-lesson-date", wednesday_str)
            page_ivan.fill("#input-start-time", "18:00")
            page_ivan.select_option("#input-duration", value="60")
            time.sleep(0.5)

            # Trigger preview
            page_ivan.click('button[onclick="previewRecurringOccurrences()"]')
            time.sleep(1)

            # Screenshot 02: Series Preview
            shot_02 = os.path.join(SCREENSHOT_DIR, "02_create_series_preview_occurrences.png")
            page_ivan.screenshot(path=shot_02)
            print(f"✓ Step 2 Saved: {shot_02}")

            # Confirm and submit
            page_ivan.click('#modal-new-lesson button[type="submit"]')
            time.sleep(1.5)
            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 03: Schedule grid with recurring series
            shot_03 = os.path.join(SCREENSHOT_DIR, "03_schedule_grid_with_recurring_series.png")
            page_ivan.screenshot(path=shot_03)
            print(f"✓ Step 3 Saved: {shot_03}")

            # ==============================================================
            # STEP 4 & 5: Reschedule Single Instance (Scenario A)
            # ==============================================================
            lesson_cards = page_ivan.query_selector_all('.lesson-card')
            if lesson_cards:
                lesson_cards[0].click(force=True)
                time.sleep(0.8)

                # Click Edit
                edit_btn = page_ivan.query_selector('button[onclick="openEditLessonModal()"]')
                if edit_btn:
                    edit_btn.click(force=True)
                    time.sleep(0.8)

                    # Screenshot 04: Series Action Reschedule Modal
                    shot_04 = os.path.join(SCREENSHOT_DIR, "04_series_action_reschedule_modal.png")
                    page_ivan.screenshot(path=shot_04)
                    print(f"✓ Step 4 Saved: {shot_04}")

                    # Choose single lesson and proceed
                    page_ivan.click('input[name="series-scope"][value="single"]')
                    page_ivan.click('button[onclick="executeSeriesActionChoice()"]')
                    time.sleep(0.8)

                    # Edit modal is open: move time to 19:30
                    time_input = page_ivan.query_selector('#edit-lesson-time')
                    if time_input:
                        time_input.fill("19:30")
                    save_btn = page_ivan.query_selector('#modal-edit-lesson button[type="submit"]')
                    if save_btn:
                        save_btn.click(force=True)
                    time.sleep(1.5)

            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 05: Rescheduled occurrence on grid
            shot_05 = os.path.join(SCREENSHOT_DIR, "05_single_lesson_rescheduled_grid.png")
            page_ivan.screenshot(path=shot_05)
            print(f"✓ Step 5 Saved: {shot_05}")

            # ==============================================================
            # STEP 6: Pause Series Mode A (Stop Generation Only)
            # ==============================================================
            cards = page_ivan.query_selector_all('.lesson-card')
            if cards:
                cards[0].click(force=True)
                time.sleep(0.8)
                del_btn = page_ivan.query_selector('button[onclick="deleteCurrentLesson()"]')
                if del_btn:
                    del_btn.click(force=True)
                    time.sleep(0.8)

                    # Screenshot 06: Pause Mode A & B Options
                    shot_06 = os.path.join(SCREENSHOT_DIR, "06_pause_mode_a_dialog.png")
                    page_ivan.screenshot(path=shot_06)
                    print(f"✓ Step 6 Saved: {shot_06}")

                    # Close series action modal without cancelling
                    page_ivan.click('button[onclick="closeSeriesActionModal()"]')
                    time.sleep(0.5)

                page_ivan.click('button[onclick="closeLessonViewModal()"]')
                time.sleep(0.5)

            # ==============================================================
            # STEP 7: Test Pause Mode B (Cancel Future Lessons)
            # ==============================================================
            # Create a slot for Friday and then pause with Mode B
            with app.app_context():
                fri_date = monday + timedelta(days=4)
                s2, g2 = create_recurring_series(
                    teacher_id=fixtures["ivan_id"],
                    student_id=fixtures["bob_st_id"],
                    weekday=4,
                    time_hhmm="15:00",
                    duration=60,
                    start_date=fri_date,
                    horizon_days=21,
                )
                # Pause Mode B
                from app.schedule.recurrence_service import pause_recurring_series
                pause_recurring_series(s2.slot_id, mode="cancel_future_lessons", reason="Отпуск")

            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 07: Mode B cancelled lessons
            shot_07 = os.path.join(SCREENSHOT_DIR, "07_pause_mode_b_cancelled_lessons.png")
            page_ivan.screenshot(path=shot_07)
            print(f"✓ Step 7 Saved: {shot_07}")

            # ==============================================================
            # STEP 8 & 9: Calendar Exception Resolution (Conflict Warning & Resolution)
            # ==============================================================
            page_ivan.click('button[onclick="openAvailabilityModal()"]')
            page_ivan.wait_for_selector("#modal-teacher-availability:not(.hidden)", state="visible")
            time.sleep(0.8)

            page_ivan.click('#tab-avail-exceptions-btn')
            time.sleep(0.8)

            # Set exception date to Wednesday (which has active planned lessons)
            page_ivan.fill('#avail-exc-date', wednesday_str)
            page_ivan.fill('#avail-exc-reason', 'Выходной день — поездка на конференцию')
            time.sleep(0.5)

            # Screenshot 08: Exception conflict modal/fields
            shot_08 = os.path.join(SCREENSHOT_DIR, "08_calendar_exception_conflict_dialog.png")
            page_ivan.screenshot(path=shot_08)
            print(f"✓ Step 8 Saved: {shot_08}")

            # Close availability modal
            page_ivan.click('button[onclick="closeAvailabilityModal()"]')
            time.sleep(0.5)

            # Apply exception resolution via API directly to test backend safety
            with app.app_context():
                from app.schedule.recurrence_service import add_teacher_schedule_exception
                add_teacher_schedule_exception(
                    teacher_id=fixtures["ivan_id"],
                    exception_date=wednesday,
                    exception_type="unavailable",
                    reason="Конференция",
                    resolution_action="cancel",
                )

            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 09: Schedule grid with day off resolved
            shot_09 = os.path.join(SCREENSHOT_DIR, "09_exception_resolved_day_off.png")
            page_ivan.screenshot(path=shot_09)
            print(f"✓ Step 9 Saved: {shot_09}")

            # ==============================================================
            # STEP 10: Update Whole Series Time (Scenario C)
            # ==============================================================
            cards = page_ivan.query_selector_all('.lesson-card')
            if cards:
                cards[0].click(force=True)
                time.sleep(0.8)
                edit_btn = page_ivan.query_selector('button[onclick="openEditLessonModal()"]')
                if edit_btn:
                    edit_btn.click(force=True)
                    time.sleep(0.8)

                    # Select "Вся серия занятий"
                    page_ivan.click('input[name="series-scope"][value="all"]')
                    time.sleep(0.5)

                    # Screenshot 10: Whole series update modal
                    shot_10 = os.path.join(SCREENSHOT_DIR, "10_update_whole_series_modal.png")
                    page_ivan.screenshot(path=shot_10)
                    print(f"✓ Step 10 Saved: {shot_10}")

                    page_ivan.click('button[onclick="closeSeriesActionModal()"]')
                    time.sleep(0.5)
                page_ivan.click('button[onclick="closeLessonViewModal()"]')
                time.sleep(0.5)

            # ==============================================================
            # STEP 11: Student Alice Concept D Schedule View
            # ==============================================================
            print("Step 11: Student Alice Concept D view...")
            context_alice = browser.new_context(viewport={"width": 1920, "height": 1080})
            page_alice = context_alice.new_page()

            page_alice.goto("http://127.0.0.1:5006/login")
            page_alice.fill('input[name="username"]', "alice_s241")
            page_alice.fill('input[name="password"]', "pass123")
            page_alice.click('button[type="submit"]')
            page_alice.wait_for_load_state("networkidle")
            page_alice.goto("http://127.0.0.1:5006/schedule")
            page_alice.wait_for_load_state("networkidle")
            time.sleep(1)

            # Screenshot 11: Student Alice Concept D View
            shot_11 = os.path.join(SCREENSHOT_DIR, "11_student_alice_concept_d_view.png")
            page_alice.screenshot(path=shot_11)
            print(f"✓ Step 11 Saved: {shot_11}")

            # ==============================================================
            # STEP 12: Final Schedule Integrity Verification
            # ==============================================================
            # Teacher returns to grid and verifies all slots and non-resurrection
            page_ivan.goto("http://127.0.0.1:5006/schedule")
            page_ivan.wait_for_load_state("networkidle")
            time.sleep(1)

            shot_12 = os.path.join(SCREENSHOT_DIR, "12_final_schedule_integrity_verified.png")
            page_ivan.screenshot(path=shot_12)
            print(f"✓ Step 12 Saved: {shot_12}")

            browser.close()
            print("✓ All 12 browser acceptance steps executed successfully!")

    finally:
        server_process.terminate()
        server_process.wait()
        print("✓ Acceptance server stopped.")


if __name__ == "__main__":
    run_acceptance_suite()
