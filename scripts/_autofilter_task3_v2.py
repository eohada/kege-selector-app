"""
Auto-filter task 3 v2 - content-aware filtering.

Derived rules from user's manual review:

ACCEPTED formulation (new EGE format):
  - Contains "Движение товаров" (product movement table)
  - Contains "Тип операции" + "Поступление" or "Продажа"
  - Standard product database: Кондитерские изделия, Молочные продукты,
    Хозтовары, Текстиль, Продукты

DELETED formulations (wrong format/topic):
  - "Автосервис" / "автозапчаст" / "Движение запчастей" (auto parts)
  - "Аудиотека" / "альбом" / "композиц" (music database)
  - "Гостиница" / "бронирован" (hotel database)
  - "волшебн" / "королевств" (fairy tale wording)
  - Old format with "схема базы данных" instead of table headers
  - "Торговля" table instead of "Движение товаров"
  - Completely unrelated tasks (logic expressions, etc.)
"""
import json
import re
from datetime import datetime

TASK_NUM = 3

all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))
deleted_log = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
accepted_log = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))

# First: remove auto-accepted task 3 entries (keep only manually accepted ones)
manual_accepted_ids = set()
for a in accepted_log:
    if a['task_number'] == TASK_NUM and 'accepted_at' in a:
        ts = a['accepted_at']
        # Manual ones were accepted before 2026-03-05T07:00 (user session)
        # Auto ones were accepted by the script later
        if ts < '2026-03-05T07:30:00':
            manual_accepted_ids.add(a['task_id'])

print(f"Manual accepted (keeping): {len(manual_accepted_ids)}")

# Remove all task 3 from accepted_log, will re-add
accepted_log = [a for a in accepted_log if a['task_number'] != TASK_NUM]

# Re-add manual ones
all_task3_data = {t['task_id']: t for t in all_tasks if t['task_number'] == TASK_NUM}
for tid in manual_accepted_ids:
    if tid in all_task3_data:
        t = all_task3_data[tid]
        accepted_log.append({
            'task_id': t['task_id'],
            'task_number': t['task_number'],
            'site_task_id': t.get('site_task_id'),
            'content_html': t.get('content_html', ''),
            'answer': t.get('answer'),
            'accepted_at': datetime.now().isoformat(),
        })

deleted_ids = set(d['task_id'] for d in deleted_log if d['task_number'] == TASK_NUM)
already_reviewed = manual_accepted_ids | deleted_ids

task_n = [t for t in all_tasks if t['task_number'] == TASK_NUM]
unreviewed = [t for t in task_n if t['task_id'] not in already_reviewed]

print(f"Task {TASK_NUM}: in_file={len(task_n)}, manual_accepted={len(manual_accepted_ids)}, "
      f"already_deleted={len(deleted_ids)}, to_review={len(unreviewed)}")


def clean(html):
    t = re.sub(r'<[^>]+>', ' ', html or '')
    t = re.sub(r'&nbsp;', ' ', t)
    t = re.sub(r'&\w+;', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


BAD_TOPICS = [
    r'автосервис',
    r'автозапчаст',
    r'движение\s+запчастей',
    r'аудиотек',
    r'альбом\w*.*композиц',
    r'гостиниц',
    r'бронирован',
    r'волшебн',
    r'королевств',
    r'ёлочн\w+\s+шар',
    r'схема\s+базы\s+данных',
    r'на\s+рисунке\s+приведена\s+схема',
]


def should_keep(task):
    html = task.get('content_html', '') or ''
    answer = (task.get('answer', '') or '').strip()
    text = clean(html)
    reasons = []

    if len(html) < 100:
        reasons.append("empty_content")
        return False, reasons

    if not answer:
        reasons.append("no_answer")

    if 'def ' in answer or 'import ' in answer or 'from ' in answer:
        reasons.append("answer_has_code")

    if not re.match(r'^\d+$', answer) and answer:
        reasons.append(f"answer_not_integer({answer[:30]})")

    # Content-based: must have the standard formulation
    has_movement = bool(re.search(r'движение\s+товаров', text, re.IGNORECASE))
    has_operation_type = bool(re.search(r'тип\s+операции', text, re.IGNORECASE))

    if not has_movement:
        reasons.append("no_movement_товаров")

    if not has_operation_type:
        reasons.append("no_тип_операции")

    # Check for bad topics
    for pattern in BAD_TOPICS:
        if re.search(pattern, text, re.IGNORECASE):
            reasons.append(f"bad_topic({pattern})")

    return len(reasons) == 0, reasons


to_keep = []
to_delete = []

for task in unreviewed:
    keep, reasons = should_keep(task)
    if keep:
        to_keep.append(task)
    else:
        to_delete.append((task, reasons))

print(f"\nAUTO-FILTER RESULTS:")
print(f"  Will KEEP (and mark accepted): {len(to_keep)}")
print(f"  Will DELETE:                   {len(to_delete)}")
print()

if to_delete:
    print("--- TASKS TO DELETE ---")
    for task, reasons in to_delete:
        ans = (task.get('answer', '') or '')[:30]
        sid = str(task.get('site_task_id') or '?')
        text = clean(task.get('content_html', ''))[:80]
        print(f"  id={task['task_id']:5d} site={sid:>8s} ans='{ans}'")
        print(f"    reasons={reasons}")
        print(f"    text: {text}")
        print()

print(f"--- TASKS TO KEEP (first 5) ---")
for task in to_keep[:5]:
    ans = (task.get('answer', '') or '')[:30]
    text = clean(task.get('content_html', ''))[:100]
    print(f"  id={task['task_id']:5d} ans='{ans}' text: {text}")
if len(to_keep) > 5:
    print(f"  ... and {len(to_keep) - 5} more")

confirm = input("\nApply? (y/n): ").strip().lower()
if confirm == 'y':
    delete_ids = set(t['task_id'] for t, _ in to_delete)

    for task, reasons in to_delete:
        deleted_log.append({
            'task_id': task['task_id'],
            'task_number': task['task_number'],
            'site_task_id': task.get('site_task_id'),
            'content_html': task.get('content_html', ''),
            'answer': task.get('answer'),
            'deleted_at': datetime.now().isoformat(),
            'auto_reasons': reasons,
        })

    for task in to_keep:
        accepted_log.append({
            'task_id': task['task_id'],
            'task_number': task['task_number'],
            'site_task_id': task.get('site_task_id'),
            'content_html': task.get('content_html', ''),
            'answer': task.get('answer'),
            'accepted_at': datetime.now().isoformat(),
        })

    new_all = [t for t in all_tasks if not (t['task_number'] == TASK_NUM and t['task_id'] in delete_ids)]

    with open('tasks_export.json', 'w', encoding='utf-8') as f:
        json.dump(new_all, f, ensure_ascii=False, indent=2)
    with open('tasks_deleted_log.json', 'w', encoding='utf-8') as f:
        json.dump(deleted_log, f, ensure_ascii=False, indent=2)
    with open('tasks_accepted_log.json', 'w', encoding='utf-8') as f:
        json.dump(accepted_log, f, ensure_ascii=False, indent=2)

    remaining = sum(1 for t in new_all if t['task_number'] == TASK_NUM)
    total_acc = sum(1 for a in accepted_log if a['task_number'] == TASK_NUM)
    print(f"\nDone!")
    print(f"  Deleted: {len(delete_ids)}")
    print(f"  Newly accepted: {len(to_keep)}")
    print(f"  Total accepted (task {TASK_NUM}): {total_acc}")
    print(f"  Remaining in file (task {TASK_NUM}): {remaining}")
else:
    print("Cancelled.")
