import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(2217, min(2266, len(lines))):
    print(f"{i+1}: {lines[i].strip()}")
