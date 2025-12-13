"""
Скрипт для проверки всех url_for в шаблонах
Находит потенциально неправильные url_for без префиксов blueprints
"""
import os
import re
from pathlib import Path

# Список endpoints, которые должны иметь префикс blueprint
BLUEPRINT_ENDPOINTS = {
    'login': 'auth.login',
    'logout': 'auth.logout',
    'user_profile': 'auth.user_profile',
    'dashboard': 'main.dashboard',
    'index': 'main.index',
    'home': 'main.index',
    'update_plans': 'main.update_plans',
    'admin_panel': 'admin.admin_panel',
    'admin_audit': 'admin.admin_audit',
    'admin_testers': 'admin.admin_testers',
    'admin_testers_edit': 'admin.admin_testers_edit',
    'admin_testers_delete': 'admin.admin_testers_delete',
    'admin_testers_clear_all': 'admin.admin_testers_clear_all',
    'admin_audit_export': 'admin.admin_audit_export',
    'student_new': 'students.student_new',
    'student_profile': 'students.student_profile',
    'student_edit': 'students.student_edit',
    'student_delete': 'students.student_delete',
    'student_archive': 'students.student_archive',
    'lesson_edit': 'lessons.lesson_edit',
    'lesson_view': 'lessons.lesson_view',
    'lesson_delete': 'lessons.lesson_delete',
    'kege_generator': 'kege_generator.kege_generator',
    'schedule': 'schedule.schedule',
    'templates_list': 'templates_manager.templates_list',
    'template_new': 'templates_manager.template_new',
    'template_view': 'templates_manager.template_view',
    'template_edit': 'templates_manager.template_edit',
    'template_delete': 'templates_manager.template_delete',
    'template_apply': 'templates_manager.template_apply',
}

def check_template_file(file_path):
    """Проверяет один шаблон на наличие неправильных url_for"""
    issues = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            
            # Ищем все url_for
            pattern = r"url_for\(['\"]([^'\"]+)['\"]"
            for line_num, line in enumerate(lines, 1):
                matches = re.finditer(pattern, line)
                for match in matches:
                    endpoint = match.group(1)
                    # Проверяем, должен ли endpoint иметь префикс blueprint
                    if endpoint in BLUEPRINT_ENDPOINTS:
                        expected = BLUEPRINT_ENDPOINTS[endpoint]
                        if endpoint != expected:
                            issues.append({
                                'file': file_path,
                                'line': line_num,
                                'endpoint': endpoint,
                                'expected': expected,
                                'line_content': line.strip()
                            })
    except Exception as e:
        print(f"Ошибка при чтении {file_path}: {e}")
    
    return issues

def main():
    """Проверяет все шаблоны"""
    templates_dir = Path('templates')
    if not templates_dir.exists():
        print("Папка templates не найдена!")
        return
    
    all_issues = []
    for template_file in templates_dir.rglob('*.html'):
        issues = check_template_file(template_file)
        all_issues.extend(issues)
    
    if all_issues:
        print(f"Найдено {len(all_issues)} потенциальных проблем:\n")
        for issue in all_issues:
            print(f"{issue['file']}:{issue['line']}")
            print(f"  Найдено: url_for('{issue['endpoint']}')")
            print(f"  Ожидается: url_for('{issue['expected']}')")
            print(f"  Строка: {issue['line_content']}")
            print()
    else:
        print("OK: Все url_for выглядят правильно!")

if __name__ == '__main__':
    main()

