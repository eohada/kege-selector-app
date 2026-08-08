import os
import json
from flask import Flask, request, jsonify
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

app = Flask(__name__)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Папка на Google Диске, куда будут загружаться файлы
GOOGLE_DRIVE_FOLDER_ID = "1Tx3AZzcgEXeIl1Zd3HzzIsCvyngqHhSM"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')
REPORTS_FILE = os.path.join(BASE_DIR, 'reports.json')
TESTS_FILE = os.path.join(BASE_DIR, 'tests_db.json')

# Начальные данные для тестов
INITIAL_TESTS = {
    "available": [
      {
        "id": "t1",
        "title": "Регистрация нового ученика с некорректной почтой",
        "area": "Регистрация и Профили",
        "role": "Гость (Без авторизации)",
        "steps": [
          "Открыть главную страницу платформы.",
          "Нажать на кнопку 'Зарегистрироваться'.",
          "В поле Email ввести некорректное значение (например, 'test@@mail..ru').",
          "Заполнить пароль и имя валидными значениями.",
          "Нажать 'Создать аккаунт'."
        ],
        "expected": "Кнопка отправки блокируется, либо под полем Email всплывает понятная ошибка валидации. Регистрация не должна проходить."
      },
      {
        "id": "t2",
        "title": "Покупка премиум-тарифа через тестовую карту",
        "area": "Тарифы и Оплата",
        "role": "Ученик (Без подписки)",
        "steps": [
          "Войти в личный кабинет ученика.",
          "Перейти на вкладку 'Тарифы'.",
          "Выбрать тариф 'Максимум' на 1 месяц, нажать 'Купить'.",
          "В окне оплаты ввести номер тестовой карты (4242 4242 4242 4242) и любой срок действия.",
          "Подтвердить платеж."
        ],
        "expected": "Платеж проходит успешно, пользователя редиректит в ЛК, статус подписки мгновенно меняется на 'Активен'."
      },
      {
        "id": "t3",
        "title": "Создание тестового ученика админом",
        "area": "Админка и Управление",
        "role": "Главный Администратор",
        "steps": [
          "Авторизоваться под учетной записью администратора.",
          "Перейти в раздел '/admin/users'.",
          "Нажать кнопку 'Добавить пользователя'.",
          "Заполнить ФИО, Email, выбрать роль 'Ученик' и нажать 'Создать'."
        ],
        "expected": "Новый пользователь появляется в списке, на его почту уходит авто-письмо с временным паролем."
      },
      {
        "id": "t4",
        "title": "Проверка адаптивности конспекта урока",
        "area": "Мобильный инспектор",
        "role": "Ученик (Любой)",
        "steps": [
          "Открыть платформу с мобильного телефона.",
          "Перейти в раздел 'Курсы' -> 'Введение в программирование'.",
          "Открыть первый урок с теорией.",
          "Проскроллить страницу до конца."
        ],
        "expected": "Все формулы, картинки и блоки кода помещаются по ширине экрана смартфона. Нет горизонтальной прокрутки всего сайта."
      },
      {
        "id": "t5",
        "title": "Бесконечный цикл в Песочнице",
        "area": "Кодерская (Песочница)",
        "role": "Ученик (Любой)",
        "steps": [
          "Открыть раздел 'Песочница кода'.",
          "Вставить бесконечный цикл.",
          "Нажать кнопку 'Запустить код'."
        ],
        "expected": "Интерпретатор не вешает браузер намертво. Через 5 секунд выполнение принудительно обрывается по таймауту."
      }
    ],
    "review": [
      {
        "id": "r1",
        "title": "Применение промокода со 100% скидкой",
        "area": "Тарифы и Оплата",
        "role": "Ученик (Без подписки)",
        "iteration": 2,
        "steps": [
          "Открыть страницу оплаты тарифа.",
          "Ввести промокод 'FREE-STUDY-2026' и нажать 'Применить'."
        ],
        "expected": "Сумма к оплате должна стать 0 рублей, кнопка 'Оплатить карту' меняется на 'Активировать бесплатно'.",
        "history": [
          {
            "author": "Тестировщик (Итерация 1)",
            "type": "Критическая ошибка",
            "comment": "При вводе промокода на 100% скидку сумма становится 0 руб, но кнопка 'Оплатить карту' все равно требует ввода платежных данных и выдает ошибку API."
          },
          {
            "author": "Разработчик (Исправлено)",
            "comment": "Исправил логику отображения кнопки. При нулевой сумме форма оплаты больше не запрашивает карту и проводит транзакцию как бесплатную активацию."
          }
        ]
      }
    ]
}

