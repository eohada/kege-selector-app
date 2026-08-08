import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update Title Mock
html = html.replace("{{ lesson.topic or 'Тема не указана' }}", "{{ lesson.topic or 'Позиционные системы счисления (Задание 14)' }}")

# 2. Update Theory Mock
old_theory = """<!-- MOCK CONTENT WHEN EMPTY -->
                        <p class="text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 font-medium leading-relaxed mb-4">
                            Добро пожаловать в новый визуальный стиль платформы BooStudy! Конспект к этому уроку пока не добавлен преподавателем.
                        </p>"""

new_theory = """<!-- MOCK CONTENT WHEN EMPTY/PREVIEW -->
                        <h2 class="text-3xl font-bold mt-2 mb-4 text-[var(--color-text-primary)] dark:drop-shadow-none">Правила перевода чисел</h2>
                        <ul class="list-disc pl-8 text-xl text-[var(--color-text-secondary)] dark:text-zinc-300 space-y-4 mb-6">
                            <li>Чтобы перевести число из десятичной системы в систему с основанием <b class="text-primary">N</b>, нужно последовательно делить это число на <b class="text-primary">N</b>.</li>
                            <li>Остатки от деления, записанные в обратном порядке, образуют запись числа в новой системе счисления.</li>
                            <li>Основание системы счисления определяет количество цифр в алфавите (например, в троичной: 0, 1, 2).</li>
                        </ul>

                        <div class="rounded-3xl p-6 relative overflow-hidden my-8" style="background: color-mix(in srgb, var(--color-warning) 5%, var(--color-bg-inset)); border: 1px solid color-mix(in srgb, var(--color-warning) 20%, transparent); box-shadow: inset 0 2px 8px color-mix(in srgb, var(--color-warning) 10%, transparent);">
                            <div class="absolute left-0 top-0 bottom-0 w-2" style="background: var(--color-warning);"></div>
                            <div class="font-bold text-xl mb-2 flex items-center gap-2" style="color: var(--color-warning);"><i class="ph-fill ph-warning-circle"></i> Важное замечание</div>
                            <div class="font-medium text-[var(--color-text-secondary)] dark:text-zinc-300 leading-relaxed text-lg">При программном переводе чисел через остатки от деления, помни: операция <code class="bg-[var(--color-bg-surface-alt)] px-2 py-1 border border-[var(--color-stroke)] dark:border-white/10 rounded-md text-[var(--color-warning)] font-bold font-mono">n % N</code> даёт последнюю цифру числа, а <code class="bg-[var(--color-bg-surface-alt)] px-2 py-1 border border-[var(--color-stroke)] dark:border-white/10 rounded-md text-[var(--color-warning)] font-bold font-mono">n // N</code> отсекает её. Собирать строку ответа нужно, <b>прибавляя новый остаток слева</b> (или перевернув строку в конце).</div>
                        </div>

                        <h2 class="text-3xl font-bold mt-8 mb-4 text-[var(--color-text-primary)] dark:drop-shadow-none">Алгоритм перевода на Python</h2>
                        <div class="bg-[#1E1B4B] rounded-[32px] p-8 shadow-[inset_0_4px_24px_rgba(0,0,0,0.4)] overflow-hidden relative my-4 border border-[#312E81]">
                            <div class="flex gap-2 mb-6">
                                <div class="w-3.5 h-3.5 rounded-full bg-danger shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                                <div class="w-3.5 h-3.5 rounded-full bg-warning shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                                <div class="w-3.5 h-3.5 rounded-full bg-success shadow-[inset_0_-1px_2px_rgba(0,0,0,0.5)]"></div>
                            </div>
                            <pre><code class="text-indigo-200 font-mono text-base leading-relaxed whitespace-pre-wrap"><span class="text-purple-400">def</span> <span class="text-blue-300">convert_base</span>(num, base):
    <span class="text-purple-400">if</span> num == <span class="text-orange-300">0</span>:
        <span class="text-purple-400">return</span> <span class="text-green-300">"0"</span>
    res = <span class="text-green-300">""</span>
    <span class="text-purple-400">while</span> num > <span class="text-orange-300">0</span>:
        res = <span class="text-emerald-300">str</span>(num % base) + res
        num = num // base
    <span class="text-purple-400">return</span> res

<span class="text-indigo-400/60 font-bold"># Пример использования:</span>
<span class="text-emerald-300">print</span>(convert_base(<span class="text-orange-300">125</span>, <span class="text-orange-300">4</span>)) <span class="text-indigo-400/60 font-bold"># Перевод 125 в 4-ичную</span></code></pre>
                        </div>"""

