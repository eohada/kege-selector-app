"""
Скрипт для исправления url_for в шаблонах после рефакторинга на blueprints
"""
import os
import re
from pathlib import Path

# Маппинг endpoints на blueprints
ENDPOINT_MAPPING = {
    # auth
    'user_profile': 'auth.user_profile',
    
    # main
    'index': 'main.index',
    'dashboard': 'main.dashboard',
    'home': 'main.index',
    'update_plans': 'main.update_plans',
    
    # students
    'student_profile': 'students.student_profile',
    'student_edit': 'students.student_edit',
    'student_delete': 'students.student_delete',
    'student_archive': 'students.student_archive',
    'student_start_lesson': 'students.student_start_lesson',
    'student_statistics': 'students.student_statistics',
    'lesson_new': 'students.lesson_new',
    'students_list': 'students.students_list',
    'student_new': 'students.student_new',
    
    # lessons
    'lesson_complete': 'lessons.lesson_complete',
    'lesson_start': 'lessons.lesson_start',
    'lesson_delete': 'lessons.lesson_delete',
    'lesson_edit': 'lessons.lesson_edit',
    'lesson_view': 'lessons.lesson_view',
    'lesson_homework_view': 'lessons.lesson_homework_view',
    'lesson_classwork_view': 'lessons.lesson_classwork_view',
    'lesson_exam_view': 'lessons.lesson_exam_view',
    'lesson_homework_save': 'lessons.lesson_homework_save',
    'lesson_homework_auto_check': 'lessons.lesson_homework_auto_check',
    'lesson_classwork_auto_check': 'lessons.lesson_classwork_auto_check',
    'lesson_exam_auto_check': 'lessons.lesson_exam_auto_check',
    'lesson_homework_delete_task': 'lessons.lesson_homework_delete_task',
    'lesson_homework_not_assigned': 'lessons.lesson_homework_not_assigned',
    'lesson_homework_export_md': 'lessons.lesson_homework_export_md',
    'lesson_classwork_export_md': 'lessons.lesson_classwork_export_md',
    'lesson_exam_export_md': 'lessons.lesson_exam_export_md',
    
    # kege_generator
    'kege_generator': 'kege_generator.kege_generator',
    'show_accepted': 'kege_generator.show_accepted',
    'show_skipped': 'kege_generator.show_skipped',
    'results': 'kege_generator.results',
    'action': 'kege_generator.action',
    
    # schedule
    'schedule': 'schedule.schedule',
    'create_lesson': 'schedule.create_lesson',
    
    # templates_manager
    'templates_list': 'templates_manager.templates_list',
    'template_view': 'templates_manager.template_view',
    'template_new': 'templates_manager.template_new',
    'template_edit': 'templates_manager.template_edit',
    'template_delete': 'templates_manager.template_delete',
    'template_apply': 'templates_manager.template_apply',
    
    # admin
    'admin': 'admin.admin',
    'admin_panel': 'admin.admin_panel',
    'admin_audit': 'admin.admin_audit',
    'admin_testers': 'admin.admin_testers',
    'admin_testers_edit': 'admin.admin_testers_edit',
    'admin_testers_delete': 'admin.admin_testers_delete',
    'admin_testers_clear_all': 'admin.admin_testers_clear_all',
    'admin_audit_export': 'admin.admin_audit_export',
    
    # main (дополнительные)
    'update_plans': 'main.update_plans',
}

# Специальные случаи (update_plans и другие)
SPECIAL_CASES = {
    'update_plans': 'main.update_plans',  # если есть такой endpoint
}

def fix_url_for_in_file(file_path):
    """Исправляет url_for в одном файле"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Паттерн для поиска url_for('endpoint' или "endpoint")
    pattern = r"url_for\(['\"]([^'\"]+)['\"]"
    
    def replace_endpoint(match):
        endpoint = match.group(1)
        
        # Если endpoint уже с префиксом blueprint, пропускаем
        if '.' in endpoint:
            return match.group(0)
        
        # Проверяем маппинг
        if endpoint in ENDPOINT_MAPPING:
            new_endpoint = ENDPOINT_MAPPING[endpoint]
            return f"url_for('{new_endpoint}'"
        elif endpoint in SPECIAL_CASES:
            new_endpoint = SPECIAL_CASES[endpoint]
            return f"url_for('{new_endpoint}'"
        else:
            # Если endpoint не найден в маппинге, оставляем как есть
            # (может быть static, или другой специальный endpoint)
            return match.group(0)
    
    content = re.sub(pattern, replace_endpoint, content)
    
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    """Основная функция"""
    base_dir = Path(__file__).parent.parent
    templates_dir = base_dir / 'templates'
    
    if not templates_dir.exists():
        print(f"Директория {templates_dir} не найдена!")
        return
    
    fixed_count = 0
    total_files = 0
    
    for template_file in templates_dir.rglob('*.html'):
        total_files += 1
        if fix_url_for_in_file(template_file):
            fixed_count += 1
            print(f"Исправлен: {template_file.relative_to(base_dir)}")
    
    print(f"\nВсего файлов: {total_files}")
    print(f"Исправлено: {fixed_count}")

if __name__ == '__main__':
    main()

