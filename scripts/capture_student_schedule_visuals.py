"""
Captures student schedule screenshots for Sprint 2.5 visual review across viewports and scenarios.
"""
import os
import sys
import time
import subprocess
import urllib.request
from datetime import datetime, date, timedelta, timezone

PG_URL = "postgresql://postgres@/boostudy_test?host=/tmp/pg_socket&port=54329"
SCREENSHOT_DIR = os.path.abspath("docs/schedule_sprint2_5_1")
PORT = 5007


def ensure_rich_student_data():
    os.environ["DATABASE_URL"] = PG_URL
    os.environ["BOOSTUDY_ALLOW_TEST_POSTGRES"] = "1"
    os.environ["BOOSTUDY_SKIP_DATABASE_BOOTSTRAP"] = "1"
    os.environ["BOOSTUDY_BACKGROUND_WORKERS_ENABLED"] = "0"
    
    from app import create_app, db
    from app.models import User, Student, Lesson
    from core.db_models import Enrollment, RecurringLessonSlot
    from werkzeug.security import generate_password_hash
    from sqlalchemy import text

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": PG_URL})
    with app.app_context():
        # Setup users
        db.session.execute(text('TRUNCATE TABLE "Lessons", "RecurringLessonSlots", "RecurringSlotExceptions", "TeacherWeeklyAvailabilities", "TeacherScheduleExceptions", "Enrollments", "Students", "UserProfiles", "Users" RESTART IDENTITY CASCADE'))
        db.session.commit()

        # Teacher 1: Ivan (Informatics)
        ivan = User(
            username="tutor_ivan_s25",
            email="ivan_s25@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Иван Сергеевич",
            is_active=True,
        )
        # Teacher 2: Elena (Mathematics)
        elena = User(
            username="tutor_elena_s25",
            email="elena_s25@example.com",
            password_hash=generate_password_hash("pass123"),
            role="tutor",
            full_name="Елена Викторовна",
            is_active=True,
        )
        # Student: Alice
        alice = User(
            username="alice_s25",
            email="alice_s25@example.com",
            password_hash=generate_password_hash("pass123"),
            role="student",
            full_name="Алиса Смирнова",
            is_active=True,
        )
        db.session.add_all([ivan, elena, alice])
        db.session.commit()

        from core.db_models import UserProfile, Assignment, Submission
        prof_ivan = UserProfile(user_id=ivan.id, first_name="Иван", last_name="Сергеевич", avatar_url="/static/images/schedule/mock_teacher_avatar.png")
        prof_elena = UserProfile(user_id=elena.id, first_name="Елена", last_name="Викторовна", avatar_url="/static/images/schedule/mock_teacher_avatar.png")
        db.session.add_all([prof_ivan, prof_elena])
        db.session.commit()

        st_alice = Student(
            user_id=alice.id,
            name="Алиса Смирнова",
            email=alice.email,
            mentor_id=ivan.id,
            streak_days=5,
        )
        db.session.add(st_alice)
        db.session.commit()

        enr_ivan = Enrollment(tutor_id=ivan.id, student_id=st_alice.student_id, subject="Информатика", status="active")
        enr_elena = Enrollment(tutor_id=elena.id, student_id=st_alice.student_id, subject="Математика", status="active")
        db.session.add_all([enr_ivan, enr_elena])
        db.session.commit()

        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())

        # Monday (day 0): 1 lesson (Completed)
        l_mon = Lesson(
            teacher_id=ivan.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(monday.year, monday.month, monday.day, 14, 0, tzinfo=timezone.utc),
            duration=60,
            status="completed",
            subject="Информатика",
            topic="Динамическое программирование: основы и таблицы",
            notes="Отличная работа с базовыми задачами. Повторить рекуррентные формулы.",
            materials=[
                {"title": "Конспект: Таблицы ДП", "url": "#", "type": "theory", "pages": "PDF • 12 стр."},
                {"title": "Шпаргалка по рекурсии", "url": "#", "type": "material", "pages": "DOC • 4 стр."},
            ]
        )

        # Tuesday (day 1): 1 lesson (In progress / Live!)
        tue = monday + timedelta(days=1)
        l_tue = Lesson(
            teacher_id=ivan.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(tue.year, tue.month, tue.day, 15, 0, tzinfo=timezone.utc),
            duration=60,
            status="in_progress",
            subject="Информатика",
            topic="Обработка графов и поиск в глубину (DFS)",
            notes="Подготовь блокнот и разбери матрицу смежности.",
            materials=[
                {"title": "Справочник алгоритмов на графах", "url": "#", "type": "theory", "pages": "PDF • 8 стр."},
            ]
        )

        # Wednesday (day 2): Packed Day (2 lessons from 2 tutors)
        wed = monday + timedelta(days=2)
        l_wed_1 = Lesson(
            teacher_id=ivan.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(wed.year, wed.month, wed.day, 13, 0, tzinfo=timezone.utc),
            duration=60,
            status="planned",
            subject="Информатика",
            topic="Разбор заданий № 19–21 (Теория игр на одну кучу)",
            notes="Внимательно разберём выигрышные стратегии 1-го и 2-го ходов.",
            materials=[
                {"title": "Презентация: Теория игр", "url": "#", "type": "theory", "pages": "PDF • 16 слайдов"}
            ]
        )
        l_wed_2 = Lesson(
            teacher_id=elena.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(wed.year, wed.month, wed.day, 16, 30, tzinfo=timezone.utc),
            duration=90,
            status="planned",
            subject="Математика",
            topic="Стереометрия: метод координат в пространстве",
            notes="Приготовить чертёжные принадлежности и транспортир.",
            materials=[
                {"title": "Координаты в пространстве: формулы", "url": "#", "type": "material", "pages": "PDF • 6 стр."}
            ]
        )

        # Thursday (day 3): 1 lesson (Rescheduled from another slot)
        thu = monday + timedelta(days=3)
        l_thu = Lesson(
            teacher_id=ivan.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(thu.year, thu.month, thu.day, 17, 0, tzinfo=timezone.utc),
            duration=60,
            status="planned",
            subject="Информатика",
            topic="Строковые алгоритмы: префикс-функция и поиск КМП",
            is_rescheduled=True,
            notes="Перенесено с субботы по согласованию.",
        )

        # Friday (day 4): 1 lesson (Cancelled)
        fri = monday + timedelta(days=4)
        l_fri = Lesson(
            teacher_id=elena.id,
            student_id=st_alice.student_id,
            lesson_date=datetime(fri.year, fri.month, fri.day, 14, 0, tzinfo=timezone.utc),
            duration=60,
            status="cancelled",
            subject="Математика",
            topic="Тригонометрические уравнения сложного вида",
            notes="Отменено: преподаватель на конференции.",
        )

        # Saturday & Sunday (days 5 & 6): Free days (weekend)

        hw_assign = Assignment(
            created_by_id=ivan.id,
            title="ДЗ: Поиск в глубину и компоненты связности",
            assignment_type="homework",
            deadline=datetime(wed.year, wed.month, wed.day, 20, 59, tzinfo=timezone.utc), # 23:59 MSK
            is_active=True,
        )
        db.session.add(hw_assign)
        db.session.commit()

        hw_sub = Submission(
            assignment_id=hw_assign.assignment_id,
            student_id=st_alice.student_id,
            status="IN_PROGRESS",
        )
        db.session.add(hw_sub)

        db.session.add_all([l_mon, l_tue, l_wed_1, l_wed_2, l_thu, l_fri])
        db.session.commit()
        print("✓ Test database seeded with rich multi-tutor schedule data.")


