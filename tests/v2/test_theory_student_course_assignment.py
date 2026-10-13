import pytest
from app.models import User, Student, Course, TheoryGroup, TheoryBlock, StudentCourseEnrollment, db
from tests.v2.conftest import login_as


def test_theory_student_course_assignment_lifecycle(app, client):
    with app.app_context():
        # 1. Setup admin
        teacher = User.query.filter_by(username="theory_test_teacher_v2").first()
        if not teacher:
            teacher = User(username="theory_test_teacher_v2", role="admin")
            teacher.set_password("pass123")
            db.session.add(teacher)
            db.session.commit()

        # 2. Setup real student & test bot student
        real_user = User.query.filter_by(username="ivan_real_student").first()
        if not real_user:
            real_user = User(username="ivan_real_student", role="student")
            real_user.set_password("pass123")
            db.session.add(real_user)
            db.session.commit()

        real_student = Student.query.filter_by(user_id=real_user.id).first()
        if not real_student:
            real_student = Student(user_id=real_user.id, name="Иван Иванов")
            db.session.add(real_student)
            db.session.commit()

        bot_user = User.query.filter_by(username="qa_bot_student_999").first()
        if not bot_user:
            bot_user = User(username="qa_bot_student_999", role="student")
            bot_user.set_password("pass123")
            db.session.add(bot_user)
            db.session.commit()

        bot_student = Student.query.filter_by(user_id=bot_user.id).first()
        if not bot_student:
            bot_student = Student(user_id=bot_user.id, name="QA Bot Student")
            db.session.add(bot_student)
            db.session.commit()

        # 3. Setup Course & topic
        course = Course.query.filter_by(slug="assign-test-course").first()
        if not course:
            course = Course(title="Тест Назначения Курс", slug="assign-test-course", is_active=True)
            db.session.add(course)
            db.session.commit()

        group = TheoryGroup.query.filter_by(course_id=course.id, name="Модуль 1").first()
        if not group:
            group = TheoryGroup(course_id=course.id, name="Модуль 1", position=1)
            db.session.add(group)
            db.session.commit()

        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=501).first()
        if not block:
            block = TheoryBlock(
                course_id=course.id,
                group_id=group.id,
                task_number=501,
                title="Вводная тема",
                content="<!--status:published-->\n# Введение\nТекст",
                position=1,
            )
            db.session.add(block)
            db.session.commit()

        # Reset any preexisting enrollment for clean test
        StudentCourseEnrollment.query.filter_by(student_id=real_student.student_id, course_id=course.id).delete()
        db.session.commit()

        course_id = course.id
        block_id = block.id
        real_sid = real_student.student_id
        real_uid = real_user.id
        teacher_uid = teacher.id

    # 4. As Teacher: Search API
    login_as(client, user_id=teacher_uid, role="admin")
    res_search = client.get(f"/theory/api/manage/students/search?course_id={course_id}&q=Иван&hide_test=1")
    assert res_search.status_code == 200
    data_search = res_search.get_json()
    assert data_search["success"] is True
    assert any(s["student_id"] == real_sid for s in data_search["students"])
    # Verify bot is hidden with hide_test=1
    assert not any(s["username"] == "qa_bot_student_999" for s in data_search["students"])

    # 5. As Teacher: Set status to 'assigned' (not initialized)
    res_assign = client.post(
        "/theory/api/manage/student/course-status",
        json={"student_id": real_sid, "course_id": course_id, "status": "assigned"},
    )
    assert res_assign.status_code == 200
    assert res_assign.get_json()["status"] == "assigned"

    # Verify student is blocked from entering the uninitialized course
    login_as(client, user_id=real_uid, role="student")
    res_course = client.get(f"/theory/course/{course_id}")
    assert res_course.status_code == 302
    assert "/theory" in res_course.location

    # Verify student is blocked from viewing a block of uninitialized course
    res_block = client.get(f"/theory/topic/{block_id}")
    assert res_block.status_code == 302
    assert "/theory" in res_block.location

    # 6. As Teacher: Activate course
    login_as(client, user_id=teacher_uid, role="admin")
    res_active = client.post(
        "/theory/api/manage/student/course-status",
        json={"student_id": real_sid, "course_id": course_id, "status": "active"},
    )
    assert res_active.status_code == 200
    assert res_active.get_json()["status"] == "active"

    # Verify student can now access the course
    login_as(client, user_id=real_uid, role="student")
    res_course_active = client.get(f"/theory/course/{course_id}")
    assert res_course_active.status_code == 200

    # 7. As Teacher: Check Student Theory Profile API
    login_as(client, user_id=teacher_uid, role="admin")
    res_prof = client.get(f"/theory/api/manage/student/{real_sid}/theory-profile")
    assert res_prof.status_code == 200
    prof_data = res_prof.get_json()
    assert prof_data["success"] is True
    assert prof_data["student"]["student_id"] == real_sid
    assert any(c["course_id"] == course_id for c in prof_data["courses"])
    prof_c = next(c for c in prof_data["courses"] if c["course_id"] == course_id)
    assert prof_c["status"] == "active"
    assert prof_c["total_topics"] >= 1
    assert any(t["task_number"] == 501 for t in prof_c["topics"])

    # 8. As Teacher: Unassign course
    res_none = client.post(
        "/theory/api/manage/student/course-status",
        json={"student_id": real_sid, "course_id": course_id, "status": "none"},
    )
    assert res_none.status_code == 200
    assert res_none.get_json()["status"] == "none"

    # Clean up
    with app.app_context():
        StudentCourseEnrollment.query.filter_by(student_id=real_sid, course_id=course_id).delete()
        db.session.commit()
