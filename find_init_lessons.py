import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/__init__.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'lessons' in line or 'assignments' in line:
            print(f"{i+1}: {line.strip()}")
