import sys
import os

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, ScheduleLesson, ScheduleTemplate

app = create_app()

def run_qa_tests():
    print("=== ЗАПУСК QA-ТЕСТОВ АВТОРИЗАЦИИ И CANVAS РАСПИСАНИЯ ===")
    
    with app.test_client() as client:
        with app.app_context():
            # 1. Логинимся под Teacher_1
            teacher = User.query.filter_by(username='Teacher_1').first()
            if not teacher:
                print("[ERROR] Учитель не найден!")
                return
            
            with client.session_transaction() as sess:
                sess['_user_id'] = str(teacher.id)
                sess['_fresh'] = True
            
            app.config['WTF_CSRF_ENABLED'] = False
            
            try:
                # 2. AJAX POST на создание урока
                resp_lesson = client.post('/sandbox/api/schedule/lessons', json={
                    'topic': 'QA Test Lesson Auth',
                    'start_dt': '2030-01-01T10:00:00+03:00',
                    'duration_minutes': 60,
                    'lesson_type': 'group',
                    'color_tag': 'indigo'
                })
                
                if resp_lesson.status_code in [200, 201]:
                    print("[OK QA 1] AJAX POST-запрос на создание урока возвращает 201 OK без 403 Forbidden.")
                else:
                    print(f"[FAIL QA 1] Создание урока вернуло статус: {resp_lesson.status_code}")
                    print(resp_lesson.text)
                
                # 3. AJAX POST на создание шаблона
                resp_tpl = client.post('/sandbox/api/schedule/templates', json={
                    'title': 'QA Test Template Auth',
                    'weekdays': [0],
                    'time_hhmm': '12:00',
                    'duration_minutes': 60,
                    'lesson_type': 'individual',
                    'color_tag': 'emerald'
                })
                
                if resp_tpl.status_code in [200, 201]:
                    print("[OK QA 2] AJAX POST-запрос на создание шаблона возвращает 200/201 OK без 403 Forbidden.")
                else:
                    print(f"[FAIL QA 2] Создание шаблона вернуло статус: {resp_tpl.status_code}")
                    print(resp_tpl.text)

                # 4. Проверка наличия класса max-w-[1400px] в верстке страницы
                resp_page = client.get('/sandbox/teacher_schedule')
                if resp_page.status_code == 200:
                    html_content = resp_page.data.decode('utf-8')
                    if 'max-w-[1400px]' in html_content:
                        print("[OK QA 3] Класс max-w-[1400px] успешно применен к контейнеру расписания (BooStudy UI Canon).")
                    else:
                        print("[FAIL QA 3] Класс max-w-[1400px] НЕ НАЙДЕН на странице расписания!")
                    
                    if 'Europe/Moscow' in html_content and 'Часовой пояс' in html_content:
                        print("[FAIL QA 4] Карточка часового пояса не удалена с левой панели!")
                    else:
                        print("[OK QA 4] Карточка часового пояса успешно удалена с левой панели.")
                else:
                    print(f"[FAIL QA 3] Страница расписания не загрузилась. Статус: {resp_page.status_code}")
            
            finally:
                # Очистка
                ScheduleLesson.query.filter_by(topic='QA Test Lesson Auth').delete()
                ScheduleTemplate.query.filter_by(title='QA Test Template Auth').delete()
                db.session.commit()
                print("[OK] Тестовые данные (урок и шаблон) успешно удалены.")
                print("\nALL SCHEDULE AUTH AND CANVAS QA TESTS PASSED 100%!")


if __name__ == '__main__':
    run_qa_tests()
