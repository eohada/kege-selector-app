/**
 * Показать красивое модальное окно подтверждения вместо стандартного confirm()
 * @param {string} message - Сообщение для пользователя
 * @param {Function} onConfirm - Callback при нажатии "Да"
 * @param {Function} onCancel - Callback при нажатии "Нет" (опционально)
 * @param {Object} options - Опции {title, isDanger, confirmText, cancelText}
 */
function showConfirmDialog(message, onConfirm, onCancel = null, options = {}) {
  const {
    title = 'Подтверждение',
    isDanger = false,
    confirmText = 'Да',
    cancelText = 'Отмена'
  } = options;

  // Создаем элементы диалога
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

  // Функция для закрытия диалога
  function closeDialog() {
    overlay.classList.add('closing');
    setTimeout(() => {
      overlay.remove();
    }, 300);
  }

  // Обработчики кнопок
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

  // Закрытие при клике на overlay
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      closeDialog();
      if (onCancel) onCancel();
    }
  });

  // Поддержка Escape для закрытия
  const escapeHandler = (e) => {
    if (e.key === 'Escape') {
      document.removeEventListener('keydown', escapeHandler);
      closeDialog();
      if (onCancel) onCancel();
    }
  };
  document.addEventListener('keydown', escapeHandler);

  // Фокус на кнопке подтверждения для удобства
  setTimeout(() => confirmBtn.focus(), 100);
}

/**
 * Экранировать HTML спецсимволы для безопасности
 */
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

/**
 * Promise-based версия для использования с async/await
 * @param {string} message
 * @param {Object} options
 * @returns {Promise<boolean>}
 */
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

/**
 * Перехватываем все onclick="return confirm(...)" на странице
 * и заменяем их на красивые модальные диалоги
 */
document.addEventListener('DOMContentLoaded', () => {
  // Перехватываем submit для форм с inline confirm в onclick
  document.addEventListener('submit', (e) => {
    const submitBtn = e.submitter;
    if (!submitBtn) return;

    // Проверяем если в onclick confirm
    const onclickAttr = submitBtn.getAttribute('onclick');
    if (!onclickAttr || !onclickAttr.includes('confirm(')) return;

    // Извлекаем текст подтверждения из confirm('text')
    const confirmMatch = onclickAttr.match(/confirm\s*\(\s*['"`]([^'"`]+)['"`]\s*\)/);
    if (!confirmMatch) return;

    e.preventDefault();
    const message = confirmMatch[1];
    const form = e.target;
    const isDanger = submitBtn.classList.contains('danger');

    showConfirmDialog(
      message,
      () => {
        // Удаляем onclick чтобы избежать двойного выполнения
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

  // Глобальный перехват window.confirm для скриптов
  const originalConfirm = window.confirm;
  window.confirm = function(message) {
    // Если вызов происходит с empty message, пропускаем
    if (!message || typeof message !== 'string') {
      return originalConfirm(message);
    }

    // Берем от 100-150 символов для заголовка
    const isDanger = message.toLowerCase().includes('удали');
    
    return new Promise((resolve) => {
      showConfirmDialog(
        message,
        () => resolve(true),
        () => resolve(false),
        {
          isDanger: isDanger,
          confirmText: isDanger ? 'Удалить' : 'Да',
          cancelText: 'Отмена'
        }
      );
    });
  };
});
