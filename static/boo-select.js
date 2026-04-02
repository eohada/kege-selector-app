/**
 * Единая инициализация выпадающих списков (Tom Select) в стиле платформы.
 */
(function () {
  'use strict';

  function buildTomSelectOptions(el) {
    var opts = {
      create: false,
      allowEmptyOption: true,
      dropdownParent: typeof document !== 'undefined' ? document.body : null,
    };

    if (!el.multiple) {
      opts.maxItems = 1;
      /* Не использовать controlInput: null — ломает открытие списка в части окружений.
         Вместо этого визуально прячем служебный input в CSS (.ts-wrapper.single .ts-control > input). */
      opts.onInitialize = function () {
        var inp = this.control_input;
        if (inp) {
          inp.setAttribute('readonly', 'readonly');
          inp.setAttribute('inputmode', 'none');
          inp.setAttribute('autocomplete', 'off');
        }
      };
    }

    opts.onDropdownOpen = function () {
      var w = this.wrapper || (this.control && this.control.closest && this.control.closest('.ts-wrapper'));
      if (w) w.classList.add('boo-select-open');
    };
    opts.onDropdownClose = function () {
      var w = this.wrapper || (this.control && this.control.closest && this.control.closest('.ts-wrapper'));
      if (w) w.classList.remove('boo-select-open');
    };
    return opts;
  }

  function shouldSkipSelect(el) {
    if (!el || el.tagName !== 'SELECT') return true;
    if (el.classList.contains('no-tomselect')) return true;
    if (el.closest && el.closest('.no-tomselect')) return true;
    if (el.multiple && el.size > 1) return true;
    if (el.classList.contains('hidden')) return true;
    if (el.hasAttribute('hidden')) return true;
    return false;
  }

  function initBooSelects(root) {
    if (typeof TomSelect === 'undefined') return;
    var scope = root && root.nodeType === 1 ? root : document;
    if (!scope || !scope.querySelectorAll) return;
    var nodes = scope.querySelectorAll('select');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (shouldSkipSelect(el)) continue;
      if (el.tomselect) continue;
      try {
        new TomSelect(el, buildTomSelectOptions(el));
      } catch (err) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[boo-select] init failed', err);
        }
      }
    }
  }

  function syncBooSelect(el) {
    if (!el || !el.tomselect) return;
    try {
      if (typeof el.tomselect.sync === 'function') {
        el.tomselect.sync();
        return;
      }
    } catch (err0) {
      /* fall through */
    }
    try {
      el.tomselect.destroy();
    } catch (errD) {
      /* ignore */
    }
    try {
      if (typeof TomSelect !== 'undefined' && !shouldSkipSelect(el)) {
        new TomSelect(el, buildTomSelectOptions(el));
      }
    } catch (err1) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[boo-select] sync failed', err1);
      }
    }
  }

  window.initBooSelects = initBooSelects;
  window.syncBooSelect = syncBooSelect;

  function boot() {
    initBooSelects(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (typeof htmx !== 'undefined' && typeof htmx.onLoad === 'function') {
      htmx.onLoad(function (elt) {
        initBooSelects(elt && elt.nodeType === 1 ? elt : document);
      });
    }
  });

  window.addEventListener('load', function () {
    initBooSelects(document);
  });
})();
