from datetime import datetime, timedelta, timezone

from app.models import Assignment, AssignmentTask, Answer, Student, Submission, Tasks, db
from core.db_models import Lesson, LessonTask, LessonTaskAttempt, StudentTaskSeen

from .conftest import login_as


def _lesson_task(app, role_users, *, visible=False, answer_visible=False, status="pending"):
    with app.app_context():
        task = Tasks(
            task_number=9918,
            content_html="<p>Найдите результат по условию.</p>",
            answer="ANSWER-NEVER-SEND-9918",
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
            max_score=1,
        )
        lesson = Lesson(student_id=role_users["student_id"], topic="Visibility security test")
        db.session.add_all([task, lesson])
        db.session.flush()
        link = LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type="homework",
            status=status,
            is_visible_to_student=visible,
            is_answer_visible_to_student=answer_visible,
        )
        db.session.add(link)
        db.session.commit()
        return lesson.lesson_id, link.lesson_task_id, task.task_id


def test_hidden_lesson_task_is_not_listed_or_openable_and_creates_no_exposure(app, client, role_users):
    lesson_id, lesson_task_id, task_id = _lesson_task(app, role_users)
    login_as(client, role_users["student_user_id"], "student")

    listing = client.get("/submissions")
    assert listing.status_code == 200
    assert f"/lesson/{lesson_id}/classwork-tasks".encode() not in listing.data

    page = client.get(
        "/task-workspace/",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    api = client.get(
        "/task-workspace/api/context",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    assert page.status_code == 404
    assert api.status_code == 404

    with app.app_context():
        assert StudentTaskSeen.query.filter_by(
            student_id=role_users["student_id"], task_id=task_id,
        ).count() == 0
        assert LessonTaskAttempt.query.filter_by(lesson_task_id=lesson_task_id).count() == 0


def test_other_student_cannot_open_lesson_task(app, client, role_users):
    _, lesson_task_id, _ = _lesson_task(app, role_users)
    with app.app_context():
        from app.models import User

        other_user = User(
            username="v2_other_student",
            email="v2_other_student@example.test",
            role="student",
            is_active=True,
        )
        db.session.add(other_user)
        db.session.flush()
        other_student = Student(name="Other V2 student", user_id=other_user.id, is_active=True)
        db.session.add(other_student)
        db.session.commit()
        other_user_id = other_user.id

    login_as(client, other_user_id, "student")
    page = client.get(
        "/task-workspace/",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    api = client.get(
        "/task-workspace/api/context",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    assert page.status_code == 403
    assert api.status_code == 403


def test_visible_graded_lesson_task_respects_explicit_answer_visibility(app, client, role_users):
    _, lesson_task_id, _ = _lesson_task(
        app, role_users, visible=True, answer_visible=False, status="graded",
    )
    login_as(client, role_users["student_user_id"], "student")

    page = client.get(
        "/task-workspace/",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    api = client.get(
        "/task-workspace/api/context",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    assert page.status_code == 200
    assert b"ANSWER-NEVER-SEND-9918" not in page.data
    assert api.status_code == 200
    payload = api.get_json()["workspace"]
    assert payload["is_published"] is True
    assert payload["is_reviewed"] is True
    assert payload["can_see_solution"] is False
    assert payload["correct_answer"] == ""
    assert payload["solution_code"] == ""
    assert payload["task"]["answer"] == ""
    assert payload["task_meta"]["correct_answer"] == ""
    assert "ANSWER-NEVER-SEND-9918" not in str(payload)


def test_explicit_answer_visibility_allows_only_the_linked_student(app, client, role_users):
    _, lesson_task_id, _ = _lesson_task(
        app, role_users, visible=True, answer_visible=True, status="graded",
    )
    login_as(client, role_users["student_user_id"], "student")
    api = client.get(
        "/task-workspace/api/context",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    assert api.status_code == 200
    assert api.get_json()["workspace"]["can_see_solution"] is True
    assert api.get_json()["workspace"]["correct_answer"] == "ANSWER-NEVER-SEND-9918"
    page = client.get(
        "/task-workspace/",
        query_string={"context_type": "lesson_task", "context_id": lesson_task_id},
    )
    assert page.status_code == 200
    assert b"ANSWER-NEVER-SEND-9918" in page.data


def test_active_assignment_is_not_duplicated_by_its_hidden_lesson_task(app, client, role_users):
    with app.app_context():
        task = Tasks(
            task_number=9920,
            content_html="<p>One published assignment card.</p>",
            answer="42",
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
        )
        lesson = Lesson(student_id=role_users["student_id"], topic="Assignment deduplication")
        db.session.add_all([task, lesson])
        db.session.flush()
        assignment = Assignment(
            title="Published assignment for dedupe",
            assignment_type="homework",
            lesson_id=lesson.lesson_id,
            created_by_id=role_users["tutor_id"],
            is_active=True,
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=role_users["student_id"],
            status="ASSIGNED",
            max_score=1,
        )
        db.session.add_all([assignment_task, submission, LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type="homework",
            is_visible_to_student=False,
            is_answer_visible_to_student=False,
        )])
        independent_task = Tasks(
            task_number=9921,
            content_html="<p>Independent visible practice.</p>",
            answer="independent-answer",
        )
        independent_lesson = Lesson(
            student_id=role_users["student_id"], topic="Independent visible lesson task",
        )
        db.session.add_all([independent_task, independent_lesson])
        db.session.flush()
        db.session.add(LessonTask(
            lesson_id=independent_lesson.lesson_id,
            task_id=independent_task.task_id,
            assignment_type="homework",
            is_visible_to_student=True,
            is_answer_visible_to_student=False,
        ))
        StudentTaskSeen.query.filter_by(
            student_id=role_users["student_id"], task_id=task.task_id,
        ).delete(synchronize_session=False)
        db.session.commit()
        lesson_id = lesson.lesson_id
        independent_lesson_id = independent_lesson.lesson_id
        submission_id = submission.submission_id

    login_as(client, role_users["student_user_id"], "student")
    listing = client.get("/submissions")
    assert listing.status_code == 200
    assert f"/submissions/{submission_id}".encode() in listing.data
    assert f"/lesson/{lesson_id}/classwork-tasks".encode() not in listing.data
    assert f"/lesson/{independent_lesson_id}/classwork-tasks".encode() in listing.data


def test_assignment_workspace_honors_linked_lesson_answer_deny(app, client, role_users):
    with app.app_context():
        task = Tasks(
            task_number=9919,
            content_html="<p>Assignment solution gate.</p>",
            answer="ANSWER-ASSIGNMENT-NEVER-SEND",
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
            max_score=1,
        )
        lesson = Lesson(student_id=role_users["student_id"], topic="Assignment visibility test")
        db.session.add_all([task, lesson])
        db.session.flush()
        StudentTaskSeen.query.filter_by(
            student_id=role_users["student_id"], task_id=task.task_id,
        ).delete(synchronize_session=False)
        assignment = Assignment(
            title="Published lesson homework",
            assignment_type="homework",
            lesson_id=lesson.lesson_id,
            created_by_id=role_users["tutor_id"],
            is_active=True,
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=role_users["student_id"],
            status="GRADED",
            total_score=1,
            max_score=1,
        )
        db.session.add_all([assignment_task, submission])
        db.session.flush()
        db.session.add(Answer(
            submission_id=submission.submission_id,
            assignment_task_id=assignment_task.assignment_task_id,
            value="42",
            score=1,
            max_score=1,
            is_correct=True,
        ))
        link = LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type="homework",
            status="graded",
            is_visible_to_student=False,
            is_answer_visible_to_student=False,
        )
        db.session.add(link)
        db.session.commit()
        submission_id = submission.submission_id
        assignment_task_id = assignment_task.assignment_task_id

    login_as(client, role_users["student_user_id"], "student")
    response = client.get(
        "/task-workspace/api/context",
        query_string={
            "context_type": "submission_task",
            "context_id": submission_id,
            "assignment_task_id": assignment_task_id,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()["workspace"]
    assert payload["can_see_solution"] is False
    assert payload["correct_answer"] == ""
    assert payload["task"]["answer"] == ""
    assert "ANSWER-ASSIGNMENT-NEVER-SEND" not in str(payload)
