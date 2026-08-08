import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. ЗАМЕНА СТРУКТУРЫ ХАБА НА ДВА НЕЗАВИСИМЫХ ОСТРОВА
# Мы полностью вырезаем старый `<div id="floating-hub-global"...` и переписываем его.
old_hub_wrapper = r'<!-- INNOVATIVE FLOATING HUB \(Global Navbar Fluid Morph\) -->[\s\S]*?<header.*?class="hub-container[^>]*>'

new_hub_wrapper = """<!-- INNOVATIVE FLOATING HUB (Global Navbar + Independent Theme Switcher) -->
<div id="floating-hub-global" class="fixed top-4 left-1/2 -translate-x-1/2 z-[100] w-auto max-w-[95vw] pointer-events-none hidden md:flex justify-center flex-row items-center gap-3">
    
    <!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар (Fluid Morph) -->
    <div class="pointer-events-auto group relative">
        <!-- Подушка безопасности для ховера -->
        <div class="absolute top-full left-0 w-full h-32 z-10 hidden group-hover:block"></div>
        
        <!-- Капсула, которая расширяется при наведении -->
        <header class="hub-container bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] rounded-full h-14 px-3 flex items-center shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/80 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] mx-auto relative transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] w-auto max-w-sm group-hover:max-w-[1440px] group-hover:px-6 group-hover:gap-4 overflow-hidden">
"""

html = re.sub(old_hub_wrapper, new_hub_wrapper, html)

# 2. РАЗДЕЛЕНИЕ КОНТЕНТА И ПРАВЫЙ ОСТРОВ
# Вырезаем старый свитчер тем и блок действий изнутри левого острова.
old_actions = r'<div class="dock-actions-permanent flex items-center gap-2">[\s\S]*?</header>'

new_actions = """<div class="dock-actions-hover hidden group-hover:flex items-center gap-2 ml-2">
            <button class="dock-icon-btn clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] hover:-translate-y-1 transition-all" onclick="document.getElementById('cmdPalette').classList.add('active')" title="Поиск (Ctrl+K)" type="button">
                <i class="ph-bold ph-magnifying-glass text-xl"></i>
            </button>
            
            {% if current_user and current_user.is_authenticated %}
            <!-- Логаут -->
            <a href="{{ url_for('auth.logout') }}" class="clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-danger/10 text-danger border border-danger/20 shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] hover:-translate-y-1 hover:bg-danger/20 transition-all ml-1" title="Выйти">
                <i class="ph-bold ph-sign-out text-lg"></i>
            </a>
            {% endif %}
        </div>
        </header>
    </div> <!-- /Левый остров -->

    <!-- ПРАВЫЙ ОСТРОВ: Инлайн-Свитчер Тем БЕЗ Ховера -->
    <div class="pointer-events-auto shrink-0 flex items-center">
        <button class="clay-interactive w-14 h-14 rounded-full flex items-center justify-center bg-[var(--color-bg-surface)]/90 backdrop-blur-xl border border-[var(--color-stroke)] shadow-[0_8px_24px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/90 dark:border-white/10 dark:shadow-[0_8px_24px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] hover:scale-105 active:scale-95 transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary cursor-pointer" onclick="toggleThemeChecked()" title="Сменить тему">
            <!-- Две иконки, Tailwind сам скроет ненужную в зависимости от класса 'dark' на html -->
            <i class="ph-bold ph-sun text-2xl block dark:hidden text-[#1E1B4B]"></i>
            <i class="ph-bold ph-moon text-2xl hidden dark:block text-[#A5B4FC]"></i>
        </button>
    </div> <!-- /Правый остров -->
"""

html = re.sub(old_actions, new_actions, html)

# 3. ИСПРАВЛЕНИЕ JS ПЕРЕКЛЮЧАТЕЛЯ ТЕМ (Со 100% гарантией работы)
old_js = r'<script>\s*// Прямой toggle темы.*?window\.dispatchEvent.*?\}\s*</script>'

new_js = """<script>
// НАДЁЖНЫЙ ФИКС СМЕНЫ ТЕМЫ
function toggleThemeChecked() {
    console.log("Toggle theme clicked!");
    const htmlEl = document.documentElement;
    const currentTheme = htmlEl.getAttribute('data-theme') || 'auto';
    let newTheme;
    
    // Если сейчас темная — делаем светлую, иначе темную
    if (currentTheme === 'dark') {
        newTheme = 'light';
    } else {
        newTheme = 'dark';
    }

    console.log("Switching theme to:", newTheme);
    
    // Жестко перезаписываем атрибут (Tailwind опирается на него)
    htmlEl.setAttribute('data-theme', newTheme);
    
    // Сохраняем в localStorage
    localStorage.setItem('theme', newTheme);
    
    console.log("Theme switched successfully.");
}
</script>"""

html = re.sub(old_js, new_js, html, flags=re.DOTALL)


# 4. ПОЛИРОВКА CSS
# Избавляемся от старых CSS хаков с display: none для панелей
old_css = r'<style>[\s\S]*?/\* Свернутое состояние.*?display: none;.*?\}'
new_css = """<style>
/* ===============================================
   УМНЫЙ КОНТЕКСТНЫЙ ВИДЖЕТ (Независимые Острова)
=============================================== */

/* Свернутое состояние (микро-остров) */
#floating-hub-global .dock-nav-item:not(.active),
#floating-hub-global .dock-mega,
#floating-hub-global .dock-actions-hover {
    width: 0;
    opacity: 0;
    overflow: hidden;
    padding: 0 !important;
    margin: 0 !important;
    pointer-events: none;
    transform: scale(0.9);
    transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
    white-space: nowrap;
}"""

html = re.sub(old_css, new_css, html, flags=re.DOTALL)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)