html = html.replace(old_theory, new_theory)

# 3. Update Tasks Nav Mock
old_nav = """{% else %}
                            <a href="#" class="clay-interactive h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.08)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] hover:-translate-y-0.5 no-underline">1</a>
                        {% endif %}"""

new_nav = """{% else %}
                            <a href="#task-1" class="clay-interactive task-nav-btn h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] text-[var(--color-text-muted)] dark:text-zinc-300 shadow-[0_2px_4px_rgba(0,0,0,0.05),inset_0_-4px_0_rgba(0,0,0,0.08)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.1)] no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">1</a>
                            <a href="#task-2" class="clay-interactive task-nav-btn h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 !bg-[var(--color-success)] !border-[rgba(0,0,0,0.1)] !text-[var(--color-bg-app)] !shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)] no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">2</a>
                            <a href="#task-3" class="clay-interactive task-nav-btn h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 !bg-[var(--color-danger)] !border-[rgba(0,0,0,0.1)] text-white !shadow-[0_4px_12px_rgba(251,113,133,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)] no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">3</a>
                            <a href="#task-4" class="clay-interactive task-nav-btn h-14 px-8 w-auto min-w-[4rem] inline-flex items-center justify-center rounded-2xl font-black text-xl transition-all hover:-translate-y-0.5 !bg-[var(--color-warning)] !border-[rgba(0,0,0,0.1)] text-white !shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-4px_0_rgba(0,0,0,0.15)] dark:!shadow-[0_2px_4px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.15)] dark:active:!shadow-[inset_0_4px_8px_rgba(0,0,0,0.4)] no-underline" onclick="document.querySelector('[data-tab=\\'tasks\\']').click();">4</a>
                        {% endif %}"""
html = html.replace(old_nav, new_nav)

