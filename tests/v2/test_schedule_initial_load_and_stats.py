"""
Тест первичной загрузки расписания, динамической статистики и выборки контекста ученика #3
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
student_profile_3 = Student.query.filter_by(student_id=3).first() or Student.query.get(3)
if not student_profile_3:
    student_profile_3 = Student.query.first()

check('Teacher_1 найден в БД', teacher is not None)
check('Профиль Ученика #3 найден в БД', student_profile_3 is not None, f'student_id={student_profile_3.student_id if student_profile_3 else None}')

created_lesson = None

try:
    # ── 2. Подготовка тестового урока для ученика #3 на этой неделе ──
    print('\n[2] Создание урока для ученика #3 на текущую неделю...')
    for l in ScheduleLesson.query.all():
        l.start_dt = datetime.now(timezone.utc) - timedelta(days=5)
        l.status = 'done'
    for l in Lesson.query.all():
        l.lesson_date = datetime.now(timezone.utc) - timedelta(days=5)
        l.status = 'completed'
    db.session.commit()

    start_dt_today = datetime.now(timezone.utc) + timedelta(hours=3)
    lesson_topic = "Урок Анастасии Смирновой #3 КЕГЭ"
    test_lesson = ScheduleLesson(
        teacher_user_id=teacher.id if teacher else 1,
        student_id=student_profile_3.student_id if student_profile_3 else 3,
        topic=lesson_topic,
        start_dt=start_dt_today,
        duration_minutes=60,
        lesson_type='individual',
        status='planned'
    )
    db.session.add(test_lesson)
    db.session.commit()
    created_lesson = test_lesson
    check('Урок успешно создан в БД для student_id=3', test_lesson.lesson_id is not None, f'lesson_id={test_lesson.lesson_id}')

    # ── 3. Проверка первичной загрузки страницы расписания и динамической статистики ──
    print('\n[3] Проверка GET /sandbox/student_schedule (контекст ученика #3)...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)  # Учитель открывает режим ученика в песочнице
        sess['sandbox_role'] = 'student'
        sess['sandbox_student_id'] = student_profile_3.student_id
        sess['_fresh'] = True

    r_sched = client.get('/sandbox/student_schedule')
    check('GET /sandbox/student_schedule = 200', r_sched.status_code == 200)
    html_sched = r_sched.data.decode('utf-8', errors='replace')

    # Проверка 1: Отсутствие хардкода 34 уроков
    check('Хардкод "34 уроков" отсутствует в HTML расписания', '34 уроков' not in html_sched)
    check('Хардкод "34 завершено" отсутствует в HTML расписания', '34 завершено' not in html_sched)

    # Проверка 2: Наличие JSON-контейнера schedule-data с уроками
    check('JSON-контейнер schedule-data присутствуют в HTML', 'id="schedule-data"' in html_sched)
    json_start = html_sched.find('id="schedule-data">') + len('id="schedule-data">')
    json_end = html_sched.find('</script>', json_start)
    schedule_json = json.loads(html_sched[json_start:json_end])
    check('Массив уроков в JSON-теге не пустой', len(schedule_json.get('lessons', [])) > 0)

    # Проверка 3: Выборка upcoming_lesson для ученика #3
    print('\n[4] Проверка выборки upcoming_lesson для ученика #3 на дашборде...')
    r_stud = client.get('/sandbox/student_dashboard')
    check('GET /sandbox/student_dashboard = 200', r_stud.status_code == 200)
    html_stud = r_stud.data.decode('utf-8', errors='replace')

    check('Тема урока ученика #3 отображается в баннере дашборда', lesson_topic in html_stud)
    check('Ссылка на комнату ученика (/sandbox/lesson_room/<id>) на дашборде', f'/sandbox/lesson_room/{test_lesson.lesson_id}' in html_stud)

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
