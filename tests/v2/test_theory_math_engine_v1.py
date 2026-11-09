from app.theory.math_rendering import prepare_theory_source
from app.theory.math_validation import validate_math_answer
from app.theory.routes import _parse_theory_checkpoints, _parse_theory_interactives, _render_theory_content_html
from app.theory.visualizations import render_function_plot, render_geometry
from app.theory.math_curriculum import (
    ValidationReport,
    _validate_latex,
    import_drafts,
    publish_selected,
    validate_math_package,
)
from bs4 import BeautifulSoup


def test_math_source_survives_sanitization_and_legacy_markdown_pipeline():
    content = r"""Короткая формула $\frac{1}{2}$ и длинная:

$$\begin{cases}x^2-1=0\\x>0\end{cases}$$

Скобки: \(\sqrt[3]{8}=2\), а отдельная система: \[\begin{aligned}a&=b\\c&=d\end{aligned}\].

| Выражение | Значение |
|---|---:|
| $x^2$ | $4$ |
"""
    rendered = str(_render_theory_content_html(content))
    assert rendered.count('class="theory-math-source"') == 6
    assert r"\frac{1}{2}" in rendered
    assert r"\begin{cases}" in rendered
    assert r"\sqrt[3]{8}" in rendered
    assert '<table' in rendered
    soup = BeautifulSoup(rendered, 'html.parser')
    assert soup.find('table').find_parent('div', class_='theory-table-scroll')


def test_image_captions_render_semantically_without_technical_prefix():
    content = r'''![Схема](/static/scheme.svg)

Подпись: на схеме отмечены точки $A$ и $B$.

    ![График](/static/graph.svg)

*График функции $y=x^2$ на промежутке от $-2$ до $2$.*

    ![Фото](/static/photo.svg)

Обычное пояснение после изображения остаётся обычным абзацем.'''
    rendered = str(_render_theory_content_html(content))
    soup = BeautifulSoup(rendered, 'html.parser')
    figures = soup.select('figure.theory-figure')
    assert len(figures) == 3
    captions = [figure.find('figcaption') for figure in figures]
    assert captions[0] is not None and 'на схеме отмечены точки' in captions[0].get_text(' ', strip=True)
    assert 'Подпись:' not in captions[0].get_text(' ', strip=True)
    assert captions[0].select_one('.theory-math-source')
    assert captions[1] is not None and 'График функции' in captions[1].get_text(' ', strip=True)
    assert captions[2] is None
    assert 'Обычное пояснение после изображения' in soup.get_text(' ', strip=True)


def test_inline_image_caption_in_the_same_markdown_paragraph():
    rendered = str(_render_theory_content_html('![Схема](/static/scheme.svg)\n*Схема: $x^2$ на числовой прямой.*'))
    soup = BeautifulSoup(rendered, 'html.parser')
    figure = soup.select_one('figure.theory-figure')
    assert figure is not None
    assert figure.select_one('img.theory-figure-image') is not None
    assert 'Схема:' in figure.select_one('figcaption').get_text(' ', strip=True)
    assert figure.select_one('figcaption .theory-math-source') is not None


def test_local_katex_accepts_profile_math_constructs():
    expressions = [
        r"\frac{1}{2}+\dfrac{3}{4}+\sqrt[3]{8}",
        r"x_1^2+\sum_{k=1}^{n}k+\prod_{k=1}^{n}k",
        r"\lim_{x\to0}\frac{\sin x}{x}+\int_0^1x^2\,\mathrm{d}x",
        r"\log_2 8+\ln e+\arcsin(1)+\arccos(0)+\arctan(1)",
        r"\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}",
        r"\begin{aligned}a&=b+c\\d&=e-f\end{aligned}",
        r"\begin{pmatrix}1&2\\3&4\end{pmatrix}+\begin{bmatrix}0\\1\end{bmatrix}",
        r"\left|\alpha+\beta\right|+\overrightarrow{AB}+\angle ABC",
    ]
    report = ValidationReport(package_dir='test')
    _validate_latex(expressions, report)
    assert report.latex_checked
    assert report.issues == []


