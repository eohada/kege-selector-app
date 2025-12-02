lines = open("app.py", "r", encoding="utf-8").readlines()
# РќР°С…РѕРґРёРј Рё СѓРґР°Р»СЏРµРј РґСѓР±Р»РёРєР°С‚С‹ РїР°СЂР°РјРµС‚СЂРѕРІ РїРѕСЃР»Рµ СЃС‚СЂРѕРєРё 599
for i in range(599, min(615, len(lines))):
    if "@app.route" in lines[i]:
        # РЈРґР°Р»СЏРµРј РІСЃРµ СЃС‚СЂРѕРєРё РјРµР¶РґСѓ 599 Рё i
        lines = lines[:600] + lines[i:]
        break
    elif "students=students," in lines[i] or "pagination=pagination," in lines[i]:
        # Р­С‚Рѕ РґСѓР±Р»РёРєР°С‚, РїСЂРѕРїСѓСЃРєР°РµРј
        continue
open("app.py", "w", encoding="utf-8").writelines(lines)
print("Removed duplicates")
