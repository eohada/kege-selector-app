

class ToastManager {
    constructor() {
        this.container = null; 
        this.init(); 
    }

    init() {
        
        if (!document.getElementById('toast-container')) {
            this.container = document.createElement('div'); 
            this.container.id = 'toast-container'; 
            this.container.className = 'toast-container'; 
            document.body.appendChild(this.container); 
        } else {
            this.container = document.getElementById('toast-container'); 
        }
    }

    show(message, type = 'info', duration = 4000) {
        
        const toast = document.createElement('div'); 
        toast.className = `toast toast-${type}`; 
        toast.setAttribute('role', 'alert'); 

        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };

        toast.innerHTML = `
            <div class="toast-content">
                <span class="toast-icon">${icons[type] || icons.info}</span>
                <span class="toast-message">${this.escapeHtml(message)}</span>
                <button class="toast-close" onclick="this.parentElement.parentElement.remove()" aria-label="Закрыть">×</button>
            </div>
        `;

        this.container.appendChild(toast); 

        setTimeout(() => toast.classList.add('show'), 10); 

        if (duration > 0) {
            setTimeout(() => {
                toast.classList.remove('show'); 
                setTimeout(() => toast.remove(), 300); 
            }, duration);
        }
        
        return toast; 
    }

    success(message, duration) {
        return this.show(message, 'success', duration); 
    }

    error(message, duration) {
        return this.show(message, 'error', duration); 
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration); 
    }

    info(message, duration) {
        return this.show(message, 'info', duration); 
    }

    escapeHtml(text) {
        
        const div = document.createElement('div'); 
        div.textContent = text; 
        return div.innerHTML; 
    }
}

const toast = new ToastManager(); 

if (typeof module !== 'undefined' && module.exports) {
    module.exports = ToastManager; 
}

