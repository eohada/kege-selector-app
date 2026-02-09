
function showConfirmDialog(message, onConfirm, onCancel = null, options = {}) {
  const {
    title = 'Подтверждение',
    isDanger = false,
    confirmText = 'Да',
    cancelText = 'Отмена'
  } = options;

  const overlay = document.createElement('div');
  overlay.className = 'confirm-dialog-overlay';

  const dialog = document.createElement('div');
  dialog.className = `confirm-dialog ${isDanger ? 'danger' : ''}`;

  dialog.innerHTML = `
    <div class="confirm-dialog-header">${escapeHtml(title)}</div>
    <div class="confirm-dialog-message">${escapeHtml(message)}</div>
    <div class="confirm-dialog-actions">
      <button class="neo-button confirm-dialog-btn-cancel" data-action="cancel">${escapeHtml(cancelText)}</button>
      <button class="neo-button confirm-dialog-btn-confirm" data-action="confirm">${escapeHtml(confirmText)}</button>
    </div>
  `;

  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  function closeDialog() {
    overlay.classList.add('closing');
    setTimeout(() => {
      overlay.remove();
    }, 300);
  }

  const confirmBtn = dialog.querySelector('[data-action="confirm"]');
  const cancelBtn = dialog.querySelector('[data-action="cancel"]');

  confirmBtn.addEventListener('click', () => {
    closeDialog();
    if (onConfirm) onConfirm();
  });

  cancelBtn.addEventListener('click', () => {
    closeDialog();
    if (onCancel) onCancel();
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      closeDialog();
      if (onCancel) onCancel();
    }
  });

  const escapeHandler = (e) => {
    if (e.key === 'Escape') {
      document.removeEventListener('keydown', escapeHandler);
      closeDialog();
      if (onCancel) onCancel();
    }
  };
  document.addEventListener('keydown', escapeHandler);

  setTimeout(() => confirmBtn.focus(), 100);
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return text.replace(/[&<>"']/g, char => map[char]);
}

function confirmDialog(message, options = {}) {
  return new Promise((resolve) => {
    showConfirmDialog(
      message,
      () => resolve(true),
      () => resolve(false),
      options
    );
  });
}

document.addEventListener('DOMContentLoaded', () => {

  document.addEventListener('submit', (e) => {
    const submitBtn = e.submitter;
    if (!submitBtn) return;

    const onclickAttr = submitBtn.getAttribute('onclick');
    if (!onclickAttr || !onclickAttr.includes('confirm(')) return;

    const confirmMatch = onclickAttr.match(/confirm\s*\(\s*['"`]([^'"`]+)['"`]\s*\)/);
    if (!confirmMatch) return;

    e.preventDefault();
    const message = confirmMatch[1];
    const form = e.target;
    const isDanger = submitBtn.classList.contains('danger');

    showConfirmDialog(
      message,
      () => {

        submitBtn.removeAttribute('onclick');
        form.submit();
      },
      null,
      {
        title: isDanger ? 'Подтверждение' : 'Подтверждение',
        isDanger: isDanger,
        confirmText: isDanger ? 'Удалить' : 'Продолжить',
        cancelText: 'Отмена'
      }
    );
  }, true);

});