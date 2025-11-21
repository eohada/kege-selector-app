

document.addEventListener('DOMContentLoaded', function() {
    
    initScheduleForms(); 
});

function initScheduleForms() {
    
    const createLessonForm = document.getElementById('createLessonForm'); 
    
    if (createLessonForm) {
        createLessonForm.addEventListener('submit', async function(e) {
            e.preventDefault(); 
            
            const formData = new FormData(createLessonForm); 

            const lessonMode = formData.get('lesson_mode') || 'single'; 
            const repeatCount = formData.get('repeat_count') ? parseInt(formData.get('repeat_count')) : null; 

            const csrfToken = formData.get('csrf_token') || 
                             document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                             document.body?.dataset?.csrfToken || ''; 

            if (!formData.get('csrf_token') && csrfToken) { 
                formData.append('csrf_token', csrfToken); 
            }

            const formDataToSend = formData; 

            const modal = createLessonForm.closest('.modal'); 
            const loadingText = lessonMode === 'recurring' && repeatCount ? 
                `Создание ${repeatCount} уроков...` : 'Создание урока...'; 
            const loaderId = modal ? loading.show(modal, loadingText) : null; 
            
            try {
                
                console.log('Отправка данных:', {
                    student_id: formData.get('student_id'),
                    lesson_date: formData.get('lesson_date'),
                    lesson_time: formData.get('lesson_time'),
                    lesson_mode: lessonMode,
                    repeat_count: repeatCount,
                    has_csrf: !!formData.get('csrf_token')
                }); 

                const headers = { 
                    'X-Requested-With': 'XMLHttpRequest' 
                }; 

                if (csrfToken) { 
                    headers['X-CSRFToken'] = csrfToken; 
                }

                const response = await fetch(createLessonForm.action, { 
                    method: 'POST', 
                    body: formDataToSend, 
                    headers: headers 
                }); 
                
                console.log('Ответ сервера:', response.status, response.statusText); 
                
                if (!response.ok) { 
                    
                    let errorText = `HTTP error! status: ${response.status}`; 
                    try { 
                        const errorData = await response.json(); 
                        if (errorData.error) { 
                            errorText = errorData.error; 
                        }
                    } catch (e) { 
                        const text = await response.text(); 
                        if (text) { 
                            errorText = text.substring(0, 200); 
                        }
                    }
                    throw new Error(errorText); 
                }

                const contentType = response.headers.get('content-type'); 
                let result; 
                
                if (contentType && contentType.includes('application/json')) { 
                    result = await response.json(); 
                    console.log('Результат:', result); 
                } else { 
                    
                    const text = await response.text(); 
                    console.error('Сервер вернул не JSON:', text.substring(0, 500)); 
                    throw new Error('Сервер вернул неожиданный формат ответа'); 
                }
                
                if (result && result.success) {
                    
                    const message = result.message || (lessonMode === 'recurring' && repeatCount ? 
                        `Создано ${repeatCount} уроков` : 'Урок успешно создан'); 
                    toast.success(message); 

                    if (modal) {
                        closeCreateModal(); 
                    }

                    createLessonForm.reset(); 
                    const repeatGroup = document.getElementById('repeatCountGroup'); 
                    if (repeatGroup) { 
                        repeatGroup.style.display = 'none'; 
                    }

                    setTimeout(() => {
                        window.location.reload(); 
                    }, 500); 
                } else {
                    
                    const errorMsg = result?.error || 'Ошибка при создании урока'; 
                    console.error('Ошибка создания урока:', result); 
                    toast.error(errorMsg); 
                }
            } catch (error) {
                console.error('Ошибка при создании урока:', error); 

                let errorMessage = 'Ошибка при создании урока. Попробуйте еще раз.'; 
                
                if (error.message) { 
                    errorMessage = error.message; 
                }
                
                toast.error(errorMessage); 
            } finally {
                if (loaderId) {
                    loading.hide(loaderId); 
                }
            }
        });
    }
}

function closeCreateModal() {
    const modal = document.getElementById('createLessonModal'); 
    if (modal) {
        modal.classList.remove('active'); 
    }
}

document.addEventListener('DOMContentLoaded', function() {
    
    const flashMessages = document.querySelectorAll('.alert, .flash-message'); 
    
    flashMessages.forEach(message => {
        const text = message.textContent.trim(); 
        const classes = message.className; 

        let type = 'info'; 
        if (classes.includes('success') || classes.includes('alert-success')) {
            type = 'success'; 
        } else if (classes.includes('error') || classes.includes('alert-danger')) {
            type = 'error'; 
        } else if (classes.includes('warning') || classes.includes('alert-warning')) {
            type = 'warning'; 
        }

        toast.show(text, type); 

        message.remove(); 
    });
});

