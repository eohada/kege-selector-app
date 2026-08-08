import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash
from app import create_app
from core.db_models import (
    db, User, UserProfile, UserRole, Student, Course, Lesson, Assignment, AssignmentTask, Tasks, Submission, AssignmentTaskChatMessage
)

TEST_USERS = [
    # 3 Students
    {"username": "Student_1", "role": "student", "name": "Иван Иванов", "class": 10, "xp": 450, "level": 1, "streak": 5},
    {"username": "Student_2", "role": "student", "name": "Глеб Малиновский", "class": 11, "xp": 8450, "level": 3, "streak": 14},
    {"username": "Student_3", "role": "student", "name": "Анастасия Смирнова", "class": 9, "xp": 14200, "level": 5, "streak": 21},

    # 3 Teachers
    {"username": "Teacher_1", "role": "tutor", "name": "Артем Петров"},
    {"username": "Teacher_2", "role": "tutor", "name": "Елена Соколова"},
    {"username": "Teacher_3", "role": "tutor", "name": "Дмитрий Волков"},

    # 3 Parents
    {"username": "Parent_1", "role": "parent", "name": "Ольга Иванова"},
    {"username": "Parent_2", "role": "parent", "name": "Сергей Малиновский"},
    {"username": "Parent_3", "role": "parent", "name": "Екатерина Смирнова"},

    # 3 Admins
    {"username": "Admin_1", "role": "admin", "name": "Михаил Сидоров"},
    {"username": "Admin_2", "role": "admin", "name": "Алексей Ковалев"},
    {"username": "Admin_3", "role": "admin", "name": "Наталья Морозова"},

    # 1 Creator
    {"username": "Creator", "role": "creator", "name": "Олег Хадасевич"},
]

def seed_users():
    app = create_app()
    with app.app_context():
        _run_seeding()

