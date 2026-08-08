import re

# 1. FIX THE WIDGET DISPLAY IN BASE.HTML (Role check)
with open('templates/base.html', 'r') as f:
    base_html = f.read()

# Clean up any bad widget includes
base_html = re.sub(r'\{% if current_user\.is_authenticated.*?%\}[\s\n]*\{% include "qa/_floating_widget\.html".*?%\}[\s\n]*\{% endif %\}', '', base_html, flags=re.DOTALL | re.MULTILINE)
base_html = re.sub(r'\{% include .qa/_floating_widget.html. ignore missing %\}', '', base_html)

# Add it safely right before </body>, without methods that might not exist
correct_include = """
    {% if current_user.is_authenticated %}
        {% if current_user.role in ['admin', 'tester', 'creator', 'chief_tester', 'chief_admin'] or session.get('original_user_id') %}
            {% include "qa/_floating_widget.html" ignore missing %}
        {% endif %}
    {% endif %}
</body>
"""
base_html = base_html.replace('</body>', correct_include)

with open('templates/base.html', 'w') as f:
    f.write(base_html)


# 2. BEAUTIFUL, RESPONISVE DASHBOARD FOR ADMIN QA
dashboard_html = """{% extends "base.html" %}
{% block title %}QA Control Room{% endblock %}

{% block content %}
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" style="padding-top: 6rem; padding-bottom: 4rem;">

    <!-- Header Section -->
    <div style="display: flex; flex-direction: column; gap: 1rem; margin-bottom: 2rem;">
        <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1rem;">
            <div>
                <h1 style="font-size: 2rem; font-weight: 800; color: var(--color-text-primary); margin: 0; display: flex; align-items: center; gap: 0.75rem;">
                    <i class="ph-bold ph-shield-check" style="color: #6366f1;"></i> QA Control Room
                </h1>
                <p style="font-size: 0.9rem; color: var(--color-text-muted); margin-top: 0.25rem;">Мониторинг, отчеты и анализ качества</p>
            </div>
            <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                <a href="{{ url_for('qa_admin.manage_tests') }}" style="background: var(--color-bg-surface-alt); color: var(--color-text-primary); border: 1px solid var(--color-stroke); padding: 0.6rem 1.25rem; border-radius: 10px; font-weight: 700; font-size: 0.875rem; display: flex; align-items: center; gap: 0.5rem; transition: all 0.2s;" onmouseover="this.style.borderColor='#6366f1';" onmouseout="this.style.borderColor='var(--color-stroke)';">
                    <i class="ph-bold ph-list-checks"></i> Тест-Кейсы
                </a>
                <a href="/qa" target="_blank" style="background: #6366f1; color: white; padding: 0.6rem 1.25rem; border-radius: 10px; font-weight: 700; font-size: 0.875rem; display: flex; align-items: center; gap: 0.5rem; transition: all 0.2s;" onmouseover="this.style.background='#4f46e5';" onmouseout="this.style.background='#6366f1';">
                    <i class="ph-bold ph-bug"></i> Панель тестера
                </a>
            </div>
        </div>
    </div>

    <!-- Stats Matrix -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
        <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <div>
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); text-transform: uppercase;">Всего отчетов</div>
                <div style="font-size: 2rem; font-weight: 800; color: var(--color-text-primary); margin-top: 0.25rem;">{{ all_reports_count }}</div>
            </div>
            <i class="ph-fill ph-files" style="font-size: 2.5rem; color: rgba(99, 102, 241, 0.2);"></i>
        </div>
        
        <div style="background: var(--color-bg-surface); border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 12px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(244, 63, 94, 0.1);">
            <div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #f43f5e; text-transform: uppercase;">Открытые баги</div>
                <div style="font-size: 2rem; font-weight: 800; color: #f43f5e; margin-top: 0.25rem;">{{ active_reports }}</div>
            </div>
            <i class="ph-fill ph-warning-circle" style="font-size: 2.5rem; color: rgba(244, 63, 94, 0.2);"></i>
        </div>

        <div style="background: var(--color-bg-surface); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 12px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(168, 85, 247, 0.1);">
            <div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #a855f7; text-transform: uppercase;">Ждут ретеста</div>
                <div style="font-size: 2rem; font-weight: 800; color: #a855f7; margin-top: 0.25rem;">{{ retest_reports }}</div>
            </div>
            <i class="ph-fill ph-arrows-clockwise" style="font-size: 2.5rem; color: rgba(168, 85, 247, 0.2);"></i>
        </div>

        <div style="background: var(--color-bg-surface); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.1);">
            <div>
                <div style="font-size: 0.75rem; font-weight: 700; color: #10b981; text-transform: uppercase;">Тест-кейсы</div>
                <div style="font-size: 2rem; font-weight: 800; color: #10b981; margin-top: 0.25rem;">{{ total_tests }}</div>
            </div>
            <i class="ph-fill ph-check-square-offset" style="font-size: 2.5rem; color: rgba(16, 185, 129, 0.2);"></i>
        </div>
    </div>

    <!-- Main Layout Grid -->
    <div style="display: flex; flex-direction: column; gap: 2rem;">
        
        <!-- Filter Panel -->
        <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.25rem;">
            <form method="GET" action="{{ url_for('qa_admin.dashboard') }}" style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;">
                <div style="flex: 1; min-width: 150px;">
                    <label style="display: block; font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); margin-bottom: 0.5rem; text-transform: uppercase;">Статус</label>
                    <select name="status" style="width: 100%; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); color: var(--color-text-primary); border-radius: 8px; padding: 0.6rem; font-size: 0.875rem; outline: none;">
                        <option value="">Все статусы</option>
                        <option value="pending" {% if request.args.get('status') == 'pending' %}selected{% endif %}>Ожидает</option>
                        <option value="in_progress" {% if request.args.get('status') == 'in_progress' %}selected{% endif %}>В работе</option>
                        <option value="retest" {% if request.args.get('status') == 'retest' %}selected{% endif %}>На ретесте</option>
                        <option value="resolved" {% if request.args.get('status') == 'resolved' %}selected{% endif %}>Решён</option>
                        <option value="rejected" {% if request.args.get('status') == 'rejected' %}selected{% endif %}>Отклонён</option>
                    </select>
                </div>
                <div style="flex: 1; min-width: 150px;">
                    <label style="display: block; font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); margin-bottom: 0.5rem; text-transform: uppercase;">Секция</label>
                    <select name="area" style="width: 100%; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); color: var(--color-text-primary); border-radius: 8px; padding: 0.6rem; font-size: 0.875rem; outline: none;">
                        <option value="">Все секции</option>
                        {% set areas_dict = all_areas if all_areas is mapping else {} %}
                        {% for key, name in areas_dict.items() %}
                            <option value="{{ key }}" {% if request.args.get('area') == key %}selected{% endif %}>{{ name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div style="flex: 1; min-width: 150px;">
                    <label style="display: block; font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); margin-bottom: 0.5rem; text-transform: uppercase;">Репортер</label>
                    <select name="reporter_id" style="width: 100%; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); color: var(--color-text-primary); border-radius: 8px; padding: 0.6rem; font-size: 0.875rem; outline: none;">
                        <option value="">Любой</option>
                        {% for t in testers %}
                            <option value="{{ t.id }}" {% if request.args.get('reporter_id') == t.id|string %}selected{% endif %}>{{ t.username }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div style="flex-shrink: 0;">
                    <button type="submit" style="background: var(--color-text-primary); color: var(--color-bg-base); border: none; padding: 0.6rem 1.25rem; border-radius: 8px; font-weight: 700; font-size: 0.875rem; cursor: pointer;">
                        Применить
                    </button>
                    {% if request.args %}
                    <a href="{{ url_for('qa_admin.dashboard') }}" style="margin-left: 0.5rem; font-size: 0.875rem; color: var(--color-text-muted); text-decoration: none; font-weight: 600;">Сбросить</a>
                    {% endif %}
                </div>
            </form>
        </div>

        <!-- Layout for Table and Sidebar -->
        <div style="display: flex; flex-direction: row; flex-wrap: wrap; gap: 2rem;">
            
            <!-- Table Container (Main Content) -->
            <div style="flex: 3; min-width: 300px; background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; text-align: left;">
                        <thead>
                            <tr style="background: var(--color-bg-surface-alt); border-bottom: 1px solid var(--color-stroke);">
                                <th style="padding: 1rem 1.5rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase;">ID / Репорт</th>
                                <th style="padding: 1rem 1.5rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase;">Статус & Приоритет</th>
                                <th style="padding: 1rem 1.5rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase;">Репортер</th>
                                <th style="padding: 1rem 1.5rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase; text-align: right;">Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for report in reports %}
                            <tr style="border-bottom: 1px solid var(--color-stroke); transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='transparent'">
                                <td style="padding: 1rem 1.5rem;">
                                    <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                                        <a href="{{ url_for('qa_admin.view_report', report_id=report.id) }}" style="color: var(--color-text-primary); text-decoration: none; font-weight: 700; font-size: 0.95rem;">
                                            <span style="color: #6366f1; font-family: monospace; font-size: 0.85rem; margin-right: 0.25rem;">#{{ report.id }}</span> 
                                            {% if report.test_case %}{{ report.test_case.title }}{% else %}Спонтанный баг{% endif %}
                                        </a>
                                        <span style="font-size: 0.75rem; color: var(--color-text-muted);"><i class="ph-bold ph-folder"></i> {{ report.area }} • {{ report.created_at.strftime('%d.%m.%Y %H:%M') }}</span>
                                    </div>
                                </td>
                                <td style="padding: 1rem 1.5rem;">
                                    <div style="display: flex; flex-direction: column; gap: 0.5rem; align-items: flex-start;">
                                        {% set st = report.status %}
                                        {% if st == 'pending' %}<span style="background: rgba(245,158,11,0.1); color: #f59e0b; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 800;">Ожидает</span>
                                        {% elif st == 'in_progress' %}<span style="background: rgba(59,130,246,0.1); color: #3b82f6; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 800;">В работе</span>
                                        {% elif st == 'retest' %}<span style="background: rgba(168,85,247,0.1); color: #a855f7; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 800;">На ретесте</span>
                                        {% elif st == 'resolved' %}<span style="background: rgba(16,185,129,0.1); color: #10b981; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 800;">Решён</span>
                                        {% elif st == 'rejected' %}<span style="background: rgba(244,63,94,0.1); color: #f43f5e; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.75rem; font-weight: 800;">Отклонён</span>
                                        {% endif %}
                                        
                                        {% if report.verdict == 'critical' %}
                                            <span style="font-size: 0.75rem; font-weight: 800; color: #f43f5e; display: flex; align-items: center; gap: 0.2rem;"><i class="ph-fill ph-fire"></i> Крит</span>
                                        {% elif report.verdict == 'minor' %}
                                            <span style="font-size: 0.75rem; font-weight: 800; color: #fbbf24; display: flex; align-items: center; gap: 0.2rem;"><i class="ph-fill ph-warning"></i> Минор</span>
                                        {% endif %}
                                    </div>
                                </td>
                                <td style="padding: 1rem 1.5rem;">
                                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                                        <div style="width: 28px; height: 28px; border-radius: 50%; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted);">
                                            {{ report.reporter.username[:2] | upper if report.reporter else '?' }}
                                        </div>
                                        <span style="font-size: 0.85rem; font-weight: 600; color: var(--color-text-primary);">{{ report.reporter.username if report.reporter else 'Неизвестно' }}</span>
                                    </div>
                                </td>
                                <td style="padding: 1rem 1.5rem; text-align: right;">
                                    <a href="{{ url_for('qa_admin.view_report', report_id=report.id) }}" style="display: inline-flex; width: 36px; height: 36px; align-items: center; justify-content: center; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); color: var(--color-text-primary); border-radius: 8px; transition: all 0.2s;" onmouseover="this.style.background='#6366f1'; this.style.borderColor='#6366f1'; this.style.color='#fff';" onmouseout="this.style.background='var(--color-bg-surface-alt)'; this.style.borderColor='var(--color-stroke)'; this.style.color='var(--color-text-primary)';">
                                        <i class="ph-bold ph-arrow-right"></i>
                                    </a>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="4" style="padding: 4rem 2rem; text-align: center;">
                                    <i class="ph-thin ph-ghost" style="font-size: 3rem; color: var(--color-text-muted); margin-bottom: 1rem;"></i>
                                    <div style="font-size: 1rem; font-weight: 700; color: var(--color-text-primary);">Багов не найдено</div>
                                    <div style="font-size: 0.85rem; color: var(--color-text-muted);">По текущим фильтрам нет результатов.</div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Sidebar (Leaderboard) -->
            <div style="flex: 1; min-width: 250px;">
                <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.5rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                    <h3 style="font-size: 1.1rem; font-weight: 800; color: var(--color-text-primary); margin: 0 0 1.25rem 0; display: flex; align-items: center; gap: 0.5rem;">
                        <i class="ph-fill ph-trophy" style="color: #fbbf24; font-size: 1.25rem;"></i> Топ Багхантеров
                    </h3>
                    
                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                        {% for rank in leaderboard %}
                        <div style="padding: 0.75rem; border-radius: 10px; background: var(--color-bg-surface-alt); border: 1px solid var(--color-stroke); display: flex; align-items: center; gap: 0.75rem;">
                            <div style="width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 800; 
                                {% if loop.index == 1 %}background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #fff;
                                {% elif loop.index == 2 %}background: linear-gradient(135deg, #94a3b8, #64748b); color: #fff;
                                {% elif loop.index == 3 %}background: linear-gradient(135deg, #b45309, #78350f); color: #fff;
                                {% else %}background: var(--color-bg-base); color: var(--color-text-muted); border: 1px solid var(--color-stroke);
                                {% endif %}">
                                {{ loop.index }}
                            </div>
                            <div style="flex: 1; min-width: 0;">
                                <div style="font-size: 0.85rem; font-weight: 700; color: var(--color-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{{ rank.user.username }}</div>
                                <div style="display: flex; gap: 0.5rem; font-size: 0.7rem; font-weight: 600; color: var(--color-text-muted); margin-top: 0.2rem;">
                                    <span style="color: #10b981;">{{ rank.total }} всего</span>
                                    {% if rank.critical_count > 0 %}<span style="color: #f43f5e;"><i class="ph-fill ph-fire"></i> {{ rank.critical_count }} крит.</span>{% endif %}
                                </div>
                            </div>
                        </div>
                        {% else %}
                        <div style="text-align: center; color: var(--color-text-muted); font-size: 0.85rem; padding: 1rem 0;">Нет данных для рейтинга</div>
                        {% endfor %}
                    </div>
                </div>
            </div>

        </div>
    </div>
</div>
{% endblock %}
"""

