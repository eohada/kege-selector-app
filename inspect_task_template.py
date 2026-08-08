import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('core/db_models.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'class TaskTemplate' in line:
        for j in range(i, min(i+35, len(lines))):
            print(f"{j+1}: {lines[j].rstrip()}")
        break
