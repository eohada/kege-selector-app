import os
import re

def refactor_template(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Проверяем, есть ли старая навигация
    if '{% include \'_primary_nav.html\' %}' not in content and '{% include "_primary_nav.html" %}' not in content:
        return False

    # Заменяем <div class="app-shell..."> на <div class="app-layout">
    # и сразу после этого (где-то) идет include _primary_nav.html
    # Мы ищем <div class="app-shell.*?>
    
    # 1. Меняем app-shell
    content = re.sub(r'<div class="app-shell[^>]*>', r'<div class="app-layout">', content, count=1)
    
    # 2. Заменяем _primary_nav.html на новую структуру
    new_nav = '''{% include '_sidebar.html' %}
    <div class="app-main">
        {% include '_topbar.html' %}
        <main class="app-content">'''
    
    content = re.sub(r'\{%\s*include\s*[\'"]_primary_nav\.html[\'"]\s*%\}', new_nav, content, count=1)
    
    # 3. Добавляем закрывающие теги перед последним </div> (закрывающим app-shell)
    # Так как мы заменили `<div class="app-shell">` на `<div class="app-layout">` и добавили `<div class="app-main"><main class="app-content">`, 
    # нам нужно добавить `</main></div>` перед самым последним `</div>`, который соответствовал `app-shell`.
    # Обычно app-shell закрывается в самом конце файла перед {% endblock %}
    
    # Найдем последнее вхождение </div>
    last_div_idx = content.rfind('</div>')
    if last_div_idx != -1:
        content = content[:last_div_idx] + '</main>\n    </div>\n' + content[last_div_idx:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        
    return True

changed_files = 0
for root, dirs, files in os.walk('templates'):
    if 'remote_admin' in root or 'errors' in root:
        continue
    for file in files:
        if file.endswith('.html'):
            path = os.path.join(root, file)
            if refactor_template(path):
                print(f"Refactored: {path}")
                changed_files += 1

print(f"Total files updated: {changed_files}")
