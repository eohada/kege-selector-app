import json
from jinja2 import Template

html = open('templates/admin/qa/dashboard.html').read()
try:
    Template(html)
    print("Dashboard syntax OK")
except Exception as e:
    print(f"Dashboard error: {e}")

html2 = open('templates/admin/qa/report_detail.html').read()
try:
    Template(html2)
    print("Report syntax OK")
except Exception as e:
    print(f"Report error: {e}")
