// Универсальная функция для модальных окон подтверждения
function showConfirmModal(options) {
    const {
        title = 'Подтверждение',
        message = 'Вы уверены?',
        confirmText = 'Подтвердить',
        cancelText = 'Отмена',
        confirmClass = 'danger',
        onConfirm = () => {},
        onCancel = () => {}
    } = options;

    // Создаем модальное окно, если его еще нет
    let modal = document.getElementById('confirm-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'confirm-modal';
        modal.className = 'confirm-modal';
        modal.innerHTML = `
            <div class="confirm-modal-content">
                <div class="confirm-modal-title"></div>
                <div class="confirm-modal-message"></div>
                <div class="confirm-modal-actions">
                    <button class="neo-button ghost confirm-cancel-btn"></button>
                    <button class="neo-button confirm-confirm-btn"></button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    // Заполняем содержимое
    const titleEl = modal.querySelector('.confirm-modal-title');
    const messageEl = modal.querySelector('.confirm-modal-message');
    const confirmBtn = modal.querySelector('.confirm-confirm-btn');
    const cancelBtn = modal.querySelector('.confirm-cancel-btn');

    titleEl.textContent = title;
    messageEl.textContent = message;
    confirmBtn.textContent = confirmText;
    cancelBtn.textContent = cancelText;

    // Устанавливаем класс для кнопки подтверждения
    confirmBtn.className = `neo-button ${confirmClass}`;

    // Очищаем предыдущие обработчики
    const newConfirmBtn = confirmBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

    // Добавляем обработчики
    newConfirmBtn.addEventListener('click', () => {
        modal.classList.remove('active');
        onConfirm();
    });

    newCancelBtn.addEventListener('click', () => {
        modal.classList.remove('active');
        onCancel();
    });

    // Закрытие по клику на фон
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
            onCancel();
        }
    });

    // Закрытие по Escape
    const escapeHandler = (e) => {
        if (e.key === 'Escape') {
            modal.classList.remove('active');
            onCancel();
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);

    // Показываем модальное окно
    modal.classList.add('active');
}

// Функция для подтверждения формы
function confirmFormSubmit(form, options) {
    // Проверяем, не добавлен ли уже обработчик
    if (form.dataset.confirmAttached === 'true') {
        return;
    }
    form.dataset.confirmAttached = 'true';
    
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        e.stopPropagation();
        showConfirmModal({
            ...options,
            onConfirm: () => {
                // Удаляем обработчик, чтобы форма могла отправиться обычным способом
                form.dataset.confirmAttached = 'false';
                // Отправляем форму напрямую
                form.submit();
            }
        });
    });
}

// Инициализация подтверждений при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    // Подтверждение удаления ученика
    const studentDeleteForms = document.querySelectorAll('form[action*="/student/"][action*="/delete"]');
    studentDeleteForms.forEach(form => {
        confirmFormSubmit(form, {
            title: 'Удалить ученика?',
            message: 'Это действие нельзя отменить! Все данные ученика, включая уроки и домашние задания, будут удалены навсегда.',
            confirmText: 'Удалить',
            cancelText: 'Отмена',
            confirmClass: 'danger'
        });
    });

    // Подтверждение удаления урока
    const lessonDeleteForms = document.querySelectorAll('form[action*="/lesson/"][action*="/delete"]');
    lessonDeleteForms.forEach(form => {
        confirmFormSubmit(form, {
            title: 'Удалить урок?',
            message: 'Это действие нельзя отменить! Все данные урока, включая домашние задания, будут удалены навсегда.',
            confirmText: 'Удалить',
            cancelText: 'Отмена',
            confirmClass: 'danger'
        });
    });

    // Подтверждение удаления задания из ДЗ
    const taskDeleteForms = document.querySelectorAll('form[id^="delete-form-"]');
    taskDeleteForms.forEach(form => {
        confirmFormSubmit(form, {
            title: 'Удалить задание?',
            message: 'Задание будет удалено из домашнего задания. Это действие можно отменить, добавив задание заново.',
            confirmText: 'Удалить',
            cancelText: 'Отмена',
            confirmClass: 'danger'
        });
    });

    // Подтверждение сброса истории
    const resetForms = document.querySelectorAll('form[action*="reset"]');
    resetForms.forEach(form => {
        const resetType = form.querySelector('[name="reset_type"]')?.value || 'unknown';
        const taskType = form.querySelector('[name="task_type_reset"]')?.value || 'all';
        
        let message = 'Вы уверены, что хотите сбросить историю? ';
        if (resetType === 'all') {
            message += 'Вся история использования заданий будет удалена.';
        } else if (resetType === 'accepted') {
            message += 'История принятых заданий будет удалена.';
        } else if (resetType === 'skipped') {
            message += 'История пропущенных заданий будет удалена.';
        } else if (resetType === 'blacklist') {
            message += 'Черный список будет очищен.';
        }

        confirmFormSubmit(form, {
            title: 'Сбросить историю?',
            message: message,
            confirmText: 'Сбросить',
            cancelText: 'Отмена',
            confirmClass: 'danger'
        });
    });

    // Подтверждение архивирования ученика
    const archiveForms = document.querySelectorAll('form[action*="/archive"]');
    archiveForms.forEach(form => {
        confirmFormSubmit(form, {
            title: 'Архивировать ученика?',
            message: 'Ученик будет перемещен в архив. Его можно будет восстановить позже.',
            confirmText: 'В архив',
            cancelText: 'Отмена',
            confirmClass: 'outline'
        });
    });

    // Обработка форм с классом confirm-delete-form
    const confirmDeleteForms = document.querySelectorAll('form.confirm-delete-form');
    confirmDeleteForms.forEach(form => {
        // Пропускаем формы с data-no-confirm
        if (form.hasAttribute('data-no-confirm')) {
            return;
        }
        
        // Определяем тип действия по action формы
        const action = form.getAttribute('action') || '';
        let title = 'Подтверждение';
        let message = 'Вы уверены?';
        let confirmText = 'Подтвердить';
        let confirmClass = 'danger';

        if (action.includes('clear_all')) {
            title = '⚠️ Удалить всех тестировщиков?';
            message = 'Это удалит ВСЕХ тестировщиков и ВСЕ их логи! Это действие нельзя отменить.';
            confirmText = 'Удалить всех';
        } else if (action.includes('/tester/') && action.includes('/delete')) {
            title = 'Удалить тестировщика?';
            message = 'Удалить тестировщика и все его логи? Это действие нельзя отменить.';
            confirmText = 'Удалить';
        } else if (action.includes('family-tie') && action.includes('delete')) {
            title = 'Удалить семейную связь?';
            message = 'Связь между родителем и учеником будет удалена. Это действие нельзя отменить.';
            confirmText = 'Удалить';
        } else if (action.includes('enrollment') && action.includes('delete')) {
            title = 'Удалить учебный контракт?';
            message = 'Контракт между преподавателем и учеником будет удален. Это действие нельзя отменить.';
            confirmText = 'Удалить';
        }

        confirmFormSubmit(form, {
            title: title,
            message: message,
            confirmText: confirmText,
            cancelText: 'Отмена',
            confirmClass: confirmClass
        });
    });
    
    // Подтверждение для массовых операций с заданиями
    const bulkActionForms = document.querySelectorAll('form[data-bulk-action]');
    bulkActionForms.forEach(form => {
        const actionType = form.getAttribute('data-bulk-action');
        let title = 'Подтверждение массового действия';
        let message = 'Это действие будет применено ко всем выбранным элементам.';
        let confirmText = 'Применить';
        let confirmClass = 'accent';
        
        if (actionType === 'accept') {
            title = 'Принять все выбранные задания?';
            message = 'Все выбранные задания будут приняты и больше не будут показываться.';
            confirmText = 'Принять все';
        } else if (actionType === 'skip') {
            title = 'Пропустить все выбранные задания?';
            message = 'Все выбранные задания будут пропущены и могут быть возвращены позже.';
            confirmText = 'Пропустить все';
        } else if (actionType === 'blacklist') {
            title = 'Добавить в черный список?';
            message = 'Все выбранные задания будут добавлены в черный список и никогда не будут показываться.';
            confirmText = 'В черный список';
            confirmClass = 'danger';
        }
        
        confirmFormSubmit(form, {
            title: title,
            message: message,
            confirmText: confirmText,
            cancelText: 'Отмена',
            confirmClass: confirmClass
        });
    });
});
