(() => {
  const dashboard = document.querySelector('[data-s33-view="dashboard"]');
  if (!dashboard) return;

  const modal = dashboard.querySelector('[data-checklist-modal]');
  const trigger = dashboard.querySelector('[data-checklist-open]');
  const closeButtons = dashboard.querySelectorAll('[data-checklist-close]');
  const resetButton = dashboard.querySelector('[data-checklist-reset]');
  const checkboxes = [...dashboard.querySelectorAll('.s34-checklist-items input[type="checkbox"]')];
  const count = dashboard.querySelector('[data-checklist-count]');
  const progress = dashboard.querySelector('[data-checklist-bar]');

  if (!modal || !trigger || !count || !progress) return;

  function updateProgress() {
    const checked = checkboxes.filter((checkbox) => checkbox.checked).length;
    count.textContent = `${checked} из ${checkboxes.length} выполнено`;
    progress.style.width = `${checkboxes.length ? (checked / checkboxes.length) * 100 : 0}%`;
  }

  function closeModal() {
    modal.hidden = true;
    trigger.focus();
  }

  trigger.addEventListener('click', () => {
    modal.hidden = false;
    modal.querySelector('input[type="checkbox"]')?.focus();
  });

  closeButtons.forEach((button) => button.addEventListener('click', closeModal));
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  modal.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeModal();
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = [...modal.querySelectorAll('button, input[type="checkbox"]')];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
  checkboxes.forEach((checkbox) => checkbox.addEventListener('change', updateProgress));
  resetButton?.addEventListener('click', () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = false; });
    updateProgress();
  });

  updateProgress();
})();
