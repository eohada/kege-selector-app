(() => {
  const match = window.location.pathname.match(/^\/guest\/s\/([^/]+)\/work$/);
  if (!match || typeof window.guestJson !== 'function') return;

  window.guestJson(`/guest/s/${encodeURIComponent(match[1])}/api/state`).then((state) => {
    if (!state.session?.timed || !state.session.deadline) return;
    const host = document.querySelector('[data-guest-timer-slot]');
    if (!host) return;
    const badge = document.createElement('div');
    badge.className = 'guest-timer';
    badge.setAttribute('role', 'status');
    host.appendChild(badge);
    const offset = Date.parse(state.session.server_now) - Date.now();
    const deadline = Date.parse(state.session.deadline);
    const totalSeconds = Math.max(1, Number(state.session.expected_duration_minutes || 0) * 60);
    const render = () => {
      const seconds = Math.max(0, Math.floor((deadline - (Date.now() + offset)) / 1000));
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      const remainder = seconds % 60;
      badge.classList.toggle('is-warning', seconds > 0 && seconds <= 15 * 60);
      badge.classList.toggle('is-expired', seconds === 0);
      badge.style.setProperty('--timer-progress', `${Math.max(0, Math.min(1, seconds / totalSeconds)) * 360}deg`);
      badge.innerHTML = seconds
        ? `<span class="guest-timer-dial" aria-hidden="true"></span><span class="guest-timer-copy"><small>${seconds <= 15 * 60 ? 'Меньше 15 минут' : 'До отправки'}</small><strong>${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}</strong><span>Черновики сохранены</span></span>`
        : '<span class="guest-timer-dial" aria-hidden="true"></span><span class="guest-timer-copy"><small>Время истекло</small><strong>Работа отправляется</strong><span>Не закрывайте страницу</span></span>';
      if (!seconds) {
        window.clearInterval(timer);
        window.guestJson(`/guest/s/${encodeURIComponent(match[1])}/submit`, {method: 'POST', body: JSON.stringify({force: true})})
          .then((result) => { window.location.replace(result.result_url); })
          .catch(() => { badge.innerHTML = '<span class="guest-timer-dial" aria-hidden="true"></span><span class="guest-timer-copy"><small>Время истекло</small><strong>Откройте результат</strong><span>Попробуйте обновить страницу</span></span>'; });
      }
    };
    render();
    const timer = window.setInterval(render, 1000);
  }).catch(() => {});
})();