def run_visual_capture(baseline_only=False):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    ensure_rich_student_data()

    print(f"Starting server on port {PORT}...")
    env = os.environ.copy()
    env["DATABASE_URL"] = PG_URL
    env["BOOSTUDY_ALLOW_TEST_POSTGRES"] = "1"
    env["SECRET_KEY"] = "dev_test_secret_sprint2_5"
    log_file = "/tmp/acceptance_server_s25.log"
    server_process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import os
from app import create_app

app = create_app({{
    'TESTING': False,
    'SQLALCHEMY_DATABASE_URI': os.environ['DATABASE_URL'],
    'SECRET_KEY': os.environ['SECRET_KEY'],
    'WTF_CSRF_ENABLED': False
}})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port={PORT}, debug=False, use_reloader=False)
""",
        ],
        env=env,
        stdout=open(log_file, "w"),
        stderr=subprocess.STDOUT,
    )

    try:
        started = False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for i in range(40):
            time.sleep(0.5)
            try:
                resp = opener.open(f"http://127.0.0.1:{PORT}/login", timeout=2)
                if resp.status in (200, 302):
                    started = True
                    break
            except Exception as e:
                if i % 5 == 0:
                    print(f"Poll check {i}: {e}")

        if not started:
            server_process.terminate()
            log_content = ""
            if os.path.exists(log_file):
                with open(log_file) as f:
                    log_content = f.read()
            raise RuntimeError(f"Server failed to start on port {PORT}:\nLOG:\n{log_content}")

        print(f"✓ Test server is live on http://127.0.0.1:{PORT}!")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-proxy-server'])

            # Desktop 1920x1080 Context
            context_1080 = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context_1080.new_page()

            page.goto(f"http://127.0.0.1:{PORT}/login")
            page.fill('input[name="username"]', "alice_s25")
            page.fill('input[name="password"]', "pass123")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

            page.goto(f"http://127.0.0.1:{PORT}/schedule")
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            if baseline_only:
                shot_base = os.path.join(SCREENSHOT_DIR, "00_baseline_current_student_schedule.png")
                page.screenshot(path=shot_base, full_page=True)
                print(f"✓ Baseline screenshot saved: {shot_base}")
                browser.close()
                return

            # 1. Desktop: Day without lessons (Empty day, disabled «Банк задач · Скоро…»)
            page.click('#unified-tab-5, [data-day-index="5"]')
            time.sleep(0.8)
            shot_01 = os.path.join(SCREENSHOT_DIR, "01_desktop_empty_day.png")
            page.screenshot(path=shot_01)
            print(f"✓ Saved 01: {shot_01}")

            # 2. Desktop: 1 completed lesson with recommendation (Monday, day 0)
            page.click('#unified-tab-0, [data-day-index="0"]')
            time.sleep(0.8)
            shot_02 = os.path.join(SCREENSHOT_DIR, "02_desktop_completed_with_recommendation.png")
            page.screenshot(path=shot_02)
            print(f"✓ Saved 02: {shot_02}")

            # 3. Desktop: 1 upcoming lesson (Thursday, day 3)
            page.click('#unified-tab-3, [data-day-index="3"]')
            time.sleep(0.8)
            shot_03 = os.path.join(SCREENSHOT_DIR, "03_desktop_upcoming_single_lesson.png")
            page.screenshot(path=shot_03)
            print(f"✓ Saved 03: {shot_03}")

            # 4. Desktop: 2 lessons + homework (Wednesday, day 2)
            page.click('#unified-tab-2, [data-day-index="2"]')
            time.sleep(0.8)
            shot_04 = os.path.join(SCREENSHOT_DIR, "04_desktop_two_lessons_and_homework.png")
            page.screenshot(path=shot_04)
            print(f"✓ Saved 04: {shot_04}")

            # 7. Desktop control: Select Wednesday (non-today day) to verify "Сегодня" badge is ABSENT
            page.click('#unified-tab-2, [data-day-index="2"]')
            time.sleep(0.5)
            shot_07 = os.path.join(SCREENSHOT_DIR, "07_desktop_control_non_today_no_badge.png")
            page.screenshot(path=shot_07)
            print(f"✓ Saved 07: {shot_07}")

            # Mobile 390x844 Context (iPhone 14 style)
            context_mob = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            page_mob = context_mob.new_page()
            page_mob.goto(f"http://127.0.0.1:{PORT}/login")
            page_mob.fill('input[name="username"]', "alice_s25")
            page_mob.fill('input[name="password"]', "pass123")
            page_mob.click('button[type="submit"]')
            page_mob.wait_for_load_state("networkidle")
            page_mob.goto(f"http://127.0.0.1:{PORT}/schedule")
            page_mob.wait_for_load_state("networkidle")
            time.sleep(1)

            # 5. Mobile 390x844: 1 lesson (Thursday, day 3)
            page_mob.click('#unified-tab-3, [data-day-index="3"]')
            time.sleep(0.8)
            shot_05 = os.path.join(SCREENSHOT_DIR, "05_mobile_390_single_lesson.png")
            page_mob.screenshot(path=shot_05, full_page=True)
            print(f"✓ Saved 05: {shot_05}")

            # 6. Mobile 390x844: Empty day (Saturday, day 5)
            page_mob.click('#unified-tab-5, [data-day-index="5"]')
            time.sleep(0.8)
            shot_06 = os.path.join(SCREENSHOT_DIR, "06_mobile_390_empty_day.png")
            page_mob.screenshot(path=shot_06, full_page=True)
            print(f"✓ Saved 06: {shot_06}")

            browser.close()
            print("✓ All requested visual screenshots captured successfully!")

    finally:
        server_process.terminate()
        server_process.wait()
        print("✓ Server stopped.")


if __name__ == "__main__":
    is_base = "--baseline" in sys.argv
    run_visual_capture(baseline_only=is_base)
