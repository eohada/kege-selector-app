import sys
sys.stdout.reconfigure(encoding='utf-8')

for path in ['app/templates_manager/routes.py', 'app/task_generator/routes.py', 'app/kege_generator/routes.py']:
    print(f"=== {path} ===")
    with open(path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if '.route(' in line:
                print(f"{i+1}: {line.strip()}")
