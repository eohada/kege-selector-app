import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('data/oge_inf_accepted.json', 'r', encoding='utf-8') as f:
    accepted = json.load(f)

with open('data/oge_inf_tasks.json', 'r', encoding='utf-8') as f:
    remaining = json.load(f)

print(f"=== ACCEPTED: {len(accepted)} ===")
print(f"=== REMAINING IN FILE: {len(remaining)} ===\n")

by_num = {}
for t in remaining:
    n = t['task_number']
    if n not in by_num:
        by_num[n] = {'total': 0, 'with_img': 0, 'with_file_link': 0, 'with_table': 0, 'text_only': 0, 'answers': []}
    by_num[n]['total'] += 1
    html = t.get('content_html', '')
    
    has_img = bool(re.search(r'<img\s', html, re.IGNORECASE))
    has_file = bool(re.search(r'get_file|\.xlsx|\.csv|\.xls|\.txt|файл', html, re.IGNORECASE))
    has_table = bool(re.search(r'<table', html, re.IGNORECASE))
    
    if has_img:
        by_num[n]['with_img'] += 1
    if has_file:
        by_num[n]['with_file_link'] += 1
    if has_table:
        by_num[n]['with_table'] += 1
    if not has_img and not has_file:
        by_num[n]['text_only'] += 1
    
    ans = t.get('answer', '')
    if ans and len(by_num[n]['answers']) < 3:
        by_num[n]['answers'].append(ans)

print(f"{'#':>3} | {'Всего':>5} | {'Картинки':>8} | {'Файлы':>5} | {'Таблицы':>7} | {'Только текст':>12} | Примеры ответов")
print("-" * 100)
for n in sorted(by_num):
    d = by_num[n]
    ans_str = ', '.join(d['answers'][:3])
    print(f"{n:>3} | {d['total']:>5} | {d['with_img']:>8} | {d['with_file_link']:>5} | {d['with_table']:>7} | {d['text_only']:>12} | {ans_str[:50]}")

print("\n\n=== CATEGORY BREAKDOWN ===")
print("\nТекстовые (можно генерировать):")
text_gen = 0
img_dep = 0
file_dep = 0
for n in sorted(by_num):
    d = by_num[n]
    if d['text_only'] > d['total'] * 0.7:
        print(f"  Задание {n}: {d['text_only']}/{d['total']} текстовых")
        text_gen += d['total']
    elif d['with_img'] > d['total'] * 0.5:
        img_dep += d['total']
    else:
        file_dep += d['total']

print(f"\nКартинко-зависимые:")
for n in sorted(by_num):
    d = by_num[n]
    if d['with_img'] > d['total'] * 0.5:
        print(f"  Задание {n}: {d['with_img']}/{d['total']} с картинками")

print(f"\nФайло/смешанные:")
for n in sorted(by_num):
    d = by_num[n]
    if d['text_only'] <= d['total'] * 0.7 and d['with_img'] <= d['total'] * 0.5:
        print(f"  Задание {n}: img={d['with_img']}, file={d['with_file_link']}, table={d['with_table']}, text={d['text_only']}")

print(f"\nИтого: текстовых={text_gen}, картинко-зависимых={img_dep}, файло-зависимых={file_dep}")
