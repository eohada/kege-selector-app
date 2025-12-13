"""
Скрипт для проверки всех url_for в шаблонах и коде
Находит потенциально неправильные url_for без префиксов blueprints
"""
import os
import re
from pathlib import Path

# Все известные blueprints и их префиксы
BLUEPRINTS = {
    'auth': ['login', 'logout', 'user_profile', 'register'],
    'main': ['index', 'dashboard', 'home', 'update_plans', 'export_data', 'import_data', 'backup_db'],
    'students': ['student_profile', 'student_new', 'student_edit', 'student_delete', 'student_archive', 'student_start_lesson', 'student_statistics', 'lesson_new', 'students_list'],
    'lessons': ['lesson_complete', 'lesson_start', 'lesson_delete', 'lesson_edit', 'lesson_view', 'lesson_homework_view', 'lesson_classwork_view', 'lesson_exam_view', 'lesson_homework_save', 'lesson_homework_auto_check', 'lesson_classwork_auto_check', 'lesson_exam_auto_check', 'lesson_homework_delete_task', 'lesson_homework_not_assigned', 'lesson_homework_export_md', 'lesson_classwork_export_md', 'lesson_exam_export_md'],
    'admin': ['admin_panel', 'admin_audit', 'admin_testers', 'admin_testers_edit', 'admin_testers_delete', 'admin_testers_clear_all', 'admin_audit_export', 'diagnostics'],
    'kege_generator': ['kege_generator'],
    'api': ['api_templates', 'api_student_create', 'api_audit_log'],
    'schedule': ['schedule', 'schedule_create_lesson'],
    'templates': ['templates_list', 'template_new', 'template_view', 'template_edit', 'template_delete', 'template_apply']
}

# Endpoints, которые не требуют префикса
NO_PREFIX_NEEDED = ['static']

def check_url_for_in_content(content, file_path):
    """Проверяет url_for в содержимом файла"""
    issues = []
    # Паттерн для поиска url_for('endpoint' или url_for("endpoint"
    pattern = r"url_for\(['\"]([^'\"]+)['\"]"
    
    matches = re.finditer(pattern, content)
    for match in matches:
        endpoint = match.group(1)
        
        # Пропускаем static и другие специальные endpoints
        if endpoint in NO_PREFIX_NEEDED:
            continue
        
        # Проверяем, есть ли префикс blueprint
        if '.' not in endpoint:
            # Это может быть проблема, но нужно проверить, есть ли такой endpoint в blueprints
            found_in_blueprint = False
            for blueprint, endpoints in BLUEPRINTS.items():
                if endpoint in endpoints:
                    issues.append({
                        'file': str(file_path),
                        'line': content[:match.start()].count('\n') + 1,
                        'endpoint': endpoint,
                        'suggestion': f"{blueprint}.{endpoint}",
                        'match': match.group(0)
                    })
                    found_in_blueprint = True
                    break
            
            # Если endpoint не найден в blueprints, но не является static, это может быть проблема
            if not found_in_blueprint and endpoint not in ['index', 'home']:
                # Проверяем, может быть это старый endpoint без blueprint
                if endpoint in ['login', 'logout', 'dashboard', 'user_profile', 'admin_panel', 'student_profile', 'schedule', 'kege_generator']:
                    issues.append({
                        'file': str(file_path),
                        'line': content[:match.start()].count('\n') + 1,
                        'endpoint': endpoint,
                        'suggestion': 'CHECK_MANUALLY',
                        'match': match.group(0)
                    })
    
    return issues

def check_all_files():
    """Проверяет все файлы в проекте"""
    base_dir = Path(__file__).parent.parent
    templates_dir = base_dir / 'templates'
    app_dir = base_dir / 'app'
    
    all_issues = []
    
    # Проверяем шаблоны
    if templates_dir.exists():
        for template_file in templates_dir.rglob('*.html'):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                issues = check_url_for_in_content(content, template_file)
                all_issues.extend(issues)
            except Exception as e:
                print(f"Ошибка при чтении {template_file}: {e}")
    
    # Проверяем Python файлы в app/
    if app_dir.exists():
        for py_file in app_dir.rglob('*.py'):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Проверяем только url_for в строках (не в комментариях)
                issues = check_url_for_in_content(content, py_file)
                all_issues.extend(issues)
            except Exception as e:
                print(f"Ошибка при чтении {py_file}: {e}")
    
    return all_issues

if __name__ == '__main__':
    print("Проверка всех url_for в проекте...")
    issues = check_all_files()
    
    if issues:
        print(f"\nНайдено {len(issues)} потенциальных проблем:\n")
        for issue in issues:
            print(f"Файл: {issue['file']}")
            print(f"  Строка {issue['line']}: {issue['match']}")
            print(f"  Endpoint: {issue['endpoint']}")
            if issue['suggestion'] != 'CHECK_MANUALLY':
                print(f"  Предложение: {issue['suggestion']}")
            print()
    else:
        print("OK: Все url_for выглядят правильно!")

