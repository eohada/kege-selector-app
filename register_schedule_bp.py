with open('app/__init__.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = "    # app.register_blueprint(schedule_bp)"
replacement = "    app.register_blueprint(schedule_bp)"

content = content.replace(target, replacement)

with open('app/__init__.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Registered schedule_bp in app/__init__.py!")
