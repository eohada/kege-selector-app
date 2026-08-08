import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Оригинальный скрипт (`lessonSocket.on('lesson_tasks_updated')`, обработка табов, localStorage)
# ОЖИДАЛ определенные классы. Например, ссылки в миникарте и основном навигаторе он искал как `.task-nav-btn`.
# Наши новые красивые ссылки имеют классы `clay-interactive h-14...`. Их JS тупо не видит.
# Добавим им класс `task-nav-btn` В КОНЕЦ, чтобы мы не сломали Tailwind, но JS их нашел.
# Также добавим IDшники `id="tasknav-{{ lt.lesson_task_id }}"`, так как скрипт обновляет их по ID.

# Замена для главных кнопок задач:
html = re.sub(
    r'<a href="#task-\{\{ lt\.lesson_task_id \}\}" class="clay-interactive h-14(.+?)\{\{ btn_class \}\} no-underline" onclick="document\.querySelector\(\'\[data-tab=\\\'tasks\\\'\]\'\)\.click\(\);"',
    r'<a id="tasknav-{{ lt.lesson_task_id }}" href="#task-{{ lt.lesson_task_id }}" class="clay-interactive h-14\1{{ btn_class }} no-underline task-nav-btn" onclick="document.querySelector(\'[data-tab=\\\'tasks\\\']\').click();"',
    html
)

# Замена для сайдбар миникарты:
html = re.sub(
    r'<div class="clay-interactive w-full pt-\[100%\](.+?)\{\{ mini_class \}\}" onclick="document\.querySelector',
    r'<a id="tasknav-{{ lt.lesson_task_id }}" href="#task-{{ lt.lesson_task_id }}" class="clay-interactive w-full pt-[100%]\1{{ mini_class }} task-nav-btn block no-underline" onclick="document.querySelector',
    html
)
# Переключаем </div> внутри цикла сайдбара на </a>, т.к. заменили <div href...> на <a>
html = html.replace(
    '<div class="absolute inset-0 flex items-center justify-center text-xl">{{ loop.index }}</div>\n                            </div>',
    '<div class="absolute inset-0 flex items-center justify-center text-xl">{{ loop.index }}</div>\n                            </a>'
)

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
