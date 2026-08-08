import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы вырезаем полностью jinja цикл задач из активной вкладки и оставляем 100% захардкоженный блок Задачи 1

old_tasks_tab = re.search(r'<!-- Форма Задачи с HTMX -->.*?</form>', html, re.DOTALL)
if old_tasks_tab:
    new_hardcoded_tasks = """<!-- Форма Задачи -->
                    <div id="task-1" class="clay-card p-10 mt-4">
                        <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                            <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">1</span>
                            Задание 14 (Позиционные системы)
                        </div>
                        <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">Значение арифметического выражения: <b>4<sup class="text-primary font-bold">2026</sup> + 2<sup class="text-primary font-bold">2024</sup> - 8</b> — записали в системе счисления с основанием 4. <br><br>Сколько цифр <b>"3"</b> содержится в этой записи?</p>
                        
                        <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                            <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Ваш ответ:</label>
                            <!-- Поле ввода вдавленное -->
                            <input type="text" class="w-full h-16 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите короткий ответ...">
                            
                            <!-- Выпуклая кнопка "Сохранить" -->
                            <button type="button" class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110 cursor-pointer">
                                Сохранить ответ
                            </button>
                        </div>
                    </div>"""
    html = html.replace(old_tasks_tab.group(0), new_hardcoded_tasks)

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