# 4. Replace Form Mock Tasks
# Using regex to extract from <!-- Mock Task --> to {% endif %} just before </div>\n            </div>\n            \n            <!-- ====== МАТЕРИАЛЫ ====== -->
match_mock_form = re.search(r'<!-- Mock Task -->.*</button>\n                            </div>\n                        </div>\n                    \{\% endif \%\}', html, re.DOTALL)
if match_mock_form:
    new_form_mock = """<!-- REAL EXAM DATA MOCK -->
                        <div id="task-1" class="clay-card p-10 mt-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">1</span>
                                Задание 14 (Позиционные системы)
                            </div>
                            <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">Значение арифметического выражения: <b>4<sup class="text-primary font-bold">2026</sup> + 2<sup class="text-primary font-bold">2024</sup> - 8</b> — записали в системе счисления с основанием 4. <br><br>Сколько цифр <b>"3"</b> содержится в этой записи?</p>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Ваш ответ:</label>
                                <input type="text" class="w-full h-16 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 rounded-2xl px-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300" placeholder="Введите короткий ответ...">
                            </div>
                        </div>

                        <div id="task-2" class="clay-card p-10 mt-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">2</span>
                                Задание 6 (Черепаха)
                            </div>
                            <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">Исполнитель Черепаха действует на плоскости с декартовой системой координат...<br>Черепахе был дан для исполнения следующий алгоритм:<br><br><code class="block bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] dark:border-white/10 p-4 rounded-xl text-primary font-mono text-lg my-4 font-bold shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]">Повтори 7 [ Вперед 10 Направо 120 ]</code><br>Определите, сколько точек с целочисленными координатами будут находиться внутри области, ограниченной линией, заданной данным алгоритмом.</p>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Автоматически проверено:</label>
                                <input type="text" value="45" readonly class="w-full h-16 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-success/40 dark:border-success/30 rounded-2xl px-6 text-xl font-bold outline-none text-success shadow-[0_0_0_4px_rgba(34,197,94,0.1)] transition-all">
                            </div>
                        </div>

                        <div id="task-3" class="clay-card p-10 mt-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">3</span>
                                Задание 24 (Обработка строк)
                            </div>
                            <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">Текстовый файл <code>24.txt</code> содержит только заглавные буквы латинского алфавита (A, B, C...).<br>Определите максимальное количество идущих подряд символов, среди которых нет комбинации символов "CAT".</p>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Развернутое решение (Код):</label>
                                <textarea class="w-full h-48 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-[var(--color-stroke)] dark:border-white/10 rounded-2xl p-6 text-xl font-bold outline-none focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] transition-all placeholder:text-[var(--color-text-muted)] dark:text-zinc-300 font-mono" placeholder="Вставьте ваш код на Python сюда...">with open('24.txt') as f:
    s = f.readline().replace('CAT', 'CA AT')
    print(max(len(c) for c in s.split()))</textarea>
                            </div>
                        </div>

                        <div id="task-4" class="clay-card p-10 mt-4 mb-4">
                            <div class="font-black text-primary text-2xl flex items-center gap-4 mb-8 pb-6 border-b border-[var(--color-stroke)]">
                                <span class="bg-[#4F46E5] text-white w-12 h-12 rounded-xl flex items-center justify-center shadow-[inset_0_-3px_0_rgba(0,0,0,0.2)] dark:bg-[#3730A3] dark:text-[#A5B4FC] dark:shadow-[inset_0_-3px_0_rgba(0,0,0,0.4)] shrink-0">4</span>
                                Задание 15 (Логика)
                            </div>
                            <p class="text-xl text-[var(--color-text-primary)] leading-relaxed mb-10 font-medium whitespace-pre-wrap">Для какого наименьшего целого неотрицательного числа <b>A</b> выражение:<br><br><span class="block bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] dark:border-white/10 p-4 rounded-xl text-primary font-mono text-lg my-4 text-center font-bold shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]">(x & 25 ≠ 0) ∨ ((x & 17 = 0) → (x & A ≠ 0))</span><br>тождественно истинно (то есть принимает значение 1 при любом целом неотрицательном значении переменной <b>x</b>)?</p>
                            
                            <div class="bg-[var(--color-bg-inset)] rounded-[28px] p-8 border border-[var(--color-stroke)] dark:border-white/10 shadow-[inset_0_4px_16px_rgba(0,0,0,0.05)]">
                                <label class="block font-black text-[var(--color-text-secondary)] dark:text-zinc-300 uppercase tracking-widest text-sm mb-4">Вернуть на доработку:</label>
                                <input type="text" value="38" class="w-full h-16 bg-[var(--color-bg-surface)] dark:bg-[var(--color-bg-surface-alt)] border-2 border-warning/40 dark:border-warning/30 rounded-2xl px-6 text-xl font-bold outline-none text-warning shadow-[0_0_0_4px_rgba(245,158,11,0.1)] transition-all">
                            </div>
                        </div>

                        <button type="submit" class="clay-interactive mt-8 w-full h-16 bg-[#4F46E5] text-white rounded-2xl font-black text-xl border border-[#4338CA] shadow-[0_8px_24px_rgba(79,70,229,0.3),inset_0_-4px_0_rgba(0,0,0,0.2)] dark:bg-[#4F46E5] dark:text-white dark:border-[#3730A3] dark:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-4px_0_rgba(0,0,0,0.3)] active:translate-y-1 active:shadow-[inset_0_4px_8px_rgba(0,0,0,0.3)] hover:brightness-110 cursor-pointer">
                            Отправить на проверку
                        </button>
                    {% endif %}"""
    html = html.replace(match_mock_form.group(0), new_form_mock)

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)
