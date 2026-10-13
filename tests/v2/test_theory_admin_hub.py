import pytest
import json
from app.models import User, Student, Course, TheoryGroup, TheoryBlock, StudentTheoryAccess, StudentCourseEnrollment, db
from tests.v2.conftest import login_as


def test_theory_admin_hub_and_management_api(app, client):
    with app.app_context():
        # 1. Setup admin/teacher user
        teacher = User.query.filter_by(username="theory_super_admin").first()
        if not teacher:
            teacher = User(username="theory_super_admin", role="admin")
            teacher.set_password("pass123")
            db.session.add(teacher)
            db.session.commit()

        # 2. Setup student user
        student_user = User.query.filter_by(username="theory_hub_student").first()
        if not student_user:
            student_user = User(username="theory_hub_student", role="student")
            student_user.set_password("pass123")
            db.session.add(student_user)
            db.session.commit()

        student = Student.query.filter_by(user_id=student_user.id).first()
        if not student:
            student = Student(user_id=student_user.id, name="Тестовый Ученик")
            db.session.add(student)
            db.session.commit()

        # 3. Setup Course
        course = Course.query.filter_by(slug="python-test-hub").first()
        if not course:
            course = Course(title="Python Тест Хаб", slug="python-test-hub", is_active=True)
            db.session.add(course)
            db.session.commit()

        # 4. Setup Group & Block
        group = TheoryGroup.query.filter_by(course_id=course.id, name="Тестовый модуль").first()
        if not group:
            group = TheoryGroup(course_id=course.id, name="Тестовый модуль", position=1)
            db.session.add(group)
            db.session.commit()

        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=999).first()
        if not block:
            block = TheoryBlock(
                course_id=course.id,
                group_id=group.id,
                task_number=999,
                title="Тестовая тема",
                content="<!--status:published-->\n# Привет\nКонтент статьи",
                read_minutes=10,
                position=1,
            )
            db.session.add(block)
            db.session.commit()

        teacher_id = teacher.id
        student_id = student.student_id
        student_user_id = student_user.id
        course_id = course.id
        group_id = group.id
        block_id = block.id

    # Log in as teacher
    login_as(client, user_id=teacher_id, role="admin")

    # A. Check GET /theory/manage renders the V2 Control Center
    resp = client.get(f"/theory/manage?course_id={course_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Пульт управления теорией" in html
    assert "Курсы и модули" in html
    assert "Материалы и статьи" in html
    assert "Ученики и доступы" in html
    assert "Прогресс и отзывы" in html
    assert "Итоговые тесты" in html

    # B. API: GET /theory/api/manage/block/<id>
    resp_block = client.get(f"/theory/api/manage/block/{block_id}")
    assert resp_block.status_code == 200
    b_data = resp_block.get_json()
    assert b_data["success"] is True
    assert b_data["block"]["title"] == "Тестовая тема"
    assert b_data["block"]["status"] == "published"
    assert "<!--status:" not in b_data["block"]["content"]

    # C. API: POST /theory/api/manage/block/toggle-status
    resp_toggle = client.post(
        "/theory/api/manage/block/toggle-status",
        data=json.dumps({"id": block_id, "status": "draft"}),
        content_type="application/json"
    )
    assert resp_toggle.status_code == 200
    assert resp_toggle.get_json()["status"] == "draft"

    with app.app_context():
        updated_b = TheoryBlock.query.get(block_id)
        assert updated_b.content.startswith("<!--status:draft-->")

    # D. API: POST /theory/api/manage/block/save
    resp_save_b = client.post(
        "/theory/api/manage/block/save",
        data=json.dumps({
            "id": block_id,
            "course_id": course_id,
            "group_id": group_id,
            "task_number": 999,
            "title": "Обновленная тема",
            "description": "Новое описание",
            "read_minutes": 12,
            "status": "published",
            "content": "# Новый контент"
        }),
        content_type="application/json"
    )
    assert resp_save_b.status_code == 200
    assert resp_save_b.get_json()["success"] is True

    # E. API: Student course enrollment toggle
    resp_enroll = client.post(
        "/theory/api/manage/student/enroll-toggle",
        data=json.dumps({"student_id": student_id, "course_id": course_id, "is_active": True}),
        content_type="application/json"
    )
    assert resp_enroll.status_code == 200
    assert resp_enroll.get_json()["is_active"] is True

    # F. API: Student topic access toggle
    resp_acc = client.post(
        "/theory/api/manage/student/access-toggle",
        data=json.dumps({"student_id": student_id, "course_id": course_id, "task_number": 999, "can_view": False}),
        content_type="application/json"
    )
    assert resp_acc.status_code == 200
    assert resp_acc.get_json()["can_view"] is False

    with app.app_context():
        acc = StudentTheoryAccess.query.filter_by(student_id=student_id, course_id=course_id, task_number=999).first()
        assert acc is not None and acc.can_view is False

    # G. API: Student batch access
    resp_batch = client.post(
        "/theory/api/manage/student/access-batch",
        data=json.dumps({"student_id": student_id, "course_id": course_id, "action": "unlock_all"}),
        content_type="application/json"
    )
    assert resp_batch.status_code == 200
    assert resp_batch.get_json()["action"] == "unlock_all"

    with app.app_context():
        acc = StudentTheoryAccess.query.filter_by(student_id=student_id, course_id=course_id, task_number=999).first()
        assert acc.can_view is True

    # H. API: Bookmark toggle for student
    login_as(client, user_id=student_user_id, role="student")
    resp_bm = client.post(
        "/theory/api/bookmark",
        data=json.dumps({"block_id": block_id, "task_number": 999, "course_id": course_id}),
        content_type="application/json"
    )
    assert resp_bm.status_code == 200
    assert resp_bm.get_json()["success"] is True
    assert resp_bm.get_json()["bookmarked"] is True

    # I. Routing tests: Staff visits /theory -> redirect to /theory/manage
    login_as(client, user_id=teacher_id, role="admin")
    resp_redirect = client.get("/theory", follow_redirects=False)
    assert resp_redirect.status_code == 302
    assert "/theory/manage" in resp_redirect.headers["Location"]

    # Legacy access routes also redirect to V2 hub students tab
    resp_legacy_access = client.get(f"/theory/manage/access?course_id={course_id}", follow_redirects=False)
    assert resp_legacy_access.status_code == 302
    assert "/theory/manage?tab=students" in resp_legacy_access.headers["Location"]

    resp_legacy_student = client.get(f"/theory/manage/access/{student_id}?course_id={course_id}", follow_redirects=False)
    assert resp_legacy_student.status_code == 302
    assert "/theory/manage?tab=students" in resp_legacy_student.headers["Location"]

    # J. Staff visits /theory?view=student -> 200 with switch banner to control center
    resp_view_student = client.get("/theory?view=student")
    assert resp_view_student.status_code == 200
    assert "Пульт управления теорией" in resp_view_student.get_data(as_text=True)

    # K. Check student theory profile API returns serialized final_test_attempts
    with app.app_context():
        from app.models import TheoryFinalTestAttempt
        attempt = TheoryFinalTestAttempt(
            user_id=student_user_id,
            student_id=student_id,
            course_id=course_id,
            attempt_number=1,
            score=19,
            total=20,
            passed=True,
            task_ids=['p1'],
            answers={'p1': 'A'},
            details=[{'task_id': 'p1', 'correct': True, 'title': 'Задача 1', 'user_answer_text': 'A', 'correct_answer_text': 'A'}],
            block_scores={'1': {'correct': 5, 'total': 5}},
        )
        db.session.add(attempt)
        db.session.commit()

    resp_prof = client.get(f"/theory/api/manage/student/{student_id}/theory-profile")
    assert resp_prof.status_code == 200
    prof_data = resp_prof.get_json()
    assert prof_data["success"] is True
    target_c = next((c for c in prof_data["courses"] if c["course_id"] == course_id), None)
    assert target_c is not None
    assert len(target_c["final_test_attempts"]) == 1
    assert target_c["final_test_attempts"][0]["score"] == 19
    assert target_c["final_test_attempts"][0]["passed"] is True
    assert target_c["final_test_attempts"][0]["details"][0]["task_id"] == "p1"

    # K. Student visits /theory -> 200 directly
    login_as(client, user_id=student_user_id, role="student")
    resp_stud = client.get("/theory", follow_redirects=False)
    assert resp_stud.status_code == 200