with open('templates/admin/qa/dashboard.html', 'w') as f:
    f.write(dashboard_html)


# 3. BEAUTIFUL TESTER WORKSPACE (Fixed 500 error removing bulk_pass and fixed styles)
index_html = """{% extends "base.html" %}
{% block title %}QA Workspace{% endblock %}

{% block content %}
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" style="padding-top: 6rem; padding-bottom: 4rem;">

    <!-- Header Section -->
    <div style="display: flex; flex-direction: column; gap: 1rem; margin-bottom: 2rem;">
        <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1rem;">
            <div>
                <h1 style="font-size: 2rem; font-weight: 800; color: var(--color-text-primary); margin: 0; display: flex; align-items: center; gap: 0.75rem;">
                    <i class="ph-bold ph-bug-beetle" style="color: #f43f5e;"></i> QA Workspace
                </h1>
                <p style="font-size: 0.9rem; color: var(--color-text-muted); margin-top: 0.25rem;">Выполнение тест-кейсов и поиск свободных багов</p>
            </div>
            <div style="display: flex; justify-content: flex-end; gap: 0.75rem; flex-wrap: wrap;">
                <a href="{{ url_for('qa_tester.history') }}" style="background: var(--color-bg-surface-alt); color: var(--color-text-primary); border: 1px solid var(--color-stroke); padding: 0.6rem 1.25rem; border-radius: 10px; font-weight: 700; font-size: 0.875rem; display: flex; align-items: center; gap: 0.5rem; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.05)';" onmouseout="this.style.background='var(--color-bg-surface-alt)';">
                    <i class="ph-bold ph-clock-counter-clockwise"></i> Моя история
                </a>
                <a href="{{ url_for('qa_tester.ad_hoc_bug') }}" style="background: #f43f5e; color: white; padding: 0.6rem 1.25rem; border-radius: 10px; font-weight: 700; font-size: 0.875rem; display: flex; align-items: center; gap: 0.5rem; transition: background 0.2s; box-shadow: 0 4px 10px rgba(244, 63, 94, 0.3);" onmouseover="this.style.background='#e11d48';" onmouseout="this.style.background='#f43f5e';">
                    <i class="ph-bold ph-plus-circle"></i> Спонтанный баг
                </a>
            </div>
        </div>
    </div>

    <!-- Quick Stats -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
        <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.5rem; display: flex; align-items: center; gap: 1rem;">
            <div style="width: 48px; height: 48px; border-radius: 12px; background: rgba(16, 185, 129, 0.1); color: #10b981; display: flex; align-items: center; justify-content: center; font-size: 1.5rem;">
                <i class="ph-fill ph-check-circle"></i>
            </div>
            <div>
                <div style="font-size: 1.5rem; font-weight: 800; color: var(--color-text-primary); line-height: 1;">{{ passed_test_ids|length }}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); text-transform: uppercase; margin-top: 0.25rem;">Пройдено</div>
            </div>
        </div>
        
        <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.5rem; display: flex; align-items: center; gap: 1rem;">
            <div style="width: 48px; height: 48px; border-radius: 12px; background: rgba(244, 63, 94, 0.1); color: #f43f5e; display: flex; align-items: center; justify-content: center; font-size: 1.5rem;">
                <i class="ph-fill ph-warning-circle"></i>
            </div>
            <div>
                <div style="font-size: 1.5rem; font-weight: 800; color: var(--color-text-primary); line-height: 1;">{{ bug_test_ids|length }}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); text-transform: uppercase; margin-top: 0.25rem;">С багами</div>
            </div>
        </div>

        <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; padding: 1.5rem; display: flex; align-items: center; gap: 1rem;">
            <div style="width: 48px; height: 48px; border-radius: 12px; background: rgba(168, 85, 247, 0.1); color: #a855f7; display: flex; align-items: center; justify-content: center; font-size: 1.5rem;">
                <i class="ph-fill ph-arrows-clockwise"></i>
            </div>
            <div>
                <div style="font-size: 1.5rem; font-weight: 800; color: var(--color-text-primary); line-height: 1;">{{ retest_test_ids|length }}</div>
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-text-muted); text-transform: uppercase; margin-top: 0.25rem;">На ретесте</div>
            </div>
        </div>
    </div>

    <!-- Active Test Cases List -->
    <div style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
        {% set current_area = namespace(val='') %}
        
        {% for test in tests %}
            {% if current_area.val != test.area %}
                {% set current_area.val = test.area %}
                <div style="background: var(--color-bg-surface-alt); padding: 0.75rem 1.5rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.05em; border-top: 1px solid var(--color-stroke); border-bottom: 1px solid var(--color-stroke); display: flex; align-items: center; gap: 0.5rem; margin-top: {% if loop.index > 1 %}-1px{% else %}0{% endif %};">
                    <i class="ph-bold ph-folder-open"></i> {{ test.area }}
                </div>
            {% endif %}

            <a href="{{ url_for('qa_tester.execute_test', test_id=test.id) }}" style="display: flex; justify-content: space-between; align-items: center; padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--color-stroke); text-decoration: none; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.02)';" onmouseout="this.style.background='transparent';">
                
                <div style="display: flex; gap: 1rem; align-items: center; flex: 1; min-width: 0;">
                    <div style="width: 36px; height: 36px; border-radius: 8px; background: var(--color-bg-base); border: 1px solid var(--color-stroke); display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 800; color: var(--color-text-muted); flex-shrink: 0;">
                        T{{ test.id }}
                    </div>
                    <div>
                        <div style="font-size: 0.95rem; font-weight: 700; color: var(--color-text-primary); margin-bottom: 0.25rem;">{{ test.title }}</div>
                        <div style="font-size: 0.75rem; color: var(--color-text-muted); display: flex; align-items: center; gap: 0.35rem;">
                            <span style="background: var(--color-bg-surface-alt); padding: 0.15rem 0.4rem; border-radius: 4px; font-weight: 600;"><i class="ph-bold ph-user-focus"></i> {{ test.role }}</span>
                        </div>
                    </div>
                </div>

                <div style="flex-shrink: 0; margin-left: 1rem;">
                    {% if test.id in passed_test_ids %}
                        <span style="display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; font-weight: 800; color: #10b981; background: rgba(16,185,129,0.1); padding: 0.35rem 0.75rem; border-radius: 9999px;"><i class="ph-bold ph-check"></i> Успешно</span>
                    {% elif test.id in bug_test_ids %}
                        <span style="display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; font-weight: 800; color: #f43f5e; background: rgba(244,63,94,0.1); padding: 0.35rem 0.75rem; border-radius: 9999px;"><i class="ph-bold ph-bug"></i> С багом</span>
                    {% elif test.id in retest_test_ids %}
                        <span style="display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; font-weight: 800; color: #a855f7; background: rgba(168,85,247,0.1); padding: 0.35rem 0.75rem; border-radius: 9999px;"><i class="ph-bold ph-arrows-clockwise"></i> Ретест</span>
                    {% else %}
                        <span style="display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.75rem; font-weight: 800; color: var(--color-text-muted); background: var(--color-bg-surface-alt); padding: 0.35rem 0.75rem; border-radius: 9999px; border: 1px solid var(--color-stroke);"><i class="ph-bold ph-dots-three"></i> Не тронут</span>
                    {% endif %}
                </div>
            </a>
        {% else %}
            <div style="padding: 4rem 2rem; text-align: center;">
                <i class="ph-thin ph-files" style="font-size: 3rem; color: var(--color-text-muted); margin-bottom: 1rem;"></i>
                <h3 style="font-size: 1.125rem; font-weight: 800; color: var(--color-text-primary); margin-bottom: 0.5rem;">Нет активных тест-кейсов</h3>
                <p style="font-size: 0.875rem; color: var(--color-text-muted);">В базе пока ничего нет. Можете начать со спонтанного баг-репорта.</p>
            </div>
        {% endfor %}
    </div>

</div>
{% endblock %}
"""

with open('templates/qa_tester/index.html', 'w') as f:
    f.write(index_html)

