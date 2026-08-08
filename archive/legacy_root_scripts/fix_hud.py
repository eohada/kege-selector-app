import re

with open('templates/lesson_homework.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. ЧИСТКА САЙДБАРА
# Удаляем самый первый дубль, который "завис" без click() обработчиков:
bug_pattern = r'<!-- Squish-мини кнопки -->\s*<div class="grid grid-cols-4 gap-3">\s*<button type="button" class="clay-interactive w-full pt-\[100%\] relative rounded-xl border border-\[var\(--color-stroke\)\].*?<!-- Squish-мини кнопки -->'
replacement = r'<!-- Squish-мини кнопки -->'

html = re.sub(bug_pattern, replacement, html, flags=re.DOTALL)

# 2. ИННОВАЦИОННЫЙ НАВИГАЦИОННЫЙ ХАБ (Плавающий док)
# Вырезаем старый полноразмерный бар навигации:
nav_pattern = r'<!-- Плавающие табы навигации -->\s*<div class="flex gap-2 pb-2 overflow-x-auto hide-scroll sticky top-2 z-\[40\] bg-\[var\(--color-bg-app\)\]\/80 backdrop-blur-xl p-2 rounded-2xl border border-\[var\(--color-stroke\)\] shadow-\[0_4px_12px_rgba\(0,0,0,0\.05\)\]" role="tablist">.*?</div>'

# Новый компактный Floating Dock (с эффектом Dynamic Island):
new_hud = """<!-- INNOVATIVE FLOATING HUB -->
    <div class="fixed top-6 left-1/2 -translate-x-1/2 z-[100] transition-all duration-300 ease-out" id="floating-hub">
        <div class="flex items-center gap-2 p-2 rounded-full bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/60 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)]" role="tablist">
            
            <button type="button" class="clay-interactive tab-btn active flex items-center justify-center gap-2 px-6 py-3 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] 
                                         [&.active]:bg-primary [&.active]:text-white [&.active]:shadow-[0_4px_12px_rgba(79,70,229,0.3),inset_0_-2px_0_rgba(0,0,0,0.2)] dark:[&.active]:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]" 
                    data-tab="theory" role="tab">
                <i class="ph-bold ph-book-open text-xl"></i> <span class="hidden md:inline">Конспект</span>
            </button>
            
            <button type="button" class="clay-interactive tab-btn flex items-center justify-center gap-2 px-6 py-3 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] 
                                         [&.active]:bg-success [&.active]:text-white [&.active]:shadow-[0_4px_12px_rgba(34,211,238,0.3),inset_0_-2px_0_rgba(0,0,0,0.2)] dark:[&.active]:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]" 
                    data-tab="tasks" role="tab">
                <i class="ph-bold ph-chalkboard-teacher text-xl"></i> <span class="hidden md:inline">Классная работа</span>
            </button>
            
            <button type="button" class="clay-interactive tab-btn flex items-center justify-center gap-2 px-6 py-3 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] 
                                         [&.active]:bg-warning [&.active]:text-white [&.active]:shadow-[0_4px_12px_rgba(245,158,11,0.3),inset_0_-2px_0_rgba(0,0,0,0.2)] dark:[&.active]:shadow-[0_4px_12px_rgba(0,0,0,0.4),inset_0_-2px_0_rgba(0,0,0,0.3)]" 
                    data-tab="materials" role="tab">
                <i class="ph-bold ph-paperclip text-xl"></i> <span class="hidden md:inline">Материалы</span>
            </button>
            
        </div>
    </div>"""

html = re.sub(nav_pattern, new_hud, html, flags=re.DOTALL)

with open('templates/lesson_homework.html', 'w', encoding='utf-8') as f:
    f.write(html)

