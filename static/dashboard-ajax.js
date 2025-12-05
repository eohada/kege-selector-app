

document.addEventListener('DOMContentLoaded', function() {
    
    initStudentForms(); 
    initStudentCards(); 
});

function initStudentForms() {
    
    const createForm = document.getElementById('create-student-form'); 
    const editForms = document.querySelectorAll('.edit-student-form'); 
    
    if (createForm) {
        
        createForm.addEventListener('submit', async function(e) {
            e.preventDefault(); 
            
            const formData = new FormData(createForm); 
            const data = Object.fromEntries(formData); 

            const loaderId = loading.show(createForm, 'Создание ученика...'); 
            
            try {
                const response = await ajax.post('/api/student/create', data); 
                
                if (response.success) {
                    
                    toast.success(response.message); 

                    const modal = createForm.closest('.modal'); 
                    if (modal) {
                        modal.classList.remove('active'); 
                    }

                    createForm.reset(); 

                    setTimeout(() => {
                        window.location.reload(); 
                    }, 500); 
                } else {
                    toast.error(response.error || 'Ошибка при создании ученика'); 
                }
            } catch (error) {
                console.error('Ошибка при создании студента:', error); 
                toast.error('Ошибка при создании ученика. Попробуйте еще раз.'); 
            } finally {
                loading.hide(loaderId); 
            }
        });
    }

    editForms.forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault(); 
            
            const formData = new FormData(form); 
            const data = Object.fromEntries(formData); 
            const studentId = form.dataset.studentId; 
            
            if (!studentId) {
                toast.error('ID студента не найден'); 
                return; 
            }

            const loaderId = loading.show(form, 'Сохранение изменений...'); 
            
            try {
                const response = await ajax.post(`/api/student/${studentId}/update`, data); 
                
                if (response.success) {
                    
                    toast.success(response.message); 

                    updateStudentCard(studentId, response.student); 

                    const modal = form.closest('.modal'); 
                    if (modal) {
                        modal.classList.remove('active'); 
                    }
                } else {
                    toast.error(response.error || 'Ошибка при сохранении изменений'); 
                }
            } catch (error) {
                console.error('Ошибка при обновлении студента:', error); 
                toast.error('Ошибка при сохранении изменений. Попробуйте еще раз.'); 
            } finally {
                loading.hide(loaderId); 
            }
        });
    });
}

function initStudentCards() {
    
    const deleteButtons = document.querySelectorAll('.delete-student-btn'); 
    
    deleteButtons.forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault(); 
            e.stopPropagation(); 
            
            const studentId = this.dataset.studentId; 
            const studentName = this.dataset.studentName || 'ученика'; 
            
            if (!studentId) {
                toast.error('ID студента не найден'); 
                return; 
            }

            // Сохраняем данные для undo
            const studentData = {
                id: studentId,
                name: studentName,
                card: card ? card.cloneNode(true) : null
            };
            
            // Показываем модальное окно подтверждения
            showConfirmModal({
                title: 'Удалить ученика?',
                message: `Вы уверены, что хотите удалить ученика "${studentName}"? Это действие нельзя отменить!`,
                confirmText: 'Удалить',
                cancelText: 'Отмена',
                confirmClass: 'danger',
                onConfirm: async () => {
                    await performDelete(studentId, studentName, card, loaderId, studentData);
                }
            });
            
            return;
        }
        
        async function performDelete(studentId, studentName, card, loaderId, studentData) {
            // Показываем индикатор загрузки, если его еще нет
            if (!loaderId && card) {
                loaderId = loading.show(card, 'Удаление...');
            } 
            
            try {
                const response = await ajax.delete(`/api/student/${studentId}/delete`); 
                
                if (response.success) {
                    // Добавляем действие в undo manager
                    if (typeof undoManager !== 'undefined') {
                        undoManager.addAction({
                            type: 'delete',
                            entity: 'student',
                            data: studentData,
                            message: `Ученик "${studentName}" удален`,
                            undo: async () => {
                                // Восстанавливаем ученика через API (если есть такой endpoint)
                                // Пока просто показываем сообщение
                                toast.info('Восстановление ученика пока не реализовано');
                            }
                        });
                    }
                    
                    toast.success(response.message); 

                    if (card) {
                        card.style.transition = 'opacity 0.3s, transform 0.3s'; 
                        card.style.opacity = '0'; 
                        card.style.transform = 'scale(0.9)'; 
                        
                        setTimeout(() => {
                            card.remove(); 

                            updateStatistics(); 
                        }, 300); 
                    } else {
                        
                        setTimeout(() => {
                            window.location.reload(); 
                        }, 500); 
                    }
                } else {
                    toast.error(response.error || 'Ошибка при удалении ученика'); 
                }
            } catch (error) {
                console.error('Ошибка при удалении студента:', error); 
                toast.error('Ошибка при удалении ученика. Попробуйте еще раз.'); 
            } finally {
                if (loaderId) {
                    loading.hide(loaderId); 
                }
            }
        });
    });
}

function updateStudentCard(studentId, studentData) {
    
    const card = document.querySelector(`[data-student-id="${studentId}"]`); 
    
    if (!card) {
        return; 
    }

    const nameElement = card.querySelector('.student-name'); 
    if (nameElement && studentData.name) {
        nameElement.textContent = studentData.name; 
    }

    const platformElement = card.querySelector('.student-platform-id'); 
    if (platformElement && studentData.platform_id) {
        platformElement.textContent = `ID: ${studentData.platform_id}`; 
    }

    const categoryElement = card.querySelector('.student-category'); 
    if (categoryElement && studentData.category) {
        categoryElement.textContent = studentData.category; 
    }
}

function updateStatistics() {

    const statsElements = document.querySelectorAll('.stat-value'); 

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

