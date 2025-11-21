

class AjaxUtils {
    constructor() {
        this.csrfToken = this.getCSRFToken(); 
    }

    getCSRFToken() {
        
        const metaTag = document.querySelector('meta[name="csrf-token"]'); 
        if (metaTag) {
            return metaTag.getAttribute('content'); 
        }
        
        const csrfInput = document.querySelector('input[name="csrf_token"]'); 
        if (csrfInput) {
            return csrfInput.value; 
        }
        
        return null; 
    }

    async request(url, options = {}) {
        
        const defaultOptions = {
            method: 'GET', 
            headers: {
                'Content-Type': 'application/json', 
                'X-Requested-With': 'XMLHttpRequest' 
            },
            credentials: 'same-origin' 
        };

        if (this.csrfToken && (options.method === 'POST' || options.method === 'PUT' || options.method === 'DELETE')) {
            defaultOptions.headers['X-CSRFToken'] = this.csrfToken; 
        }

        const finalOptions = { ...defaultOptions, ...options }; 

        if (finalOptions.body && typeof finalOptions.body === 'object' && !(finalOptions.body instanceof FormData)) {
            finalOptions.body = JSON.stringify(finalOptions.body); 
        }

        try {
            const response = await fetch(url, finalOptions); 

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`); 
            }

            const contentType = response.headers.get('content-type'); 
            if (contentType && contentType.includes('application/json')) {
                return await response.json(); 
            }
            
            return await response.text(); 
        } catch (error) {
            console.error('AJAX request failed:', error); 
            throw error; 
        }
    }

    async submitForm(formElement, options = {}) {
        
        const formData = new FormData(formElement); 

        if (this.csrfToken && !formData.has('csrf_token')) {
            formData.append('csrf_token', this.csrfToken); 
        }

        const url = formElement.action || window.location.href; 
        const method = formElement.method || 'POST'; 

        return this.request(url, {
            method: method, 
            body: formData, 
            headers: {
                'X-Requested-With': 'XMLHttpRequest' 
                
            },
            ...options 
        });
    }

    async post(url, data, options = {}) {
        
        return this.request(url, {
            method: 'POST', 
            body: data, 
            ...options 
        });
    }

    async get(url, options = {}) {
        
        return this.request(url, {
            method: 'GET', 
            ...options 
        });
    }

    async delete(url, options = {}) {
        
        return this.request(url, {
            method: 'DELETE', 
            ...options 
        });
    }

    async put(url, data, options = {}) {
        
        return this.request(url, {
            method: 'PUT', 
            body: data, 
            ...options 
        });
    }
}

const ajax = new AjaxUtils(); 

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AjaxUtils; 
}

