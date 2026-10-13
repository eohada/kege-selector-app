import pytest
from app.models import Course, TheoryGroup, TheoryBlock, User, Student, db
from app.theory.experience import build_experience
from tests.v2.conftest import login_as
from scripts.seed_comprehensive_python_theory import MODULES_DEF


def test_programming_course_theory_isolation(app, client):
    """Ensure course 'Программирование' contains only its 7 Python modules (30 topics)

    and does not leak exam tasks 1-27 or empty ghost groups.
    """
    with app.app_context():
        # 1. Setup Course 1 (ЕГЭ Информатика) with exam task
        c_ege = Course(title="ЕГЭ Информатика", slug="ege_informatics", is_active=True)
        db.session.add(c_ege)
        db.session.flush()

        g_ege = TheoryGroup(course_id=c_ege.id, name="Теория по заданиям ЕГЭ №1–27", position=1)
        db.session.add(g_ege)
        db.session.flush()

        b_ege = TheoryBlock(
            course_id=c_ege.id, group_id=g_ege.id, task_number=1,
            title="Задание №1. Графы и таблицы", content="<!--status:published-->Содержание задания 1",
            position=1,
        )
        db.session.add(b_ege)

        # 2. Setup Course 6 (Программирование)
        c_prog = Course(title="Программирование", slug="programming", is_active=True)
        db.session.add(c_prog)
        db.session.flush()

        # Add a ghost empty group to c_prog
        g_ghost = TheoryGroup(course_id=c_prog.id, name="Введение в программирование (пустая)", position=0)
        db.session.add(g_ghost)

        # Add the 7 programming modules
        prog_blocks = []
        for g_pos, m in enumerate(MODULES_DEF, start=1):
            g = TheoryGroup(course_id=c_prog.id, name=m["name"], position=g_pos)
            db.session.add(g)
            db.session.flush()
            for b_pos, (tn, info) in enumerate(sorted(m["topics"].items()), start=1):
                b = TheoryBlock(
                    course_id=c_prog.id, group_id=g.id, task_number=tn,
                    title=info["title"], content=f"<!--status:published-->{info['content'].strip()}",
                    position=b_pos,
                )
                db.session.add(b)
                prog_blocks.append(b)

        # 3. Setup Math course without theory
        c_math = Course(title="ЕГЭ Математика", slug="ege_math_profile", is_active=True)
        db.session.add(c_math)

        # Creator user
        user = User(username="creator_iso", role="creator")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()

        user_id = user.id
        prog_id = c_prog.id
        ege_id = c_ege.id
        math_id = c_math.id

    # Verify build_experience isolation
    with app.app_context():
        exp = build_experience(staff=True)
        prog_card = next(c for c in exp["courses"] if c["id"] == prog_id)
        ege_card = next(c for c in exp["courses"] if c["id"] == ege_id)
        math_card = next(c for c in exp["courses"] if c["id"] == math_id)

        # Programming card has exactly 30 topics and 7 groups (ghost group excluded!)
        assert prog_card["total"] == 30
        assert len(prog_card["groups"]) == 7
        assert all(g["name"] != "Введение в программирование (пустая)" for g in prog_card["groups"])
        assert all(101 <= t["task_number"] <= 130 for t in prog_card["topics"])  # strictly topics 101..130

        # EGE card has its exam block
        assert ege_card["total"] == 1

        # Math card has 0 topics
        assert math_card["total"] == 0

    # Test HTTP response for course page
    login_as(client, user_id=user_id, role="creator")
    resp = client.get(f"/theory/course/{prog_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Программирование: Основы и типы данных" in html
    assert "Задание №1. Графы и таблицы" not in html
    assert "Введение в программирование (пустая)" not in html


def test_programming_course_progression_and_final_test_locking(app, client):
    """Verify topic linear ordering, continue_topic calculation, study time,

    and final test locked state until all 30 topics are completed.
    """
    from app.models import StudentTheoryState

    with app.app_context():
        course = Course(title="Программирование", slug="prog_seq", is_active=True)
        db.session.add(course)
        db.session.flush()

        blocks = []
        for g_pos, m in enumerate(MODULES_DEF, start=1):
            g = TheoryGroup(course_id=course.id, name=m["name"], position=g_pos)
            db.session.add(g)
            db.session.flush()
            for b_pos, (tn, info) in enumerate(sorted(m["topics"].items()), start=1):
                b = TheoryBlock(
                    course_id=course.id, group_id=g.id, task_number=tn,
                    title=info["title"], content=f"<!--status:published-->{info['content'].strip()}",
                    read_minutes=20, position=b_pos,
                )
                db.session.add(b)
                blocks.append(b)

        u = User(username="student_seq", role="student")
        u.set_password("pass123")
        db.session.add(u)
        db.session.flush()

        student = Student(user_id=u.id, name="Тестовый Ученик", study_time_seconds=3600)
        db.session.add(student)
        db.session.flush()

        # Complete topics 101, 102, 103 (3 out of 30 = 10%)
        for tn in (101, 102, 103):
            db.session.add(StudentTheoryState(
                student_id=student.student_id, course_id=course.id,
                task_number=tn, is_read=True, reading_progress=100,
            ))
        db.session.commit()

        user_id = u.id
        course_id = course.id
        student_id = student.student_id

    # 1. Test build_experience logic
    with app.app_context():
        exp = build_experience(student_id=student_id)
        card = next(c for c in exp["courses"] if c["id"] == course_id)

        # Strictly ordered 101 to 130
        task_numbers = [t["task_number"] for t in card["topics"]]
        assert task_numbers == list(range(101, 131))

        # Progress stats
        assert card["completed"] == 3
        assert card["total"] == 30
        assert card["progress"] == 10

        # Study time: 3 topics * 20 min = 60 min = 1 h
        assert card["study_minutes"] == 60
        assert card["study_time_display"] == "1 ч"

        # Continue topic is 104, NOT 105
        assert card["continue_topic"]["task_number"] == 104
        assert card["continue_topic"]["locked"] is False

        # Topic 105 is sequence-locked waiting for 104
        topic_105 = next(t for t in card["topics"] if t["task_number"] == 105)
        assert topic_105["locked"] is True

        # Final test is locked (completed < 30)
        assert card["final_test_unlocked"] is False

    # 2. Test HTTP views as student
    login_as(client, user_id=user_id, role="student")

    # Course view shows course progress in hero continue card and sidebar milestone
    resp = client.get(f"/theory/course/{course_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Center continuation banner shows course progress (10% курса) instead of 0% темы
    assert "10% курса · 3 из 30 тем" in html
    assert "1 ч" in html  # dynamic study time displayed

    # Module 1 does NOT show stray final test button below its topics
    assert "tx-final-section" not in html

    # Sidebar contains final test milestone
    assert "Итоговый тест" in html

    # Visiting group=final_test shows locked card
    resp_final = client.get(f"/theory/course/{course_id}?group=final_test")
    assert resp_final.status_code == 200
    final_html = resp_final.get_data(as_text=True)
    assert "Итоговый тест пока закрыт" in final_html
    assert "Прогресс курса: 3 из 30 тем (10%)" in final_html
