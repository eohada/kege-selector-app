// Функция для инициализации кнопки "Наверх"
function initScrollToTop() {
    // Проверяем, есть ли уже кнопка
    if (document.querySelector('.scroll-to-top')) return;

    // Создаем кнопку
    const scrollButton = document.createElement('button');
    scrollButton.className = 'scroll-to-top';
    scrollButton.setAttribute('aria-label', 'Наверх');
    scrollButton.innerHTML = `
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 4l-8 8h5v8h6v-8h5l-8-8z"/>
        </svg>
    `;
    document.body.appendChild(scrollButton);
    
    // Обработчик прокрутки
    let ticking = false;
    function handleScroll() {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                const scrollY = window.scrollY || window.pageYOffset;
                const showThreshold = 300; // Показывать после 300px прокрутки
                
                if (scrollY > showThreshold) {
                    scrollButton.classList.add('visible');
                } else {
                    scrollButton.classList.remove('visible');
                }
                
                ticking = false;
            });
            ticking = true;
        }
    }
    
    window.addEventListener('scroll', handleScroll, { passive: true });
    
    // Обработчик клика
    scrollButton.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
    
    // Проверяем начальное состояние
    handleScroll();
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', initScrollToTop);
