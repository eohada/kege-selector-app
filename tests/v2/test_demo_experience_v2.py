import re
import pytest
from core.db_models import db, User, Student, Submission, Assignment, Tasks, UserAchievement
from app.models import CallRequest
from app.notifications.service import notify_user


def test_demo_entry_page(client):
    """Экран старта демоверсии возвращает форму первого знакомства с Бу."""
    res = client.get('/demo')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Глава 1' in html
    assert 'Знакомство' in html
    assert 'Привет! Я Бу' in html
    assert 'student_name' in html or 'student-name' in html


def test_demo_mutations_require_csrf_token(client, app):
    """Demo state-changing endpoints fail closed when CSRF is absent/invalid."""
    app.config['WTF_CSRF_ENABLED'] = True
    response = client.get('/demo')
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True)).group(1)
    payload = {'student_name': 'CSRF', 'goal': 'ege_90'}
    assert client.post('/demo/api/init', json=payload).status_code == 403
    assert client.post('/demo/api/init', json=payload, headers={'X-CSRFToken': 'invalid'}).status_code == 403
    assert client.post('/demo/api/init', json=payload, headers={'X-CSRFToken': token}).status_code == 200


def test_demo_mutations_fail_closed_before_initialization(client):
    """State-changing demo APIs cannot bootstrap or mutate a session implicitly."""
    assert client.post('/demo/api/state', json={'step_id': 'finale'}).status_code == 403
    assert client.post('/demo/api/event', json={'action_id': 'demo:finale:shown'}).status_code == 403
    assert client.post('/demo/api/verify-answer', json={'answer': '42'}).status_code == 403


