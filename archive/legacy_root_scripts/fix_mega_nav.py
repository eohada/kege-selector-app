import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы сносим старую структуру хаба и делаем "Fluid Hover Morph"
# 1. Захватываем весь <div id="floating-hub-global"... вплоть до </header></div></div>
# Поскольку регулярки могут ошибаться на длинных блоках, я заменю шапку до <nav class="dock-nav">
old_top = r'<!-- INNOVATIVE FLOATING HUB \(Global Navbar\) -->.*?<header[^>]+>'

new_top = """<!-- INNOVATIVE FLOATING HUB (Global Navbar Fluid Morph) -->
<div id="floating-hub-global" class="fixed top-6 left-1/2 -translate-x-1/2 z-[100] w-auto max-w-[95vw] pointer-events-none hidden md:flex justify-center group flex-row items-center gap-2">
    <div class="pointer-events-auto">
        <!-- Капсула, которая расширяется при наведении -->
        <header class="bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] rounded-full h-16 flex items-center shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/80 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] transition-all ease-[cubic-bezier(0.34,1.56,0.64,1)] duration-500 hover:gap-4 hover:px-6 w-min hover:w-auto overflow-hidden mx-auto">
"""

html = re.sub(old_top, new_top, html, flags=re.DOTALL)

# 2. Очищаем стили навигационных ссылок в доке
# Заменяем class="dock-nav-item" (без clay-interactive, если они еще не добавлены)
def replace_nav_item(match):
    original = match.group(0)
    if 'clay-interactive' not in original:
        return original.replace(
            'class="dock-nav-item ', 
            'class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] '
        )
    return original

html = re.sub(r'class="dock-nav-item .*?"', replace_nav_item, html)

# Удалим устаревший hover эффект dock-nav-highlight из HTML
html = html.replace('<div class="dock-nav-highlight" data-nav-highlight aria-hidden="true"></div>', '')

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
