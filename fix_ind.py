with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# РќР°С…РѕРґРёРј dashboard С„СѓРЅРєС†РёСЋ
dashboard_start = None
try_start = None
except_start = None

for i, line in enumerate(lines):
    if 'def dashboard():' in line:
        dashboard_start = i
    if dashboard_start and '    try:' in line:
        try_start = i
    if try_start and line.strip().startswith('except') and 'dashboard:' not in line:
        except_start = i
        break

if try_start and except_start:
    # РСЃРїСЂР°РІР»СЏРµРј РёРЅРґРµРЅС‚Р°С†РёСЋ РІСЃРµС… СЃС‚СЂРѕРє РІРЅСѓС‚СЂРё try Р±Р»РѕРєР°
    for i in range(try_start + 1, except_start):
        line = lines[i]
        # Р•СЃР»Рё СЃС‚СЂРѕРєР° РЅР°С‡РёРЅР°РµС‚СЃСЏ СЃ 8 РїСЂРѕР±РµР»РѕРІ (СѓСЂРѕРІРµРЅСЊ try), РЅРѕ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ РІРЅСѓС‚СЂРё if/for Рё С‚.Рґ.
        if line.startswith('        ') and not line.startswith('        ' * 2):
            # РџСЂРѕРІРµСЂСЏРµРј РїСЂРµРґС‹РґСѓС‰СѓСЋ СЃС‚СЂРѕРєСѓ - РµСЃР»Рё СЌС‚Рѕ if/for/while, С‚Рѕ СЃР»РµРґСѓСЋС‰Р°СЏ РґРѕР»Р¶РЅР° РёРјРµС‚СЊ 12 РїСЂРѕР±РµР»РѕРІ
            if i > 0 and any(lines[i-1].strip().startswith(kw) for kw in ['if ', 'for ', 'while ', 'elif ', 'else:']):
                if not line.startswith('            '):
                    lines[i] = '            ' + line.lstrip()
            # Р•СЃР»Рё СЌС‚Рѕ РЅРµ РІРЅСѓС‚СЂРё if, РЅРѕ РёРјРµРµС‚ С‚РѕР»СЊРєРѕ 8 РїСЂРѕР±РµР»РѕРІ Рё РїСЂРµРґС‹РґСѓС‰Р°СЏ СЃС‚СЂРѕРєР° Р±С‹Р»Р° if/for
            elif i > 0 and lines[i-1].strip().endswith(':'):
                if line.startswith('        ') and len(line) - len(line.lstrip()) == 8:
                    lines[i] = '            ' + line.lstrip()

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed')