def _run_seeding():
    print("[Schema Only] Re-creating clean database tables...")
    db.drop_all()
    db.create_all()

    now = datetime.now(timezone.utc)

    # 1. Seed Course: «Информатика ЕГЭ 2026»
    course = Course(
        title="Информатика ЕГЭ 2026",
        slug="ege_inf_2026",
        is_active=True
    )
    db.session.add(course)
    db.session.flush()

    # 2. Seed Test Users
    user_map = {}
    for udata in TEST_USERS:
        username = udata["username"]
        role = udata["role"]
        display_name = udata["name"]

        user = User(
            username=username,
            email=f"{username.lower()}@boostudy.ru",
            password_hash=generate_password_hash("password123"),
            role=role,
            avatar_url=f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}&backgroundColor=e0f2fe",
            about_me=f"Тестовый аккаунт {display_name} ({role}) на платформе BooStudy.",
            is_active=True
        )
        db.session.add(user)
        db.session.flush()
        user_map[username] = user

        db.session.add(UserRole(user_id=user.id, role=role))

        name_parts = display_name.split()
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        profile = UserProfile(
            user_id=user.id,
            first_name=first_name,
            last_name=last_name,
            phone="+7 (999) 000-00-00",
            timezone="Europe/Moscow"
        )
        db.session.add(profile)

    teacher1_user = user_map["Teacher_1"]
    teacher2_user = user_map["Teacher_2"]
    student1_user = user_map["Student_1"]

    # 3. Seed Students & Link Mentor
    student_records = {}
    for udata in TEST_USERS:
        if udata["role"] == "student":
            u = user_map[udata["username"]]
            is_student_1 = (udata["username"] == "Student_1")
            
            student = Student(
                user_id=u.id,
                name=udata["name"],
                school_class=udata.get("class", 11),
                xp=udata.get("xp", 5000),
                level=udata.get("level", 2),
                streak_days=udata.get("streak", 10),
                category="ЕГЭ 2026",
                goal_text="Сдать КЕГЭ по Информатике на 90+ баллов",
                mentor_id=teacher1_user.id if is_student_1 else None
            )
            db.session.add(student)
            db.session.flush()
            student_records[udata["username"]] = student

    student1 = student_records["Student_1"]

    # 4. Seed EXACTLY 5 Lessons for Student_1
    lessons_data = [
        {"topic": "Урок 1. Введение в КЕГЭ и системное ПО", "status": "completed", "delta_days": -14},
        {"topic": "Урок 2. Кодирование информации и алфавитный подход", "status": "completed", "delta_days": -10},
        {"topic": "Урок 3. Перебор вариантов и itertools в Python", "status": "completed", "delta_days": -5},
        {"topic": "Урок 4. Алгебра логики и таблицы истинности", "status": "planned", "delta_days": 0},
        {"topic": "Урок 5. Динамическое программирование в №15", "status": "planned", "delta_days": 4},
    ]

    for ld in lessons_data:
        lesson_dt = now + timedelta(days=ld["delta_days"])
        if ld["delta_days"] == 0:
            lesson_dt = now + timedelta(minutes=30)
            
        lesson = Lesson(
            student_id=student1.student_id,
            exam_course_id=course.id,
            topic=ld["topic"],
            status=ld["status"],
            lesson_date=lesson_dt,
            duration=60,
            lesson_type="regular"
        )
        db.session.add(lesson)

    # 5. Seed Tasks with KaTeX Formulas, Tables & File Attachments
    db_tasks = []

    # Task 1 (КЕГЭ №2)
    t1 = Tasks(
        task_number=2,
        course_id=course.id,
        content_html=r'''<p class="font-semibold text-slate-800">
          Логическая функция $F$ задаётся выражением: 
          <span class="font-mono bg-slate-100 text-indigo-700 px-2.5 py-1 rounded-lg border border-slate-200 font-bold">$((x \to y) \equiv (w \to z)) \lor (x \land w)$</span>
        </p>
        <p>
          Ниже приведен фрагмент таблицы истинности функции $F$, содержащий все наборы аргументов, при которых функция $F$ <strong>ложна</strong>. Определите, какому столбцу таблицы истинности соответствует каждая из переменных $x, y, z, w$.
        </p>
        <div class="bg-slate-50 border border-slate-200 rounded-2xl p-4 overflow-x-auto my-3">
          <table class="w-full text-center text-xs font-mono font-bold">
            <thead class="bg-slate-200/70 text-slate-600 border-b border-slate-300">
              <tr>
                <th class="py-2.5 px-3">Переменная 1</th>
                <th class="py-2.5 px-3">Переменная 2</th>
                <th class="py-2.5 px-3">Переменная 3</th>
                <th class="py-2.5 px-3">Переменная 4</th>
                <th class="py-2.5 px-3 bg-indigo-100 text-indigo-800">Функция F</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 text-slate-800">
              <tr>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3">1</td>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3 bg-indigo-50 font-black text-rose-600">0</td>
              </tr>
              <tr>
                <td class="py-2 px-3">1</td>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3">1</td>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3 bg-indigo-50 font-black text-rose-600">0</td>
              </tr>
              <tr>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3">0</td>
                <td class="py-2 px-3">1</td>
                <td class="py-2 px-3">1</td>
                <td class="py-2 px-3 bg-indigo-50 font-black text-rose-600">0</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-xs font-semibold text-slate-500">
          В ответе напишите буквы $x, y, z, w$ в том порядке, в котором соответствуют им столбцы (без разделителей).
        </p>''',
        answer="zwyx",
        attached_files='[{"name": "table_task02.xlsx", "size": "14 KB", "url": "/sandbox/download_attachment/table_task02.xlsx"}, {"name": "data_task02.txt", "size": "8 KB", "url": "/sandbox/download_attachment/data_task02.txt"}]',
        difficulty_level=2,
        created_by_user_id=teacher1_user.id,
        topic="Таблицы истинности логических выражений",
        source="Апробация КЕГЭ",
        starter_code=r'''# Скрипт перебора таблицы истинности КЕГЭ №2
print("x y z w")
for x in range(2):
    for y in range(2):
        for z in range(2):
            for w in range(2):
                f = ((not(x <= y)) == (w <= z)) or (x and w)
                if not f:
                    print(x, y, z, w)'''
    )
    db.session.add(t1)

    # Task 2 (КЕГЭ №15)
    t2 = Tasks(
        task_number=15,
        course_id=course.id,
        content_html=r'''<p class="font-semibold text-slate-800">
          Обозначим через $P$ поразрядную конъюнкцию неотрицательных целых чисел $m$ и $n$. 
          Для какого наименьшего натурального числа $A$ формула 
          $$(x \land 29 \neq 0) \to ((x \land 17 = 0) \to (x \land A \neq 0))$$ 
          тождественно истинна (то есть принимает значение $1$ при любом неотрицательном целом значении переменной $x$)?
        </p>''',
        answer="12",
        attached_files='[{"name": "15_demo.py", "size": "2 KB", "url": "/sandbox/download_attachment/15_demo.py"}]',
        difficulty_level=2,
        created_by_user_id=teacher1_user.id,
        topic="Истинность предиката и поразрядные операции",
        source="ФИПИ 2026",
        starter_code=r'''# Код решения №15
def f(x, A):
    return (x & 29 != 0) <= ((x & 17 == 0) <= (x & A != 0))

for A in range(1, 1000):
    if all(f(x, A) for x in range(1000)):
        print(A)
        break'''
    )
    db.session.add(t2)

    # Task 3 (КЕГЭ №17)
    t3 = Tasks(
        task_number=17,
        course_id=course.id,
        content_html=r'''<p class="font-semibold text-slate-800">
          В файле <code class="bg-slate-100 text-indigo-700 px-1.5 py-0.5 rounded font-mono font-bold">17_demo.txt</code> содержится последовательность целых чисел. Элементы последовательности могут принимать целые значения от $-10\,000$ до $10\,000$ включительно.
        </p>
        <p class="mt-2">
          Определите количество пар элементов последовательности, в которых хотя бы одно число делится на $3$, а сумма элементов пары кратна $5$. В ответе запишите два числа: сначала количество найденных пар, затем максимальную из сумм элементов таких пар.
        </p>''',
        answer="2837 18490",
        attached_files='[{"name": "17_demo.txt", "size": "45 KB", "url": "/sandbox/download_attachment/17_demo.txt"}]',
        difficulty_level=1,
        created_by_user_id=teacher1_user.id,
        topic="Обработка числовой последовательности",
        source="Демоверсия ФИПИ",
        starter_code=r'''# Код решения №17
# with open('17_demo.txt') as f:
#     data = [int(x) for x in f]'''
    )
    db.session.add(t3)
    db.session.flush()

    db_tasks = [t1, t2, t3]

    # 6. Seed 3 Assignments created by Teacher_1 & issued to Student_1
    t1_homeworks = [
        {
            "title": "Производная и первообразная. Практика.",
            "assignment_type": "homework",
            "deadline": now + timedelta(hours=18),
            "status": "active"
        },
        {
            "title": "Задание №2. Алгебра логики.",
            "assignment_type": "homework",
            "deadline": now + timedelta(days=4),
            "status": "active"
        },
        {
            "title": "Проверочная работа №3. Графы и пути в графах.",
            "assignment_type": "classwork",
            "deadline": now + timedelta(days=5),
            "status": "active"
        }
    ]

    for idx, hw in enumerate(t1_homeworks):
        ass = Assignment(
            title=hw["title"],
            assignment_type=hw["assignment_type"],
            deadline=hw["deadline"],
            created_by_id=teacher1_user.id,
            is_active=True,
            status=hw["status"],
            max_attempts_default=3,
            allow_separate_submission=True
        )
        db.session.add(ass)
        db.session.flush()

        # Bind 3 tasks to assignment
        for order_i, t_obj in enumerate(db_tasks, start=1):
            ass_task = AssignmentTask(
                assignment_id=ass.assignment_id,
                task_id=t_obj.task_id,
                order_index=order_i,
                max_score=1,
                max_attempts=3
            )
            db.session.add(ass_task)

        sub = Submission(
            assignment_id=ass.assignment_id,
            student_id=student1.student_id,
            status="IN_PROGRESS",
            total_score=0,
            max_score=len(db_tasks)
        )
        db.session.add(sub)
        db.session.flush()

        # Seed Curator Chat Messages bound to assignment_id & task_id (1 and 2)
        chat1 = AssignmentTaskChatMessage(
            assignment_id=ass.assignment_id,
            task_id=1,
            user_id=teacher1_user.id,
            user_name="Артем Петров (Наставник)",
            user_role="tutor",
            message="В этой задаче обрати внимание на равносильность (≡) и импликацию (x <= y)!",
            created_at=now - timedelta(minutes=15)
        )
        chat2 = AssignmentTaskChatMessage(
            assignment_id=ass.assignment_id,
            task_id=2,
            user_id=teacher1_user.id,
            user_name="Артем Петров (Наставник)",
            user_role="tutor",
            message="В задании №15 проще всего перебрать значения A от 1 до 1000 с помощью `all()`.",
            created_at=now - timedelta(minutes=10)
        )
        db.session.add_all([chat1, chat2])

    # 7. Seed Assignments for Teacher_2 (for isolation check)
    t2_assignments = [
        {
            "title": "Задание №17. Последовательности чисел и делимость.",
            "assignment_type": "homework",
            "deadline": now + timedelta(days=3),
            "status": "active"
        }
    ]

    for hw in t2_assignments:
        ass = Assignment(
            title=hw["title"],
            assignment_type=hw["assignment_type"],
            deadline=hw["deadline"],
            created_by_id=teacher2_user.id,
            is_active=True,
            status=hw["status"]
        )
        db.session.add(ass)

    db.session.commit()
    print(f"[OK] Clean DB initialized with {len(TEST_USERS)} users, 1 Course, 5 Lessons, 3 Tasks with KaTeX & Files, and 3 Assignments!")

if __name__ == "__main__":
    seed_users()
