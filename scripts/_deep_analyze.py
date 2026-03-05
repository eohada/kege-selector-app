"""Deep text analysis of accepted vs deleted for a task number."""
import json
import re
import sys

TASK_NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 3

accepted = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))
deleted = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))

acc = [a for a in accepted if a['task_number'] == TASK_NUM]
dlt = [d for d in deleted if d['task_number'] == TASK_NUM and d.get('content_html')]


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = re.sub(r'data:image/[^"\'>\s]+', '', text)
    return re.sub(r'\s+', ' ', text).strip()


print(f"Task {TASK_NUM}: accepted={len(acc)}, deleted_with_content={len(dlt)}")
print()

print("=" * 100)
print("ACCEPTED TEXTS (user approved these formulations)")
print("=" * 100)
for i, a in enumerate(acc):
    text = strip_html(a.get('content_html', ''))
    ans = (a.get('answer', '') or '')[:30]
    print(f"\n--- ACCEPTED #{i+1} (id={a['task_id']}, ans={ans}) ---")
    print(text[:500])

print()
print("=" * 100)
print("DELETED TEXTS (user rejected these formulations)")
print("=" * 100)
for i, d in enumerate(dlt):
    text = strip_html(d.get('content_html', ''))
    ans = (d.get('answer', '') or '')[:30]
    reasons = d.get('auto_reasons', [])
    print(f"\n--- DELETED #{i+1} (id={d['task_id']}, ans={ans}, auto_reasons={reasons}) ---")
    print(text[:500])
