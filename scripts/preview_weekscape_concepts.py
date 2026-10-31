"""
BooStudy / ORISTERA — Student Schedule Sprint 1.5
Exploration Runner for 3 Weekscape Concepts:
  - Concept A: Adaptive Weekboard
  - Concept B: Editorial Weekscape
  - Concept C: Panoramic Horizon & Dynamic Workspace
Renders each concept with identical synthetic data and captures 1440x900 and 1920x1080 screenshots.
"""
import os
import sys
import time
import json
import threading
from datetime import datetime, timedelta, timezone as dt_timezone
from werkzeug.serving import make_server

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

ISOLATED_DB_PATH = '/tmp/test_schedule_preview.db'
if os.path.exists(ISOLATED_DB_PATH):
    try:
        os.remove(ISOLATED_DB_PATH)
    except Exception:
        pass

os.environ['DATABASE_URL'] = f'sqlite:///{ISOLATED_DB_PATH}'
os.environ['SQLITE_DB_PATH'] = ISOLATED_DB_PATH
os.environ['BOOSTUDY_SKIP_DATABASE_BOOTSTRAP'] = '1'
os.environ['BOOSTUDY_BACKGROUND_WORKERS_ENABLED'] = '0'
os.environ['SECRET_KEY'] = 'test-e2e-secret-key-sprint-1-5'
os.environ['WTF_CSRF_ENABLED'] = 'false'

from app import create_app, db
from core.db_models import User, Student, Lesson, Assignment, Submission
from werkzeug.security import generate_password_hash
from flask import jsonify, request, session, render_template_string
from flask_login import login_user

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{ISOLATED_DB_PATH}'

@app.route('/api/internal/test_login', methods=['POST'])
def test_login():
    data = request.get_json(force=True) or {}
    user_id = data.get('user_id')
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    login_user(user)
    session['_user_id'] = str(user.id)
    session['_fresh'] = True
    session['sandbox_role'] = 'student'
    return jsonify({'status': 'ok', 'user_id': user.id, 'role': user.role})


def seed_database():
    with app.app_context():
        db.create_all()

        mentor = User(id=99, username='e2e_mentor', email='m@test.com', password_hash=generate_password_hash('p'), role='teacher', full_name='Виктор Сергеевич (Преподаватель)')
        db.session.add(mentor)
        db.session.commit()

        u_std = User(id=102, username='e2e_std', email='std@test.com', password_hash=generate_password_hash('p'), role='student', full_name='София Стандартная')
        db.session.add(u_std)
        db.session.commit()
        st_std = Student(student_id=102, user_id=102, name='София Стандартная', mentor_id=99, is_active=True)
        db.session.add(st_std)
        db.session.commit()
        print('Seed data ready.')


