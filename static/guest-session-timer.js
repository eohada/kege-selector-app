(() => {
  const match = window.location.pathname.match(/^\/guest\/s\/([^/]+)\/work$/);
  if (!match || typeof window.guestJson !== 'function') return;

  window.guestJson(`/guest/s/${encodeURIComponent(match[1])}/api/state`).then((state) => {
    if (!state.session?.timed || !state.session.deadline) return;
    const host = document.querySelector('.guest-workspace-header');
    if (!host) return;
    const badge = document.createElement('div');
    badge.className = 'guest-timer';
    badge.setAttribute('role', 'status');
    host.appendChild(badge);
    const offset = Date.parse(state.session.server_now) - Date.now();
    const deadline = Date.parse(state.session.deadline);
    const render = () => {
      const seconds = Math.max(0, Math.floor((deadline - (Date.now() + offset)) / 1000));
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      const remainder = seconds % 60;
      badge.classList.toggle('is-warning', seconds > 0 && seconds <= 15 * 60);
      badge.classList.toggle('is-expired', seconds === 0);
      badge.innerHTML = seconds
        ? `<small>Осталось времени</small><strong>${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}</strong>`
        : '<small>Время истекло</small><strong>Работа отправляется</strong>';
      if (!seconds) window.clearInterval(timer);
    };
    render();
    const timer = window.setInterval(render, 1000);
  }).catch(() => {});
})();
