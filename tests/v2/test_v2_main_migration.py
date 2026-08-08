"""
QA Автотест Промоушена V2 в Основную Платформу и Изоляции Legacy V1:
- Тест 1: Авторизация учеником (Student_1) -> GET /dashboard = 200 (Дашборд ученика V2)
- Тест 2: Авторизация преподавателем (Teacher_1) -> GET /dashboard = 200 (Дашборд преподавателя V2)
- Тест 3: Проверка боевых роутов GET /schedule, /lesson_room/1, /teacher_room/1 = 200
- Тест 4: Проверка чистых REST API: POST /api/lesson_room/check_task = 200
- Тест 5: Подтверждение отсоединения блюпринтов V1 без ошибок импорта
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

print('\n[1] Инициализация контекста приложения и проверка пользователей...')
ctx = app.app_context()
ctx.push()

app.config['WTF_CSRF_ENABLED'] = False
client = app.test_client()

student_user = User.query.filter_by(username='Student_1').first()
teacher_user = User.query.filter_by(username='Teacher_1').first()

check('Student_1 найден в БД', student_user is not None)
check('Teacher_1 найден в БД', teacher_user is not None)

try:
    # ── 1. Студент: GET /dashboard — Проверка дашборда ученика V2 ──
    print('\n[2] Проверка авторизации Ученика и GET /dashboard...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student_user.id if student_user else 1)
        sess['_fresh'] = True

    r_st_dash = client.get('/dashboard')
    check('GET /dashboard (Студент) = 200', r_st_dash.status_code == 200)
    html_st_dash = r_st_dash.data.decode('utf-8', errors='replace')
    check('HTML содержит элементы Bento-дашборда ученика V2', 'Ближайший урок' in html_st_dash or 'Моё расписание' in html_st_dash)

    # ── 2. Преподаватель: GET /dashboard — Проверка дашборда преподавателя V2 ──
    print('\n[3] Проверка авторизации Преподавателя и GET /dashboard...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher_user.id if teacher_user else 2)
        sess['_fresh'] = True

    r_tch_dash = client.get('/dashboard')
    check('GET /dashboard (Преподаватель) = 200', r_tch_dash.status_code == 200)
    html_tch_dash = r_tch_dash.data.decode('utf-8', errors='replace')
    check('HTML содержит элементы Bento-дашборда преподавателя V2', ('Преподаватель' in html_tch_dash or 'Расписание' in html_tch_dash))

    # ── 3. Боевые REST Роуты V2 (/schedule, /lesson_room/1, /teacher_room/1) ──
    print('\n[4] Проверка боевых REST-маршрутов V2...')
    r_sched = client.get('/schedule')
    check('GET /schedule = 200', r_sched.status_code == 200)

    r_lroom = client.get('/lesson_room/1')
    check('GET /lesson_room/1 = 200', r_lroom.status_code == 200)
    html_lroom = r_lroom.data.decode('utf-8', errors='replace')
    check('Комната урока содержит Fabric.js и 4 вкладки', 'fabric.min.js' in html_lroom and 'content-theory' in html_lroom)

    r_troom = client.get('/teacher_room/1')
    check('GET /teacher_room/1 = 200', r_troom.status_code == 200)

    # ── 4. Чистые REST API (/api/lesson_room/check_task) ──
    print('\n[5] Проверка чистых REST API (/api/lesson_room/check_task)...')
    r_api_check = client.post('/api/lesson_room/check_task', json={
        "lesson_id": 1,
        "task_id": 1,
        "answer": "8"
    })
    check('POST /api/lesson_room/check_task = 200', r_api_check.status_code == 200)
    data_check = r_api_check.get_json()
    check('ok == True', data_check.get('ok') is True)
    check('is_correct == True', data_check.get('is_correct') is True)

    # ── 5. Проверка отсоединения V1 Блюпринтов ──
    print('\n[6] Проверка отсоединения устаревших V1 блюпринтов...')
    registered_blueprints = list(app.blueprints.keys())
    check('schedule_bp не зарегистрирован в app', 'schedule' not in registered_blueprints)
    check('lessons_bp не зарегистрирован в app', 'lessons' not in registered_blueprints)
    check('students_bp не зарегистрирован в app', 'students' not in registered_blueprints)

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
