"""
Тест полной функциональности комнаты урока ученика /sandbox/lesson_room/<lesson_id>
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

app.config['WTF_CSRF_ENABLED'] = False
client = app.test_client()

student_user = User.query.filter_by(username='Student_1').first()
check('Student_1 найден в БД', student_user is not None)

try:
    # ── 1. GET /sandbox/lesson_room/1 — Проверка отображения комнаты урока и 4 вкладок ──
    print('\n[2] Проверка GET /sandbox/lesson_room/1 (HTML и 4 вкладки)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student_user.id if student_user else 1)
        sess['sandbox_role'] = 'student'
        sess['sandbox_student_id'] = 3
        sess['_fresh'] = True

    r_room = client.get('/sandbox/lesson_room/1')
    check('GET /sandbox/lesson_room/1 = 200', r_room.status_code == 200)
    html_room = r_room.data.decode('utf-8', errors='replace')

    check('Вкладка "Теория" (content-theory) присутствует в HTML', 'id="content-theory"' in html_room)
    check('Вкладка "Практика и задачи" (content-classwork) присутствует в HTML', 'id="content-classwork"' in html_room)
    check('Вкладка "Конспект" (content-notes) присутствует в HTML', 'id="content-notes"' in html_room)
    check('Вкладка "Интерактивная доска" (content-whiteboard) присутствует в HTML', 'id="content-whiteboard"' in html_room)
    check('Видеоплеер присутствует в HTML', 'id="lesson-video-player"' in html_room)
    check('Таймкоды видео присутствуют в HTML', 'timecode-btn' in html_room)
    check('Кнопка "В дашборд" присутствует в HTML', 'В дашборд' in html_room)

    # ── 2. POST /sandbox/api/lesson_room/check_task — Проверка работы тренажёра ──
    print('\n[3] Проверка POST /sandbox/api/lesson_room/check_task (Верный и неверный ответы)...')
    
    # 2.1 Верный ответ на задачу №4 (ответ "7")
    r_correct = client.post('/sandbox/api/lesson_room/check_task', json={
        "lesson_id": 1,
        "task_id": 4,
        "answer": "7"
    })
    check('POST check_task (верный ответ) = 200', r_correct.status_code == 200)
    data_correct = r_correct.get_json()
    check('JSON response ok == True', data_correct.get('ok') is True)
    check('JSON response is_correct == True', data_correct.get('is_correct') is True)
    check('Сообщение об успехе содержит "Отлично"', 'Отлично' in data_correct.get('message', ''))

    # 2.2 Неверный ответ на задачу №4 (ответ "999")
    r_wrong = client.post('/sandbox/api/lesson_room/check_task', json={
        "lesson_id": 1,
        "task_id": 4,
        "answer": "999"
    })
    check('POST check_task (неверный ответ) = 200', r_wrong.status_code == 200)
    data_wrong = r_wrong.get_json()
    check('JSON response ok == True', data_wrong.get('ok') is True)
    check('JSON response is_correct == False', data_wrong.get('is_correct') is False)
    check('Сообщение об ошибке содержит "Неверно"', 'Неверно' in data_wrong.get('message', ''))

    # ── 3. GET /sandbox/api/lesson_room/download_summary/1 — Проверка скачивания PDF ──
    print('\n[4] Проверка GET /sandbox/api/lesson_room/download_summary/1 (PDF скачивание)...')
    r_pdf = client.get('/sandbox/api/lesson_room/download_summary/1')
    check('GET download_summary = 200', r_pdf.status_code == 200)
    check('Content-Type == application/pdf', r_pdf.headers.get('Content-Type') == 'application/pdf')
    check('Content-Disposition содержит attachment', 'attachment' in r_pdf.headers.get('Content-Disposition', ''))
    check('Бинарный заголовок %PDF присутствуют в файле', r_pdf.data.startswith(b'%PDF'))

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