class ServerThread(threading.Thread):
    def __init__(self, port=5558):
        super().__init__(daemon=True)
        self.port = port
        self.server = make_server('127.0.0.1', port, app.wsgi_app, threaded=True)

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def get_mock_data():
    """Returns clean, robust synthetic schedule_page_data for testing concepts."""
    return {
        'week_label': '27 октября — 2 ноября 2026',
        'teacher_name': 'Виктор Сергеевич',
        'student_notes_general': '«Обрати особое внимание на динамическое программирование — это ключевая тема ЕГЭ №27!»',
        'default_selected_day_index': 2, # Среда
        'weekdays': [
            {
                'name': 'Пн', 'full_name': 'Понедельник', 'date': 27, 'month_name': 'октября',
                'is_today': False, 'is_past': True, 'is_completed': True, 'day_index': 0, 'events_count': 2,
                'events': [
                    {'id': 'l1', 'type': 'lesson', 'title': 'Рекурсивные алгоритмы и стек вызовов', 'time_str': '14:00 – 15:00', 'badge': 'Проведено', 'color': 'emerald', 'icon': 'ph-check-circle', 'status': 'completed', 'action_label': 'Материалы урока →'},
                    {'id': 'h1', 'type': 'homework', 'title': 'ДЗ 1: Рекурсия и Фибоначчи', 'time_str': 'Сдано вовремя', 'badge': 'ДЗ сдано', 'color': 'emerald', 'icon': 'ph-file-text', 'status': 'SUBMITTED', 'action_label': 'Посмотреть решение →'}
                ]
            },
            {
                'name': 'Вт', 'full_name': 'Вторник', 'date': 28, 'month_name': 'октября',
                'is_today': False, 'is_past': True, 'is_completed': False, 'day_index': 1, 'events_count': 0,
                'events': [{'id': 'f1', 'type': 'free', 'title': 'Самостоятельное закрепление', 'time_str': 'Свободный день', 'badge': 'Практика', 'color': 'slate', 'icon': 'ph-sparkle', 'status': 'free', 'action_label': 'Открыть теорию →'}]
            },
            {
                'name': 'Ср', 'full_name': 'Среда', 'date': 29, 'month_name': 'октября',
                'is_today': True, 'is_past': False, 'is_completed': False, 'day_index': 2, 'events_count': 2,
                'events': [
                    {'id': 'l2', 'type': 'lesson', 'title': 'Динамическое программирование: одномерные таблицы', 'time_str': '16:00 – 17:30', 'badge': 'Запланировано', 'color': 'indigo', 'icon': 'ph-laptop', 'status': 'planned', 'action_label': 'Войти в урок →'},
                    {'id': 'h2', 'type': 'homework', 'title': 'ДЗ 2: Кузнечик и динамика', 'time_str': 'До 20:00', 'badge': 'В процессе', 'color': 'amber', 'icon': 'ph-file-text', 'status': 'IN_PROGRESS', 'action_label': 'Продолжить выполнение →'}
                ]
            },
            {
                'name': 'Чт', 'full_name': 'Четверг', 'date': 30, 'month_name': 'октября',
                'is_today': False, 'is_past': False, 'is_completed': False, 'day_index': 3, 'events_count': 0,
                'events': [{'id': 'f2', 'type': 'free', 'title': 'День повторения', 'time_str': 'Свободный день', 'badge': 'Отдых', 'color': 'slate', 'icon': 'ph-sparkle', 'status': 'free', 'action_label': 'Открыть теорию →'}]
            },
            {
                'name': 'Пт', 'full_name': 'Пятница', 'date': 31, 'month_name': 'октября',
                'is_today': False, 'is_past': False, 'is_completed': False, 'day_index': 4, 'events_count': 1,
                'events': [
                    {'id': 'l3', 'type': 'lesson', 'title': 'Теория графов и матрицы смежности', 'time_str': '17:00 – 18:00', 'badge': 'Отменено', 'color': 'slate', 'icon': 'ph-x-circle', 'status': 'cancelled', 'action_label': 'Перенести занятие →'}
                ]
            },
            {
                'name': 'Сб', 'full_name': 'Суббота', 'date': 1, 'month_name': 'ноября',
                'is_today': False, 'is_past': False, 'is_completed': False, 'day_index': 5, 'events_count': 1,
                'events': [
                    {'id': 'h3', 'type': 'homework', 'title': 'ДЗ 3: Поиск путей в графе', 'time_str': 'До 18:00', 'badge': 'На доработке', 'color': 'rose', 'icon': 'ph-file-text', 'status': 'RETURNED', 'action_label': 'Доработать задание →'}
                ]
            },
            {
                'name': 'Вс', 'full_name': 'Воскресенье', 'date': 2, 'month_name': 'ноября',
                'is_today': False, 'is_past': False, 'is_completed': False, 'day_index': 6, 'events_count': 0,
                'events': [{'id': 'f3', 'type': 'free', 'title': 'Выходной • Время для отдыха', 'time_str': 'Весь день', 'badge': 'Отдых', 'color': 'amber', 'icon': 'ph-sun', 'status': 'free', 'action_label': 'Банк заданий →'}]
            }
        ],
        'useful_materials': [
            {'title': 'Динамическое программирование — шпаргалка', 'pages': 'Конспект • 4 стр.'},
            {'title': 'Типовые шаблоны решения задачи №27', 'pages': 'PDF • База кода'}
        ],
        'weekly_stats': {
            'conducted': 1, 'planned': 1, 'homework': 3, 'percent': 50
        }
    }


