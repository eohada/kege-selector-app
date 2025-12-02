import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. РСЃРїСЂР°РІР»СЏРµРј РіР»РѕР±Р°Р»СЊРЅС‹Р№ РѕР±СЂР°Р±РѕС‚С‡РёРє РѕС€РёР±РѕРє
old_handler = """@app.errorhandler(SQLAlchemyError)
def handle_db_error(e):
    db.session.rollback()
    logger.error(f'РћС€РёР±РєР° SQLAlchemy: {e}', exc_info=True)
    if isinstance(e, PendingRollbackError):
        logger.warning('РћР±РЅР°СЂСѓР¶РµРЅР° РЅРµРІР°Р»РёРґРЅР°СЏ С‚СЂР°РЅР·Р°РєС†РёСЏ, РІС‹РїРѕР»РЅРµРЅ rollback')
    raise"""

new_handler = """@app.errorhandler(SQLAlchemyError)
def handle_db_error(e):
    db.session.rollback()
    logger.error(f'РћС€РёР±РєР° SQLAlchemy: {e}', exc_info=True)
    if isinstance(e, PendingRollbackError):
        logger.warning('РћР±РЅР°СЂСѓР¶РµРЅР° РЅРµРІР°Р»РёРґРЅР°СЏ С‚СЂР°РЅР·Р°РєС†РёСЏ, РІС‹РїРѕР»РЅРµРЅ rollback')
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': 'РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ Рє Р±Р°Р·Рµ РґР°РЅРЅС‹С…. РџРѕРїСЂРѕР±СѓР№С‚Рµ РѕР±РЅРѕРІРёС‚СЊ СЃС‚СЂР°РЅРёС†Сѓ.'}), 500
    flash('РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ Рє Р±Р°Р·Рµ РґР°РЅРЅС‹С…. РџРѕРїСЂРѕР±СѓР№С‚Рµ РѕР±РЅРѕРІРёС‚СЊ СЃС‚СЂР°РЅРёС†Сѓ.', 'error')
    try:
        return redirect(url_for('dashboard'))
    except:
        return 'РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ Рє Р±Р°Р·Рµ РґР°РЅРЅС‹С…', 500"""

content = content.replace(old_handler, new_handler)

# 2. РСЃРїСЂР°РІР»СЏРµРј identify_tester
identify_start = content.find('def identify_tester():')
if identify_start != -1:
    except_pos = content.find('except Exception as e:', identify_start)
    if except_pos != -1 and 'db.session.rollback()' not in content[identify_start:except_pos+200]:
        old_except = 'except Exception as e:'
        new_except = """except (PendingRollbackError, OperationalError) as e:
        db.session.rollback()
    except Exception as e:
        db.session.rollback()"""
        content = content[:except_pos] + new_except + content[except_pos + len(old_except):]

# 3. РћР±РµСЂС‚С‹РІР°РµРј dashboard
dashboard_start = content.find('def dashboard():')
if dashboard_start != -1 and 'try:' not in content[dashboard_start:dashboard_start+150]:
    # РќР°С…РѕРґРёРј РєРѕРЅРµС† С„СѓРЅРєС†РёРё (СЃР»РµРґСѓСЋС‰Р°СЏ def РёР»Рё @app.route)
    next_def = content.find('\ndef ', dashboard_start + 20)
    next_route = content.find('\n@app.route', dashboard_start + 20)
    func_end = min([x for x in [next_def, next_route] if x != -1] or [len(content)])
    
    func_body = content[dashboard_start:func_end]
    # РќР°С…РѕРґРёРј РїРѕСЃР»РµРґРЅРёР№ return
    last_return = func_body.rfind('\n    return ')
    if last_return != -1:
        return_end = func_body.find('\n', last_return + 15)
        if return_end == -1:
            return_end = len(func_body)
        
        new_func = func_body[:18] + '    try:\n        ' + func_body[18:return_end] + '\n    except (PendingRollbackError, OperationalError) as e:\n        db.session.rollback()\n        logger.error(f"РћС€РёР±РєР° Р‘Р” РІ dashboard: {e}")\n        flash("РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ Рє Р±Р°Р·Рµ РґР°РЅРЅС‹С…. РџРѕРїСЂРѕР±СѓР№С‚Рµ РѕР±РЅРѕРІРёС‚СЊ СЃС‚СЂР°РЅРёС†Сѓ.", "error")\n        return render_template("dashboard.html", students=[], pagination=None, search_query=request.args.get("search", "").strip(), category_filter=request.args.get("category", ""), total_students=0, ege_students=0, oge_students=0, levelup_students=0, programming_students=0)\n    except Exception as e:\n        db.session.rollback()\n        logger.error(f"РќРµРѕР¶РёРґР°РЅРЅР°СЏ РѕС€РёР±РєР° РІ dashboard: {e}", exc_info=True)\n        flash("РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё Р·Р°РіСЂСѓР·РєРµ РґР°РЅРЅС‹С….", "error")\n        return render_template("dashboard.html", students=[], pagination=None, search_query="", category_filter="", total_students=0, ege_students=0, oge_students=0, levelup_students=0, programming_students=0)\n' + func_body[return_end:]
        
        content = content[:dashboard_start] + new_func + content[func_end:]

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('РСЃРїСЂР°РІР»РµРЅРёСЏ РїСЂРёРјРµРЅРµРЅС‹')
