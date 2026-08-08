"""
Тест динамической выборки ближайшего урока (upcoming_lesson) и комнат урока для ученика и преподавателя
"""
import sys
import os
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath('e:/projects/kege_selector_app_current'))

from wsgi import app
from core.db_models import db, User, ScheduleLesson, Student, Lesson

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
student_user = User.query.filter_by(username='Student_1').first()
student_profile = Student.query.filter_by(user_id=student_user.id).first() if student_user else None

check('Teacher_1 найден в БД', teacher is not None)
check('Student_1 найден в БД', student_profile is not None)

created_lesson = None

try:
    # ── 2. Очистка старых активных/будущих уроков и создание уникального урока на ближайшие 24 часа ──
    print('\n[2] Очистка старых записей и создание урока на ближайшие 24 часа...')
    for l in ScheduleLesson.query.all():
        l.start_dt = datetime.now(timezone.utc) - timedelta(days=2)
        l.status = 'done'
    for l in Lesson.query.all():
        l.lesson_date = datetime.now(timezone.utc) - timedelta(days=2)
        l.status = 'completed'
    db.session.commit()

    start_dt_24h = datetime.now(timezone.utc) + timedelta(hours=4)
    lesson_topic = "Индивидуальный КЕГЭ Урок 2026"
    test_lesson = ScheduleLesson(
        teacher_user_id=teacher.id if teacher else 1,
        student_id=student_profile.student_id if student_profile else 1,
        topic=lesson_topic,
        start_dt=start_dt_24h,
        duration_minutes=60,
        lesson_type='individual',
        status='planned'
    )
    db.session.add(test_lesson)
    db.session.commit()
    created_lesson = test_lesson
    check('Урок создан в БД на ближайшие 24ч', test_lesson.lesson_id is not None, f'lesson_id={test_lesson.lesson_id}')

    # ── 3. Проверка контекста ученика песочницы (sandbox_role = 'student') ──
    print('\n[3] Проверка Дашборда Ученика (GET /sandbox/student_dashboard)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student_user.id)
        sess['sandbox_role'] = 'student'
        sess['sandbox_student_id'] = student_profile.student_id
        sess['_fresh'] = True

    r_stud = client.get('/sandbox/student_dashboard')
    check('GET /sandbox/student_dashboard = 200', r_stud.status_code == 200)
    html_stud = r_stud.data.decode('utf-8', errors='replace')

    check('Тема ближайшего урока на дашборде ученика', lesson_topic in html_stud)
    check('Ссылка на комнату ученика (/sandbox/lesson_room)', f'/sandbox/lesson_room/{test_lesson.lesson_id}' in html_stud)
    check('Заглушка "Ближайших уроков не запланировано" отсутствует', 'Ближайших уроков не запланировано' not in html_stud)

    # ── 4. Проверка страницы расписания ученика (/sandbox/schedule и /sandbox/student_schedule) ──
    print('\n[4] Проверка Расписания Ученика (GET /sandbox/student_schedule)...')
    r_sched = client.get('/sandbox/student_schedule')
    check('GET /sandbox/student_schedule = 200', r_sched.status_code == 200)
    html_sched = r_sched.data.decode('utf-8', errors='replace')

    check('В сайдбаре "БЛИЖАЙШИЙ ОНЛАЙН" отображается тема урока', lesson_topic in html_sched)
    check('В сайдбаре присутствует ссылка на комнату ученика (/sandbox/lesson_room)', f'/sandbox/lesson_room/{test_lesson.lesson_id}' in html_sched)
    check('Текст "Нет предстоящих занятий" отсутствует в сайдбаре', 'Нет предстоящих занятий' not in html_sched)

    # ── 5. Проверка Дашборда и Комнаты Преподавателя (/sandbox/teacher_dashboard & /sandbox/teacher_room) ──
    print('\n[5] Проверка Дашборда Преподавателя (GET /sandbox/teacher_dashboard)...')
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['sandbox_role'] = 'teacher'
        sess['_fresh'] = True

    r_teach = client.get('/sandbox/teacher_dashboard')
    check('GET /sandbox/teacher_dashboard = 200', r_teach.status_code == 200)
    html_teach = r_teach.data.decode('utf-8', errors='replace')

    check('Тема ближайшего урока на дашборде преподавателя', lesson_topic in html_teach)
    check('Ссылка на комнату преподавателя (/sandbox/teacher_room/<id>) присутствует', f'/sandbox/teacher_room/{test_lesson.lesson_id}' in html_teach)

    print('\n[6] Проверка работы страниц комнат урока...')
    r_t_room = client.get(f'/sandbox/teacher_room/{test_lesson.lesson_id}')
    check('GET /sandbox/teacher_room/<id> = 200', r_t_room.status_code == 200)

    r_s_room = client.get(f'/sandbox/lesson_room/{test_lesson.lesson_id}')
    check('GET /sandbox/lesson_room/<id> = 200', r_s_room.status_code == 200)

finally:
    if created_lesson:
        db.session.delete(created_lesson)
        db.session.commit()
    ctx.pop()

print('\n' + '=' * 60)
passed = sum(1 for s, *_ in results if s == PASS)
failed = sum(1 for s, *_ in results if s == FAIL)
print(f'Итог: {PASS} {passed} прошло | {FAIL} {failed} провалено | Всего: {len(results)}')

if failed:
    sys.exit(1)
else:
    sys.exit(0)
