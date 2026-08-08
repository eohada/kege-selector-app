"""
Тест структуры сетки расписания (24-часовая шкала времени 00:00-23:00 и слоты дней)
"""
import sys
import os

sys.path.insert(0, os.path.abspath('e:/projects/kege_selector_app_current'))

from wsgi import app
from core.db_models import db, User

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

teacher = User.query.filter_by(username='Teacher_1').first()
check('Teacher_1 найден в БД', teacher is not None)

try:
    # ── 2. Проверка структуры сетки /sandbox/teacher_schedule ──
    print('\n[2] Проверка сетки расписания преподавателя (GET /sandbox/teacher_schedule)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['sandbox_role'] = 'teacher'
        sess['_fresh'] = True

    r_t = client.get('/sandbox/teacher_schedule')
    check('GET /sandbox/teacher_schedule = 200', r_t.status_code == 200)
    html_t = r_t.data.decode('utf-8', errors='replace')

    check('Шкала времени 00:00 присутствует в HTML', '00:00' in html_t)
    check('Шкала времени 12:00 присутствует в HTML', '12:00' in html_t)
    check('Шкала времени 23:00 присутствует в HTML', '23:00' in html_t)
    check('Контейнер hour-rows присутствует в DOM', 'id="hour-rows"' in html_t)
    check('Сетка дней недели days-header присутствует в DOM', 'id="days-header"' in html_t)

    # ── 3. Проверка структуры сетки /sandbox/student_schedule ──
    print('\n[3] Проверка сетки расписания ученика (GET /sandbox/student_schedule)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['sandbox_role'] = 'student'
        sess['sandbox_student_id'] = 3
        sess['_fresh'] = True

    r_s = client.get('/sandbox/student_schedule')
    check('GET /sandbox/student_schedule = 200', r_s.status_code == 200)
    html_s = r_s.data.decode('utf-8', errors='replace')

    check('Шкала времени 00:00 присутствует в HTML ученика', '00:00' in html_s)
    check('Шкала времени 12:00 присутствует в HTML ученика', '12:00' in html_s)
    check('Шкала времени 23:00 присутствует в HTML ученика', '23:00' in html_s)
    check('Контейнер hour-rows присутствует в DOM ученика', 'id="hour-rows"' in html_s)

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
