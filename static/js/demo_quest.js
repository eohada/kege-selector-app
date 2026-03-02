/**
 * Demo Quest — интерактивное кино: затемнение экрана, spotlight на одной кнопке,
 * имитация ввода (typewriter), пульсирующий указатель.
 */
(function() {
    'use strict';

    var TOTAL_STEPS = 5;
    var DEMO_ANSWER_TEXT = '42';
    var TYPEWRITER_MS_PER_CHAR = 90;

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

    function addSpotlightRing(el) {
        if (el && el.classList && !el.classList.contains('demo-spotlight-ring'))
            el.classList.add('demo-spotlight-ring');
    }

    function removeSpotlightRing(el) {
        if (el && el.classList)
            el.classList.remove('demo-spotlight-ring');
    }

    /**
     * Имитация ввода текста посимвольно в поле (textarea или CodeMirror).
     * По завершении вызывает onDone().
     */
    function typewriterIntoField(text, onDone) {
        var textarea = document.querySelector('.demo-first-answer');
        var codeWrap = document.querySelector('.code-editor-wrap');
        var target = textarea;
        var isCodeMirror = false;
        if (!textarea && codeWrap) {
            var cmWrap = codeWrap.querySelector('.code-editor-cm-wrap');
            var cmText = cmWrap && cmWrap.querySelector('.code-editor-text');
            if (cmText && cmText.cmInstance) {
                target = null;
                isCodeMirror = true;
            } else if (cmText) {
                target = cmText;
            }
        }
        if (!target && !isCodeMirror) {
            if (onDone) onDone();
            return;
        }

        var index = 0;
        var currentValue = '';
        function tick() {
            if (index >= text.length) {
                if (target) target.dispatchEvent(new Event('input', { bubbles: true }));
                if (onDone) setTimeout(onDone, 400);
                return;
            }
            var char = text[index];
            index += 1;
            currentValue += char;
            if (isCodeMirror) {
                var cmEl = codeWrap.querySelector('.code-editor-text');
                if (cmEl && cmEl.cmInstance) {
                    cmEl.cmInstance.setValue(currentValue);
                    cmEl.cmInstance.setCursor(0, currentValue.length);
                }
            } else if (target) {
                target.value = currentValue;
                target.dispatchEvent(new Event('input', { bubbles: true }));
            }
            setTimeout(tick, TYPEWRITER_MS_PER_CHAR);
        }
        if (isCodeMirror) {
            var cmEl = codeWrap.querySelector('.code-editor-text');
            if (cmEl && cmEl.cmInstance) cmEl.cmInstance.setValue('');
        } else if (target) {
            target.value = '';
        }
        setTimeout(tick, 200);
    }

    /**
     * Конфиг шага по path и DOM.
     * Возвращает { step, title, description, element, isAnswerPhase }.
     * isAnswerPhase = true только на странице работы, когда уже нажали «Начать» и видно поле ответа.
     */
    function getStepConfig() {
        var path = window.location.pathname.replace(/\/$/, '') || '/';
        var step = 1;
        var title = '';
        var description = '';
        var element = null;
        var isAnswerPhase = false;

        if (path.indexOf('/student/dashboard') !== -1 || path === '/' || path === '/dashboard' || path === '') {
            step = 1;
            title = 'Шаг 1 из ' + TOTAL_STEPS;
            description = 'Здесь твой главный экран. Нажми на кнопку «Задания» в меню слева — там ждёт демо-работа.';
            element = document.getElementById('demo-open-assignments') || document.getElementById('demo-nav-assignments');
            if (!element) element = document.body;
        }
        else if (path.indexOf('/submissions') !== -1 && path.match(/\/submissions\/\d+/) === null) {
            step = 2;
            title = 'Шаг 2 из ' + TOTAL_STEPS;
            description = 'Открой работу «Пробник-1» — нажми кнопку «Начать» на карточке.';
            element = document.querySelector('.demo-submission-card') || document.querySelector('.demo-btn-begin') || document.querySelector('.demo-highlight-begin');
            if (!element) element = document.querySelector('.submission-card');
            if (!element) element = document.body;
        }
        else if (path.match(/\/submissions\/\d+/) !== null) {
            step = 3;
            var startBtn = document.getElementById('start-btn');
            var answerBlock = document.getElementById('demo-answer-block');
            var submitBtn = document.getElementById('submit-btn');
            if (startBtn && startBtn.offsetParent !== null) {
                title = 'Шаг 3 из ' + TOTAL_STEPS;
                description = 'Нажми «Начать выполнение» — откроется задание и таймер.';
                element = startBtn;
            } else if (answerBlock || submitBtn) {
                isAnswerPhase = true;
                title = 'Шаг 3 из ' + TOTAL_STEPS;
                description = 'Сюда вводится ответ. Нажми «Далее» — мы введём его за тебя посимвольно.';
                element = answerBlock || document.querySelector('.demo-first-answer') || document.getElementById('demo-paste-answer');
                if (!element) element = document.querySelector('.task-card');
                if (!element) element = document.body;
            } else {
                title = 'Шаг 3 из ' + TOTAL_STEPS;
                description = 'Введи ответ и нажми «Сдать работу» внизу.';
                element = submitBtn || document.body;
            }
        }
        else if (path.indexOf('/trainer') !== -1) {
            step = 4;
            title = 'Шаг 4 из ' + TOTAL_STEPS;
            description = 'Здесь можно решать задачи с подсказками ИИ. Зайди в «Статистика» в меню — там финал демо.';
            element = document.getElementById('demo-nav-stats') || document.body;
        }
        else if (path.indexOf('/analytics') !== -1 || path.indexOf('/student_analytics') !== -1) {
            step = 5;
            title = 'Шаг 5 из ' + TOTAL_STEPS;
            description = 'Здесь — твой прогресс. Зарегистрируйся, чтобы сохранить данные и продолжить.';
            element = document.body;
        }
        else {
            step = getDemoStep();
            if (step < 1 || step > TOTAL_STEPS) step = 1;
            title = 'Шаг ' + step + ' из ' + TOTAL_STEPS;
            description = 'Перейди в «Задания» и открой работу «Пробник-1».';
            element = document.getElementById('demo-nav-assignments') || document.body;
        }

        return { step: step, title: title, description: description, element: element, isAnswerPhase: isAnswerPhase };
    }

    /**
     * Запуск подсветки одного шага с кинематографичными настройками и пульсирующим кольцом.
     * opts: { onNextClick, onDestroyed } — опциональные колбэки.
     */
    function runDriverStep(config, opts) {
        opts = opts || {};
        var driverFn = getDriver();
        if (!driverFn) return null;
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
            nextBtnText: 'Далее',
            prevBtnText: '',
            doneBtnText: 'Понятно',
            popoverClass: 'demo-driver-popover',
            overlayOpacity: 0.92,
            stagePadding: 16,
            stageRadius: 12,
            showButtons: ['next', 'close'],
            steps: steps,
            onHighlighted: function(element) {
                addSpotlightRing(element);
            },
            onDeselected: function(element) {
                removeSpotlightRing(element);
            },
            onDestroyed: function(element, step, options) {
                removeSpotlightRing(element);
                if (opts.onDestroyed) opts.onDestroyed();
            },
            onNextClick: opts.onNextClick || undefined
        });

        if (driverObj && typeof driverObj.drive === 'function')
            driverObj.drive();
        return driverObj;
    }

    /**
     * Сценарий на странице работы (ответ): подсветка поля → имитация ввода → подсветка «Сдать».
     */
    function runSubmissionAnswerScenario() {
        var answerBlock = document.getElementById('demo-answer-block');
        var submitBtn = document.getElementById('submit-btn');
        var el = answerBlock || document.querySelector('.demo-first-answer') || document.body;

        var driverFn = getDriver();
        if (!driverFn) return;

        var steps = [{
            element: el,
            popover: {
                title: 'Шаг 3 из ' + TOTAL_STEPS,
                description: 'Сюда вводится ответ. Нажми «Далее» — мы введём его за тебя посимвольно.',
                side: 'right',
                align: 'start'
            }
        }];

        var driverObj = driverFn({
            showProgress: false,
            allowClose: true,
            nextBtnText: 'Далее',
            doneBtnText: 'Понятно',
            popoverClass: 'demo-driver-popover',
            overlayOpacity: 0.92,
            stagePadding: 16,
            stageRadius: 12,
            showButtons: ['next', 'close'],
            steps: steps,
            onHighlighted: function(element) { addSpotlightRing(element); },
            onDeselected: function(element) { removeSpotlightRing(element); },
            onNextClick: function(element, step, options) {
                options.driver.destroy();
                removeSpotlightRing(element);
                typewriterIntoField(DEMO_ANSWER_TEXT, function() {
                    setTimeout(function() {
                        runDriverStep({
                            step: 3,
                            title: 'Шаг 3 из ' + TOTAL_STEPS,
                            description: 'Теперь нажми кнопку «Сдать работу» внизу экрана.',
                            element: submitBtn || document.body
                        }, { onDestroyed: null });
                    }, 500);
                });
            },
            onDestroyed: function(element) { removeSpotlightRing(element); }
        });

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
        btn.onclick = function() {
            if (config.step === 3 && config.isAnswerPhase)
                runSubmissionAnswerScenario();
            else
                runDriverStep(config);
        };
    }

    function init() {
        if (!getDemoState()) return;

        var config = getStepConfig();
        setDemoStep(config.step);
        updateWidget(config);
        bindHighlightButton(config);

        if (config.step === 5 && typeof confetti === 'function') {
            try { confetti({ particleCount: 80, spread: 60, origin: { y: 0.7 } }); } catch (e) {}
        }

        setTimeout(function() {
            if (config.step === 3 && config.isAnswerPhase)
                runSubmissionAnswerScenario();
            else
                runDriverStep(config);
        }, 900);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 500); });
    } else {
        setTimeout(init, 500);
    }
})();
