(function () {
  function metaContent(name) {
    var m = document.querySelector('meta[name="' + name + '"]');
    return m && m.content ? String(m.content).trim() : '';
  }
  document.addEventListener('DOMContentLoaded', function () {
    var mode = metaContent('user-timezone-mode');
    if (mode !== 'auto') return;
    try {
      if (sessionStorage.getItem('boo_tz_reported') === '1') return;
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!tz) return;
      var token = metaContent('csrf-token');
      fetch('/api/me/timezone', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': token || '',
        },
        body: JSON.stringify({ browser_iana: tz }),
      })
        .then(function (r) {
          return r.json().catch(function () {
            return {};
          });
        })
        .then(function (data) {
          if (data && data.success) {
            sessionStorage.setItem('boo_tz_reported', '1');
            var previousEffective = metaContent('user-timezone-effective');
            if (data.effective) {
              var eff = document.querySelector('meta[name="user-timezone-effective"]');
              if (eff) eff.setAttribute('content', data.effective);
            }
            // Первая отрисовка могла быть в fallback-поясе. Обновляем её один раз,
            // чтобы server-rendered даты сразу соответствовали времени устройства.
            if (data.effective && data.effective !== previousEffective && !sessionStorage.getItem('boo_tz_reloaded')) {
              sessionStorage.setItem('boo_tz_reloaded', '1');
              window.location.reload();
            }
          }
        })
        .catch(function () {});
    } catch (e) {}
  });
})();
