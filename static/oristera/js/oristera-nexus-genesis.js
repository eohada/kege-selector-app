/** Interactions for the Student Nexus Genesis surface. */
(function() {
  'use strict';

  const menuId = 'ori-genesis-menu';
  const menuButtonId = 'ori-genesis-menu-toggle';
  const dialogId = 'ori-genesis-space-dialog';
  let lastDialogTrigger = null;

  function getMenuParts() {
    return {
      button: document.getElementById(menuButtonId),
      menu: document.getElementById(menuId)
    };
  }

  function closeMenu({ restoreFocus = false } = {}) {
    const { button, menu } = getMenuParts();
    if (!button || !menu) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', 'Открыть меню');
    if (restoreFocus) button.focus();
  }

  function openMenu() {
    const { button, menu } = getMenuParts();
    if (!button || !menu) return;
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-label', 'Закрыть меню');
    menu.querySelector('a, button')?.focus();
  }

  function openSpaceDialog(trigger) {
    const dialog = document.getElementById(dialogId);
    if (!dialog) return;
    closeMenu();
    lastDialogTrigger = trigger;
    if (typeof dialog.showModal === 'function') {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    dialog.querySelector('.ori-genesis-dialog-close')?.focus();
  }

  document.addEventListener('click', event => {
    const menuButton = event.target.closest(`#${menuButtonId}`);
    if (menuButton) {
      const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
      if (isOpen) closeMenu();
      else openMenu();
      return;
    }

    const dialogTrigger = event.target.closest('[data-open-space-dialog]');
    if (dialogTrigger) {
      event.preventDefault();
      openSpaceDialog(dialogTrigger);
      return;
    }

    const { menu, button } = getMenuParts();
    if (menu && !menu.hidden && !menu.contains(event.target) && !button?.contains(event.target)) closeMenu();
    if (event.target.closest(`#${menuId} a`)) closeMenu();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && getMenuParts().button?.getAttribute('aria-expanded') === 'true') {
      closeMenu({ restoreFocus: true });
    }
  });

  document.addEventListener('click', event => {
    const dialog = document.getElementById(dialogId);
    if (!dialog?.open || event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    const clickedInside = event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
    if (!clickedInside) dialog.close();
  });

  document.addEventListener('close', event => {
    if (event.target.id !== dialogId) return;
    if (lastDialogTrigger?.isConnected) lastDialogTrigger.focus();
    lastDialogTrigger = null;
  }, true);

  window.addEventListener('ori:space-entered', () => {
    closeMenu();
    lastDialogTrigger = null;
  });
})();
