with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Заголовки и обертка колонок
old_col_start = '''    <div class="lesson-room-workspace">
        <div class="lesson-room-main-column">'''

new_col_start = '''    <div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-8 items-start mt-4">
        <div class="lesson-room-main-column w-full min-w-0">'''
html = html.replace(old_col_start, new_col_start)

# 2. Обертка Конспекта (tab-theory)
old_theory_start = '''            <div id="tab-theory" class="tab-pane active">
        <div class="glass-panel">'''

new_theory_start = '''            <div id="tab-theory" class="tab-pane active">
        <div class="clay-card p-6 md:p-10 mb-8 max-w-4xl mx-auto flex flex-col gap-6">'''
html = html.replace(old_theory_start, new_theory_start)

# 3. Сайдбар перенос
old_sidebar_anchor = '''        </div>
            </div> <!-- end of lesson-room-main-column -->

        </div> <!-- end of lesson-room-workspace -->'''

new_sidebar_anchor = '''        </div>
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
                        <a id="tasknav-side-{{ lt.lesson_task_id }}" href="#task-{{ lt.lesson_task_id }}" class="task-nav-btn {{ nav_class }} !w-full !px-0 !h-auto !pt-[100%] !rounded-xl relative block no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                            <span class="absolute inset-0 flex items-center justify-center text-xl font-black">{{ loop.index }}</span>
                        </a>
                    {% endfor %}
                    {% endif %}
                </div>
            </div>
        </aside>

        </div> <!-- end of lesson-room-workspace -->'''
html = html.replace(old_sidebar_anchor, new_sidebar_anchor)


# 4. Обновляем CSS стили кнопок навигации внутри блока <style>
old_css_start = '''    .task-nav-btn {
        width: 36px;
        height: 36px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: transparent;
        border: 2px solid var(--stroke-2);
        color: var(--text-muted);
        font-weight: 700;
        font-size: 0.95rem;
        cursor: pointer;
        transition: all 0.2s ease;
        text-decoration: none;
    }

    .task-nav-btn:hover {
        border-color: var(--accent-1);
        color: var(--text-primary);
        transform: translateY(-2px);
    }
    
    .task-nav-btn.nav-correct {
        background: rgba(0, 254, 202, 0.1);
        border-color: var(--success);
        color: var(--success);
    }
    
    .task-nav-btn.nav-incorrect {
        background: rgba(255, 108, 145, 0.1);
        border-color: var(--danger);
        color: var(--danger);
    }

    .task-nav-btn.nav-returned {
        background: rgba(255, 212, 92, 0.12);
        border-color: var(--warning);
        color: var(--warning);
    }

    .task-nav-btn.nav-graded {
        background: rgba(31, 123, 255, 0.14);
        border-color: var(--accent-2);
        color: var(--accent-2);
    }'''

new_css_start = '''    .task-nav-btn {
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
    .task-nav-btn:active { transform: translateY(4px) !important; box-shadow: inset 0 4px 8px rgba(0,0,0,0.1) !important; }
    
    .task-nav-btn.nav-correct {
        background: var(--color-success) !important;
        border-color: rgba(0,0,0,0.1) !important;
        color: var(--color-bg-app) !important;
        box-shadow: 0 4px 12px rgba(34,211,238,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
    }
    html[data-theme="dark"] .task-nav-btn.nav-correct { box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important; }
    
    .task-nav-btn.nav-incorrect {
        background: var(--color-danger) !important;
        border-color: rgba(0,0,0,0.1) !important;
        color: #fff !important;
        box-shadow: 0 4px 12px rgba(251,113,133,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
    }
    html[data-theme="dark"] .task-nav-btn.nav-incorrect { box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important; }
    
    .task-nav-btn.nav-returned {
        background: var(--color-warning) !important;
        border-color: rgba(0,0,0,0.1) !important;
        color: #fff !important;
        box-shadow: 0 4px 12px rgba(245,158,11,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
    }
    html[data-theme="dark"] .task-nav-btn.nav-returned { box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important; }
    
    .task-nav-btn.nav-graded {
        background: var(--color-primary) !important;
        border-color: rgba(0,0,0,0.1) !important;
        color: #fff !important;
        box-shadow: 0 4px 12px rgba(79,70,229,0.3), inset 0 -4px 0 rgba(0,0,0,0.15) !important;
    }
    html[data-theme="dark"] .task-nav-btn.nav-graded { box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 -4px 0 rgba(0,0,0,0.3) !important; }'''

html = html.replace(old_css_start, new_css_start)

# 5. Стилизация карточек задач
old_task_card = '''        .task-card {
            border-radius: var(--radius-lg);
            background: var(--surface-2);
            border: 1px solid var(--stroke-1);
            padding: 1.5rem;
            position: relative;
            box-shadow: var(--shadow-sm);
        }'''
new_task_card = '''        .task-card {
            border-radius: 28px;
            background: var(--color-bg-surface);
            padding: 2.5rem;
            position: relative;
            margin-top: 1rem;
            box-shadow: var(--clay-shadow-out), var(--clay-shadow-in);
            border: none;
        }'''
html = html.replace(old_task_card, new_task_card)

# 6. Добавим стилизацию для инпутов, чтобы они выглядели как вдавленные Claymorphism элементы.
css_inputs = '''
    .task-content textarea, .task-content input[type="text"] {
        border-radius: 1rem !important;
        background: var(--color-bg-surface) !important;
        border: 2px solid var(--color-stroke) !important;
        box-shadow: inset 0 4px 12px rgba(0,0,0,0.02) !important;
        font-weight: 700 !important;
        font-size: 1.15rem !important;
        padding: 1rem 1.5rem !important;
    }
    html[data-theme="dark"] .task-content textarea, html[data-theme="dark"] .task-content input[type="text"] {
        background: var(--color-bg-surface-alt) !important;
        border-color: rgba(255,255,255,0.1) !important;
    }
    .task-content textarea:focus, .task-content input[type="text"]:focus {
        border-color: var(--color-primary) !important;
        box-shadow: inset 0 4px 12px rgba(0,0,0,0.02), 0 0 0 4px color-mix(in srgb, var(--color-primary) 20%, transparent) !important;
        outline: none !important;
    }
'''
html = html.replace('</style>', css_inputs + '\n    </style>')

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
