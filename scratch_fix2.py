with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re

# Fix syntax errors injected by my previous python re.sub script
content = content.replace(r"{\'success\': False, \'message\': \'Нет прав\'}", "{'success': False, 'message': 'Нет прав'}")
content = content.replace(r"{\\'success\\': False, \\'message\\': \\'Нет прав\\'}", "{'success': False, 'message': 'Нет прав'}")

with open('app/main/routes.py', 'w', encoding='utf-8') as f:
    f.write(content)
