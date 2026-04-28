(() => {
  'use strict';

  if (window.__themeSwitcherLoaded) return;
  window.__themeSwitcherLoaded = true;

  const STORAGE_KEY = 'ui.themeMode';
  const THEMES = ['auto', 'dark', 'light'];

  function getStoredTheme() {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      return THEMES.includes(v) ? v : 'auto';
    } catch {
      return 'auto';
    }
  }

  function setStoredTheme(mode) {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // ignore
    }
  }

  function applyTheme(mode) {
    const root = document.documentElement;

    if (mode === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else if (mode === 'light') {
      root.setAttribute('data-theme', 'light');
    } else {
      root.removeAttribute('data-theme');
    }

    root.setAttribute('data-theme-mode', mode);
    try {
      window.dispatchEvent(new CustomEvent('boo:theme-changed', { detail: { mode: mode } }));
    } catch (e) {}
  }

  function updateToggles(mode) {
    document.querySelectorAll('[data-theme-toggle]').forEach((toggle) => {
      toggle.querySelectorAll('[data-theme-value]').forEach((btn) => {
        const v = btn.getAttribute('data-theme-value');
        const active = v === mode;
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    });
  }

  function initToggles() {
    document.querySelectorAll('[data-theme-toggle]').forEach((toggle) => {
      toggle.querySelectorAll('[data-theme-value]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const v = btn.getAttribute('data-theme-value') || 'auto';
          const mode = THEMES.includes(v) ? v : 'auto';
          setStoredTheme(mode);
          applyTheme(mode);
          updateToggles(mode);
        });
      });
    });
  }

  function boot() {
    const mode = getStoredTheme();
    applyTheme(mode);
    updateToggles(mode);
    initToggles();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();

