import re
from markupsafe import Markup

def render_qa_comment(text):
    if not text:
        return 'Комментарий отсутствует'
    
    # 1. Извлекаем HAR-логи, если они есть
    logs_html = ""
    parts = text.split('\n\n--- Консоль (HAR) ---\n')
    main_comment = parts[0]
    
    if len(parts) > 1:
        logs_content = parts[1]
        logs_html = f'<details class="mt-4 p-4 rounded-lg" style="background: var(--color-bg-surface); border: 1px solid var(--color-stroke); cursor: pointer;"><summary class="font-bold text-sm select-none" style="color: #f43f5e;"><i class="ph-bold ph-terminal mr-2"></i>Логи консоли (Нажмите, чтобы развернуть)</summary><div class="mt-3 text-xs whitespace-pre-wrap font-mono overflow-x-auto" style="color: var(--color-text-muted); line-height: 1.4;">{logs_content}</div></details>'

    # 2. Замена скриншотов
    pattern_img = r'\[Скриншот прикреплен:\s*(/[^\]]+)\]'
    replacement_img = r'<br><a href="\1" target="_blank" class="inline-block mt-2 mb-2 border border-slate-200 rounded-lg overflow-hidden hover:opacity-90 transition-opacity"><img src="\1" style="max-height: 300px; max-width: 100%; object-fit: contain;"></a><br>'
    html_text = re.sub(pattern_img, replacement_img, main_comment)

    # 3. Замена видео
    pattern_vid = r'\[Видео прикреплено:\s*(/[^\]]+)\]'
    replacement_vid = r'<br><div class="mt-2 mb-2"><video controls style="max-height: 400px; max-width: 100%; border-radius: 8px; border: 1px solid var(--color-stroke);"><source src="\1" type="video/webm"><source src="\1" type="video/mp4">Ваш браузер не поддерживает встроенные видео. <a href="\1" target="_blank" style="color: var(--color-accent);">Скачать видео</a></video></div><br>'
    html_text = re.sub(pattern_vid, replacement_vid, html_text)

    # 4. Базовое форматирование
    html_text = html_text.replace('\n', '<br>')
    
    return Markup(html_text + logs_html)
