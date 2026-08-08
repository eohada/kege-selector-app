import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/templates_manager/routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(180, min(270, len(lines))):
    print(f"{i+1}: {lines[i].rstrip()}")
