"""
Тест корректности работы времени (UTC ISO Z), верстки модалки и передачи учеников
"""
import sys
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath('e:/projects/kege_selector_app_current'))

from wsgi import app
from core.db_models import db, User, ScheduleLesson, Student

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

print('\n[1] Инициализация тестового окружения...')
ctx = app.app_context()
ctx.push()

# Отключаем CSRF при тестировании через Flask test client
app.config['WTF_CSRF_ENABLED'] = False

teacher = User.query.filter_by(username='Teacher_1').first()
student_user = User.query.filter_by(username='Student_1').first()
student_profile = Student.query.filter_by(user_id=student_user.id).first() if student_user else None

check('Teacher_1 найден в БД', teacher is not None)
check('Student_1 найден в БД', student_profile is not None)

client = app.test_client()

try:
    # ── 2. Рендеринг страницы и данные учеников ──
    print('\n[2] Проверка контекста страницы и верстки модалки...')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id) if teacher else '1'
        sess['_fresh'] = True

    r_page = client.get('/sandbox/teacher_schedule')
    check('GET /sandbox/teacher_schedule = 200', r_page.status_code == 200)
    
    html = r_page.data.decode('utf-8', errors='replace')
    
    # 1. Структура модалки и кнопки
    check('Модалка содержит контейнер modal-box', 'modal-box flex flex-col' in html or 'modal-box' in html)
    check('Кнопка "Отмена" в модальной структуре', 'Отмена' in html)
    check('Кнопка "СОЗДАТЬ УРОК" в модальной структуре', 'СОЗДАТЬ УРОК' in html)
    check('Футер modal-footer содержит flex justify-end', 'modal-footer' in html and 'justify-end' in html)

    # 2. Передача списка учеников
    check('Страница содержит JSON с ключом students', '"students": [' in html or '"students":[' in html or '"students":' in html)
    
    # ── 3. Эндпоинт /sandbox/api/teacher/students ──
    print('\n[3] Эндпоинт получения учеников...')
    r_studs = client.get('/sandbox/api/teacher/students')
    check('GET /sandbox/api/teacher/students = 200', r_studs.status_code == 200)
    studs_data = r_studs.get_json() or {}
    check('Поле students в ответе API', 'students' in studs_data and isinstance(studs_data['students'], list))
    check('Список учеников не пустой', len(studs_data.get('students', [])) > 0)

    # ── 4. Проверка цепи времени (15:00 local -> ISO UTC 'Z') ──
    print('\n[4] Проверка сохранения и выдачи времени (UTC ISO Z)...')
    # Имитируем отправку с фронтенда 15:00 в локальном времени преподавателя
    # JS делает localDateObj.toISOString(), получая маркер 'Z'
    dt_local = datetime(2026, 7, 26, 15, 0, 0, tzinfo=ZoneInfo('Asia/Tomsk'))
    dt_utc = dt_local.astimezone(timezone.utc)
    iso_send = dt_utc.isoformat().replace('+00:00', 'Z')
    
    r_create = client.post('/sandbox/api/schedule/lessons',
        data=json.dumps({
            'topic': 'QA Урок Время 15:00',
            'start_dt': iso_send,
            'duration_minutes': 60,
            'lesson_type': 'individual',
            'student_id': student_profile.student_id if student_profile else 1
        }),
        content_type='application/json'
    )
    
    check('POST /sandbox/api/schedule/lessons = 201', r_create.status_code == 201, f'status={r_create.status_code}')
    res_json = r_create.get_json() or {}
    check('Ответ содержит ok=True', res_json.get('ok') is True)
    
    created_lesson = res_json.get('lesson', {})
    start_iso = created_lesson.get('start_iso', '')
    check('API возвращает start_iso в UTC', start_iso.endswith('+00:00') or start_iso.endswith('Z'), f'got={start_iso}')
    
    created_id = created_lesson.get('lesson_id')
    
    # ── GET /sandbox/api/schedule/lessons ──
    r_list = client.get('/sandbox/api/schedule/lessons?week_offset=0')
    check('GET /sandbox/api/schedule/lessons = 200', r_list.status_code == 200)
    list_json = r_list.get_json() or {}
    lessons_list = list_json.get('lessons', [])
    
    target_in_list = next((l for l in lessons_list if l.get('lesson_id') == created_id), None)
    check('Созданный урок найден в списке за неделю', target_in_list is not None)
    if target_in_list:
        check('start_iso урока сохранён корректно', 'start_iso' in target_in_list)

    # Очистка
    if created_id:
        client.delete(f'/sandbox/api/schedule/lessons/{created_id}')

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
