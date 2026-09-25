import json
import pytest
from app.assignments.ai_importer import parse_and_convert_ai_homework
from core.db_models import Tasks
from tests.v2.conftest import login_as


SAMPLE_USER_JSON = """{
  "title": "Закрепление: условия и типы данных",
  "subtitle": "Короткая практика после разбора ошибок",
  "audience": "ученик с нулевого уровня, подготовка к ЕГЭ по информатике",
  "estimated_minutes": 25,
  "instructions": "Не торопись. В заданиях с кодом сначала выпиши, какие переменные будут текстом, а какие — числами. После этого обязательно запусти программу на примерах.",
  "skills_checked": [
    "типы str и int",
    "input() и int(input())",
    "арифметические операции",
    "сравнения",
    "if / else",
    "логический оператор and"
  ],
  "tasks": [
    {
      "id": "conditions-reinforce-01",
      "type": "choice",
      "title": "Число или текст?",
      "prompt": "Какой тип данных будет у переменной `count` после выполнения кода?\\n\\n```python\\ncount = int(input())\\n```",
      "options": [
        { "id": "a", "text": "str — текст" },
        { "id": "b", "text": "int — целое число" },
        { "id": "c", "text": "bool — истина или ложь" },
        { "id": "d", "text": "Переменная не получит тип" }
      ],
      "correct_option_id": "b",
      "explanation": "input() получает текст, а int(...) преобразует этот текст в целое число.",
      "points": 1
    },
    {
      "id": "conditions-reinforce-02",
      "type": "short_answer",
      "title": "Прочитай код внимательно",
      "prompt": "Что выведет программа? Впиши только число.\\n\\n```python\\ntext_number = \\"12\\"\\nnumber = int(text_number) + 8\\n\\nif number > 15:\\n    print(number - 5)\\nelse:\\n    print(number)\\n```",
      "correct_answer": "15",
      "explanation": "Текст \\"12\\" превращается в число 12. Затем number равно 20, условие выполняется, и выводится 20 - 5.",
      "points": 1
    },
    {
      "id": "conditions-reinforce-03",
      "type": "extended_answer",
      "title": "Исправь программу",
      "prompt": "Программа должна вывести `Проход есть`, если код равен 1234. Она выдаёт ошибку. Объясни, почему, и напиши исправленную первую строку.\\n\\n```python\\ncode = input()\\nif code == 1234:\\n    print(\\"Проход есть\\")\\nelse:\\n    print(\\"Неверный код\\")\\n```",
      "rubric": [
        "Указано, что input() возвращает строку.",
        "Указано, что код нужно сравнивать со строкой \\"1234\\" или преобразовать ввод в int.",
        "Написана корректная исправленная строка."
      ],
      "sample_answer": "input() возвращает текст, поэтому нельзя сравнивать его с числом 1234. Можно написать: code = int(input()).",
      "points": 2
    },
    {
      "id": "conditions-reinforce-04",
      "type": "code",
      "title": "Двузначное число",
      "prompt": "Вводится целое число `n`. Выведи `Двузначное`, если оно лежит в диапазоне от 10 до 99 включительно. Иначе выведи `Не двузначное`.\\n\\nИспользуй `and`.\\n\\nПримеры:\\n- `42` → `Двузначное`\\n- `7` → `Не двузначное`\\n- `100` → `Не двузначное`",
      "starter_code": "n = int(input())\\n\\n# напиши программу ниже\\n",
      "tests": [
        { "input": "42", "output": "Двузначное", "visibility": "public" },
        { "input": "7", "output": "Не двузначное", "visibility": "public" },
        { "input": "10", "output": "Двузначное", "visibility": "hidden" },
        { "input": "99", "output": "Двузначное", "visibility": "hidden" },
        { "input": "100", "output": "Не двузначное", "visibility": "hidden" }
      ],
      "reference_solution": "n = int(input())\\n\\nif n >= 10 and n <= 99:\\n    print(\\"Двузначное\\")\\nelse:\\n    print(\\"Не двузначное\\")",
      "teacher_hint": "В условии должны одновременно выполняться две проверки: число не меньше 10 и не больше 99.",
      "points": 3
    },
    {
      "id": "conditions-reinforce-05",
      "type": "code",
      "title": "Заявка на курс",
      "prompt": "Вводятся три значения: имя ученика, возраст и ответ `да` или `нет` на вопрос «есть согласие на участие?».\\n\\nЗаявка принимается, если ученику 14 лет или больше **и** он ввёл `да`. Тогда выведи `Заявка принята`. Во всех остальных случаях выведи `Заявка не принята`.\\n\\nИмя нужно считать текстом, возраст — числом, ответ — текстом.\\n\\nПример ввода:\\n```text\\nАня\\n15\\nда\\n```\\n\\nПример вывода:\\n```text\\nЗаявка принята\\n```",
      "starter_code": "name = input()\\nage = int(input())\\nanswer = input()\\n\\n# напиши программу ниже\\n",
      "tests": [
        { "input": "Аня\\n15\\nда", "output": "Заявка принята", "visibility": "public" },
        { "input": "Илья\\n13\\nда", "output": "Заявка не принята", "visibility": "public" },
        { "input": "Маша\\n17\\nнет", "output": "Заявка не принята", "visibility": "hidden" },
        { "input": "Рома\\n14\\nда", "output": "Заявка принята", "visibility": "hidden" }
      ],
      "reference_solution": "name = input()\\nage = int(input())\\nanswer = input()\\n\\nif age >= 14 and answer == \\"да\\":\\n    print(\\"Заявка принята\\")\\nelse:\\n    print(\\"Заявка не принята\\")",
      "teacher_hint": "Вспомни: возраст — число, а ответ `да` — текст, поэтому его берём в кавычки.",
      "points": 4
    }
  ],
  "total_points": 11,
  "teacher_note": "Это не новая тема, а точечное закрепление ошибок: перед разбором попроси ученика в заданиях 4–5 вслух назвать тип каждой переменной. Не открывай подсказки заранее."
}"""


