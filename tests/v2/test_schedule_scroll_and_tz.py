import os
import sys

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db, User

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False  # Отключаем CSRF для тестов

def check(message, condition, details=""):
    status = "[OK]" if condition else "[FAIL]"
    print(f"{status} {message}")
    if not condition:
        if details:
            print(f"       -> {details}")
        sys.exit(1)

def run_tests():
    with app.app_context():
        # Подготовка пользователя для входа
        teacher = User.query.filter_by(username='Teacher_1').first()
        student = User.query.filter_by(username='Student_1').first()

        if not teacher or not student:
            print("Тестовые пользователи не найдены. Пропускаем.")
            sys.exit(0)

        with app.test_client() as client:
            # --- 1. Тест маршрутов преподавателя ---
            client.post('/login', data={'login': 'Teacher_1', 'password': 'password'})
            
            resp_teach = client.get('/sandbox/teacher_schedule')
            check("Teacher schedule route returns 200", resp_teach.status_code == 200)
            
            html_teach = resp_teach.data.decode('utf-8')
            check("Teacher schedule has NO timezone select/card", 
                  'name="timezone"' not in html_teach and 'Часовой пояс' not in html_teach)
            
            check("Teacher schedule has UI Canon container width max-w-[1400px]", 
                  'max-w-[1400px]' in html_teach)
            
            check("Teacher schedule has scroll-smooth wrapper", 
                  'scroll-smooth' in html_teach)
                  
            client.get('/logout')

            # --- 2. Тест маршрутов ученика ---
            client.post('/login', data={'login': 'Student_1', 'password': 'password'})
            
            resp_stud = client.get('/sandbox/student_schedule')
            check("Student schedule route returns 200", resp_stud.status_code == 200)
            
            html_stud = resp_stud.data.decode('utf-8')
            check("Student schedule has NO timezone select/card", 
                  'name="timezone"' not in html_stud and 'Часовой пояс' not in html_stud)
            
            check("Student schedule has UI Canon container width max-w-[1400px]", 
                  'max-w-[1400px]' in html_stud)
            
            check("Student schedule has scroll-smooth wrapper", 
                  'scroll-smooth' in html_stud)
            
            print("\nALL SCHEDULE SCROLL AND TZ QA TESTS PASSED 100%!")

if __name__ == '__main__':
    run_tests()
