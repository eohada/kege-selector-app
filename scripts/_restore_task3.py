"""
Restore task 3 entries that were wrongly auto-deleted.
Rule: if content has "Движение товаров" -> it's valid, restore it.
Also accept all valid remaining tasks.
"""
import json
import re
from datetime import datetime

TASK_NUM = 3

all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))
deleted_log = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
accepted_log = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))

accepted_ids = set(a['task_id'] for a in accepted_log if a['task_number'] == TASK_NUM)


def clean(html):
    t = re.sub(r'<[^>]+>', ' ', html or '')
    t = re.sub(r'&nbsp;', ' ', t)
    t = re.sub(r'&\w+;', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def is_valid_task3(task):
    """Check if this task matches the accepted EGE #3 format."""
    html = task.get('content_html', '') or ''
    text = clean(html)
    answer = (task.get('answer', '') or '').strip()

    if len(html) < 100:
        return False, "empty"

    if not answer:
        return False, "no_answer"

    if not re.match(r'^\d+$', answer):
        return False, f"answer_not_int({answer[:20]})"

    if 'def ' in answer or 'import ' in answer:
        return False, "answer_has_code"

    has_movement = bool(re.search(r'движение\s+товаров', text, re.IGNORECASE))
    has_operation = bool(re.search(r'тип\s+операции', text, re.IGNORECASE))
    has_postavki = bool(re.search(r'поставк\w+\s+товаров', text, re.IGNORECASE))
    has_prodazha = bool(re.search(r'поступлени|продаж', text, re.IGNORECASE))

    # Primary: has "Движение товаров" (the standard table name)
    if has_movement:
        return True, "has_movement"

    # Secondary: postavki товаров + prodazha patterns (valid variant)
    if has_postavki and has_prodazha and has_operation:
        return True, "has_postavki_pattern"

    return False, "no_valid_formulation"


# Find wrongly deleted tasks to restore
auto_deleted_3 = [d for d in deleted_log
                  if d['task_number'] == TASK_NUM
                  and d.get('auto_reasons')
                  and d.get('content_html')]

to_restore = []
to_stay_deleted = []

for d in auto_deleted_3:
    valid, reason = is_valid_task3(d)
    if valid:
        to_restore.append(d)
    else:
        to_stay_deleted.append((d, reason))

print(f"Auto-deleted task 3 entries: {len(auto_deleted_3)}")
print(f"To RESTORE (wrongly deleted): {len(to_restore)}")
print(f"Correctly deleted: {len(to_stay_deleted)}")
print()

if to_restore:
    print("--- RESTORING ---")
    for t in to_restore[:10]:
        text = clean(t.get('content_html', ''))[:100]
        print(f"  id={t['task_id']:5d} ans={t.get('answer','?')} text: {text}")
    if len(to_restore) > 10:
        print(f"  ... and {len(to_restore) - 10} more")

if to_stay_deleted:
    print(f"\n--- CORRECTLY DELETED ({len(to_stay_deleted)}) ---")
    for t, reason in to_stay_deleted[:10]:
        text = clean(t.get('content_html', ''))[:100]
        print(f"  id={t['task_id']:5d} ans={t.get('answer','?')[:20]} reason={reason}")
        print(f"    {text}")
    if len(to_stay_deleted) > 10:
        print(f"  ... and {len(to_stay_deleted) - 10} more")

confirm = input("\nApply restore? (y/n): ").strip().lower()
if confirm == 'y':
    restore_ids = set(t['task_id'] for t in to_restore)

    # Add restored tasks back to all_tasks
    for d in to_restore:
        restored_task = {
            'task_id': d['task_id'],
            'task_number': d['task_number'],
            'task_group_id': d.get('task_group_id'),
            'site_task_id': d.get('site_task_id'),
            'source_url': d.get('source_url'),
            'content_html': d['content_html'],
            'answer': d.get('answer'),
            'attached_files': d.get('attached_files'),
            'difficulty_level': d.get('difficulty_level'),
            'hints': d.get('hints'),
            'source_prototype': d.get('source_prototype'),
            'course_id': d.get('course_id'),
        }
        all_tasks.append(restored_task)

        # Mark as accepted
        if d['task_id'] not in accepted_ids:
            accepted_log.append({
                'task_id': d['task_id'],
                'task_number': d['task_number'],
                'site_task_id': d.get('site_task_id'),
                'content_html': d.get('content_html', ''),
                'answer': d.get('answer'),
                'accepted_at': datetime.now().isoformat(),
            })

    # Remove restored from deleted_log
    deleted_log = [d for d in deleted_log if d['task_id'] not in restore_ids]

    # Also accept existing task 3 in file that aren't yet accepted
    existing_3 = [t for t in all_tasks if t['task_number'] == TASK_NUM]
    for t in existing_3:
        if t['task_id'] not in accepted_ids and t['task_id'] not in restore_ids:
            valid, _ = is_valid_task3(t)
            if valid:
                accepted_log.append({
                    'task_id': t['task_id'],
                    'task_number': t['task_number'],
                    'site_task_id': t.get('site_task_id'),
                    'content_html': t.get('content_html', ''),
                    'answer': t.get('answer'),
                    'accepted_at': datetime.now().isoformat(),
                })

    # Sort all_tasks by task_number, task_id
    all_tasks.sort(key=lambda t: (t['task_number'], t['task_id']))

    with open('tasks_export.json', 'w', encoding='utf-8') as f:
        json.dump(all_tasks, f, ensure_ascii=False, indent=2)
    with open('tasks_deleted_log.json', 'w', encoding='utf-8') as f:
        json.dump(deleted_log, f, ensure_ascii=False, indent=2)
    with open('tasks_accepted_log.json', 'w', encoding='utf-8') as f:
        json.dump(accepted_log, f, ensure_ascii=False, indent=2)

    final_count = sum(1 for t in all_tasks if t['task_number'] == TASK_NUM)
    final_accepted = sum(1 for a in accepted_log if a['task_number'] == TASK_NUM)
    print(f"\nDone!")
    print(f"  Restored: {len(restore_ids)}")
    print(f"  Task {TASK_NUM} in file: {final_count}")
    print(f"  Task {TASK_NUM} accepted: {final_accepted}")
else:
    print("Cancelled.")
