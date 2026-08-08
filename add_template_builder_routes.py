with open('app/main/routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

builder_routes_code = """

@main_bp.route('/teacher/templates/new', methods=['GET', 'POST'], endpoint='create_template_view')
@login_required
def create_template_view():
    \"\"\"Маршрут открытия конструктора для создания нового шаблона заданий.\"\"\"
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    return redirect(url_for('templates.template_new'))


@main_bp.route('/teacher/templates/<int:template_id>/edit', methods=['GET', 'POST'], endpoint='edit_template_view')
@login_required
def edit_template_view(template_id):
    \"\"\"Маршрут открытия конструктора для редактирования существующего шаблона.\"\"\"
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    template = TaskTemplate.query.get_or_404(template_id)
    if active_role not in ['admin', 'creator'] and template.created_by != current_user.id:
        flash("Чужой шаблон нельзя редактировать", "warning")
        return redirect(url_for('main.teacher_templates_library'))

    return redirect(url_for('templates.template_edit', template_id=template_id))
"""

if 'def create_template_view():' not in content:
    content += "\n" + builder_routes_code
    with open('app/main/routes.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added create_template_view and edit_template_view to app/main/routes.py!")
else:
    print("Routes already present.")
