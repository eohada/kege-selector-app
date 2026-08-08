const fs = require('fs');
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// 1. Изменяем обертку на CSS Grid (Split-Screen)
const gridWrap = `
        <!-- MOCK DATA INJECTION FOR THEORY TAB -->
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const theoryContent = document.getElementById('theory-content');
                if (theoryContent && theoryContent.innerHTML.includes('*Конспект пуст*')) {
                    theoryContent.innerHTML = "<div class='flex flex-col gap-6 max-w-4xl mx-auto'>" +
                        "<h1 class='text-4xl font-black mb-4'>🚀 Введение в Claymorphism</h1>" +
                        "<p class='text-lg text-[var(--color-text-secondary)] font-medium leading-relaxed mb-4'>Добро пожаловать в новый визуальный стиль платформы BooStudy! Этот стиль построен на мягких тенях, глубоких градиентах и тактильных элементах, которые хочется нажимать.</p>" +
                        "<div class='rounded-2xl p-6 relative overflow-hidden' style='background: color-mix(in srgb, var(--color-primary) 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, var(--color-primary) 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, var(--color-primary) 10%, transparent);'>" +
                            "<div class='absolute left-0 top-0 bottom-0 w-2' style='background: var(--color-primary);'></div>" +
                            "<div class='font-bold text-lg mb-2 flex items-center gap-2' style='color: var(--color-primary);'><i class='ph-fill ph-info'></i> Интересный факт</div>" +
                            "<div class='font-medium text-[var(--color-text-secondary)] leading-relaxed'>Клейморфизм (Claymorphism) отличается от неоморфизма тем, что он добавляет объем не только за счет света, но и за счет глубокого цвета и закругленных форм, делая интерфейс похожим на настоящую глину или пластилин.</div>" +
                        "</div>" +
                        "<h2 class='text-2xl font-bold mt-6 mb-4'>Основные принципы</h2>" +
                        "<ul class='list-disc pl-6 text-lg text-[var(--color-text-secondary)] space-y-2 mb-6'>" +
                            "<li><strong class='text-primary'>Мягкие тени:</strong> Двойной <code>box-shadow</code> (внешний drop и внутренний inset).</li>" +
                            "<li><strong class='text-primary'>Скругления:</strong> Большие значения <code>border-radius</code> (24px - 32px).</li>" +
                            "<li><strong class='text-primary'>Тактильность:</strong> Анимации нажатия со squish эффектом.</li>" +
                        "</ul>" +
                        "<div class='bg-[var(--color-bg-inset)] rounded-2xl p-4 border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] my-6'>" +
                            "<img src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=2664&auto=format&fit=crop' alt='3D Abstract' class='w-full h-[400px] object-cover rounded-xl shadow-sm'>" +
                            "<div class='text-muted text-sm mt-3 text-center font-bold'>Пример абстрактного 3D-дизайна, вдохновляющего новые интерфейсы.</div>" +
                        "</div>" +
                        "<div class='rounded-2xl p-6 relative overflow-hidden' style='background: color-mix(in srgb, var(--color-warning) 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, var(--color-warning) 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, var(--color-warning) 10%, transparent);'>" +
                            "<div class='absolute left-0 top-0 bottom-0 w-2' style='background: var(--color-warning);'></div>" +
                            "<div class='font-bold text-lg mb-2 flex items-center gap-2' style='color: var(--color-warning);'><i class='ph-fill ph-warning-circle'></i> Правило тестирования</div>" +
                            "<div class='font-medium text-[var(--color-text-secondary)] leading-relaxed'>Контрастность — слабое место многих мягких стилей. Всегда проверяйте свои тексты на читабельность в темной теме. Избегайте использования тонких начертаний шрифтов на цветных фонах.</div>" +
                        "</div>" +
                        "<h2 class='text-2xl font-bold mt-6 mb-4'>Пример кода</h2>" +
                        "<div class='bg-[#1E1E2E] rounded-2xl p-6 shadow-[inset_0_2px_10px_rgba(0,0,0,0.5)] overflow-hidden relative'>" +
                            "<div class='flex gap-2 mb-4'>" +
                                "<div class='w-3 h-3 rounded-full bg-danger'></div>" +
                                "<div class='w-3 h-3 rounded-full bg-warning'></div>" +
                                "<div class='w-3 h-3 rounded-full bg-success'></div>" +
                            "</div>" +
                            "<pre><code class='text-blue-300 font-mono text-sm leading-relaxed'>.clay-card {\\n    background: var(--color-bg-surface);\\n    border-radius: 28px;\\n    box-shadow: var(--clay-shadow-out), var(--clay-shadow-in);\\n    transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);\\n}</code></pre>" +
                        "</div>" +
                        "<div class='rounded-2xl p-6 relative overflow-hidden mt-6' style='background: color-mix(in srgb, var(--color-success) 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, var(--color-success) 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, var(--color-success) 10%, transparent);'>" +
                            "<div class='absolute left-0 top-0 bottom-0 w-2' style='background: var(--color-success);'></div>" +
                            "<div class='font-bold text-lg mb-2 flex items-center gap-2' style='color: var(--color-success);'><i class='ph-fill ph-check-circle'></i> Готово к работе</div>" +
                            "<div class='font-medium text-[var(--color-text-secondary)] leading-relaxed'>Теперь весь этот интерфейс готов к внедрению реальных уроков преподавателями! Перейди на вкладку «Классная работа», чтобы посмотреть, как обновились кнопки задач.</div>" +
                        "</div>" +
                    "</div>";
                }
            });
        </script>
        
        <div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-8 items-start relative mt-4">
            <!-- Левая колонка: Основной контент (Конспект, Тесты) -->
            <div class="lesson-room-main-column w-full min-w-0">
`;

