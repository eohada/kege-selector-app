import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы вырезаем испорченный Floating Dock, который я случайно налепил на табы урока
bad_hub_pattern = r'<!-- Плавающие табы навигации -->\s*<div class="fixed top-6 left-1/2 -translate-x-1/2 z-\[100\].*?</div>\s*</div>'

# Если не нашло первую вариацию, ищем любую fixed-капсулу перед сеткой
bad_hub_pattern_alt = r'<!-- Плавающие табы навигации -->\s*<div[^>]*fixed[^>]*>.*?</div>\s*</div>'

# Краш-фикс: просто снесем всё от "Плавающие табы навигации" до "ИДЕАЛЬНАЯ СЕТКА"
bad_hub_pattern_broad = r'<!-- Плавающие табы навигации -->.*?<!-- ИДЕАЛЬНАЯ СЕТКА: strictly Grid -->'

# И возвращаем оригинальную, скромную горизонтальную панельку для табов конспекта/задач
good_lesson_tabs = """<!-- Внутристраничные табы навигации -->
    <div class="flex gap-2 pb-2 overflow-x-auto hide-scroll mb-4" role="tablist">
        <button type="button" class="clay-interactive tab-btn active flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="theory" role="tab">
            <i class="ph-bold ph-book-open text-lg"></i> Конспект
        </button>
        <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="tasks" role="tab">
            <i class="ph-bold ph-chalkboard-teacher text-lg"></i> Классная работа
        </button>
        <button type="button" class="clay-interactive tab-btn flex-1 min-w-max px-6 py-3 rounded-xl font-bold transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 bg-[var(--color-bg-surface)] border border-[var(--color-stroke)] shadow-[0_2px_4px_rgba(0,0,0,0.02)] [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:border-primary/20 [&.active]:shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]" data-tab="materials" role="tab">
            <i class="ph-bold ph-paperclip text-lg"></i> Материалы
        </button>
    </div>

    <!-- ИДЕАЛЬНАЯ СЕТКА: strictly Grid -->"""

html_fixed = re.sub(bad_hub_pattern_broad, good_lesson_tabs, html, flags=re.DOTALL)

# Если паттерн не сработал из-за мелких изменений
if html_fixed == html:
    # Ищем жесткий fixed top-6 и убиваем его
    html_fixed = html.replace('class="fixed top-6 left-1/2 -translate-x-1/2 z-[100] transition-all duration-300 ease-out" id="floating-hub"', 'class="flex w-full mb-6 mx-auto justify-center"')

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html_fixed)
