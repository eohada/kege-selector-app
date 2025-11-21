

class CsrfFormHelper { 
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

document.addEventListener('DOMContentLoaded', function() { 
    const helper = new CsrfFormHelper(); 
    helper.processAllForms(); 
}); 

