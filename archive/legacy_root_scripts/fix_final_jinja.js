const fs = require('fs');
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// 1. ВЗРЫВ БЛОКА НАВИГАЦИИ (Табы задач)
// Проблема: Старый цикл генерировал кнопки <button class="... inline-flex items-center justify-center...">
// Но внутри этого flex-контейнера он не вел себя как flex-row, а растягивался.
// Оригинальный статический макет использовал flex-wrap:
const oldTasksNav = `                    <!-- Навигация по задачам (Squish effect) -->
                    <div class="clay-card p-6 flex flex-wrap justify-center gap-4">
                        {% if current_task_nav_list %}`;
const newTasksNav = `                    <!-- Навигация по задачам (Squish effect) -->
                    <div class="clay-card p-6 flex flex-wrap justify-center gap-4 w-full">
                        {% if current_task_nav_list %}`;
content = content.replace(oldTasksNav, newTasksNav);

// Исправим "сосиску": У кнопки ширина/padding должны ограничивать ее. В макете было `h-14 px-8 inline-flex`. Вроде нормально. НО если кнопок мало, они растягивались. Добавим `w-auto`.
content = content.replace(/<button class="clay-interactive h-14 px-8 inline-flex/g, '<button class="clay-interactive h-14 px-8 w-auto min-w-[4rem] inline-flex');

// 2. ОТСТУП У НОМЕРА ЗАДАНИЯ В ТЕМНОЙ ТЕМЕ
// Было: <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-none">{{ loop.index }}</span>
// `dark:shadow-none` убивало объем. Нужно вернуть нормальную тень. И добавить `shrink-0`.
content = content.replace(/dark:shadow-none/g, 'dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0');

// 3. ПАРСЕР КОНСПЕКТА (Вернем все блоки Theory)
// Я удалил обработку Header'а. Надо вернуть `b.type == 'header'` и другие, сохранив дизайн Notion-style.
const oldTheoryLogic = `                            {% if b.type == 'paragraph' %}
                                <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4 whitespace-pre-wrap">{{ b.text }}</p>
                            {% elif b.type == 'callout' %}`;
const newTheoryLogic = `                            {% if b.type == 'paragraph' %}
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
                            {% elif b.type == 'callout' %}`;
content = content.replace(oldTheoryLogic, newTheoryLogic);

// 4. ТЕМНАЯ ТЕМА: Грязные белые пятна (Инверсия)
// Вспомним, что в `content` блока задач форма ввода имеет белую обводку в Dark Mode: bg-[var(--color-bg-surface)]... Это нужно поправить.
content = content.replace(/border-2 border-\[var\(--color-stroke\)\]/g, 'border-2 border-[var(--color-stroke)] dark:border-white/10 dark:bg-[var(--color-bg-surface-alt)]');
content = content.replace(/bg-\[var\(--color-bg-surface\)\]/g, 'bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)]');

// 5. РЕНДЕРИНГ МАКРОСА `render_task_content`
// Макрос `hw_task.lesson_task.content` ломал `div` из-за `safe`. Вернем `render_task_content` из старого файла (бэкап).
// В шапку:
content = content.replace("{% block html_attrs %}", "{% from '_task_content_block.html' import render_task_content %}\n{% block html_attrs %}");
// В шаблон задачи:
content = content.replace("{{ hw_task.lesson_task.content | safe }}", "{{ render_task_content(hw_task.lesson_task.content, false, 'task-content') | safe if hw_task.lesson_task.content else '' }}");


fs.writeFileSync('templates/lesson_homework.html', content);
