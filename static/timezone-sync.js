/**
 * BooStudy Global Timezone Sync
 * Автоматически определяет IANA-пояс браузера и незаметно синхронизирует с сервером,
 * если у пользователя включён авторежим ('auto') и пояс изменился.
 */
(function() {
  'use strict';

  function syncBrowserTimezone() {
    try {
      if (!window.Intl || !Intl.DateTimeFormat) return;
      const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!browserTz) return;

      const metaEffective = document.querySelector('meta[name="user-timezone-effective"]');
      const metaMode = document.querySelector('meta[name="user-timezone-mode"]');
      const effectiveTz = metaEffective ? metaEffective.getAttribute('content') : '';
      const mode = metaMode ? metaMode.getAttribute('content') : 'auto';

      // Если установлен ручной режим и пояс уже задан, не переопределяем принудительно
      if (mode === 'manual') return;

      // В режиме auto гарантируем немедленное отражение локального пояса в интерфейсе
      if (effectiveTz !== browserTz) {
        if (metaEffective) metaEffective.setAttribute('content', browserTz);
        const headerName = document.getElementById('profile-tz-header-name');
        if (headerName) headerName.textContent = browserTz;
        if (window.BooTimezone && typeof window.BooTimezone.setViewerTz === 'function') {
          window.BooTimezone.setViewerTz(browserTz);
        } else {
          window.dispatchEvent(new CustomEvent('boostudy:timezone-changed', { detail: { timezone: browserTz } }));
        }
      }

      // Если эффективный пояс уже совпадает с браузерным и уже был синхронизирован, повторно не отправляем
      const storageKey = 'boostudy_synced_tz';
      try {
        if (effectiveTz === browserTz && sessionStorage.getItem(storageKey) === browserTz) return;
      } catch (e) {}

      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

      fetch('/api/me/timezone', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
          browser_iana: browserTz,
          timezone_mode: 'auto'
        })
      })
      .then(r => r.json())
      .then(data => {
        if (data && data.success) {
          try {
            sessionStorage.setItem(storageKey, browserTz);
          } catch (e) {}
          if (metaEffective) metaEffective.setAttribute('content', browserTz);
          const headerName = document.getElementById('profile-tz-header-name');
          if (headerName) headerName.textContent = browserTz;
        }
      })
      .catch(() => {});
    } catch (err) {
      // Молчаливый failover без прерывания рендеринга страницы
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncBrowserTimezone);
  } else {
    syncBrowserTimezone();
  }
})();
