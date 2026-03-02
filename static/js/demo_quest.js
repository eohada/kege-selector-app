/**
 * Demo Quest — интерактивный квест по платформе.
 * Виджет «Шаг N из M», подсветка Driver.js, конфетти на финише.
 */
(function() {
    'use strict';

    var TOTAL_STEPS = 5;

    function getDemoState() {
        var isDemo = false;
        try {
            if (document.cookie.indexOf('is_demo=true') !== -1) isDemo = true;
            if (!isDemo && localStorage.getItem('is_demo') === 'true') isDemo = true;
            if (isDemo) localStorage.setItem('is_demo', 'true');
        } catch (e) {}
        return isDemo;
    }

    function getDemoStep() {
        try {
            var step = localStorage.getItem('demoStep');
            if (step === null && document.cookie.indexOf('demoStep=') !== -1) {
                var m = document.cookie.match(/demoStep=(\d+)/);
                if (m) { step = m[1]; localStorage.setItem('demoStep', step); }
            }
            return step !== null ? parseInt(step, 10) : 0;
        } catch (e) { return 0; }
    }

    function setDemoStep(n) {
        try { localStorage.setItem('demoStep', String(n)); } catch (e) {}
    }

    function getDriver() {
        try {
            if (typeof window.driver !== 'undefined' && window.driver.driver)
                return window.driver.driver;
            if (typeof window['driver.js'] !== 'undefined' && window['driver.js'].driver)
                return window['driver.js'].driver;
        } catch (e) {}
        return null;
    }

    /**
     * По текущему path и DOM определяем номер шага и данные для подсветки.
     * Возвращает { step: 1..5, title, description, element }.
     */
    function getStepConfig() {
        var path = window.location.pathname.replace(/\/$/, '') || '/';
        var step = 1;
        var title = '';
        var description = '';
        var element = null;

        // Шаг 1: дашборд
        if (path.indexOf('/student/dashboard') !== -1 || path === '/' || path === '/dashboard' || path === '') {
            step = 1;
            title = 'Шаг 1 из ' + TOTAL_STEPS + ': С чего начать';
            description = 'Здесь твой главный экран. Нажми «Задания» в меню слева — там ждёт демо-работа «Пробник-1».';
            element = document.getElementById('demo-open-assignments') || document.getElementById('demo-nav-assignments');
            if (!element) element = document.body;
        }
        // Шаг 2: список сдач
        else if (path.indexOf('/submissions') !== -1 && path.match(/\/submissions\/\d+/) === null) {
            step = 2;
            title = 'Шаг 2 из ' + TOTAL_STEPS + ': Твои работы';
            description = 'Открой работу «Пробник-1» — нажми кнопку «Начать» на карточке.';
            element = document.querySelector('.demo-submission-card') || document.querySelector('.demo-btn-begin') || document.querySelector('.demo-highlight-begin');
            if (!element) element = document.querySelector('.submission-card');
            if (!element) element = document.body;
        }
        // Шаг 3: страница выполнения работы
        else if (path.match(/\/submissions\/\d+/) !== null) {
            step = 3;
            var startBtn = document.getElementById('start-btn');
            var answerBlock = document.getElementById('demo-answer-block');
            var submitSection = document.getElementById('demo-submit-section');
            if (startBtn && startBtn.offsetParent !== null) {
                title = 'Шаг 3 из ' + TOTAL_STEPS + ': Начать выполнение';
                description = 'Нажми «Начать выполнение», чтобы открыть задание и таймер.';
                element = startBtn;
            } else if (answerBlock || submitSection) {
                title = 'Шаг 3 из ' + TOTAL_STEPS + ': Ответ и сдача';
                description = 'Нажми «Вставить ответ», затем внизу страницы — «Сдать работу».';
                element = answerBlock || document.getElementById('demo-paste-answer') || submitSection || document.getElementById('submit-btn');
                if (!element) element = document.body;
            } else {
                title = 'Шаг 3 из ' + TOTAL_STEPS + ': Выполнение работы';
                description = 'Введи ответ в поле и нажми «Сдать работу» внизу.';
                element = document.getElementById('submit-btn') || document.body;
            }
        }
        // Шаг 4: тренажёр
        else if (path.indexOf('/trainer') !== -1) {
            step = 4;
            title = 'Шаг 4 из ' + TOTAL_STEPS + ': Тренажёр';
            description = 'Здесь можно решать задачи с подсказками ИИ. Теперь зайди в «Статистика» в меню слева — там финал демо.';
            element = document.getElementById('demo-nav-stats') || document.body;
        }
        // Шаг 5: аналитика / статистика
        else if (path.indexOf('/analytics') !== -1 || path.indexOf('/student_analytics') !== -1) {
            step = 5;
            title = 'Шаг 5 из ' + TOTAL_STEPS + ': Почти готово!';
            description = 'Здесь — твой прогресс и рейтинг. Зарегистрируйся, чтобы сохранить данные и продолжить учёбу.';
            element = document.body;
        }
        // Неизвестная страница — показываем текущий сохранённый шаг или 1
        else {
            step = getDemoStep();
            if (step < 1 || step > TOTAL_STEPS) step = 1;
            title = 'Шаг ' + step + ' из ' + TOTAL_STEPS;
            description = 'Перейди в раздел «Задания» в меню и открой работу «Пробник-1».';
            element = document.getElementById('demo-nav-assignments') || document.body;
        }

        return { step: step, title: title, description: description, element: element };
    }

    function runDriverStep(config) {
        var driverFn = getDriver();
        if (!driverFn) return;
        var el = config.element || document.body;
        var steps = [{
            element: el,
            popover: {
                title: config.title,
                description: config.description,
                side: el === document.body ? 'bottom' : 'right',
                align: 'start'
            }
        }];
        var driverObj = driverFn({
            showProgress: false,
            allowClose: true,
            nextBtnText: 'Понятно',
            prevBtnText: '',
            doneBtnText: 'Понятно',
            popoverClass: 'demo-driver-popover',
            steps: steps
        });
        if (driverObj && typeof driverObj.drive === 'function')
            driverObj.drive();
    }

    function updateWidget(config) {
        var w = document.getElementById('demo-quest-widget');
        if (!w) return;
        var stepLabel = document.getElementById('demo-quest-step-label');
        var hint = document.getElementById('demo-quest-hint');
        var progressInner = document.getElementById('demo-quest-progress-inner');
        if (stepLabel) stepLabel.textContent = 'Шаг ' + config.step + ' из ' + TOTAL_STEPS;
        if (hint) hint.textContent = config.description;
        if (progressInner) progressInner.style.width = (100 * config.step / TOTAL_STEPS) + '%';
        w.style.display = '';
        w.setAttribute('aria-hidden', 'false');
    }

    function bindHighlightButton(config) {
        var btn = document.getElementById('demo-quest-btn-highlight');
        if (!btn) return;
        btn.onclick = function() { runDriverStep(config); };
    }

    function init() {
        if (!getDemoState()) return;

        var config = getStepConfig();
        setDemoStep(config.step);
        updateWidget(config);
        bindHighlightButton(config);

        // На шаге 5 — конфетти один раз
        if (config.step === 5 && typeof confetti === 'function') {
            try {
                confetti({ particleCount: 80, spread: 60, origin: { y: 0.7 } });
            } catch (e) {}
        }

        // Один раз показываем подсветку с задержкой, чтобы виджет успел отрисоваться
        setTimeout(function() {
            runDriverStep(config);
        }, 800);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 400); });
    } else {
        setTimeout(init, 400);
    }
})();
