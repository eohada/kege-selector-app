import sys
import os
import json
import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from core.db_models import db, User, TeacherProfile, TeacherProgram, TeacherResult, TeacherWebinar, CallRequest


def run_teacher_profile_qa_tests():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        db.create_all()

        # Seed test teacher
        teacher = User.query.filter_by(email='qa_teacher_profile@boostudy.ru').first()
        if not teacher:
            teacher = User(
                email='qa_teacher_profile@boostudy.ru',
                username='qa_teacher_mentor',
                full_name='Виктор Менторов',
                role='tutor',
                password_hash='pbkdf2:test_hash',
                is_active=True
            )
            db.session.add(teacher)
            db.session.commit()

        # Seed test student
        student = User.query.filter_by(email='qa_student_profile@boostudy.ru').first()
        if not student:
            student = User(
                email='qa_student_profile@boostudy.ru',
                username='qa_student_user',
                full_name='Анастасия Ученикова',
                role='student',
                password_hash='pbkdf2:test_hash',
                is_active=True
            )
            db.session.add(student)
            db.session.commit()

        teacher.role = 'tutor'
        student.role = 'student'
        db.session.commit()

        print(f"SEED VERIFICATION: teacher.id={teacher.id} ({teacher.email}), student.id={student.id} ({student.email})")

        client = app.test_client()

        # Clear previous test results & reviews for a clean slate
        TeacherResult.query.filter_by(teacher_id=teacher.id).delete()
        TeacherProgram.query.filter_by(teacher_id=teacher.id).delete()
        TeacherWebinar.query.filter_by(teacher_id=teacher.id).delete()
        from core.db_models import TeacherReview
        TeacherReview.query.filter_by(teacher_id=teacher.id).delete()
        db.session.commit()

        print("\n--- TEST 1: GET /profile as Teacher (Universal Profile Owner View) ---")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher.id)
            sess['sandbox_role'] = 'tutor'
            sess['_fresh'] = True

        res1 = client.get('/profile')
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"
        html1 = res1.get_data(as_text=True)
        assert 'Виктор Менторов' in html1 or 'qa_teacher_mentor' in html1
        assert 'Редактировать профиль' in html1
        assert 'Оставить отзыв' not in html1  # Self-review button forbidden for owner!
        assert 'Результаты пока не добавлены' in html1
        print("SUCCESS: GET /profile -> 200 OK (Owner View with Edit button, NO self-review button!)")

        print("\n--- TEST 2: GET /sandbox/mentor_profile Redirect ---")
        res_redir = client.get('/sandbox/mentor_profile')
        assert res_redir.status_code == 302, f"Expected 302, got {res_redir.status_code}"
        assert '/profile' in res_redir.headers.get('Location', '')
        print("SUCCESS: GET /sandbox/mentor_profile -> 302 Redirect to /profile!")

        print("\n--- TEST 3: GET /u/<username> as Student (Public Showcase & Action Bar) ---")
        from flask import g
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        db.session.commit()
        client_student = app.test_client()
        with client_student.session_transaction() as sess:
            sess['_user_id'] = str(student.id)
            sess['sandbox_role'] = 'student'
            sess['_fresh'] = True

        res2 = client_student.get(f'/u/{teacher.username}')
        html2 = res2.get_data(as_text=True)
        assert res2.status_code == 200, f"Expected 200, got {res2.status_code}"
        assert 'Записаться на занятие' in html2
        assert 'Оставить отзыв' in html2  # Student seeing teacher HAS leave review button!
        assert 'Редактировать профиль' not in html2  # Student CANNOT edit teacher profile!
        print("SUCCESS: GET /u/<username> -> 200 OK (Public Showcase View with Enroll & Review buttons, NO edit button!)")

        print("\n--- TEST 4: Self-Review Prohibition (POST /api/mentor/<id>/review by Teacher) ---")
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher.id)
            sess['sandbox_role'] = 'tutor'
            sess['_fresh'] = True

        res_self = client.post(f'/api/mentor/{teacher.id}/review', json={
            "rating": 5.0,
            "text": "Я сам о себе отличного мнения!"
        })
        assert res_self.status_code == 403, f"Expected 403 Forbidden for self-review, got {res_self.status_code}"
        print("SUCCESS: Self-review prohibited with 403 Forbidden!")

        print("\n--- TEST 5: GET /profile/<student_id> as Teacher (Student Profile View) ---")
        res_st_prof = client.get(f'/profile/{student.id}')
        assert res_st_prof.status_code == 200
        html_st = res_st_prof.get_data(as_text=True)
        assert 'Назначить ДЗ' in html_st  # Teacher viewing student profile HAS assign HW action button!
        assert 'Анастасия Ученикова' in html_st or 'qa_student_user' in html_st
        print("SUCCESS: GET /profile/<student_id> -> 200 OK (Teacher viewing Student Profile with Assign HW action!)")

        print("\n--- TEST 4: POST /api/teacher/profile/update ---")
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher.id)
            sess['sandbox_role'] = 'tutor'

        update_payload = {
            "full_name": "Виктор Менторов (Эксперт V2)",
            "specialization": "Информатика & Алгоритмы",
            "university": "МГУ (ВМК)",
            "experience_years": 8,
            "bio": "Опытный наставник BooStudy с 8-летним стажем. 100-балльники каждый год.",
            "tags": ["🐍 Python Advanced", "⚡ КЕГЭ 2026", "🎓 МГУ ВМК"],
            "programs": [
                {
                    "title": "Информатика 90+ Спецкурс",
                    "program_type": "ГОДОВОЙ КУРС",
                    "group_size_info": "Группа 8 чел.",
                    "description": "Спецкурс по алгоритмам",
                    "seats_left": 4
                }
            ],
            "results": [
                {
                    "student_name": "Илья К.",
                    "score": 100,
                    "target_university": "МФТИ",
                    "subject": "Информатика"
                }
            ],
            "webinars": [
                {
                    "title": "Разбор задания 27: Динамическое программирование",
                    "duration_minutes": 120,
                    "room_id": "demo_lesson_1"
                }
            ]
        }

        res3 = client.post('/api/teacher/profile/update', json=update_payload)
        assert res3.status_code == 200, f"Expected 200, got {res3.status_code}"
        data3 = json.loads(res3.get_data(as_text=True))
        assert data3.get('status') == 'success'

        # Verify DB updates
        prof_db = TeacherProfile.query.filter_by(user_id=teacher.id).first()
        assert prof_db.university == "МГУ (ВМК)"
        assert prof_db.experience_years == 8
        progs_db = TeacherProgram.query.filter_by(teacher_id=teacher.id).all()
        assert len(progs_db) == 1
        assert progs_db[0].title == "Информатика 90+ Спецкурс"
        results_db = TeacherResult.query.filter_by(teacher_id=teacher.id).all()
        assert len(results_db) == 1
        assert results_db[0].score == 100
        print("SUCCESS: POST /api/teacher/profile/update -> DB profile, programs, and results updated successfully!")

        print("\n--- TEST 6: POST /api/mentor/<id>/enroll ---")
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        with client_student.session_transaction() as sess:
            sess['_user_id'] = str(student.id)
            sess['sandbox_role'] = 'student'
            sess['_fresh'] = True
        target_prog = progs_db[0]
        enroll_payload = {
            "program_id": target_prog.id,
            "student_name": "Анастасия Ученикова",
            "phone": "+7 999 777-66-55",
            "notes": "Хочу подготовиться на 100 баллов!"
        }

        res4 = client_student.post(f'/api/mentor/{teacher.id}/enroll', json=enroll_payload)
        assert res4.status_code == 200, f"Expected 200, got {res4.status_code}"
        data4 = json.loads(res4.get_data(as_text=True))
        assert data4.get('status') == 'success'

        # Verify call request created in DB
        call_req = CallRequest.query.filter(CallRequest.message.like('%Анастасия%')).first()
        assert call_req is not None
        assert "+7 999 777-66-55" in call_req.message
        print("SUCCESS: POST /api/mentor/<id>/enroll -> CallRequest recorded in DB & response 200 OK!")

        print("\n--- TEST 7: POST /api/mentor/<id>/review & Dynamic Rating Calculation ---")
        # Post first review (5.0 stars)
        res_rev1 = client_student.post(f'/api/mentor/{teacher.id}/review', json={
            "rating": 5.0,
            "student_name": "Анастасия Ученикова",
            "text": "Потрясающий преподаватель! Объясняет 27 задачу за 10 минут."
        })
        assert res_rev1.status_code == 200
        assert json.loads(res_rev1.get_data(as_text=True)).get('status') == 'success'

        # Post second review (4.0 stars)
        res_rev2 = client_student.post(f'/api/mentor/{teacher.id}/review', json={
            "rating": 4.0,
            "student_name": "Дмитрий С.",
            "text": "Отличный курс, все понравилось!"
        })
        assert res_rev2.status_code == 200

        # Verify dynamic stats recalculation: (5 + 4) / 2 = 4.5 average rating, 2 reviews
        from app.main.routes import calculate_teacher_stats
        recalculated_stats = calculate_teacher_stats(teacher.id)
        assert recalculated_stats['rating'] == 4.5
        assert recalculated_stats['reviews_count'] == 2
        print("SUCCESS: POST /api/mentor/<id>/review -> Ratings dynamically recalculated to 4.5 (2 reviews)!")

        print("\n--- TEST 8: GET /student/dashboard as Student (Mentor Profile Links) ---")
        from core.db_models import Student
        student_db = Student.query.filter_by(user_id=student.id).first()
        if not student_db:
            student_db = Student(user_id=student.id, name=student.full_name or 'Анастасия Ученикова', mentor_id=teacher.id)
            db.session.add(student_db)
        else:
            student_db.mentor_id = teacher.id
        db.session.commit()

        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        with client_student.session_transaction() as sess:
            sess['_user_id'] = str(student.id)
            sess['sandbox_role'] = 'student'
            sess['_fresh'] = True

        res_dash = client_student.get('/student/dashboard')
        assert res_dash.status_code == 200, f"Expected 200, got {res_dash.status_code}"
        html_dash = res_dash.get_data(as_text=True)
        assert f'href="/profile/{teacher.id}"' in html_dash, "Mentor card must link to /profile/<teacher_id>"
        assert 'Профиль наставника' in html_dash
        print("SUCCESS: GET /student/dashboard -> Mentor Bento card links to /profile/<teacher_id>!")

        print("\n--- TEST 9: GET /students as Teacher (Symmetric Teacher-Student List) ---")
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher.id)
            sess['sandbox_role'] = 'tutor'
            sess['_fresh'] = True

        res_st_list = client.get('/students')
        assert res_st_list.status_code == 200, f"Expected 200, got {res_st_list.status_code}"
        html_st_list = res_st_list.get_data(as_text=True)
        assert 'У вас пока нет добавленных учеников' not in html_st_list, "Student list must NOT be empty when student has mentor_id"
        assert 'Анастасия Ученикова' in html_st_list or 'qa_student_user' in html_st_list
        assert f'href="/profile/{student.id}"' in html_st_list or f'href="/profile/{student_db.student_id}"' in html_st_list
        print("SUCCESS: GET /students -> Teacher sees assigned student with link to /profile/<student_id>!")

        print("\n============================================================")
        print("ALL QA TESTS FOR TEACHER PROFILE V2 PASSED 100% PERFECTLY!")
        print("============================================================\n")

if __name__ == '__main__':
    run_teacher_profile_qa_tests()
