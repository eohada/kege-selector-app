import re

with open('templates/lesson_homework_backup_jinja.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Back button
html = re.sub(
    r'<div class="flex items-center">\s*<a href="\{\{ url_for\(\'students\.student_profile\'.*?</a>\s*</div>',
    r'''<div class="flex items-center">
    <a href="{{ url_for('students.student_profile', student_id=student.student_id) if is_student_view or is_parent_view else url_for('main.dashboard') }}" class="flex items-center w-fit gap-2 text-[var(--color-text-secondary)] dark:text-zinc-300 font-bold text-sm hover:text-primary transition-colors bg-[var(--color-bg-surface)] px-4 py-2.5 rounded-xl border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] no-underline clay-interactive">
        <i class="ph-bold ph-arrow-left text-lg"></i> Назад
    </a>
</div>''',
    html,
    flags=re.DOTALL
)

# 2. Header
new_header = r'''<div class="mt-2 mb-2 px-2 flex justify-between items-start flex-wrap gap-4">
    <div>
        <h1 class="text-4xl md:text-5xl font-black mb-6 leading-tight text-[var(--color-text-primary)] dark:drop-shadow-none">{{ lesson.topic or 'Тема не указана' }}</h1>
        <div class="flex flex-wrap items-center gap-3">
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <i class="ph-fill ph-calendar-blank text-primary text-lg"></i> {{ lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else '—' }}
            </span>
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <i class="ph-fill ph-clock text-primary text-lg"></i> {{ lesson.duration }} мин
            </span>
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <img src="https://api.dicebear.com/7.x/adventurer-neutral/svg?seed={{ (student.name or student.student_id|string)|urlencode }}&backgroundColor=F3F0FF" alt="" class="w-6 h-6 rounded-md bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shrink-0">
                {{ student.name }}
            </span>
            <span class="px-4 py-2 bg-info/10 text-info border border-info/30 rounded-xl font-extrabold text-[0.7rem] uppercase tracking-widest shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">
                {% if assignment_type == 'homework' %}Домашняя работа{% elif assignment_type == 'classwork' %}Классная работа{% else %}Экзамен{% endif %}
            </span>
        </div>
    </div>
    <div class="flex flex-wrap items-center gap-3 shrink-0 mt-4 md:mt-0">
        {% if not is_student_view and not is_parent_view %}
        <a href="{{ url_for('assignments.assignment_create', source='lesson', lesson_id=lesson.lesson_id, assignment_type='homework') }}" class="clay-interactive neo-button accent !shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-2px_0_rgba(0,0,0,0.1)]">
            <i class="ph-bold ph-house-line text-lg"></i> Создать ДЗ
        </a>
        <a href="{{ url_for('lessons.lesson_edit', lesson_id=lesson.lesson_id) }}" class="clay-interactive px-4 py-2 rounded-xl bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] font-bold text-[var(--color-text-primary)] shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-2px_0_rgba(0,0,0,0.05)] hover:-translate-y-0.5" title="Редактировать">
            <i class="ph-bold ph-pencil-simple text-lg"></i>
        </a>
        <button type="button" class="clay-interactive px-4 py-2 rounded-xl bg-danger/10 border border-danger/30 text-danger shadow-[inset_0_-2px_0_rgba(239,68,68,0.2)] hover:-translate-y-0.5" title="Удалить урок" onclick="deleteLesson({{ lesson.lesson_id }}, {{ student.student_id }})">
            <i class="ph-bold ph-trash text-lg"></i>
        </button>
        {% endif %}
        {% if is_student_view %}
        <a href="{{ url_for('assignments.submissions_list') }}" class="clay-interactive neo-button neo-outline">
            <i class="ph-bold ph-check-square-offset text-lg"></i> К заданиям
        </a>
        {% endif %}
    </div>
</div>'''
html = re.sub(r'<header class="lesson-header">.*?</header>', new_header, html, flags=re.DOTALL)

# 3. Tabs
new_tabs = r'''<div class="flex gap-2 mb-6 overflow-x-auto pb-2 hide-scroll sticky top-2 z-[40] bg-[var(--color-bg-app)]/80 backdrop-blur-xl p-2 rounded-2xl border border-[var(--color-stroke)] shadow-[0_4px_12px_rgba(0,0,0,0.05)]" role="tablist">
    <button type="button" class="clay-interactive tab-btn active flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="theory" role="tab">
        <i class="ph-bold ph-book-open text-lg"></i> Конспект
    </button>
    <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="tasks" role="tab">
        <i class="ph-bold ph-chalkboard-teacher text-lg"></i> Задания
    </button>
    <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="materials" role="tab">
        <i class="ph-bold ph-paperclip text-lg"></i> Материалы
    </button>
    {% if not is_student_view %}
    <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="notes" role="tab">
        <i class="ph-bold ph-note text-lg"></i> Заметки ученика
    </button>
    {% endif %}
    <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="whiteboard" role="tab">
        <i class="ph-bold ph-presentation-chart text-lg"></i> Доска
    </button>
</div>'''
html = re.sub(r'<div class="lesson-tabs hide-scroll" role="tablist">.*?</div>\n', new_tabs + '\n', html, flags=re.DOTALL)

# 4. Content Containers (CSS Grid)
html = html.replace('<div class="flex flex-col gap-6 w-full">', '<div class="flex flex-col gap-6 w-full max-w-[1600px] mx-auto pb-16">')
html = html.replace('<div class="lesson-room-workspace">', '<div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-10 items-start mt-4">')
html = html.replace('<div class="lesson-room-main-column">', '<div class="lesson-room-main-column w-full min-w-0">')

# 5. Overriding old styles with Claymorphism Squish variables inside CSS block
squish_css = r'''
/* ===== CLAYMORPHISM OVERRIDES FOR JINJA FORM LOGIC ===== */
.task-nav-btn {
    height: 3.5rem !important;
    padding: 0 2rem !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    border-radius: 1rem !important;
    font-weight: 900 !important;
    font-size: 1.25rem !important;
    transition: all 0.15s !important;
    background: var(--color-bg-surface-alt) !important;
    border: 1px solid var(--color-stroke) !important;
    color: var(--color-text-muted) !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05), inset 0 -4px 0 rgba(0,0,0,0.08) !important;
    cursor: pointer !important;
    text-decoration: none !important;
}
html[data-theme="dark"] .task-nav-btn { color: #d4d4d8 !important; }
.task-nav-btn:hover { transform: translateY(-2px) !important; }
.task-nav-btn:active {
    transform: translateY(4px) !important;
    box-shadow: inset 0 4px 8px rgba(0,0,0,0.1) !important;
}
.task-nav-btn.nav-correct {
    background: var(--color-success) !important;
    border-color: rgba(0,0,0,0.1) !important;
    color: var(--color-bg-app) !important;
    box-shadow: 0 4px 12px rgba(34,211,238,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
}
html[data-theme="dark"] .task-nav-btn.nav-correct {
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important;
}
.task-nav-btn.nav-incorrect {
    background: var(--color-danger) !important;
    border-color: rgba(0,0,0,0.1) !important;
    color: #fff !important;
    box-shadow: 0 4px 12px rgba(251,113,133,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
}
html[data-theme="dark"] .task-nav-btn.nav-incorrect {
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important;
}
.task-nav-btn.nav-returned {
    background: var(--color-warning) !important;
    border-color: rgba(0,0,0,0.1) !important;
    color: #fff !important;
    box-shadow: 0 4px 12px rgba(245,158,11,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
}
html[data-theme="dark"] .task-nav-btn.nav-returned {
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important;
}
.task-nav-btn.nav-graded {
    background: var(--color-primary) !important;
    border-color: rgba(0,0,0,0.1) !important;
    color: #fff !important;
    box-shadow: 0 4px 12px rgba(79,70,229,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
}
html[data-theme="dark"] .task-nav-btn.nav-graded {
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important;
}

/* Перехват стилей полей ввода и кнопок ответа */
body .lesson-room-workspace .neo-input {
    background: var(--color-bg-surface) !important;
    border: 2px solid var(--color-stroke) !important;
    border-radius: 1rem !important;
    height: 4rem !important;
    font-weight: 700 !important;
    box-shadow: inset 0 4px 12px rgba(0,0,0,0.02) !important;
    font-size: 1.15rem !important;
}
body .lesson-room-workspace .neo-input:focus {
    border-color: var(--color-primary) !important;
    box-shadow: inset 0 4px 12px rgba(0,0,0,0.02), 0 0 0 4px color-mix(in srgb, var(--color-primary) 20%, transparent) !important;
}
body .lesson-room-workspace button[type="submit"] {
    background: #4F46E5 !important;
    color: white !important;
    border-radius: 1rem !important;
    height: 4rem !important;
    font-weight: 900 !important;
    font-size: 1.25rem !important;
    border: 1px solid #3730A3 !important;
    box-shadow: 0 8px 24px rgba(79,70,229,0.3), inset 0 -4px 0 rgba(0,0,0,0.2) !important;
    transition: all 0.15s !important;
}
html[data-theme="dark"] body .lesson-room-workspace button[type="submit"] {
    box-shadow: 0 4px 12px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important;
}
body .lesson-room-workspace button[type="submit"]:active {
    transform: translateY(4px) !important;
    box-shadow: inset 0 4px 8px rgba(0,0,0,0.3) !important;
}
'''
html = html.replace('</style>', squish_css + '\n    </style>')

# 6. Theory modifications
# Remove the old glass-panel wrapping theory
html = html.replace('<div class="glass-panel">', '<div class="flex flex-col gap-6 max-w-4xl mx-auto py-4">', 1)
# Update callouts
old_callout = r'''\{\% set tone = b\.tone or 'info' \%\}[\s\S]*?<div style="border: 1px solid \{\{ border \}\}; background: \{\{ bg \}\}; border-radius: var\(--radius-md\); padding: 1rem;">[\s\S]*?\{\% if b\.title \%\}<div style="font-weight: 900; margin-bottom: 0\.35rem;">\{\{ b\.title \}\}</div>\{\% endif \%\}[\s\S]*?<div style="white-space: pre-wrap; line-height: 1\.65;">\{\{ b\.text \}\}</div>[\s\S]*?</div>'''
new_callout = r'''{% set tone = b.tone or 'info' %}
                            {% set clr = 'var(--color-primary)' if tone == 'info' else ('var(--color-success)' if tone == 'success' else ('var(--color-warning)' if tone == 'warning' else 'var(--color-danger)')) %}
                            <div class="rounded-3xl p-6 relative overflow-hidden my-4" style="background: color-mix(in srgb, {{ clr }} 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, {{ clr }} 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, {{ clr }} 10%, transparent);">
                                <div class="absolute left-0 top-0 bottom-0 w-2" style="background: {{ clr }};"></div>
                                {% if b.title %}
                                <div class="font-bold text-xl mb-2 flex items-center gap-2" style="color: {{ clr }};">
                                    <i class="ph-fill ph-info"></i> {{ b.title }}
                                </div>
                                {% endif %}
                                <div class="font-medium text-[var(--color-text-secondary)] dark:text-zinc-300 leading-relaxed text-lg whitespace-pre-wrap">{{ b.text }}</div>
                            </div>'''
html = re.sub(old_callout, new_callout, html)

# Update images
old_img = r'''<div style="border: 1px solid var\(--stroke-1\); background: rgba\(255,255,255,0\.02\); border-radius: var\(--radius-md\); padding: 0\.85rem;">[\s\S]*?</div>'''
new_img = r'''<div class="bg-[var(--color-bg-inset)] rounded-[32px] p-4 border border-[var(--color-stroke)] shadow-[inset_0_4px_12px_rgba(0,0,0,0.05)] my-6">
                                {% if b.url %}<img src="{{ b.url }}" alt="image" class="w-full max-h-[520px] object-cover rounded-[24px] shadow-sm">{% endif %}
                                {% if b.caption %}<div class="text-[var(--color-text-muted)] dark:text-zinc-300 text-xs mt-4 text-center font-black uppercase tracking-widest">{{ b.caption }}</div>{% endif %}
                            </div>'''
html = re.sub(old_img, new_img, html)

# 7. Update Task Cards mapping
html = html.replace('class="task-card', 'class="task-card clay-card p-10 mt-4')
html = re.sub(
    r'<div class="task-header">\s*<div class="task-number">\s*<span>(.*?)</span>\s*</div>',
    r'''<div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)] pt-4">
        <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-none">\1</span> Задание''',
    html
)
html = html.replace('class="task-nav-bar', 'class="task-nav-bar clay-card flex flex-wrap justify-center gap-4 pt-6 pb-6 px-6')

# 8. Add Sidebar to Grid
sidebar = r'''
        </div> <!-- end of lesson-room-main-column -->

        <!-- ПРАВАЯ КОЛОНКА (Сайдбар) -->
        <aside class="hidden xl:flex flex-col gap-8 sticky top-24 z-10 w-full" id="lesson-sidebar">
            <div class="clay-card p-6 flex flex-col gap-5 relative overflow-hidden">
                <div class="absolute -right-12 -top-12 w-40 h-40 bg-primary/20 rounded-full blur-[40px] pointer-events-none"></div>
                
                <div class="flex items-center justify-between mb-2 relative z-10">
                    <div class="text-xs font-black uppercase tracking-widest text-[var(--color-text-muted)] dark:text-zinc-300">До конца урока</div>
                    <div class="px-3 py-1.5 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] text-primary rounded-xl font-black text-sm shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] flex items-center gap-1.5">
                        <i class="ph-bold ph-hourglass text-lg"></i> {{ lesson.duration }} мин
                    </div>
                </div>
                
                <div class="h-px w-full bg-[var(--color-stroke)] my-2 relative z-10"></div>
                
                <div class="flex items-center gap-4 mt-1 relative z-10">
                    <div class="w-16 h-16 rounded-[1.25rem] bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] shadow-[0_4px_12px_rgba(0,0,0,0.05),inset_0_-2px_0_rgba(0,0,0,0.05)] overflow-hidden shrink-0">
                        {% if lesson.author and lesson.author.avatar_url %}
                        <img src="{{ url_for('static', filename='uploads/avatars/' + lesson.author.avatar_url) }}" alt="teacher" class="w-full h-full object-cover">
                        {% else %}
                        <img src="https://api.dicebear.com/7.x/shapes/svg?seed={{ lesson.author_id or 'teacher' }}&backgroundColor=F3F0FF" alt="teacher" class="w-full h-full object-cover">
                        {% endif %}
                    </div>
                    <div class="min-w-0">
                        <div class="text-[0.65rem] font-black text-primary mb-1 uppercase tracking-widest">Преподаватель</div>
                        <div class="font-black text-[var(--color-text-primary)] truncate text-xl">
                            {% if lesson.author %}{{ lesson.author.name }}{% else %}Виктор Соколов{% endif %}
                        </div>
                    </div>
                </div>
                <button class="clay-interactive mt-4 w-full h-14 inline-flex items-center justify-center gap-2 bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-primary font-black rounded-2xl shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.05)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] transition-all hover:brightness-[0.97] relative z-10">
                    <i class="ph-bold ph-chat-circle-dots text-2xl"></i> Написать в чат
                </button>
            </div>
            
            <div class="clay-card p-6">
                <div class="font-black text-xl text-[var(--color-text-primary)] mb-6 flex items-center justify-between">
                    <span>Задания</span>
                    <span class="text-xs px-2.5 py-1.5 bg-[var(--color-bg-inset)] rounded-[10px] text-[var(--color-text-secondary)] dark:text-zinc-300 border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] font-extrabold uppercase">
                        {{ current_task_nav_list|length if current_task_nav_list else 0 }} задач
                    </span>
                </div>
                
                <div class="grid grid-cols-4 gap-3">
                    {% if current_task_nav_list %}
                    {% for lt in current_task_nav_list %}
                        {% set user_ans = user_answers_dict.get(lt.lesson_task_id) %}
                        {% set user_status = user_ans.status if user_ans else 'none' %}
                        {% set user_score = user_ans.score if user_ans else 0 %}
                        {% set nav_class = '' %}
                        {% if user_status == 'correct' or user_status == 'graded' and user_score == lt.lesson_task.max_score %}
                            {% set nav_class = 'nav-correct' %}
                        {% elif user_status == 'incorrect' %}
                            {% set nav_class = 'nav-incorrect' %}
                        {% elif user_status == 'returned' %}
                            {% set nav_class = 'nav-returned' %}
                        {% elif user_status == 'graded' %}
                            {% set nav_class = 'nav-graded' %}
                        {% endif %}
                        <a href="#task-{{ lt.lesson_task_id }}" class="task-nav-btn {{ nav_class }} !h-auto !pt-[100%] !w-full !px-0" onclick="document.querySelector('[data-tab=\'tasks\']').click();" style="position:relative;">
                            <span class="absolute inset-0 flex items-center justify-center text-xl">{{ loop.index }}</span>
                        </a>
                    {% endfor %}
                    {% endif %}
                </div>
            </div>
        </aside>
'''
html = html.replace('</div>\n        </div>\n            </div> <!-- end of lesson-room-main-column -->', sidebar + '\n        </div>')

# 9. Add Vanilla JS logic at the very end
js = r'''
<!-- Vanilla JS Переключатель Табов -->
<script>
    document.addEventListener('DOMContentLoaded', function() {
        const tabBtns = document.querySelectorAll('[role="tablist"] .tab-btn');
        const tabPanes = document.querySelectorAll('.tab-pane');
        
        tabBtns.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const targetId = 'tab-' + this.dataset.tab;
                const targetPane = document.getElementById(targetId);
                if (!targetPane) return;
                
                tabBtns.forEach(b => b.classList.remove('active'));
                
                tabPanes.forEach(pane => {
                    pane.style.opacity = '0';
                    setTimeout(() => {
                        pane.classList.remove('block');
                        pane.classList.add('hidden');
                        pane.classList.remove('active');
                    }, 300);
                });
                
                this.classList.add('active');
                
                setTimeout(() => {
                    targetPane.classList.remove('hidden');
                    targetPane.classList.add('block');
                    targetPane.classList.add('active');
                    
                    requestAnimationFrame(() => {
                        targetPane.style.opacity = '1';
                    });
                }, 350);
            });
        });
        
        // Hide unused on load
        tabPanes.forEach(pane => {
            if(!pane.classList.contains('active')) {
                pane.classList.add('hidden');
                pane.style.opacity = '0';
            } else {
                pane.classList.add('block');
                pane.style.opacity = '1';
            }
        });
    });
</script>
'''
html = html.replace('{% endblock %}', js + '\n{% endblock %}')

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