def test_math_is_renderable_inside_question_options_and_callout():
    content = r"""[IMPORTANT title="Формула $x^2$ важна"]
Свойство: $\frac{a}{b}$.
[/IMPORTANT]

[CHECKPOINT key="math-cp" question="Чему равно $\sqrt{9}$?" options="$2$|$3$" answer="$3$" explanation="Поскольку $3^2=9$."]

[INTERACTIVE type="math" key="math-input" validator="fraction" prompt="Введите $\frac{1}{2}$" answer="\frac{1}{2}"]
"""
    rendered = str(_render_theory_content_html(content))
    # Question and option math become renderable nodes. The answer attribute is
    # intentionally kept as escaped source because it is not learner-visible.
    assert rendered.count('class="theory-math-source"') >= 6
    assert 'data-checkpoint-key="math-cp"' in rendered
    assert 'data-interactive-type="math"' in rendered
    assert '<math-field' in rendered


def test_math_preparation_does_not_scan_code_and_strips_unsafe_authored_html():
    content = r"""Text $x^2$.

```html
<script>not an executable script</script> $\frac{1}{2}$
```

<script>alert(1)</script><img src="x" onerror="alert(1)">
"""
    prepared, tokens = prepare_theory_source(content)
    assert len(tokens) == 1
    # Fenced code is deliberately protected from the author-HTML sanitizer;
    # Markdown must still render it as escaped code, not executable markup.
    assert 'onerror' not in prepared
    rendered = str(_render_theory_content_html(content))
    assert rendered.count('class="theory-math-source"') == 1
    code_text = BeautifulSoup(rendered, 'html.parser').get_text(' ', strip=True)
    assert 'not an executable script' in code_text
    assert r'\frac' in code_text and '$' in code_text
    assert 'alert(1)' in rendered
    assert '<script' not in rendered
    assert 'onerror=' not in rendered


def test_math_validation_numeric_fraction_tolerance_and_multiple_answers():
    assert validate_math_answer('0,5', '1/2', validator='numeric')['correct']
    assert validate_math_answer(r'\frac{2}{4}', '1/2', validator='fraction')['correct']
    for latex_fraction in (r'\frac12', r'\dfrac12', r'\tfrac12', r'\frac{1}{2}'):
        assert validate_math_answer(latex_fraction, '1/2', validator='fraction')['correct']
    assert validate_math_answer('2/4', r'\frac12', validator='fraction')['correct']
    assert validate_math_answer('1.001', '1', validator='numeric_tolerance', absolute_tolerance='0.002')['correct']
    assert not validate_math_answer('1.01', '1', validator='numeric_tolerance', absolute_tolerance='0.002')['correct']
    assert validate_math_answer('2', '1|2', validator='numeric', valid_answers='1|2')['correct']


def test_math_validation_symbolic_polynomials_is_exact_and_domain_safe():
    assert validate_math_answer('(x-1)(x+1)', 'x^2-1', validator='symbolic')['correct']
    assert validate_math_answer('2x+2y', '2*(x+y)', validator='symbolic')['correct']
    rejected = validate_math_answer('x/x', '1', validator='symbolic')
    assert rejected['status'] == 'unsupported'
    assert 'область определения' in rejected['message']


def test_math_validation_sets_intervals_and_unsupported_input():
    assert validate_math_answer('{3; -1; 2}', '{-1; 2; 3}', validator='set')['correct']
    assert validate_math_answer('(-inf; 2]', '(-∞; 2]', validator='interval')['correct']
    assert validate_math_answer('__import__("os")', '1', validator='numeric')['status'] in {'unsupported', 'invalid_format'}
    assert validate_math_answer('x+1', '2', validator='numeric')['status'] == 'unsupported'


