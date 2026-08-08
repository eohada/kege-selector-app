import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/schedule/routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(318, 330):
    print(f"{i+1}: {lines[i].rstrip()}")
