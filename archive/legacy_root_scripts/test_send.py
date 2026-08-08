import requests
import json

url = "http://127.0.0.1:5000/api/qa/desktop-report"
headers = {"Authorization": "Bearer QA_COMPANION_SECRET_TOKEN_2026"}
data = {
    'area': 'Общая',
    'verdict': 'critical',
    'description': 'Test API Bug from pure script'
}

res = requests.post(url, headers=headers, data=data)
print(res.status_code)
print(res.text)