content = content.replace('<div class="lesson-room-workspace">\n            <div class="lesson-room-main-column w-full">', gridWrap);

// 2. Добавляем правый сайдбар в конец
const sidebarStr = `
            </div> <!-- End of Left Column -->
            
            <!-- Правая колонка: Sticky Sidebar -->
            <aside class="hidden xl:flex flex-col gap-6 sticky top-8 z-10 w-full" id="lesson-sidebar">
                
                <!-- Виджет преподавателя & Таймер -->
                <div class="clay-card p-6 flex flex-col gap-4 relative overflow-hidden">
                    <div class="absolute -right-10 -top-10 w-32 h-32 bg-primary/10 rounded-full blur-2xl"></div>
                    
                    <div class="flex items-center justify-between mb-2">
                        <div class="text-xs font-extrabold uppercase tracking-widest text-muted">Тайминг урока</div>
                        <div class="px-3 py-1 bg-primary/10 text-primary rounded-lg font-bold text-sm border border-primary/20 shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">
                            <i class="ph-bold ph-timer mr-1"></i> {{ lesson.duration }} мин
                        </div>
                    </div>
                    
                    <div class="h-px w-full bg-[var(--color-stroke)] my-1"></div>
                    
                    <div class="flex items-center gap-4 mt-2">
                        <div class="w-14 h-14 rounded-2xl bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] overflow-hidden shrink-0">
                            {% if lesson.author and lesson.author.avatar_url %}
                            <img src="{{ url_for('static', filename='uploads/avatars/' + lesson.author.avatar_url) }}" alt="teacher" class="w-full h-full object-cover">
                            {% else %}
                            <img src="https://api.dicebear.com/7.x/shapes/svg?seed={{ lesson.author_id or 'teacher' }}&backgroundColor=F3F0FF" alt="teacher" class="w-full h-full object-cover">
                            {% endif %}
                        </div>
                        <div class="min-w-0">
                            <div class="text-xs font-bold text-primary mb-0.5">Преподаватель</div>
                            <div class="font-bold text-[var(--color-text-primary)] truncate text-sm">
                                {% if lesson.author %}{{ lesson.author.name }}{% else %}Администрация{% endif %}
                            </div>
                        </div>
                    </div>
                    
                    <!-- Кнопка 'Задать вопрос' -->
                    <button class="clay-interactive mt-3 w-full neo-button sm !bg-[var(--color-bg-inset)] !border-[var(--color-stroke)] hover:!border-primary/40 hover:!text-primary shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)]">
                        <i class="ph-bold ph-chat-circle-dots text-lg"></i> Задать вопрос
                    </button>
                </div>
                
                <!-- Навигация по заданиям (миникарта) -->
                <div class="clay-card p-6">
                    <div class="font-bold text-[var(--color-text-primary)] mb-4 flex items-center justify-between">
                        <span>Задания урока</span>
                        <span class="text-xs px-2 py-1 bg-[var(--color-bg-inset)] rounded-md text-muted border border-[var(--color-stroke)]">
                            {% if current_task_nav_list %}{{ current_task_nav_list|length }}{% else %}0{% endif %} шт
                        </span>
                    </div>
                    
                    {% if current_task_nav_list and current_task_nav_list|length > 0 %}
                    <div class="grid grid-cols-5 gap-2">
                        {% for lt in current_task_nav_list %}
                            <!-- Цветные точки миникарты, аналогично основным кнопкам -->
                            <div class="w-full pt-[100%] relative rounded-lg border border-[var(--color-stroke)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)] bg-[var(--color-bg-surface)] hover:scale-105 cursor-pointer transition-transform duration-200">
                                <a href="#task-{{ lt.lesson_task_id }}" class="absolute inset-0 flex items-center justify-center text-xs font-extrabold text-muted no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                                    {{ loop.index }}
                                </a>
                            </div>
                        {% endfor %}
                    </div>
                    {% else %}
                    <div class="text-center py-4 bg-[var(--color-bg-inset)] rounded-xl border border-[var(--color-stroke)] border-dashed">
                        <i class="ph-fill ph-clipboard-text text-2xl text-muted/50 mb-2"></i>
                        <div class="text-xs font-bold text-muted">Нет заданий</div>
                    </div>
                    {% endif %}
                </div>
            </aside>
`;

let contentParts = content.split('        {% if not is_student_view and not is_parent_view %}\n        <div id="createLessonTemplateModal"');
if(contentParts.length > 1) {
    content = contentParts[0] + sidebarStr + '\n        </div>\n\n        {% if not is_student_view and not is_parent_view %}\n        <div id="createLessonTemplateModal"' + contentParts[1];
}

fs.writeFileSync('templates/lesson_homework.html', content);
