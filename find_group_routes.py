import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if '/groups' in line or '/teacher/group' in line:
            print(f"{i+1}: {line.strip()}")