# Template A: Adaptive Weekboard
TEMPLATE_CONCEPT_A = """
{% extends "sandbox/layout_student.html" %}
{% block sandbox_content %}
<div class="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
  <!-- Concept Badge -->
  <div class="flex items-center justify-between">
    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-700 text-xs font-black uppercase tracking-wider">
      <span>Концепция A</span> &bull; <span>Adaptive Weekboard</span>
    </div>
    <span class="text-xs text-slate-500 font-bold">Синтетический прототип №1</span>
  </div>

  <!-- Header -->
  <div class="flex items-center justify-between flex-wrap gap-4 bg-white p-5 rounded-3xl border border-slate-200/80 shadow-2xs">
    <div class="flex items-center gap-3">
      <div class="w-11 h-11 rounded-2xl bg-indigo-600 text-white flex items-center justify-center text-xl font-bold shadow-md shadow-indigo-600/20">
        <i class="ph-bold ph-calendar-blank"></i>
      </div>
      <div>
        <h1 class="text-xl font-black text-slate-900 tracking-tight font-display">Недельная доска (Weekboard)</h1>
        <p class="text-xs text-slate-500 font-medium">Все 7 дней в единой связной интерактивной плоскости</p>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1 bg-slate-50 border border-slate-200 rounded-xl p-1 shadow-2xs">
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-white flex items-center justify-center font-bold cursor-pointer">&larr;</button>
        <span class="px-3 py-1 text-xs font-black text-slate-800">{{ data.week_label }}</span>
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-white flex items-center justify-center font-bold cursor-pointer">&rarr;</button>
      </div>
      <button class="px-3 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-bold text-slate-700 shadow-2xs cursor-pointer flex items-center gap-1.5">
        <i class="ph-bold ph-crosshair text-indigo-600"></i>
        <span>Сегодня</span>
      </button>
    </div>
  </div>

  <!-- Weekboard Shelf (7 Adaptive Connected Columns) -->
  <div class="bg-white rounded-3xl border border-slate-200/90 p-4 shadow-sm">
    <div class="flex items-center justify-between mb-3 px-1 text-xs">
      <span class="font-black uppercase tracking-wider text-slate-400 text-[11px]">Горизонт учебной недели</span>
      <span class="text-slate-400 font-medium text-[11px]">Кликните на день для раскрытия инспектора</span>
    </div>
    <div class="grid grid-cols-7 gap-3">
      {% for d in data.weekdays %}
      <div class="rounded-2xl border p-3 transition flex flex-col justify-between min-h-[145px] cursor-pointer {% if d.day_index == 2 %}border-indigo-600 bg-indigo-50/40 shadow-md ring-2 ring-indigo-500/20{% else %}border-slate-200 bg-white hover:border-slate-300{% endif %}">
        <div class="flex items-center justify-between pb-2 border-b border-slate-100">
          <span class="text-xs font-black {% if d.day_index == 2 %}text-indigo-600{% else %}text-slate-800{% endif %}">{{ d.name }}, {{ d.date }}</span>
          {% if d.is_completed %}
          <i class="ph-bold ph-check text-emerald-600 text-xs"></i>
          {% elif d.is_today %}
          <span class="w-2 h-2 rounded-full bg-indigo-600 animate-pulse"></span>
          {% endif %}
        </div>
        <div class="py-2 space-y-1.5 my-auto">
          {% for ev in d.events %}
            <div class="px-2 py-1 rounded-lg text-[10px] font-bold truncate {% if ev.type == 'lesson' and ev.status == 'completed' %}bg-emerald-100 text-emerald-800{% elif ev.type == 'lesson' %}bg-indigo-100 text-indigo-800{% elif ev.type == 'homework' %}bg-amber-100 text-amber-800{% else %}bg-slate-100 text-slate-500{% endif %}">
              {{ ev.title }}
            </div>
          {% endfor %}
        </div>
        <div class="text-[10px] font-bold text-slate-400 pt-1.5 border-t border-slate-100 flex items-center justify-between">
          <span class="truncate">{{ d.events[0].time_str }}</span>
          {% if d.events_count > 1 %}
          <span class="text-indigo-600 font-black">+{{ d.events_count - 1 }}</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Selected Day Inspector Workspace -->
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
    <div class="lg:col-span-8 bg-white rounded-3xl border border-slate-200/90 p-6 shadow-sm space-y-4">
      <div class="flex items-center justify-between pb-3 border-b border-slate-100">
        <div>
          <span class="text-xs font-black text-indigo-600 uppercase tracking-wider">Инспектор дня</span>
          <h2 class="text-xl font-black text-slate-900">Среда, 29 октября &bull; Сегодня</h2>
        </div>
        <span class="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs font-bold border border-indigo-100">2 события</span>
      </div>

      <!-- Events in Day -->
      <div class="space-y-3">
        <div class="p-5 rounded-2xl border border-indigo-100 bg-indigo-50/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-lg bg-indigo-600 text-white text-[11px] font-black">16:00 – 17:30</span>
              <span class="text-xs font-bold text-indigo-700">Индивидуальный урок</span>
            </div>
            <h3 class="text-base font-bold text-slate-900">Динамическое программирование: одномерные таблицы</h3>
            <p class="text-xs text-slate-600 font-medium">Разбор классических задач на поиск оптимальных подпоследовательностей.</p>
          </div>
          <button class="px-5 py-2.5 rounded-xl bg-indigo-600 text-white text-xs font-bold hover:bg-indigo-700 shrink-0 shadow-md shadow-indigo-600/20 cursor-pointer">Войти в урок &rarr;</button>
        </div>

        <div class="p-4 rounded-2xl border border-amber-200 bg-amber-50/30 flex items-center justify-between gap-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 rounded-md bg-amber-600 text-white text-[10px] font-black">До 20:00</span>
              <span class="text-xs font-bold text-amber-800">Домашнее задание</span>
            </div>
            <h3 class="text-sm font-bold text-slate-900">ДЗ 2: Кузнечик и динамика</h3>
          </div>
          <button class="px-4 py-2 rounded-xl border border-slate-200 bg-white text-slate-800 text-xs font-bold hover:bg-slate-50 shrink-0 cursor-pointer">Продолжить &rarr;</button>
        </div>
      </div>
    </div>

    <!-- Right Sidebar Materials & Note -->
    <div class="lg:col-span-4 space-y-4">
      <div class="bg-white rounded-3xl border border-slate-200/90 p-5 shadow-sm space-y-3">
        <h4 class="text-xs font-black uppercase text-slate-400 tracking-wider">Материалы дня</h4>
        <div class="space-y-2">
          {% for m in data.useful_materials %}
          <div class="p-3 rounded-2xl border border-slate-100 bg-slate-50/60 flex items-center justify-between">
            <span class="text-xs font-bold text-slate-800 truncate">{{ m.title }}</span>
            <i class="ph-bold ph-file-text text-slate-400"></i>
          </div>
          {% endfor %}
        </div>
      </div>

      <div class="bg-white rounded-3xl border border-slate-200/90 p-5 shadow-sm space-y-2">
        <div class="flex items-center gap-2 text-indigo-700 text-xs font-bold">
          <i class="ph-bold ph-chalkboard-teacher text-sm"></i>
          <span>Совет преподавателя</span>
        </div>
        <p class="text-xs text-slate-600 leading-relaxed italic">{{ data.student_notes_general }}</p>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""


# Template B: Editorial Weekscape
TEMPLATE_CONCEPT_B = """
{% extends "sandbox/layout_student.html" %}
{% block sandbox_content %}
<div class="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-8">
  <!-- Concept Badge -->
  <div class="flex items-center justify-between">
    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-700 text-xs font-black uppercase tracking-wider">
      <span>Концепция B</span> &bull; <span>Editorial Weekscape</span>
    </div>
    <span class="text-xs text-slate-500 font-bold">Синтетический прототип №2</span>
  </div>

  <!-- Editorial Masthead Header -->
  <div class="border-b border-slate-200 pb-6 flex items-end justify-between flex-wrap gap-4">
    <div>
      <span class="text-xs font-black uppercase tracking-widest text-indigo-600">BooStudy Journal &bull; Учебная неделя</span>
      <h1 class="text-3xl sm:text-4xl font-black text-slate-900 tracking-tight font-display mt-1">
        Среда, 29 октября
      </h1>
      <p class="text-sm text-slate-500 font-medium mt-1">Сегодня главное событие недели — занятие по динамическому программированию</p>
    </div>
    <div class="flex items-center gap-3">
      <div class="text-right hidden sm:block">
        <span class="text-xs font-bold text-slate-400">Период:</span>
        <div class="text-sm font-black text-slate-800">{{ data.week_label }}</div>
      </div>
      <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-xl p-1 shadow-2xs">
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-slate-100 flex items-center justify-center font-bold cursor-pointer">&larr;</button>
        <button class="px-3 py-1 rounded-lg text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-100 cursor-pointer">Сегодня</button>
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-slate-100 flex items-center justify-center font-bold cursor-pointer">&rarr;</button>
      </div>
    </div>
  </div>

  <!-- Flow Strip of Week (Editorial Typography-First Strip) -->
  <div class="flex items-center gap-2.5 overflow-x-auto pb-2 no-scrollbar">
    {% for d in data.weekdays %}
    <div class="flex-1 min-w-[130px] p-3 rounded-2xl transition cursor-pointer {% if d.day_index == 2 %}bg-slate-900 text-white shadow-xl{% elif d.is_past %}bg-slate-100 text-slate-500{% else %}bg-white border border-slate-200 text-slate-800 hover:border-slate-300{% endif %}">
      <div class="flex items-center justify-between text-xs mb-1">
        <span class="font-black uppercase tracking-wider">{{ d.name }}</span>
        <span class="font-bold {% if d.day_index == 2 %}text-indigo-400{% else %}text-slate-400{% endif %}">{{ d.date }}</span>
      </div>
      <div class="text-xs font-bold truncate mt-2">
        {% if d.events_count > 0 %}
          {{ d.events[0].title }}
        {% else %}
          <span class="text-slate-400 font-normal">Отдых</span>
        {% endif %}
      </div>
      <div class="mt-2 flex items-center justify-between text-[10px]">
        <span class="{% if d.day_index == 2 %}text-indigo-300{% else %}text-slate-400{% endif %} font-medium">{{ d.events[0].time_str }}</span>
        {% if d.is_completed %}
        <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
        {% elif d.is_today %}
        <span class="w-2 h-2 rounded-full bg-indigo-400 animate-ping"></span>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- Editorial Asymmetric Workspace (58% Feature / 42% Stream) -->
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
    
    <!-- Left Feature Story: Active Day Centerpiece (7 cols = 58%) -->
    <div class="lg:col-span-7 bg-white rounded-3xl border border-slate-200/90 p-8 shadow-sm space-y-6 relative overflow-hidden">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="px-3 py-1 rounded-full bg-indigo-600 text-white text-xs font-black tracking-wider uppercase">Урок дня</span>
          <span class="text-xs font-bold text-slate-400">16:00 – 17:30 (90 мин)</span>
        </div>
        <span class="text-xs font-bold text-emerald-600 flex items-center gap-1">
          <i class="ph-bold ph-shield-check"></i> Онлайн-комната готова
        </span>
      </div>

      <div class="space-y-3">
        <h2 class="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight leading-tight font-display">
          Динамическое программирование: одномерные таблицы
        </h2>
        <p class="text-sm text-slate-600 leading-relaxed">
          Изучаем метод восходящего решения задач, базовые рекуррентные соотношения и оптимизацию пространственной сложности для заданий ЕГЭ №27.
        </p>
      </div>

      <!-- Teacher Quote & Chip -->
      <div class="p-4 rounded-2xl bg-slate-50 border border-slate-200/80 flex items-start gap-4">
        <div class="w-12 h-12 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-lg shrink-0">
          ВС
        </div>
        <div class="space-y-1">
          <div class="text-xs font-bold text-slate-900">{{ data.teacher_name }}</div>
          <p class="text-xs text-slate-500 italic">{{ data.student_notes_general }}</p>
        </div>
      </div>

      <!-- Action Button -->
      <div class="flex items-center gap-4 pt-2">
        <button class="flex-1 py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 active:translate-y-0.5 transition cursor-pointer flex items-center justify-center gap-2">
          <span>Войти в занятие</span>
          <i class="ph-bold ph-arrow-right"></i>
        </button>
        <button class="px-5 py-3.5 rounded-2xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-bold text-sm shadow-2xs active:translate-y-0.5 transition cursor-pointer">
          Конспект теории
        </button>
      </div>
    </div>

    <!-- Right Stream: Supporting Tasks & Assets (5 cols = 42%) -->
    <div class="lg:col-span-5 space-y-6">
      
      <!-- Homework Card -->
      <div class="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <span class="text-xs font-black uppercase text-slate-400 tracking-wider">Дедлайн сегодня</span>
          <span class="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-[10px] font-bold">До 20:00</span>
        </div>
        <div>
          <h3 class="text-base font-bold text-slate-900">ДЗ 2: Кузнечик и динамика</h3>
          <p class="text-xs text-slate-500 mt-1">Осталось решить 3 задачи из 5</p>
        </div>
        <button class="w-full py-2.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800 text-xs font-bold transition cursor-pointer">
          Продолжить решение &rarr;
        </button>
      </div>

      <!-- Materials -->
      <div class="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-sm space-y-3">
        <span class="text-xs font-black uppercase text-slate-400 tracking-wider">Материалы к уроку</span>
        {% for m in data.useful_materials %}
        <div class="flex items-center justify-between p-3 rounded-2xl border border-slate-100 hover:bg-slate-50 transition">
          <div class="text-xs font-bold text-slate-800 truncate pr-2">{{ m.title }}</div>
          <span class="text-[10px] text-slate-400 shrink-0">{{ m.pages }}</span>
        </div>
        {% endfor %}
      </div>

    </div>

  </div>
