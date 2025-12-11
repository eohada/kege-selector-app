import sys
with open(r'D:\VSCode\kege_selector_app\app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
lines[1083] = "    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)\n"
with open(r'D:\VSCode\kege_selector_app\app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Исправлено')
