/**
 * =============================================================================
 * BOOSTUDY POCKET OS — SPRINT 1.1
 * Light Experience Rebuild & Mobile Interaction Quality
 * Dedicated Mobile Student Classroom Experience & Ergonomic Focus Navigation
 * =============================================================================
 */

(function () {
  'use strict';

  const BooStudyPocketOS = {
    active: false,
    currentFocus: 'board', // 'board' | 'code' | 'task'
    socket: null,
    lastViewportSentAt: 0,
    viewportRaf: null,
    toastTimeout: null,
    lastTargetCoords: null,
    lastRunCode: null,
    activeRunId: null,

    // 1. Initialization & Presentation Detection
    init() {
      const isFeatureEnabled = Boolean(
        window.__pocketOsFeatureEnabled ||
        window.trainerOsConfig?.pocket_os_enabled ||
        document.body.classList.contains('pocket-os-active')
      );
      const isTeacher = Boolean(
        window.trainerOsConfig?.is_studio_teacher ||
        window.trainerOsConfig?.room_role === 'teacher' ||
        window.boostudyLessonControl?.getRole?.() === 'teacher'
      );

      // Server-side guard: never activate for teachers or if flag disabled
      if (!isFeatureEnabled || isTeacher) {
        return;
      }

      // Detect mobile device, touch screen, or small screen dimension
      const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
      const isMobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
      const minScreenDim = Math.min(
        window.screen?.width || window.innerWidth,
        window.screen?.height || window.innerHeight,
        window.innerWidth,
        window.innerHeight
      );
      const isMobileDevice = isMobileUA || (isTouchDevice && minScreenDim <= 768);
      const isMobileSized = window.innerWidth <= 768 || (window.innerHeight <= 500 && (isTouchDevice || minScreenDim <= 768));
      const urlParams = new URLSearchParams(window.location.search);
      const isParamForced = urlParams.get('pocket_os') === '1';

      if (!isMobileDevice && !isMobileSized && !isParamForced) {
        return;
      }

      this.active = true;
      document.documentElement.classList.add('pocket-os-active');
      document.body.classList.add('pocket-os-active');
      document.body.dataset.pocketFocus = this.currentFocus;

      // Isolate presentation layer from WindowManager desktop inline styles
      this.isolatePresentationLayer();

      this.buildShell();
      this.bindNavigation();
      this.bindVirtualSymbols();
      this.bindCanvasGestures();
      this.bindSocketEvents();
      this.initLiveKitIntegration();
      this.bindViewportAndKeyboard();
      this.bindCodeChangeListener();
      this.enforceReadOnlyCanvas();
      this.reportMobileViewport(true);

      // Lock confirmed mobile mode across window resize and orientation change
      window.addEventListener('resize', () => {
        this.reportMobileViewport(true);
        if (this.currentFocus === 'task') {
          this.renderTaskState();
        }
      });
      window.addEventListener('orientationchange', () => {
        this.reportMobileViewport(true);
      });

      console.info('[BooStudy Pocket OS 1.2] Active in mobile mode.');
    },

    stripInlineCoordinates(el) {
      if (!el) return;
      el.style.removeProperty('width');
      el.style.removeProperty('height');
      el.style.removeProperty('top');
      el.style.removeProperty('left');
      el.style.removeProperty('right');
      el.style.removeProperty('bottom');
      el.style.removeProperty('inset');
      el.style.removeProperty('transform');
    },

    isolatePresentationLayer() {
      // Preserve desktop window geometry before Pocket presentation takes over
      ['code-window', 'canvas-window', 'task-window'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) {
          if (!el.dataset.pocketSavedStyle) {
            el.dataset.pocketSavedStyle = el.getAttribute('style') || '';
          }
          this.stripInlineCoordinates(el);
        }
      });
    },

    restoreDesktopLayer() {
      ['code-window', 'canvas-window', 'task-window'].forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.dataset.pocketSavedStyle !== undefined) {
          el.setAttribute('style', el.dataset.pocketSavedStyle);
          delete el.dataset.pocketSavedStyle;
          window.windowManager?.ensureRoomWindowAccessible?.(el);
        }
      });
    },

    // Resolve socket from global instances
    getSocket() {
      if (this.socket && this.socket.connected) return this.socket;
      if (window.boostudyLessonSocket && window.boostudyLessonSocket.connected) {
        this.socket = window.boostudyLessonSocket;
        return this.socket;
      }
      if (window.state?.socket && window.state.socket.connected) {
        this.socket = window.state.socket;
        return this.socket;
      }
      if (window.boostudyWhiteboard?.state?.socket && window.boostudyWhiteboard.state.socket.connected) {
        this.socket = window.boostudyWhiteboard.state.socket;
        return this.socket;
      }
      return null;
    },

    getState() {
      return window.state || window.boostudyWhiteboard?.state || {};
    },

    // 2. Build Light Mobile Shell UI
    buildShell() {
      const arena = document.getElementById('trainer-arena-view');
      if (!arena) return;

      // Create Shell Container
      let shell = document.getElementById('pocket-os-shell');
      if (!shell) {
        shell = document.createElement('div');
        shell.id = 'pocket-os-shell';
        arena.appendChild(shell);
      }

      const lessonTitle = window.trainerOsConfig?.room_title || 'Занятие BooStudy';

      shell.innerHTML = `
        <!-- Top Compact Header (Light, clean, authentic BooStudy) -->
        <header class="pocket-header" id="pocket-header">
          <div class="pocket-header-left">
            <button type="button" class="pocket-header-exit-btn" id="pocket-exit-btn" title="Выйти из урока">
              <i class="ph-bold ph-arrow-left"></i>
            </button>
            <div class="pocket-header-info">
              <span class="pocket-header-title">${this.escapeHtml(lessonTitle)}</span>
              <span class="pocket-header-subtitle">
                <span class="pocket-status-dot"></span>
                <span id="pocket-teacher-status">Преподаватель в сети</span>
              </span>
            </div>
          </div>
          <div class="pocket-header-right">
            <button type="button" class="pocket-btn-join-call" id="pocket-btn-join-call" title="Присоединиться к видеоуроку">
              <i class="ph-bold ph-video-camera"></i>
              <span>Войти в звонок</span>
            </button>
            <button type="button" class="pocket-av-toggle" id="pocket-mic-toggle" title="Микрофон" style="display:none;" aria-label="Микрофон">
              <i class="ph-bold ph-microphone"></i>
            </button>
            <button type="button" class="pocket-av-toggle" id="pocket-cam-toggle" title="Камера" style="display:none;" aria-label="Камера">
              <i class="ph-bold ph-video-camera"></i>
            </button>
            <button type="button" class="pocket-call-leave-btn" id="pocket-call-leave" title="Покинуть звонок" style="display:none;" aria-label="Покинуть звонок">
              <i class="ph-bold ph-phone-disconnect"></i>
            </button>
          </div>
        </header>

        <!-- Focus Surface -->
        <main class="pocket-focus-surface" id="pocket-focus-surface">
          <!-- Floating Board Controls -->
          <div class="pocket-board-controls" id="pocket-board-controls">
            <button type="button" class="pocket-board-btn is-rejoin" id="pocket-btn-rejoin" title="К преподавателю">
              <i class="ph-bold ph-crosshair"></i>
            </button>
            <button type="button" class="pocket-board-btn" id="pocket-btn-zoom-in" title="Увеличить">
              <i class="ph-bold ph-plus"></i>
            </button>
            <button type="button" class="pocket-board-btn" id="pocket-btn-zoom-out" title="Уменьшить">
              <i class="ph-bold ph-minus"></i>
            </button>
            <button type="button" class="pocket-board-btn" id="pocket-btn-zoom-fit" title="Сбросить масштаб">
              <i class="ph-bold ph-corners-out"></i>
            </button>
          </div>

          <!-- Read-only badge on board -->
          <div class="pocket-read-only-pill" id="pocket-read-only-pill">
            <i class="ph-bold ph-lock-simple"></i>
            <span>Доска учителя · Просмотр</span>
          </div>

          <!-- Floating LiveKit Video Pill (Compact & Informative) -->
          <div class="pocket-video-pill is-compact-indicator" id="pocket-video-pill" title="Видеосвязь">
            <div class="pocket-video-pill-avatar" id="pocket-video-pill-avatar">
              <span class="pocket-status-dot"></span>
              <span id="pocket-video-pill-name">Учитель</span>
            </div>
            <div id="pocket-video-pill-stream"></div>
          </div>
        </main>

        <!-- Bottom Navigation Bar (Light, 3 tabs, accessible) -->
        <nav class="pocket-nav-bar" id="pocket-nav-bar" aria-label="Переключение фокуса">
          <button type="button" class="pocket-nav-item is-active" data-focus="board" id="pocket-nav-board">
            <i class="ph-bold ph-chalkboard-simple"></i>
            <span>Доска</span>
          </button>
          <button type="button" class="pocket-nav-item" data-focus="code" id="pocket-nav-code">
            <i class="ph-bold ph-code"></i>
            <span>Код</span>
          </button>
          <button type="button" class="pocket-nav-item" data-focus="task" id="pocket-nav-task">
            <i class="ph-bold ph-check-square-offset"></i>
            <span>Задание</span>
          </button>
        </nav>

        <!-- Focus Suggestion Toast Card (Light, tactful) -->
        <div class="pocket-toast" id="pocket-toast" role="alert" aria-live="polite">
          <div class="pocket-toast-content">
            <div class="pocket-toast-icon" id="pocket-toast-icon">
              <i class="ph-bold ph-chalkboard-simple"></i>
            </div>
            <div class="pocket-toast-text">
              <span class="pocket-toast-title" id="pocket-toast-title">Учитель предлагает фокус</span>
              <span class="pocket-toast-subtitle" id="pocket-toast-subtitle">Нажмите, чтобы перейти</span>
            </div>
          </div>
          <div class="pocket-toast-actions">
            <button type="button" class="pocket-toast-btn-action pocket-toast-btn" id="pocket-toast-btn-action">Перейти</button>
            <button type="button" class="pocket-toast-btn-dismiss" id="pocket-toast-btn-dismiss" title="Закрыть">
              <i class="ph-bold ph-x"></i>
            </button>
          </div>
        </div>
      `;

      // Header exit button
      document.getElementById('pocket-exit-btn')?.addEventListener('click', () => {
        if (confirm('Вы уверены, что хотите выйти из урока?')) {
          window.location.href = '/schedule';
        }
      });


      // Board Controls bindings
      document.getElementById('pocket-btn-zoom-in')?.addEventListener('click', () => {
        window.BooCanvasOverlay?.zoomIn?.();
        this.reportMobileViewport();
      });
      document.getElementById('pocket-btn-zoom-out')?.addEventListener('click', () => {
        window.BooCanvasOverlay?.zoomOut?.();
        this.reportMobileViewport();
      });
      document.getElementById('pocket-btn-zoom-fit')?.addEventListener('click', () => {
        this.fitCanvasContent();
      });
      document.getElementById('pocket-btn-rejoin')?.addEventListener('click', () => {
        this.rejoinTeacherCamera();
      });

      // Toast Dismiss
      document.getElementById('pocket-toast-btn-dismiss')?.addEventListener('click', () => {
        this.dismissToast();
      });

      // Mount Code Enhancements
      this.mountCodeEnhancements();
    },

    // 3. Mount Ergonomic Python Code Enhancements (Single light header, no duplication)
    mountCodeEnhancements() {
      const codeWindow = document.getElementById('code-window');
      const textarea = document.getElementById('code-editor-textarea');
      if (!codeWindow || !textarea) return;

      // Prevent mobile auto-caps and auto-correct
      textarea.setAttribute('autocapitalize', 'off');
      textarea.setAttribute('autocorrect', 'off');
      textarea.setAttribute('spellcheck', 'false');

      // Check if virtual symbol toolbar already exists
      if (document.getElementById('pocket-virtual-symbols')) return;

      // Virtual Symbol Toolbar (Horizontally scrollable)
      const symbolsBar = document.createElement('div');
      symbolsBar.id = 'pocket-virtual-symbols';
      symbolsBar.className = 'pocket-virtual-symbols';

      const symbols = [
        { label: 'Tab', val: '    ', isWide: true },
        { label: '(', val: '(' },
        { label: ')', val: ')' },
        { label: '[', val: '[' },
        { label: ']', val: ']' },
        { label: '{', val: '{' },
        { label: '}', val: '}' },
        { label: ':', val: ':' },
        { label: '=', val: '=' },
        { label: '"', val: '"' },
        { label: "'", val: "'" },
        { label: '_', val: '_' },
        { label: '+', val: '+' },
        { label: '-', val: '-' },
        { label: '*', val: '*' },
        { label: '/', val: '/' },
        { label: '%', val: '%' },
        { label: '#', val: '#' },
        { label: ',', val: ', ' },
        { label: '<', val: '<' },
        { label: '>', val: '>' },
      ];

      symbols.forEach((sym) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `pocket-symbol-key${sym.isWide ? ' is-wide' : ''}`;
        btn.textContent = sym.label;
        btn.dataset.val = sym.val;
        symbolsBar.appendChild(btn);
      });

      // Single Code Actions Bar (File indicator, save status, console toggle, run button)
      const actionsBar = document.createElement('div');
      actionsBar.id = 'pocket-code-actions-bar';
      actionsBar.className = 'pocket-code-header';
      actionsBar.innerHTML = `
        <div class="pocket-code-filename">
          <i class="ph-bold ph-file-code"></i>
          <span id="pocket-code-filename-label">main.py</span>
          <span id="pocket-code-permission-badge" class="pocket-code-perm-badge is-readonly"><i class="ph-bold ph-lock-key"></i> Только чтение</span>
          <span class="pocket-code-save-status"><span class="pocket-code-save-dot"></span><span class="pocket-code-save-text">Сохранено</span></span>
        </div>
        <div class="pocket-code-actions-top">
          <button type="button" class="pocket-btn-console-toggle" id="pocket-btn-console-toggle" title="Показать/скрыть консоль">
            <i class="ph-bold ph-terminal-window"></i> <span class="pocket-btn-label">Консоль</span>
          </button>
          <button type="button" class="pocket-btn-run" id="pocket-btn-run" title="Запустить Python код">
            <i class="ph-bold ph-play"></i> <span class="pocket-btn-label">Запуск</span>
          </button>
        </div>
      `;

      // Terminal Output Bottom Drawer (Light, clean)
      const terminalDrawer = document.createElement('div');
      terminalDrawer.id = 'pocket-terminal-drawer';
      terminalDrawer.className = 'pocket-terminal-drawer is-collapsed';
      terminalDrawer.innerHTML = `
        <div class="pocket-terminal-header">
          <div style="display:flex;align-items:center;gap:6px;">
            <span><i class="ph-bold ph-terminal"></i> Консоль</span>
            <span id="pocket-terminal-stale-badge" class="pocket-terminal-stale-badge" style="display:none;">
              <i class="ph-bold ph-pencil-simple"></i> код изменён
            </span>
          </div>
          <div class="pocket-terminal-actions">
            <button type="button" class="pocket-terminal-clear-btn" id="pocket-terminal-clear-btn">Очистить</button>
            <button type="button" id="pocket-terminal-close-btn" style="background:none;border:none;color:var(--pocket-text-muted);cursor:pointer;">
              <i class="ph-bold ph-caret-down text-sm"></i>
            </button>
          </div>
        </div>
        <div class="pocket-terminal-body" id="pocket-terminal-body">
          <div id="pocket-terminal-placeholder" style="color:var(--pocket-text-muted);">Здесь появится результат выполнения программы...</div>
        </div>
      `;

      // Prepend actions bar at top of code window
      codeWindow.prepend(actionsBar);
      // Append virtual symbol bar after editor body
      codeWindow.appendChild(symbolsBar);
      // Append terminal drawer at the bottom
      codeWindow.appendChild(terminalDrawer);

      // Run button handler
      document.getElementById('pocket-btn-run')?.addEventListener('click', () => {
        this.runPythonCode();
      });

      // Console toggle handler
      document.getElementById('pocket-btn-console-toggle')?.addEventListener('click', () => {
        this.toggleTerminalDrawer();
      });
      terminalDrawer.querySelector('.pocket-terminal-header')?.addEventListener('click', (e) => {
        if (e.target.closest('#pocket-terminal-clear-btn') || e.target.closest('#pocket-terminal-close-btn')) return;
        this.toggleTerminalDrawer();
      });
      document.getElementById('pocket-terminal-close-btn')?.addEventListener('click', () => {
        this.toggleTerminalDrawer(false);
      });
      document.getElementById('pocket-terminal-clear-btn')?.addEventListener('click', () => {
        const body = document.getElementById('pocket-terminal-body');
        if (body) body.innerHTML = '<div style="color:var(--pocket-text-muted);">Консоль очищена.</div>';
        const desktopOut = document.getElementById('terminal-console-output');
        if (desktopOut) desktopOut.innerHTML = '';
      });

      this.updateCodePermissionBadge();
    },

    updateCodePermissionBadge() {
      const badge = document.getElementById('pocket-code-permission-badge');
      const textarea = document.getElementById('code-editor-textarea');
      const runBtn = document.getElementById('pocket-btn-run');
      const control = typeof window.controlState === 'function' ? window.controlState() : (window.boostudyLessonControl?.getControl?.() || {});
      const isTeacher = window.state?.role === 'teacher' || Boolean(window.trainerOsConfig?.is_studio_teacher);
      const isFrozen = Boolean(control.freeze_student);
      const studentAllowed = Boolean(control.student_code_editing);
      const canEdit = isTeacher || (!isFrozen && studentAllowed);
      const canRun = isTeacher || !isFrozen;

      if (textarea) {
        textarea.readOnly = !canEdit;
        if (!canEdit) {
          textarea.setAttribute('aria-readonly', 'true');
        } else {
          textarea.removeAttribute('aria-readonly');
        }
      }

      if (runBtn) {
        runBtn.disabled = !canRun;
        if (!canRun) {
          runBtn.title = 'Режим демонстрации (запуск заблокирован)';
        } else {
          runBtn.title = 'Запустить Python код';
        }
      }

      if (!badge) return;

      if (isTeacher) {
        badge.className = `pocket-code-perm-badge ${studentAllowed ? 'is-editable' : 'is-readonly'}`;
        badge.innerHTML = studentAllowed ? '<i class="ph-bold ph-users"></i> Ученик пишет' : '<i class="ph-bold ph-lock-key"></i> Только вы';
        badge.title = studentAllowed ? 'Ученику разрешено совместное редактирование кода' : 'Ученик только наблюдает за вашим кодом';
      } else if (isFrozen) {
        badge.className = 'pocket-code-perm-badge is-frozen';
        badge.innerHTML = '<i class="ph-bold ph-lock-key"></i> Демонстрация';
        badge.title = 'Преподаватель включил режим демонстрации (ввод заблокирован)';
      } else if (canEdit) {
        badge.className = 'pocket-code-perm-badge is-editable';
        badge.innerHTML = '<i class="ph-bold ph-pencil-simple-line"></i> Можно писать';
        badge.title = 'Вам разрешено редактировать код';
      } else {
        badge.className = 'pocket-code-perm-badge is-readonly';
        badge.innerHTML = '<i class="ph-bold ph-lock-key"></i> Только чтение';
        badge.title = 'Преподаватель пишет код (режим демонстрации)';
      }
    },

    // 4. Bind Virtual Symbols Insertion
    bindVirtualSymbols() {
      const symbolsBar = document.getElementById('pocket-virtual-symbols');
      const textarea = document.getElementById('code-editor-textarea');
      if (!symbolsBar || !textarea) return;

      let lastSelection = {
        start: textarea.value.length,
        end: textarea.value.length,
      };

      const updateSelection = () => {
        if (typeof textarea.selectionStart === 'number') {
          lastSelection.start = textarea.selectionStart;
          lastSelection.end = textarea.selectionEnd;
        }
      };

      textarea.addEventListener('select', updateSelection);
      textarea.addEventListener('keyup', updateSelection);
      textarea.addEventListener('click', updateSelection);
      textarea.addEventListener('input', updateSelection);

      let lastInsertTime = 0;
      const doInsert = (btn, e) => {
        if (!btn) return;
        if (e && e.preventDefault) e.preventDefault();
        if (textarea.readOnly) return;
        if (window.controlState?.()?.freeze_student) return;
        if (window.boostudyLessonControl?.canEditCode && !window.boostudyLessonControl.canEditCode()) return;

        const now = Date.now();
        if (now - lastInsertTime < 60) return;
        lastInsertTime = now;

        const insertVal = btn.dataset.val;
        if (typeof insertVal !== 'string') return;

        const isFocused = (document.activeElement === textarea);
        const isKbOpen = isFocused || document.body.classList.contains('pocket-keyboard-open');

        const start = isFocused ? (textarea.selectionStart ?? lastSelection.start) : lastSelection.start;
        const end = isFocused ? (textarea.selectionEnd ?? lastSelection.end) : lastSelection.end;
        const val = textarea.value;

        textarea.value = val.substring(0, start) + insertVal + val.substring(end);
        const newPos = start + insertVal.length;
        lastSelection.start = newPos;
        lastSelection.end = newPos;

        if (typeof textarea.setSelectionRange === 'function') {
          textarea.setSelectionRange(newPos, newPos);
        }

        // Only retain focus if keyboard was already open and active
        // If keyboard was closed, do NOT call textarea.focus() to avoid summoning on-screen keyboard
        if (isKbOpen && isFocused) {
          textarea.focus();
        }

        // Trigger input event for OT synchronization & syntax highlighting
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        if (typeof window.onCodeEditorInput === 'function') {
          window.onCodeEditorInput(textarea.value);
        }
      };

      // Pointerdown handles tap without blurring textarea or summoning keyboard
      let lastPointerDownTime = 0;
      symbolsBar.addEventListener('pointerdown', (e) => {
        const btn = e.target.closest('.pocket-symbol-key');
        if (btn) {
          e.preventDefault();
          lastPointerDownTime = Date.now();
          doInsert(btn, e);
        }
      });

      symbolsBar.addEventListener('click', (e) => {
        const btn = e.target.closest('.pocket-symbol-key');
        if (btn) {
          e.preventDefault();
          if (Date.now() - lastPointerDownTime < 500) {
            return;
          }
          doInsert(btn, e);
        }
      });
    },

    // 5. Navigation & Focus Manager
    bindNavigation() {
      const navBar = document.getElementById('pocket-nav-bar');
      if (!navBar) return;

      navBar.addEventListener('click', (e) => {
        const item = e.target.closest('.pocket-nav-item');
        if (!item) return;
        const targetFocus = item.dataset.focus;
        if (targetFocus) {
          this.switchFocus(targetFocus);
        }
      });
    },

    switchFocus(mode, options = {}) {
      if (!['board', 'code', 'task'].includes(mode)) return;
      this.currentFocus = mode;
      document.body.dataset.pocketFocus = mode;

      // Strip any conflicting inline coordinates to ensure 100% full-screen mobile geometry
      ['canvas-window', 'code-window', 'task-window'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) this.stripInlineCoordinates(el);
      });

      // Update Nav buttons
      document.querySelectorAll('.pocket-nav-item').forEach((item) => {
        const active = item.dataset.focus === mode;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-selected', String(active));
      });

      // Read-only indicator on board
      const boardControls = document.getElementById('pocket-board-controls');
      const boardPill = document.getElementById('pocket-read-only-pill');
      if (boardControls) boardControls.style.display = mode === 'board' ? 'flex' : 'none';
      if (boardPill) boardPill.style.display = mode === 'board' ? 'inline-flex' : 'none';

      // Mode-specific actions
      if (mode === 'board') {
        const win = document.getElementById('canvas-window');
        if (win) { win.classList.remove('hidden'); win.style.display = 'flex'; win.style.opacity = '1'; }
        this.enforceReadOnlyCanvas();
        window.BooCanvasOverlay?.redraw?.();
      } else if (mode === 'code') {
        const win = document.getElementById('code-window');
        if (win) { win.classList.remove('hidden'); win.style.display = 'flex'; win.style.opacity = '1'; }
        if (!document.getElementById('pocket-code-actions-bar')) {
          this.mountCodeEnhancements();
        }
        this.updateCodePermissionBadge();
        if (typeof window.updateCodeHighlight === 'function') {
          window.updateCodeHighlight();
        }
      } else if (mode === 'task') {
        const win = document.getElementById('task-window');
        if (win) { win.classList.remove('hidden'); win.style.display = 'flex'; win.style.opacity = '1'; }
        this.renderTaskState();
      }

      // Sync viewport state to teacher immediately
      this.reportMobileViewport(true);
    },

    // Task Focus State Handler: Empty vs Active
    renderTaskState() {
      const taskBody = document.querySelector('#task-window .task-window-body');
      if (!taskBody) return;

      let emptyEl = document.getElementById('pocket-task-empty-state');
      const currentContent = document.getElementById('task-current-content');
      const submitForm = document.getElementById('student-classwork-submit-form');
      const attachedList = document.getElementById('task-attached-list');

      const contentText = currentContent?.innerText || currentContent?.textContent || '';
      const isPlaceholder = contentText.includes('нет прикреплённых заданий') ||
        contentText.includes('Преподаватель пока не открыл задание') ||
        (!contentText.trim() && !window.room_task && !attachedList?.querySelector('button'));

      if (isPlaceholder) {
        if (!emptyEl) {
          emptyEl = document.createElement('div');
          emptyEl.id = 'pocket-task-empty-state';
          emptyEl.className = 'pocket-task-empty-state';
          emptyEl.innerHTML = `
            <div class="pocket-task-empty-icon">
              <i class="ph-bold ph-tray"></i>
            </div>
            <h3 class="pocket-task-empty-title">Пока нет задания</h3>
            <p class="pocket-task-empty-desc">Преподаватель ещё не открыл задание для тебя. Вы можете работать на доске или в редакторе кода.</p>
            <div class="pocket-task-empty-actions">
              <button type="button" class="pocket-task-empty-btn is-primary" id="pocket-task-go-board">
                <i class="ph-bold ph-chalkboard-simple"></i> Перейти к доске
              </button>
              <button type="button" class="pocket-task-empty-btn" id="pocket-task-go-code">
                <i class="ph-bold ph-code"></i> В редактор кода
              </button>
            </div>
          `;
          taskBody.prepend(emptyEl);
          document.getElementById('pocket-task-go-board')?.addEventListener('click', () => this.switchFocus('board'));
          document.getElementById('pocket-task-go-code')?.addEventListener('click', () => this.switchFocus('code'));
        }
        emptyEl.style.display = 'flex';
        if (currentContent) currentContent.style.display = 'none';
        const taskTitle = document.getElementById('task-current-title');
        if (taskTitle) taskTitle.style.display = 'none';
        if (submitForm) submitForm.classList.add('hidden');
      } else {
        if (emptyEl) emptyEl.style.display = 'none';
        if (currentContent) {
          currentContent.style.display = 'block';
          // Wrap wide tables in responsive horizontal scroll wrapper if not yet wrapped
          const tables = currentContent.querySelectorAll('table:not(.pocket-wrapped)');
          tables.forEach((tbl) => {
            tbl.classList.add('pocket-wrapped');
            const wrapper = document.createElement('div');
            wrapper.className = 'pocket-table-container';
            wrapper.setAttribute('tabindex', '0');
            wrapper.setAttribute('role', 'region');
            wrapper.setAttribute('aria-label', 'Таблица весовой матрицы');
            tbl.parentNode.insertBefore(wrapper, tbl);
            wrapper.appendChild(tbl);
          });
        }
        const taskTitle = document.getElementById('task-current-title');
        if (taskTitle) taskTitle.style.display = 'block';
        if (submitForm) submitForm.classList.remove('hidden');
      }

      // Hide static guidance block from mobile task UI
      document.querySelectorAll('.lesson-os-task-guidance, .pocket-os-hide-guidance').forEach((el) => {
        el.style.display = 'none';
      });
    },

    // 6. Read-Only Canvas & Multi-Touch Gestures
    enforceReadOnlyCanvas() {
      if (window.BooCanvasOverlay) {
        window.BooCanvasOverlay.setReadOnly(true);
        window.BooCanvasOverlay.setTool('pan');
      }
    },

    bindCanvasGestures() {
      const canvasViewport = document.getElementById('whiteboard-canvas-viewport');
      if (!canvasViewport) return;

      let touchStartDist = 0;
      let touchStartScale = 1.0;

      canvasViewport.addEventListener(
        'touchstart',
        (e) => {
          if (e.touches.length === 2) {
            e.preventDefault();
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            touchStartDist = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
            touchStartScale = window.BooCanvasOverlay?.getCamera?.()?.scale || 1.0;
          }
        },
        { passive: false }
      );

      canvasViewport.addEventListener(
        'touchmove',
        (e) => {
          if (e.touches.length === 2 && touchStartDist > 0) {
            e.preventDefault();
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            const curDist = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
            const scaleFactor = curDist / touchStartDist;
            const newScale = Math.min(4.0, Math.max(0.2, touchStartScale * scaleFactor));
            const cam = window.BooCanvasOverlay?.getCamera?.();
            if (cam && window.BooCanvasOverlay?.setCamera) {
              window.BooCanvasOverlay.setCamera(cam.offsetX, cam.offsetY, newScale, false);
            }
            this.reportMobileViewport();
          }
        },
        { passive: false }
      );

      canvasViewport.addEventListener('touchend', (e) => {
        if (e.touches.length < 2) {
          touchStartDist = 0;
          this.reportMobileViewport(true);
        }
      });
    },

    // 7. Center & Zoom Helpers
    fitCanvasContent() {
      if (!window.BooCanvasOverlay) return;
      const vp = document.getElementById('whiteboard-canvas-viewport');
      const width = vp?.clientWidth || window.innerWidth;
      const height = vp?.clientHeight || window.innerHeight;
      window.BooCanvasOverlay.setCamera(width / 2, height / 2, 1.0, true);
      this.reportMobileViewport(true);
    },

    rejoinTeacherCamera() {
      const state = this.getState();
      const teacherCam = state?.teacherCamera || state?.remoteStudentViewports?.['teacher'];
      if (teacherCam && window.BooCanvasOverlay?.setCamera) {
        window.BooCanvasOverlay.setCamera(teacherCam.x || 0, teacherCam.y || 0, teacherCam.scale || 1.0, true);
        this.reportMobileViewport(true);
      } else {
        this.fitCanvasContent();
      }
    },

    bindViewportAndKeyboard() {
      const textarea = document.getElementById('code-editor-textarea');
      if (textarea) {
        textarea.addEventListener('focus', () => {
          document.body.classList.add('pocket-keyboard-open');
          setTimeout(() => {
            textarea.scrollIntoView({ block: 'nearest' });
          }, 150);
        });
        textarea.addEventListener('blur', () => {
          document.body.classList.remove('pocket-keyboard-open');
        });
      }

      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => {
          if (!this.active) return;
          const vv = window.visualViewport;
          const kbHeight = Math.max(0, window.innerHeight - vv.height);
          const isKbOpen = kbHeight > 100;
          document.body.classList.toggle('pocket-keyboard-open', isKbOpen);
          document.documentElement.style.setProperty('--pocket-viewport-height', `${vv.height}px`);
        });
      }
    },

    getCurrentCode() {
      const currentFileName = window.activeFileName || 'main.py';
      const textarea = document.getElementById('code-editor-textarea');
      if (textarea && typeof textarea.value === 'string') {
        return textarea.value;
      }
      return window.virtualFS?.[currentFileName] || '';
    },

    checkCodeStale() {
      if (this.lastRunCode === null) {
        this.setStaleBadge(false);
        return;
      }
      const currentCode = this.getCurrentCode();
      const isStale = (currentCode !== this.lastRunCode);
      this.setStaleBadge(isStale);
    },

    setStaleBadge(stale) {
      const badge = document.getElementById('pocket-terminal-stale-badge');
      if (badge) {
        badge.style.display = stale ? 'inline-flex' : 'none';
      }
    },

    bindCodeChangeListener() {
      const textarea = document.getElementById('code-editor-textarea');
      if (textarea) {
        textarea.addEventListener('input', () => {
          this.checkCodeStale();
        });
        textarea.addEventListener('change', () => {
          this.checkCodeStale();
        });
      }

      // Intercept onCodeEditorInput to capture edits from OT, virtual symbols, formatters
      const self = this;
      const originalOnCodeInput = window.onCodeEditorInput;
      if (typeof originalOnCodeInput === 'function' && !window.__pocketOsInputIntercepted) {
        window.__pocketOsInputIntercepted = true;
        window.onCodeEditorInput = function (val) {
          originalOnCodeInput.apply(this, arguments);
          self.checkCodeStale();
        };
      }
    },

    // 8. Python Code Execution & Output Terminal Sync
    runPythonCode() {
      if (this._isExecuting) return;
      this._isExecuting = true;

      try {
        this.toggleTerminalDrawer(true);
        const currentCode = this.getCurrentCode();
        const currentFileName = window.activeFileName || 'main.py';
        const pageId = window.BooCanvasOverlay?.getActivePageId?.() || window.state?.currentPageId || 'page_1';
        const runId = 'run_' + Date.now();

        this.activeRunId = runId;
        this.lastRunCode = currentCode;
        this.setStaleBadge(false);

        const desktopConsole = document.getElementById('terminal-console-output');
        const pocketConsole = document.getElementById('pocket-terminal-body');

        if (pocketConsole) {
          pocketConsole.innerHTML = `
            <div style="color:var(--pocket-text-muted);display:flex;align-items:center;gap:6px;">
              <span class="pocket-status-dot" style="background:#f59e0b;animation:pulse 1s infinite;"></span>
              <span>Выполняется ${this.escapeHtml(currentFileName)}...</span>
            </div>
          `;
        }

        // Clean up previous terminal observer if any
        if (this._terminalObserver) {
          this._terminalObserver.disconnect();
          this._terminalObserver = null;
        }

        // Sync active code into virtualFS before running
        if (typeof window.onCodeEditorInput === 'function') {
          window.onCodeEditorInput(currentCode);
        }

        // Execute via existing trainer engine
        if (typeof window.executeRunCode === 'function') {
          window.executeRunCode({ code: currentCode, fileName: currentFileName, runId, pageId });
        }

        // Synchronize structured execution result
        if (desktopConsole && pocketConsole) {
          const syncOut = () => {
            const content = desktopConsole.innerHTML;
            if (content && !content.includes('animate-ping')) {
              pocketConsole.innerHTML = content;
            }
          };
          this._terminalObserver = new MutationObserver(() => {
            syncOut();
          });
          this._terminalObserver.observe(desktopConsole, { childList: true, subtree: true, characterData: true });
          setTimeout(() => {
            syncOut();
            if (this._terminalObserver) {
              this._terminalObserver.disconnect();
              this._terminalObserver = null;
            }
            this._isExecuting = false;
          }, 3500);
        } else {
          setTimeout(() => {
            this._isExecuting = false;
          }, 600);
        }
      } catch (err) {
        console.error('[PocketOS] runPythonCode error:', err);
        this._isExecuting = false;
      }
    },

    toggleTerminalDrawer(forceState) {
      const drawer = document.getElementById('pocket-terminal-drawer');
      const btn = document.getElementById('pocket-btn-console-toggle');
      if (!drawer) return;

      const isCollapsed = typeof forceState === 'boolean' ? !forceState : !drawer.classList.contains('is-collapsed');
      drawer.classList.toggle('is-collapsed', isCollapsed);
      btn?.classList.toggle('is-open', !isCollapsed);
      this.isTerminalDrawerOpen = !isCollapsed;
      this.reportMobileViewport(true);
    },

    // 9. Teacher Suggestion & Show Here Socket Events
    bindSocketEvents() {
      const socket = this.getSocket();
      if (!socket) {
        setTimeout(() => this.bindSocketEvents(), 300);
        return;
      }

      if (this._socketEventsBound) return;
      this._socketEventsBound = true;
      this._processedCommandIds = this._processedCommandIds || new Set();

      this.reportMobileViewport(true);
      socket.on('connect', () => this.reportMobileViewport(true));

      if (!this._heartbeatStarted) {
        this._heartbeatStarted = true;
        setInterval(() => {
          if (this.active) {
            this.reportMobileViewport(false);
          }
        }, 1500);
      }

      // Teacher Show Here (`whiteboard_show_here`)
      socket.on('whiteboard_show_here', (payload) => {
        if (!payload) return;
        const myId = window.trainerOsConfig?.user_id || window.trainerOsConfig?.viewer_id || window.state?.user_id;
        if (payload.target_user_id && myId && String(payload.target_user_id) !== String(myId)) {
          return;
        }
        this.handleShowHere(payload);
      });

      // Teacher Focus Suggestion / Forced Focus (`lesson_room_ui`)
      socket.on('lesson_room_ui', (payload) => {
        if (!payload) return;
        const myId = window.trainerOsConfig?.user_id || window.trainerOsConfig?.viewer_id || window.state?.user_id;
        if (payload.target_user_id && myId && String(payload.target_user_id) !== String(myId)) {
          return;
        }

        if (payload.kind === 'set_focus' && payload.target_focus) {
          this.handleSetFocus(payload.target_focus);
          return;
        }

        if (payload.kind === 'focus_suggestion' && payload.target_focus) {
          const cmdId = payload.command_id;
          const lessonId = window.trainerOsConfig?.lesson_id || window.state?.lesson_id;
          if (cmdId && socket && lessonId) {
            socket.emit('lesson_room_ui', {
              lesson_id: lessonId,
              kind: 'focus_suggestion_ack',
              command_id: cmdId,
            });
          }
          if (payload.created_at && (Date.now() - payload.created_at > 30000)) {
            return;
          }
          if (cmdId) {
            if (this._processedCommandIds.has(cmdId)) return;
            this._processedCommandIds.add(cmdId);
            if (this._processedCommandIds.size > 200) {
              const first = this._processedCommandIds.values().next().value;
              this._processedCommandIds.delete(first);
            }
          }
          this.handleFocusSuggestion(payload.target_focus);
          return;
        }

        if (payload.kind === 'terminal_close') {
          this.toggleTerminalDrawer(false);
          return;
        }

        if (payload.kind === 'terminal_output') {
          this.handleTerminalOutput(payload);
          return;
        }

        if (payload.kind === 'run_start') {
          this.handleTerminalRunStart(payload);
          return;
        }
      });

      // Window events dispatched by trainer.html
      if (!this._terminalEventsBound) {
        this._terminalEventsBound = true;
        window.addEventListener('boostudy:terminal-output', (e) => {
          if (e.detail) this.handleTerminalOutput(e.detail);
        });
        window.addEventListener('boostudy:terminal-run-start', (e) => {
          if (e.detail) this.handleTerminalRunStart(e.detail);
        });
        window.addEventListener('boostudy:terminal-close', () => {
          this.toggleTerminalDrawer(false);
        });
        window.addEventListener('boostudy:control-updated', () => {
          this.updateCodePermissionBadge();
        });
      }
    },

    handleSetFocus(target) {
      if (!['board', 'code', 'task'].includes(target)) return;
      this.switchFocus(target);

      const targetNames = {
        board: 'Доска',
        code: 'Код',
        task: 'Задание',
      };
      const label = targetNames[target] || target;

      let pill = document.getElementById('pocket-teacher-focus-pill');
      if (!pill) {
        pill = document.createElement('div');
        pill.id = 'pocket-teacher-focus-pill';
        document.body.appendChild(pill);
      }
      pill.innerHTML = `<i class="ph-bold ph-lock-key"></i> <span>Фокус: ${this.escapeHtml(label)} (управляет преподаватель)</span>`;
      pill.classList.add('is-visible');

      if (this._focusPillTimer) clearTimeout(this._focusPillTimer);
      this._focusPillTimer = setTimeout(() => {
        pill.classList.remove('is-visible');
      }, 2500);
    },

    handleTerminalRunStart(payload) {
      const pocketConsole = document.getElementById('pocket-terminal-body');
      if (pocketConsole) {
        const initiator = payload.initiator_name || 'Преподаватель';
        pocketConsole.innerHTML = `
          <div style="color:var(--pocket-text-muted);display:flex;align-items:center;gap:6px;">
            <span class="pocket-status-dot" style="background:#f59e0b;animation:pulse 1s infinite;"></span>
            <span>${this.escapeHtml(initiator)} выполняет ${this.escapeHtml(payload.file_name || 'main.py')}...</span>
          </div>
        `;
      }
    },

    handleTerminalOutput(payload) {
      this._isExecuting = false;
      const pocketConsole = document.getElementById('pocket-terminal-body');
      if (!pocketConsole) return;

      const isError = Boolean(payload.is_error);
      const output = payload.output || '';
      const duration = payload.duration || '0.000';
      const exitCode = payload.exit_code ?? 0;
      const fileName = payload.file_name || 'main.py';
      const initiator = payload.initiator_name || (payload.is_local ? 'Вы' : 'Преподаватель');

      const colorStyle = isError ? 'color:#ef4444;font-weight:700;' : 'color:#10b981;font-weight:700;';
      const prefix = isError ? '[Ошибка выполнения]:\n' : '';

      pocketConsole.innerHTML = `
        <div style="font-family:ui-monospace, monospace;font-size:12px;line-height:1.5;">
          <div style="color:var(--pocket-text-muted);font-size:11px;margin-bottom:4px;">
            <i class="ph-bold ph-play"></i> ${this.escapeHtml(initiator)} запустил(а) ${this.escapeHtml(fileName)}
          </div>
          <div style="${colorStyle}white-space:pre-wrap;word-break:break-word;">${prefix}${this.escapeHtml(output)}</div>
          <div style="color:var(--pocket-text-muted);font-size:10px;margin-top:6px;border-top:1px solid var(--pocket-border);padding-top:4px;">
            Выполнено за ${duration} с · Код: ${exitCode}
          </div>
        </div>
      `;

      // Auto-open drawer if currently in code focus
      if (this.currentFocus === 'code') {
        this.toggleTerminalDrawer(true);
      } else {
        // If in board or task focus, show unobtrusive toast notification
        const subtitle = isError ? 'Ошибка выполнения Python' : (output.trim() ? output.trim().split('\n')[0] : 'Программа успешно выполнена');
        this.showToast({
          icon: isError ? 'ph-warning-circle' : 'ph-terminal',
          title: `Результат запуска: ${fileName}`,
          subtitle: subtitle.length > 50 ? subtitle.slice(0, 48) + '…' : subtitle,
          actionText: 'В консоль',
          onAction: () => {
            this.switchFocus('code');
            this.toggleTerminalDrawer(true);
          },
        });
      }
    },

    handleShowHere(payload) {
      const world_x = payload.world_x ?? payload.x ?? 0;
      const world_y = payload.world_y ?? payload.y ?? 0;
      const world_w = payload.world_w ?? payload.w ?? payload.width ?? 300;
      const world_h = payload.world_h ?? payload.h ?? payload.height ?? 300;
      this.lastTargetCoords = { world_x, world_y, world_w, world_h };

      if (this.currentFocus === 'board') {
        this.zoomToTargetWorldRect(world_x, world_y, world_w, world_h);
      } else {
        this.showToast({
          icon: 'ph-chalkboard-simple',
          title: 'Учитель показывает область на доске',
          subtitle: 'Нажмите «Перейти», чтобы открыть доску',
          actionText: 'Перейти к доске',
          onAction: () => {
            this.switchFocus('board');
            this.zoomToTargetWorldRect(world_x, world_y, world_w, world_h);
          },
        });
      }
    },

    handleFocusSuggestion(target) {
      const titles = {
        board: 'Учитель предлагает открыть доску',
        code: 'Учитель предлагает открыть редактор кода',
        task: 'Учитель предлагает открыть условие задания',
      };
      const icons = {
        board: 'ph-chalkboard-simple',
        code: 'ph-code',
        task: 'ph-check-square-offset',
      };
      const actionLabels = {
        board: 'На доску',
        code: 'В код',
        task: 'К заданию',
      };

      if (this.currentFocus === target) return;

      this.showToast({
        icon: icons[target] || 'ph-lightbulb',
        title: titles[target] || 'Предложение учителя',
        subtitle: 'Переключиться на этот экран?',
        actionText: actionLabels[target] || 'Перейти',
        onAction: () => {
          this.switchFocus(target);
        },
      });
    },

    zoomToTargetWorldRect(worldX, worldY, worldW, worldH) {
      if (!window.BooCanvasOverlay?.setCamera) return;
      const vp = document.getElementById('whiteboard-canvas-viewport');
      const viewW = vp?.clientWidth || window.innerWidth;
      const viewH = vp?.clientHeight || window.innerHeight;

      // Fit within available mobile viewport with padding
      const pad = 24;
      const availW = Math.max(100, viewW - pad * 2);
      const availH = Math.max(100, viewH - pad * 2);

      const scaleX = availW / Math.max(worldW, 100);
      const scaleY = availH / Math.max(worldH, 100);
      // Clamp to readable educational range [0.65, 2.0] so content is always crisp, centered and readable
      const targetScale = Math.min(2.0, Math.max(0.65, Math.min(scaleX, scaleY)));

      const centerX = worldX + worldW / 2;
      const centerY = worldY + worldH / 2;

      // Correct BooCanvas camera projection: project target center directly to center of viewport
      const targetOffsetX = -(centerX - viewW / 2) * targetScale;
      const targetOffsetY = -(centerY - viewH / 2) * targetScale;

      window.BooCanvasOverlay.setCamera(targetOffsetX, targetOffsetY, targetScale, true);
      this.reportMobileViewport(true);
    },

    // 10. Toast Notification System
    showToast({ icon, title, subtitle, actionText, onAction }) {
      const toast = document.getElementById('pocket-toast');
      const iconEl = document.getElementById('pocket-toast-icon');
      const titleEl = document.getElementById('pocket-toast-title');
      const subtitleEl = document.getElementById('pocket-toast-subtitle');
      const actionBtn = document.getElementById('pocket-toast-btn-action');
      if (!toast) return;

      if (iconEl) iconEl.innerHTML = `<i class="ph-bold ${icon}"></i>`;
      if (titleEl) titleEl.textContent = title;
      if (subtitleEl) subtitleEl.textContent = subtitle;
      if (actionBtn) {
        actionBtn.textContent = actionText;
        actionBtn.onclick = () => {
          this.dismissToast();
          if (typeof onAction === 'function') onAction();
        };
      }

      toast.classList.add('is-visible');

      if (this.toastTimeout) clearTimeout(this.toastTimeout);
      this.toastTimeout = setTimeout(() => {
        this.dismissToast();
      }, 12000);
    },

    dismissToast() {
      const toast = document.getElementById('pocket-toast');
      if (toast) toast.classList.remove('is-visible');
      if (this.toastTimeout) {
        clearTimeout(this.toastTimeout);
        this.toastTimeout = null;
      }
    },

    // 11. LiveKit Video & Audio Continuous Integration
    initLiveKitIntegration() {
      const joinBtn = document.getElementById('pocket-btn-join-call');
      const leaveBtn = document.getElementById('pocket-call-leave');
      const micBtn = document.getElementById('pocket-mic-toggle');
      const camBtn = document.getElementById('pocket-cam-toggle');
      const videoPill = document.getElementById('pocket-video-pill');

      // Bind Join button
      joinBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.joinLiveKitCall();
      });

      // Bind Leave button
      leaveBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.leaveLiveKitCall();
      });

      // Bind AV toggles
      micBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleLiveKitAudio();
      });

      camBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleLiveKitVideo();
      });

      // Video Pill toggle expansion or join
      videoPill?.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!window.lessonLivekit?.isConnected) {
          this.joinLiveKitCall();
        } else {
          videoPill.classList.toggle('is-expanded');
        }
      });

      // Check secure context
      const isSecure = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
      if (!isSecure && joinBtn) {
        joinBtn.classList.add('is-warning');
        joinBtn.innerHTML = '<i class="ph-bold ph-shield-warning"></i> <span>Требуется HTTPS</span>';
        joinBtn.title = 'Для доступа к микрофону и камере на смартфоне требуется HTTPS';
      }

      // Sync with desktop lessonLivekit instance
      const hookController = () => {
        if (!window.lessonLivekit) return;

        this.syncLiveKitUIState();

        if (!window.lessonLivekit._pocketHooked) {
          window.lessonLivekit._pocketHooked = true;
          const origUpdateStatus = window.lessonLivekit.updateStatusBadge;
          window.lessonLivekit.updateStatusBadge = (status, label) => {
            origUpdateStatus?.call(window.lessonLivekit, status, label);
            this.syncLiveKitUIState();
          };

          const origShowCall = window.lessonLivekit.showActiveCallView;
          window.lessonLivekit.showActiveCallView = () => {
            origShowCall?.call(window.lessonLivekit);
            this.syncLiveKitUIState();
          };

          const origShowLobby = window.lessonLivekit.showLobbyView;
          window.lessonLivekit.showLobbyView = () => {
            origShowLobby?.call(window.lessonLivekit);
            this.syncLiveKitUIState();
          };

          const origSyncRemote = window.lessonLivekit.syncRemoteParticipantUI;
          window.lessonLivekit.syncRemoteParticipantUI = () => {
            origSyncRemote?.call(window.lessonLivekit);
            this.syncLiveKitUIState();
          };
        }
      };

      hookController();
      setInterval(() => {
        hookController();
        this.syncLiveKitUIState();
      }, 1000);
    },

    async joinLiveKitCall() {
      const isSecure = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
      const joinBtn = document.getElementById('pocket-btn-join-call');

      if (!isSecure) {
        const msg = `Для доступа к микрофону и камере мобильные браузеры требуют защищённое соединение (HTTPS). Откройте урок через https://${window.location.hostname}:5443 или включите флаг Chrome (unsafely-treat-insecure-origin-as-secure).`;
        alert(msg);
        return;
      }

      if (!window.lessonLivekit) {
        alert('Модуль видеосвязи ещё загружается или недоступен для данного занятия.');
        return;
      }

      if (window.lessonLivekit.isConnected || window.lessonLivekit.isConnecting) return;

      if (joinBtn) {
        joinBtn.disabled = true;
        joinBtn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i> <span>Подключение...</span>';
      }

      try {
        await window.lessonLivekit.joinRoom();
      } catch (err) {
        console.error('[PocketOS] Join room error:', err);
        const isPerm = String(err?.message || err?.name).toLowerCase().includes('notallowed') ||
                       String(err?.message || err?.name).toLowerCase().includes('permission');
        if (isPerm) {
          alert('Доступ к микрофону или камере отклонён. Разрешите доступ к медиаустройствам в настройках браузера.');
        } else {
          alert('Не удалось подключиться к видеоконференции: ' + (err?.message || 'сеть недоступна'));
        }
      } finally {
        this.syncLiveKitUIState();
      }
    },

    leaveLiveKitCall() {
      if (!window.lessonLivekit) return;
      if (confirm('Вы уверены, что хотите завершить видеозвонок?')) {
        window.lessonLivekit.leaveRoom();
        this.syncLiveKitUIState();
      }
    },

    toggleLiveKitAudio() {
      const micBtn = document.getElementById('pocket-mic-toggle');
      if (window.lessonLivekit?.toggleMicrophone) {
        window.lessonLivekit.toggleMicrophone().then(() => {
          this.syncLiveKitUIState();
        }).catch(() => {
          this.syncLiveKitUIState();
        });
      }
    },

    toggleLiveKitVideo() {
      const camBtn = document.getElementById('pocket-cam-toggle');
      if (window.lessonLivekit?.toggleCamera) {
        window.lessonLivekit.toggleCamera().then(() => {
          this.syncLiveKitUIState();
        }).catch(() => {
          this.syncLiveKitUIState();
        });
      }
    },

    syncLiveKitUIState() {
      const joinBtn = document.getElementById('pocket-btn-join-call');
      const leaveBtn = document.getElementById('pocket-call-leave');
      const micBtn = document.getElementById('pocket-mic-toggle');
      const camBtn = document.getElementById('pocket-cam-toggle');
      const pill = document.getElementById('pocket-video-pill');
      const streamContainer = document.getElementById('pocket-video-pill-stream');
      const avatar = document.getElementById('pocket-video-pill-avatar');
      const nameEl = document.getElementById('pocket-video-pill-name');

      const isConnected = Boolean(window.lessonLivekit?.isConnected);
      const isConnecting = Boolean(window.lessonLivekit?.isConnecting);
      const isSecure = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

      if (isConnected) {
        if (joinBtn) joinBtn.style.display = 'none';
        if (leaveBtn) leaveBtn.style.display = 'flex';
        if (micBtn) {
          micBtn.style.display = 'flex';
          micBtn.classList.toggle('is-muted', Boolean(window.lessonLivekit.isAudioMuted));
          micBtn.innerHTML = window.lessonLivekit.isAudioMuted
            ? '<i class="ph-bold ph-microphone-slash"></i>'
            : '<i class="ph-bold ph-microphone"></i>';
        }
        if (camBtn) {
          camBtn.style.display = 'flex';
          camBtn.classList.toggle('is-muted', Boolean(window.lessonLivekit.isVideoMuted));
          camBtn.innerHTML = window.lessonLivekit.isVideoMuted
            ? '<i class="ph-bold ph-video-camera-slash"></i>'
            : '<i class="ph-bold ph-video-camera"></i>';
        }

        // Sync remote video stream or avatar
        const desktopVideo = document.getElementById('livekit-remote-video') || document.querySelector('#video-window video');
        if (desktopVideo && desktopVideo.srcObject && desktopVideo.videoWidth > 0 && desktopVideo.style.display !== 'none') {
          pill?.classList.remove('is-compact-indicator');
          if (streamContainer) {
            let mirrorVideo = streamContainer.querySelector('video');
            if (!mirrorVideo) {
              mirrorVideo = document.createElement('video');
              mirrorVideo.autoplay = true;
              mirrorVideo.playsInline = true;
              mirrorVideo.muted = true;
              streamContainer.appendChild(mirrorVideo);
            }
            if (mirrorVideo.srcObject !== desktopVideo.srcObject) {
              mirrorVideo.srcObject = desktopVideo.srcObject;
            }
          }
          if (avatar) avatar.style.display = 'none';
        } else {
          if (streamContainer) streamContainer.innerHTML = '';
          pill?.classList.add('is-compact-indicator');
          if (avatar) {
            avatar.style.display = 'flex';
            avatar.innerHTML = `<span class="pocket-status-dot"></span><span>Учитель</span>`;
          }
        }
      } else if (isConnecting) {
        if (joinBtn) {
          joinBtn.style.display = 'inline-flex';
          joinBtn.disabled = true;
          joinBtn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i> <span>Подключение...</span>';
        }
        if (leaveBtn) leaveBtn.style.display = 'none';
        if (micBtn) micBtn.style.display = 'none';
        if (camBtn) camBtn.style.display = 'none';
        if (streamContainer) streamContainer.innerHTML = '';
        pill?.classList.add('is-compact-indicator');
        if (avatar) {
          avatar.style.display = 'flex';
          avatar.innerHTML = `<span class="pocket-status-dot" style="background:#f59e0b;animation:pulse 1s infinite;"></span><span>Подключение...</span>`;
        }
      } else {
        // Disconnected
        if (joinBtn) {
          joinBtn.style.display = 'inline-flex';
          joinBtn.disabled = false;
          if (!isSecure) {
            joinBtn.classList.add('is-warning');
            joinBtn.innerHTML = '<i class="ph-bold ph-shield-warning"></i> <span>Требуется HTTPS</span>';
          } else {
            joinBtn.classList.remove('is-warning');
            joinBtn.innerHTML = '<i class="ph-bold ph-video-camera"></i> <span>Войти в звонок</span>';
          }
        }
        if (leaveBtn) leaveBtn.style.display = 'none';
        if (micBtn) micBtn.style.display = 'none';
        if (camBtn) camBtn.style.display = 'none';
        if (streamContainer) streamContainer.innerHTML = '';
        pill?.classList.add('is-compact-indicator');
        if (avatar) {
          avatar.style.display = 'flex';
          avatar.innerHTML = isSecure
            ? `<i class="ph-bold ph-video-camera" style="font-size:14px;color:var(--pocket-primary);"></i><span>Войти в звонок</span>`
            : `<i class="ph-bold ph-shield-warning" style="font-size:14px;color:#d97706;"></i><span>Нужен HTTPS</span>`;
        }
      }
    },

    // 12. Student Viewport Reporting (accurate mobile world rectangle)
    reportMobileViewport(immediate = false) {
      if (!this.active) return;
      const now = performance.now();

      const doSend = () => {
        this.lastViewportSentAt = performance.now();
        const socket = this.getSocket();
        const lessonId = window.trainerOsConfig?.lesson_id;
        const state = this.getState();
        const activePid = window.BooCanvasOverlay?.getActivePageId?.() || state?.currentPageId || 'page_1';
        const pageId = String(activePid).replace(/-/g, '_');
        if (!socket || !lessonId) return;

        let worldX = 0, worldY = 0, worldW = 390, worldH = 844;
        if (window.BooCanvasOverlay?.getViewportWorldBounds) {
          const bounds = window.BooCanvasOverlay.getViewportWorldBounds();
          worldX = bounds.worldX;
          worldY = bounds.worldY;
          worldW = bounds.worldW;
          worldH = bounds.worldH;
        } else {
          const currentScale = state?.scale || 1.0;
          worldX = (0 - (state?.panX || 0)) / currentScale;
          worldY = (0 - (state?.panY || 0)) / currentScale;
          worldW = (document.getElementById('whiteboard-canvas-viewport')?.clientWidth || 390) / currentScale;
          worldH = (document.getElementById('whiteboard-canvas-viewport')?.clientHeight || 844) / currentScale;
        }

        const drawer = document.getElementById('pocket-terminal-drawer');
        const isTermOpen = Boolean(this.isTerminalDrawerOpen || (drawer && !drawer.classList.contains('is-collapsed')));

        socket.emit('whiteboard_viewport', {
          lesson_id: lessonId,
          page_id: pageId,
          mode: this.currentFocus,
          is_mobile: true,
          device: 'pocket_os',
          terminal_open: isTermOpen,
          world_x: worldX,
          world_y: worldY,
          world_w: worldW,
          world_h: worldH,
        });
      };

      if (immediate || now - this.lastViewportSentAt > 100) {
        if (this.viewportRaf) cancelAnimationFrame(this.viewportRaf);
        doSend();
      } else if (!this.viewportRaf) {
        this.viewportRaf = requestAnimationFrame(doSend);
      }
    },

    escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    },
  };

  // Export to window
  window.BooStudyPocketOS = BooStudyPocketOS;

  // Auto-init on DOMContentLoaded or immediate if document already ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => BooStudyPocketOS.init());
  } else {
    BooStudyPocketOS.init();
  }
})();
