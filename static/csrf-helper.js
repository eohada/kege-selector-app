

window.CsrfFormHelper = window.CsrfFormHelper || class CsrfFormHelper {
    constructor() { 
        this.token = this.getToken(); 
    } 

    getToken() { 
        const bodyToken = document.body ? document.body.dataset.csrfToken : null; 
        if (bodyToken) { 
            return bodyToken; 
        } 
        const metaTag = document.querySelector('meta[name="csrf-token"]'); 
        if (metaTag) { 
            return metaTag.getAttribute('content'); 
        } 
        return ''; 
    } 

    ensureFormToken(form) { 
        if (!form || form.tagName !== 'FORM') { 
            return; 
        } 
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') { 
            return; 
        } 
        if (form.querySelector('input[name="csrf_token"]')) { 
            return; 
        } 
        const hiddenInput = document.createElement('input'); 
        hiddenInput.type = 'hidden'; 
        hiddenInput.name = 'csrf_token'; 
        hiddenInput.value = this.token || ''; 
        form.appendChild(hiddenInput); 
    } 

    processAllForms() { 
        if (!this.token) { 
            console.warn('CSRF token not found for auto-injection'); 
            return; 
        } 
        const forms = document.querySelectorAll('form'); 
        forms.forEach(form => this.ensureFormToken(form)); 
    } 
} 

window.initCsrfHelper = function(root) {
    const helper = new window.CsrfFormHelper();
    if (root && typeof root.querySelectorAll === 'function') {
        const forms = root.querySelectorAll('form');
        forms.forEach(form => helper.ensureFormToken(form));
    } else {
        helper.processAllForms();
    }
};

document.addEventListener('DOMContentLoaded', function() { 
    window.initCsrfHelper();
}); 
