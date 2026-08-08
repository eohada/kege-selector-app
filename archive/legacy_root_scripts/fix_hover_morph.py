import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Захватываем <style> блок и полностью переписываем логику скрытия и ховера
old_css = r'<style>[\s\S]*?</style>'

new_css = """<style>
/* ===============================================
   УМНЫЙ КОНТЕКСТНЫЙ ВИДЖЕТ (Fluid Hover Morph 3.0)
=============================================== */

/* Контейнер панели */
#floating-hub-global .hub-container {
    width: auto;
    max-width: 320px; /* Компактное состояние (Default State) */
    transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
    /* Защитный барьер: невидимый паддинг внизу у группы, чтобы мышь не соскакивала */
    position: relative;
}

#floating-hub-global::after {
    content: '';
    position: absolute;
    top: 100%;
    left: -10vw;
    width: 120vw;
    height: 300px;
    z-index: 10;
    pointer-events: none; /* по умолчанию не перехватывает клики */
}
#floating-hub-global:hover::after {
    pointer-events: auto; /* при ховере удерживает фокус */
}

/* Свернутое состояние (микро-остров) */
/* Скрываем всё кроме Бренда, Активной Вкладки, и Таймера ПЛАВНО */
#floating-hub-global .dock-nav-item:not(.active),
#floating-hub-global .dock-mega,
#floating-hub-global .dock-actions {
    width: 0;
    opacity: 0;
    overflow: hidden;
    padding: 0 !important;
    margin: 0 !important;
    pointer-events: none;
    transform: scale(0.95);
    transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
    /* display: flex ВМЕСТО none, чтобы transition работал */
    display: flex;
}

/* Раскрытое состояние (Hover Morph) */
#floating-hub-global:hover .hub-container {
    max-width: 1440px; /* Раскрываемся */
    padding: 0 1.5rem;
    gap: 1rem;
}

#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-mega,
#floating-hub-global:hover .dock-actions {
    opacity: 1;
    width: auto;
    pointer-events: auto;
    transform: scale(1);
}

/* Возвращаем отступы элементам при ховере */
#floating-hub-global:hover .dock-nav-item:not(.active) {
    padding: 0.5rem 1.25rem !important;
}

/* Меню Профиля (z-index fix) */
#floating-hub-global .profile-dropdown-content {
    z-index: 120 !important;
    position: absolute;
    top: calc(100% + 1rem); /* Четкий отступ ниже капсулы */
    right: 0;
    pointer-events: auto; /* чтобы можно было кликать внутри */
}
/* Разрешаем клики внутри выпадающего меню даже если оно лежит на защитном паддинге */
.profile-dropdown.is-open {
    pointer-events: auto;
}

/* Стилизация активной кнопки (Комната / Главная) */
#floating-hub-global .dock-nav-item.active {
    background: var(--color-primary) !important;
    color: #F8FAFC !important; /* Насыщенный светлый текст вместо белого на белом */
    box-shadow: 0 4px 12px rgba(79,70,229,0.3), inset 0 -2px 0 rgba(0,0,0,0.2) !important;
    margin: 0 0.2rem;
}
html[data-theme="dark"] #floating-hub-global .dock-nav-item.active {
    color: #ffffff !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4), inset 0 -2px 0 rgba(0,0,0,0.3) !important;
}
html[data-theme="light"] #floating-hub-global .dock-nav-item.active {
    /* Если в светлой теме индиго фон режет глаза, делаем насыщенный темный индиго */
    background: #312E81 !important; 
    color: #EEF2FF !important;
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

html = re.sub(old_css, new_css, html, flags=re.DOTALL)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
