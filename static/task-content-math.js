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
      strict: function (errorCode) {
        return errorCode === 'unicodeTextInMathMode' ? 'ignore' : 'warn';
      },
      preProcess: function (mathText) {
        return (mathText || '').replace(/\u00a0/g, ' ');
      },
      // Без 'code': на kompege формулы часто в <code>\( … \)</code> — иначе auto-render их полностью пропускает.
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre'],
      ignoredClasses: ['katex'],
    };
  }

  function normalizeNbsp(node) {
    if (!node) return;
    if (node.nodeType === 3 /* Node.TEXT_NODE */) {
      if (node.nodeValue && node.nodeValue.indexOf('\u00a0') !== -1) {
        node.nodeValue = node.nodeValue.replace(/\u00a0/g, ' ');
      }
    } else if (node.nodeType === 1 /* Node.ELEMENT_NODE */ && !['SCRIPT', 'STYLE'].includes(node.nodeName)) {
      for (var i = 0; i < node.childNodes.length; i++) {
        normalizeNbsp(node.childNodes[i]);
      }
    }
  }

  function tryRender(root) {
    if (!root || typeof global.renderMathInElement !== 'function') {
      return false;
    }
    try {
      normalizeNbsp(root);
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
