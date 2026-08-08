with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if '/sandbox/student_dashboard' in line or '/sandbox/students' in line:
            print(f"{i+1}: {line.strip()}")
