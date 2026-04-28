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
            if (data.effective) {
              var eff = document.querySelector('meta[name="user-timezone-effective"]');
              if (eff) eff.setAttribute('content', data.effective);
            }
          }
        })
        .catch(function () {});
    } catch (e) {}
  });
})();