def test_demo_session_initialization(client, app):
    """Инициализация демосессии создаёт изолированного ученика и demo assignment."""
    payload = {
        'student_name': 'Алиса',
        'exam': 'ege',
        'goal': 'ege',
    }
    res = client.post('/demo/api/init', json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    state = data['state']
    assert state['student_name'] == 'Алиса'
    assert state['chapter_id'] == 'chapter_1'
    assert state['step_id'] == 'welcome'
    assert state['submission_id'] is not None
    assert state['assignment_task_id'] is not None
    assert state['mistake_submission_id'] is not None
    assert state['mistake_assignment_task_id'] is not None
    assert state['theory_url'].startswith('/theory/topic/')
    assert state['program_url'].startswith('/student/')
    assert state['analytics_url'].startswith('/student/')
    sub_id = state['submission_id']

    with app.app_context():
        sub = Submission.query.get(sub_id)
        assert sub is not None
        assert sub.status == 'IN_PROGRESS'
        student = Student.query.get(sub.student_id)
        assert student is not None
        assert student.name == 'Алиса'
        user = User.query.get(student.user_id)
        assert user is not None
        assert user.is_demo_user is True

    theory_response = client.get(state['theory_url'])
    assert theory_response.status_code == 200
    theory_html = theory_response.get_data(as_text=True)
    assert 'Трассировка алгоритма: как читать программу по шагам' in theory_html
    assert 'algorithm-branch' in theory_html
    assert 'data-demo-target="theory-material"' in theory_html

    theory_block_id = int(state['theory_url'].split('/')[3].split('?')[0])
    checkpoint = client.post('/theory/api/checkpoint', json={
        'block_id': theory_block_id,
        'checkpoint_key': 'algorithm-branch',
        'answer': 'Прибавить 1',
    })
    assert checkpoint.status_code == 200
    assert checkpoint.get_json()['correct'] is True

    program_response = client.get(state['program_url'])
    assert program_response.status_code == 200
    assert 'data-demo-target="route-module"' in program_response.get_data(as_text=True)

    analytics_response = client.get(state['analytics_url'])
    assert analytics_response.status_code == 200
    assert 'data-demo-target="analytics-progress"' in analytics_response.get_data(as_text=True)


def test_demo_dashboard_handoff_is_persisted_with_initial_session_cookie(client):
    """Cinema → dashboard does not lose the first Chapter 2 scene on fast navigation."""
    response = client.post('/demo/api/init', json={
        'student_name': 'Саша',
        'exam': 'ege',
        'goal': 'ege',
        'start_at_dashboard': True,
    })
    assert response.status_code == 200
    assert response.get_json()['state']['chapter_id'] == 'chapter_2'
    assert response.get_json()['state']['step_id'] == 'chapter2_mission'

    persisted = client.get('/demo/api/state').get_json()['state']
    assert persisted['chapter_id'] == 'chapter_2'
    assert persisted['step_id'] == 'chapter2_mission'


def test_demo_repeated_semantic_action_is_safe_after_refresh(client):
    """A delayed duplicate action must never send a visitor back or show 409."""
    client.post('/demo/api/init', json={'student_name': 'Саша', 'start_at_dashboard': True})
    first = client.post('/demo/api/event', json={'action_id': 'demo:dashboard:program_explored'})
    assert first.status_code == 200
    second = client.post('/demo/api/event', json={'action_id': 'demo:dashboard:program_explored'})
    assert second.status_code == 200
    assert second.get_json()['idempotent'] is True
    assert second.get_json()['state']['step_id'] == 'chapter2_mission'


def test_demo_director_can_jump_to_a_cinematic_chapter_and_reset(client):
    """Режиссёрская панель меняет только изолированную демосессию."""
    init = client.post('/demo/api/init', json={'student_name': 'Режиссёр', 'start_at_dashboard': True})
    assert init.status_code == 200

    finale = client.post('/demo/api/director', json={'chapter': 'chapter_10'})
    assert finale.status_code == 200
    finale_data = finale.get_json()
    assert finale_data['success'] is True
    assert finale_data['url'] == '/workspace/profile'
    assert finale_data['state']['chapter_id'] == 'chapter_10'
    assert finale_data['state']['step_id'] == 'finale'
    assert 'trial_completed' in finale_data['state']['completed_actions']

    reset = client.post('/demo/api/director', json={'chapter': 'chapter_1'})
    assert reset.status_code == 200
    assert reset.get_json()['url'] == '/demo/'
    assert client.get('/demo/api/state').get_json()['state']['step_id'] == 'welcome'


def test_demo_director_exposes_every_chapter_from_one_isolated_session(client):
    """Presenter controls can rehearse every scene without replaying the path."""
    init = client.post('/demo/api/init', json={'student_name': 'Режиссёр', 'start_at_dashboard': True})
    assert init.status_code == 200
    expected = {
        'chapter_2': 'dashboard_intro', 'chapter_3': 'trial_intro',
        'chapter_4': 'library_intro', 'chapter_5': 'mistakes_intro',
        'chapter_6': 'route_intro', 'chapter_7': 'wins_intro', 'chapter_8': 'schedule_intro',
        'chapter_9': 'profile_intro', 'chapter_10': 'finale',
    }
    expected_destinations = {
        'chapter_2': '/dashboard', 'chapter_3': '/dashboard', 'chapter_4': '/theory/topic/',
        'chapter_5': '/submissions', 'chapter_6': '/student/', 'chapter_7': '/student/',
        'chapter_8': '/schedule', 'chapter_9': '/workspace/profile', 'chapter_10': '/workspace/profile',
    }
    revision = 0
    for chapter, step in expected.items():
        response = client.post('/demo/api/director', json={'chapter': chapter})
        assert response.status_code == 200
        state = response.get_json()['state']
        destination = response.get_json()['url']
        assert (state['chapter_id'], state['step_id']) == (chapter, step)
        assert expected_destinations[chapter] in destination
        assert state['director_revision'] > revision
        revision = state['director_revision']


def test_demo_intro_request_updates_the_same_lead_and_notifies_creator(client, app, monkeypatch):
    """The finale form has a consent gate and edits an existing demo lead."""
    client.post('/demo/api/init', json={'student_name': 'Марина', 'grade': '10', 'goal': 'ege_90'})
    payload = {
        'name': 'Марина', 'grade': '10', 'goal': 'ЕГЭ 90+', 'contact': '@marina',
        'slot': '2026-10-03T18:00', 'timezone': 'Europe/Moscow', 'consent': True,
    }

    missing_consent = client.post('/demo/api/request', json={**payload, 'consent': False})
    assert missing_consent.status_code == 400

    created = client.post('/demo/api/request', json=payload)
    assert created.status_code == 200
    created_data = created.get_json()
    assert created_data['success'] is True
    assert created_data['existing'] is False
    assert created_data['notified'] is False
    assert created_data['queued'] is True

    updated = client.post('/demo/api/request', json={**payload, 'slot': '2026-10-04T18:00'})
    assert updated.status_code == 200
    updated_data = updated.get_json()
    assert updated_data['existing'] is True
    assert updated_data['request_id'] == created_data['request_id']
    assert client.get('/demo/api/state').get_json()['state']['flags']['intro_request_sent'] is True

    with app.app_context():
        rows = CallRequest.query.filter_by(id=created_data['request_id']).all()
        assert len(rows) == 1
        assert '2026-10-04T18:00' in rows[0].message


def test_demo_intro_request_succeeds_when_telegram_queue_is_unavailable(client, app, monkeypatch):
    """A notification outage must not roll back an already persisted demo lead."""
    client.post('/demo/api/init', json={'student_name': 'Олег', 'grade': '9', 'goal': 'oge_5'})
    payload = {
        'name': 'Олег', 'grade': '9', 'goal': 'ОГЭ на 5', 'contact': 'oleg@example.com',
        'slot': '2026-10-03T18:00', 'timezone': 'Europe/Moscow', 'consent': True,
    }
    monkeypatch.setattr(
        'app.demo.routes.enqueue_direct_delivery',
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('telegram queue unavailable')),
    )

    response = client.post('/demo/api/request', json=payload)

    assert response.status_code == 200
    assert response.get_json()['success'] is True
    assert response.get_json()['queued'] is False
    with app.app_context():
        lead = CallRequest.query.filter_by(source='demo_intro', is_demo=True).order_by(CallRequest.id.desc()).first()
        assert lead is not None


