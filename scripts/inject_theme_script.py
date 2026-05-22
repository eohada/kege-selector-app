import os
import re

script_to_inject = '''    <script>
        (function(){
            try {
                var v = localStorage.getItem('ui.themeMode');
                if (v === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
                else if (v === 'light') document.documentElement.setAttribute('data-theme', 'light');
            } catch(e) {}
        })();
    </script>
</head>'''

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Проверяем, есть ли уже этот скрипт, чтобы не добавлять дважды
    if "localStorage.getItem('ui.themeMode')" in content and "document.documentElement.setAttribute" in content:
        return False

    if '</head>' in content:
        content = content.replace('</head>', script_to_inject, 1)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

changed = 0
for root, dirs, files in os.walk('templates'):
    for file in files:
        if file.endswith('.html'):
            path = os.path.join(root, file)
            if process_file(path):
                print(f"Updated: {path}")
                changed += 1

print(f"Total files updated: {changed}")
