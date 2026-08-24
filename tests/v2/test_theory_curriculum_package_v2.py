import re

from app.theory.curriculum import load_curriculum, import_curriculum
from tests.v2.test_course_adaptive_program_v2 import login_as


def test_ege_curriculum_is_complete_and_detailed():
    package = load_curriculum()
    assert {group['key'] for group in package['groups']} == {'intro_programming', 'ege_tasks'}
    ege = next(group for group in package['groups'] if group['key'] == 'ege_tasks')
    intro = next(group for group in package['groups'] if group['key'] == 'intro_programming')
    assert {block['task_number'] for block in ege['blocks']} == set(range(1, 28))
    assert min(len(block['content']) for group in package['groups'] for block in group['blocks']) >= 1000
    assert all('[CHECKPOINT' in block['content'] for group in package['groups'] for block in group['blocks'])
    assert all('## Лаборатория темы' in block['content'] for block in ege['blocks'])
    assert all('key="lab-' in block['content'] for block in ege['blocks'])
    assert len({block['content'].split('## Лаборатория темы', 1)[1].split('**Действие ученика.**', 1)[0] for block in ege['blocks']}) == len(ege['blocks'])
    assert all(block['content'].count('[CHECKPOINT') >= 2 for block in intro['blocks'])
    assert all(len(block['content']) >= 3000 for block in intro['blocks'])
    assert all(block['content'].count('[INTERACTIVE') >= 3 for block in intro['blocks'])
    for block in intro['blocks']:
        starts = [match.start() for match in re.finditer(r'\[INTERACTIVE\s+', block['content'])]
        assert starts[-1] - starts[0] >= max(500, len(block['content']) // 4)
        assert max(starts) < block['content'].rfind('## Микро-проверки')
    assert all('## Лаборатория темы' not in block['content'] for block in intro['blocks'])
    assert all('## Прототипы ЕГЭ 2026' not in block['content'] for block in intro['blocks'])
    all_blocks = ege['blocks']
    interactive_types = {
        kind for block in all_blocks
        for kind in re.findall(r'\[INTERACTIVE\s+type="([^"]+)"', block['content'])
    }
    assert len(interactive_types) >= 20
    assert all(block['content'].count('[INTERACTIVE') >= 3 for block in all_blocks)
    for block in all_blocks:
        starts = [match.start() for match in re.finditer(r'\[INTERACTIVE\s+', block['content'])]
        assert len(starts) >= 3
        assert starts[-1] - starts[0] >= max(200, len(block['content']) // 5)
        keys = re.findall(r'\[INTERACTIVE\s+[^\]]*\bkey="([^"]+)"', block['content'])
        assert len(keys) == len(set(keys)), f"duplicate interactive keys in topic {block['task_number']}"
    assert all('## Прототипы ЕГЭ 2026' in block['content'] and '## Кодовый шаблон' in block['content'] for block in all_blocks)
    assert all('placeholder="Например: 101"' not in block['content'] for block in all_blocks)


def test_intro_code_practices_start_with_an_unsolved_program():
    """A green coding card must require a real edit before its first check."""
    intro = next(group for group in load_curriculum()['groups'] if group['key'] == 'intro_programming')
    markers = [
        marker
        for block in intro['blocks']
        for marker in re.findall(r'\[INTERACTIVE type="code"[^\]]+\]', block['content'])
    ]
    expected_starters = {
        'py101-code': 'print(7 + 4)',
        'py102-code': 'print(2 * 3 * 3)',
        'py104-code': 'print(1 + 2 + 3)',
        'py105-code': 'print(4 * 3)',
        "py106-code": "print(len('ЕГ'))",
        'py108-code': 'print(2 + 3 + 3)',
    }
    parsed = {
        attrs['key']: attrs
        for marker in markers
        for attrs in [dict(re.findall(r'(\w+)="([^"]*)"', marker))]
    }
    assert set(parsed) == set(expected_starters)
    assert {key: attrs['code'] for key, attrs in parsed.items()} == expected_starters
    assert all(attrs['code'] != f"print({attrs['expected']})" for attrs in parsed.values())


def test_curriculum_import_upserts_groups_and_blocks(app, role_users):
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup

    package = load_curriculum()
    with app.app_context():
        course = Course(title='ЕГЭ Информатика QA', slug='ege-informatics-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        result = import_curriculum(db, TheoryBlock, TheoryGroup, package, course.id, role_users['tutor_id'], publish=True)
        assert result['groups_created'] == 2
        assert result['blocks_created'] == 35
        assert TheoryBlock.query.filter_by(course_id=course.id).count() == 35
        assert TheoryBlock.query.filter_by(course_id=course.id, task_number=27).one().content.startswith('<!--status:published-->')
        second = import_curriculum(db, TheoryBlock, TheoryGroup, package, course.id, role_users['tutor_id'], publish=True)
        assert second['groups_created'] == 0
        assert second['blocks_created'] == 0
        assert second['blocks_updated'] == 35


def test_student_can_autocheck_and_leave_feedback_on_imported_topic(client, app, role_users):
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup, TheoryCheckpointAttempt, TheoryFeedback

    with app.app_context():
        course = Course(title='ЕГЭ Информатика API QA', slug='ege-informatics-api-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        import_curriculum(db, TheoryBlock, TheoryGroup, load_curriculum(), course.id, role_users['tutor_id'], publish=True)
        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=1).one()
        block_id = block.id
    login_as(client, role_users['student_user_id'], 'student')
    catalog = client.get(f'/theory?course_id={course.id}')
    assert catalog.status_code == 200
    assert 'ЕГЭ Информатика API QA' in catalog.get_data(as_text=True)
    article = client.get(f'/theory/topic/{block_id}?course_id={course.id}')
    assert article.status_code == 200
    article_html = article.get_data(as_text=True)
    assert 'Автопроверка внутри темы' in article_html
    assert 'Обратная связь' in article_html
    assert 'checkpoint-choice' in article_html
    assert 'theory-interactive' in article_html
    assert 'data-interactive-type="choice"' in article_html
    assert 'theory-section--goal' in article_html
    assert 'theory-section--method' in article_html
    assert 'theory-section--practice' in article_html
    assert 'data-retired-theory-handler' in article_html
    assert '\\n' not in article_html
    assert 'theory-spacer' not in article_html
    assert 'theory-smart-code' in article_html
    assert '##' not in article_html
    assert '<h2>' in article_html
    assert '<pre' in article_html
    assert '&lt;h2&gt;' not in article_html
    assert '&lt;section' not in article_html
    response = client.post('/theory/api/checkpoint', json={'block_id': block_id, 'checkpoint_key': 't1-1', 'answer': 'условие и ограничения'})
    assert response.status_code == 200
    assert response.get_json()['correct'] is True
    lab_response = client.post('/theory/api/checkpoint', json={'block_id': block_id, 'checkpoint_key': 'lab-1', 'answer': 'набор значений'})
    assert lab_response.status_code == 200
    assert lab_response.get_json()['correct'] is True
    feedback = client.post('/theory/api/feedback', json={'block_id': block_id, 'rating': 5, 'comment': 'Понятно'})
    assert feedback.status_code == 200
    with app.app_context():
        assert TheoryCheckpointAttempt.query.filter_by(block_id=block_id).count() == 2
        assert {attempt.checkpoint_key for attempt in TheoryCheckpointAttempt.query.filter_by(block_id=block_id).all()} == {'t1-1', 'lab-1'}
        assert TheoryFeedback.query.filter_by(task_number=1).one().comment == 'Понятно'


def test_all_interactive_formats_render_with_controls(app):
    """Every declared format must render a usable control and submit target."""
    from app.theory.routes import _render_theory_content_html, _parse_theory_interactives

    markers = [
        '[INTERACTIVE type="input" key="i-input" prompt="Введите" answer="42"]',
        '[INTERACTIVE type="choice" key="i-choice" prompt="Выберите" options="A|B" answer="A"]',
        '[INTERACTIVE type="order" key="i-order" prompt="Порядок" options="a|b" answer="a>b"]',
        '[INTERACTIVE type="table" key="i-table" prompt="Таблица" rows="2" answer="1|2"]',
        '[INTERACTIVE type="boolean" key="i-boolean" prompt="Да или нет" answer="true"]',
        '[INTERACTIVE type="code" key="i-code" prompt="Код" code="print(4)" expected="4" answer="pass"]',
        '[INTERACTIVE type="multi" key="i-multi" prompt="Несколько" options="A|B|C" answer="A|B"]',
        '[INTERACTIVE type="match" key="i-match" prompt="Пара" answer="A=B"]',
        '[INTERACTIVE type="classify" key="i-classify" prompt="Класс" options="A|B" answer="A"]',
        '[INTERACTIVE type="fill" key="i-fill" prompt="Пропуск" answer="range"]',
        '[INTERACTIVE type="slider" key="i-slider" prompt="Шкала" answer="50"]',
        '[INTERACTIVE type="hotspot" key="i-hotspot" prompt="Клетка" answer="5"]',
        '[INTERACTIVE type="sequence" key="i-sequence" prompt="Шаги" options="a|b" answer="a>b"]',
        '[INTERACTIVE type="trace" key="i-trace" prompt="Трассировка" rows="2" answer="1|2"]',
        '[INTERACTIVE type="regex" key="i-regex" prompt="Шаблон" answer="\\d+"]',
        '[INTERACTIVE type="binary" key="i-binary" prompt="Двоичный вид" answer="101"]',
        '[INTERACTIVE type="formula" key="i-formula" prompt="Формула" answer="a+b"]',
        '[INTERACTIVE type="predict" key="i-predict" prompt="Прогноз" answer="42"]',
        '[INTERACTIVE type="debug" key="i-debug" prompt="Отладка" code="print(4)" expected="4" answer="pass"]',
        '[INTERACTIVE type="explain" key="i-explain" prompt="Объяснение" answer="границы"]',
    ]
    with app.app_context():
        parsed = _parse_theory_interactives('\n'.join(markers))
        html = str(_render_theory_content_html('\n'.join(markers)))
    assert {item['type'] for item in parsed} == {
        'input', 'choice', 'order', 'table', 'boolean', 'code', 'multi', 'match',
        'classify', 'fill', 'slider', 'hotspot', 'sequence', 'trace', 'regex',
        'binary', 'formula', 'predict', 'debug', 'explain',
    }
    assert len(parsed) == 20
    assert html.count('data-action="interactive-submit"') == 20
    assert html.count('data-interactive-result') == 20
    assert 'data-match-left' in html and 'data-match-right' in html
    assert 'data-interactive-boolean' in html
    assert 'data-table-cell' in html
    assert 'data-interactive-code' in html
    assert 'data-order-value' in html
    assert 'data-interactive-option' in html
    assert 'data-expected' not in html
    assert 'data-interactive-slider' in html and 'data-slider-output' in html
    assert 'value="50" data-interactive-slider' not in html


def test_multi_interactive_accepts_same_choices_in_any_order(client, app, role_users):
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup

    with app.app_context():
        course = Course(title='ЕГЭ Информатика Multi QA', slug='ege-informatics-multi-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        import_curriculum(db, TheoryBlock, TheoryGroup, load_curriculum(), course.id, role_users['tutor_id'], publish=True)
        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=6).one()
        block_id = block.id
        marker = re.search(r'\[INTERACTIVE type="multi"[^\]]+\]', block.content)
        assert marker
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', marker.group(0)))
    login_as(client, role_users['student_user_id'], 'student')
    response = client.post('/theory/api/checkpoint', json={
        'block_id': block_id,
        'checkpoint_key': attrs['key'],
        'answer': '|'.join(reversed(attrs['answer'].split('|'))),
    })
    assert response.status_code == 200
    assert response.get_json()['correct'] is True


def test_interactive_choice_marker_is_accepted_by_checkpoint_api(client, app, role_users):
    """Interactive cards share the checkpoint endpoint without a legacy marker."""
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup

    with app.app_context():
        course = Course(title='ЕГЭ Информатика Interactive API QA', slug='ege-informatics-interactive-api-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        import_curriculum(db, TheoryBlock, TheoryGroup, load_curriculum(), course.id, role_users['tutor_id'], publish=True)
        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=1).one()
        marker = re.search(r'\[INTERACTIVE type="choice"[^\]]+\]', block.content)
        assert marker
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', marker.group(0)))
        block_id = block.id
    login_as(client, role_users['student_user_id'], 'student')
    response = client.post('/theory/api/checkpoint', json={
        'block_id': block_id,
        'checkpoint_key': attrs['key'],
        'answer': attrs['answer'],
    })
    assert response.status_code == 200
    assert response.get_json()['correct'] is True


def test_code_interactive_is_validated_by_server_without_expected_answer_leak(client, app, role_users):
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup
    from app.theory.routes import _render_theory_content_html

    with app.app_context():
        course = Course(title='ЕГЭ Информатика Code QA', slug='ege-informatics-code-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        import_curriculum(db, TheoryBlock, TheoryGroup, load_curriculum(), course.id, role_users['tutor_id'], publish=True)
        block = next(
            candidate for candidate in TheoryBlock.query.filter_by(course_id=course.id).all()
            if re.search(r'\[INTERACTIVE type="code"[^\]]+\]', candidate.content)
        )
        block_id = block.id
        marker = re.search(r'\[INTERACTIVE type="code"[^\]]+\]', block.content)
        assert marker
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', marker.group(0)))
        rendered = str(_render_theory_content_html(block.content))
        assert 'data-expected' not in rendered
    login_as(client, role_users['student_user_id'], 'student')
    correct = client.post('/theory/api/checkpoint', json={
        'block_id': block_id,
        'checkpoint_key': attrs['key'],
        'answer': attrs['expected'],
    })
    assert correct.status_code == 200
    assert correct.get_json()['correct'] is True
    wrong = client.post('/theory/api/checkpoint', json={
        'block_id': block_id,
        'checkpoint_key': attrs['key'],
        'answer': 'not-the-output',
    })
    assert wrong.status_code == 200
    assert wrong.get_json()['correct'] is False


def test_every_interactive_format_round_trips_through_checkpoint_api(client, app, role_users):
    """All twenty formats must be persistable, not merely present in rendered HTML."""
    from app import db
    from app.models import Course, TheoryBlock, TheoryGroup, TheoryCheckpointAttempt

    with app.app_context():
        course = Course(title='ЕГЭ Информатика Interactive API QA', slug='ege-informatics-interactive-api-qa', is_active=True)
        db.session.add(course)
        db.session.flush()
        import_curriculum(db, TheoryBlock, TheoryGroup, load_curriculum(), course.id, role_users['tutor_id'], publish=True)
        candidates = {}
        for block in TheoryBlock.query.filter_by(course_id=course.id).all():
            for marker in re.finditer(r'\[INTERACTIVE\s+([^\]]+)\]', block.content):
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', marker.group(0)))
                candidates.setdefault(attrs.get('type'), (block.id, attrs))
        assert set(candidates) == {
            'input', 'choice', 'order', 'table', 'boolean', 'code', 'multi', 'match',
            'classify', 'fill', 'slider', 'hotspot', 'sequence', 'trace', 'regex',
            'binary', 'formula', 'predict', 'debug', 'explain',
        }

    login_as(client, role_users['student_user_id'], 'student')
    for kind, (block_id, attrs) in candidates.items():
        answer = attrs.get('expected', attrs['answer']) if kind in {'code', 'debug'} else attrs['answer']
        response = client.post('/theory/api/checkpoint', json={
            'block_id': block_id,
            'checkpoint_key': attrs['key'],
            'answer': answer,
        })
        assert response.status_code == 200, (kind, response.get_data(as_text=True))
        assert response.get_json()['correct'] is True, kind

        wrong = client.post('/theory/api/checkpoint', json={
            'block_id': block_id,
            'checkpoint_key': attrs['key'],
            'answer': '__definitely_wrong__',
        })
        assert wrong.status_code == 200, (kind, wrong.get_data(as_text=True))
        assert wrong.get_json()['correct'] is False, kind

    with app.app_context():
        assert TheoryCheckpointAttempt.query.filter_by(student_id=role_users['student_id']).count() >= 20
