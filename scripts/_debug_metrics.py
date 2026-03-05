import json, re, sys, html as html_module
sys.stdout.reconfigure(encoding='utf-8')

with open('data/oge_inf_tasks.json', 'r', encoding='utf-8') as f:
    tasks = json.load(f)

def clean_text(h):
    t = re.sub(r'<[^>]+>', ' ', h or '')
    t = html_module.unescape(t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = t.replace('\u00ad', '')
    return t

def count_html_rows(h):
    return len(re.findall(r'<tr', h or '', re.IGNORECASE))

for tn in [1, 4, 5, 6, 8, 13, 15]:
    group = [t for t in tasks if t['task_number'] == tn]
    print(f"\n{'='*60}")
    print(f"TASK {tn} ({len(group)} tasks)")
    print(f"{'='*60}")

    texts = [len(clean_text(t.get('content_html', ''))) for t in group]
    answers = [len(str(t.get('answer', '') or '')) for t in group]
    rows = [count_html_rows(t.get('content_html', '')) for t in group]

    print(f"  text_len:  min={min(texts)}  max={max(texts)}  avg={sum(texts)//len(texts)}  median={sorted(texts)[len(texts)//2]}")
    print(f"  answer_len: min={min(answers)}  max={max(answers)}  avg={sum(answers)//len(answers)}  median={sorted(answers)[len(answers)//2]}")
    print(f"  html_rows: min={min(rows)}  max={max(rows)}  avg={sum(rows)//len(rows)}  median={sorted(rows)[len(rows)//2]}")

    if tn == 6:
        for t in group[:5]:
            txt = clean_text(t.get('content_html', ''))
            has_loop = bool(re.search(r'(while|for|пока|цикл|нц\b)', txt, re.IGNORECASE))
            has_nested = bool(re.search(r'(если.*если|if.*if|вложенн)', txt, re.IGNORECASE))
            print(f"    id={t['site_id']}  len={len(txt)}  loop={has_loop}  nested={has_nested}  ans={t.get('answer','')}")

    if tn == 8:
        for t in group[:5]:
            txt = clean_text(t.get('content_html', ''))
            conds = len(re.findall(r'(\bИ\b|\bИЛИ\b|\bНЕ\b|\bAND\b|\bOR\b|\bNOT\b|∧|∨|¬|&)', txt))
            print(f"    id={t['site_id']}  len={len(txt)}  conds={conds}  ans={t.get('answer','')}")

    if tn == 1:
        for t in group[:5]:
            txt = clean_text(t.get('content_html', ''))
            al = len(str(t.get('answer', '') or ''))
            print(f"    id={t['site_id']}  text_len={len(txt)}  answer_len={al}  ans='{t.get('answer','')}'")

    if tn == 15:
        for t in group[:3]:
            txt = clean_text(t.get('content_html', ''))
            has_nl = bool(re.search(r'(вложенн\w*\s+цикл|цикл\w*\s+внутри)', txt, re.IGNORECASE))
            has_aux = bool(re.search(r'(вспомогательн|процедур)', txt, re.IGNORECASE))
            print(f"    id={t['site_id']}  len={len(txt)}  nested_loop={has_nl}  auxiliary={has_aux}")
