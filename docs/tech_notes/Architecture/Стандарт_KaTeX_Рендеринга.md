---
status: stable
tags: [status/stable, katex, standard, architecture, jinja2, vendor]
domain: Стандарты и Архитектура Платформы
type: standard
---
# Канонический Стандарт Рендеринга Формул KaTeX

**Статус документа:** #status/stable (Канон Платформы BooStudy)

## 📌 4 Золотых Правила Рендеринга Формул

### 1. Python Seed Standard (Сырые строки `r"""..."""`)
Все задачи с LaTeX математикой в сидах и миграциях **ОБЯЗАНЫ** декларироваться исключительно через сырые тройные кавычки `r"""..."""` или `r'''...'''`.
- **Запрещено:** обычные кавычки `"""..."""`, в которых Python съедает бэкслэши `\to` (превращает в `\t` табуляцию) и `\neq` (в перенос строки `\n`).
- **Обязательно:** оборачивать формулы в разделители `$ ... $` (inline) или `$$ ... $$` (display):
  ```python
  content_html = r"""<p>Логическая функция $F$: $((x \to y) \equiv (w \to z)) \lor (x \land w)$</p>"""
  ```

### 2. Jinja2 Safe Output (`| safe`)
В HTML-шаблонах вывод математического условия задачи выполняется строго с фильтром `safe`:
```html
<div class="math-content">
  {{ task.content_html | safe }}
</div>
```

### 3. Vendor CDN & Local Fallback (`/static/vendor/katex/`)
Подключение вендора KaTeX выполняется с CDN jsDelivr и обязательным `onerror` фолбэком на локальные статические файлы проекта:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css" onerror='this.onerror=null;this.href="{{ url_for("static", filename="vendor/katex/katex.min.css") }}";'>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js" onerror='this.onerror=null;this.src="{{ url_for("static", filename="vendor/katex/katex.min.js") }}";'></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js" onerror='this.onerror=null;this.src="{{ url_for("static", filename="vendor/katex/auto-render.min.js") }}";' onload="initKaTeX()"></script>
```

### 4. JS Parser Configuration & Microtask Delay (`renderMathInElement`)
Функция клиентского парсера настроена без игнорирования тегов `<code>` и с микротасковой задержкой `setTimeout(..., 50)` при динамическом переключении задач:
```javascript
function renderKaTeXNow() {
    console.log("[KaTeX Debug] Attempting render...", typeof renderMathInElement);
    const target = document.getElementById('task-content-area') || document.body;
    if (typeof renderMathInElement === 'function') {
        renderMathInElement(target, {
            delimiters: [
                {left: "$$", right: "$$", display: true},
                {left: "$", right: "$", display: false},
                {left: "\\(", right: "\\)", display: false},
                {left: "\\[", right: "\\]", display: true}
            ],
            ignoredTags: ["script", "noscript", "style", "textarea", "pre"], // БЕЗ 'code'!
            throwOnError: false
        });
        console.log("[KaTeX Debug] Render finished successfully!");
    }
}
```
