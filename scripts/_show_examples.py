import json, re, sys, html
sys.stdout.reconfigure(encoding='utf-8')

with open('data/oge_inf_tasks.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def clean(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = html.unescape(text)
    return text

for tn in [7, 9, 11, 12, 13, 14, 15]:
    tasks = [t for t in data if t['task_number'] == tn]
    print(f"\n{'='*80}")
    print(f"ЗАДАНИЕ {tn} ({len(tasks)} шт.)")
    print(f"{'='*80}")
    
    for i, t in enumerate(tasks[:3]):
        h = t.get('content_html', '')
        imgs = re.findall(r'src=["\']([^"\']*)["\']', h)
        file_refs = re.findall(r'(файл\w*|\.xlsx|\.csv|\.xls|\.txt|get_file)', h, re.IGNORECASE)
        text = clean(h)
        
        print(f"\n--- Пример {i+1} (site_id={t['site_id']}) ---")
        print(f"  Ответ: {t.get('answer', 'НЕТ')}")
        print(f"  Картинки: {imgs if imgs else 'нет'}")
        print(f"  Файлы: {file_refs if file_refs else 'нет'}")
        print(f"  Текст: {text[:400]}")
        if len(text) > 400:
            print(f"  ... (+{len(text)-400} символов)")