def test_demo_scenario_v2_migrates_legacy_terminal_state(client):
    """An obsolete terminal state restarts at the current intake, never at victory."""
    client.post('/demo/api/init', json={'student_name': 'Саша'})
    with client.session_transaction() as session:
        state = session['demo_state']
        state.update({
            'version': 1,
            'chapter_id': 'chapter_3',
            'step_id': 'victory',
            'completed_actions': ['demo:trial:opened'],
        })
        session['demo_state'] = state

    response = client.get('/demo/api/state')
    state = response.get_json()['state']
    assert state['version'] == 5
    assert state['chapter_id'] == 'chapter_1'
    assert state['step_id'] == 'welcome'
    assert state['completed_actions'] == []


def test_demo_engine_events_and_idempotency(client, app):
    """События сценария сохраняются, а повторные действия не дублируются."""
    # 1. Init session
    res = client.post('/demo/api/init', json={'student_name': 'Тестер', 'exam': 'ege'})
    assert res.status_code == 200

    # 2. Follow an allowed sequence: enter the base, then start its mission.
    event_payload = {
        'action_id': 'transition_step',
        'chapter_id': 'chapter_2',
        'step_id': 'dashboard_intro',
        'payload': {},
    }
    res_ev = client.post('/demo/api/event', json=event_payload)
    assert res_ev.status_code == 200
    data = res_ev.get_json()
    assert data['success'] is True
    state = data['state']
    assert state['step_id'] == 'dashboard_intro'
    assert 'transition_step' in state['completed_actions']

    started = client.post('/demo/api/event', json={
        'action_id': 'demo:chapter2:started',
        'chapter_id': 'chapter_2',
        'step_id': 'dashboard_intro',
        'payload': {},
    })
    assert started.status_code == 200
    mission = client.post('/demo/api/event', json={
        'action_id': 'transition_step',
        'chapter_id': 'chapter_2',
        'step_id': 'chapter2_mission',
        'payload': {},
    })
    assert mission.status_code == 200
    state = mission.get_json()['state']
    assert state['step_id'] == 'chapter2_mission'
    count_actions = len(state['completed_actions'])

    # 3. Repeated action (idempotency check)
    res_ev_repeat = client.post('/demo/api/event', json=event_payload)
    assert res_ev_repeat.status_code == 409
    state_repeat = res_ev_repeat.get_json()['state']
    assert len(state_repeat['completed_actions']) == count_actions

    # 4. State query sync
    res_st = client.get('/demo/api/state')
    assert res_st.status_code == 200
    assert res_st.get_json()['state']['step_id'] == 'chapter2_mission'


