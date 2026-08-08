import os

with open("templates/_dock_nav.html", "w", encoding="utf-8") as f:
    f.write("""{% from '_ui_icon.html' import ui_icon %}
{% from '_spa_main_nav_attrs.html' import spa_main_nav_attrs %}

{# ── Компактная мобильная шапка (десктопный dock скрыт) ── #}
{% if current_user and current_user.is_authenticated %}
<div class="mobile-topbar md:hidden">
    <a {{ spa_main_nav_attrs(url_for('main.index'), '', false) }} class="mobile-topbar-brand">
        <i class="ph-fill ph-ghost"></i>
        <span>BooStudy</span>
    </a>
    <div class="mobile-topbar-actions">
        <a {{ spa_main_nav_attrs(url_for('notifications.notifications_list'), 'notifications') }} class="mobile-topbar-btn" aria-label="Уведомления">
            <i class="ph-bold ph-bell-ringing"></i>
        </a>
        <a {{ spa_main_nav_attrs(url_for('auth.user_profile'), 'profile') }} class="mobile-topbar-btn" aria-label="Профиль">
            <i class="ph-bold ph-user-circle"></i>
        </a>
    </div>
</div>
{% endif %}


<!-- ==============================================
     ПЛАВАЮЩАЯ НАВИГАЦИЯ (Claymorphism UI)
=============================================== -->
    
    <!-- ЛЕВЫЙ ОСТРОВ: Глобальный Навбар (Fluid Morph) -->
    <!-- УБРАН общий flex-родитель! Остров висит независимо в корне DOM -->
    <div id="floating-hub-global" class="fixed top-4 left-1/2 -translate-x-1/2 z-[100] pointer-events-auto group relative flex items-center justify-center origin-center hidden md:flex">
        
        <!-- УБРАНА подушка 120vw. Теперь только локальная страховка шириной в сам контейнер -->
        <div class="absolute top-full left-0 w-full h-10 z-10 hidden group-hover:block"></div>
        
        <!-- Капсула, которая расширяется при наведении ИЗ ЦЕНТРА -->
        <header class="hub-container bg-[var(--color-bg-surface)]/80 backdrop-blur-xl border border-[var(--color-stroke)] rounded-full h-14 px-3 flex items-center justify-center shadow-[0_8px_32px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/90 dark:border-white/10 dark:shadow-[0_8px_32px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] overflow-hidden">

        {# ── Brand ── #}
        <a {{ spa_main_nav_attrs(url_for('main.index'), '', false) }} class="dock-brand pl-0">
            <div class="dock-brand-icon">
                <i class="ph-fill ph-ghost text-xl"></i>
            </div>
            <span class="dock-brand-text">BooStudy</span>
        </a>

        {# ── Nav Pills (Desktop) ── #}
        {% if current_user and current_user.is_authenticated %}
        <nav class="dock-nav">
            
            {# === PARENT role === #}
            {% if current_user.is_parent() %}
            <a {{ spa_main_nav_attrs(url_for('parents.parent_dashboard'), 'parent_dashboard') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'parent_dashboard' %}active{% endif %}">
                <i class="ph-bold ph-baby text-lg"></i> Мои дети
            </a>
            {% set sub_allow_lessons = (subscription_access.allow_lessons if subscription_access and subscription_access.allow_lessons is not none else True) %}
            {% if sub_allow_lessons and (has_permission(current_user, 'schedule.view') or has_permission(current_user, 'tools.schedule')) %}
            <a {{ spa_main_nav_attrs(url_for('schedule.schedule'), 'schedule') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'schedule' %}active{% endif %}">
                <i class="ph-bold ph-calendar-blank text-lg"></i> Расписание
            </a>
            {% endif %}
            <a {{ spa_main_nav_attrs(url_for('main.faq'), 'faq') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'faq' %}active{% endif %}">
                <i class="ph-bold ph-question text-lg"></i> FAQ
            </a>

            {# === STUDENT role === #}
            {% elif current_user.is_student() %}
            {% set sub_allow_lessons = (subscription_access.allow_lessons if subscription_access and subscription_access.allow_lessons is not none else True) %}
            {% set sub_allow_trainer = (subscription_access.allow_trainer if subscription_access and subscription_access.allow_trainer is not none else True) %}
            {% if current_student %}
            <a {{ spa_main_nav_attrs(url_for('main.student_dashboard'), 'student_dashboard') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page in ['student_dashboard','dashboard'] %}active{% endif %}">
                <i class="ph-bold ph-house text-lg"></i> Главная
            </a>
            {% if sub_allow_lessons %}
            <a {{ spa_main_nav_attrs(url_for('students.student_profile', student_id=current_student.student_id), 'student_profile') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'student_profile' %}active{% endif %}">
                <i class="ph-bold ph-house text-lg"></i> Комната
            </a>
            <a id="demo-nav-assignments" {{ spa_main_nav_attrs(url_for('assignments.submissions_list'), 'assignments') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'assignments' %}active{% endif %}">
                <i class="ph-bold ph-tray text-lg"></i> Задания
            </a>
            {% endif %}
            {% if sub_allow_trainer and has_permission(current_user, 'trainer.use') %}
            <a id="demo-nav-trainer" {{ spa_main_nav_attrs(url_for('trainer.trainer_v2'), 'trainer') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'trainer' %}active{% endif %}">
                <i class="ph-bold ph-game-controller text-lg"></i> Тренажёр
            </a>
            {% endif %}
            {% if has_permission(current_user, 'theory.view') %}
            <a {{ spa_main_nav_attrs(url_for('theory.theory_index'), 'theory') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'theory' %}active{% endif %}">
                <i class="ph-bold ph-book-open text-lg"></i> Теория
            </a>
            {% endif %}
            <a id="demo-nav-stats" {{ spa_main_nav_attrs(url_for('students.student_analytics', student_id=current_student.student_id) if current_student else '#', 'student_analytics') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'student_analytics' %}active{% endif %}">
                <i class="ph-bold ph-chart-line-up text-lg"></i> Статистика
            </a>
            {% endif %}

            {# === TEACHER / ADMIN / CREATOR role === #}
            {% else %}
            <a {{ spa_main_nav_attrs(url_for('main.dashboard'), 'dashboard') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'dashboard' %}active{% endif %}">
                <i class="ph-bold ph-users-three text-lg"></i> Ученики
            </a>
            <a {{ spa_main_nav_attrs(url_for('schedule.schedule'), 'schedule') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'schedule' %}active{% endif %}">
                <i class="ph-bold ph-calendar-blank text-lg"></i> Расписание
            </a>
            {% if has_permission(current_user, 'assignment.grade') %}
            <a {{ spa_main_nav_attrs(url_for('lessons.review_queue'), 'review_queue') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'review_queue' %}active{% endif %}" style="position:relative;">
                <i class="ph-bold ph-tray text-lg"></i> Проверка
            </a>
            {% endif %}
            {% if has_permission(current_user, 'trainer.use') %}
            <a {{ spa_main_nav_attrs(url_for('trainer.trainer_v2'), 'trainer') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'trainer' %}active{% endif %}">
                <i class="ph-bold ph-game-controller text-lg"></i> Тренажёр
            </a>
            {% endif %}
            {% if current_user.is_creator() or current_user.is_chief_tester() or current_user.is_tester() %}
            <a {{ spa_main_nav_attrs(url_for('chief_tester.dashboard'), 'chief_tester_dashboard') }} class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page == 'chief_tester_dashboard' %}active{% endif %}">
                <i class="ph-bold ph-radar text-lg"></i> QA Отдел
            </a>
            {% endif %}

            {# ── Mega-menu: Инструменты ── #}
            <div class="dock-mega">
                <button class="dock-nav-item clay-interactive px-4 py-2 rounded-full font-black text-sm transition-all duration-300 ease-out text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary hover:bg-[var(--color-bg-inset)] {% if active_page in mega_active_pages %}active{% endif %}" data-mega-nav-trigger type="button">
                    <i class="ph-bold ph-squares-four text-lg"></i> Ещё
                    <i class="ph ph-caret-down text-xs" style="margin-left:2px;"></i>
                </button>
                <div class="dock-mega-panel">
                    <div class="grid grid-cols-2 gap-x-6 gap-y-1">
                        <div>
                            <div class="dock-mega-group-title">Учёба</div>
                            {% if has_permission(current_user, 'assignment.view') %}
                            <a {{ spa_main_nav_attrs(url_for('assignments.assignments_list'), 'assignments') }} class="dock-mega-link">
                                <i class="ph-bold ph-file-text text-base text-muted"></i> Работы
                            </a>
                            {% endif %}
                            {% if has_permission(current_user, 'theory.manage') %}
                            <a {{ spa_main_nav_attrs(url_for('theory.manage_list'), 'theory_manage') }} class="dock-mega-link">
                                <i class="ph-bold ph-book-open text-base text-muted"></i> Теория
                            </a>
                            {% endif %}
                            <a {{ spa_main_nav_attrs(url_for('reminders.reminders_list'), 'reminders') }} class="dock-mega-link">
                                <i class="ph-bold ph-bell text-base text-muted"></i> Напоминания
                            </a>

                            <div class="dock-mega-group-title mt-3">Создание</div>
                            <a {{ spa_main_nav_attrs(url_for('task_generator.task_generator'), 'generator') }} class="dock-mega-link">
                                <i class="ph-bold ph-magic-wand text-base text-muted"></i> Генератор
                            </a>
                            {% if has_permission(current_user, 'task.manage') %}
                            <a {{ spa_main_nav_attrs(url_for('templates.templates_list'), 'templates') }} class="dock-mega-link">
                                <i class="ph-bold ph-file-dashed text-base text-muted"></i> Шаблоны
                            </a>
                            {% endif %}
                            {% if has_permission(current_user, 'lesson.edit') %}
                            <a {{ spa_main_nav_attrs(url_for('library.materials_library'), 'library') }} class="dock-mega-link">
                                <i class="ph-bold ph-books text-base text-muted"></i> Библиотека
                            </a>
                            {% endif %}
                        </div>
                        <div>
                            <div class="dock-mega-group-title">Управление</div>
                            {% if has_permission(current_user, 'groups.view') %}
                            <a {{ spa_main_nav_attrs(url_for('groups.groups_list'), 'groups') }} class="dock-mega-link">
                                <i class="ph-bold ph-users text-base text-muted"></i> Группы
                            </a>
                            {% endif %}
                            {% if has_permission(current_user, 'billing.manage') %}
                            <a {{ spa_main_nav_attrs(url_for('billing.billing_plans'), 'billing') }} class="dock-mega-link">
                                <i class="ph-bold ph-credit-card text-base text-muted"></i> Тарифы
                            </a>
                            {% endif %}
                            {% if current_user.is_admin() or current_user.is_creator() %}
                            <div class="dock-mega-group-title mt-3">Админ</div>
                            <a {{ spa_main_nav_attrs(url_for('admin.admin_panel'), 'admin_panel') }} class="dock-mega-link">
                                <i class="ph-bold ph-gear text-base text-muted"></i> Панель
                            </a>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            {% endif %}
        </nav>
        {% endif %}

        {# ── Right side: Search + Profiling / Logout ── #}
        <div class="dock-actions-hover hidden group-hover:flex items-center gap-2 ml-2">
            
            {% if config and config.get('IS_SANDBOX') %}
            <span class="px-2 py-1 bg-amber-500/90 text-white text-[10px] font-bold rounded-full uppercase tracking-wider shadow mr-1">SANDBOX</span>
            {% endif %}

            <button class="dock-icon-btn clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-[var(--color-bg-surface-alt)] border border-[var(--color-stroke)] hover:-translate-y-1 transition-all" onclick="document.getElementById('cmdPalette').classList.add('active')" title="Поиск (Ctrl+K)" type="button">
                <i class="ph-bold ph-magnifying-glass text-xl"></i>
            </button>
            
            {% if current_user and current_user.is_authenticated %}
            <a href="{{ url_for('auth.logout') }}" class="clay-interactive w-10 h-10 rounded-full flex items-center justify-center bg-danger/10 text-danger border border-danger/20 shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] hover:-translate-y-1 hover:bg-danger/20 transition-all ml-1" title="Выйти">
                <i class="ph-bold ph-sign-out text-lg"></i>
            </a>
            {% endif %}
        </div>
        </header>
    </div> <!-- /Левый остров -->


<!-- ПРАВЫЙ ОСТРОВ: Инлайн-Свитчер Тем БЕЗ Ховера (Hard Positioned) -->
<!-- Свитчер полностью вынесен из общего контейнера и безопасно привязан на left-[calc(50%+380px)] -->
<div id="theme-switcher-island" class="fixed top-4 left-[calc(50%+380px)] z-[100] pointer-events-auto flex items-center hidden md:flex">
    <button class="clay-interactive w-14 h-14 rounded-full flex items-center justify-center bg-[var(--color-bg-surface)]/90 backdrop-blur-xl border border-[var(--color-stroke)] shadow-[0_8px_24px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8)] dark:bg-[var(--color-bg-surface)]/90 dark:border-white/10 dark:shadow-[0_8px_24px_rgba(0,0,0,0.4),inset_0_2px_4px_rgba(255,255,255,0.05)] hover:scale-105 active:scale-95 transition-all text-[var(--color-text-secondary)] dark:text-zinc-300 hover:text-primary cursor-pointer pointer-events-auto group" onclick="toggleThemeQuick()" title="Сменить тему">
        <i class="ph-bold ph-sun text-2xl group-active:rotate-[15deg] transition-transform duration-300 block dark:hidden text-[#1E1B4B]"></i>
        <i class="ph-bold ph-moon text-2xl group-active:-rotate-[15deg] transition-transform duration-300 hidden dark:block text-[#A5B4FC]"></i>
    </button>
</div>

<!-- ==============================================
     СКРИПТЫ И СТИЛИ 
=============================================== -->
<script>
    if (typeof window.toggleThemeQuick === 'undefined') {
        window.toggleThemeQuick = function() {
            const root = document.documentElement;
            // Читаем атрибут напрямую (надежнее, чем класс)
            const isDark = root.getAttribute('data-theme') === 'dark' || root.classList.contains('dark');
            const newTheme = isDark ? 'light' : 'dark';

            // Обновляем HTML data-атрибут (используется DaisyUI или кастомным CSS)
            root.setAttribute('data-theme', newTheme);
            
            // Меняем Tailwind class (dark | empty)
            if (newTheme === 'dark') {
                root.classList.add('dark');
            } else {
                root.classList.remove('dark');
            }

            // Сохраняем стейт безопасно
            try {
                localStorage.setItem('theme', newTheme);
            } catch (e) {
                console.warn("Storage API block");
            }
            
            // Broadcast Event для Alpine.js или других слушателей (если есть на клиенте)
            window.dispatchEvent(new CustomEvent('theme-changed', { detail: newTheme }));
        };
    }
</script>

<style>
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
}

/* Раскрытое состояние (Hover Morph) */
#floating-hub-global:hover .hub-container {
    padding: 0 1.5rem;
    gap: 1rem;
}

/* Принудительно делаем ссылки кликабельными (активными) при ховере */
#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-icon-btn,
#floating-hub-global:hover a {
    pointer-events: auto !important;
}

#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-mega,
#floating-hub-global:hover .dock-actions-hover {
    display: flex;
    opacity: 1;
    width: auto;
    transform: scale(1);
    transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Возвращаем отступы элементам при ховере */
#floating-hub-global:hover .dock-nav-item:not(.active) {
    padding: 0.5rem 1.25rem !important;
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
    background: linear-gradient(145deg, #6366f1, #4f46e5) !important;
    color: #ffffff !important;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.2), inset 0 -2px 4px rgba(255, 255, 255, 0.4), 0 4px 12px rgba(79, 70, 229, 0.3) !important;
    border: 1px solid rgba(0,0,0,0.1) !important;
}

.dock-nav {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    display: flex;
    align-items: center;
    gap: 0.25rem;
}
</style>""")
