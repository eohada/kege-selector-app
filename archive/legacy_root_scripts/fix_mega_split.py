import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. ПОЛНОСТЬЮ УБИВАЕМ ОБЩИЙ ФЛЕКС КОНТЕЙНЕР #floating-hub-global
# И разбиваем его на два абсолютно независимых fixed элемента.

old_wrapper = r'<!-- INNOVATIVE FLOATING HUB \(Global Navbar \+ Independent Theme Switcher\) -->[\s\S]*?<!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар \(Fluid Morph\) -->'

# Мы больше не оборачиваем острова в один flex. Они живут отдельно.
new_wrapper = """<!-- INNOVATIVE FLOATING HUB (Totally Isolated Islands) -->
    
    <!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар (Fluid Morph) -->"""
html = re.sub(old_wrapper, new_wrapper, html)

# Исправляем Левый Остров: задаем ему жесткую привязку по центру
old_left_island = r'<div class="pointer-events-auto group relative flex items-center justify-center shrink-0 origin-center">'

new_left_island = r'<div id="floating-hub-global" class="fixed top-4 left-1/2 -translate-x-1/2 z-[100] pointer-events-auto group relative flex items-center justify-center origin-center">'
html = html.replace(old_left_island, new_left_island)

# Исправляем Правый Остров: задаем ему жесткую привязку сбоку, ВНЕ левого острова
old_right_island = r'<!-- ПРАВЫЙ ОСТРОВ: Инлайн-Свитчер Тем БЕЗ Ховера -->\s*<div class="pointer-events-auto shrink-0 flex items-center">.*?</div> <!-- /Правый остров -->\s*</div>\s*</div>'

new_right_island = """<!-- ПРАВЫЙ ОСТРОВ: Инлайн-Свитчер Тем БЕЗ Ховера (Hard Positioned) -->
<div id="theme-switcher-island" class="fixed top-4 left-[calc(50%+190px)] z-[100] pointer-events-auto flex items-center">
    <button class="clay-interactive w-14 h-14 rounded-full flex items-center justify-center bg-[var(--color-bg-surface)]/90 backdrop-blur-xl border border-[var(--color-stroke)] shadow-[0_8px_24px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/90 dark:border-white/10 dark:shadow-[0_8px_24px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] hover:scale-105 active:scale-95 transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary cursor-pointer pointer-events-auto" onclick="toggleThemeChecked()" title="Сменить тему">
        <i class="ph-bold ph-sun text-2xl block dark:hidden text-[#1E1B4B]"></i>
        <i class="ph-bold ph-moon text-2xl hidden dark:block text-[#A5B4FC]"></i>
    </button>
</div>"""

# На всякий случай подчистим старое закрытие flex-родителя `</div></div>` в конце
html = re.sub(
    r'<!-- ПРАВЫЙ ОСТРОВ: Инлайн-Свитчер Тем БЕЗ Ховера -->.*?</div> <!-- /Правый остров -->\s*</div>', 
    new_right_island, 
    html, 
    flags=re.DOTALL
)


# 2. РЕЛЕВАНТНЫЙ JS СВИТЧЕР (100% ГАРАНТИЯ ПЕРЕКЛЮЧЕНИЯ DATA-THEME)
old_js = r'<script>\s*// НАДЁЖНЫЙ ФИКС СМЕНЫ ТЕМЫ[\s\S]*?</script>'

new_js = """<script>
// АБСОЛЮТНО НЕУБИВАЕМЫЙ СВИТЧЕР ТЕМ
function toggleThemeChecked() {
    const htmlEl = document.documentElement;
    // Смотрим, какой класс реально сейчас висит на <html>
    const currentTheme = htmlEl.getAttribute('data-theme') || 'light';
    
    // Жестко инвертируем
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    // Перезаписываем
    htmlEl.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    console.log('BooStudy Theme toggled to:', newTheme);
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: newTheme }));
}
</script>"""

html = re.sub(old_js, new_js, html, flags=re.DOTALL)


with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)

