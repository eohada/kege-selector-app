import requests
res = requests.get('http://127.0.0.1:5000/admin/qa/reports/14')
print(res.text)
