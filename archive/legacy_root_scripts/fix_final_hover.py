import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы жестко стабилизируем Левый Остров, чтобы он расширялся равномерно из центра и не выталкивал правый свитчер
old_hub_wrapper = r'<!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар \(Fluid Morph\) -->[\s\S]*?<header.*?class="hub-container[^>]*>'

new_hub_wrapper = """<!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар (Fluid Morph) -->
    <div class="pointer-events-auto group relative flex items-center justify-center shrink-0 origin-center">
        <!-- Подушка безопасности для ховера -->
        <div class="absolute top-full left-1/2 -translate-x-1/2 w-[120vw] h-32 z-10 hidden group-hover:block"></div>
        
        <!-- Капсула, которая расширяется при наведении ИЗ ЦЕНТРА -->
        <header class="hub-container bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] rounded-full h-14 px-3 flex items-center justify-center shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/80 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] overflow-hidden">
"""

html = re.sub(old_hub_wrapper, new_hub_wrapper, html)

# Исправляем ширину в CSS
css_old = r'/\* Раскрытое состояние \(Hover Morph\) \*/\s*#floating-hub-global:hover \.hub-container \{[\s\S]*?\}'

css_new = """/* Раскрытое состояние (Hover Morph) */
#floating-hub-global:hover .hub-container {
    padding: 0 1.5rem;
    gap: 1rem;
}

/* Принудительно делаем ссылки кликабельными (активными) при ховере */
#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-icon-btn,
#floating-hub-global:hover a {
    pointer-events: auto !important;
}"""
html = re.sub(css_old, css_new, html)

# Сделаем жесткое переопределение JS свитчера 
old_js = r'<script>\s*// НАДЁЖНЫЙ ФИКС СМЕНЫ ТЕМЫ[\s\S]*?</script>'
new_js = """<script>
// НАДЁЖНЫЙ ФИКС СМЕНЫ ТЕМЫ
function toggleThemeChecked() {
    const htmlEl = document.documentElement;
    // Определяем текущую тему
    let currentTheme = htmlEl.getAttribute('data-theme') || localStorage.getItem('theme') || 'light';
    
    // Если auto, определяем по OS
    if (currentTheme === 'auto') {
        currentTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    
    // Инвертируем
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    // Физически меняем класс (в Tailwind это data-theme)
    htmlEl.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    // Триггерим ивент для графика и других JS скриптов
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: newTheme }));
    console.log("Theme switched to: ", newTheme);
}
</script>"""
html = re.sub(old_js, new_js, html)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
