(() => {
  'use strict';

  if (window.__themeSwitcherLoaded) return;
  window.__themeSwitcherLoaded = true;

  const STORAGE_KEY = 'ui.themeMode';
  const THEMES = ['auto', 'dark', 'light'];

  let isBooting = true;

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

    const updateTheme = () => {
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
        document.dispatchEvent(new CustomEvent('boo:theme-changed', { detail: { mode: mode } }));
      } catch (e) {}
    };

    if (isBooting) {
      updateTheme();
      return;
    }

    // Try view transition API for hardware-accelerated crossfade
    if (document.startViewTransition) {
      root.setAttribute('data-theme-transitioning', 'true');
      const transition = document.startViewTransition(() => {
        updateTheme();
      });
      transition.finished.finally(() => {
        root.removeAttribute('data-theme-transitioning');
      });
    } else {
      root.classList.add('theme-transitioning');
      void root.offsetHeight; // Force reflow to register the transition before theme change
      updateTheme();
      setTimeout(() => {
        root.classList.remove('theme-transitioning');
      }, 350);
    }
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
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-theme-value]');
      if (!btn) return;
      const toggle = btn.closest('[data-theme-toggle]');
      if (!toggle) return;
      
      const v = btn.getAttribute('data-theme-value') || 'auto';
      const mode = THEMES.includes(v) ? v : 'auto';
      setStoredTheme(mode);
      applyTheme(mode);
      updateToggles(mode);
    });
  }

  window.updateThemeToggles = function() {
    updateToggles(getStoredTheme());
  };

  function boot() {
    const mode = getStoredTheme();
    applyTheme(mode);
    updateToggles(mode);
    initToggles();
    isBooting = false;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();

