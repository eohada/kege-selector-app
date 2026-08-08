import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы добавили HTML-классы, но нам нужен еще <style> перехватчик для 'active' состояния док-итемов, 
# чтобы перекрыть их старые стили. Добавим его в самый конец файла.
css_injection = """
<style>
/* Claymorphism Active State for Global Floating Hub */
#floating-hub-global .dock-nav-item.active {
    background: var(--color-primary) !important;
    color: white !important;
    box-shadow: 0 4px 12px rgba(79,70,229,0.3), inset 0 -2px 0 rgba(0,0,0,0.2) !important;
}
html[data-theme="dark"] #floating-hub-global .dock-nav-item.active {
    box-shadow: 0 4px 12px rgba(0,0,0,0.4), inset 0 -2px 0 rgba(0,0,0,0.3) !important;
}

/* Hide the old static background of dock-nav */
.dock-nav {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

#floating-hub-global header {
    width: auto !important;
    gap: 1rem !important;
}

#floating-hub-global .dock-brand {
    padding-left: 0;
    margin-right: 0.5rem;
}
</style>
"""

# Обертка для ID #floating-hub-global (мы забыли его добавить в предыдущем скрипте)
html = html.replace('<!-- INNOVATIVE FLOATING HUB (Global Navbar) -->\n<div class="fixed top-4', '<!-- INNOVATIVE FLOATING HUB (Global Navbar) -->\n<div id="floating-hub-global" class="fixed top-4')

if '<!-- INNOVATIVE FLOATING HUB (Global Navbar) -->' in html:
    html += css_injection

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
