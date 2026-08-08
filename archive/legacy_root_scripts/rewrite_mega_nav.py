import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Заменяем класс на контейнере 'div.pointer-events-auto' так, чтобы меню профиля не обрезалось.
# Мы убираем 'overflow-hidden' у header, так как он обрезал профиль-меню, но мы хотим, чтобы 
# меню пружинило. Для этого мы зададим overflow-hidden только тем секциям, которые должны прятаться.

# Сначала восстановим <header>, чтобы он НЕ имел overflow-hidden.
old_header = r'<header class="bg-\[var\(--color-bg-surface\)\]/80 backdrop-blur-xl border border-\[var\(--color-stroke\)\] rounded-full h-16 flex items-center shadow-\[0_8px_32px_rgba\(0,0,0,0\.1\),inset_0_2px_4px_rgba\(255,255,255,0\.8\)\] dark:bg-\[var\(--color-bg-surface\)\]/80 dark:border-white/10 dark:shadow-\[0_8px_32px_rgba\(0,0,0,0\.4\),inset_0_2px_4px_rgba\(255,255,255,0\.05\)\] transition-all ease-\[cubic-bezier\(0\.34,1\.56,0\.64,1\)\] duration-500 hover:gap-4 hover:px-6 w-min hover:w-auto overflow-hidden mx-auto">'
new_header = r'<header class="hub-container bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] rounded-full h-16 px-3 flex items-center shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/80 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] mx-auto relative">'
html = re.sub(old_header, new_header, html)


# 2. Обновляем CSS.
new_css = """<style>
/* ===============================================
   УМНЫЙ КОНТЕКСТНЫЙ ВИДЖЕТ (Hover Morph)
=============================================== */

/* Контейнер панели */
#floating-hub-global .hub-container {
    width: auto;
    transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
    /* Никакого overflow: hidden, чтобы профиль-меню могло выпадать! */
}

/* Свернутое состояние (микро-остров) */
/* Скрываем всё кроме Бренда, Активной Вкладки, и Таймера */
#floating-hub-global .dock-nav-item:not(.active),
#floating-hub-global .dock-mega,
#floating-hub-global .dock-actions {
    display: none;
    opacity: 0;
    width: 0;
    margin: 0 !important;
    padding: 0 !important;
    transform: scale(0.9);
}

/* Анимация при Ховере на панель (Раскрытие) */
#floating-hub-global:hover .hub-container {
    padding: 0 1.5rem;
    gap: 1rem;
}

#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-mega,
#floating-hub-global:hover .dock-actions {
    display: flex;
    opacity: 1;
    width: auto;
    transform: scale(1);
    transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Возвращаем отступы элементам при ховере */
#floating-hub-global:hover .dock-nav-item:not(.active) {
    padding: 0.5rem 1rem !important;
}

/* Меню Профиля (z-index fix) */
#floating-hub-global .profile-dropdown-content {
    z-index: 110 !important;
    position: absolute;
    top: 120%; /* Опускаем ниже панели */
    right: 0;
    margin-top: 0.5rem;
}

/* Стилизация активной кнопки (Комната / Главная) */
#floating-hub-global .dock-nav-item.active {
    background: var(--color-primary) !important;
    color: white !important;
    box-shadow: 0 4px 12px rgba(79,70,229,0.3), inset 0 -2px 0 rgba(0,0,0,0.2) !important;
    margin: 0 0.2rem;
}
html[data-theme="dark"] #floating-hub-global .dock-nav-item.active {
    box-shadow: 0 4px 12px rgba(0,0,0,0.4), inset 0 -2px 0 rgba(0,0,0,0.3) !important;
}

/* Контекстный Индикатор (Таймер) */
.hub-context-pill {
    background: var(--color-bg-inset);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-stroke);
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    font-weight: 800;
    font-size: 0.85rem;
}
[data-theme="dark"] .hub-context-pill {
    color: #e4e4e7;
    border-color: rgba(255,255,255,0.1);
}

.dock-nav {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex;
    align-items: center;
    gap: 0.25rem;
}
</style>"""

html = re.sub(r'<style>.*?</style>', new_css, html, flags=re.DOTALL)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
