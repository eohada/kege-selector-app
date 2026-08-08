import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Заменим сломанный `if student` в кнопке <a href...>
# Бэкенд в уроке передает `student` только родителям и преподавателям. Для учеников есть `current_user`. Это вызывало 500 ошибку "UndefinedError: 'student' is undefined"
html = re.sub(
    r'<a href="\{\{ url_for\(\'students\.student_profile\', student_id=student\.student_id\) if student else \'#\' \}\}".*?>',
    r'<a href="{{ url_for(\'students.student_profile\', student_id=student.student_id) if (student and student.student_id) else (url_for(\'main.dashboard\') if is_student_view else \'#\') }}" class="flex items-center gap-2 text-[var(--color-text-secondary)] dark:text-zinc-300 font-bold text-sm hover:text-primary transition-colors bg-[var(--color-bg-surface)] px-4 py-2.5 rounded-xl border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] no-underline clay-interactive">',
    html
)

# Вышеизложенная замена использует 'is_student_view', которая 100% есть в `app.context_processor`.

# Подстрахуем аватарку в шапке (где `student.student_id`)
html = re.sub(
    r'https://api\.dicebear\.com/7\.x/adventurer-neutral/svg\?seed=\{\{ student\.student_id if student else \'student_mock\' \}\}',
    r'https://api.dicebear.com/7.x/adventurer-neutral/svg?seed={{ student.student_id if (student and student.student_id) else (current_user.id if current_user.is_authenticated else \'mock\') }}',
    html
)
html = re.sub(
    r'\{\{ student\.name if student else \'Иван Иванов\' \}\}',
    r'{{ student.name if student else (current_user.name if current_user.is_authenticated else \'Ученик\') }}',
    html
)

# 2. Вернем полностью оригинальный блок <script>!
# Я скопирую его как есть из `lesson_homework_backup_jinja.html` и вставлю без изменений
with open('templates/lesson_homework_backup_jinja.html', 'r', encoding='utf-8') as b_f:
    backup_html = b_f.read()

# Найдем огромный блок JS скрипта
start_idx = backup_html.find('<script>\n        const LESSON_ID = {{ lesson.lesson_id }};')
end_idx = backup_html.rfind('{% endblock %}')

if start_idx != -1 and end_idx != -1:
    original_js = backup_html[start_idx:end_idx].strip()
    
    # Заменяем место перед `{% endblock %}`
    html = html.replace('\n{% endblock %}', '\n\n    ' + original_js + '\n{% endblock %}')

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