def test_semantic_blocks_reveal_solution_and_independent_step_exercise():
    content = r"""[DEFINITION title="Квадрат"]
Квадрат числа: $x^2$.
[/DEFINITION]

[THEOREM title="Положительность"]
Для $x\ne0$ верно $x^2>0$.
[/THEOREM]

[PROOF]
Квадрат ненулевого числа положителен.
[/PROOF]

[EXAMPLE title="Подстановка"]
При $x=3$ получаем $9$.
[/EXAMPLE]

[FORMULA title="Разность квадратов"]
$$a^2-b^2=(a-b)(a+b)$$
[/FORMULA]

[COMMON_MISTAKE title="Не сокращайте слагаемые"]
Нельзя сокращать части суммы как дроби.
[/COMMON_MISTAKE]

[SUMMARY]
Повторите свойство и проверьте его на примере.
[/SUMMARY]

[SOLUTION title="Показать разбор"]
Сначала вычислим дискриминант $D=b^2-4ac$.
[/SOLUTION]

[STEP_EXERCISE key="quadratic" title="Корни квадратного уравнения"]
[STEP key="discriminant" prompt="Найдите $D$ для $x^2-5x+6=0$" answer="1" validator="numeric"]
[STEP key="first-root" prompt="Укажите меньший корень" answer="2" validator="numeric"]
[/STEP_EXERCISE]"""
    rendered = str(_render_theory_content_html(content))
    for class_name in ('theory-definition', 'theory-theorem', 'theory-proof', 'theory-example', 'theory-formula', 'theory-common-mistake', 'theory-summary', 'theory-solution', 'theory-step-exercise'):
        assert class_name in rendered
    assert rendered.count('data-interactive-key="quadratic.') == 2
    assert rendered.count('<math-field') == 2
    items = _parse_theory_checkpoints(content)
    assert {item['key'] for item in items} >= {'quadratic.discriminant', 'quadratic.first-root'}


def test_math_interval_answers_with_brackets_and_author_feedback_parse():
    content = r'''[INTERACTIVE type="math" key="interval-answer" prompt="Запишите интервал" answer="[-1; 1]" validator="interval" explanation="Обе границы включены." hint="Проверьте скобки."]

[STEP_EXERCISE key="interval-steps" title="Запишите тот же интервал"]
[STEP key="write-interval" prompt="Введите интервал" answer="[-1; 1]" validator="interval"]
[/STEP_EXERCISE]'''
    items = _parse_theory_interactives(content)
    assert len(items) == 2
    assert items[0]['answer'] == '[-1; 1]'
    assert items[0]['explanation'] == 'Обе границы включены.'
    assert items[1]['answer'] == '[-1; 1]'
    assert 'theory-step-exercise' in str(_render_theory_content_html(content))


def test_safe_declarative_graph_and_geometry_svg():
    graph = render_function_plot({
        'functions': [{'expression': 'x^2', 'label': 'y=x²'}, {'expression': 'x', 'label': 'y=x'}],
        'x_min': -4, 'x_max': 4, 'y_min': -2, 'y_max': 12,
        'points': [{'x': 1, 'y': 1, 'label': 'пересечение'}],
        'intervals': [{'x_min': 0, 'x_max': 2}], 'show_intersections': True,
    })
    assert '<svg' in graph and '<path' in graph and '<circle' in graph
    assert 'пересечение' in graph and 'fill-opacity="0.52"' in graph
    try:
        render_function_plot({'functions': [{'expression': '__import__("os")'}]})
        assert False, 'unknown functions must be rejected'
    except ValueError as error:
        assert 'Не удалось построить' in str(error)

    diagram = render_geometry({'items': [
        {'type': 'point', 'name': 'A', 'x': 100, 'y': 100},
        {'type': 'point', 'name': 'B', 'x': 300, 'y': 100},
        {'type': 'point', 'name': 'C', 'x': 100, 'y': 300},
        {'type': 'segment', 'from': 'A', 'to': 'B', 'equal_marks': 1},
        {'type': 'polygon', 'points': ['A', 'B', 'C'], 'fill': 'url(javascript:alert(1))'},
        {'type': 'angle', 'a': 'B', 'vertex': 'A', 'b': 'C', 'right': True},
    ]})
    assert '<polygon' in diagram and '<polyline' in diagram and 'fill="#c7d2fe"' in diagram
    assert 'javascript:' not in diagram


