

class UndoManager {
    constructor() {
        this.history = [];
        this.maxHistory = 10;
        this.init();
    }
    
    init() {

        this.createUndoNotification();
    }
    
    createUndoNotification() {
        const container = document.createElement('div');
        container.id = 'undo-notification';
        container.className = 'undo-notification';
        document.body.appendChild(container);
    }
    
    addAction(action) {

        this.history.unshift(action);

        if (this.history.length > this.maxHistory) {
            this.history.pop();
        }

        this.showUndoNotification(action);
    }
    
    async undo() {
        if (this.history.length === 0) return;
        
        const action = this.history.shift();
        if (action.undo) {
            try {
                await action.undo();
                if (typeof toast !== 'undefined') {
                    toast.success('Действие отменено');
                }
            } catch (error) {
                console.error('Ошибка при отмене действия:', error);
                if (typeof toast !== 'undefined') {
                    toast.error('Не удалось отменить действие');
                }
            }
        }
    }
    
    showUndoNotification(action) {
        const container = document.getElementById('undo-notification');
        if (!container) return;
        
        const notification = document.createElement('div');
        notification.className = 'undo-notification-item';
        notification.innerHTML = `
            <span>${action.message || 'Действие выполнено'}</span>
            <button class="undo-btn" onclick="undoManager.undo()">Отменить</button>
        `;
        
        container.appendChild(notification);

        setTimeout(() => {
            if (notification.parentElement) {
                notification.style.opacity = '0';
                setTimeout(() => {
                    notification.remove();
                }, 300);
            }
        }, 5000);
    }
}

const undoManager = new UndoManager();

function createDeleteUndoAction(entityType, entityId, entityData, restoreCallback) {
    return {
        type: 'delete',
        entity: entityType,
        data: entityData,
        message: `${entityType === 'student' ? 'Ученик' : 'Урок'} удален`,
        undo: async () => {
            await restoreCallback(entityId, entityData);
        }
    };
}

