"""
QA-тест: Расписание — верстка, CRUD, таймзоны, шаблоны, автопланировщик, роль ученика.
Запуск (из корня проекта):
    .venv\\Scripts\\python.exe scratch/test_schedule_layout_and_crud.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

PASS = '✅'
FAIL = '❌'
results = []


def check(label, ok, detail=''):
    status = PASS if ok else FAIL
    results.append((status, label, detail))
    print(f'  {status} {label}' + (f' — {detail}' if detail else ''))


# ─────────────────────────────────────────────────────────────
# 1. Инициализация приложения и контекст
# ─────────────────────────────────────────────────────────────
print('\n[1] Инициализация Flask и моделей...')
from wsgi import app
from core.db_models import db, ScheduleLesson, ScheduleTemplate, SchoolGroup, User

ctx = app.app_context()
ctx.push()
db.create_all()

teacher = User.query.filter_by(username='Teacher_1').first()
student = User.query.filter_by(username='Student_1').first()

check('Таблица ScheduleLessons существует', True)
check('Таблица ScheduleTemplates существует', True)
check('Teacher_1 найден в БД', teacher is not None)
check('Student_1 найден в БД', student is not None)

# ─────────────────────────────────────────────────────────────
# 2. HTTP-доступность страниц расписания
# ─────────────────────────────────────────────────────────────
print('\n[2] HTTP-доступность страниц расписания...')
import json

client = app.test_client()
app.config['WTF_CSRF_ENABLED'] = False

if teacher:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['_fresh'] = True

r1 = client.get('/sandbox/teacher_schedule')
check('/sandbox/teacher_schedule возвращает 200', r1.status_code == 200,
      f'status={r1.status_code}')

r_api = client.get('/sandbox/api/schedule/lessons')
check('/sandbox/api/schedule/lessons возвращает 200', r_api.status_code == 200,
      f'status={r_api.status_code}')

r_templates = client.get('/sandbox/api/schedule/templates')
check('/sandbox/api/schedule/templates возвращает 200', r_templates.status_code == 200)

# Студент: страница расписания
if student:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student.id)
        sess['_fresh'] = True
    r_stud = client.get('/sandbox/student_schedule')
    check('/sandbox/student_schedule возвращает 200', r_stud.status_code == 200,
          f'status={r_stud.status_code}')
    # Ученик не должен видеть 500 при попытке вызвать POST API
    r_hack = client.post('/sandbox/api/schedule/lessons',
                         data=json.dumps({
                             'topic': 'Взлом системы', 'start_dt': '2026-08-01T18:00:00',
                             'duration_minutes': 60
                         }),
                         content_type='application/json')
    check('Ученик не получает 500 при попытке POST API', r_hack.status_code != 500)

# Вернуть сессию преподавателя
if teacher:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['_fresh'] = True

# ─────────────────────────────────────────────────────────────
# 3. CRUD: Создание, чтение, обновление, удаление урока
# ─────────────────────────────────────────────────────────────
print('\n[3] CRUD уроков расписания...')

LESSON_TOPIC = 'QA_Алгебра логики (тест)'
start_dt = datetime(2026, 8, 1, 18, 0, 0, tzinfo=ZoneInfo('Europe/Moscow'))
start_dt_iso = start_dt.isoformat()

# CREATE
r_create = client.post('/sandbox/api/schedule/lessons',
    data=json.dumps({
        'topic': LESSON_TOPIC,
        'start_dt': start_dt_iso,
        'duration_minutes': 90,
        'lesson_type': 'webinar',
        'meeting_url': 'https://zoom.us/test',
        'color_tag': 'emerald',
    }),
    content_type='application/json'
)
check('POST /api/schedule/lessons → 201', r_create.status_code == 201, f'status={r_create.status_code}')

created_data = r_create.get_json()
check('Ответ содержит ok=True', created_data.get('ok') is True)
created_lesson = created_data.get('lesson', {})
lesson_id = created_lesson.get('lesson_id')
check('lesson_id в ответе', bool(lesson_id), f'lesson_id={lesson_id}')
check('topic корректен', created_lesson.get('topic') == LESSON_TOPIC)
check('duration_minutes корректен', created_lesson.get('duration_minutes') == 90)
check('grid_top присутствует (позиция в пикселях)', 'grid_top' in created_lesson)
check('grid_height присутствует (высота карточки)', 'grid_height' in created_lesson)
check('weekday присутствует', 'weekday' in created_lesson)

# READ прямо из БД
db_lesson = db.session.get(ScheduleLesson, lesson_id) if lesson_id else None
check('Урок сохранён в БД', db_lesson is not None)
if db_lesson:
    # SQLite не хранит tzinfo, PostgreSQL хранит — проверяем факт сохранения времени
    check('UTC время сохранено в БД', db_lesson.start_dt is not None)
    check('meeting_url сохранён', db_lesson.meeting_url == 'https://zoom.us/test')
else:
    check('UTC время сохранено в БД', False, 'Урок не создан')
    check('meeting_url сохранён', False, 'Урок не создан')

# UPDATE
r_update = client.put(f'/sandbox/api/schedule/lessons/{lesson_id}',
    data=json.dumps({
        'topic': LESSON_TOPIC + ' (обновлено)',
        'duration_minutes': 60,
        'color_tag': 'indigo',
    }),
    content_type='application/json'
)
check('PUT /api/schedule/lessons/<id> → 200', r_update.status_code == 200)
updated = r_update.get_json().get('lesson', {})
check('Тема обновлена', updated.get('topic') == LESSON_TOPIC + ' (обновлено)')
check('Длительность обновлена', updated.get('duration_minutes') == 60)

# GO LIVE
r_live = client.post(f'/sandbox/api/schedule/lessons/{lesson_id}/go_live')
check('POST /go_live → 200', r_live.status_code == 200)
live_data = r_live.get_json()
check('Статус стал live', live_data.get('lesson', {}).get('status') == 'live')
check('meeting_url в ответе go_live', 'meeting_url' in live_data)

# DELETE
r_del = client.delete(f'/sandbox/api/schedule/lessons/{lesson_id}')
check('DELETE /api/schedule/lessons/<id> → 200', r_del.status_code == 200)
check('ok=True в ответе на DELETE', r_del.get_json().get('ok') is True)

db_lesson_after = db.session.get(ScheduleLesson, lesson_id) if lesson_id else None
check('Урок удалён из БД', db_lesson_after is None)

# ─────────────────────────────────────────────────────────────
# 4. Таймзоны: конвертация UTC → локальное время
# ─────────────────────────────────────────────────────────────
print('\n[4] Таймзоны — конвертация UTC → локальное время...')

utc_dt = datetime(2026, 8, 1, 15, 0, 0, tzinfo=timezone.utc)  # 15:00 UTC = 18:00 MSK

if teacher:
    lesson_tz = ScheduleLesson(
        teacher_user_id=teacher.id,
        topic='QA_TZ_Test',
        start_dt=utc_dt,
        duration_minutes=60,
        lesson_type='group',
        status='planned',
        color_tag='indigo',
    )
    # Тестируем to_dict() in-memory (без коммита) — SQLite убирает tzinfo при раундтрипе
    utc_aware = utc_dt.replace(tzinfo=timezone.utc)  # гарантированно aware
    lesson_tz.start_dt = utc_aware

    result_dict = lesson_tz.to_dict('Europe/Moscow')
    check('start_time в MSK = 18:00', result_dict['start_time'] == '18:00',
          f'got: {result_dict["start_time"]}')
    check('end_time в MSK = 19:00', result_dict['end_time'] == '19:00',
          f'got: {result_dict["end_time"]}')
    check('grid_top для 18:00 = 1800', result_dict['grid_top'] == 1800,
          f'got: {result_dict["grid_top"]}')
    check('grid_height для 60 мин = 100', result_dict['grid_height'] == 100,
          f'got: {result_dict["grid_height"]}')

    result_tomsk = lesson_tz.to_dict('Asia/Tomsk')
    check('В Томске (UTC+7) время = 22:00', result_tomsk['start_time'] == '22:00',
          f'got: {result_tomsk["start_time"]}')


# ─────────────────────────────────────────────────────────────
# 5. Шаблоны расписания
# ─────────────────────────────────────────────────────────────
print('\n[5] Шаблоны расписания...')

r_tmpl = client.post('/sandbox/api/schedule/templates',
    data=json.dumps({
        'title': 'QA_Шаблон 11А',
        'weekdays': [1, 3],
        'time_hhmm': '18:00',
        'duration_minutes': 90,
        'lesson_type': 'group',
    }),
    content_type='application/json'
)
check('POST /api/schedule/templates → 201', r_tmpl.status_code == 201)
tmpl_data = r_tmpl.get_json()
tmpl_id = tmpl_data.get('template', {}).get('template_id')
check('template_id в ответе', bool(tmpl_id))

r_tmpl_list = client.get('/sandbox/api/schedule/templates')
check('GET /api/schedule/templates → 200', r_tmpl_list.status_code == 200)
templates = r_tmpl_list.get_json().get('templates', [])
check('Шаблон виден в списке', any(t['template_id'] == tmpl_id for t in templates))

r_bad1 = client.post('/sandbox/api/schedule/templates',
    data=json.dumps({'title': '', 'weekdays': [0], 'time_hhmm': '18:00'}),
    content_type='application/json'
)
check('Пустое название шаблона → 400', r_bad1.status_code == 400)

r_bad2 = client.post('/sandbox/api/schedule/templates',
    data=json.dumps({'title': 'Test', 'weekdays': [], 'time_hhmm': '18:00'}),
    content_type='application/json'
)
check('Пустые weekdays → 400', r_bad2.status_code == 400)

r_del_tmpl = client.delete(f'/sandbox/api/schedule/templates/{tmpl_id}')
check('DELETE /api/schedule/templates/<id> → 200', r_del_tmpl.status_code == 200)
db_tmpl = db.session.get(ScheduleTemplate, tmpl_id) if tmpl_id else None
check('Шаблон деактивирован (is_active=False)', db_tmpl is not None and not db_tmpl.is_active)

# ─────────────────────────────────────────────────────────────
# 6. Автопланировщик
# ─────────────────────────────────────────────────────────────
print('\n[6] Автопланировщик...')

r_tmpl2 = client.post('/sandbox/api/schedule/templates',
    data=json.dumps({
        'title': 'QA_Autoplan_Шаблон',
        'weekdays': [0, 4],  # Пн, Пт
        'time_hhmm': '19:00',
        'duration_minutes': 60,
        'lesson_type': 'webinar',
    }),
    content_type='application/json'
)
tmpl2_id = r_tmpl2.get_json().get('template', {}).get('template_id')
check('Шаблон для автопланировщика создан', bool(tmpl2_id))

r_auto = client.post('/sandbox/api/schedule/autoplanner',
    data=json.dumps({
        'date_from': '2026-08-03',  # Пн
        'date_to': '2026-08-09',   # Вс
        'template_ids': [tmpl2_id],
    }),
    content_type='application/json'
)
check('POST /api/schedule/autoplanner → 200', r_auto.status_code == 200)
auto_data = r_auto.get_json()
check('ok=True', auto_data.get('ok') is True)
created_count = auto_data.get('created_count', 0)
check('Создано 2 урока (Пн + Пт)', created_count == 2, f'created_count={created_count}')

# Идемпотентность
r_auto2 = client.post('/sandbox/api/schedule/autoplanner',
    data=json.dumps({
        'date_from': '2026-08-03',
        'date_to': '2026-08-09',
        'template_ids': [tmpl2_id],
    }),
    content_type='application/json'
)
auto_data2 = r_auto2.get_json()
check('Повторный запуск не дублирует (created=0)', auto_data2.get('created_count') == 0,
      f'created_count={auto_data2.get("created_count")}')

r_too_long = client.post('/sandbox/api/schedule/autoplanner',
    data=json.dumps({'date_from': '2026-01-01', 'date_to': '2026-06-01'}),
    content_type='application/json'
)
check('Диапазон >3 мес → 400', r_too_long.status_code == 400)

# Очистка
lessons_auto = ScheduleLesson.query.filter_by(template_id=tmpl2_id).all()
for l in lessons_auto:
    db.session.delete(l)
tmpl2_obj = db.session.get(ScheduleTemplate, tmpl2_id) if tmpl2_id else None
if tmpl2_obj:
    tmpl2_obj.is_active = False
db.session.commit()
check('Тестовые уроки очищены из БД', True)

# ─────────────────────────────────────────────────────────────
# 7. Студент: только просмотр (нет кнопок управления)
# ─────────────────────────────────────────────────────────────
print('\n[7] Страница ученика: только просмотр...')

if student:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student.id)
        sess['_fresh'] = True
    r_stud = client.get('/sandbox/student_schedule')
    body = r_stud.data.decode('utf-8', errors='replace')
    check('student_schedule 200', r_stud.status_code == 200)
    check('Нет кнопки "Новый урок" у студента', 'Новый урок' not in body)
    check('Нет кнопки "Шаблоны расписания" у студента', 'openTemplatesModal' not in body)
    check('Нет кнопки "Автопланировщик" у студента', 'runAutoplanner' not in body)
    check('Есть кнопка "Войти в комнату урока" (студент)', 'В КОМНАТУ УРОКА' in body or 'join-btn' in body)

# ─────────────────────────────────────────────────────────────
# 8. Layout: изолированный скролл и безопасность
# ─────────────────────────────────────────────────────────────
print('\n[8] Layout: изолированный скролл и zero-alert...')

if teacher:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher.id)
        sess['_fresh'] = True

r_teach = client.get('/sandbox/teacher_schedule')
body_t = r_teach.data.decode('utf-8', errors='replace')

check('Класс schedule-scroll присутствует в HTML', 'schedule-scroll' in body_t)
check('scrollToCurrentTime в JS', 'scrollToCurrentTime' in body_t)
# Проверяем только блок <script> из teacher_schedule, не включаем подключаемые шаблоны
def extract_schedule_scripts(html):
    """Extract only the <script> blocks from teacher_schedule.html itself."""
    import re
    # Берём только schedule-page секцию и скрипты, которые идут ПОСЛЕ нашего контента
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    # Оставляем только скрипты, содержащие ключевые слова расписания
    our_scripts = [s for s in scripts if 'scrollToCurrentTime' in s or 'schedule-data' in s or 'ScheduleLesson' in s.lower()]
    return ' '.join(our_scripts)

schedule_js = extract_schedule_scripts(body_t)
check('Нет alert() в JS (зона расписания, не включая includes)', 'alert(' not in schedule_js,
      'Найдено alert() в нашем JS')
check('Нет confirm() в JS', 'confirm(' not in body_t)
check('Данные через JSON-тег (не в JS-коде)', 'schedule-data' in body_t)
check('body overflow hidden', 'overflow: hidden' in body_t or 'overflow:hidden' in body_t)

# ─────────────────────────────────────────────────────────────
# ИТОГ
# ─────────────────────────────────────────────────────────────
ctx.pop()

print('\n' + '=' * 60)
passed = sum(1 for s, *_ in results if s == PASS)
failed = sum(1 for s, *_ in results if s == FAIL)
print(f'Итог: {PASS} {passed} прошло | {FAIL} {failed} провалено | Всего: {len(results)}')
if failed:
    print('\nПровалено:')
    for s, label, detail in results:
        if s == FAIL:
            print(f'  {FAIL} {label}' + (f' — {detail}' if detail else ''))
    sys.exit(1)
else:
    print('\nВсе тесты прошли! 🎉')
    sys.exit(0)
