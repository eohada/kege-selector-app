with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("if current_user.role not in [\\'tutor\\', \\'admin\\']:", "if current_user.role not in ['tutor', 'admin']:")

with open('app/main/routes.py', 'w', encoding='utf-8') as f:
    f.write(content)
