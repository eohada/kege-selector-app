"""Deep analysis of accepted vs deleted patterns for task 2."""
import json
import re

accepted = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))
deleted = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))
all_tasks = json.load(open('tasks_export.json', 'r', encoding='utf-8'))

acc2 = [a for a in accepted if a['task_number'] == 2]
del2 = [d for d in deleted if d['task_number'] == 2]
rem2 = [t for t in all_tasks if t['task_number'] == 2]

def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def features(task):
    html = task.get('content_html', '')
    text = strip_html(html)
    answer = task.get('answer', '') or ''
    
    has_table = '<table' in html.lower()
    has_b64_img = 'data:image' in html
    has_ext_img = bool(re.search(r'<img[^>]+src=["\']https?://', html))
    has_katex = 'katex' in html
    
    # answer analysis
    ans_len = len(answer.strip())
    ans_is_int = bool(re.match(r'^\d+$', answer.strip())) if answer.strip() else False
    ans_is_letters = bool(re.match(r'^[a-zA-Z]+$', answer.strip())) if answer.strip() else False
    ans_has_spaces = ' ' in answer.strip()
    ans_has_code = 'def ' in answer or 'from ' in answer or 'import ' in answer
    
    # content patterns
    has_truth_table_mention = bool(re.search(r'таблиц[аыуе]\s+истинност', text, re.IGNORECASE))
    has_logic_function = bool(re.search(r'логическ[аоиуе]\w*\s+функци', text, re.IGNORECASE))
    has_determine_column = bool(re.search(r'определите.*столбц', text, re.IGNORECASE))
    has_write_letters = bool(re.search(r'напишите\s+букв', text, re.IGNORECASE))
    has_two_functions = bool(re.search(r'F_?[12]|две\s+логическ', text, re.IGNORECASE))
    has_full_table = len(re.findall(r'<tr', html)) > 6
    
    html_len = len(html)
    
    return {
        'has_table': has_table,
        'has_b64_img': has_b64_img,
        'has_ext_img': has_ext_img,
        'has_katex': has_katex,
        'ans_len': ans_len,
        'ans_is_int': ans_is_int,
        'ans_is_letters': ans_is_letters,
        'ans_has_spaces': ans_has_spaces,
        'ans_has_code': ans_has_code,
        'has_truth_table': has_truth_table_mention,
        'has_logic_function': has_logic_function,
        'has_determine_column': has_determine_column,
        'has_write_letters': has_write_letters,
        'has_two_functions': has_two_functions,
        'has_full_table': has_full_table,
        'html_len': html_len,
    }

print("=" * 80)
print(f"TASK 2 ANALYSIS: accepted={len(acc2)}, deleted={len(del2)}, remaining={len(rem2)}")
print("=" * 80)

print("\n--- ACCEPTED patterns ---")
for a in acc2:
    f = features(a)
    ans = (a.get('answer', '') or '')[:50]
    print(f"  id={a['task_id']:5d} ans='{ans}' | tbl={f['has_table']} img={f['has_b64_img']} katex={f['has_katex']} "
          f"truth={f['has_truth_table']} logic={f['has_logic_function']} det_col={f['has_determine_column']} "
          f"letters={f['ans_is_letters']} int={f['ans_is_int']} ans_len={f['ans_len']} "
          f"2func={f['has_two_functions']} full_tbl={f['has_full_table']} html={f['html_len']}")

print("\n--- DELETED patterns ---")
for d in del2:
    f = features(d)
    ans = (d.get('answer', '') or '')[:50]
    print(f"  id={d['task_id']:5d} ans='{ans}' | tbl={f['has_table']} img={f['has_b64_img']} katex={f['has_katex']} "
          f"truth={f['has_truth_table']} logic={f['has_logic_function']} det_col={f['has_determine_column']} "
          f"letters={f['ans_is_letters']} int={f['ans_is_int']} ans_len={f['ans_len']} "
          f"2func={f['has_two_functions']} full_tbl={f['has_full_table']} html={f['html_len']}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

acc_feats = [features(a) for a in acc2]
del_feats = [features(d) for d in del2]

for key in ['has_table', 'has_b64_img', 'has_ext_img', 'has_katex', 'ans_is_int', 'ans_is_letters',
            'ans_has_spaces', 'ans_has_code', 'has_truth_table', 'has_logic_function',
            'has_determine_column', 'has_write_letters', 'has_two_functions', 'has_full_table']:
    acc_pct = sum(1 for f in acc_feats if f[key]) / len(acc_feats) * 100 if acc_feats else 0
    del_pct = sum(1 for f in del_feats if f[key]) / len(del_feats) * 100 if del_feats else 0
    marker = " <<<" if abs(acc_pct - del_pct) > 30 else ""
    print(f"  {key:25s}: accepted={acc_pct:5.1f}%  deleted={del_pct:5.1f}%{marker}")

acc_ans_lens = [f['ans_len'] for f in acc_feats]
del_ans_lens = [f['ans_len'] for f in del_feats]
print(f"\n  answer_len avg: accepted={sum(acc_ans_lens)/len(acc_ans_lens):.1f}  deleted={sum(del_ans_lens)/len(del_ans_lens):.1f}")

acc_html_lens = [f['html_len'] for f in acc_feats]
del_html_lens = [f['html_len'] for f in del_feats]
print(f"  html_len avg:   accepted={sum(acc_html_lens)/len(acc_html_lens):.0f}  deleted={sum(del_html_lens)/len(del_html_lens):.0f}")
