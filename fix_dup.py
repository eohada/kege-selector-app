with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# РЈРґР°Р»СЏРµРј РґСѓР±Р»РёРєР°С‚ СЃС‚СЂРѕРєРё 560
if len(lines) > 559 and lines[559].strip() == 'if category_filter:':
    lines.pop(559)

# РСЃРїСЂР°РІР»СЏРµРј СЃС‚СЂРѕРєСѓ 560 (С‚РµРїРµСЂСЊ СЌС‚Рѕ Р±СѓРґРµС‚ 559 РїРѕСЃР»Рµ СѓРґР°Р»РµРЅРёСЏ)
if len(lines) > 559:
    lines[559] = '            query = query.filter_by(category=category_filter)\n'

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed')
