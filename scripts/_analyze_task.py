"""Analyze accepted/deleted patterns for a given task number."""
import json
import re
import sys

TASK_NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 2

accepted = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))
deleted = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))

acc = [a for a in accepted if a['task_number'] == TASK_NUM]
dlt = [d for d in deleted if d['task_number'] == TASK_NUM]
remaining = [t for t in all_tasks if t['task_number'] == TASK_NUM]

print(f"Task #{TASK_NUM}: accepted={len(acc)}, deleted={len(dlt)}, remaining={len(remaining)}")
print()

def extract_text(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = re.sub(r'data:image/[^"\'>\s]+', '[IMG]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def has_base64_img(html):
    return 'data:image' in (html or '')

def has_external_img(html):
    return bool(re.search(r'<img[^>]+src=["\']https?://', html or ''))

def has_table(html):
    return '<table' in (html or '').lower()

def answer_type(ans):
    if not ans:
        return 'NONE'
    if re.match(r'^\d+$', ans.strip()):
        return 'INT'
    if re.match(r'^[\d.]+$', ans.strip()):
        return 'FLOAT'
    return 'TEXT'

print("=== ACCEPTED ===")
for a in acc:
    html = a.get('content_html', '')
    text = extract_text(html)[:250]
    print(f"  id={a['task_id']} ans={a.get('answer','?')} ans_type={answer_type(a.get('answer',''))} "
          f"len={len(html)} b64img={has_base64_img(html)} extimg={has_external_img(html)} table={has_table(html)}")
    print(f"    {text}")
    print()

print("=== DELETED ===")
for d in dlt:
    html = d.get('content_html', '')
    text = extract_text(html)[:250]
    print(f"  id={d['task_id']} ans={d.get('answer','?')} ans_type={answer_type(d.get('answer',''))} "
          f"len={len(html)} b64img={has_base64_img(html)} extimg={has_external_img(html)} table={has_table(html)}")
    print(f"    {text}")
    print()
