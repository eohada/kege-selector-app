"""
Auto-filter task 2 based on accepted/deleted patterns.

Rules derived from user's manual review:

KEEP if ALL conditions met:
  1. content_html is non-empty (len > 100)
  2. Has HTML table (<table)
  3. Has KaTeX formulas (katex)
  4. Mentions "таблица истинности" (truth table)
  5. Mentions "определите" + "столбц" (determine which column)
  6. Answer is ONLY letters (a-zA-Z), length 3-6
  7. Answer does NOT contain code (def, import, from)
  8. Does NOT have TWO functions (F1 + F2 pattern)
  9. Table is NOT a full truth table (<=6 <tr> rows for partial table)

DELETE otherwise.
"""
import json
import re

all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))
deleted_log = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
accepted_log = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))

accepted_ids = set(a['task_id'] for a in accepted_log if a['task_number'] == 2)
already_reviewed_ids = accepted_ids | set(d['task_id'] for d in deleted_log if d['task_number'] == 2)

task2 = [t for t in all_tasks if t['task_number'] == 2]
non_task2 = [t for t in all_tasks if t['task_number'] != 2]

unreviewed = [t for t in task2 if t['task_id'] not in already_reviewed_ids]

print(f"Task 2 total in file: {len(task2)}")
print(f"Already accepted: {len(accepted_ids)}")
print(f"Unreviewed remaining: {len(unreviewed)}")
print()


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


def should_keep(task):
    html = task.get('content_html', '') or ''
    answer = (task.get('answer', '') or '').strip()
    text = strip_html(html)

    reasons = []

    if len(html) < 100:
        reasons.append("empty_content")

    if '<table' not in html.lower():
        reasons.append("no_table")

    if 'katex' not in html:
        reasons.append("no_katex")

    if not re.search(r'таблиц\w*\s+истинност', text, re.IGNORECASE):
        reasons.append("no_truth_table_mention")

    if not re.search(r'определите.*столбц', text, re.IGNORECASE):
        reasons.append("no_determine_column")

    if not answer:
        reasons.append("no_answer")
    elif not re.match(r'^[a-zA-Z]+$', answer):
        reasons.append(f"answer_not_letters({answer[:30]})")
    elif len(answer) < 3 or len(answer) > 6:
        reasons.append(f"answer_wrong_len({len(answer)})")

    if 'def ' in answer or 'import ' in answer or 'from ' in answer:
        reasons.append("answer_has_code")

    if re.search(r'F_?1.*F_?2|F_?2.*F_?1|две\s+логическ', text, re.IGNORECASE):
        reasons.append("two_functions")

    tr_count = len(re.findall(r'<tr', html))
    if tr_count > 6:
        reasons.append(f"full_truth_table({tr_count}_rows)")

    return (len(reasons) == 0, reasons)


to_keep = []
to_delete = []

for task in unreviewed:
    keep, reasons = should_keep(task)
    if keep:
        to_keep.append(task)
    else:
        to_delete.append((task, reasons))

print(f"AUTO-FILTER RESULTS:")
print(f"  Will KEEP:   {len(to_keep)}")
print(f"  Will DELETE: {len(to_delete)}")
print()

print("--- TASKS TO DELETE ---")
for task, reasons in to_delete:
    ans = (task.get('answer', '') or '')[:40]
    sid = task.get('site_task_id') or '?'
    print(f"  id={task['task_id']:5d} site={str(sid):>8s} ans='{ans}' reasons={reasons}")

print()
print("--- TASKS TO KEEP (sample) ---")
for task in to_keep[:5]:
    ans = (task.get('answer', '') or '')[:40]
    sid = task.get('site_task_id') or '?'
    print(f"  id={task['task_id']:5d} site={str(sid):>8s} ans='{ans}'")
if len(to_keep) > 5:
    print(f"  ... and {len(to_keep) - 5} more")

confirm = input("\nApply filter? (y/n): ").strip().lower()
if confirm == 'y':
    delete_ids = set(t['task_id'] for t, _ in to_delete)
    
    from datetime import datetime
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

    new_all = [t for t in all_tasks if not (t['task_number'] == 2 and t['task_id'] in delete_ids)]

    with open('tasks_export.json', 'w', encoding='utf-8') as f:
        json.dump(new_all, f, ensure_ascii=False, indent=2)

    with open('tasks_deleted_log.json', 'w', encoding='utf-8') as f:
        json.dump(deleted_log, f, ensure_ascii=False, indent=2)

    remaining2 = sum(1 for t in new_all if t['task_number'] == 2)
    print(f"\nDone! Deleted {len(delete_ids)} tasks. Task 2 remaining: {remaining2}")
else:
    print("Cancelled.")
