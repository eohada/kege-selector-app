import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/__init__.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(445, 460):
    print(f"{i+1}: {lines[i].rstrip()}")
