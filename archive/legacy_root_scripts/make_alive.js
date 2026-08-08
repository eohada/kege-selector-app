const fs = require('fs');

// Читаем текущий рабочий файл
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// 1. Оживляем вкладки (Javascript)
// В JS-скрипте, скорее всего, ломалась инициализация или отсутствовала кнопка-инициализатор.
// Если в HTML нет <a href="#task-id"> на кнопках, JS не скроллит к заданию.
const taskBtnPattern = /<button class="clay-interactive h-14 px-8 w-auto min-w-\[4rem\] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0\.5 \{\{ btn_class \}\}">\s*\{\{ loop\.index \}\}\s*<\/button>/g;

const taskBtnReplacement = `<a href="#task-{{ lt.lesson_task_id }}" class="clay-interactive h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 {{ btn_class }} no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">
                                    {{ loop.index }}
                                </a>`;
content = content.replace(taskBtnPattern, taskBtnReplacement);

// То же самое для Mock кнопок, чтобы они стали ссылками (если нужны)
const mockBtnPattern = /<button class="clay-interactive h-14 px-8 w-auto min-w-\[4rem\] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all bg-\[var\(--color-bg-surface-alt\)\] border border-\[var\(--color-stroke\)\] text-\[var\(--color-text-muted\)\] dark:text-zinc-300 shadow-\[0_2px_4px_rgba\(0,0,0,0\.05\),inset_0_-4px_0_rgba\(0,0,0,0\.08\)\] active:translate-y-1 active:shadow-\[inset_0_4px_8px_rgba\(0,0,0,0\.1\)\] hover:-translate-y-0\.5">1<\/button>/g;
const mockBtnReplacement = `<a href="#" class="clay-interactive h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.08)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] hover:-translate-y-0.5 no-underline">1</a>`;
content = content.replace(mockBtnPattern, mockBtnReplacement);

// 2. ВОЗВРАЩАЕМ ПОДЛОЖКУ КОНСПЕКТА (Clay-карточка)
// Было: <div class="flex flex-col gap-6 max-w-4xl mx-auto py-4">
// Стало: Обернем в .clay-card
content = content.replace(
    '<div class="flex flex-col gap-6 max-w-4xl mx-auto py-4">',
    '<div class="clay-card p-8 md:p-12 mb-8 flex flex-col gap-6 max-w-4xl mx-auto py-4">'
);

// 3. ФОРМЫ ВОЗВРАЩАЕМ К ЖИЗНИ. Оживляем кнопку "Сохранить ответ"
// Я должен убедиться, что вокруг карточек задач стоит тег <form> !
// Вставляем открывающий тег формы и старые обертки
const formStartPattern = `                    <!-- Форма Задачи -->
                    {% if homework_tasks %}
                        {% for hw_task in homework_tasks %}
                        <div class="clay-card p-10 mt-4">`;
                        
const formStartReplacement = `                    <!-- Исходная форма отправки заданий -->
                    <form id="homework-form" method="POST" data-no-ajax action="{% if is_student_view %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_student_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_student_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_student_save', lesson_id=lesson.lesson_id) }}{% endif %}{% else %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_save', lesson_id=lesson.lesson_id) }}{% endif %}{% endif %}">
                        {% if csrf_token %}<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">{% endif %}

                    {% if homework_tasks %}
                        {% for hw_task in homework_tasks %}
                        <div id="task-{{ hw_task.lesson_task_id }}" class="clay-card p-10 mt-4">`;

content = content.replace(formStartPattern, formStartReplacement);

// Вставляем генерацию input type="hidden" для ID задания, как было в старой логике
// Восстанавливаем атрибут name= у textarea/input, без него сохранения не будет!
const textAreaPattern = /<textarea class="w-full h-32 bg-\[var\(--color-bg-surface\)\] border-2 border-\[var\(--color-stroke\)\] dark:border-white\/10 dark:bg-\[var\(--color-bg-surface-alt\)\] rounded-2xl p-6 text-xl font-bold outline-none focus:border-primary focus:shadow-\[0_0_0_4px_color-mix\(in_srgb,var\(--color-primary\)_20%,transparent\)\] transition-all placeholder:text-\[var\(--color-text-muted\)\] dark:text-zinc-300">\{\{ user_ans\.answer_detailed if user_ans and user_ans\.answer_detailed else '' \}\}<\/textarea>/g;
const textAreaReplacement = `<textarea name="answer_detailed_{{ hw_task.lesson_task_id }}" class="w-full h-32 bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] dark:border-white/10 dark:bg-[var(--color-bg-surface-alt)] rounded-2xl p-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Ваш развернутый ответ...">{{ user_ans.answer_detailed if user_ans and user_ans.answer_detailed else '' }}</textarea>`;
content = content.replace(textAreaPattern, textAreaReplacement);

const inputPattern = /<input type="text" value="\{\{ user_ans\.answer_short if user_ans and user_ans\.answer_short else '' \}\}" class="w-full h-16 bg-\[var\(--color-bg-surface\)\] border-2 border-\[var\(--color-stroke\)\] dark:border-white\/10 dark:bg-\[var\(--color-bg-surface-alt\)\] rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-\[0_0_0_4px_color-mix\(in_srgb,var\(--color-primary\)_20%,transparent\)\] transition-all placeholder:text-\[var\(--color-text-muted\)\] dark:text-zinc-300" placeholder="Введите ответ...">/g;
const inputReplacement = `<input type="text" name="answer_short_{{ hw_task.lesson_task_id }}" value="{{ user_ans.answer_short if user_ans and user_ans.answer_short else '' }}" class="w-full h-16 bg-[var(--color-bg-surface)] border-2 border-[var(--color-stroke)] dark:border-white/10 dark:bg-[var(--color-bg-surface-alt)] rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите короткий ответ...">`;
content = content.replace(inputPattern, inputReplacement);

// Закрываем форму ПОСЛЕ кнопки "Сохранить все"
const btnPattern = `Сохранить всё
                        </button>
                    {% else %}`;
const btnReplacement = `Сохранить всё
                        </button>
                    </form>
                    {% else %}`;
content = content.replace(btnPattern, btnReplacement);

// Добавим type="submit" нашей кнопке сохранения
const submitPattern = /<button class="clay-interactive mt-8 w-full h-16 bg-\[\#4F46E5\] text-white rounded-2xl font-black text-xl border border-\[\#4338CA\] shadow-\[0_8px_24px_rgba\(79,70,229,0\.3\),inset_0_-4px_0_rgba\(0,0,0,0\.2\)\] dark:bg-\[\#4F46E5\] dark:text-white dark:border-\[\#3730A3\] dark:shadow-\[0_4px_12px_rgba\(0,0,0,0\.4\),inset_0_-4px_0_rgba\(0,0,0,0\.3\)\] active:translate-y-1 active:shadow-\[inset_0_4px_8px_rgba\(0,0,0,0\.3\)\] hover:brightness-110">/g;
const submitReplacement = `<button type="submit" class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110 cursor-pointer">`;
content = content.replace(submitPattern, submitReplacement);

// Чтобы JS снова ожил, нам нужно убедиться, что теги script не были удалены или их обрезало.
// Я вижу в файле `<script>` с логикой. 

fs.writeFileSync('templates/lesson_homework.html', content);