</div>
{% endblock %}
"""


# Template C: Panoramic Horizon & Dynamic Workspace
TEMPLATE_CONCEPT_C = """
{% extends "sandbox/layout_student.html" %}
{% block sandbox_content %}
<div class="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
  <!-- Concept Badge -->
  <div class="flex items-center justify-between">
    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-black uppercase tracking-wider">
      <span>Концепция C</span> &bull; <span>Panoramic Horizon & Dynamic Workspace</span>
    </div>
    <span class="text-xs text-slate-500 font-bold">Синтетический прототип №3</span>
  </div>

  <!-- Header Strip -->
  <div class="flex items-center justify-between flex-wrap gap-4">
    <div class="flex items-center gap-3">
      <div class="w-11 h-11 rounded-2xl bg-indigo-600 text-white flex items-center justify-center text-xl font-bold shadow-md shadow-indigo-600/20">
        <i class="ph-bold ph-compass"></i>
      </div>
      <div>
        <div class="flex items-center gap-2">
          <h1 class="text-xl font-black text-slate-900 tracking-tight font-display">BooStudy Weekscape</h1>
          <span class="px-2 py-0.5 rounded-full bg-indigo-50 border border-indigo-100 text-indigo-700 text-[10px] font-black uppercase">Учебное пространство</span>
        </div>
        <p class="text-xs text-slate-500 font-medium">Связанная неделя: события, материалы и ритм обучения</p>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-xl p-1 shadow-2xs">
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-slate-100 flex items-center justify-center font-bold cursor-pointer">&larr;</button>
        <span class="px-3 py-1 text-xs font-black text-slate-800">{{ data.week_label }}</span>
        <button class="w-8 h-8 rounded-lg text-slate-600 hover:bg-slate-100 flex items-center justify-center font-bold cursor-pointer">&rarr;</button>
      </div>
      <button class="px-3 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-bold text-slate-700 shadow-2xs cursor-pointer flex items-center gap-1.5">
        <i class="ph-bold ph-crosshair text-indigo-600"></i>
        <span>Сегодня</span>
      </button>
    </div>
  </div>

  <!-- Panoramic Week Horizon (Continuous Ribbon) -->
  <div class="bg-white rounded-3xl border border-slate-200/90 p-2 shadow-sm">
    <div class="grid grid-cols-7 gap-1.5">
      {% for d in data.weekdays %}
      <div class="rounded-2xl p-3 transition flex flex-col justify-between min-h-[96px] cursor-pointer {% if d.day_index == 2 %}bg-indigo-600 text-white shadow-lg shadow-indigo-600/25 ring-2 ring-indigo-500{% elif d.is_today %}bg-indigo-50/70 border border-indigo-200 text-slate-900{% else %}hover:bg-slate-50 text-slate-800{% endif %}">
        <div class="flex items-center justify-between w-full">
          <span class="text-xs font-black uppercase tracking-wider {% if d.day_index == 2 %}text-indigo-200{% else %}text-slate-400{% endif %}">{{ d.name }}</span>
          <span class="text-sm font-black {% if d.day_index == 2 %}text-white{% else %}text-slate-900{% endif %}">{{ d.date }}</span>
        </div>

        <div class="my-1">
          {% if d.events_count > 0 %}
          <div class="text-[11px] font-bold truncate {% if d.day_index == 2 %}text-white{% else %}text-slate-700{% endif %}">
            {{ d.events[0].title }}
          </div>
          {% else %}
          <div class="text-[11px] font-medium text-slate-400">Отдых</div>
          {% endif %}
        </div>

        <div class="flex items-center justify-between pt-1 border-t {% if d.day_index == 2 %}border-indigo-500/50 text-indigo-200{% else %}border-slate-100 text-slate-400{% endif %} text-[10px] font-bold">
          <span>{{ d.events[0].time_str }}</span>
          {% if d.events_count > 1 %}
          <span class="px-1.5 py-0.2 rounded-md {% if d.day_index == 2 %}bg-white/20 text-white{% else %}bg-indigo-100 text-indigo-700{% endif %} text-[9px]">+{{ d.events_count - 1 }}</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Dynamic Daily Workspace (Adapts naturally to content) -->
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
    
    <!-- Left: Timeline of Day's Events (8 cols = 66%) -->
    <div class="lg:col-span-8 space-y-4">
      <div class="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-sm space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-slate-100">
          <div>
            <span class="text-xs font-black text-indigo-600 uppercase tracking-wider">Фокус дня</span>
            <h2 class="text-xl font-black text-slate-900">Среда, 29 октября &bull; Сегодня</h2>
          </div>
          <span class="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 font-bold text-xs border border-indigo-100">2 события запланировано</span>
        </div>

        <!-- Event 1: Lesson -->
        <div class="p-5 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/50 to-white flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div class="space-y-1.5 max-w-xl">
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-lg bg-indigo-600 text-white text-xs font-black">16:00 – 17:30</span>
              <span class="px-2 py-0.5 rounded-lg bg-indigo-100 text-indigo-800 text-[11px] font-bold">Индивидуальный урок</span>
            </div>
            <h3 class="text-lg font-black text-slate-900 leading-snug">Динамическое программирование: одномерные таблицы</h3>
            <p class="text-xs text-slate-600 leading-relaxed font-medium">Разбор классических задач на поиск оптимальных подпоследовательностей и оптимизация по памяти.</p>
          </div>
          <div class="flex sm:flex-col gap-2 shrink-0">
            <button class="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-600/20 active:translate-y-0.5 transition cursor-pointer">Войти в урок &rarr;</button>
            <button class="px-4 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-bold cursor-pointer">Теория</button>
          </div>
        </div>

        <!-- Event 2: Homework -->
        <div class="p-4 rounded-2xl border border-amber-200 bg-amber-50/30 flex items-center justify-between gap-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 rounded-md bg-amber-600 text-white text-[10px] font-black">До 20:00</span>
              <span class="text-xs font-bold text-amber-800">Домашнее задание &bull; 5 задач</span>
            </div>
            <h4 class="text-sm font-bold text-slate-900">ДЗ 2: Кузнечик и динамика</h4>
          </div>
          <button class="px-4 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-800 text-xs font-bold shrink-0 cursor-pointer">Продолжить &rarr;</button>
        </div>
      </div>
    </div>

    <!-- Right: Contextual Companion & Materials (4 cols = 34%) -->
    <div class="lg:col-span-4 space-y-4">
      <!-- Materials Card -->
      <div class="bg-white rounded-3xl border border-slate-200/90 p-5 shadow-sm space-y-3">
        <h4 class="text-xs font-black uppercase text-slate-400 tracking-wider">Материалы к изучению</h4>
        <div class="space-y-2">
          {% for m in data.useful_materials %}
          <div class="p-3 rounded-2xl border border-slate-100 bg-slate-50/60 flex items-center justify-between hover:bg-slate-100 transition cursor-pointer">
            <div class="space-y-0.5">
              <div class="text-xs font-bold text-slate-800">{{ m.title }}</div>
              <div class="text-[10px] text-slate-400 font-medium">{{ m.pages }}</div>
            </div>
            <i class="ph-bold ph-arrow-up-right text-slate-400 text-xs"></i>
          </div>
          {% endfor %}
        </div>
      </div>

      <!-- Tutor Note Card -->
      <div class="bg-white rounded-3xl border border-slate-200/90 p-5 shadow-sm space-y-3">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-700 font-black text-xs">
            ВС
          </div>
          <div>
            <div class="text-xs font-bold text-slate-900">{{ data.teacher_name }}</div>
            <span class="text-[10px] text-slate-400 font-medium">Преподаватель курса</span>
          </div>
        </div>
        <p class="text-xs text-slate-600 leading-relaxed italic bg-slate-50 p-3 rounded-xl border border-slate-100">
          {{ data.student_notes_general }}
        </p>
      </div>
    </div>

  </div>

  <!-- Weekly Pulse / Insights Bar (Single cohesive bar, no duplicate day grid) -->
  <div class="bg-white rounded-3xl border border-slate-200/90 p-5 shadow-sm grid grid-cols-1 md:grid-cols-3 gap-6 divide-y md:divide-y-0 md:divide-x divide-slate-100">
    <div class="flex items-center gap-4">
      <div class="w-12 h-12 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center text-xl font-bold">
        <i class="ph-bold ph-check-circle"></i>
      </div>
      <div>
        <div class="text-lg font-black text-slate-900">1 из 2 уроков</div>
        <div class="text-xs text-slate-500 font-medium">Проведено на этой неделе (50%)</div>
      </div>
    </div>

    <div class="flex items-center gap-4 md:pl-6 pt-4 md:pt-0">
      <div class="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center text-xl font-bold">
        <i class="ph-bold ph-hourglass-high"></i>
      </div>
      <div>
        <div class="text-lg font-black text-slate-900">3 задания</div>
        <div class="text-xs text-slate-500 font-medium">1 сдано &bull; 1 в работе &bull; 1 на доработке</div>
      </div>
    </div>

    <div class="flex items-center gap-4 md:pl-6 pt-4 md:pt-0">
      <div class="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center text-xl font-bold">
        <i class="ph-bold ph-trend-up"></i>
      </div>
      <div>
        <div class="text-lg font-black text-slate-900">Ритм обучения: 85%</div>
        <div class="text-xs text-slate-500 font-medium">Регулярная подготовка без пропусков</div>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""


