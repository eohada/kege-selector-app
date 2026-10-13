import pytest
from app.models import User, Student, Course, TheoryGroup, TheoryBlock, StudentTheoryState, db
from tests.v2.conftest import login_as


def test_bank_preview_and_final_test_lifecycle(app, client):
    with app.app_context():
        user = User(username="student_bank_v2", role="student")
        user.set_password("pass123")
        db.session.add(user)
        db.session.commit()

        student = Student(user_id=user.id, name="Test Student")
        db.session.add(student)
        db.session.commit()

        course = Course(title="Python Course", slug="python-course")
        db.session.add(course)
        db.session.commit()

        group = TheoryGroup(name="Программирование на Python", course_id=course.id)
        db.session.add(group)
        db.session.commit()

        block = TheoryBlock(group_id=group.id, course_id=course.id, title="Основы", task_number=1, content="<p>Текст</p>")
        db.session.add(block)
        db.session.commit()

        # Mark block as completed
        state = StudentTheoryState(student_id=student.student_id, course_id=course.id, task_number=1, is_read=True, reading_progress=100)
        db.session.add(state)
        db.session.commit()

        user_id = user.id
        course_id = course.id

    login_as(client, user_id=user_id, role="student")

    # 1. Preview route works and renders 200 tasks across 4 blocks
    preview_resp = client.get(f"/theory/bank-preview?course_id={course_id}")
    assert preview_resp.status_code == 200
    html_text = preview_resp.get_data(as_text=True)
    assert "банк заданий по программированию" in html_text.lower()
    assert "B1-01" in html_text
    assert "B2-01" in html_text
    assert "B3-01" in html_text
    assert "B4-01" in html_text

    # 2. Final test variant generation returns 20 tasks in strict block order
    gen_resp = client.get(f"/api/python-programming/final-test?course_id={course_id}&seed=123")
    assert gen_resp.status_code == 200
    gen_data = gen_resp.get_json()
    assert gen_data["success"] is True
    assert len(gen_data["tasks"]) == 20
    # Tasks 1..5: Block 1
    assert [t["block"] for t in gen_data["tasks"][:5]] == [1, 1, 1, 1, 1]
    # Tasks 6..10: Block 2
    assert [t["block"] for t in gen_data["tasks"][5:10]] == [2, 2, 2, 2, 2]
    # Tasks 11..15: Block 3
    assert [t["block"] for t in gen_data["tasks"][10:15]] == [3, 3, 3, 3, 3]
    # Tasks 16..20: Block 4
    assert [t["block"] for t in gen_data["tasks"][15:20]] == [4, 4, 4, 4, 4]

    # Verify task fields passed to client
    first_task = gen_data["tasks"][0]
    assert "type" in first_task
    assert "block" in first_task
    assert "content_html" in first_task

    # 3. Test grading endpoint: 18 correct answers out of 20 = 90% -> passed = True
    answers = {}
    for i, t in enumerate(gen_data["tasks"]):
        if i < 18:
            answers[t["id"]] = t["answer"]
        else:
            answers[t["id"]] = "WRONG_ANSWER"

    grade_resp = client.post(
        "/api/python-programming/final-test/grade",
        json={"course_id": course_id, "answers": answers},
    )
    assert grade_resp.status_code == 200
    grade_data = grade_resp.get_json()
    assert grade_data["success"] is True
    assert grade_data["correct"] == 18
    assert grade_data["threshold"] == 18
    assert grade_data["threshold_percent"] == 90
    assert grade_data["passed"] is True
    assert grade_data["new_achievement"] is not None
    assert grade_data["new_achievement"]["key"] == "secret_python_master"
    assert grade_data["new_achievement"]["is_secret"] is True
    assert grade_data["new_achievement"]["xp_reward"] == 50

    # 4. 17 correct answers = 85% -> passed = False (< 90%)
    with client.session_transaction() as sess:
        sess[f"python_final_test_{course_id}"] = {
            "task_ids": [t["id"] for t in gen_data["tasks"]],
            "attempted": True,
            "passed": False,
            "score": 0,
        }

    answers_17 = {}
    for i, t in enumerate(gen_data["tasks"]):
        if i < 17:
            answers_17[t["id"]] = t["answer"]
        else:
            answers_17[t["id"]] = "WRONG_ANSWER"

    grade_resp_17 = client.post(
        "/api/python-programming/final-test/grade",
        json={"course_id": course_id, "answers": answers_17},
    )
    assert grade_resp_17.status_code == 200
    grade_data_17 = grade_resp_17.get_json()
    assert grade_data_17["correct"] == 17
    assert grade_data_17["threshold"] == 18
    assert grade_data_17["passed"] is False
    assert grade_data_17.get("new_achievement") is None
