const fs = require('fs');

const functionalHTML = `{% extends 'base.html' %}
{% from '_task_content_block.html' import render_task_content %}
{% block html_attrs %}data-student-lesson-room="1"{% endblock %}
{% block title %}{{ lesson.topic or 'Урок' }} · BooStudy{% endblock %}
{% set active_page = 'student_profile' if (is_student_view or is_parent_view) else 'dashboard' %}
{% block body_attrs %}data-cinema-scene="lesson"{% endblock %}
{% block body_class %}{% if is_student_view or is_parent_view %}layout-student{% else %}layout-teacher teacher-mode{% endif %} min-h-screen{% endblock %}

{% block content %}
<div class="flex flex-col gap-6 w-full max-w-[1600px] mx-auto pb-16">
    <!-- Кнопка назад -->
    <div class="flex items-center">
        <a href="{{ url_for('students.student_profile', student_id=student.student_id) if (student and student.student_id) else (url_for('main.dashboard') if is_student_view else '#') }}" class="flex items-center gap-2 text-[var(--color-text-secondary)] dark:text-zinc-300 font-bold text-sm hover:text-primary transition-colors bg-[var(--color-bg-surface)] px-4 py-2.5 rounded-xl border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] no-underline clay-interactive">
            <i class="ph-bold ph-arrow-left text-lg"></i> Назад
        </a>
    </div>

    <!-- Заголовок урока -->
    <div class="mt-2 mb-2 px-2 flex justify-between items-start flex-wrap gap-4">
        <div>
            <h1 class="text-4xl md:text-5xl font-black mb-6 leading-tight text-[var(--color-text-primary)] dark:drop-shadow-none">{{ lesson.topic or 'Тема не указана' }}</h1>
            <div class="flex flex-wrap items-center gap-3">
                <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                    <i class="ph-fill ph-calendar-blank text-primary text-lg"></i> {{ lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson and lesson.lesson_date else '—' }}
                </span>
                <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                    <i class="ph-fill ph-clock text-primary text-lg"></i> {{ lesson.duration if lesson else 0 }} мин
                </span>
                <span class="px-4 py-2 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] rounded-xl font-bold text-sm text-[var(--color-text-secondary)] dark:text-zinc-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.02)] flex items-center gap-2">
                    <img src="https://api.dicebear.com/7.x/adventurer-neutral/svg?seed={{ student.student_id if (student and student.student_id) else (current_user.id if current_user.is_authenticated else 'mock') }}&backgroundColor=F3F0FF" alt="" class="w-6 h-6 rounded-md bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shrink-0">
                    {{ student.name if student else (current_user.name if current_user.is_authenticated else 'Ученик') }}
                </span>
                <span class="px-4 py-2 bg-info/10 text-info border border-info/30 rounded-xl font-extrabold text-[0.7rem] uppercase tracking-widest shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">
                    {% if assignment_type == 'homework' %}Домашняя работа{% elif assignment_type == 'exam' %}Экзамен{% else %}Классная работа{% endif %}
                </span>
            </div>
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
    <div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-10 items-start mt-4">
        
        <!-- ЛЕВАЯ КОЛОНКА (Контент) -->
        <div class="lesson-room-main-column w-full min-w-0">
            
            <!-- ====== КОНСПЕКТ ====== -->
            <div id="tab-theory" class="tab-pane block" style="transition: opacity 0.3s ease; opacity: 1;">
                <div class="clay-card p-8 md:p-12 mb-8 flex flex-col gap-6 max-w-4xl mx-auto py-4">
                    {% if content_blocks and content_blocks|length > 0 %}
                        {% for b in content_blocks %}
                            {% if b.type == 'paragraph' %}
                                <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4 whitespace-pre-wrap">{{ b.text }}</p>
                            {% elif b.type == 'header' %}
                                <h{{ b.level or 2 }} class="text-3xl font-bold mt-8 mb-4 text-[var(--color-text-primary)] dark:drop-shadow-none">{{ b.text }}</h{{ b.level or 2 }}>
                            {% elif b.type == 'list' %}
                                <ul class="list-disc pl-8 text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 space-y-4 mb-6">
                                    {% for item in b.items %}
                                        <li>{{ item }}</li>
                                    {% endfor %}
                                </ul>
                            {% elif b.type == 'code' %}
                                <div class="bg-[#1E1B4B] rounded-[32px] p-8 shadow-[inset_0_4px_24px_rgba(0,0,0,0.4)] overflow-hidden relative my-4 border border-[#312E81]">
                                    <div class="flex gap-2 mb-6">
                                        <div class="w-3.5 h-3.5 rounded-full bg-danger shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                                        <div class="w-3.5 h-3.5 rounded-full bg-warning shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                                        <div class="w-3.5 h-3.5 rounded-full bg-success shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                                    </div>
                                    <pre><code class="text-indigo-200 font-mono text-base leading-relaxed whitespace-pre-wrap">{{ b.code }}</code></pre>
                                </div>
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
                                <div class="bg-[var(--color-bg-inset)] rounded-[32px] p-4 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_12px_rgba(0,0,0,0.05)] my-6">
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
                        <!-- MOCK CONTENT WHEN EMPTY -->
                        <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4">
                            Добро пожаловать в новый визуальный стиль платформы BooStudy! Конспект к этому уроку пока не добавлен преподавателем.
                        </p>
                    {% endif %}
                </div>
            </div>

            <!-- ====== КЛАССНАЯ РАБОТА ====== -->
            <div id="tab-tasks" class="tab-pane hidden" style="transition: opacity 0.3s ease; opacity: 0;">
                <div class="max-w-4xl mx-auto flex flex-col gap-6 py-4">
                    
                    <!-- Навигация по задачам (Squish effect) -->
                    <div class="clay-card p-6 flex flex-wrap justify-center gap-4 w-full">
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
                                
                                <a id="tasknav-{{ lt.lesson_task_id }}" href="#task-{{ lt.lesson_task_id }}" class="clay-interactive task-nav-btn h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 {{ btn_class }} no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                                    {{ loop.index }}
                                </a>
                            {% endfor %}
                        {% else %}
                            <div class="text-center text-[var(--color-text-muted)] font-bold py-4">Нет заданий</div>
                        {% endif %}
                    </div>

                    <!-- Форма Задачи с HTMX -->
                    <form id="homework-form" hx-post="{% if is_student_view %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_student_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_student_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_student_save', lesson_id=lesson.lesson_id) }}{% endif %}{% else %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_save', lesson_id=lesson.lesson_id) }}{% endif %}{% endif %}" hx-swap="none">
                        {% if csrf_token %}<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">{% endif %}

                        {% if homework_tasks %}
                            {% for hw_task in homework_tasks %}
                            <div id="task-{{ hw_task.lesson_task_id }}" class="clay-card p-10 mt-4">
                                <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                    <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">{{ loop.index }}</span>
                                    {% if hw_task.lesson_task.title %}{{ hw_task.lesson_task.title }}{% else %}Задание по теории{% endif %}
                                </div>
                                <div class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">{{ render_task_content(hw_task.lesson_task.content, false, 'task-content') | safe if hw_task.lesson_task.content else '' }}</div>
                                
                                <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                    {% set user_ans = user_answers_dict.get(hw_task.lesson_task_id) %}
                                    <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Ваш ответ:</label>
                                    
                                    {% if hw_task.lesson_task.task_type == 'detailed' %}
                                    <textarea name="answer_detailed_{{ hw_task.lesson_task_id }}" class="w-full h-32 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 rounded-2xl p-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Ваш развернутый ответ...">{{ user_ans.answer_detailed if user_ans and user_ans.answer_detailed else '' }}</textarea>
                                    {% else %}
                                    <input type="text" name="answer_short_{{ hw_task.lesson_task_id }}" value="{{ user_ans.answer_short if user_ans and user_ans.answer_short else '' }}" class="w-full h-16 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите короткий ответ...">
                                    {% endif %}
                                </div>
                            </div>
                            {% endfor %}
                            <button type="submit" class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110 cursor-pointer">
                                Сохранить всё
                            </button>
                        {% endif %}
                    </form>
                </div>
            </div>
            
            <!-- ====== МАТЕРИАЛЫ ====== -->
            <div id="tab-materials" class="tab-pane hidden" style="transition: opacity 0.3s ease; opacity: 0;">
                <div class="max-w-4xl mx-auto py-10">
                    <div class="bg-[var(--color-bg-inset)] rounded-[40px] p-16 flex flex-col items-center justify-center text-center border-dashed border-4 border-[var(--color-stroke)] hidden-shadow">
                        <div class="w-28 h-28 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] rounded-[2rem] flex items-center justify-center shadow-[0_8px_24px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.02)] border border-[var(--color-stroke)] mb-8">
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
                    <div class="text-xs font-black uppercase tracking-widest text-[var(--color-text-muted)] dark:text-zinc-300">Длительность</div>
                    <div class="px-3 py-1.5 bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] text-primary rounded-xl font-black text-sm shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] flex items-center gap-1.5">
                        <i class="ph-bold ph-hourglass text-lg"></i> {{ lesson.duration if lesson else 90 }} мин
                    </div>
                </div>
                
                <div class="h-px w-full bg-[var(--color-stroke)] my-2 relative z-10"></div>
                
                <div class="flex items-center gap-4 mt-1 relative z-10">
                    <!-- Аватар 'выпуклый' в сайдбаре -->
                    <div class="w-16 h-16 rounded-[1.25rem] bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 shadow-[0_4px_12px_rgba(0,0,0,0.05),inset_0_-2px_0_rgba(0,0,0,0.05)] overflow-hidden shrink-0">
                        {% if lesson and lesson.author and lesson.author.avatar_url %}
                        <img src="{{ url_for('static', filename='uploads/avatars/' + lesson.author.avatar_url) }}" alt="teacher" class="w-full h-full object-cover">
                        {% else %}
                        <img src="https://api.dicebear.com/7.x/shapes/svg?seed={{ lesson.author_id if (lesson and lesson.author) else 'teacher_pro' }}&backgroundColor=F3F0FF" alt="teacher" class="w-full h-full object-cover">
                        {% endif %}
                    </div>
                    <div class="min-w-0">
                        <div class="text-[0.65rem] font-black text-primary mb-1 uppercase tracking-widest">Преподаватель</div>
                        <div class="font-black text-[var(--color-text-primary)] truncate text-xl">
                            {{ lesson.author.name if (lesson and lesson.author) else 'Преподаватель' }}
                        </div>
                    </div>
                </div>
                
                <button class="clay-interactive mt-4 w-full h-14 inline-flex items-center justify-center gap-2 bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-primary font-black rounded-2xl shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.05)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] transition-all hover:brightness-[0.97] relative z-10 cursor-pointer">
                    <i class="ph-bold ph-chat-circle-dots text-2xl"></i> Написать в чат
                </button>
            </div>
            
            <!-- Миникарта заданий -->
            <div class="clay-card p-6">
                <div class="font-black text-xl text-[var(--color-text-primary)] mb-6 flex items-center justify-between">
                    <span>Задания</span>
                    <span class="text-xs px-2.5 py-1.5 bg-[var(--color-bg-inset)] rounded-[10px] text-[var(--color-text-secondary)] dark:text-zinc-300 border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] font-extrabold uppercase">
                        {{ current_task_nav_list|length if current_task_nav_list else 0 }} задач
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
                            
                            <a id="tasknav-side-{{ lt.lesson_task_id }}" href="#task-{{ lt.lesson_task_id }}" class="clay-interactive task-nav-btn w-full pt-[100%] relative rounded-xl border font-black hover:-translate-y-0.5 active:translate-y-1 cursor-pointer transition-all no-underline block {{ mini_class }}" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                                <span class="absolute inset-0 flex items-center justify-center text-xl">{{ loop.index }}</span>
                            </a>
                        {% endfor %}
                    {% endif %}
                </div>
            </div>
        </aside>
    </div>
</div>

<!-- ============================================== -->
<!-- Переключение вкладок С НУЛЯ (Без костылей) -->
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

        // Навигация с кнопок задач на вкладку "Классная работа"
        const combinedTaskBtns = document.querySelectorAll('#lesson-sidebar .grid a, #tab-tasks .clay-card.w-full a');
        combinedTaskBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                const tasksTab = document.querySelector('[data-tab="tasks"]');
                if (tasksTab) tasksTab.click();
            });
        });
    });
</script>
{% endblock %}
`
fs.writeFileSync('templates/lesson_homework.html', functionalHTML);
