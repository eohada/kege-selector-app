import requests

class BooStudyAPI:
    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.secret_token = "QA_COMPANION_SECRET_TOKEN_2026"
        
    def send_bug(self, description, area, verdict, video_path=None, screenshot_path=None):
        url = f"{self.base_url}/api/qa/desktop-report"
        
        headers = {
            "Authorization": f"Bearer {self.secret_token}"
        }
        
        data = {
            'area': area,
            'verdict': verdict,
            'description': description
        }
        
        files = {}
        if video_path:
            # Открываем файл как бинарный поток 'rb'
            files['video'] = open(video_path, 'rb')
            
        try:
            print(f"Uploading bug report to {url}...")
            res = requests.post(url, headers=headers, data=data, files=files)
            
            # Закрываем файл после отправки
            if 'video' in files:
                files['video'].close()
                
            if res.ok:
                print("✅ Успешно доставлено на сервер!")
                return True
            else:
                print(f"❌ Ошибка сервера: {res.status_code} {res.text}")
                return False
        except Exception as e:
            print("❌ Ошибка сети:", e)
            if 'video' in files: files['video'].close()
            return False