# Инициализация файлов базы данных
if not os.path.exists(TESTS_FILE):
    with open(TESTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(INITIAL_TESTS, f, ensure_ascii=False, indent=2)

if not os.path.exists(REPORTS_FILE):
    with open(REPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False)

def get_drive_service():
    """Инициализация клиента Google Drive API"""
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError("Файл token.json не найден! Запустите get_tokens.py")
        
    creds = Credentials.from_authorized_user_file(TOKEN_FILE)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(creds.to_json())
            
    return build('drive', 'v3', credentials=creds)

@app.route('/api/tests', methods=['GET'])
def get_tests():
    try:
        with open(TESTS_FILE, 'r', encoding='utf-8') as f:
            tests = json.load(f)
        return jsonify(tests)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload-to-drive', methods=['POST'])
def upload_to_drive():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Файл не отправлен"}), 400
            
        uploaded_file = request.files['file']
        test_id = request.form.get('test_id', 'unknown_test')
        
        import tempfile
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, uploaded_file.filename)
        uploaded_file.save(temp_path)
        
        service = get_drive_service()
        
        file_metadata = {
            'name': f"Test_{test_id}_{uploaded_file.filename}",
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }
        
        media = MediaFileUpload(
            temp_path,
            mimetype=uploaded_file.content_type,
            resumable=True
        )
        
        drive_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # Права доступа на чтение по ссылке
        try:
            service.permissions().create(
                fileId=drive_file.get('id'),
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except Exception as perm_err:
            print("Предупреждение: не удалось сделать файл публичным:", perm_err)

        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as cleanup_err:
            print("Предупреждение: не удалось удалить временный файл:", cleanup_err)
            
        return jsonify({
            "success": True,
            "file_id": drive_file.get('id'),
            "link": drive_file.get('webViewLink')
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reports', methods=['POST'])
def save_report():
    try:
        report_data = request.json
        if not report_data:
            return jsonify({"error": "Данные отчета пусты"}), 400
            
        # Читаем и обновляем отчеты
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            reports = json.load(f)
            
        new_report = {
            "id": len(reports) + 1,
            "test_id": report_data.get("test_id"),
            "test_title": report_data.get("test_title"),
            "area": report_data.get("area"),
            "comment": report_data.get("comment"),
            "verdict": report_data.get("verdict"),
            "gdrive_link": report_data.get("gdrive_link"),
            "gdrive_links": report_data.get("gdrive_links", []),
            "timestamp": report_data.get("timestamp"),
            "status": "pending" # pending | resolved
        }
        reports.append(new_report)
        
        with open(REPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)

        # Перемещаем тест в архив разработчика или удаляем из активных списков
        with open(TESTS_FILE, 'r', encoding='utf-8') as f:
            tests = json.load(f)

        test_id = report_data.get("test_id")
        tests.setdefault("developer", [])
        
        # Находим текущий тест в available или review
        target_test = None
        
        for t in tests.get("available", []):
            if t["id"] == test_id:
                target_test = t
                break
        if not target_test:
            for t in tests.get("review", []):
                if t["id"] == test_id:
                    target_test = t
                    break

        # Удаляем из активных
        tests["available"] = [t for t in tests.get("available", []) if t["id"] != test_id]
        tests["review"] = [t for t in tests.get("review", []) if t["id"] != test_id]
        
        # Если тест найден и это баг (не успех), сохраняем его в "developer" для отслеживания итераций
        if target_test and report_data.get("verdict") in ["critical", "minor"]:
            # Удаляем старый инстанс из developer если был, и кладем свежий
            tests["developer"] = [t for t in tests["developer"] if t["id"] != test_id]
            tests["developer"].append(target_test)

        with open(TESTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tests, f, ensure_ascii=False, indent=2)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reports', methods=['GET'])
def get_reports():
    try:
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        # Возвращаем только активные (не решенные) отчеты
        active_reports = [r for r in reports if r.get("status", "pending") == "pending"]
        return jsonify(active_reports)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reports/<int:report_id>/resolve', methods=['POST'])
def resolve_report(report_id):
    try:
        data = request.json
        dev_comment = data.get("comment", "Исправлено.")

        # Находим отчет
        with open(REPORTS_FILE, 'r', encoding='utf-8') as f:
            reports = json.load(f)

        report = next((r for r in reports if r["id"] == report_id), None)
        if not report:
            return jsonify({"error": "Отчет не найден"}), 404

        report["status"] = "resolved"

        with open(REPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)

        # Возвращаем тест в "review" список для тестировщиков
        with open(TESTS_FILE, 'r', encoding='utf-8') as f:
            tests = json.load(f)

        test_id = report["test_id"]
        tests.setdefault("developer", [])
        
        # Пытаемся найти тест в developer
        test_item = next((t for t in tests["developer"] if t["id"] == test_id), None)
        
        # Если не нашли, берем шаблон из INITIAL_TESTS
        if not test_item:
            all_templates = INITIAL_TESTS["available"] + INITIAL_TESTS["review"]
            template = next((t for t in all_templates if t["id"] == test_id), None)
            if template:
                test_item = {
                    "id": template["id"],
                    "title": template["title"],
                    "area": template["area"],
                    "role": template["role"],
                    "steps": template["steps"],
                    "expected": template["expected"],
                    "iteration": template.get("iteration", 1),
                    "history": template.get("history", [])
                }

        if test_item:
            current_iter = test_item.get("iteration", 1)
            test_item["iteration"] = current_iter + 1
            
            # Собираем ссылки на фото
            photo_link = report.get("gdrive_link")
            if not photo_link and report.get("gdrive_links"):
                photo_link = report.get("gdrive_links")[0] # Берем первое для старого UI
                
            test_item.setdefault("history", []).append({
                "author": f"Тестировщик (Итерация {current_iter})",
                "type": "Критическая ошибка" if report["verdict"] == "critical" else "Незначительная ошибка",
                "comment": report["comment"],
                "gdrive": photo_link,
                "gdrives": report.get("gdrive_links", [])
            })
            
            test_item["history"].append({
                "author": "Разработчик (Исправлено)",
                "comment": dev_comment
            })

            # Переносим в review и чистим из developer
            tests["review"] = [t for t in tests.get("review", []) if t["id"] != test_id]
            tests["review"].append(test_item)
            tests["developer"] = [t for t in tests.get("developer", []) if t["id"] != test_id]

            with open(TESTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tests, f, ensure_ascii=False, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Запуск Flask-сервера...")
    app.run(port=5050, debug=True)
