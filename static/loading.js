

class LoadingManager {
    constructor() {
        this.activeLoaders = new Set(); 
    }

    show(element, text = 'Загрузка...') {
        
        const loaderId = `loader-${Date.now()}-${Math.random()}`; 

        const loader = document.createElement('div'); 
        loader.className = 'loading-overlay'; 
        loader.dataset.loaderId = loaderId; 
        loader.innerHTML = `
            <div class="loading-spinner">
                <div class="spinner"></div>
                <div class="loading-text">${this.escapeHtml(text)}</div>
            </div>
        `;

        const targetElement = typeof element === 'string' 
            ? document.querySelector(element) 
            : element; 
        
        if (!targetElement) {
            console.warn('Loading target element not found'); 
            return null; 
        }

        const originalPosition = window.getComputedStyle(targetElement).position; 
        if (originalPosition === 'static') {
            targetElement.style.position = 'relative'; 
        }

        targetElement.dataset.originalPosition = originalPosition; 

        targetElement.appendChild(loader); 

        this.activeLoaders.add(loaderId); 

        setTimeout(() => loader.classList.add('show'), 10); 
        
        return loaderId; 
    }

    hide(loaderId) {
        
        if (!this.activeLoaders.has(loaderId)) {
            return; 
        }
        
        const loader = document.querySelector(`[data-loader-id="${loaderId}"]`); 
        if (!loader) {
            this.activeLoaders.delete(loaderId); 
            return; 
        }

        const targetElement = loader.parentElement; 
        if (targetElement && targetElement.dataset.originalPosition) {
            targetElement.style.position = targetElement.dataset.originalPosition; 
        }

        loader.classList.remove('show'); 

        setTimeout(() => {
            loader.remove(); 
            this.activeLoaders.delete(loaderId); 
        }, 300); 
    }

    async withLoading(element, asyncFunction, loadingText = 'Загрузка...') {
        
        const loaderId = this.show(element, loadingText); 
        
        try {
            const result = await asyncFunction(); 
            return result; 
        } finally {
            if (loaderId) {
                this.hide(loaderId); 
            }
        }
    }

    escapeHtml(text) {
        
        const div = document.createElement('div'); 
        div.textContent = text; 
        return div.innerHTML; 
    }
}

const loading = new LoadingManager(); 

if (typeof module !== 'undefined' && module.exports) {
    module.exports = LoadingManager; 
}

