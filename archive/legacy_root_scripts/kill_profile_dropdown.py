import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. ЗАЧИСТКА МЕНЮ ПРОФИЛЯ
# Профиль-меню слишком хрупкое. Мы убиваем его полностью и заменяем на компактный свитчер тем.

# Вырезаем целиком блок dock-actions
old_actions_pattern = r'{# ── Right side: Search \+ Avatar ── #}.*?</div>\s*</header>'

new_actions = """{# ── Right side: Search + Quick Tools ── #}
        <div class="dock-actions flex items-center gap-2">
            {% if config.get('IS_SANDBOX') %}
            <span class="sandbox-badge">SANDBOX</span>
            {% endif %}

            <button class="dock-icon-btn clay-interactive" onclick="document.getElementById('cmdPalette').classList.add('active')" title="Поиск (Ctrl+K)" type="button">
                <i class="ph-bold ph-magnifying-glass text-xl"></i>
            </button>

            {% if current_user and current_user.is_authenticated %}
            <!-- Прямой свитчер тем (Новый Clay-дизайн) -->
            <button class="theme-switcher-btn clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] hover:-translate-y-1 transition-all" onclick="toggleThemeQuick()" title="Сменить тему">
                <i class="ph-bold ph-sun text-xl block dark:hidden text-[#F59E0B]"></i>
                <i class="ph-bold ph-moon text-xl hidden dark:block text-[#A5B4FC]"></i>
            </button>

            <!-- Прямой логаут вместо меню профиля -->
            <a href="{{ url_for('auth.logout') }}" class="clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-danger/10 text-danger border border-danger/20 shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] hover:-translate-y-1 hover:bg-danger/20 transition-all ml-1" title="Выйти">
                <i class="ph-bold ph-sign-out text-lg"></i>
            </a>
            {% endif %}
        </div>

        </header>"""

html = re.sub(old_actions_pattern, new_actions, html, flags=re.DOTALL)

# Также удалим JS логику этого выпадающего меню, так как мы его убили
html = re.sub(r'<script>\s*\(function\(\) \{\s*if \(window\.__profileDropdownInitialized\).*?\}\)\(\);\s*</script>', '', html, flags=re.DOTALL)

# Добавим нашу кастомную JS-логику для быстрого переключения тем напрямую
quick_theme_js = """<script>
// Прямой toggle темы для новой луны/солнца
function toggleThemeQuick() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'auto';
    let newTheme;
    
    // Простая логика: если сейчас 'dark' или если 'auto' и ОС тёмная, то переключаем на 'light'
    if (currentTheme === 'dark') {
        newTheme = 'light';
    } else if (currentTheme === 'light') {
        newTheme = 'dark';
    } else {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        newTheme = prefersDark ? 'light' : 'dark';
    }

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    // Диспатчим ивент, если на сайте где-то слушают старые свитчеры
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: newTheme }));
}
</script>"""

if 'toggleThemeQuick()' not in html:
    html = html.replace('</style>', '</style>\n' + quick_theme_js)


# 2. ИСПРАВЛЕНИЕ АКТИВНОЙ КНОПКИ В СВЕТЛОЙ ТЕМЕ
# Я заменю цвет с #312E81 на приятный объемный градиент для светлой темы
old_light_color = r'''html\[data-theme="light"\] #floating-hub-global \.dock-nav-item\.active \{
    /\* Если в светлой теме индиго фон режет глаза, делаем насыщенный темный индиго \*/
    background: #312E81 !important; 
    color: #EEF2FF !important;
\}'''

new_light_color = '''html[data-theme="light"] #floating-hub-global .dock-nav-item.active {
    /* Сочный лавандовый индиго с вдавленной внутренней тенью для эффекта Clay */
    background: linear-gradient(145deg, #6366f1, #4f46e5) !important;
    color: #ffffff !important;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.2), inset 0 -2px 4px rgba(255, 255, 255, 0.4), 0 4px 12px rgba(79, 70, 229, 0.3) !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
}'''

html = re.sub(old_light_color, new_light_color, html)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)

