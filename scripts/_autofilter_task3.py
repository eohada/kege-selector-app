"""
Auto-filter task 3 based on accepted/deleted patterns.
Also marks all kept tasks as accepted.
"""
import json
import re
from datetime import datetime

TASK_NUM = 3

all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))
deleted_log = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
accepted_log = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))

accepted_ids = set(a['task_id'] for a in accepted_log if a['task_number'] == TASK_NUM)
deleted_ids = set(d['task_id'] for d in deleted_log if d['task_number'] == TASK_NUM)
already_reviewed = accepted_ids | deleted_ids

task_n = [t for t in all_tasks if t['task_number'] == TASK_NUM]
unreviewed = [t for t in task_n if t['task_id'] not in already_reviewed]

print(f"Task {TASK_NUM}: in_file={len(task_n)}, accepted={len(accepted_ids)}, deleted={len(deleted_ids)}, unreviewed={len(unreviewed)}")
print()


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


# --- Analyze patterns from user's samples ---
acc_samples = [a for a in accepted_log if a['task_number'] == TASK_NUM]
del_samples = [d for d in deleted_log if d['task_number'] == TASK_NUM and d.get('content_html')]

print("=== ACCEPTED SAMPLE ANALYSIS ===")
for a in acc_samples[:10]:
    html = a.get('content_html', '')
    text = strip_html(html)[:200]
    ans = (a.get('answer', '') or '')[:50]
    has_tbl = '<table' in html.lower()
    has_katex = 'katex' in html
    has_img = 'data:image' in html
    tr_count = len(re.findall(r'<tr', html))
    print(f"  id={a['task_id']:5d} ans='{ans}' tbl={has_tbl} katex={has_katex} img={has_img} tr={tr_count} html={len(html)}")

print()
print("=== DELETED SAMPLE ANALYSIS ===")
for d in del_samples[:10]:
    html = d.get('content_html', '')
    text = strip_html(html)[:200]
    ans = (d.get('answer', '') or '')[:50]
    has_tbl = '<table' in html.lower()
    has_katex = 'katex' in html
    has_img = 'data:image' in html
    tr_count = len(re.findall(r'<tr', html))
    reasons = d.get('auto_reasons', [])
    print(f"  id={d['task_id']:5d} ans='{ans}' tbl={has_tbl} katex={has_katex} img={has_img} tr={tr_count} html={len(html)}")
    print(f"    text: {text[:150]}")

print()

# --- Derive rules ---
# Collect features from accepted
acc_features = []
for a in acc_samples:
    html = a.get('content_html', '') or ''
    text = strip_html(html)
    answer = (a.get('answer', '') or '').strip()
    acc_features.append({
        'ans': answer,
        'ans_len': len(answer),
        'ans_is_int': bool(re.match(r'^\d+$', answer)) if answer else False,
        'has_table': '<table' in html.lower(),
        'has_katex': 'katex' in html,
        'has_img': 'data:image' in html,
        'html_len': len(html),
        'has_code': 'def ' in answer or 'import ' in answer,
    })

# Print feature summary
print("=== ACCEPTED FEATURE SUMMARY ===")
for key in ['has_table', 'has_katex', 'has_img', 'ans_is_int', 'has_code']:
    pct = sum(1 for f in acc_features if f[key]) / len(acc_features) * 100
    print(f"  {key:20s}: {pct:5.1f}%")
ans_lens = [f['ans_len'] for f in acc_features]
print(f"  ans_len range: {min(ans_lens)}-{max(ans_lens)}, avg={sum(ans_lens)/len(ans_lens):.1f}")
html_lens = [f['html_len'] for f in acc_features]
print(f"  html_len range: {min(html_lens)}-{max(html_lens)}")
print()

# Determine answer type pattern
ans_types = {}
for f in acc_features:
    a = f['ans']
    if re.match(r'^\d+$', a):
        ans_types['int'] = ans_types.get('int', 0) + 1
    elif re.match(r'^[a-zA-Z]+$', a):
        ans_types['letters'] = ans_types.get('letters', 0) + 1
    else:
        ans_types['other'] = ans_types.get('other', 0) + 1
