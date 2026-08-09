from datetime import datetime, timezone

from tests.v2.conftest import login_as


def _theory_fixture(app, role_users):
    from app import db
    from app.models import Course, Lesson, TheoryBlock, TheoryGroup

    with app.app_context():
        course = Course(title='Тестовый курс теории', slug='theory-learning-v2', is_active=True)
        db.session.add(course)
        db.session.flush()
        group = TheoryGroup(course_id=course.id, name='Логика', position=1)
        db.session.add(group)
        db.session.flush()
        first = TheoryBlock(
            course_id=course.id,
            group_id=group.id,
            task_number=1,
            position=1,
            title='Таблицы истинности',
            content=(
                '<!--status:published-->\n'
                'Разберите условие и выберите ответ.\n'
                '[CHECKPOINT key="logic-1" question="Что верно?" '
                'options="A|B|C" answer="B" explanation="B — верный вариант."]'
            ),
        )
        second = TheoryBlock(
            course_id=course.id,
            group_id=group.id,
            task_number=2,
            position=2,
            title='Повторение логики',
            content='<!--status:published-->\nВторой материал.',
        )
        lesson = Lesson(
            student_id=role_users['student_id'],
            exam_course_id=course.id,
            lesson_date=datetime.now(timezone.utc),
            topic='Теория в Studio',
        )
        db.session.add_all([first, second, lesson])
        db.session.commit()
        return {
            'course_id': course.id,
            'first_id': first.id,
            'second_id': second.id,
            'lesson_id': lesson.lesson_id,
        }


def test_student_theory_learning_cycle(app, client, role_users):
    from app import db
    from app.models import StudentTheoryNote, StudentTheoryState, TheoryCheckpointAttempt, TheoryStudyAssignment

    fixture = _theory_fixture(app, role_users)
    with app.app_context():
        db.session.add(TheoryStudyAssignment(
            student_id=role_users['student_id'],
            block_id=fixture['first_id'],
            assigned_by_user_id=role_users['tutor_id'],
            message='Повтори перед уроком.',
        ))
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    article = client.get(f"/theory/topic/{fixture['first_id']}?course_id={fixture['course_id']}")
    assert article.status_code == 200
    assert 'Что верно?' in article.get_data(as_text=True)
    assert 'data-last-position="0"' in article.get_data(as_text=True)

    assert client.post('/theory/api/progress', json={
        'block_id': fixture['first_id'], 'progress': 37, 'position': 420,
    }).get_json() == {'success': True, 'progress': 37}
    assert client.post('/theory/api/note', json={
        'block_id': fixture['first_id'], 'content': 'Проверить таблицу истинности.',
    }).get_json()['saved'] is True
    assert client.post('/theory/api/bookmark', json={
        'block_id': fixture['first_id'], 'value': True,
    }).get_json()['bookmarked'] is True

    wrong = client.post('/theory/api/checkpoint', json={
        'block_id': fixture['first_id'], 'checkpoint_key': 'logic-1', 'answer': 'A',
    })
    assert wrong.status_code == 200
    assert wrong.get_json()['correct'] is False
    correct = client.post('/theory/api/checkpoint', json={
        'block_id': fixture['first_id'], 'checkpoint_key': 'logic-1', 'answer': 'B',
    })
    assert correct.status_code == 200
    assert correct.get_json()['correct'] is True
    assert correct.get_json()['attempts'] == 2

    completed = client.post('/theory/api/read', json={'block_id': fixture['first_id']})
    assert completed.status_code == 200
    with app.app_context():
        state = StudentTheoryState.query.filter_by(
            student_id=role_users['student_id'], course_id=fixture['course_id'], task_number=1
        ).one()
        assert state.is_read is True
        assert state.reading_progress == 100
        assert state.last_position == 420
        assert StudentTheoryNote.query.filter_by(student_id=role_users['student_id'], block_id=fixture['first_id']).one().content
        attempt = TheoryCheckpointAttempt.query.filter_by(student_id=role_users['student_id'], block_id=fixture['first_id']).one()
        assert attempt.is_correct is True and attempt.attempts_count == 2
        assert TheoryStudyAssignment.query.filter_by(student_id=role_users['student_id'], block_id=fixture['first_id']).one().status == 'completed'


def test_tutor_can_assign_theory_to_scoped_student(app, client, role_users):
    from app import db
    from app.models import TheoryStudyAssignment

    fixture = _theory_fixture(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(
        f"/theory/manage?course_id={fixture['course_id']}",
        data={
            'action': 'assign_material',
            'block_id': fixture['first_id'],
            'student_id': role_users['student_id'],
            'assignment_message': 'Повтори перед уроком.',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        assignment = TheoryStudyAssignment.query.filter_by(
            student_id=role_users['student_id'], block_id=fixture['first_id']
        ).one()
        assert assignment.status == 'assigned'
        assert assignment.message == 'Повтори перед уроком.'


def test_lesson_studio_uses_canonical_theory_and_validates_selected_block(app, client, role_users):
    fixture = _theory_fixture(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')

    room = client.get(f"/lesson/{fixture['lesson_id']}/room")
    assert room.status_code == 200
    html = room.get_data(as_text=True)
    assert 'data-view="theory"' in html
    assert f'/theory/topic/{fixture["first_id"]}?course_id={fixture["course_id"]}' in html
    assert '/sandbox/lesson_room/' not in html

    saved = client.post(
        f"/lesson/{fixture['lesson_id']}/studio/state",
        json={
            'active_pane': 'theory',
            'active_theory_block_id': fixture['first_id'],
            'follow_student': True,
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()['state']['active_theory_block_id'] == fixture['first_id']

    invalid = client.post(
        f"/lesson/{fixture['lesson_id']}/studio/state",
        json={'active_theory_block_id': fixture['second_id'] + 9999},
    )
    assert invalid.status_code == 400