def test_ai_importer_direct_service_conversion(app, role_users):
    """Проверка прямого парсинга JSON домашнего задания от ИИ-агента."""
    tutor_id = role_users['tutor_id']

    with app.app_context():
        res = parse_and_convert_ai_homework(SAMPLE_USER_JSON, user_id=tutor_id)

        assert res['success'] is True
        assert res['count'] == 5

        meta = res['assignment_meta']
        assert meta['title'] == 'Закрепление: условия и типы данных'
        assert meta['time_limit'] == 25
        assert 'Не торопись' in meta['description']
        assert 'типы str и int' in meta['description']

        tasks = res['tasks']
        assert len(tasks) == 5

        # Task 1: single_choice
        t1 = tasks[0]
        assert t1['answer_spec']['type'] == 'single_choice'
        assert t1['answer'] == 'b'
        assert len(t1['answer_spec']['options']) == 4
        assert t1['max_score'] == 1
        assert 'Число или текст' in t1['content_html']

        # Task 2: short_answer
        t2 = tasks[1]
        assert t2['answer_spec']['type'] == 'short_answer'
        assert t2['answer'] == '15'
        assert t2['max_score'] == 1

        # Task 3: long_answer (extended_answer)
        t3 = tasks[2]
        assert t3['answer_spec']['type'] == 'long_answer'
        assert t3['requires_manual_grading'] is True
        assert t3['max_score'] == 2
        assert 'Критерии проверки' in t3['solution'] or 'input()' in t3['solution']

        # Task 4: code
        t4 = tasks[3]
        assert t4['answer_spec']['type'] == 'code'
        assert 'int(input())' in t4['starter_code']
        assert len(t4['answer_spec']['tests']) == 5
        assert t4['max_score'] == 3

        # Task 5: code
        t5 = tasks[4]
        assert t5['answer_spec']['type'] == 'code'
        assert len(t5['answer_spec']['tests']) == 4
        assert t5['max_score'] == 4


