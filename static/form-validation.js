

class FormValidator {
    constructor(form) {
        this.form = form;
        this.errors = {};
        this.init();
    }
    
    init() {

        const fields = this.form.querySelectorAll('input, textarea, select');
        fields.forEach(field => {

            field.addEventListener('blur', () => this.validateField(field));

            field.addEventListener('input', () => this.clearFieldError(field));
        });

        this.form.addEventListener('submit', (e) => {
            if (!this.validateAll()) {
                e.preventDefault();
                this.showFirstError();
            }
        });
    }
    
    validateField(field) {
        const fieldName = field.name;
        const value = field.value.trim();
        const rules = this.getFieldRules(field);

        this.clearFieldError(field);

        for (const rule of rules) {
            const error = this.checkRule(value, rule, field);
            if (error) {
                this.setFieldError(field, error);
                return false;
            }
        }
        
        return true;
    }
    
    getFieldRules(field) {
        const rules = [];

        if (field.hasAttribute('required') || field.classList.contains('required')) {
            rules.push({type: 'required'});
        }

        if (field.hasAttribute('minlength')) {
            rules.push({
                type: 'minlength',
                value: parseInt(field.getAttribute('minlength'))
            });
        }

        if (field.hasAttribute('maxlength')) {
            rules.push({
                type: 'maxlength',
                value: parseInt(field.getAttribute('maxlength'))
            });
        }

        if (field.hasAttribute('pattern')) {
            rules.push({
                type: 'pattern',
                value: field.getAttribute('pattern')
            });
        }

        if (field.type === 'email') {
            rules.push({type: 'email'});
        }

        if (field.type === 'number') {
            rules.push({type: 'number'});
            if (field.hasAttribute('min')) {
                rules.push({
                    type: 'min',
                    value: parseFloat(field.getAttribute('min'))
                });
            }
            if (field.hasAttribute('max')) {
                rules.push({
                    type: 'max',
                    value: parseFloat(field.getAttribute('max'))
                });
            }
        }

        if (fieldName === 'name') {
            rules.push({type: 'minlength', value: 2});
        }
        
        if (fieldName === 'target_score') {
            rules.push({type: 'number'});
            rules.push({type: 'min', value: 0});
            rules.push({type: 'max', value: 100});
        }
        
        return rules;
    }
    
    checkRule(value, rule, field) {
        switch (rule.type) {
            case 'required':
                if (!value) {
                    return 'Это поле обязательно для заполнения';
                }
                break;
                
            case 'minlength':
                if (value.length < rule.value) {
                    return `Минимальная длина: ${rule.value} символов`;
                }
                break;
                
            case 'maxlength':
                if (value.length > rule.value) {
                    return `Максимальная длина: ${rule.value} символов`;
                }
                break;
                
            case 'pattern':
                const regex = new RegExp(rule.value);
                if (!regex.test(value)) {
                    return 'Неверный формат';
                }
                break;
                
            case 'email':
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (value && !emailRegex.test(value)) {
                    return 'Введите корректный email адрес';
                }
                break;
                
            case 'number':
                if (value && isNaN(value)) {
                    return 'Введите число';
                }
                break;
                
            case 'min':
                if (value && parseFloat(value) < rule.value) {
                    return `Минимальное значение: ${rule.value}`;
                }
                break;
                
            case 'max':
                if (value && parseFloat(value) > rule.value) {
                    return `Максимальное значение: ${rule.value}`;
                }
                break;
        }
        
        return null;
    }
    
    setFieldError(field, message) {
        field.classList.add('error');

        let errorElement = field.parentElement.querySelector('.field-error');
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.className = 'field-error';
            field.parentElement.appendChild(errorElement);
        }
        
        errorElement.textContent = message;
        this.errors[field.name] = message;
    }
    
    clearFieldError(field) {
        field.classList.remove('error');
        const errorElement = field.parentElement.querySelector('.field-error');
        if (errorElement) {
            errorElement.remove();
        }
        delete this.errors[field.name];
    }
    
    validateAll() {
        const fields = this.form.querySelectorAll('input, textarea, select');
        let isValid = true;
        
        fields.forEach(field => {
            if (!this.validateField(field)) {
                isValid = false;
            }
        });
        
        return isValid;
    }
    
    showFirstError() {
        const firstErrorField = this.form.querySelector('.error');
        if (firstErrorField) {
            firstErrorField.scrollIntoView({behavior: 'smooth', block: 'center'});
            firstErrorField.focus();
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        new FormValidator(form);
    });
});

