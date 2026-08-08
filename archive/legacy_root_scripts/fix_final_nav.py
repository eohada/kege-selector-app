import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. ЗАМЕНА СТИЛЯ АКТИВНОЙ КНОПКИ В СВЕТЛОЙ ТЕМЕ
old_light_color = r'''html\[data-theme="light"\] #floating-hub-global \.dock-nav-item\.active \{.*?\}'''
new_light_color = '''html[data-theme="light"] #floating-hub-global .dock-nav-item.active {
    background: linear-gradient(145deg, #6366f1, #4f46e5) !important;
    color: #ffffff !important;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.2), inset 0 -2px 4px rgba(255, 255, 255, 0.4), 0 4px 12px rgba(79, 70, 229, 0.3) !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
}'''
html = re.sub(old_light_color, new_light_color, html, flags=re.DOTALL)

# 2. УДАЛЕНИЕ ПРОФИЛЬНОГО ДРОПДАУНА И ВНЕДРЕНИЕ INLINE-ПЕРЕКЛЮЧАТЕЛЯ
# Заменяем структуру <div class="dock-actions">
actions_pattern = r'<div class="dock-actions">[\s\S]*?</div>\s*</header>'

new_actions = """<div class="dock-actions-permanent flex items-center gap-2">
            {% if config.get('IS_SANDBOX') %}
            <span class="sandbox-badge">SANDBOX</span>
            {% endif %}

            <!-- Прямой свитчер тем (Inline Toggle) -->
            <button class="theme-switcher-btn clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-[var(--color-bg-inset)] border border-[var(--color-stroke)] shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] hover:-translate-y-1 transition-all pointer-events-auto" onclick="toggleThemeQuick()" title="Сменить тему">
                <i class="ph-bold ph-sun text-xl block dark:hidden text-[#F59E0B]"></i>
                <i class="ph-bold ph-moon text-xl hidden dark:block text-[#A5B4FC]"></i>
            </button>

            <!-- Группа, скрытая по умолчанию, появляющаяся по ховеру -->
            <div class="dock-actions-hover hidden group-hover:flex items-center gap-2">
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
        </div>
        </header>"""

html = re.sub(actions_pattern, new_actions, html)

# Удаляем скрипт инициализации старого профильного меню
html = re.sub(r'<script>\s*\(function\(\) \{\s*if \(window\.__profileDropdownInitialized\)[\s\S]*?\}\)\(\);\s*</script>', '', html)

# Добавляем JS нового свитчера, если его нет
js_script = """<script>
// Прямой toggle темы для новой луны/солнца
function toggleThemeQuick() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'auto';
    let newTheme;
    if (currentTheme === 'dark') { newTheme = 'light'; }
    else if (currentTheme === 'light') { newTheme = 'dark'; }
    else { newTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'; }
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: newTheme }));
}
</script>"""

if 'toggleThemeQuick' not in html:
    html = html.replace('</style>', '</style>\n' + js_script)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
