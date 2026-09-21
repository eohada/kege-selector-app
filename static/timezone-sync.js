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

      // Если эффективный пояс уже совпадает с браузерным, повторно не отправляем
      if (effectiveTz && effectiveTz === browserTz) return;

      // Проверяем сессионный кэш, чтобы не слать запрос на каждый переход по страницам
      const storageKey = 'boostudy_synced_tz';
      try {
        if (sessionStorage.getItem(storageKey) === browserTz) return;
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