def test_demo_dashboard_and_task_access(client, app):
    """Демо-пользователь имеет доступ к дашборду и странице задания с demo-target атрибутами."""
    res_init = client.post('/demo/api/init', json={'student_name': 'Борис'})
    sub_id = res_init.get_json()['state']['submission_id']

    # Дашборд ученика доступен без подписки
    res_dash = client.get('/dashboard')
    assert res_dash.status_code == 200
    dash_html = res_dash.get_data(as_text=True)
    assert 'data-demo-target="upcoming-lesson"' in dash_html
    assert 'data-demo-target="recent-assignments"' in dash_html
    assert 'data-demo-target="learning-program"' in dash_html
    assert 'data-demo-analytics-url=' in dash_html

    with app.app_context():
        student_id = Submission.query.get(sub_id).student_id
    res_analytics = client.get(f'/student/{student_id}/analytics')
    assert res_analytics.status_code == 200
    analytics_html = res_analytics.get_data(as_text=True)
    assert 'data-demo-target="analytics-progress"' in analytics_html
    assert 'Твои достижения' in analytics_html

    # Страница задания доступна (редирект в каноничный Workspace V2)
    res_sub = client.get(f'/submissions/{sub_id}', follow_redirects=True)
    assert res_sub.status_code == 200
    sub_html = res_sub.get_data(as_text=True)
    assert 'data-demo-target="task-card"' in sub_html
    assert 'data-demo-target="task-input"' in sub_html
    assert 'data-demo-target="task-submit"' in sub_html


def test_demo_programming_goal_persists_into_the_personal_route(client, app):
    """The fourth Chapter 1 goal changes the demo student's route context."""
    response = client.post('/demo/api/init', json={
        'student_name': 'Миша',
        'exam': 'ege',
        'goal': 'programming',
    })
    assert response.status_code == 200
    state = response.get_json()['state']
    assert state['goal'] == 'programming'

    from core.db_models import LearningTrajectory
    with app.app_context():
        submission = db.session.get(Submission, state['submission_id'])
        trajectory = LearningTrajectory.query.filter_by(student_id=submission.student_id).one()
        assert trajectory.learning_goal == 'Цель: научиться программировать · подготовка по информатике'


def test_regular_student_never_receives_experience_layer(client, app):
    """Companion assets are opt-in for the isolated demo identity only."""
    with app.app_context():
        user = User(
            username='ordinary_student',
            email='ordinary_student@example.test',
            role='student',
            is_active=True,
            is_demo_user=False,
        )
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.add(Student(name='Обычный ученик', user_id=user.id, is_active=True))
        db.session.commit()

    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = 'student'

    response = client.get('/dashboard')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="boo-companion-root"' not in html
    assert 'js/demo/boo_companion.js' not in html


def test_demo_task_verification_and_branching(client, app):
    """Проверка ответа задания Главы 3: реакция на ошибку и победный исход."""
    res_init = client.post('/demo/api/init', json={'student_name': 'Даниил'})
    sub_id = res_init.get_json()['state']['submission_id']

    # 1. Неправильный ответ
    res_wrong = client.post('/demo/api/verify-answer', json={
        'submission_id': sub_id,
        'answer': '999',
    })
    assert res_wrong.status_code == 200
    data_wrong = res_wrong.get_json()
    assert data_wrong['success'] is True
    assert data_wrong['is_correct'] is False
    assert 'hint' in data_wrong
    assert data_wrong['next_step'] == 'trial_retry'
    assert data_wrong['state']['step_id'] == 'trial_retry'
    assert data_wrong['state']['director_revision'] > 0

    # 2. Правильный ответ (5)
    res_correct = client.post('/demo/api/verify-answer', json={
        'submission_id': sub_id,
        'answer': '5',
    })
    assert res_correct.status_code == 200
    data_correct = res_correct.get_json()
    assert data_correct['success'] is True
    assert data_correct['is_correct'] is True
    assert data_correct['chapter_completed'] is True
    assert data_correct['next_step'] == 'victory'
    assert data_correct['achievement_unlocked'] is True

    # Проверка изменения статуса в БД
    with app.app_context():
        sub = Submission.query.get(sub_id)
        assert sub.status == 'GRADED'
        assert UserAchievement.query.filter_by(student_id=sub.student_id, achievement_key='first_step').count() == 1


def test_demo_mistake_retry_updates_the_real_submission(client, app):
    """Chapter 5 keeps the graded mistake and grades a separate editable retry."""
    init = client.post('/demo/api/init', json={'student_name': 'Ира'})
    retry_id = init.get_json()['state']['mistake_submission_id']
    assert retry_id is not None
    with client.session_transaction() as session:
        state = session['demo_state']
        state['chapter_id'] = 'chapter_5'
        state['step_id'] = 'mistakes_opened'
        session['demo_state'] = state

    response = client.post('/demo/api/verify-answer', json={'submission_id': retry_id, 'answer': '5'})
    assert response.status_code == 200
    result = response.get_json()
    assert result['is_correct'] is True
    assert result['next_step'] == 'mistakes_opened'
    assert result['chapter_id'] == 'chapter_5'

    with app.app_context():
        retry = db.session.get(Submission, retry_id)
        assert retry.status == 'GRADED'
        assert any(answer.is_correct for answer in retry.answers)


