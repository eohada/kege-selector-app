(() => {
  const match = window.location.pathname.match(/^\/guest\/s\/([^/]+)\/work$/);
  if (!match || typeof window.guestJson !== 'function') return;

  window.guestJson(`/guest/s/${encodeURIComponent(match[1])}/api/state`).then((state) => {
    if (!state.session?.timed || !state.session.deadline) return;
    const host = document.querySelector('.guest-hero');
    if (!host) return;
    const badge = document.createElement('span');
    badge.className = 'pill';
    badge.setAttribute('role', 'status');
    host.appendChild(badge);
    const offset = Date.parse(state.session.server_now) - Date.now();
    const deadline = Date.parse(state.session.deadline);
    const render = () => {
      const seconds = Math.max(0, Math.floor((deadline - (Date.now() + offset)) / 1000));
      badge.textContent = seconds
        ? `Осталось: ${Math.floor(seconds / 60)} мин ${seconds % 60} сек`
        : 'Время истекло — работа отправляется';
      if (!seconds) window.clearInterval(timer);
    };
    render();
    const timer = window.setInterval(render, 1000);
  }).catch(() => {});
})();
