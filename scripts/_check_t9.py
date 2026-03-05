import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('data/oge_inf_tasks.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

SDAMGIA_BASE = "https://inf-oge.sdamgia.ru"

t9 = [t for t in data if t['task_number'] == 9]
print(f"Task 9 count: {len(t9)}")

if t9:
    task = t9[0]
    html = task.get('content_html', '')
    
    imgs_before = re.findall(r'src=["\'][^"\']*["\']', html)
    print(f"\nBEFORE fix:")
    for img in imgs_before:
        print(f"  {img}")
    
    fixed = html.replace('src="/get_file', f'src="{SDAMGIA_BASE}/get_file')
    
    imgs_after = re.findall(r'src=["\'][^"\']*["\']', fixed)
    print(f"\nAFTER fix:")
    for img in imgs_after:
        print(f"  {img}")
    
    has_match = 'src="/get_file' in html
    print(f'\nPattern src=\\"/get_file found in raw HTML: {has_match}')
    
    idx = html.find('/get_file')
    if idx >= 0:
        print(f"Context around /get_file: ...{html[max(0,idx-20):idx+40]}...")