@app.route('/preview/concept-a')
def preview_concept_a():
    return render_template_string(TEMPLATE_CONCEPT_A, data=get_mock_data())

@app.route('/preview/concept-b')
def preview_concept_b():
    return render_template_string(TEMPLATE_CONCEPT_B, data=get_mock_data())

@app.route('/preview/concept-c')
def preview_concept_c():
    return render_template_string(TEMPLATE_CONCEPT_C, data=get_mock_data())


def capture_concept_previews():
    seed_database()
    server = ServerThread(port=5558)
    server.start()
    time.sleep(1.0)
    print("Preview server started on port 5558.")

    from playwright.sync_api import sync_playwright

    output_dir = os.path.join(ROOT_DIR, 'docs', 'schedule_sprint1_5_screenshots', 'concepts')
    os.makedirs(output_dir, exist_ok=True)

    concepts = [
        ('concept_a', 'http://127.0.0.1:5558/preview/concept-a'),
        ('concept_b', 'http://127.0.0.1:5558/preview/concept-b'),
        ('concept_c', 'http://127.0.0.1:5558/preview/concept-c'),
    ]

    viewports = [
        ('1440x900', 1440, 900),
        ('1920x1080', 1920, 1080),
    ]

    def auth_session(context, user_id):
        page = context.new_page()
        resp = page.request.post('http://127.0.0.1:5558/api/internal/test_login', data=json.dumps({'user_id': user_id}), headers={'Content-Type': 'application/json'})
        assert resp.status == 200
        page.close()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for c_id, url in concepts:
                for vp_name, w, h in viewports:
                    context = browser.new_context(viewport={'width': w, 'height': h})
                    auth_session(context, 102)
                    page = context.new_page()
                    page.goto(url)
                    page.wait_for_timeout(500)

                    shot_path = os.path.join(output_dir, f"{c_id}_{vp_name}.png")
                    page.screenshot(path=shot_path, full_page=True)
                    print(f"Captured: {shot_path}")
                    page.close()
                    context.close()
            browser.close()
    finally:
        server.shutdown()
        print("Server shutdown completed.")

if __name__ == '__main__':
    capture_concept_previews()
