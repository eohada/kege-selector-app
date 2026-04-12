/**
 * Единый KaTeX auto-render для HTML заданий (поток генератора, динамическая подгрузка в уроке и т.д.).
 * Требует загруженные katex.js и contrib/auto-render.js (глобальные katex и renderMathInElement).
 */
(function (global) {
  'use strict';

  function getOpts() {
    return {
      // Без одиночного '$': непарный $ в тексте (валюта и т.д.) ломает auto-render и оставляет \\(...\\) сырым.
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\(', right: '\\)', display: false },
        { left: '\\[', right: '\\]', display: true },
      ],
      throwOnError: false,
      trust: true,
      // Без 'code': на kompege формулы часто в <code>\( … \)</code> — иначе auto-render их полностью пропускает.
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre'],
      ignoredClasses: ['katex'],
    };
  }

  function tryRender(root) {
    if (!root || typeof global.renderMathInElement !== 'function') {
      return false;
    }
    try {
      global.renderMathInElement(root, getOpts());
      return true;
    } catch (e) {
      return false;
    }
  }

  /**
   * Рендер формул внутри root; при отложенной загрузке KaTeX — несколько попыток.
   */
  function boostudyRenderTaskMath(root, attempts) {
    var left = typeof attempts === 'number' ? attempts : 35;
    if (!root) {
      return;
    }
    if (tryRender(root)) {
      return;
    }
    if (left <= 0) {
      return;
    }
    setTimeout(function () {
      boostudyRenderTaskMath(root, left - 1);
    }, 100);
  }

  global.boostudyGetTaskMathOpts = getOpts;
  global.boostudyRenderTaskMath = boostudyRenderTaskMath;
})(typeof window !== 'undefined' ? window : this);
