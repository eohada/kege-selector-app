(() => {
  const form = document.getElementById('qr-review-form');
  document.addEventListener('keydown', (event) => {
    if (event.altKey && event.key === 'ArrowRight') {
      const next = document.getElementById('qr-next');
      if (next) { event.preventDefault(); next.click(); }
    } else if (event.altKey && event.key === 'ArrowLeft') {
      const previous = document.getElementById('qr-prev');
      if (previous) { event.preventDefault(); previous.click(); }
    } else if (form && (event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault(); form.requestSubmit();
    } else if (form && !event.altKey && !event.ctrlKey && !event.metaKey && ['1', '2', '3'].includes(event.key)) {
      const group = document.activeElement?.closest('.qr-rating');
      if (!group) return;
      const value = { '1': 'yes', '2': 'no', '3': 'na' }[event.key];
      const input = group.querySelector(`input[value="${value}"]`);
      if (input) { event.preventDefault(); input.checked = true; input.focus(); }
    }
  });
})();
