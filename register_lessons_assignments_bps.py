with open('app/__init__.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("    # app.register_blueprint(lessons_bp)", "    app.register_blueprint(lessons_bp)")
content = content.replace("    # app.register_blueprint(assignments_bp)", "    app.register_blueprint(assignments_bp)")

with open('app/__init__.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Registered lessons_bp and assignments_bp in app/__init__.py!")
