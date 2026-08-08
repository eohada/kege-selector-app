import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'sandbox/impersonate' in line:
            print(f"{i+1}: {line.strip()}")