def test_uploaded_svg_sanitizer_strips_active_and_external_markup():
    import xml.etree.ElementTree as ET
    from app.theory.math_curriculum import _sanitize_svg

    unsafe = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" onload="alert(1)">
      <script>alert(2)</script><foreignObject><iframe src="https://example.invalid"></iframe></foreignObject>
      <rect x="1" y="1" width="10" height="10" fill="#4f46e5" onclick="alert(3)"/>
      <image href="https://example.invalid/tracker.svg"/>
    </svg>'''
    sanitized = ET.fromstring(_sanitize_svg(unsafe))
    local_name = lambda value: value.rsplit('}', 1)[-1]
    tags = {local_name(node.tag) for node in sanitized.iter()}
    attrs = {local_name(key) for node in sanitized.iter() for key in node.attrib}
    values = [value for node in sanitized.iter() for value in node.attrib.values()]
    assert 'svg' in tags and 'rect' in tags and sanitized.attrib['viewBox'] == '0 0 20 20'
    assert not tags.intersection({'script', 'foreignObject', 'iframe', 'image'})
    assert not any(name.lower().startswith('on') for name in attrs)
    assert not any('https://example.invalid' in value for value in values)


def _write_math_package(root, *, content='## Теория\n\nФормула $$x^2$$.\n\n![Чертёж](asset:triangle)\n'):
    import json
    root.mkdir(parents=True, exist_ok=True)
    (root / 'groups/algebra/assets').mkdir(parents=True, exist_ok=True)
    (root / 'groups/algebra/assets/triangle.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" onload="alert(1)"><script>alert(1)</script><path d="M0 0L100 0L50 100Z" fill="#4f46e5"/></svg>',
        encoding='utf-8',
    )
    (root / 'groups/algebra/001-basics.md').write_text(content, encoding='utf-8')
    manifest = {
        'schema_version': 1,
        'course': {'slug': 'math-import-test', 'title': 'Тестовый курс математики'},
        'expected_structure': {'groups': 1, 'articles': 1},
        'groups': [{
            'key': 'algebra', 'name': 'Алгебра', 'description': 'Основы', 'position': 1,
            'assets': [{'key': 'triangle', 'path': 'groups/algebra/assets/triangle.svg'}],
            'articles': [{
                'key': 'algebra-basics', 'task_number': 1, 'position': 1,
                'title': 'Алгебраические выражения', 'description': 'Степени и формулы',
                'read_minutes': 10, 'status': 'draft', 'source': 'groups/algebra/001-basics.md',
            }],
        }],
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return manifest


def test_math_package_validation_and_safe_idempotent_draft_import(app, tmp_path):
    from app.models import Course, TheoryBlock, TheoryGroup, db

    root = tmp_path / 'math-course'
    manifest = _write_math_package(root)
    loaded, report = validate_math_package(root)
    assert report.valid and report.latex_checked
    assert report.groups == 1 and report.articles == 1 and report.assets == 1

    with app.app_context():
        result = import_drafts(
            loaded, report, author_id=None, overwrite=False, db=db,
            Course=Course, TheoryBlock=TheoryBlock, TheoryGroup=TheoryGroup,
            static_root=tmp_path / 'static',
        )
        assert result['course_created'] is True
        course = Course.query.filter_by(slug='math-import-test').one()
        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=1).one()
        original_id = block.id
        assert block.content.startswith('<!--status:draft-->')
        assert '/static/uploads/theory_math/math-import-test/algebra/' in block.content
        assert 'onload=' not in (tmp_path / 'static').rglob('*.svg').__iter__().__next__().read_text(encoding='utf-8')
        repeated = import_drafts(
            loaded, report, author_id=None, overwrite=False, db=db,
            Course=Course, TheoryBlock=TheoryBlock, TheoryGroup=TheoryGroup,
            static_root=tmp_path / 'static',
        )
        assert repeated['articles_unchanged'] == 1
        assert TheoryBlock.query.filter_by(course_id=course.id, task_number=1).count() == 1
        assert TheoryBlock.query.filter_by(course_id=course.id, task_number=1).one().id == original_id

        published = publish_selected(
            loaded, report, selected_keys={'algebra-basics'}, db=db,
            Course=Course, TheoryBlock=TheoryBlock,
        )
        assert published['published'] == 1
        block = TheoryBlock.query.filter_by(course_id=course.id, task_number=1).one()
        assert block.content.startswith('<!--status:published-->')

        (root / 'groups/algebra/001-basics.md').write_text('## Теория\n\nНовая версия.\n', encoding='utf-8')
        changed_manifest, changed_report = validate_math_package(root)
        try:
            import_drafts(
                changed_manifest, changed_report, author_id=None, overwrite=True, db=db,
                Course=Course, TheoryBlock=TheoryBlock, TheoryGroup=TheoryGroup,
                static_root=tmp_path / 'static',
            )
            assert False, 'published content must never be silently overwritten'
        except ValueError as error:
            assert 'Конфликт статей' in str(error)


def test_math_package_rejects_path_traversal_and_malformed_interactions(tmp_path):
    root = tmp_path / 'bad-package'
    manifest = _write_math_package(root)
    manifest['groups'][0]['articles'][0]['source'] = '../outside.md'
    manifest['groups'][0]['articles'][0]['position'] = 1
    import json
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    _, report = validate_math_package(root)
    assert not report.valid
    assert any('выходить за каталог' in issue['message'] for issue in report.issues)


def test_student_direct_article_and_interaction_requests_obey_sequence_lock(app, client, role_users):
    from app.models import Course, TheoryBlock, TheoryGroup, db
    from tests.v2.conftest import login_as

    with app.app_context():
        course = Course(title='Маршрут доступа к теории', slug='theory-direct-lock-test', is_active=True)
        db.session.add(course)
        db.session.flush()
        group = TheoryGroup(course_id=course.id, name='Алгебра', position=1)
        db.session.add(group)
        db.session.flush()
        first = TheoryBlock(course_id=course.id, group_id=group.id, task_number=1, position=1, title='Первая', content='<!--status:published-->Первая.')
        second = TheoryBlock(
            course_id=course.id, group_id=group.id, task_number=2, position=2, title='Вторая',
            content='<!--status:published-->Вторая.\n[INTERACTIVE type="input" key="later-check" prompt="Ответ" answer="готово"]',
        )
        db.session.add_all([first, second])
        db.session.commit()
        first_id, second_id, course_id = first.id, second.id, course.id

    login_as(client, role_users['student_user_id'], 'student')
    blocked_article = client.get(f'/theory/topic/{second_id}?course_id={course_id}')
    assert blocked_article.status_code == 302
    blocked_api = client.post('/theory/api/checkpoint', json={
        'block_id': second_id, 'checkpoint_key': 'later-check', 'answer': 'готово',
    })
    assert blocked_api.status_code == 404

    assert client.get(f'/theory/topic/{first_id}?course_id={course_id}').status_code == 200
    completed = client.post('/theory/api/read', json={'block_id': first_id})
    assert completed.status_code == 200
    assert client.get(f'/theory/topic/{second_id}?course_id={course_id}').status_code == 200
    accepted = client.post('/theory/api/checkpoint', json={
        'block_id': second_id, 'checkpoint_key': 'later-check', 'answer': 'готово',
    })
    assert accepted.status_code == 200 and accepted.get_json()['correct'] is True


def test_student_math_answer_api_checks_variants_and_persists_attempts(app, client, role_users):
    from app.models import Course, TheoryBlock, TheoryCheckpointAttempt, TheoryGroup, db
    from tests.v2.conftest import login_as

    content = r'''<!--status:published-->
