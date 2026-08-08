import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы видимо случайно добавили новый шматок сайдбара и оставили старый. 
# Найдём дубль <!-- Правая колонка: Sticky Sidebar --> ... </aside> и удалим его, так как правильный сайдбар был выше: <!-- ПРАВАЯ КОЛОНКА (Сайдбар) -->

html_cleaned = re.sub(
    r'<!-- Правая колонка: Sticky Sidebar -->\s*<aside class="hidden xl:flex flex-col gap-6 sticky top-8 z-10 w-full" id="lesson-sidebar">.*?</aside>', 
    '', 
    html, 
    flags=re.DOTALL
)

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html_cleaned)
