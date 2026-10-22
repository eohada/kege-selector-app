/**
 * BooStudy Code Tracer (Бу Трассировщик)
 * Пошаговая визуализация структур памяти Python (Stack & Heap), связей,
 * мутаций списков/словарей и интерактивных брейкпоинтов.
 */
(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.BooTracer = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  let instance = null;

  class BooTracerEngine {
    constructor() {
      if (instance) return instance;
      instance = this;

      this.isOpen = false;
      this.isDetached = false;
      this.frames = [];
      this.currentIndex = 0;
      this.isPlaying = false;
      this.playTimer = null;
      this.playSpeed = 1.0;
      this.breakpoints = new Set();
      this.activeFileName = 'main.py';
      this.lastCode = '';
      this.isLoading = false;
      this.inputs = [];
      this._skipInputModal = false;

      this.initDom();
      this.bindGutterBreakpoints();
      this.bindGlobalShortcuts();
    }

    /** Глобальные горячие клавиши отладки (F5, F10, Shift+F10) */
    bindGlobalShortcuts() {
      window.addEventListener('keydown', (e) => {
        if (!this.isOpen) return;
        if (e.key === 'F10') {
          e.preventDefault();
          if (e.shiftKey) {
            this.stepBackward();
          } else {
            this.stepForward();
          }
        } else if (e.key === 'F5') {
          e.preventDefault();
          this.togglePlay();
        }
      });

      window.addEventListener('resize', () => {
        if (this.isOpen && this.frames[this.currentIndex]) {
          requestAnimationFrame(() => this.drawPointers(this.frames[this.currentIndex]));
        }
      });
    }

    /** Инициализация разметки интерфейса трассировщика */
    initDom() {
      // 1. Пристыкованная панель в редакторе кода
      this.dockedPanel = document.getElementById('editor-tracer-panel');
      // 2. Отдельное плавающее окно Lesson OS
      this.floatingWindow = document.getElementById('tracer-window');

      this.renderTracerShell();
    }

    /** Возвращает целевой контейнер для содержимого трассировщика */
    getContentContainer() {
      if (this.isDetached) {
        return document.getElementById('tracer-window-content') || this.floatingWindow;
      }
      return this.dockedPanel;
    }

    /** Создает разметку оболочки трассировщика */
    renderTracerShell() {
      const container = this.getContentContainer();
      if (!container) return;

      // Очищаем противоположный контейнер для избежания дублирования ID в DOM
      if (this.isDetached) {
        if (this.dockedPanel) this.dockedPanel.innerHTML = '';
      } else {
        const floatContent = document.getElementById('tracer-window-content');
        if (floatContent) floatContent.innerHTML = '';
      }

      container.innerHTML = `
        <div class="boo-tracer-panel ${this.isDetached ? 'is-detached' : ''}" id="boo-tracer-main-panel">
          ${!this.isDetached ? `
          <!-- Шапка трассировщика (в пристыкованном виде) -->
          <div class="boo-tracer-header">
            <div class="boo-tracer-title">
              <i class="ph-bold ph-git-commit"></i>
              <span>Бу Трассировщик</span>
            </div>
            <div class="boo-tracer-header-actions">
              <button type="button" class="boo-tracer-action-btn" id="boo-tracer-dock-toggle-btn" title="Открепить в отдельное окно OS">
                <i class="ph-bold ph-arrow-square-out"></i>
                <span id="boo-tracer-dock-text">Открепить</span>
              </button>
              <button type="button" class="boo-tracer-action-btn" id="boo-tracer-close-btn" title="Закрыть трассировщик">
                <i class="ph-bold ph-x"></i>
              </button>
            </div>
          </div>
          ` : ''}

          <!-- Панель управления отладчиком -->
          <div class="boo-tracer-controls-bar">
            <div class="boo-tracer-controls-row">
              <div class="boo-tracer-buttons-group">
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-prev" title="Шаг назад (Shift+F10)">
                  <i class="ph-bold ph-caret-left"></i>
                </button>
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-play" title="Воспроизведение / Пауза (F5)">
                  <i class="ph-bold ph-play" id="boo-tracer-play-icon"></i>
                </button>
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-next" title="Шаг вперёд (F10)">
                  <i class="ph-bold ph-caret-right"></i>
                </button>
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-bp" title="Продолжить до брейкпоинта">
                  <i class="ph-bold ph-fast-forward"></i>
                </button>
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-reset" title="В начало">
                  <i class="ph-bold ph-arrow-counter-clockwise"></i>
                </button>
                <button type="button" class="boo-tracer-ctrl-btn" id="boo-tracer-btn-reload" title="Перезапустить трассировку">
                  <i class="ph-bold ph-arrows-clockwise"></i>
                </button>
              </div>

              <!-- Бейдж шага -->
              <div class="boo-tracer-step-badge">
                Шаг <strong id="boo-tracer-cur-step">0</strong> / <span id="boo-tracer-total-step">0</span>
              </div>

              <!-- Селектор скорости -->
              <div class="boo-tracer-speed-group">
                <button type="button" class="boo-tracer-speed-btn" data-speed="0.5">0.5x</button>
                <button type="button" class="boo-tracer-speed-btn active" data-speed="1">1x</button>
                <button type="button" class="boo-tracer-speed-btn" data-speed="2">2x</button>
                <button type="button" class="boo-tracer-speed-btn" data-speed="5">5x</button>
              </div>
            </div>

            <!-- Шкала времени (Timeline Scrubber) -->
            <div class="boo-tracer-timeline-row">
              <input type="range" class="boo-tracer-slider" id="boo-tracer-slider" min="0" max="0" value="0" step="1">
            </div>
          </div>

          <!-- Рабочая область визуализации памяти -->
          <div class="boo-tracer-body" id="boo-tracer-body">
            <svg class="boo-tracer-svg-layer" id="boo-tracer-svg-layer"></svg>

            <!-- Интерактивная карточка ожидания ввода input() -->
            <div id="boo-tracer-interactive-input-sec" class="hidden"></div>

            <!-- Стек вызовов и переменные -->
            <div class="boo-tracer-section" id="boo-tracer-stack-sec">
              <div class="boo-tracer-section-title">
                <span>Стек вызовов и переменные</span>
                <span class="count" id="boo-tracer-vars-count">0</span>
              </div>
              <div id="boo-tracer-stack-container">
                <div class="text-xs text-slate-500 italic p-2">Нажмите «Трассировка» для запуска пошагового анализа...</div>
              </div>
            </div>

            <!-- Объекты кучи (Списки, Словари) -->
            <div class="boo-tracer-section" id="boo-tracer-heap-sec">
              <div class="boo-tracer-section-title">
                <span>Куча (Heap Objects)</span>
                <span class="count" id="boo-tracer-heap-count">0</span>
              </div>
              <div class="boo-tracer-heap-grid" id="boo-tracer-heap-container"></div>
            </div>

            <!-- Консоль stdout текущего шага -->
            <div class="boo-tracer-section" id="boo-tracer-stdout-sec">
              <div class="boo-tracer-section-title">
                <span>Вывод консоли (print)</span>
              </div>
              <div class="boo-tracer-stdout-card" id="boo-tracer-stdout-box">
                <span class="boo-tracer-stdout-empty">Вывод программы пуст</span>
              </div>
            </div>
          </div>
        </div>
      `;

      this.bindControls();
    }

    /** Привязка обработчиков кнопок и контролов */
    bindControls() {
      const panel = document.getElementById('boo-tracer-main-panel');
      if (!panel) return;

      panel.querySelector('#boo-tracer-close-btn')?.addEventListener('click', () => this.close());
      panel.querySelector('#boo-tracer-dock-toggle-btn')?.addEventListener('click', () => this.toggleDockMode());

      panel.querySelector('#boo-tracer-btn-prev')?.addEventListener('click', () => this.stepBackward());
      panel.querySelector('#boo-tracer-btn-next')?.addEventListener('click', () => this.stepForward());
      panel.querySelector('#boo-tracer-btn-play')?.addEventListener('click', () => this.togglePlay());
      panel.querySelector('#boo-tracer-btn-bp')?.addEventListener('click', () => this.runToBreakpoint());
      panel.querySelector('#boo-tracer-btn-reset')?.addEventListener('click', () => this.jumpToStep(0));
      panel.querySelector('#boo-tracer-btn-reload')?.addEventListener('click', () => this.restartTrace());

      const slider = panel.querySelector('#boo-tracer-slider');
      let sliderDebounceTimer = null;
      slider?.addEventListener('input', (e) => {
        this.pause();
        const stepVal = parseInt(e.target.value, 10);
        this.jumpToStep(stepVal, true);
        clearTimeout(sliderDebounceTimer);
        sliderDebounceTimer = setTimeout(() => {
          this.broadcastSync();
        }, 40);
      });
      slider?.addEventListener('change', () => {
        clearTimeout(sliderDebounceTimer);
        this.broadcastSync();
      });

      panel.querySelectorAll('.boo-tracer-speed-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          panel.querySelectorAll('.boo-tracer-speed-btn').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          this.playSpeed = parseFloat(btn.dataset.speed || '1.0');
          if (this.isPlaying) {
            this.pause();
            this.play();
          } else {
            this.broadcastSync();
          }
        });
      });

      // Скролл тела трассировщика мгновенно пересчитывает стрелки
      const body = panel.querySelector('#boo-tracer-body');
      body?.addEventListener('scroll', () => {
        if (this.frames[this.currentIndex]) {
          this.drawPointers(this.frames[this.currentIndex]);
        }
      }, { passive: true });
    }

    /** Привязка кликов по номерам строк в желобе редактора для брейкпоинтов */
    bindGutterBreakpoints() {
      const gutter = document.getElementById('line-numbers-gutter');
      if (!gutter) return;

      gutter.addEventListener('click', (e) => {
        const lineEl = e.target.closest('.gutter-line, [data-line], div');
        if (!lineEl) return;
        const lineAttr = lineEl.getAttribute('data-line');
        const lineNum = lineAttr ? parseInt(lineAttr, 10) : parseInt(lineEl.textContent.trim(), 10);
        if (isNaN(lineNum) || lineNum <= 0) return;

        this.toggleBreakpoint(lineNum);
      });

      // Перехватываем window.updateLineNumbers, чтобы сохранять брейкпоинты при обновлении кода
      const origUpdate = window.updateLineNumbers;
      if (typeof origUpdate === 'function' && !origUpdate.__tracerHooked) {
        window.updateLineNumbers = (...args) => {
          origUpdate.apply(window, args);
          this.updateGutterBreakpoints();
        };
        window.updateLineNumbers.__tracerHooked = true;
      }
    }

    /** Переключает брейкпоинт на строке */
    toggleBreakpoint(lineNum) {
      if (this.breakpoints.has(lineNum)) {
        this.breakpoints.delete(lineNum);
      } else {
        this.breakpoints.add(lineNum);
      }
      this.updateGutterBreakpoints();
      this.broadcastSync();
    }

    /** Обновляет визуальное отображение брейкпоинтов в желобе */
    updateGutterBreakpoints() {
      const gutter = document.getElementById('line-numbers-gutter');
      if (!gutter) return;

      gutter.querySelectorAll('.gutter-line, [data-line]').forEach((el) => {
        const lineAttr = el.getAttribute('data-line');
        const num = lineAttr ? parseInt(lineAttr, 10) : parseInt(el.textContent.trim(), 10);
        if (this.breakpoints.has(num)) {
          el.classList.add('line-gutter-breakpoint');
        } else {
          el.classList.remove('line-gutter-breakpoint');
        }
      });
    }

    /** Переключает видимость панели трассировщика (или перезапускает с новым кодом, если уже открыт) */
    toggle(code, fileName) {
      if (this.isOpen) {
        this.restartTrace();
      } else {
        this.open(code, fileName);
      }
    }

    /** Полный перезапуск трассировщика по актуальному коду с очисткой сохранённых stdin значений */
    async restartTrace(skipSync = false) {
      this.pause();
      this.inputs = [];
      this.activeFileName = window.activeFileName || this.activeFileName || 'main.py';
      this.lastCode = document.getElementById('code-editor-textarea')?.value || window.virtualFS?.[this.activeFileName] || '';
      this.currentIndex = 0;
      this.pendingStep = 0;
      this.renderInteractiveInputPrompt(null);
      await this.runTrace(this.lastCode, this.activeFileName, []);
      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Открывает трассировщик и запускает сбор кадров */
    async open(code, fileName, skipSync = false) {
      this.isOpen = true;
      this.activeFileName = fileName || window.activeFileName || 'main.py';
      this.lastCode = typeof code === 'string' && code ? code : (document.getElementById('code-editor-textarea')?.value || window.virtualFS?.[this.activeFileName] || '');
      this.inputs = []; // Очищаем историю stdin при первичном/повторном открытии
      this.renderInteractiveInputPrompt(null);

      if (this.isDetached) {
        if (typeof window.openWindow === 'function') {
          window.openWindow('tracer-window');
        } else {
          this.floatingWindow?.classList.remove('hidden');
        }
        if (window.windowManager && this.floatingWindow) {
          window.windowManager.registerWindow('tracer-window');
          window.windowManager.bringToFront(this.floatingWindow);
        }
      } else {
        this.dockedPanel?.classList.remove('hidden');
      }

      const toggleBtn = document.getElementById('editor-tracer-toggle-btn');
      if (toggleBtn) {
        toggleBtn.classList.add('is-active', 'ring-2', 'ring-cyan-400');
      }

      await this.runTrace(this.lastCode, this.activeFileName, []);
      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Закрывает трассировщик */
    close(skipSync = false) {
      this.pause();
      this.isOpen = false;
      this.dockedPanel?.classList.add('hidden');
      if (typeof window.closeWindow === 'function') {
        window.closeWindow('tracer-window');
      } else {
        this.floatingWindow?.classList.add('hidden');
      }

      const toggleBtn = document.getElementById('editor-tracer-toggle-btn');
      if (toggleBtn) {
        toggleBtn.classList.remove('is-active', 'ring-2', 'ring-cyan-400');
      }

      this.clearActiveLineHighlight();
      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Переключает между пристыкованной панелью и плавающим окном OS */
    toggleDockMode(skipSync = false) {
      this.isDetached = !this.isDetached;
      if (this.isDetached) {
        this.dockedPanel?.classList.add('hidden');
        this.renderTracerShell();
        if (typeof window.openWindow === 'function') {
          window.openWindow('tracer-window');
        } else {
          this.floatingWindow?.classList.remove('hidden');
        }
        if (window.windowManager && this.floatingWindow) {
          window.windowManager.registerWindow('tracer-window');
          window.windowManager.bringToFront(this.floatingWindow);
        }
      } else {
        if (typeof window.closeWindow === 'function') {
          window.closeWindow('tracer-window');
        } else {
          this.floatingWindow?.classList.add('hidden');
        }
        this.renderTracerShell();
        this.dockedPanel?.classList.remove('hidden');
      }
      this.renderCurrentStep();
      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Запрашивает серверную трассировку кода */
    async runTrace(code, fileName, inputs = null) {
      if (this.isLoading) return;

      if (Array.isArray(inputs)) {
        this.inputs = inputs;
      } else {
        this.inputs = [];
      }

      this.isLoading = true;
      this.pause();

      const bodyEl = document.getElementById('boo-tracer-body');
      if (bodyEl) {
        const stackCont = document.getElementById('boo-tracer-stack-container');
        if (stackCont) {
          stackCont.innerHTML = `
            <div class="flex items-center gap-2 p-3 text-cyan-400 font-mono text-xs">
              <span class="w-2 h-2 rounded-full bg-cyan-400 animate-ping"></span>
              Анализ выполнения Python 3.12...
            </div>
          `;
        }
      }

      try {
        const res = await fetch('/api/v2/code/trace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code,
            file_name: fileName,
            inputs: this.inputs || [],
            pause_on_input: true,
            max_steps: 1000
          }),
        });

        const data = await res.json();
        if (data.success && Array.isArray(data.frames) && data.frames.length > 0) {
          this.frames = data.frames;
          this.isWaitingInput = Boolean(data.waiting_input);
          this.currentInputPrompt = data.input_prompt || '';
          this.currentInputLine = data.input_line || (this.frames[this.frames.length - 1]?.line || 1);

          if (this.pendingStep !== null && this.pendingStep !== undefined) {
            this.currentIndex = Math.max(0, Math.min(this.pendingStep, this.frames.length - 1));
            this.pendingStep = null;
          } else if (this.isWaitingInput) {
            this.currentIndex = this.frames.length - 1;
          } else {
            this.currentIndex = 0;
          }
          this.updateSliderBounds();
          this.renderCurrentStep();
          this.updateStdinIndicator();
        } else {
          this.renderError(data.error || 'Не удалось выполнить трассировку кода');
        }
      } catch (err) {
        this.renderError(`Сетевая ошибка: ${err.message}`);
      } finally {
        this.isLoading = false;
      }
    }

    /** Отображает интерактивную карточку ожидания ввода input() */
    renderInteractiveInputPrompt(frame) {
      const container = document.getElementById('boo-tracer-interactive-input-sec');
      if (!container) return;

      const isLastStep = this.currentIndex === this.frames.length - 1;
      if (!this.isWaitingInput || !isLastStep) {
        container.classList.add('hidden');
        container.innerHTML = '';
        return;
      }

      container.classList.remove('hidden');
      const promptText = this.currentInputPrompt ? String(this.currentInputPrompt) : '';
      const promptHtml = promptText
        ? `<div class="text-slate-800 font-mono text-xs bg-slate-100/90 px-3 py-1.5 rounded-xl border border-slate-200">Подсказка: <strong>${escapeHtml(promptText)}</strong></div>`
        : '';

      container.innerHTML = `
        <div id="boo-tracer-step-input-card" class="m-3 p-4 bg-[#F8FAFC] border-2 border-slate-300 shadow-[0_8px_20px_rgba(15,23,42,0.14),0_4px_0_#CBD5E1] rounded-[1.25rem] flex flex-col gap-3 z-20">
          <div class="flex items-center justify-between pb-2 border-b border-slate-200">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-lg bg-indigo-100 border border-indigo-300 text-indigo-700 flex items-center justify-center font-bold text-xs shadow-xs">
                <i class="ph-bold ph-terminal-window"></i>
              </div>
              <div>
                <h5 class="font-extrabold text-slate-900 text-xs">Программа ожидает ввод для input()</h5>
                <span class="text-[11px] text-indigo-700 font-mono font-bold">Строка ${this.currentInputLine || frame.line}</span>
              </div>
            </div>
            <span class="px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 text-[10px] font-black uppercase tracking-wider animate-pulse">Ожидание</span>
          </div>
          ${promptHtml}
          <div class="flex items-center gap-2 pt-1">
            <input type="text" id="boo-tracer-step-input-val"
              class="flex-1 px-3.5 py-2 text-xs font-mono font-bold text-slate-900 bg-white border-2 border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all"
              placeholder="Введите значение (например, 42)..." autofocus autocomplete="off">
            <button type="button" id="boo-tracer-step-input-btn"
              class="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-black text-xs rounded-xl border border-indigo-700 border-b-[4px] shadow-[0_4px_10px_rgba(79,70,229,0.25)] active:border-b-[1px] active:translate-y-[2px] transition-all flex items-center gap-1.5 cursor-pointer">
              <span>Ввести</span> <i class="ph-bold ph-arrow-right"></i>
            </button>
          </div>
        </div>
      `;

      const inputVal = container.querySelector('#boo-tracer-step-input-val');
      const submitBtn = container.querySelector('#boo-tracer-step-input-btn');

      if (inputVal) {
        setTimeout(() => inputVal.focus(), 60);
        inputVal.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            this.submitStepInput();
          }
        });
      }

      submitBtn?.addEventListener('click', () => this.submitStepInput());
    }

    /** Отправка пошагового значения для input() */
    submitStepInput() {
      const inputEl = document.getElementById('boo-tracer-step-input-val');
      if (!inputEl) return;
      const val = inputEl.value;
      if (!Array.isArray(this.inputs)) this.inputs = [];
      this.inputs.push(val);
      this.isWaitingInput = false;

      if (window.boostudyLessonControl?.sendUi) {
        window.boostudyLessonControl.sendUi({
          kind: 'tracer_input_submit',
          input_val: val,
          inputs: this.inputs,
        });
      }

      this.pendingStep = this.frames.length;
      this.runTrace(this.lastCode, this.activeFileName, this.inputs);
    }

    /** Обновляет точку-индикатор наличия входных данных в кнопке Stdin */
    updateStdinIndicator() {
      const ind = document.getElementById('boo-tracer-stdin-indicator');
      if (ind) {
        ind.classList.toggle('hidden', !(this.inputs && this.inputs.length));
      }
    }

    /** Обновляет границы ползунка таймлайна */
    updateSliderBounds() {
      const slider = document.getElementById('boo-tracer-slider');
      const totalBadge = document.getElementById('boo-tracer-total-step');
      const max = Math.max(0, this.frames.length - 1);

      if (slider) {
        slider.max = max;
        slider.value = this.currentIndex;
      }
      if (totalBadge) {
        totalBadge.textContent = max;
      }
    }

    /** Шаг вперёд */
    stepForward() {
      if (this.currentIndex < this.frames.length - 1) {
        this.jumpToStep(this.currentIndex + 1);
        return true;
      }
      this.pause();
      return false;
    }

    /** Шаг назад */
    stepBackward() {
      if (this.currentIndex > 0) {
        this.jumpToStep(this.currentIndex - 1);
        return true;
      }
      return false;
    }

    /** Переход к конкретному шагу */
    jumpToStep(idx, skipSync = false) {
      if (idx < 0) idx = 0;
      if (idx >= this.frames.length) idx = this.frames.length - 1;
      this.currentIndex = idx;

      const slider = document.getElementById('boo-tracer-slider');
      const curBadge = document.getElementById('boo-tracer-cur-step');
      if (slider) slider.value = idx;
      if (curBadge) curBadge.textContent = idx;

      this.renderCurrentStep();
      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Воспроизведение / Пауза */
    togglePlay() {
      if (this.isPlaying) {
        this.pause();
      } else {
        this.play();
      }
    }

    play(skipSync = false) {
      if (this.isPlaying) return;
      this.isPlaying = true;
      this.updatePlayBtnUi(true);

      if (!skipSync) {
        this.broadcastSync();
      }

      const delay = Math.round(1000 / this.playSpeed);
      this.playTimer = setInterval(() => {
        const canContinue = this.stepForward();
        if (!canContinue) {
          this.pause();
          return;
        }

        const currentFrame = this.frames[this.currentIndex];
        if (currentFrame && this.breakpoints.has(currentFrame.line)) {
          this.pause();
        }
      }, delay);
    }

    pause(skipSync = false) {
      if (!this.isPlaying) return;
      this.isPlaying = false;
      if (this.playTimer) {
        clearInterval(this.playTimer);
        this.playTimer = null;
      }
      this.updatePlayBtnUi(false);

      if (!skipSync) {
        this.broadcastSync();
      }
    }

    /** Продолжить выполнение до ближайшего брейкпоинта */
    runToBreakpoint() {
      this.pause();
      let nextIdx = this.currentIndex + 1;
      while (nextIdx < this.frames.length) {
        const f = this.frames[nextIdx];
        if (this.breakpoints.has(f.line)) {
          this.jumpToStep(nextIdx);
          return;
        }
        nextIdx++;
      }
      // Если точек останова не встретилось, идём до конца
      this.jumpToStep(this.frames.length - 1);
    }

    updatePlayBtnUi(playing) {
      const playIcon = document.getElementById('boo-tracer-play-icon');
      const playBtn = document.getElementById('boo-tracer-btn-play');
      if (playIcon) {
        playIcon.className = playing ? 'ph-bold ph-pause' : 'ph-bold ph-play';
      }
      if (playBtn) {
        playBtn.classList.toggle('is-active-play', playing);
      }
    }

    /** Отрисовывает состояние памяти текущего шага */
    renderCurrentStep() {
      if (!this.frames.length || this.currentIndex >= this.frames.length) return;
      const frame = this.frames[this.currentIndex];

      // 0. Интерактивная карточка ожидания ввода input()
      this.renderInteractiveInputPrompt(frame);

      // 1. Подсветка строки в коде
      this.highlightExecutingLine(frame.line);

      // 2. Рендер стека и локальных переменных
      this.renderStackFrame(frame);

      // 3. Рендер объектов кучи (Heap)
      this.renderHeapObjects(frame);

      // 4. Рендер вывода print
      this.renderStdout(frame.stdout);

      // 5. Отрисовка динамических стрелок-указателей
      requestAnimationFrame(() => this.drawPointers(frame));
    }

    /** Подсветка текущей выполняемой строки в редакторе кода */
    highlightExecutingLine(lineNum) {
      this.clearActiveLineHighlight();
      if (!lineNum || lineNum < 1) return;
      this.activeLine = lineNum;

      // 1. Позиционируем плавающий оверлей активной строки
      const overlay = document.getElementById('code-tracer-active-line-overlay');
      const textarea = document.getElementById('code-editor-textarea');
      if (overlay && textarea) {
        overlay.classList.remove('hidden');
        this.repositionActiveLineOverlay();

        // Скроллим редактор, если строка не помещается в экран
        const lineTop = 24 + (lineNum - 1) * 22;
        const visibleTop = textarea.scrollTop;
        const visibleBottom = textarea.scrollTop + textarea.clientHeight;
        if (lineTop < visibleTop + 24 || lineTop > visibleBottom - 48) {
          textarea.scrollTop = Math.max(0, lineTop - Math.floor(textarea.clientHeight / 2));
          if (typeof window.syncCodeEditorScroll === 'function') {
            window.syncCodeEditorScroll();
          }
        }
      }

      // 2. Подсвечиваем строку в желобе номеров строк
      const gutter = document.getElementById('line-numbers-gutter');
      if (gutter) {
        const lineEl = gutter.querySelector(`.gutter-line[data-line="${lineNum}"]`) ||
                       Array.from(gutter.querySelectorAll('.gutter-line, div')).find((el) => {
                         const n = el.getAttribute('data-line') || el.textContent.trim();
                         return n === String(lineNum);
                       });
        if (lineEl) {
          lineEl.classList.add('line-gutter-active-tracer');
        }
      }
    }

    /** Пересчет Y-координаты оверлея при скролле редактора */
    repositionActiveLineOverlay() {
      if (!this.activeLine) return;
      const overlay = document.getElementById('code-tracer-active-line-overlay');
      const textarea = document.getElementById('code-editor-textarea');
      if (overlay && textarea) {
        const y = 24 + (this.activeLine - 1) * 22 - textarea.scrollTop;
        overlay.style.top = `${y}px`;
      }
    }

    clearActiveLineHighlight() {
      this.activeLine = null;
      const overlay = document.getElementById('code-tracer-active-line-overlay');
      if (overlay) overlay.classList.add('hidden');

      document.querySelectorAll('.line-gutter-active-tracer').forEach((el) => {
        el.classList.remove('line-gutter-active-tracer');
      });
      document.querySelectorAll('.code-editor-line-active-tracer').forEach((el) => {
        el.classList.remove('code-editor-line-active-tracer');
      });
    }

    /** Отрисовка стека вызовов и локальных переменных */
    renderStackFrame(frame) {
      const container = document.getElementById('boo-tracer-stack-container');
      const countBadge = document.getElementById('boo-tracer-vars-count');
      if (!container) return;

      const rawName = frame.func_name || 'main';
      const funcTitle = (rawName === '<module>' || rawName === '__main__') ? 'main' : rawName;

      const locals = frame.locals || {};
      const varKeys = Object.keys(locals);
      if (countBadge) countBadge.textContent = varKeys.length;

      if (varKeys.length === 0) {
        container.innerHTML = `
          <div class="boo-tracer-stack-frame">
            <div class="boo-tracer-frame-header">
              <span>${funcTitle}()</span>
              <span class="boo-tracer-frame-line">стр. ${frame.line}</span>
            </div>
            <div class="text-[11px] text-slate-500 italic p-1">Локальные переменные пока не объявлены</div>
          </div>
        `;
        return;
      }

      let varsHtml = '';
      varKeys.forEach((varName) => {
        const valInfo = locals[varName];
        const isMutated = frame.mutated_vars && frame.mutated_vars.includes(varName);

        let valDisplay = '';
        let isRef = false;
        let targetId = '';

        if (valInfo.is_ref) {
          isRef = true;
          targetId = valInfo.target_id;
          valDisplay = `<span class="boo-tracer-var-val is-ref" data-target-id="${targetId}">➔ ${valInfo.preview}</span>`;
        } else {
          const isStr = valInfo.type === 'str';
          valDisplay = `<span class="boo-tracer-var-val ${isStr ? 'is-str' : ''}">${isStr ? `"${valInfo.value}"` : valInfo.value}</span>`;
        }

        varsHtml += `
          <div class="boo-tracer-var-row ${isMutated ? 'mutated' : ''}" id="tracer-var-row-${varName}">
            <div class="boo-tracer-var-left">
              <span class="boo-tracer-var-name">${varName}</span>
              <span class="boo-tracer-var-type">${valInfo.type}</span>
            </div>
            <div class="boo-tracer-var-right">
              ${valDisplay}
            </div>
          </div>
        `;
      });

      container.innerHTML = `
        <div class="boo-tracer-stack-frame">
          <div class="boo-tracer-frame-header">
            <span>${funcTitle}()</span>
            <span class="boo-tracer-frame-line">стр. ${frame.line}</span>
          </div>
          <div class="boo-tracer-vars-list">
            ${varsHtml}
          </div>
        </div>
      `;
    }

    /** Отрисовка объектов кучи (Heap) */
    renderHeapObjects(frame) {
      const container = document.getElementById('boo-tracer-heap-container');
      const countBadge = document.getElementById('boo-tracer-heap-count');
      if (!container) return;

      const heap = frame.heap || {};
      const heapIds = Object.keys(heap);
      if (countBadge) countBadge.textContent = heapIds.length;

      if (heapIds.length === 0) {
        container.innerHTML = `<div class="text-[11px] text-slate-500 italic p-1">В куче нет составных объектов (списков/словарей)</div>`;
        return;
      }

      let heapHtml = '';
      heapIds.forEach((objId) => {
        const obj = heap[objId];
        const isMutated = frame.mutated_heap_ids && frame.mutated_heap_ids.includes(objId);

        let bodyHtml = '';

        if (obj.type === 'list' || obj.type === 'tuple') {
          let cellsHtml = '';
          const items = obj.items || [];
          items.forEach((item, idx) => {
            const itemVal = item.is_ref ? `➔ #${item.target_id.slice(-4)}` : (item.type === 'str' ? `"${item.value}"` : item.value);
            // Проверка, активен ли этот индекс в цикле
            const isLoopActive = frame.locals && Object.values(frame.locals).some((loc) => loc.value === idx || loc.value === item.value);

            cellsHtml += `
              <div class="boo-tracer-array-cell ${isLoopActive ? 'is-loop-active' : ''}">
                <div class="boo-tracer-cell-index">${idx}</div>
                <div class="boo-tracer-cell-value">${itemVal}</div>
              </div>
            `;
          });

          bodyHtml = `<div class="boo-tracer-array-view">${cellsHtml}</div>`;
        } else if (obj.type === 'dict') {
          let rowsHtml = '';
          const entries = obj.entries || [];
          entries.forEach((entry) => {
            const v = entry.value;
            const valStr = v.is_ref ? `➔ #${v.target_id.slice(-4)}` : (v.type === 'str' ? `"${v.value}"` : v.value);
            rowsHtml += `
              <div class="boo-tracer-dict-row">
                <span class="boo-tracer-dict-key">${entry.key}</span>
                <span class="boo-tracer-dict-sep">:</span>
                <span class="boo-tracer-dict-val">${valStr}</span>
              </div>
            `;
          });
          bodyHtml = `<div class="boo-tracer-dict-view">${rowsHtml}</div>`;
        } else {
          bodyHtml = `<div class="text-xs text-slate-300 p-1">${obj.type} (${obj.length} элементов)</div>`;
        }

        heapHtml += `
          <div class="boo-tracer-heap-card ${isMutated ? 'highlighted-ref' : ''}" id="tracer-heap-card-${objId}" data-heap-id="${objId}">
            <div class="boo-tracer-heap-header">
              <span class="font-bold text-indigo-300 text-xs">${obj.type.toUpperCase()} [${obj.length}]</span>
              <span class="boo-tracer-heap-id">#${objId.slice(-6)}</span>
            </div>
            ${bodyHtml}
          </div>
        `;
      });

      container.innerHTML = heapHtml;
    }

    /** Отрисовка динамических неоновых стрелок связей Stack -> Heap */
    drawPointers(frame) {
      const svg = document.getElementById('boo-tracer-svg-layer');
      const body = document.getElementById('boo-tracer-body');
      if (!svg || !body) return;

      svg.innerHTML = '';
      const bodyRect = body.getBoundingClientRect();
      const locals = frame.locals || {};

      // Маркер стрелки
      const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      defs.innerHTML = `
        <marker id="boo-tracer-arrow-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />
        </marker>
      `;
      svg.appendChild(defs);

      Object.entries(locals).forEach(([varName, valInfo]) => {
        if (!valInfo.is_ref || !valInfo.target_id) return;

        const varRow = document.getElementById(`tracer-var-row-${varName}`);
        const heapCard = document.getElementById(`tracer-heap-card-${valInfo.target_id}`);
        if (!varRow || !heapCard) return;

        const refSocket = varRow.querySelector('.is-ref') || varRow;
        const startRect = refSocket.getBoundingClientRect();
        const endRect = heapCard.getBoundingClientRect();

        const x1 = startRect.right - bodyRect.left;
        const y1 = startRect.top + startRect.height / 2 - bodyRect.top + body.scrollTop;

        const x2 = endRect.left - bodyRect.left;
        const y2 = endRect.top + 16 - bodyRect.top + body.scrollTop;

        // Плавная кривая Безье
        const dx = Math.abs(x2 - x1);
        const cp1x = x1 + Math.max(30, dx * 0.4);
        const cp1y = y1;
        const cp2x = x2 - Math.max(30, dx * 0.4);
        const cp2y = y2;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`);
        path.setAttribute('class', 'boo-tracer-pointer-arrow');
        path.setAttribute('marker-end', 'url(#boo-tracer-arrow-head)');

        svg.appendChild(path);
      });
    }

    /** Отрисовка stdout */
    renderStdout(stdout) {
      const box = document.getElementById('boo-tracer-stdout-box');
      if (!box) return;

      if (!stdout || !stdout.trim()) {
        box.innerHTML = `<span class="boo-tracer-stdout-empty">Вывод программы пуст</span>`;
      } else {
        box.textContent = stdout;
      }
    }

    renderError(msg) {
      const stackCont = document.getElementById('boo-tracer-stack-container');
      if (stackCont) {
        stackCont.innerHTML = `
          <div class="p-3 rounded-lg bg-rose-950/80 border border-rose-500/40 text-rose-300 text-xs font-mono">
            <strong>Ошибка трассировки:</strong><br>${msg}
          </div>
        `;
      }
    }

    /** Двусторонняя синхронизация через Socket.IO комнаты урока */
    broadcastSync() {
      if (!window.boostudyLessonControl?.sendUi) return;

      window.boostudyLessonControl.sendUi({
        kind: 'tracer_state',
        step: this.currentIndex,
        playing: this.isPlaying,
        speed: this.playSpeed,
        file_name: this.activeFileName,
        is_open: this.isOpen,
        is_detached: this.isDetached,
        breakpoints: Array.from(this.breakpoints),
        code: this.lastCode,
        inputs: this.inputs || [],
      });
    }

    /** Применение удаленного состояния трассировщика из сети */
    applyRemoteState(payload) {
      if (!payload) return;

      // 1. Синхронизация точек останова (брейкпоинтов)
      if (Array.isArray(payload.breakpoints)) {
        const incomingBp = new Set(payload.breakpoints);
        let changed = incomingBp.size !== this.breakpoints.size;
        if (!changed) {
          for (const b of incomingBp) {
            if (!this.breakpoints.has(b)) {
              changed = true;
              break;
            }
          }
        }
        if (changed) {
          this.breakpoints = incomingBp;
          this.updateGutterBreakpoints();
        }
      }

      // 2. Синхронизация открытия / закрытия / перезапуска трассировки
      if (typeof payload.is_open === 'boolean' && payload.is_open !== this.isOpen) {
        if (payload.is_open) {
          if (typeof payload.step === 'number') {
            this.pendingStep = payload.step;
          }
          this.open(payload.code || null, payload.file_name, true);
        } else {
          this.close(true);
        }
      } else if (payload.is_open && payload.code && payload.code !== this.lastCode) {
        if (typeof payload.step === 'number') {
          this.pendingStep = payload.step;
        }
        this.open(payload.code, payload.file_name, true);
      }

      // 3. Синхронизация открепления/прикрепления панели
      if (typeof payload.is_detached === 'boolean' && payload.is_detached !== this.isDetached) {
        this.toggleDockMode(true);
      }

      // 4. Синхронизация воспроизведения / паузы
      if (typeof payload.playing === 'boolean') {
        if (payload.playing && !this.isPlaying) {
          this.isPlaying = true;
          this.updatePlayBtnUi(true);
        } else if (!payload.playing && this.isPlaying) {
          this.pause(true);
        }
      }

      // 5. Синхронизация текущего шага
      if (typeof payload.step === 'number' && payload.step !== this.currentIndex) {
        if (this.isLoading) {
          this.pendingStep = payload.step;
        } else {
          this.jumpToStep(payload.step, true);
        }
      }

      // 6. Синхронизация скорости
      if (typeof payload.speed === 'number' && payload.speed !== this.playSpeed) {
        this.playSpeed = payload.speed;
        const panel = document.getElementById('boo-tracer-main-panel');
        if (panel) {
          panel.querySelectorAll('.boo-tracer-speed-btn').forEach((b) => {
            b.classList.toggle('active', parseFloat(b.dataset.speed) === payload.speed);
          });
        }
      }

      // 7. Синхронизация входных данных (stdin / input)
      if (Array.isArray(payload.inputs)) {
        this.inputs = payload.inputs;
      }
      if (payload.kind === 'tracer_input_submit') {
        if (Array.isArray(payload.inputs)) {
          this.inputs = payload.inputs;
        } else if (payload.input_val) {
          if (!Array.isArray(this.inputs)) this.inputs = [];
          this.inputs.push(payload.input_val);
        }
        this.runTrace(this.lastCode, this.activeFileName, this.inputs);
      }
    }
  }

  // Создаем глобальный синглтон
  const tracerInstance = new BooTracerEngine();
  return tracerInstance;
});