def test_demo_wrong_answer_stays_on_the_supported_retry_path(client):
    """Wrong answers lead to one hint and a retry, without skipping the route."""
    init = client.post('/demo/api/init', json={'student_name': 'Лена'})
    sub_id = init.get_json()['state']['submission_id']
    wrong = client.post('/demo/api/verify-answer', json={'submission_id': sub_id, 'answer': '21'})
    assert wrong.get_json()['state']['step_id'] == 'trial_retry'

    state = wrong.get_json()['state']
    assert state['chapter_id'] == 'chapter_3'
    assert state['step_id'] == 'trial_retry'
    assert state['flags']['trial_attempts'] == 1


def test_demo_security_and_isolation(client, app):
    """Демо-пользователю блокируется доступ к закрытым разделам и не отправляются внешние нотификации."""
    res_init = client.post('/demo/api/init', json={'student_name': 'Ольга'})
    with app.app_context():
        demo_user = User.query.filter_by(is_demo_user=True).order_by(User.id.desc()).first()
        demo_user_id = demo_user.id

    # 1. Попытка открыть административные или биллинговые разделы
    res_admin = client.get('/admin/tariffs')
    assert res_admin.status_code == 302
    assert 'demo_blocked=1' in res_admin.headers.get('Location', '')

    res_billing = client.get('/billing/plans')
    assert res_billing.status_code == 302
    assert 'demo_blocked=1' in res_billing.headers.get('Location', '')

    # 2. notify_user для демо-пользователя не создаёт внешних записей
    with app.app_context():
        notify_user(demo_user_id, kind='demo_test', title='Тестовое уведомление')
        # Уведомление не должно добавиться
        from app.models import UserNotification
        notif = UserNotification.query.filter_by(user_id=demo_user_id).first()
        assert notif is None


def test_demo_exit(client, app):
    """Выход из демо-режима очищает сессию и разлогинивает временного пользователя."""
    client.post('/demo/api/init', json={'student_name': 'Влад'})
    res_exit = client.post('/demo/api/exit')
    assert res_exit.status_code == 200
    assert res_exit.get_json()['success'] is True

    # Запрос к дашборду теперь требует логина
    res_dash = client.get('/dashboard')
    assert res_dash.status_code == 302
    assert '/login' in res_dash.headers.get('Location', '')


def test_demo_monotonic_step_ranking(client, app):
    """Шаги сценария не откатываются назад при запоздалых или устаревших событиях."""
    res_init = client.post('/demo/api/init', json={'student_name': 'Максим'})
    assert res_init.status_code == 200

    # Correctly persisted state remains authoritative after a stale request.
    with client.session_transaction() as session:
        state = session['demo_state']
        state['chapter_id'] = 'chapter_2'
        state['step_id'] = 'ready_for_trial'
        session['demo_state'] = state

    # Пытаемся отправить устаревший шаг welcome
    res_stale = client.post('/demo/api/event', json={
        'action_id': 'stale_click',
        'chapter_id': 'chapter_1',
        'step_id': 'welcome',
        'payload': {}
    })
    assert res_stale.status_code == 409
    state_stale = res_stale.get_json()['state']
    # Шаг должен остаться ready_for_trial, а не откатиться к welcome
    assert state_stale['step_id'] == 'ready_for_trial'
    assert state_stale['chapter_id'] == 'chapter_2'


def test_demo_rejects_forged_final_transition(client):
    """A browser cannot skip the whole story with a forged API request."""
    client.post('/demo/api/init', json={'student_name': 'Ника'})
    response = client.post('/demo/api/event', json={
        'action_id': 'transition_step',
        'chapter_id': 'chapter_8',
        'step_id': 'finale',
    })
    assert response.status_code == 409
    state = response.get_json()['state']
    assert state['chapter_id'] == 'chapter_1'
    assert state['step_id'] == 'welcome'


