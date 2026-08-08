with open('templates/task_generator.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace extends 'base.html' with extends "sandbox/layout_teacher.html"
content = content.replace("{% extends 'base.html' %}", '{% extends "sandbox/layout_teacher.html" %}')
content = content.replace('{% extends "base.html" %}', '{% extends "sandbox/layout_teacher.html" %}')

# Find where {% block content %} starts
if '{% block content %}' in content:
    content = content.replace('{% block content %}', '{% block sandbox_content %}\n<main class="flex-1 bg-[#F8FAFC] overflow-y-auto overflow-x-hidden p-4 sm:p-6 pl-[6.5rem]">\n<div class="max-w-[1400px] mx-auto bg-white rounded-[2.5rem] p-6 sm:p-8 shadow-sm border border-slate-200/60 my-4 relative flex flex-col min-h-[calc(100vh-4rem)]">')

# Find where {% endblock %} closes content block before {% block scripts_extra %} or {% block head_js %}
target_end = '</div>\n{% endblock %}'
# Replace last </div> before {% block scripts_extra %}
if '{% block scripts_extra %}' in content:
    idx = content.find('{% block scripts_extra %}')
    content_part1 = content[:idx]
    content_part2 = content[idx:]
    # Replace last {% endblock %} in part 1
    last_end = content_part1.rfind('{% endblock %}')
    if last_end != -1:
        content_part1 = content_part1[:last_end] + '</div>\n</main>\n{% endblock %}' + content_part1[last_end+14:]
    content = content_part1 + content_part2

with open('templates/task_generator.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Converted templates/task_generator.html to sandbox/layout_teacher.html!")
