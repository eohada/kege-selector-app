import json
import pytest
from datetime import datetime, timezone

from app import db
from app.models import (
    User,
    Student,
    Lesson,
    LessonTask,
    Assignment,
    AssignmentTask,
    Submission,
    Answer,
    LessonParticipantBan,
    Tasks,
)
from core.db_models import utc_now
from app.task_workspace.service import (
    WorkspaceContext,
    save_workspace_code,
)
from app.lessons.lesson_socket import is_user_banned_from_lesson


def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def _seed_base_data(app):
    with app.app_context():
        teacher = User(username='test_wf_teacher', email='wf_teacher@test.local', role='tutor', is_active=True)
        student_user = User(username='test_wf_student', email='wf_student@test.local', role='student', is_active=True)
        db.session.add_all([teacher, student_user])
        db.session.flush()

        student = Student(user_id=student_user.id, name='Test Student', tutor_id=teacher.id)
        db.session.add(student)
        db.session.flush()

        lesson = Lesson(
            student_id=student.student_id,
            topic='Workflow Integration Test',
            status='in_progress',
            lesson_date=utc_now(),
        )
        db.session.add(lesson)
        db.session.flush()

        task = Tasks(
            task_number=27,
            content_html='<p>Sample test condition 12345</p>',
            answer='GOLDEN_ANSWER_42',
            starter_code='print("starter")',
            created_by_id=teacher.id,
            is_active=True,
        )
        db.session.add(task)
        db.session.flush()

        asgn = Assignment(
            title='Test Assignment 1',
            assignment_type='homework',
            created_by_id=teacher.id,
            lesson_id=lesson.lesson_id,
            deadline=utc_now(),
            is_active=True,
        )
        db.session.add(asgn)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=asgn.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=2,
        )
        db.session.add(at)
        db.session.flush()

        sub = Submission(
            assignment_id=asgn.assignment_id,
            student_id=student.student_id,
            status='SUBMITTED',
        )
        db.session.add(sub)
        db.session.flush()

        ans = Answer(
            submission_id=sub.submission_id,
            assignment_task_id=at.assignment_task_id,
            value='STUDENT_WRONG_ANSWER',
            student_code='x = 10\nprint(x)',
            is_correct=False,
            score=0,
            max_score=2,
            needs_revision=False,
        )
        db.session.add(ans)
        db.session.commit()

        return {
            'teacher_id': teacher.id,
            'student_user_id': student_user.id,
            'student_id': student.student_id,
            'lesson_id': lesson.lesson_id,
            'task_id': task.task_id,
            'assignment_id': asgn.assignment_id,
            'assignment_task_id': at.assignment_task_id,
            'submission_id': sub.submission_id,
            'answer_id': ans.answer_id,
        }


def test_kick_and_unban_gates(app):
    data = _seed_base_data(app)
    lesson_id = data['lesson_id']
    student_user_id = data['student_user_id']
    teacher_id = data['teacher_id']

    with app.app_context():
        # Initially not banned
        assert is_user_banned_from_lesson(lesson_id, student_user_id) is False

        # Ban the student
        ban = LessonParticipantBan(
            lesson_id=lesson_id,
            user_id=student_user_id,
            banned_by_user_id=teacher_id,
            is_active=True,
        )
        db.session.add(ban)
        db.session.commit()

        # Gate active
        assert is_user_banned_from_lesson(lesson_id, student_user_id) is True

        # Unban the student
        ban.is_active = False
        ban.unbanned_at = utc_now()
        db.session.commit()

        # Gate inactive
        assert is_user_banned_from_lesson(lesson_id, student_user_id) is False