def test_demo_rejects_action_from_the_wrong_scene(client):
    """Semantic events are scoped to their scene, not trusted from the client."""
    client.post('/demo/api/init', json={'student_name': 'Лев'})
    response = client.post('/demo/api/event', json={
        'action_id': 'demo:library:material_opened',
        'chapter_id': 'chapter_1',
        'step_id': 'welcome',
    })
    assert response.status_code == 409
    assert response.get_json()['state']['step_id'] == 'welcome'


def test_demo_finale_reward_stays_inside_the_demo_session(client):
    """The narrative finale reward never touches the shared achievements system."""
    client.post('/demo/api/init', json={'student_name': 'Рома'})
    with client.session_transaction() as session:
        state = session['demo_state']
        state.update({'chapter_id': 'chapter_8', 'step_id': 'finale'})
        session['demo_state'] = state

    response = client.post('/demo/api/event', json={'action_id': 'demo:finale:shown'})
    assert response.status_code == 200
    assert response.get_json()['state']['flags']['cinema_reward'] == 'spark'


def test_demo_enriched_dataset_isolation(client, app):
    """Демо-пользователь получает реалистичный связный набор данных без пустых блоков."""
    from app.models import Lesson, GradebookEntry, StudentLearningPlanItem, StudentTaskStatistics
    from core.db_models import LearningTrajectory, TrajectoryModule

    res_init = client.post('/demo/api/init', json={'student_name': 'София'})
    assert res_init.status_code == 200
    sub_id = res_init.get_json()['state']['submission_id']

    with app.app_context():
        sub = db.session.get(Submission, sub_id)
        assert sub is not None
        student = db.session.get(Student, sub.student_id)
        assert student is not None

        # 1. Проверяем привязанного наставника
        assert student.mentor_id is not None

        # 2. Проверяем предстоящий урок
        upcoming = Lesson.query.filter_by(student_id=student.id, status='planned').first()
        assert upcoming is not None
        assert 'Анализ программ' in (upcoming.topic or '')

        # 3. Проверяем завершенные уроки (2 шт.)
        completed_lessons = Lesson.query.filter_by(student_id=student.id, status='completed').all()
        assert len(completed_lessons) >= 2

        # 4. Проверяем оцененную домашнюю работу с комментарием наставника
        graded_entry = GradebookEntry.query.filter_by(student_id=student.id).first()
        assert graded_entry is not None
        assert graded_entry.score == 10
        assert graded_entry.comment is not None

        # 5. Проверяем план обучения (3 темы)
        plan_items = StudentLearningPlanItem.query.filter_by(student_id=student.id).all()
        assert len(plan_items) >= 3

        # 6. Проверяем статистику решения задач
        stats = StudentTaskStatistics.query.filter_by(student_id=student.id).first()
        assert stats is not None
        assert stats.manual_correct > 0

        # 7. У демо есть настоящая персональная траектория с модулями,
        # а не только плоский список карточек на дашборде.
        trajectory = LearningTrajectory.query.filter_by(student_id=student.id).first()
        assert trajectory is not None
        assert trajectory.is_template is False
        assert TrajectoryModule.query.filter_by(course_id=trajectory.course_id).count() >= 3

        # 8. Для главы о работе над ошибками доступна отдельная оцененная работа
        # с неверной попыткой и человеческим комментарием наставника.
        review = Submission.query.join(Assignment).filter(
            Submission.student_id == student.id,
            Assignment.title == 'Разбор ошибки: след по алгоритму',
        ).first()
        assert review is not None
        assert review.status == 'GRADED'
        assert any(answer.is_correct is False and answer.teacher_comment for answer in review.answers)


def test_demo_dashboard_canonical_url_and_no_teacher_access(client, app):
    """url_for('main.dashboard') возвращает /dashboard, а ученик перенаправляется с /teacher/dashboard на /dashboard."""
    from flask import url_for

    with app.test_request_context():
        canonical_dashboard = url_for('main.dashboard')
        assert canonical_dashboard == '/dashboard'

    # Логиним демо-ученика
    res_init = client.post('/demo/api/init', json={'student_name': 'Артем'})
    assert res_init.status_code == 200
    assert res_init.get_json()['dashboard_url'] == '/dashboard'

    # При попытке перехода на /teacher/dashboard ученик мягко нормализуется на /dashboard
    res_teacher = client.get('/teacher/dashboard', follow_redirects=False)
    assert res_teacher.status_code == 302
    assert res_teacher.headers.get('Location').endswith('/dashboard')
