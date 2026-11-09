(() => {
  'use strict';

  const KATEX_OPTIONS = {
    throwOnError: false,
    strict: (errorCode) => errorCode === 'unicodeTextInMathMode' ? 'ignore' : 'error',
    trust: false,
    maxSize: 50,
    maxExpand: 500,
    output: 'htmlAndMathml',
  };

  function renderMath(root = document) {
    if (!window.katex) return;
    const nodes = [];
    if (root.matches?.('.theory-math-source')) nodes.push(root);
    nodes.push(...(root.querySelectorAll?.('.theory-math-source') || []));
    nodes.forEach(node => {
      if (node.dataset.katexRendered === 'true') return;
      const source = node.textContent || '';
      const displayMode = node.dataset.mathMode === 'display';
      try {
        window.katex.render(source, node, {...KATEX_OPTIONS, displayMode, macros: {}});
        node.dataset.katexRendered = 'true';
        if (node.querySelector('.katex-error')) {
          node.classList.add('theory-math-invalid');
          node.dataset.mathError = 'true';
          if (node.closest('[data-theory-preview]')) {
            node.setAttribute('aria-label', 'Не удалось разобрать формулу. Исходная запись: ' + source);
          }
        }
      } catch (error) {
        node.textContent = source;
        node.classList.add('theory-math-invalid');
        node.dataset.katexRendered = 'true';
        node.dataset.mathError = 'true';
        if (node.closest('[data-theory-preview]')) {
          node.title = 'Ошибка формулы: ' + (error?.message || 'неизвестная ошибка');
        }
      }
    });

    const preview = root.closest?.('[data-theory-preview]') || (root.matches?.('[data-theory-preview]') ? root : null);
    if (preview) {
      const errors = preview.querySelectorAll('.theory-math-invalid').length;
      let notice = preview.querySelector('[data-math-preview-errors]');
      if (errors && !notice) {
        notice = document.createElement('div');
        notice.dataset.mathPreviewErrors = 'true';
        notice.className = 'theory-math-preview-warning';
        notice.setAttribute('role', 'status');
        notice.textContent = `Формул с ошибкой: ${errors}. Проверьте TeX перед сохранением.`;
        preview.prepend(notice);
      } else if (!errors) {
        notice?.remove();
      } else if (notice) {
        notice.textContent = `Формул с ошибкой: ${errors}. Проверьте TeX перед сохранением.`;
      }
    }
  }

  function initializeMathFields(root = document) {
    root.querySelectorAll?.('math-field[data-interactive-math]').forEach(field => {
      if (field.dataset.mathFieldReady === 'true') return;
      field.dataset.mathFieldReady = 'true';
      field.setAttribute('virtual-keyboard-mode', 'onfocus');
      field.setAttribute('smart-fence', '');
      field.setAttribute('math-virtual-keyboard-policy', 'auto');
    });
  }

  function renderTextWithMath(text, target) {
    if (!target) return;
    target.replaceChildren();
    const source = String(text ?? '');
    const pattern = /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$[^\n$]+?(?<!\\)\$(?![\w])/g;
    let cursor = 0;
    for (const match of source.matchAll(pattern)) {
      const value = match[0];
      if (match.index > cursor) target.append(document.createTextNode(source.slice(cursor, match.index)));
      let body = value;
      let mode = 'inline';
      if (value.startsWith('$$')) { body = value.slice(2, -2); mode = 'display'; }
      else if (value.startsWith('\\[')) { body = value.slice(2, -2); mode = 'display'; }
      else if (value.startsWith('\\(')) body = value.slice(2, -2);
      else body = value.slice(1, -1);
      const formula = document.createElement('span');
      formula.className = 'theory-math-source';
      formula.dataset.mathMode = mode;
      formula.setAttribute('role', 'math');
      formula.textContent = body;
      target.append(formula);
      renderMath(formula);
      cursor = match.index + value.length;
    }
    if (cursor < source.length) target.append(document.createTextNode(source.slice(cursor)));
  }

  window.BooTheoryMath = {render: renderMath, initializeMathFields, renderText: renderTextWithMath};

  function initialize(root = document) {
    renderMath(root);
    initializeMathFields(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initialize(), {once: true});
  } else {
    initialize();
  }
  document.addEventListener('theory:content-rendered', event => initialize(event.detail?.root || document));
})();
