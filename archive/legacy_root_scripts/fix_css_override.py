import re

with open('templates/_dock_nav.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Мы должны убедиться, что Свитчер Тем ВСЕГДА виден. В свернутом состоянии хаб прятал "dock-actions".
# Теперь у нас "dock-actions-permanent". Изменим CSS так, чтобы эта часть не сворачивалась.
css_old = r'#floating-hub-global .dock-actions \{[\s\S]*?\}'
css_new = r'''#floating-hub-global .dock-nav-item:not(.active),
#floating-hub-global .dock-mega,
#floating-hub-global .dock-actions-hover {
    display: none;
    opacity: 0;
    width: 0;
    margin: 0 !important;
    padding: 0 !important;
    transform: scale(0.9);
}'''

html = re.sub(r'#floating-hub-global \.dock-nav-item:not\(\.active\),\s*#floating-hub-global \.dock-mega,\s*#floating-hub-global \.dock-actions \{[\s\S]*?\}', css_new, html)

css_hover_old = r'#floating-hub-global:hover \.dock-actions \{[\s\S]*?\}'
css_hover_new = r'''#floating-hub-global:hover .dock-nav-item:not(.active),
#floating-hub-global:hover .dock-mega,
#floating-hub-global:hover .dock-actions-hover {
    display: flex;
    opacity: 1;
    width: auto;
    transform: scale(1);
    transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}'''
html = re.sub(r'#floating-hub-global:hover \.dock-nav-item:not\(\.active\),\s*#floating-hub-global:hover \.dock-mega,\s*#floating-hub-global:hover \.dock-actions \{[\s\S]*?\}', css_hover_new, html)

with open('templates/_dock_nav.html', 'w', encoding='utf-8') as f:
    f.write(html)
