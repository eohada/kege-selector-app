const fs = require('fs');

const staticContent = `{% extends 'base.html' %}
{% block html_attrs %}data-student-lesson-room="1"{% endblock %}
{% block title %}{{ lesson.topic or 'Урок' }} · BooStudy{% endblock %}
{% block body_class %}layout-student min-h-screen{% endblock %}

{% block content %}
<div class="flex flex-col gap-6 w-full max-w-[1600px] mx-auto pb-16">
    <!-- Кнопка назад -->
    <div class="flex items-center">
        <a href="{{ url_for('students.student_profile', student_id=student.student_id) if student else '#' }}" class="flex items-center gap-2 text-[var(--color-text-secondary)] dark:text-zinc-300 font-bold text-sm hover:text-primary transition-colors bg-[var(--color-bg-surface)] px-4 py-2.5 rounded-xl border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] no-underline clay-interactive">
            <i class="ph-bold ph-arrow-left text-lg"></i> Назад в профиль
        </a>
    </div>

    <!-- Заголовок урока -->
    <div class="mt-2 mb-2 px-2">
        <h1 class="text-4xl md:text-5xl font-black mb-6 leading-tight text-[var(--color-text-primary)] dark:drop-shadow-none">{{ lesson.topic or 'Тема не указана' }}</h1>
        <div class="flex flex-wrap items-center gap-3">
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <i class="ph-fill ph-calendar-blank text-primary text-lg"></i> {{ lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson and lesson.lesson_date else '—' }}
            </span>
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <i class="ph-fill ph-clock text-primary text-lg"></i> {{ lesson.duration if lesson else 0 }} мин
            </span>
            <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                <img src="https://api.dicebear.com/7.x/adventurer-neutral/svg?seed={{ student.student_id if student else 'student_mock' }}&backgroundColor=F3F0FF" alt="" class="w-6 h-6 rounded-md bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shrink-0">
                {{ student.name if student else 'Иван Иванов' }}
            </span>
            <span class="px-4 py-2 bg-info/10 text-info border border-info/30 rounded-xl font-extrabold text-[0.7rem] uppercase tracking-widest shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">
                {% if assignment_type == 'homework' %}Домашняя работа{% elif assignment_type == 'exam' %}Экзамен{% else %}Классная работа{% endif %}
            </span>
        </div>
    </div>

    <!-- Плавающие табы навигации -->
    <div class="flex gap-2 pb-2 overflow-x-auto hide-scroll sticky top-2 z-[40] bg-[var(--color-bg-app)]/80 backdrop-blur-xl p-2 rounded-2xl border border-[var(--color-stroke)] shadow-[0_4px_12px_rgba(0,0,0,0.05)]" role="tablist">
        <button type="button" class="clay-interactive tab-btn active flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="theory" role="tab">
            <i class="ph-bold ph-book-open text-lg"></i> Конспект
        </button>
        <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="tasks" role="tab">
            <i class="ph-bold ph-chalkboard-teacher text-lg"></i> Классная работа
        </button>
        <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-transparent shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="materials" role="tab">
            <i class="ph-bold ph-paperclip text-lg"></i> Материалы
        </button>
    </div>

    <!-- ИДЕАЛЬНАЯ СЕТКА: strictly Grid -->
    <div class="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-10 items-start mt-4">
        
        <!-- ЛЕВАЯ КОЛОНКА (Контент) -->
        <div class="w-full min-w-0">
            
            <!-- ====== КОНСПЕКТ ====== -->
            <div id="tab-theory" class="tab-pane block" style="transition: opacity 0.3s ease; opacity: 1;">
                <div class="flex flex-col gap-6 max-w-4xl mx-auto py-4">
                    {% if content_blocks and content_blocks|length > 0 %}
                        {% for b in content_blocks %}
                            {% if b.type == 'paragraph' %}
                                <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4 whitespace-pre-wrap">{{ b.text }}</p>
                            {% elif b.type == 'callout' %}
                                {% set tone = b.tone or 'info' %}
                                {% set clr = 'var(--color-primary)' if tone == 'info' else ('var(--color-success)' if tone == 'success' else ('var(--color-warning)' if tone == 'warning' else 'var(--color-danger)')) %}
                                <div class="rounded-3xl p-6 relative overflow-hidden my-4" style="background: color-mix(in srgb, {{ clr }} 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, {{ clr }} 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, {{ clr }} 10%, transparent);">
                                    <div class="absolute left-0 top-0 bottom-0 w-2" style="background: {{ clr }};"></div>
                                    {% if b.title %}
                                    <div class="font-bold text-xl mb-2 flex items-center gap-2" style="color: {{ clr }};">
                                        <i class="ph-fill ph-info"></i> {{ b.title }}
                                    </div>
                                    {% endif %}
                                    <div class="font-medium text-[var(--color-text-secondary)] dark:text-zinc-300 leading-relaxed text-lg whitespace-pre-wrap">{{ b.text }}</div>
                                </div>
                            {% elif b.type == 'image' %}
                                <div class="bg-[var(--color-bg-inset)] rounded-[32px] p-4 border border-[var(--color-stroke)] shadow-[inset_0_4px_12px_rgba(0,0,0,0.05)] my-6">
                                    <img src="{{ b.url }}" alt="image" class="w-full max-h-[520px] object-cover rounded-[24px] shadow-sm">
                                    {% if b.caption %}
                                    <div class="text-[var(--color-text-muted)] dark:text-zinc-300 text-xs mt-4 text-center font-black uppercase tracking-widest">{{ b.caption }}</div>
                                    {% endif %}
                                </div>
                            {% elif b.type == 'divider' %}
                                <div class="h-px w-full bg-[var(--color-stroke)] my-6 opacity-60"></div>
                            {% endif %}
                        {% endfor %}
                    {% else %}
                        <!-- MOCK CONTENT -->
                        <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4">
                            Добро пожаловать в новый визуальный стиль платформы BooStudy! Этот стиль построен на мягких тенях, глубоких градиентах и тактильных элементах, которые хочется нажимать. Обрати внимание: теперь текст лежит прямо на фоне страницы — никакого лишнего "коробочного" дизайна, только чистый контент (Notion-style).
                        </p>

                        <div class="rounded-3xl p-6 relative overflow-hidden my-4" style="background: color-mix(in srgb, var(--color-primary) 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, var(--color-primary) 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, var(--color-primary) 10%, transparent);">
                            <div class="absolute left-0 top-0 bottom-0 w-2" style="background: var(--color-primary);"></div>
                            <div class="font-bold text-xl mb-2 flex items-center gap-2" style="color: var(--color-primary);"><i class="ph-fill ph-info"></i> Что такое Claymorphism?</div>
                            <div class="font-medium text-[var(--color-text-secondary)] dark:text-zinc-300 leading-relaxed text-lg">Он отличается от неоморфизма тем, что добавляет объем не только за счет света, но и за счет глубокого цвета и закругленных форм. Интерфейс выглядит как гладкая вылепленная глина.</div>
                        </div>
                    {% endif %}
                </div>
            </div>

            <!-- ====== КЛАССНАЯ РАБОТА ====== -->
            <div id="tab-tasks" class="tab-pane hidden" style="transition: opacity 0.3s ease; opacity: 0;">
                <div class="max-w-4xl mx-auto flex flex-col gap-6 py-4">
                    
                    <!-- Навигация по задачам (Squish effect) -->
                    <div class="clay-card p-6 flex flex-wrap justify-center gap-4">
                        {% if current_task_nav_list %}
                            {% for lt in current_task_nav_list %}
                                {% set user_ans = user_answers_dict.get(lt.lesson_task_id) %}
                                {% set user_status = user_ans.status if user_ans else 'none' %}
                                {% set user_score = user_ans.score if user_ans else 0 %}
                                
                                {% if user_status == 'correct' or user_status == 'graded' and user_score == lt.lesson_task.max_score %}
                                    {% set btn_class = '!bg-[var(--color-success)] !border-[rgba(0,0,0,0.1)] !text-[var(--color-bg-app)] !shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                                {% elif user_status == 'incorrect' %}
                                    {% set btn_class = '!bg-[var(--color-danger)] !border-[rgba(0,0,0,0.1)] text-white !shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                                {% elif user_status == 'returned' %}
                                    {% set btn_class = '!bg-[var(--color-warning)] !border-[rgba(0,0,0,0.1)] text-white !shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                                {% else %}
                                    {% set btn_class = 'bg-[var(--color-bg-surface-alt)] border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.08)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)]' %}
                                {% endif %}
                                
                                <button class="clay-interactive h-14 px-8 inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 {{ btn_class }}">
                                    {{ loop.index }}
                                </button>
                            {% endfor %}
                        {% else %}
                            <button class="clay-interactive h-14 px-8 inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.08)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] hover:-translate-y-0.5">1</button>
                        {% endif %}
                    </div>

                    <!-- Форма Задачи -->
                    {% if homework_tasks %}
                        {% for hw_task in homework_tasks %}
                        <div class="clay-card p-10 mt-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-none">{{ loop.index }}</span>
                                {% if hw_task.lesson_task.title %}{{ hw_task.lesson_task.title }}{% else %}Задание по теории{% endif %}
                            </div>
                            <div class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">{{ hw_task.lesson_task.content | safe }}</div>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                {% set user_ans = user_answers_dict.get(hw_task.lesson_task_id) %}
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Ваш ответ:</label>
                                
                                {% if hw_task.lesson_task.task_type == 'detailed' %}
                                <textarea class="w-full h-32 bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] rounded-2xl p-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300">{{ user_ans.answer_detailed if user_ans and user_ans.answer_detailed else '' }}</textarea>
                                {% else %}
                                <input type="text" value="{{ user_ans.answer_short if user_ans and user_ans.answer_short else '' }}" class="w-full h-16 bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите ответ...">
                                {% endif %}
                            </div>
                        </div>
                        {% endfor %}
                        <button class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110">
                            Сохранить всё
                        </button>
                    {% else %}
                        <!-- Mock Task -->
                        <div class="clay-card p-10 mt-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-none">1</span>
                                Задание по теории
                            </div>
                            <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium">
                                Определите, какой атрибут CSS отвечает за создание мягких размытых краев внутри элемента, характерных для стиля Claymorphism. (Введите одно слово)
                            </p>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Ваш ответ:</label>
                                <input type="text" class="w-full h-16 bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите ответ...">
                                
                                <button class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110">
                                    Сохранить ответ
                                </button>
                            </div>
                        </div>
                    {% endif %}
                </div>
            </div>
            
            <!-- ====== МАТЕРИАЛЫ ====== -->
            <div id="tab-materials" class="tab-pane hidden" style="transition: opacity 0.3s ease; opacity: 0;">
                <div class="max-w-4xl mx-auto py-10">
                    <div class="bg-[var(--color-bg-inset)] rounded-[40px] p-16 flex flex-col items-center justify-center text-center border-dashed border-4 border-[var(--color-stroke)] hidden-shadow">
                        <div class="w-28 h-28 bg-[var(--color-bg-surface)] rounded-[2rem] flex items-center justify-center shadow-[0_8px_24px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.02)] border border-[var(--color-stroke)] mb-8">
                            <i class="ph-fill ph-file-pdf text-6xl text-primary opacity-80"></i>
                        </div>
                        <h3 class="text-3xl font-black text-[var(--color-text-primary)] mb-4">Материалов пока нет</h3>
                        <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium max-w-lg">Здесь будут отображаться дополнительные файлы, презентации и ссылки, прикрепленные преподавателем.</p>
                    </div>
                </div>
            </div>

        </div> <!-- /Левая колонка -->

        <!-- ПРАВАЯ КОЛОНКА (Сайдбар) -->
        <aside class="hidden xl:flex flex-col gap-8 sticky top-24 z-10 w-full" id="lesson-sidebar">
                
            <!-- Виджет преподавателя (Clay Card) -->
            <div class="clay-card p-6 flex flex-col gap-5 relative overflow-hidden">
                <div class="absolute -right-12 -top-12 w-40 h-40 bg-primary/20 rounded-full blur-[40px] pointer-events-none"></div>
                
                <div class="flex items-center justify-between mb-2 relative z-10">
                    <div class="text-xs font-black uppercase tracking-widest text-[var(--color-text-muted)] dark:text-zinc-300">До конца урока</div>
                    <div class="px-3 py-1.5 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] text-primary rounded-xl font-black text-sm shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] flex items-center gap-1.5">
                        <i class="ph-bold ph-hourglass text-lg"></i> {{ lesson.duration if lesson else 90 }} мин
                    </div>
                </div>
                
                <div class="h-px w-full bg-[var(--color-stroke)] my-2 relative z-10"></div>
                
                <div class="flex items-center gap-4 mt-1 relative z-10">
                    <!-- Аватар 'выпуклый' в сайдбаре -->
                    <div class="w-16 h-16 rounded-[1.25rem] bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] shadow-[0_4px_12px_rgba(0,0,0,0.05),inset_0_-2px_0_rgba(0,0,0,0.05)] overflow-hidden shrink-0">
                        {% if lesson and lesson.author and lesson.author.avatar_url %}
                        <img src="{{ url_for('static', filename='uploads/avatars/' + lesson.author.avatar_url) }}" alt="teacher" class="w-full h-full object-cover">
                        {% else %}
                        <img src="https://api.dicebear.com/7.x/shapes/svg?seed={{ lesson.author_id if lesson and lesson.author else 'teacher_pro' }}&backgroundColor=F3F0FF" alt="teacher" class="w-full h-full object-cover">
                        {% endif %}
                    </div>
                    <div class="min-w-0">
                        <div class="text-[0.65rem] font-black text-primary mb-1 uppercase tracking-widest">Преподаватель</div>
                        <div class="font-black text-[var(--color-text-primary)] truncate text-xl">
                            {{ lesson.author.name if lesson and lesson.author else 'Илья Муромец' }}
                        </div>
                    </div>
                </div>
                
                <button class="clay-interactive mt-4 w-full h-14 inline-flex items-center justify-center gap-2 bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-primary font-black rounded-2xl shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.05)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] transition-all hover:brightness-[0.97] relative z-10">
                    <i class="ph-bold ph-chat-circle-dots text-2xl"></i> Написать в чат
                </button>
            </div>
            
            <!-- Миникарта заданий -->
            <div class="clay-card p-6">
                <div class="font-black text-xl text-[var(--color-text-primary)] mb-6 flex items-center justify-between">
                    <span>Задания</span>
                    <span class="text-xs px-2.5 py-1.5 bg-[var(--color-bg-inset)] rounded-[10px] text-[var(--color-text-secondary)] dark:text-zinc-300 border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] font-extrabold uppercase">
                        {{ current_task_nav_list|length if current_task_nav_list else 4 }} задачи
                    </span>
                </div>
                
                <!-- Squish-мини кнопки -->
                <div class="grid grid-cols-4 gap-3">
                    {% if current_task_nav_list %}
                        {% for lt in current_task_nav_list %}
                            {% set user_ans = user_answers_dict.get(lt.lesson_task_id) %}
                            {% set user_status = user_ans.status if user_ans else 'none' %}
                            {% set user_score = user_ans.score if user_ans else 0 %}
                            
                            {% if user_status == 'correct' or user_status == 'graded' and user_score == lt.lesson_task.max_score %}
                                {% set mini_class = '!bg-[var(--color-success)] !border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-[var(--color-bg-app)] active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                            {% elif user_status == 'incorrect' %}
                                {% set mini_class = '!bg-[var(--color-danger)] !border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-white active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                            {% elif user_status == 'returned' %}
                                {% set mini_class = '!bg-[var(--color-warning)] !border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-white active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)]' %}
                            {% else %}
                                {% set mini_class = 'bg-[var(--color-bg-surface-alt)] border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.05)] active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)]' %}
                            {% endif %}
                            
                            <div class="clay-interactive w-full pt-[100%] relative rounded-xl border font-black hover:-translate-y-0.5 active:translate-y-1 cursor-pointer transition-all {{ mini_class }}" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                                <div class="absolute inset-0 flex items-center justify-center text-xl">{{ loop.index }}</div>
                            </div>
                        {% endfor %}
                    {% else %}
                        <div class="clay-interactive w-full pt-[100%] relative rounded-xl border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.05)] bg-[var(--color-bg-surface-alt)] font-black text-[var(--color-text-muted)] dark:text-zinc-300 hover:-translate-y-0.5 active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] cursor-pointer" onclick="document.querySelector('[data-tab=\'tasks\']').click();"><div class="absolute inset-0 flex items-center justify-center text-xl">1</div></div>
                        <div class="clay-interactive w-full pt-[100%] relative rounded-xl bg-[var(--color-success)] border border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-[var(--color-bg-app)] font-black hover:-translate-y-0.5 active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] cursor-pointer" onclick="document.querySelector('[data-tab=\'tasks\']').click();"><div class="absolute inset-0 flex items-center justify-center text-xl">2</div></div>
                        <div class="clay-interactive w-full pt-[100%] relative rounded-xl bg-[var(--color-danger)] border border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-white font-black hover:-translate-y-0.5 active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] cursor-pointer" onclick="document.querySelector('[data-tab=\'tasks\']').click();"><div class="absolute inset-0 flex items-center justify-center text-xl">3</div></div>
                        <div class="clay-interactive w-full pt-[100%] relative rounded-xl bg-[var(--color-warning)] border border-[rgba(0,0,0,0.1)] shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] text-white font-black hover:-translate-y-0.5 active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] cursor-pointer" onclick="document.querySelector('[data-tab=\'tasks\']').click();"><div class="absolute inset-0 flex items-center justify-center text-xl">4</div></div>
                    {% endif %}
                </div>
            </div>
            
        </aside>

    </div>
</div>

<!-- ============================================== -->
<!-- Vanilla JS Переключатель Табов -->
<!-- ============================================== -->
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
                
                // Деактивируем всё
                tabBtns.forEach(b => b.classList.remove('active'));
                
                // Плавно скрываем все панели
                tabPanes.forEach(pane => {
                    pane.style.opacity = '0';
                    setTimeout(() => {
                        pane.classList.remove('block');
                        pane.classList.add('hidden');
                        pane.classList.remove('active');
                    }, 300); // Совпадает с transition duration
                });
                
                // Активируем нужную кнопку
                this.classList.add('active');
                
                // Показываем нужную вкладку
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
    });
</script>
{% endblock %}
`;

fs.writeFileSync('templates/lesson_homework.html', staticContent);
