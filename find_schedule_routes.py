import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/schedule/routes.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if '.route(' in line:
            print(f"{i+1}: {line.strip()}")
