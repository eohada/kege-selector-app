import os
from flask import render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.designer import designer_bp
from app.auth.rbac_utils import check_access
import time

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@designer_bp.route('/designer/assets')
@login_required
@check_access('assets.manage')
def assets_manager():
    """Галерея ассетов для дизайнера"""
    static_folder = current_app.static_folder
    assets = []
    
    # Сканируем папку static/icons и static/images
    target_dirs = ['icons', 'images', 'img']
    
    for subdir in target_dirs:
        full_path = os.path.join(static_folder, subdir)
        if os.path.exists(full_path):
            for filename in os.listdir(full_path):
                if allowed_file(filename):
                    assets.append({
                        'folder': subdir,
                        'filename': filename,
                        'path': f"{subdir}/{filename}",
                        'url': url_for('static', filename=f"{subdir}/{filename}") + f"?v={int(time.time())}"
                    })
    
    return render_template('designer_assets.html', assets=assets)

@designer_bp.route('/designer/assets/replace', methods=['POST'])
@login_required
@check_access('assets.manage')
def replace_asset():
    """Замена существующего файла"""
    if 'file' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('designer.assets_manager'))
        
    file = request.files['file']
    target_folder = request.form.get('folder')
    target_filename = request.form.get('filename')
    
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('designer.assets_manager'))
        
    if file and target_folder and target_filename:
        # Проверяем безопасность путей (чтобы не вышли за пределы static)
        if '..' in target_folder or '..' in target_filename:
            flash('Недопустимый путь', 'error')
            return redirect(url_for('designer.assets_manager'))
            
        full_path = os.path.join(current_app.static_folder, target_folder, target_filename)
        
        if not os.path.exists(full_path):
            flash('Целевой файл не найден', 'error')
            return redirect(url_for('designer.assets_manager'))
            
        try:
            # Перезаписываем файл
            file.save(full_path)
            flash(f'Файл {target_filename} успешно обновлен!', 'success')
        except Exception as e:
            flash(f'Ошибка при сохранении: {e}', 'error')
            
    return redirect(url_for('designer.assets_manager'))
