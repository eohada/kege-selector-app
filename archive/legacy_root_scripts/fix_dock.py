import os

template_content = """{% from '_ui_icon.html' import ui_icon %}
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

{# ── Плавающий навбар-островок (Изолированные острова) ── #}
<div class="fixed top-6 left-0 right-0 z-[100] hidden md:flex items-center justify-center pointer-events-none">

    <!-- ЛЕВЫЙ ОСТРОВ (Навигация) -->
    <nav class="group pointer-events-auto absolute top-0 left-1/2 -translate-x-1/2 flex items-center h-14 bg-gradient-to-br from-indigo-500 to-purple-600 dark:from-gray-800 dark:to-gray-900 rounded-full px-2 shadow-[0_12px_24px_-8px_rgba(99,102,241,0.5),inset_0_3px_6px_rgba(255,255,255,0.4),inset_0_-3px_6px_rgba(0,0,0,0.15)] dark:shadow-[0_12px_24px_-8px_rgba(0,0,0,0.8),inset_0_2px_4px_rgba(255,255,255,0.05),inset_0_-3px_6px_rgba(0,0,0,0.4)] transition-all duration-300 ease-[cubic-bezier(0.25,1,0.5,1)]">
        
        <div class="flex items-center gap-2 px-1 relative">
            {# ── Brand ── #}
            <a {{ spa_main_nav_attrs(url_for('main.index'), '', false) }} class="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/25 border border-white/20 shadow-[inset_0_1px_2px_rgba(255,255,255,0.2)] transition-colors duration-200">
                <i class="ph-fill ph-ghost text-white text-xl"></i>
            </a>

            {# ── Active Pin (Visible by default) ── #}
            {% if current_user and current_user.is_authenticated %}
                {% if current_user.is_student() and current_student %}
                <a {{ spa_main_nav_attrs(url_for('students.student_profile', student_id=current_student.student_id), 'student_profile') }} class="flex-shrink-0 px-4 h-10 flex items-center justify-center rounded-full bg-white text-indigo-700 font-bold text-sm shadow-[0_4px_10px_rgba(0,0,0,0.1),inset_0_-2px_4px_rgba(0,0,0,0.05),inset_0_2px_4px_rgba(255,255,255,0.6)] dark:bg-gray-700 dark:text-gray-100 transition-transform hover:scale-[1.02] active:scale-95 whitespace-nowrap">
                    Комната
                </a>
                {% else %}
                <a {{ spa_main_nav_attrs(url_for('main.dashboard'), 'dashboard') }} class="flex-shrink-0 px-4 h-10 flex items-center justify-center rounded-full bg-white text-indigo-700 font-bold text-sm shadow-[0_4px_10px_rgba(0,0,0,0.1),inset_0_-2px_4px_rgba(0,0,0,0.05),inset_0_2px_4px_rgba(255,255,255,0.6)] dark:bg-gray-700 dark:text-gray-100 transition-transform hover:scale-[1.02] active:scale-95 whitespace-nowrap">
                    Дашборд
                </a>
                {% endif %}
            {% endif %}

            {# ── Hidden Nav Section ── #}
            <div class="flex items-center max-w-0 opacity-0 overflow-hidden group-hover:max-w-[800px] group-hover:opacity-100 group-hover:overflow-visible transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)]">
                <div class="flex items-center gap-1 w-max px-2">
                    {% if current_user and current_user.is_authenticated %}
                        
                        {# === PARENT role === #}
                        {% if current_user.is_parent() %}
                            <a {{ spa_main_nav_attrs(url_for('parents.parent_dashboard'), 'parent_dashboard') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'parent_dashboard' %}bg-white/20 font-bold{% endif %}">
                                <i class="ph-bold ph-baby text-lg"></i> Мои дети
                            </a>
                            {% set sub_allow_lessons = (subscription_access.allow_lessons if subscription_access and subscription_access.allow_lessons is not none else True) %}
                            {% if sub_allow_lessons and (has_permission(current_user, 'schedule.view') or has_permission(current_user, 'tools.schedule')) %}
                                <a {{ spa_main_nav_attrs(url_for('schedule.schedule'), 'schedule') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'schedule' %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-calendar-blank text-lg"></i> Расписание
                                </a>
                            {% endif %}
                            <a {{ spa_main_nav_attrs(url_for('main.faq'), 'faq') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'faq' %}bg-white/20 font-bold{% endif %}">
                                <i class="ph-bold ph-question text-lg"></i> FAQ
                            </a>
                        
                        {# === STUDENT role === #}
                        {% elif current_user.is_student() %}
                            {% set sub_allow_lessons = (subscription_access.allow_lessons if subscription_access and subscription_access.allow_lessons is not none else True) %}
                            {% set sub_allow_trainer = (subscription_access.allow_trainer if subscription_access and subscription_access.allow_trainer is not none else True) %}
                            {% if current_student %}
                                <a {{ spa_main_nav_attrs(url_for('main.student_dashboard'), 'student_dashboard') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page in ['student_dashboard','dashboard'] %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-house text-lg"></i> Главная
                                </a>
                                {% if sub_allow_lessons %}
                                    <a {{ spa_main_nav_attrs(url_for('assignments.submissions_list'), 'assignments') }} id="demo-nav-assignments" class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'assignments' %}bg-white/20 font-bold{% endif %}">
                                        <i class="ph-bold ph-tray text-lg"></i> Задания
                                    </a>
                                {% endif %}
                                {% if sub_allow_trainer and has_permission(current_user, 'trainer.use') %}
                                    <a {{ spa_main_nav_attrs(url_for('trainer.trainer_v2'), 'trainer') }} id="demo-nav-trainer" class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'trainer' %}bg-white/20 font-bold{% endif %}">
                                        <i class="ph-bold ph-game-controller text-lg"></i> Тренажёр
                                    </a>
                                {% endif %}
                                {% if has_permission(current_user, 'theory.view') %}
                                    <a {{ spa_main_nav_attrs(url_for('theory.theory_index'), 'theory') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'theory' %}bg-white/20 font-bold{% endif %}">
                                        <i class="ph-bold ph-book-open text-lg"></i> Теория
                                    </a>
                                {% endif %}
                                <a {{ spa_main_nav_attrs(url_for('students.student_analytics', student_id=current_student.student_id), 'student_analytics') }} id="demo-nav-stats" class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'student_analytics' %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-chart-line-up text-lg"></i> Статистика
                                </a>
                            {% endif %}
                        
                        {# === TEACHER / ADMIN / CREATOR role === #}
                        {% else %}
                            <a {{ spa_main_nav_attrs(url_for('schedule.schedule'), 'schedule') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'schedule' %}bg-white/20 font-bold{% endif %}">
                                <i class="ph-bold ph-calendar-blank text-lg"></i> Расписание
                            </a>
                            {% if has_permission(current_user, 'assignment.grade') %}
                                <a {{ spa_main_nav_attrs(url_for('lessons.review_queue'), 'review_queue') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'review_queue' %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-tray text-lg"></i> Проверка
                                </a>
                            {% endif %}
                            {% if has_permission(current_user, 'trainer.use') %}
                                <a {{ spa_main_nav_attrs(url_for('trainer.trainer_v2'), 'trainer') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'trainer' %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-game-controller text-lg"></i> Тренажёр
                                </a>
                            {% endif %}
                            {% if current_user.is_creator() or current_user.is_chief_tester() or current_user.is_tester() %}
                                <a {{ spa_main_nav_attrs(url_for('chief_tester.dashboard'), 'chief_tester_dashboard') }} class="flex items-center gap-1.5 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page == 'chief_tester_dashboard' %}bg-white/20 font-bold{% endif %}">
                                    <i class="ph-bold ph-radar text-lg"></i> QA Отдел
                                </a>
                            {% endif %}
                            
                            {# ── Инструменты (Mega-menu) ── #}
                            <div class="relative group/mega inline-block">
                                <button class="flex items-center gap-1 px-3 py-2 rounded-full text-white/90 hover:text-white hover:bg-white/10 active:scale-95 transition-all text-sm font-medium whitespace-nowrap {% if active_page in mega_active_pages %}bg-white/20 font-bold{% endif %}" type="button">
                                    <i class="ph-bold ph-squares-four text-lg"></i> Ещё <i class="ph ph-caret-down text-xs"></i>
                                </button>
                                <div class="absolute top-[calc(100%+12px)] left-1/2 -translate-x-1/2 bg-[var(--color-bg-surface)] backdrop-blur-xl border border-[var(--color-stroke)] shadow-2xl rounded-2xl w-max min-w-[300px] p-4 opacity-0 pointer-events-none group-hover/mega:opacity-100 group-hover/mega:pointer-events-auto transition-all z-[110]">
                                    <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-[var(--color-text-secondary)] text-left">
                                        <div>
                                            <div class="font-bold text-xs uppercase mb-2 opacity-50">Учёба</div>
                                            {% if has_permission(current_user, 'assignment.view') %}
                                            <a {{ spa_main_nav_attrs(url_for('assignments.assignments_list'), 'assignments') }} class="dock-mega-link"><i class="ph-bold ph-file-text"></i> Работы</a>
                                            {% endif %}
                                            {% if has_permission(current_user, 'theory.manage') %}
                                            <a {{ spa_main_nav_attrs(url_for('theory.manage_list'), 'theory_manage') }} class="dock-mega-link"><i class="ph-bold ph-book-open"></i> Теория</a>
                                            {% endif %}
                                            <a {{ spa_main_nav_attrs(url_for('reminders.reminders_list'), 'reminders') }} class="dock-mega-link"><i class="ph-bold ph-bell"></i> Напоминания</a>

                                            <div class="font-bold text-xs uppercase mt-3 mb-2 opacity-50">Создание</div>
                                            <a {{ spa_main_nav_attrs(url_for('task_generator.task_generator'), 'generator') }} class="dock-mega-link"><i class="ph-bold ph-magic-wand"></i> Генератор</a>
                                            {% if has_permission(current_user, 'task.manage') %}
                                            <a {{ spa_main_nav_attrs(url_for('templates.templates_list'), 'templates') }} class="dock-mega-link"><i class="ph-bold ph-file-dashed"></i> Шаблоны</a>
                                            {% endif %}
                                            {% if has_permission(current_user, 'lesson.edit') %}
                                            <a {{ spa_main_nav_attrs(url_for('library.materials_library'), 'library') }} class="dock-mega-link"><i class="ph-bold ph-books"></i> Библиотека</a>
                                            {% endif %}
                                        </div>
                                        <div>
                                            <div class="font-bold text-xs uppercase mb-2 opacity-50">Управление</div>
                                            {% if has_permission(current_user, 'groups.view') %}
                                            <a {{ spa_main_nav_attrs(url_for('groups.groups_list'), 'groups') }} class="dock-mega-link"><i class="ph-bold ph-users"></i> Группы</a>
                                            {% endif %}
                                            {% if has_permission(current_user, 'billing.manage') %}
                                            <a {{ spa_main_nav_attrs(url_for('billing.billing_plans'), 'billing') }} class="dock-mega-link"><i class="ph-bold ph-credit-card"></i> Тарифы</a>
                                            {% endif %}
                                            {% if current_user.is_admin() or current_user.is_creator() %}
                                            <div class="font-bold text-xs uppercase mt-3 mb-2 opacity-50">Админ</div>
                                            <a {{ spa_main_nav_attrs(url_for('admin.admin_panel'), 'admin_panel') }} class="dock-mega-link"><i class="ph-bold ph-gear"></i> Панель</a>
                                            {% endif %}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {% endif %}
                    {% endif %}
                </div>
            </div>

            {# ── Search & Avatar (Always visible on right) ── #}
            <div class="flex items-center gap-1.5 pl-2 border-l border-white/20 py-1">
                {% if config.get('IS_SANDBOX') %}
                <span class="px-2 py-1 bg-amber-500/90 text-white text-[10px] font-bold rounded-full uppercase tracking-wider shadow">SANDBOX</span>
                {% endif %}

                <button class="w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors" onclick="document.getElementById('cmdPalette').classList.add('active')" title="Поиск (Ctrl+K)" type="button">
                    <i class="ph-bold ph-magnifying-glass text-lg"></i>
                </button>

                {% if current_user and current_user.is_authenticated %}
                <div class="relative" data-profile-dropdown>
                    <button class="w-10 h-10 rounded-full border border-white/30 hover:border-white focus:outline-none overflow-hidden transition-colors flex items-center justify-center p-0 m-0" data-profile-trigger type="button" aria-haspopup="menu" aria-expanded="false">
                        {% if current_user.is_demo_user %}
                        <img src="{{ url_for('static', filename='images/demo_user_avatar.png') }}" alt="Avatar" class="w-full h-full object-cover">
                        {% elif current_user.avatar_url %}
                        <img src="{{ current_user.avatar_url }}" alt="Avatar" class="w-full h-full object-cover">
                        {% else %}
                        <div class="w-full h-full bg-black/40 flex items-center justify-center text-white font-bold text-sm">{{ current_user.username[0].upper() }}</div>
                        {% endif %}
                    </button>
                    <!-- Old Profile Dropdown structure with original classes for styles! -->
                    <div class="profile-dropdown-content absolute top-[calc(100%+8px)] right-0 z-[120]" data-profile-menu>
                        <a {{ spa_main_nav_attrs(url_for('auth.user_profile'), 'profile') }} class="profile-item">
                            <i class="ph-bold ph-user text-base text-muted"></i>
                            <span>Профиль</span>
                        </a>
                        {% if release_notes %}
                        <button type="button" class="profile-item w-full text-left bg-transparent border-none cursor-pointer" onclick="openReleaseNotesModal()" style="display: flex; align-items: center; gap: 0.5rem; width: 100%;">
                            <i class="ph-bold ph-sparkles text-base text-muted" style="color: var(--boo-cyan, #06b6d4);"></i>
                            <span>Что нового</span>
                        </button>
                        {% endif %}
                        <a {{ spa_main_nav_attrs(url_for('notifications.notifications_list'), 'notifications') }} class="profile-item">
                            <i class="ph-bold ph-bell text-base text-muted"></i>
                            <span>Уведомления</span>
                        </a>
                        {% if current_user.is_admin() or current_user.is_creator() %}
                        <a {{ spa_main_nav_attrs(url_for('admin.admin_panel'), 'admin_panel') }} class="profile-item">
                            <i class="ph-bold ph-gear text-base text-muted"></i>
                            <span>Админ панель</span>
                        </a>
                        {% endif %}
                        <div class="profile-dropdown-divider" aria-hidden="true"></div>
                        <a href="{{ url_for('auth.logout') }}" class="profile-item" style="color:#EF4444;">
                            <i class="ph-bold ph-sign-out text-base"></i>
                            <span>Выход</span>
                        </a>
                    </div>
                </div>
                {% endif %}
            </div>
        </div>
    </nav>

    <!-- ПРАВЫЙ ОСТРОВ (Theme Switcher) -->
    <button onclick="toggleThemeQuick()" title="Сменить тему" aria-label="Сменить тему оформления" class="pointer-events-auto absolute top-0 left-[calc(50%+300px)] w-14 h-14 flex items-center justify-center bg-[var(--color-bg-surface)] backdrop-blur-xl border border-[var(--color-stroke)] rounded-full cursor-pointer shadow-[0_8px_16px_-4px_rgba(0,0,0,0.1),inset_0_2px_4px_rgba(255,255,255,0.8),inset_0_-3px_6px_rgba(0,0,0,0.05)] dark:shadow-[0_12px_24px_-8px_rgba(0,0,0,0.8),inset_0_2px_4px_rgba(255,255,255,0.05),inset_0_-3px_6px_rgba(0,0,0,0.4)] hover:scale-105 active:scale-95 transition-all duration-200 group">
        <i class="ph-bold ph-sun text-2xl text-amber-500 drop-shadow-sm group-active:rotate-[15deg] transition-transform duration-300 block dark:hidden"></i>
        <i class="ph-bold ph-moon text-2xl text-indigo-300 drop-shadow-sm group-active:-rotate-[15deg] transition-transform duration-300 hidden dark:block"></i>
    </button>
</div>

<!-- Scripts and Styles -->
<script>
(function() {
    if (window.__profileDropdownInitialized) return;
    window.__profileDropdownInitialized = true;
    
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('[data-profile-trigger]');
        if (trigger) {
            e.preventDefault();
            e.stopPropagation();
            var dropdown = trigger.closest('[data-profile-dropdown]');
            if (dropdown) {
                var isOpen = dropdown.classList.contains('is-open');
                document.querySelectorAll('[data-profile-dropdown].is-open').forEach(function(d) {
                    d.classList.remove('is-open');
                    d.querySelector('[data-profile-trigger]')?.setAttribute('aria-expanded', 'false');
                });
                if (!isOpen) {
                    dropdown.classList.add('is-open');
                    trigger.setAttribute('aria-expanded', 'true');
                }
            }
            return;
        }
        var openDropdowns = document.querySelectorAll('[data-profile-dropdown].is-open');
        openDropdowns.forEach(function(dropdown) {
            if (!dropdown.contains(e.target)) {
                dropdown.classList.remove('is-open');
                dropdown.querySelector('[data-profile-trigger]')?.setAttribute('aria-expanded', 'false');
            }
        });
    });
})();

if (typeof window.toggleThemeQuick === 'undefined') {
    window.toggleThemeQuick = function() {
        const root = document.documentElement;
        const isDark = root.getAttribute('data-theme') === 'dark' || root.classList.contains('dark');
        const newTheme = isDark ? 'light' : 'dark';
        root.setAttribute('data-theme', newTheme);
        if (newTheme === 'dark') root.classList.add('dark');
        else root.classList.remove('dark');
        try { localStorage.setItem('theme', newTheme); } catch(e) {}
        window.dispatchEvent(new CustomEvent('theme-changed', { detail: newTheme }));
    };
}
</script>
<style>
    .profile-dropdown.is-open .profile-dropdown-content {
        opacity: 1 !important;
        transform: translateY(0) !important;
        pointer-events: auto !important;
        display: block; /* guarantee visibility */
    }
</style>
"""

with open("templates/_dock_nav.html", "w", encoding="utf-8") as f:
    f.write(template_content)
