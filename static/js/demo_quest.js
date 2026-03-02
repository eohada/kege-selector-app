/**
 * Demo Quest — сценарий демо-тура для знакомства с платформой.
 * Состояние: localStorage.demoStep и cookie is_demo.
 */
(function() {
    'use strict';

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

    function runDriverSteps(steps, opts) {
        var driverFn = getDriver();
        if (!driverFn || !steps.length) return;
        opts = opts || {};
        var config = {
            showProgress: true,
            allowClose: true,
            nextBtnText: 'Далее',
            prevBtnText: 'Назад',
            doneBtnText: 'Готово',
            popoverClass: 'demo-driver-popover',
            steps: steps,
            onDestroyed: opts.onDestroyed || function() {}
        };
        var driverObj = driverFn(config);
        if (driverObj && typeof driverObj.drive === 'function') {
            driverObj.drive();
        }
    }

    function init() {
        if (!getDemoState()) return;

        var path = window.location.pathname.replace(/\/$/, '') || '/';
        var step = getDemoStep();

        // Шаг 0: дашборд ученика — приветствие и подсветка «Задания»
        if (path.indexOf('/student/dashboard') !== -1 || path === '/' || path === '/dashboard') {
            var steps = [];
            steps.push({
                element: 'body',
                popover: {
                    title: 'Привет! 👋',
                    description: 'Погнали посмотрим, как тут всё устроено. Пройди несколько шагов и получи первую ачивку!',
                    side: 'bottom',
                    align: 'start'
                }
            });
            var btn = document.getElementById('demo-open-assignments') || document.getElementById('demo-nav-assignments');
            if (btn) {
                steps.push({
                    element: btn,
                    popover: {
                        title: 'Шаг 1 из 3: Домашки',
                        description: 'Тут живут твои домашки. Нажми «Далее», затем кликни по кнопке и открой раздел «Задания».',
                        side: 'right',
                        align: 'start'
                    }
                });
            }
            if (steps.length) {
                runDriverSteps(steps, {
                    onDestroyed: function() { setDemoStep(1); }
                });
            }
            return;
        }

        // Страница заданий (submissions list: /submissions)
        if (path.indexOf('/submissions') !== -1 && path.indexOf('/submissions/') === -1) {
            if (step < 2) setDemoStep(2);
            var navTrainer = document.getElementById('demo-nav-trainer');
            if (navTrainer) {
                runDriverSteps([{
                    element: navTrainer,
                    popover: {
                        title: 'Шаг 2 из 3: Тренажёр',
                        description: 'Теперь зайди в Тренажёр — там можно решать задачи с подсказками ИИ. Кликни по ссылке в меню слева.',
                        side: 'right',
                        align: 'start'
                    }
                }]);
            }
            return;
        }

        // Тренажёр
        if (path.indexOf('/trainer') !== -1) {
            if (step < 3) setDemoStep(3);
            runDriverSteps([{
                element: 'body',
                popover: {
                    title: 'Тренажёр 🧠',
                    description: 'Здесь ты решаешь задачи, а ИИ подсказывает, если что-то пошло не так. Попробуй отправить решение и посмотри подсказки!',
                    side: 'bottom',
                    align: 'start'
                }
            }]);
            return;
        }

        // Статистика / аналитика
        if (path.indexOf('/analytics') !== -1 || path.indexOf('/student_analytics') !== -1) {
            setDemoStep(4);
            if (typeof confetti === 'function') {
                try { confetti({ particleCount: 80, spread: 60, origin: { y: 0.7 } }); } catch (e) {}
            }
            runDriverSteps([{
                element: 'body',
                popover: {
                    title: 'Красава! 🎉',
                    description: 'Квест пройден. Здесь — твой рейтинг и радар навыков. Хочешь заниматься по-настоящему? Зарегистрируйся!',
                    side: 'bottom',
                    align: 'start'
                }
            }]);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 600); });
    } else {
        setTimeout(init, 600);
    }
})();
