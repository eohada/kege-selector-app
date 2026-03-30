import os, json, re

files = [
    'boostudy2.0_examples/prepod/biblioteka.html',
    'boostudy2.0_examples/prepod/classroom_example_prepod.html',
    'boostudy2.0_examples/prepod/generator.html',
    'boostudy2.0_examples/prepod/gruppi.html',
    'boostudy2.0_examples/prepod/komnata_uroka.html',
    'boostudy2.0_examples/prepod/new_lesson_example.html',
    'boostudy2.0_examples/prepod/shabloni.html',
    'boostudy2.0_examples/prepod/tarifi.html',
    'boostudy2.0_examples/prepod/zadaniya_example.html',
    'boostudy2.0_examples/profiles/stud_profile_example.html',
    'boostudy2.0_examples/profiles/creator_profile.html'
]

html_pattern = re.compile(r'<(a|button)([^>]*)>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
result = {}

for f in files:
    if not os.path.exists(f):
        continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        matches = html_pattern.findall(content)
        elements = []
        for tag, attrs, inner in matches:
            text = re.sub(r'<[^>]+>', ' ', inner).strip()
            text = re.sub(r'\s+', ' ', text)
            
            id_match = re.search(r'id=[\'\"]([^\'\"]+)[\'\"]', attrs, re.IGNORECASE)
            id_val = id_match.group(1) if id_match else None
            
            title_match = re.search(r'title=[\'\"]([^\'\"]+)[\'\"]', attrs, re.IGNORECASE)
            title_val = title_match.group(1) if title_match else None
            
            href_match = re.search(r'href=[\'\"]([^\'\"]+)[\'\"]', attrs, re.IGNORECASE)
            href_val = href_match.group(1) if href_match else None
            
            icon_match = re.search(r'class=[\'\"]([^\'\"]*(?:ph|fa|icon)[^\'\"]*)[\'\"]', inner, re.IGNORECASE)
            icon_val = icon_match.group(1) if icon_match else None
            
            if text or title_val or icon_val or id_val:
                elements.append({
                    'text': text,
                    'title': title_val,
                    'href': href_val,
                    'icon': icon_val
                })
        # remove duplicates
        unique_elements = []
        seen = set()
        for e in elements:
            key = f"{e['text']}-{e['title']}-{e['href']}-{e['icon']}"
            if key not in seen:
                seen.add(key)
                unique_elements.append(e)
                
        result[f] = unique_elements

with open('parsed_elements.json', 'w', encoding='utf-8') as out:
    json.dump(result, out, ensure_ascii=False, indent=2)
