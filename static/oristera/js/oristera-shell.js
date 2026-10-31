/**
 * PROJECT ORISTERA — SHELL CONTROLLER
 * Spatial HUD, Keyboard Navigation & Continuum State
 */
(function() {
  'use strict';

  class OristeraShell {
    constructor() {
      this.init();
    }

    init() {
      this.bindKeyboardShortcuts();
      this.bindModeToggle();
      this.syncContinuumState();
    }

    /**
     * Быстрые пространственные переходы с клавиатуры (Alt + 1..5)
     */
    bindKeyboardShortcuts() {
      document.addEventListener('keydown', (e) => {
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
          const map = {
            '1': '/oristera/nexus',
            '2': '/oristera/atlas',
            '3': '/oristera/practice',
            '4': '/oristera/lessons',
            '5': '/oristera/teacher'
          };
          const target = map[e.key];
          if (target) {
            e.preventDefault();
            if (window.OristeraMotion && window.OristeraMotion.teleportTo) {
              window.OristeraMotion.teleportTo(target);
            } else {
              window.location.href = target;
            }
          }
        }
      });
    }

    /**
     * Переключатель режимов
     */
    bindModeToggle() {
      const toggleBtn = document.getElementById('ori-mode-toggle-btn');
      if (!toggleBtn) return;

      toggleBtn.addEventListener('click', () => {
        document.body.style.transition = 'opacity 180ms ease';
        document.body.style.opacity = '0.5';
      });
    }

    /**
     * Запрос актуального состояния Continuum
     */
    syncContinuumState() {
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
          fetch('/oristera/api/state')
            .then(res => res.json())
            .then(data => {
              if (data && data.ok) {
                // Continuum state synced
              }
            })
            .catch(() => {});
        }
      });
    }
  }

  window.OristeraShell = new OristeraShell();
})();
