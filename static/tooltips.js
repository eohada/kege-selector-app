// Система tooltips для подсказок

class TooltipManager {
    constructor() {
        this.tooltips = new Map();
        this.init();
    }
    
    init() {
        // Инициализируем tooltips для элементов с атрибутом data-tooltip
        document.addEventListener('DOMContentLoaded', () => {
            this.initTooltips();
        });
        
        // Также инициализируем для динамически добавленных элементов
        const observer = new MutationObserver(() => {
            this.initTooltips();
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
    
    initTooltips() {
        const elements = document.querySelectorAll('[data-tooltip]');
        elements.forEach(element => {
            if (!this.tooltips.has(element)) {
                this.createTooltip(element);
            }
        });
    }
    
    createTooltip(element) {
        const text = element.getAttribute('data-tooltip');
        const position = element.getAttribute('data-tooltip-position') || 'top';
        
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.textContent = text;
        tooltip.setAttribute('role', 'tooltip');
        
        // Показываем tooltip при наведении
        element.addEventListener('mouseenter', () => {
            this.showTooltip(element, tooltip, position);
        });
        
        element.addEventListener('mouseleave', () => {
            this.hideTooltip(tooltip);
        });
        
        element.addEventListener('focus', () => {
            this.showTooltip(element, tooltip, position);
        });
        
        element.addEventListener('blur', () => {
            this.hideTooltip(tooltip);
        });
        
        this.tooltips.set(element, tooltip);
    }
    
    showTooltip(element, tooltip, position) {
        document.body.appendChild(tooltip);
        
        const rect = element.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        
        let top, left;
        
        switch (position) {
            case 'top':
                top = rect.top - tooltipRect.height - 8;
                left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
                break;
            case 'bottom':
                top = rect.bottom + 8;
                left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
                break;
            case 'left':
                top = rect.top + (rect.height / 2) - (tooltipRect.height / 2);
                left = rect.left - tooltipRect.width - 8;
                break;
            case 'right':
                top = rect.top + (rect.height / 2) - (tooltipRect.height / 2);
                left = rect.right + 8;
                break;
        }
        
        // Корректируем позицию, чтобы tooltip не выходил за границы экрана
        const padding = 8;
        if (left < padding) left = padding;
        if (left + tooltipRect.width > window.innerWidth - padding) {
            left = window.innerWidth - tooltipRect.width - padding;
        }
        if (top < padding) top = padding;
        if (top + tooltipRect.height > window.innerHeight - padding) {
            top = window.innerHeight - tooltipRect.height - padding;
        }
        
        tooltip.style.top = `${top}px`;
        tooltip.style.left = `${left}px`;
        tooltip.classList.add('active');
    }
    
    hideTooltip(tooltip) {
        tooltip.classList.remove('active');
        setTimeout(() => {
            if (tooltip.parentElement) {
                tooltip.parentElement.removeChild(tooltip);
            }
        }, 200);
    }
}

// Инициализация
const tooltipManager = new TooltipManager();