print(f"  Answer types: {ans_types}")
print()


def should_keep(task):
    html = task.get('content_html', '') or ''
    answer = (task.get('answer', '') or '').strip()
    text = strip_html(html)
    reasons = []

    if len(html) < 100:
        reasons.append("empty_content")

    if not answer:
        reasons.append("no_answer")

    if 'def ' in answer or 'import ' in answer or 'from ' in answer:
        reasons.append("answer_has_code")

    # Task 3 specific: check if answer seems valid
    # Based on accepted pattern, determine what's valid
    # If all accepted are integers, reject non-integers, etc.
    dominant_type = max(ans_types, key=ans_types.get) if ans_types else 'int'

    if dominant_type == 'int':
        if answer and not re.match(r'^\d+$', answer):
            if len(answer) > 20:
                reasons.append(f"answer_too_long({len(answer)})")
            elif re.search(r'[а-яА-Я]', answer):
                reasons.append("answer_has_cyrillic")
    elif dominant_type == 'letters':
        if answer and not re.match(r'^[a-zA-Z]+$', answer):
            reasons.append("answer_not_letters")

    # Check content quality
    if 'katex' not in html and not any(x in html for x in ['<table', 'data:image', '<pre', '<code']):
        if len(html) < 200:
            reasons.append("low_quality_content")

    return (len(reasons) == 0, reasons)


# --- Apply filter ---
to_keep = []
to_delete = []

for task in unreviewed:
    keep, reasons = should_keep(task)
    if keep:
        to_keep.append(task)
    else:
        to_delete.append((task, reasons))

print(f"AUTO-FILTER RESULTS:")
print(f"  Will KEEP (and mark accepted): {len(to_keep)}")
print(f"  Will DELETE:                   {len(to_delete)}")
print()

if to_delete:
    print("--- TASKS TO DELETE ---")
    for task, reasons in to_delete:
        ans = (task.get('answer', '') or '')[:40]
        sid = task.get('site_task_id') or '?'
        print(f"  id={task['task_id']:5d} site={str(sid):>8s} ans='{ans}' reasons={reasons}")
    print()

if to_keep:
    print(f"--- TASKS TO KEEP (showing first 10) ---")
    for task in to_keep[:10]:
        ans = (task.get('answer', '') or '')[:40]
        sid = task.get('site_task_id') or '?'
        print(f"  id={task['task_id']:5d} site={str(sid):>8s} ans='{ans}'")
    if len(to_keep) > 10:
        print(f"  ... and {len(to_keep) - 10} more")

confirm = input("\nApply? (y/n): ").strip().lower()
if confirm == 'y':
    # Delete bad tasks
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

    # Mark kept tasks as accepted
    keep_ids = set(t['task_id'] for t in to_keep)
    for task in to_keep:
        accepted_log.append({
            'task_id': task['task_id'],
            'task_number': task['task_number'],
            'site_task_id': task.get('site_task_id'),
            'content_html': task.get('content_html', ''),
            'answer': task.get('answer'),
            'accepted_at': datetime.now().isoformat(),
        })

    # Save
    new_all = [t for t in all_tasks if not (t['task_number'] == TASK_NUM and t['task_id'] in delete_ids)]

    with open('tasks_export.json', 'w', encoding='utf-8') as f:
        json.dump(new_all, f, ensure_ascii=False, indent=2)
    with open('tasks_deleted_log.json', 'w', encoding='utf-8') as f:
        json.dump(deleted_log, f, ensure_ascii=False, indent=2)
    with open('tasks_accepted_log.json', 'w', encoding='utf-8') as f:
        json.dump(accepted_log, f, ensure_ascii=False, indent=2)

    remaining = sum(1 for t in new_all if t['task_number'] == TASK_NUM)
    total_accepted = sum(1 for a in accepted_log if a['task_number'] == TASK_NUM)
    print(f"\nDone!")
    print(f"  Deleted: {len(delete_ids)}")
    print(f"  Newly accepted: {len(keep_ids)}")
    print(f"  Total accepted (task {TASK_NUM}): {total_accepted}")
    print(f"  Remaining in file (task {TASK_NUM}): {remaining}")
else:
    print("Cancelled.")