def test_answer_revelation_security_gates(app):
    data = _seed_base_data(app)
    task_id = data['task_id']

    with app.app_context():
        task = Tasks.query.get(task_id)

        # 1. Student viewing wrong answer on unpublished submission
        # MUST NOT reveal golden answer or solution
        ctx_wrong = WorkspaceContext(
            context_type='submission_task',
            context_id=data['submission_id'],
            task_id=task.task_id,
            task=task,
            title='Task Title',
            subtitle='Subtitle',
            source_label='Homework',
            submission_id=data['submission_id'],
            assignment_task_id=data['assignment_task_id'],
            can_edit=True,
            can_review=False,
            is_task_correct=False,
            is_published=False,
            needs_revision=False,
            is_reviewed=True,
            correct_answer='GOLDEN_ANSWER_42',
            solution_code='GOLDEN_SOLUTION_BODY',
            solution_html='<p>GOLDEN_SOLUTION_HTML</p>',
        )
        payload_wrong = ctx_wrong.as_payload()
        assert payload_wrong['can_see_solution'] is False
        assert payload_wrong['correct_answer'] == ''
        assert payload_wrong['solution_html'] == ''
        assert payload_wrong['solution_code'] == ''
        assert 'GOLDEN_ANSWER_42' not in json.dumps(payload_wrong)
        assert 'GOLDEN_SOLUTION_BODY' not in json.dumps(payload_wrong)

        # 2. Student returned for revision - even if published, answers remain hidden
        ctx_revision = WorkspaceContext(
            context_type='submission_task',
            context_id=data['submission_id'],
            task_id=task.task_id,
            task=task,
            title='Task Title',
            subtitle='Subtitle',
            source_label='Homework',
            submission_id=data['submission_id'],
            assignment_task_id=data['assignment_task_id'],
            can_edit=True,
            can_review=False,
            is_task_correct=False,
            is_published=True,
            needs_revision=True,
            is_reviewed=True,
            correct_answer='GOLDEN_ANSWER_42',
            solution_code='GOLDEN_SOLUTION_BODY',
            solution_html='<p>GOLDEN_SOLUTION_HTML</p>',
        )
        payload_rev = ctx_revision.as_payload()
        assert payload_rev['can_see_solution'] is False
        assert payload_rev['correct_answer'] == ''
        assert 'GOLDEN_ANSWER_42' not in json.dumps(payload_rev)

        # 3. Student answered correctly - reveals single task solution
        ctx_correct = WorkspaceContext(
            context_type='submission_task',
            context_id=data['submission_id'],
            task_id=task.task_id,
            task=task,
            title='Task Title',
            subtitle='Subtitle',
            source_label='Homework',
            submission_id=data['submission_id'],
            assignment_task_id=data['assignment_task_id'],
            can_edit=False,
            can_review=False,
            is_task_correct=True,
            is_published=False,
            needs_revision=False,
            is_reviewed=True,
            correct_answer='GOLDEN_ANSWER_42',
            solution_code='GOLDEN_SOLUTION_BODY',
            solution_html='<p>GOLDEN_SOLUTION_HTML</p>',
        )
        payload_correct = ctx_correct.as_payload()
        assert payload_correct['can_see_solution'] is True
        assert payload_correct['correct_answer'] == 'GOLDEN_ANSWER_42'
        assert payload_correct['solution_code'] == 'GOLDEN_SOLUTION_BODY'

        # 4. Teacher reviewing - always sees answer and solution
        ctx_teacher = WorkspaceContext(
            context_type='submission_task',
            context_id=data['submission_id'],
            task_id=task.task_id,
            task=task,
            title='Task Title',
            subtitle='Subtitle',
            source_label='Homework',
            submission_id=data['submission_id'],
            assignment_task_id=data['assignment_task_id'],
            can_edit=True,
            can_review=True,
            is_task_correct=False,
            is_published=False,
            needs_revision=False,
            is_reviewed=False,
            correct_answer='GOLDEN_ANSWER_42',
            solution_code='GOLDEN_SOLUTION_BODY',
            solution_html='<p>GOLDEN_SOLUTION_HTML</p>',
        )
        payload_teacher = ctx_teacher.as_payload()
        assert payload_teacher['can_see_solution'] is True
        assert payload_teacher['correct_answer'] == 'GOLDEN_ANSWER_42'
        assert payload_teacher['solution_code'] == 'GOLDEN_SOLUTION_BODY'


def test_virtualfs_stale_write_protection(app):
    data = _seed_base_data(app)

    with app.app_context():
        task = Tasks.query.get(data['task_id'])
        ctx = WorkspaceContext(
            context_type='submission_task',
            context_id=data['submission_id'],
            task_id=task.task_id,
            task=task,
            title='Task Title',
            subtitle='Subtitle',
            source_label='Homework',
            submission_id=data['submission_id'],
            assignment_task_id=data['assignment_task_id'],
            can_edit=True,
            can_review=False,
        )

        # Save revision 1
        rev1 = save_workspace_code(
            ctx,
            code='v1_code',
            files={'main.py': 'v1_code', 'helper.py': 'def h(): pass'},
            open_tabs=['main.py', 'helper.py'],
            active_file='main.py',
            revision=1,
        )
        assert rev1 >= 2

        # Save with stale revision (revision 1 when current >= 2) must raise ValueError
        with pytest.raises(ValueError, match="Stale revision"):
            save_workspace_code(
                ctx,
                code='stale_code',
                files={'main.py': 'stale_code'},
                open_tabs=['main.py'],
                active_file='main.py',
                revision=1,
            )


def test_insert_into_lesson_endpoint(app, client):
    data = _seed_base_data(app)
    login_as(client, data['teacher_id'], 'tutor')

    insert_payload = {
        'source_assignment_id': data['assignment_id'],
        'source_submission_id': data['submission_id'],
        'source_assignment_task_id': data['assignment_task_id'],
        'task_id': data['task_id'],
        'assignment_type': 'classwork',
    }

    res = client.post(f"/lesson/{data['lesson_id']}/tasks/insert", json=insert_payload)
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data['success'] is True
    assert res_data['count'] == 1

    with app.app_context():
        # Verify new LessonTask was created with student's code from homework
        lt = LessonTask.query.filter_by(
            lesson_id=data['lesson_id'],
            task_id=data['task_id'],
            assignment_type='classwork',
        ).first()
        assert lt is not None
        assert lt.student_submission == 'x = 10\nprint(x)'

        # Verify provenance was saved in lesson.review_summaries
        lesson = Lesson.query.get(data['lesson_id'])
        prov = (lesson.review_summaries or {}).get('task_provenance', {}).get(str(lt.lesson_task_id))
        assert prov is not None
        assert prov['source_submission_id'] == data['submission_id']
        assert prov['origin'] == 'assignment_submission'

        # Verify original submission and answer in homework remain untouched
        orig_ans = Answer.query.get(data['answer_id'])
        assert orig_ans is not None
        assert orig_ans.student_code == 'x = 10\nprint(x)'
        assert orig_ans.value == 'STUDENT_WRONG_ANSWER'
