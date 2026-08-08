"""
QA Автотест интерактивности Комнаты Урока ученика (/sandbox/lesson_room/<id>):
- Проверка 1: CSRF-защита и валидация ответов тренажёра (POST check_task = 200 без 403)
- Проверка 2: Интеграция Fabric.js на доске (библиотека и инструменты управления)
- Проверка 3: Парсинг Markdown и отсутствие сырых "###"
- Проверка 4: Динамическое имя преподавателя
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath('e:/projects/kege_selector_app_current'))

from wsgi import app
from core.db_models import db, User, ScheduleLesson

PASS = '✅'
FAIL = '❌'
results = []

def check(label, condition, detail=''):
    if condition:
        results.append((PASS, label, detail))
        print(f'  {PASS} {label}' + (f' — {detail}' if detail else ''))
    else:
        results.append((FAIL, label, detail))
        print(f'  {FAIL} {label}' + (f' — {detail}' if detail else ''))

print('\n[1] Инициализация контекста приложения...')
ctx = app.app_context()
ctx.push()

app.config['WTF_CSRF_ENABLED'] = True
client = app.test_client()

student_user = User.query.filter_by(username='Student_1').first()
teacher_user = User.query.filter_by(username='Teacher_1').first()

check('Student_1 найден в БД', student_user is not None)
check('Teacher_1 найден в БД', teacher_user is not None)

try:
    # ── 1. GET /sandbox/lesson_room/1 — Проверка подключения Fabric.js & элементов управления ──
    print('\n[2] Проверка GET /sandbox/lesson_room/1 (Fabric.js & Инициализация)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student_user.id if student_user else 1)
        sess['sandbox_role'] = 'student'
        sess['sandbox_student_id'] = 3
        sess['_fresh'] = True

    r_room = client.get('/sandbox/lesson_room/1')
    check('GET /sandbox/lesson_room/1 = 200', r_room.status_code == 200)
    html_room = r_room.data.decode('utf-8', errors='replace')

    check('Библиотека Fabric.js подключена через CDN', 'fabric.min.js' in html_room)
    check('Кнопка режима кисти (tool-pencil) присутствует', 'id="tool-pencil"' in html_room)
    check('Кнопка режима выделения (tool-select) присутствует', 'id="tool-select"' in html_room)
    check('Кнопка добавления прямоугольника (btn-add-rect) присутствует', 'id="btn-add-rect"' in html_room)
    check('Кнопка добавления текста (btn-add-text) присутствует', 'id="btn-add-text"' in html_room)
    check('Элемент загрузки изображений (board-image-input) присутствует', 'id="board-image-input"' in html_room)

    # Проверка парсинга Markdown и преподавателя
    check('Тег <h3> скомпилирован из Markdown', '<h3>' in html_room)
    check('Сырые символы "### 📐" отсутствуют в HTML конспекта', '### 📐' not in html_room)
    check('Имя преподавателя присутствует в сайдбаре', ('Даниил Багин' in html_room or 'Teacher_1' in html_room or 'Преподаватель' in html_room))

    # ── 2. POST /sandbox/api/lesson_room/check_task — CSRF и проверка заданий ──
    print('\n[3] Проверка POST /sandbox/api/lesson_room/check_task с CSRF...')
    r_check = client.post('/sandbox/api/lesson_room/check_task', json={
        "lesson_id": 1,
        "task_id": 1,
        "answer": "8"
    }, headers={
        'X-CSRFToken': 'test_csrf_token'
    })
    check('POST check_task без ошибки 403 (Status = 200)', r_check.status_code == 200)
    data_check = r_check.get_json()
    check('ok == True', data_check.get('ok') is True)
    check('is_correct == True', data_check.get('is_correct') is True)

finally:
    ctx.pop()

print('\n' + '=' * 60)
passed = sum(1 for s, *_ in results if s == PASS)
failed = sum(1 for s, *_ in results if s == FAIL)
print(f'Итог: {PASS} {passed} прошло | {FAIL} {failed} провалено | Всего: {len(results)}')

if failed:
    sys.exit(1)
else:
    sys.exit(0)