def test_ai_importer_http_endpoint(client, role_users):
    """Проверка вызова API /assignments/api/import-ai-json с загрузкой JSON."""
    tutor_id = role_users['tutor_id']
    login_as(client, tutor_id, 'tutor')

    resp = client.post(
        '/assignments/api/import-ai-json',
        data=json.dumps({'json_data': SAMPLE_USER_JSON}),
        content_type='application/json'
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['count'] == 5
    assert data['assignment_meta']['title'] == 'Закрепление: условия и типы данных'
    assert len(data['tasks']) == 5


def test_ai_importer_handles_plain_tasks_list(app, role_users):
    """Проверка поддержки прямого массива заданий без метаданных работы."""
    tutor_id = role_users['tutor_id']
    raw_list = [
        {
            "type": "choice",
            "title": "Выбор",
            "prompt": "2 + 2 = ?",
            "options": [{"id": "1", "text": "3"}, {"id": "2", "text": "4"}],
            "correct_option_id": "2",
            "points": 1
        },
        {
            "type": "short_answer",
            "prompt": "5 * 5 = ?",
            "correct_answer": "25",
            "points": 2
        }
    ]

    with app.app_context():
        res = parse_and_convert_ai_homework(raw_list, user_id=tutor_id)
        assert res['success'] is True
        assert res['count'] == 2
        assert res['tasks'][0]['answer'] == '2'
        assert res['tasks'][1]['answer'] == '25'


def test_ai_importer_bank_http_endpoint(client, role_users):
    """Проверка вызова API /task-generator/bank/import-json."""
    tutor_id = role_users['tutor_id']
    login_as(client, tutor_id, 'tutor')

    resp = client.post(
        '/task-generator/bank/import-json',
        data=json.dumps({'json_data': SAMPLE_USER_JSON}),
        content_type='application/json'
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['count'] == 5


def test_ai_importer_matching_task_user_format(app, role_users):
    """Проверка парсинга формата matching из пользовательского файла (left_items, right_items, correct_matches)."""
    tutor_id = role_users['tutor_id']
    user_matching_json = """{
      "tasks": [
        {
          "id": "conditions-v2-03",
          "type": "matching",
          "title": "Сопоставь сравнение и результат",
          "prompt": "Соедини выражение с результатом, который оно даёт.",
          "left_items": [
            {"id": "l1", "text": "9 > 4"},
            {"id": "l2", "text": "7 == 7"},
            {"id": "l3", "text": "3 != 3"},
            {"id": "l4", "text": "10 <= 2"}
          ],
          "right_items": [
            {"id": "r1", "text": "False: числа равны, неравенство ложно"},
            {"id": "r2", "text": "True: девять строго больше четырёх"},
            {"id": "r3", "text": "True: значения одинаковы"},
            {"id": "r4", "text": "False: десять не меньше и не равно двум"}
          ],
          "correct_matches": [
            {"left_id": "l1", "right_id": "r2"},
            {"left_id": "l2", "right_id": "r3"},
            {"left_id": "l3", "right_id": "r1"},
            {"left_id": "l4", "right_id": "r4"}
          ],
          "points": 2
        }
      ]
    }"""

    with app.app_context():
        res = parse_and_convert_ai_homework(user_matching_json, user_id=tutor_id)
        assert res['success'] is True
        assert res['count'] == 1
        t_data = res['tasks'][0]
        assert t_data['max_score'] == 2
        assert t_data['requires_manual_grading'] is False
        expected_dict = {"l1": "r2", "l2": "r3", "l3": "r1", "l4": "r4"}
        assert json.loads(t_data['answer']) == expected_dict
        spec = t_data['answer_spec']
        assert spec['type'] == 'matching'
        assert len(spec['pairs']) == 4
        assert len(spec['options']) == 4
        assert spec['correct_matches'] == expected_dict


def test_auto_grade_matching_and_custom_task(app, role_users):
    """Проверка авто-проверки matching и кастомных заданий без CourseTaskTemplate."""
    from datetime import timedelta
    from app.assignments.routes import auto_grade_answer
    from app.utils.timezone import utc_now
    from core.db_models import Assignment, AssignmentTask, Answer, Tasks
    from app import db

    with app.app_context():
        tutor_id = role_users['tutor_id']
        custom_task = Tasks(
            task_number=99,
            site_task_id="test:matching:1",
            content_html="<p>Сопоставление</p>",
            answer=json.dumps({"l1": "r2", "l2": "r1"}),
            created_by_id=tutor_id,
            difficulty_level=1,
            max_score=2,
        )
        db.session.add(custom_task)
        db.session.flush()

        assignment = Assignment(
            title="Тест сопоставления",
            assignment_type="homework",
            deadline=utc_now() + timedelta(days=1),
            created_by_id=tutor_id,
        )
        db.session.add(assignment)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=custom_task.task_id,
            order_index=1,
            max_score=2,
        )
        db.session.add(at)
        db.session.flush()

        # Правильный ответ (даже если ключи в другом порядке)
        correct_ans = Answer(value=json.dumps({"l2": "r1", "l1": "r2"}))
        is_corr, score = auto_grade_answer(correct_ans, at)
        assert is_corr is True
        assert score == 2

        # Неправильный ответ
        wrong_ans = Answer(value=json.dumps({"l1": "r1", "l2": "r2"}))
        is_corr, score = auto_grade_answer(wrong_ans, at)
        assert is_corr is False
        assert score == 0


def test_assignment_edit_and_update_v2(client, role_users, app):
    """Проверка открытия V2-конструктора при редактировании и успешного обновления через /update."""
    from datetime import timedelta
    from app.utils.timezone import utc_now
    from core.db_models import Assignment, AssignmentTask, Tasks
    from app import db

    tutor_id = role_users['tutor_id']
    student_id = role_users['student_id']
    login_as(client, tutor_id, 'tutor')

    with app.app_context():
        t1 = Tasks(task_number=1, site_task_id="t1", content_html="Task 1", answer="42", created_by_id=tutor_id)
        t2 = Tasks(task_number=2, site_task_id="t2", content_html="Task 2", answer="84", created_by_id=tutor_id)
        db.session.add_all([t1, t2])
        db.session.flush()

        assign = Assignment(
            title="Старая работа",
            description="Старое описание",
            deadline=utc_now() + timedelta(days=2),
            created_by_id=tutor_id,
            assignment_type="homework",
            max_attempts_default=3,
        )
        db.session.add(assign)
        db.session.flush()

        at1 = AssignmentTask(assignment_id=assign.assignment_id, task_id=t1.task_id, order_index=0, max_score=1)
        db.session.add(at1)
        db.session.commit()
        assign_id = assign.assignment_id
        t1_id = t1.task_id
        t2_id = t2.task_id

    # 1. GET /assignments/<id>/edit открывает современный sandbox/create_assignment.html
    resp = client.get(f'/assignments/{assign_id}/edit')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Редактирование работы' in html
    assert f'Работа #{assign_id}' in html
    assert 'isEditMode": true' in html

    # 2. POST /assignments/<id>/update сохраняет измененные поля и задания
    update_payload = {
        'title': 'Обновленная работа V2',
        'description': 'Новое описание',
        'type': 'test',
        'time_limit_minutes': 60,
        'time_limit_strict': True,
        'hard_deadline': True,
        'hide_before_start': True,
        'allow_separate_submission': False,
        'tasks': [
            {'task_id': t1_id, 'max_score': 5, 'requires_manual_grading': True},
            {'task_id': t2_id, 'max_score': 3, 'requires_manual_grading': False},
        ],
        'recipientIds': [student_id]
    }
    up_resp = client.post(f'/assignments/{assign_id}/update', json=update_payload)
    assert up_resp.status_code == 200
    assert up_resp.get_json()['success'] is True

    # 3. Проверка обновленного состояния в БД
    with app.app_context():
        refreshed = Assignment.query.get(assign_id)
        assert refreshed.title == 'Обновленная работа V2'
        assert refreshed.description == 'Новое описание'
        assert refreshed.assignment_type == 'test'
        assert refreshed.time_limit_minutes == 60
        assert refreshed.time_limit_strict is True
        assert len(refreshed.tasks) == 2
        t_map = {at.task_id: at for at in refreshed.tasks}
        assert t_map[t1_id].max_score == 5
        assert t_map[t1_id].requires_manual_grading is True
        assert t_map[t2_id].max_score == 3
        assert t_map[t2_id].requires_manual_grading is False
        # Проверяем, что ученик назначен
        assert len(refreshed.submissions) == 1
        assert refreshed.submissions[0].student_id == student_id
        assert refreshed.submissions[0].max_score == 8


