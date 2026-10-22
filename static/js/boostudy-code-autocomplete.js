/**
 * BooStudy Code Autocomplete (IntelliSense)
 * Контекстное автодополнение для редактора кода в стиле VS Code.
 */
(function(window, document) {
  'use strict';

  const PYTHON_KEYWORDS = [
    'def', 'return', 'if', 'elif', 'else', 'for', 'while', 'break', 'continue',
    'import', 'from', 'as', 'class', 'try', 'except', 'finally', 'with', 'lambda',
    'yield', 'True', 'False', 'None', 'is', 'not', 'and', 'or', 'in', 'pass', 'global'
  ];

  const PYTHON_BUILTINS = [
    'print', 'range', 'len', 'input', 'int', 'str', 'float', 'bool', 'list', 'dict',
    'set', 'tuple', 'sorted', 'enumerate', 'zip', 'min', 'max', 'sum', 'abs', 'round',
    'map', 'filter', 'all', 'any', 'open', 'read', 'readline', 'write', 'close',
    'append', 'extend', 'pop', 'remove', 'insert', 'index', 'count', 'clear', 'copy',
    'keys', 'values', 'items', 'get', 'update', 'split', 'join', 'strip', 'replace',
    'lower', 'upper', 'startswith', 'endswith', 'find', 'format'
  ];

  class BooCodeAutocomplete {
    constructor() {
      this.textarea = null;
      this.popup = null;
      this.suggestions = [];
      this.selectedIndex = 0;
      this.currentPrefix = '';
      this.prefixStart = 0;
      this.isVisible = false;

      this.init();
    }

    init() {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => this.setup());
      } else {
        this.setup();
      }
    }

    setup() {
      this.textarea = document.getElementById('code-editor-textarea');
      if (!this.textarea) return;

      this.createPopupEl();
      this.bindEvents();
    }

    createPopupEl() {
      let existing = document.getElementById('code-autocomplete-popup');
      if (existing) {
        this.popup = existing;
        return;
      }

      this.popup = document.createElement('div');
      this.popup.id = 'code-autocomplete-popup';
      this.popup.style.display = 'none';
      document.body.appendChild(this.popup);
    }

    bindEvents() {
      if (!this.textarea) return;

      this.textarea.addEventListener('input', () => this.onInput());
      this.textarea.addEventListener('keydown', (e) => this.onKeyDown(e), true);
      this.textarea.addEventListener('click', () => this.hide());
      this.textarea.addEventListener('blur', () => {
        setTimeout(() => {
          if (!this.popup?.contains(document.activeElement)) {
            this.hide();
          }
        }, 180);
      });

      window.addEventListener('resize', () => this.hide());
      window.addEventListener('scroll', () => this.hide(), true);
    }

    onInput() {
      if (!this.textarea) this.setup();
      if (!this.textarea) return;

      const val = this.textarea.value;
      const caret = this.textarea.selectionStart;

      // Получаем текст текущей строки до каретки
      const lineStart = val.lastIndexOf('\n', caret - 1) + 1;
      const textBefore = val.slice(lineStart, caret);

      // Извлекаем идентификатор перед кареткой
      const match = textBefore.match(/([a-zA-Z_][a-zA-Z0-9_]*)$/);
      if (!match || match[1].length < 2) {
        this.hide();
        return;
      }

      const prefix = match[1];
      this.currentPrefix = prefix;
      this.prefixStart = caret - prefix.length;

      const candidates = this.collectCandidates(prefix, val);
      if (!candidates.length) {
        this.hide();
        return;
      }

      this.suggestions = candidates.slice(0, 8);
      this.selectedIndex = 0;
      this.render();
      this.positionPopup();
      this.show();
    }

    collectCandidates(prefix, fullText) {
      const lower = prefix.toLowerCase();
      const tokens = new Map();

      // 1. Поиск переменных и функций в текущем коде
      const idRegex = /\b([a-zA-Z_][a-zA-Z0-9_]{1,})\b/g;
      let m;
      while ((m = idRegex.exec(fullText)) !== null) {
        const word = m[1];
        if (word === prefix) continue;
        if (word.toLowerCase().startsWith(lower)) {
          if (!tokens.has(word)) {
            const nextChar = fullText.slice(m.index + word.length).trim()[0];
            const isFunc = nextChar === '(';
            tokens.set(word, {
              name: word,
              type: isFunc ? 'func' : 'var',
              priority: word.startsWith(prefix) ? 1 : 2,
            });
          }
        }
      }

      // 2. Встроенные функции Python
      for (const b of PYTHON_BUILTINS) {
        if (b.toLowerCase().startsWith(lower) && !tokens.has(b)) {
          tokens.set(b, {
            name: b,
            type: 'builtin',
            priority: b.startsWith(prefix) ? 3 : 4,
          });
        }
      }

      // 3. Ключевые слова Python
      for (const k of PYTHON_KEYWORDS) {
        if (k.toLowerCase().startsWith(lower) && !tokens.has(k)) {
          tokens.set(k, {
            name: k,
            type: 'keyword',
            priority: k.startsWith(prefix) ? 5 : 6,
          });
        }
      }

      const list = Array.from(tokens.values());
      list.sort((a, b) => {
        if (a.priority !== b.priority) return a.priority - b.priority;
        return a.name.localeCompare(b.name);
      });

      return list;
    }

    positionPopup() {
      if (!this.popup || !this.textarea) return;

      const rect = this.textarea.getBoundingClientRect();
      const val = this.textarea.value;
      const caret = this.prefixStart;

      const lines = val.slice(0, caret).split('\n');
      const lineIdx = lines.length - 1;
      const colIdx = lines[lineIdx].length;

      const style = window.getComputedStyle(this.textarea);
      const lineHeight = parseFloat(style.lineHeight) || 22;
      const charWidth = 7.3;

      let top = rect.top + (parseFloat(style.paddingTop) || 24) + (lineIdx * lineHeight) - this.textarea.scrollTop + lineHeight + 4;
      let left = rect.left + (parseFloat(style.paddingLeft) || 16) + (colIdx * charWidth) - this.textarea.scrollLeft;

      const popupW = 280;
      const popupH = 220;
      if (left + popupW > window.innerWidth - 12) {
        left = window.innerWidth - popupW - 12;
      }
      if (top + popupH > window.innerHeight - 12) {
        top = top - lineHeight - popupH - 8;
      }

      this.popup.style.top = `${Math.max(10, Math.round(top))}px`;
      this.popup.style.left = `${Math.max(10, Math.round(left))}px`;
    }

    render() {
      if (!this.popup) return;

      const badges = {
        var: { label: 'v', cls: 'code-autocomplete-badge-var' },
        func: { label: 'f', cls: 'code-autocomplete-badge-func' },
        builtin: { label: 'b', cls: 'code-autocomplete-badge-builtin' },
        keyword: { label: 'k', cls: 'code-autocomplete-badge-keyword' },
      };

      this.popup.innerHTML = this.suggestions.map((item, idx) => {
        const isSelected = idx === this.selectedIndex;
        const b = badges[item.type] || badges.var;
        const prefixLen = this.currentPrefix.length;
        const matchPart = item.name.slice(0, prefixLen);
        const restPart = item.name.slice(prefixLen);

        return `
          <div class="code-autocomplete-item ${isSelected ? 'is-selected' : ''}" data-index="${idx}">
            <div style="display:flex;align-items:center;gap:0.5rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
              <span class="code-autocomplete-badge ${b.cls}">
                ${b.label}
              </span>
              <span style="overflow:hidden;text-overflow:ellipsis;">
                <strong style="color:#4f46e5;">${escapeHtml(matchPart)}</strong>${escapeHtml(restPart)}
              </span>
            </div>
            <span style="font-size:0.5625rem;text-transform:uppercase;font-weight:700;color:#94a3b8;font-family:sans-serif;letter-spacing:0.05em;padding-left:0.5rem;flex-shrink:0;">
              ${item.type}
            </span>
          </div>
        `;
      }).join('');

      this.popup.querySelectorAll('.code-autocomplete-item').forEach(el => {
        el.addEventListener('mousedown', (e) => {
          e.preventDefault();
          this.selectedIndex = parseInt(el.dataset.index, 10);
          this.applySelection();
        });
      });
    }

    onKeyDown(e) {
      if (!this.isVisible) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        this.selectedIndex = (this.selectedIndex + 1) % this.suggestions.length;
        this.render();
        this.scrollSelectedIntoView();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        this.selectedIndex = (this.selectedIndex - 1 + this.suggestions.length) % this.suggestions.length;
        this.render();
        this.scrollSelectedIntoView();
      } else if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        this.applySelection();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.hide();
      }
    }

    scrollSelectedIntoView() {
      const selectedEl = this.popup?.querySelector(`[data-index="${this.selectedIndex}"]`);
      if (selectedEl) {
        selectedEl.scrollIntoView({ block: 'nearest' });
      }
    }

    applySelection() {
      if (!this.textarea || this.selectedIndex >= this.suggestions.length) return;
      const selected = this.suggestions[this.selectedIndex];
      if (!selected) return;

      const val = this.textarea.value;
      const caret = this.textarea.selectionStart;

      const before = val.slice(0, this.prefixStart);
      const after = val.slice(caret);

      const isCallable = selected.type === 'func' || selected.type === 'builtin';
      const hasParenAfter = after.trim().startsWith('(');
      const addParens = isCallable && !hasParenAfter;
      const replacement = selected.name + (addParens ? '()' : '');
      const newCaret = this.prefixStart + (addParens ? selected.name.length + 1 : replacement.length);

      this.textarea.value = before + replacement + after;
      this.textarea.setSelectionRange(newCaret, newCaret);

      if (typeof window.onCodeEditorInput === 'function') {
        window.onCodeEditorInput(this.textarea.value);
      }

      this.hide();
      this.textarea.focus();
    }

    show() {
      if (this.popup && !this.isVisible) {
        this.popup.style.display = 'block';
        this.isVisible = true;
      }
    }

    hide() {
      if (this.popup && this.isVisible) {
        this.popup.style.display = 'none';
        this.isVisible = false;
        this.suggestions = [];
      }
    }
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  window.BooCodeAutocomplete = new BooCodeAutocomplete();
})(window, document);