[INTERACTIVE type="math" key="fraction-answer" prompt="Введите половину" answer="1/2" validator="fraction" valid_answers="1/2|0.5|0,5" explanation="Все варианты задают одно число." hint="Разделите единицу на два."]
[INTERACTIVE type="math" key="polynomial-answer" prompt="Введите многочлен" answer="x^2-1" validator="symbolic"]'''
    with app.app_context():
        course = Course(title='API математического ответа', slug='theory-math-api-test', is_active=True)
        db.session.add(course)
        db.session.flush()
        group = TheoryGroup(course_id=course.id, name='Проверки', position=1)
        db.session.add(group)
        db.session.flush()
        block = TheoryBlock(
            course_id=course.id, group_id=group.id, task_number=1, position=1,
            title='Проверка дробей', content=content,
        )
        db.session.add(block)
        db.session.commit()
        block_id, course_id = block.id, course.id

    login_as(client, role_users['student_user_id'], 'student')
    article = client.get(f'/theory/topic/{block_id}?course_id={course_id}')
    assert article.status_code == 200
    html = article.get_data(as_text=True)
    assert 'data-interactive-key="fraction-answer"' in html
    assert 'data-answer="1/2"' not in html

    equivalent = client.post('/theory/api/checkpoint', json={
        'block_id': block_id, 'checkpoint_key': 'fraction-answer', 'answer': '0,5',
    })
    assert equivalent.status_code == 200
    assert equivalent.get_json()['correct'] is True
    assert equivalent.get_json()['explanation'] == 'Все варианты задают одно число.'

    mathlive_fraction = client.post('/theory/api/checkpoint', json={
        'block_id': block_id, 'checkpoint_key': 'fraction-answer', 'answer': r'\frac12',
    })
    assert mathlive_fraction.status_code == 200
    assert mathlive_fraction.get_json()['correct'] is True

    retry = client.post('/theory/api/checkpoint', json={
        'block_id': block_id, 'checkpoint_key': 'fraction-answer', 'answer': '0.75',
    })
    assert retry.status_code == 200
    assert retry.get_json()['correct'] is False
    assert retry.get_json()['attempts'] == 3

    unsupported = client.post('/theory/api/checkpoint', json={
        'block_id': block_id, 'checkpoint_key': 'polynomial-answer', 'answer': 'x/x',
    })
    assert unsupported.status_code == 200
    assert unsupported.get_json()['status'] == 'unsupported'
    assert 'область определения' in unsupported.get_json()['message']

    with app.app_context():
        attempt = TheoryCheckpointAttempt.query.filter_by(
            student_id=role_users['student_id'], block_id=block_id,
            checkpoint_key='fraction-answer',
        ).one()
        assert attempt.selected_answer == '0.75'
        assert attempt.is_correct is False
        assert attempt.attempts_count == 3


def test_inactive_draft_math_course_is_visible_but_cannot_be_assigned(app, client, role_users):
    from app.models import Course, StudentCourseEnrollment, TheoryBlock, TheoryGroup, db
    from tests.v2.conftest import login_as

    with app.app_context():
        course = Course(title='ЕГЭ-2027: профильная математика', slug='theory-draft-assignment-test', is_active=False)
        db.session.add(course)
        db.session.flush()
        group = TheoryGroup(course_id=course.id, name='Математический фундамент', position=1)
        db.session.add(group)
        db.session.flush()
        block = TheoryBlock(
            course_id=course.id, group_id=group.id, task_number=1, position=1,
            title='Черновая статья', content='<!--status:draft-->Материал.',
        )
        db.session.add(block)
        db.session.commit()
        course_id = course.id

    login_as(client, role_users['tutor_id'], 'tutor')
    profile = client.get(f"/theory/api/manage/student/{role_users['student_id']}/theory-profile")
    assert profile.status_code == 200
    listed_course = next(item for item in profile.get_json()['courses'] if item['course_id'] == course_id)
    assert listed_course['can_assign'] is False
    assert listed_course['course_is_active'] is False
    assert listed_course['published_topics'] == 0
    assert listed_course['draft_topics'] == 1

    response = client.post('/theory/api/manage/student/course-status', json={
        'student_id': role_users['student_id'], 'course_id': course_id, 'status': 'assigned',
    })
    assert response.status_code == 409
    assert 'неактивен' in response.get_json()['error'].lower()
    with app.app_context():
        assert StudentCourseEnrollment.query.filter_by(
            student_id=role_users['student_id'], course_id=course_id,
        ).first() is None


def test_theory_preview_post_requires_csrf_when_csrf_is_enabled(app, client, role_users):
    import re
    from app.models import Course, TheoryGroup, db
    from tests.v2.conftest import login_as

    with app.app_context():
        course = Course(title='Курс для CSRF', slug='theory-csrf-test', is_active=True)
        db.session.add(course)
        db.session.flush()
        db.session.add(TheoryGroup(course_id=course.id, name='Группа', position=1))
        db.session.commit()
        course_id = course.id
    app.config['WTF_CSRF_ENABLED'] = True
    login_as(client, role_users['tutor_id'], 'tutor')

    rejected = client.post('/theory/manage/preview', json={'title': 'Предпросмотр', 'content': 'Текст'})
    assert rejected.status_code in {400, 403}

    page = client.get(f'/theory/manage?course_id={course_id}')
    assert page.status_code == 200
    token_match = re.search(r"X-CSRFToken':\s*'([^']+)'", page.get_data(as_text=True))
    assert token_match
    accepted = client.post(
        '/theory/manage/preview',
        json={'title': 'Предпросмотр', 'content': 'Текст'},
        headers={'X-CSRFToken': token_match.group(1)},
    )
    assert accepted.status_code == 200 and accepted.get_json()['success'] is True


def test_student_theory_progress_api_requires_csrf_when_enabled(app, client, role_users):
    import re
    from app.models import Course, TheoryBlock, TheoryGroup, db
    from tests.v2.conftest import login_as

    with app.app_context():
        course = Course(title='CSRF API', slug='theory-csrf-api-test', is_active=True)
        db.session.add(course)
        db.session.flush()
        group = TheoryGroup(course_id=course.id, name='Группа', position=1)
        db.session.add(group)
        db.session.flush()
        block = TheoryBlock(
            course_id=course.id, group_id=group.id, task_number=1, position=1,
            title='Первая тема', content='<!--status:published-->Текст темы.',
        )
        db.session.add(block)
        db.session.commit()
        block_id, course_id = block.id, course.id

    app.config['WTF_CSRF_ENABLED'] = True
    login_as(client, role_users['student_user_id'], 'student')
    article = client.get(f'/theory/topic/{block_id}?course_id={course_id}')
    assert article.status_code == 200
    token_match = re.search(r"X-CSRFToken':\s*'([^']+)'", article.get_data(as_text=True))
    assert token_match

    rejected = client.post('/theory/api/progress', json={
        'block_id': block_id, 'progress': 25, 'position': 100,
    })
    assert rejected.status_code in {400, 403}

    accepted = client.post('/theory/api/progress', json={
        'block_id': block_id, 'progress': 25, 'position': 100,
    }, headers={'X-CSRFToken': token_match.group(1)})
    assert accepted.status_code == 200
    assert accepted.get_json() == {'success': True, 'progress': 25}
