(() => {
  const welcome = document.querySelector('#rc3-welcome');
  const durationLabel = document.querySelector('[data-rc3-duration]');
  const modeReturn = document.querySelector('[data-rc3-reopen]');
  const panel = document.querySelector('[data-rc3-tour-panel]');
  if (!welcome || !durationLabel || !modeReturn || !panel) return;
  document.querySelector('.s30-nav')?.append(modeReturn);

  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const SPEEDS = [0.75, 1, 1.25, 1.5];
  const KEYBOARD_SCROLL_KEYS = new Set(['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' ']);

  const TOUR_MANIFEST = [
    { id: 'os-workspace', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Рабочее пространство', root: '[data-s30-story]', anchor: '[data-s30-step="enter"]', copy: '[data-s30-copy="enter"]', attention: 'WATCH', watchMs: 2100, importance: 1.12 },
    { id: 'os-assignment', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Задание в комнате ученика', root: '[data-s30-story]', anchor: '[data-s30-step="task"]', copy: '[data-s30-copy="task"]', attention: 'READ', watchMs: 1400, importance: 1.04 },
    { id: 'os-code', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Решение развивается на экране', root: '[data-s30-story]', anchor: '[data-s30-step="typing-continue"]', copy: '[data-s30-copy="typing"]', attention: 'WATCH', watchMs: 2300, importance: 1.2 },
    { id: 'os-result', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Проверенный результат', root: '[data-s30-story]', anchor: '[data-s30-step="result"]', copy: '[data-s30-copy="result"]', attention: 'HOLD', watchMs: 1450, importance: 1.04 },
    { id: 'os-canvas', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Холст отдельного урока', root: '[data-s30-story]', anchor: '[data-s30-step="math-tree"]', copy: '[data-s30-copy="math-tree"]', attention: 'WATCH', watchMs: 1850, importance: 1.12 },
    { id: 'os-complete', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Связанная учебная сцена', root: '[data-s30-story]', anchor: '[data-s30-step="math-done"]', copy: '[data-s30-copy="math-done"]', attention: 'HOLD', watchMs: 1600, importance: 1.08 },

    { id: 'homework-plan', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Условие и план решения', root: '[data-s38-homework]', progress: 0.3, copy: '[data-homework-step="brief"]', attention: 'READ', watchMs: 1350, importance: 1.02 },
    { id: 'homework-tools', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Инструменты и черновик', root: '[data-s38-homework]', progress: 0.7, copy: '[data-homework-step="draft"]', attention: 'WATCH', watchMs: 1850, importance: 1.1 },
    { id: 'homework-result', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Результат работы', root: '[data-s38-homework]', progress: 0.92, copy: '[data-homework-step="handoff"]', attention: 'HOLD', watchMs: 1600, importance: 1.08 },

    { id: 'analytics-start', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Первые подтверждённые результаты', root: '[data-s32-story]', progress: 0.14, copy: '.s32-copy', attention: 'READ', watchMs: 1300, importance: 1.02 },
    { id: 'analytics-chart', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Как растёт график', root: '[data-s32-story]', progress: 0.38, copy: '.s32-copy', attention: 'WATCH', watchMs: 2100, importance: 1.2 },
    { id: 'analytics-topics', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Точность по темам', root: '[data-s32-story]', progress: 0.64, copy: '.s32-copy', attention: 'WATCH', watchMs: 2100, importance: 1.16 },
    { id: 'analytics-summary', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Общий результат ученика', root: '[data-s32-story]', progress: 0.88, copy: '.s32-copy', attention: 'HOLD', watchMs: 1700, importance: 1.08 },

    { id: 'dashboard-start', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Главный обзор', root: '[data-s36-story]', progress: 0.18, copy: '[data-copy-block="continue"]', attention: 'READ', watchMs: 1300, importance: 1.02 },
    { id: 'dashboard-schedule', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Занятия и программа', root: '[data-s36-story]', progress: 0.46, copy: '[data-copy-block="curriculum"]', attention: 'WATCH', watchMs: 1950, importance: 1.12 },
    { id: 'dashboard-progress', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Материалы и прогресс', root: '[data-s36-story]', progress: 0.75, copy: '[data-copy-block="progress"]', attention: 'WATCH', watchMs: 1900, importance: 1.12 },
    { id: 'dashboard-summary', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Центр обучения целиком', root: '[data-s36-story]', progress: 0.92, copy: '[data-copy-block="complete"]', attention: 'HOLD', watchMs: 1550, importance: 1.08 },

    { id: 'schedule-week', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Учебная неделя', root: '[data-s37-story]', progress: 0.06, copy: '[data-s37-copy-block="week"]', attention: 'READ', watchMs: 1250, importance: 1.02 },
    { id: 'schedule-day', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Выбор дня и карточка урока', root: '[data-s37-story]', progress: 0.33, copy: '[data-s37-copy-block="lesson"]', attention: 'WATCH', watchMs: 1900, importance: 1.12 },
    { id: 'schedule-homework', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Домашняя работа и материалы', root: '[data-s37-story]', progress: 0.62, copy: '[data-s37-copy-block="homework"]', attention: 'WATCH', watchMs: 1900, importance: 1.12 },
    { id: 'schedule-overview', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Ритм недели', root: '[data-s37-story]', progress: 0.92, copy: '[data-s37-copy-block="overview"]', attention: 'HOLD', watchMs: 1600, importance: 1.08 },

    { id: 'theory-library', chapter: 'theory', chapterTitle: 'Теория', label: 'Библиотека учебных материалов', root: '[data-s39-theory]', progress: 0.04, copy: '[data-s39-theory-copy-step="library"]', attention: 'READ', watchMs: 1250, importance: 1.02 },
    { id: 'theory-structure', chapter: 'theory', chapterTitle: 'Теория', label: 'Структура темы', root: '[data-s39-theory]', progress: 0.2, copy: '[data-s39-theory-copy-step="structure"]', attention: 'READ', watchMs: 1500, importance: 1.06 },
    { id: 'theory-reading', chapter: 'theory', chapterTitle: 'Теория', label: 'Чтение и пример', root: '[data-s39-theory]', progress: 0.35, copy: '[data-s39-theory-copy-step="reading"]', attention: 'WATCH', watchMs: 1800, importance: 1.12 },
    { id: 'theory-bookmark', chapter: 'theory', chapterTitle: 'Теория', label: 'Закладки', root: '[data-s39-theory]', progress: 0.5, copy: '[data-s39-theory-copy-step="bookmark"]', attention: 'WATCH', watchMs: 1600, importance: 1.08 },
    { id: 'theory-notes', chapter: 'theory', chapterTitle: 'Теория', label: 'Личные заметки', root: '[data-s39-theory]', progress: 0.64, copy: '[data-s39-theory-copy-step="notes"]', attention: 'READ', watchMs: 1300, importance: 1.04 },
    { id: 'theory-progress', chapter: 'theory', chapterTitle: 'Теория', label: 'Позиция и прогресс чтения', root: '[data-s39-theory]', progress: 0.78, copy: '[data-s39-theory-copy-step="progress"]', attention: 'WATCH', watchMs: 1800, importance: 1.1 },
    { id: 'theory-check', chapter: 'theory', chapterTitle: 'Теория', label: 'Добровольная микропроверка', root: '[data-s39-theory]', progress: 0.93, copy: '[data-s39-theory-copy-step="check"]', attention: 'READ', watchMs: 1750, importance: 1.1 },

    { id: 'profile-identity', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'История ученицы', root: '[data-s39-profile]', progress: 0.08, copy: '[data-s39-profile-copy-step="identity"]', attention: 'READ', watchMs: 1300, importance: 1.05 },
    { id: 'profile-xp', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Уровень и 765 XP', root: '[data-s39-profile]', progress: 0.27, copy: '[data-s39-profile-copy-step="xp"]', attention: 'WATCH', watchMs: 1800, importance: 1.12 },
    { id: 'profile-achievements', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Награды и серия активности', root: '[data-s39-profile]', progress: 0.47, copy: '[data-s39-profile-copy-step="achievements"]', attention: 'WATCH', watchMs: 1900, importance: 1.12 },
    { id: 'profile-referrals', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Учебное время и приглашение', root: '[data-s39-profile]', progress: 0.7, copy: '[data-s39-profile-copy-step="referral"]', attention: 'READ', watchMs: 1600, importance: 1.08 },
    { id: 'profile-complete', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Полная композиция профиля', root: '[data-s39-profile]', progress: 1, copy: '[data-s39-profile-copy-step="complete"]', attention: 'HOLD', watchMs: 2100, importance: 1.16 },

    { id: 'founder-story', chapter: 'founder', chapterTitle: 'Создатель BooStudy', label: 'Личная история и приглашение', root: '[data-s42-founder]', section: true, copy: '.s42-founder-copy', attention: 'READ', founderRevealMs: 4840, watchMs: 0, importance: 1.18 }
  ];

  const chapterNames = [...new Set(TOUR_MANIFEST.map((item) => item.chapter))];
  const totalStops = TOUR_MANIFEST.length;

  function wordCount(text) {
    return (String(text || '').match(/[\p{L}\p{N}]+(?:[’'-][\p{L}\p{N}]+)*/gu) || []).length;
  }

  function getEpisodeText(episode) {
    const root = document.querySelector(episode.root);
    const copy = root?.querySelector(episode.copy);
    if (copy) return copy.textContent.trim();
    const visibleCopy = root?.querySelector('h1, h2, h3, p');
    return visibleCopy?.textContent.trim() || episode.label;
  }

  function estimateReadMs(episode, speed = 1) {
    const words = wordCount(getEpisodeText(episode));
    const base = words * (60000 / 185) * (episode.importance || 1);
    return clamp(base / speed, 1800, episode.chapter === 'founder' ? 60000 : 8200);
  }

  function scrollMax() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function targetFor(episode) {
    const root = document.querySelector(episode.root);
    if (!root) return 0;
    const rootTop = root.getBoundingClientRect().top + window.scrollY;
    let target;
    if (episode.section) {
      target = rootTop - Math.max(0, window.innerHeight * 0.015);
    } else if (episode.anchor) {
      const anchor = root.querySelector(episode.anchor);
      target = anchor ? anchor.getBoundingClientRect().top + window.scrollY : rootTop;
    } else {
      const range = Math.max(1, root.offsetHeight - window.innerHeight);
      target = rootTop + range * clamp(episode.progress || 0, 0, 1);
    }
    return clamp(target, 0, scrollMax());
  }

  function travelMs(from, to, speed = 1) {
    if (motionPreference.matches) return 0;
    const distanceInScreens = Math.abs(to - from) / Math.max(1, window.innerHeight);
    return clamp(720 + distanceInScreens * 460, 720, 2100) / speed;
  }

  function estimateTourMs(speed = 1) {
    let cursor = 0;
    return TOUR_MANIFEST.reduce((sum, episode) => {
      const target = targetFor(episode);
      const move = travelMs(cursor, target, speed);
      const read = estimateReadMs(episode, speed);
      const watch = clamp(episode.watchMs / speed, 850, 3200);
      const hold = 460 / speed;
      cursor = target;
      return sum + move + read + watch + hold;
    }, 0);
  }

  function formatDuration(ms) {
    const minutes = Math.max(1, Math.round(ms / 60000));
    return `${minutes} мин · время рассчитано по тексту и сценам`;
  }

  durationLabel.textContent = formatDuration(estimateTourMs(1));

  class GuidedTourController {
    constructor() {
      this.state = 'idle';
      this.speed = 1;
      this.currentIndex = 0;
      this.phase = 'idle';
      this.phaseDuration = 0;
      this.phaseRemaining = 0;
      this.phaseStartedAt = 0;
      this.phaseFromY = 0;
      this.phaseToY = 0;
      this.phaseStartProgress = 0;
      this.rafId = 0;
      this.timerId = 0;
      this.generation = 0;
      this.wasPausedBeforeSeek = false;
      this.pausedAnimations = [];
      this.savedOverflow = null;
      this.statusMessage = '';
      this.collapsed = false;
      this.durationByEpisode = [];
      this.routeStartY = 0;
      this.lastPanelPaint = 0;
      this.panelNodes = {};
      this.renderPanel();
      this.bindPanel();
      this.bindGlobalInputs();
      document.documentElement.dataset.rc3TourState = 'idle';
      document.documentElement.dataset.rc3Mode = 'idle';
    }

    isAutoMode() {
      return ['auto-playing', 'auto-paused', 'auto-seeking', 'auto-complete', 'reduced-motion'].includes(this.state);
    }

    isLockingInput() {
      return ['auto-playing', 'auto-paused', 'auto-seeking', 'reduced-motion'].includes(this.state);
    }

    isPlaying() {
      return this.state === 'auto-playing' || this.state === 'reduced-motion' || this.state === 'auto-seeking';
    }

    activeState() {
      return motionPreference.matches ? 'reduced-motion' : 'auto-playing';
    }

    setState(state, message = '') {
      this.state = state;
      this.statusMessage = message;
      document.documentElement.dataset.rc3Mode = this.isLockingInput() ? 'auto' : state;
      document.documentElement.dataset.rc3TourState = state;
      this.updatePanel();
    }

    setPanelVisible(visible) {
      panel.hidden = !visible;
      modeReturn.hidden = visible || this.state === 'idle';
      this.updatePanel();
    }

    renderPanel() {
      panel.innerHTML = `
        <div class="rc3-tour-panel__top">
          <div class="rc3-tour-panel__chapter"><span class="rc3-tour-panel__eyebrow" data-rc3-current-chapter>Экскурсия по BooStudy</span><strong data-rc3-current-label>Подготовка маршрута</strong><small data-rc3-phase-label>Выбери, как смотреть</small></div>
          <div class="rc3-tour-panel__status" role="status" aria-live="polite"><i aria-hidden="true"></i><span data-rc3-state-label>Готово</span></div>
        </div>
        <div class="rc3-tour-panel__progress"><input data-rc3-progress type="range" min="0" max="1000" value="0" aria-label="Прогресс экскурсии"><output data-rc3-progress-output>0% · —</output></div>
        <div class="rc3-tour-panel__controls">
          <button type="button" data-rc3-prev aria-label="Предыдущий эпизод">← Назад</button>
          <button type="button" data-rc3-play aria-label="Пауза экскурсии">Ⅱ Пауза</button>
          <button type="button" data-rc3-next aria-label="Следующий эпизод">Дальше →</button>
          <select data-rc3-speed aria-label="Скорость экскурсии"><option value="0.75">0,75×</option><option value="1" selected>1×</option><option value="1.25">1,25×</option><option value="1.5">1,5×</option></select>
          <span class="rc3-tour-panel__spacer"></span>
          <button class="rc3-tour-panel__secondary" type="button" data-rc3-collapse aria-label="Свернуть панель">Свернуть</button>
          <button class="rc3-tour-panel__secondary" type="button" data-rc3-restart>Сначала</button>
          <button class="rc3-tour-panel__exit" type="button" data-rc3-exit>В ручной режим</button>
        </div>
        <p class="rc3-tour-panel__complete" data-rc3-complete hidden></p>`;
      this.panelNodes = {
        chapter: panel.querySelector('[data-rc3-current-chapter]'),
        label: panel.querySelector('[data-rc3-current-label]'),
        phase: panel.querySelector('[data-rc3-phase-label]'),
        state: panel.querySelector('[data-rc3-state-label]'),
        progress: panel.querySelector('[data-rc3-progress]'),
        progressOutput: panel.querySelector('[data-rc3-progress-output]'),
        play: panel.querySelector('[data-rc3-play]'),
        prev: panel.querySelector('[data-rc3-prev]'),
        next: panel.querySelector('[data-rc3-next]'),
        speed: panel.querySelector('[data-rc3-speed]'),
        collapse: panel.querySelector('[data-rc3-collapse]'),
        restart: panel.querySelector('[data-rc3-restart]'),
        exit: panel.querySelector('[data-rc3-exit]'),
        complete: panel.querySelector('[data-rc3-complete]')
      };
    }

    bindPanel() {
      this.panelNodes.play.addEventListener('click', () => {
        if (this.state === 'auto-complete') this.restart();
        else if (this.state === 'auto-paused') this.resume();
        else this.pause();
      });
      this.panelNodes.prev.addEventListener('click', () => this.previous());
      this.panelNodes.next.addEventListener('click', () => this.next());
      this.panelNodes.speed.addEventListener('change', () => this.setSpeed(Number(this.panelNodes.speed.value)));
      this.panelNodes.collapse.addEventListener('click', () => {
        this.collapsed = !this.collapsed;
        panel.dataset.collapsed = String(this.collapsed);
        this.panelNodes.collapse.textContent = this.collapsed ? 'Развернуть' : 'Свернуть';
      });
      this.panelNodes.restart.addEventListener('click', () => this.restart());
      this.panelNodes.exit.addEventListener('click', () => this.exitToManual());
      this.panelNodes.progress.addEventListener('input', () => {
        const value = Number(this.panelNodes.progress.value) / 1000;
        const stopIndex = clamp(Math.floor(value * totalStops), 0, totalStops - 1);
        this.panelNodes.progressOutput.value = `${Math.round(value * 100)}% · эпизод ${stopIndex + 1}/${totalStops}`;
      });
      this.panelNodes.progress.addEventListener('change', () => {
        const value = Number(this.panelNodes.progress.value) / 1000;
        const stopIndex = clamp(Math.floor(value * totalStops), 0, totalStops - 1);
        this.seek(stopIndex);
      });
    }

    bindGlobalInputs() {
      this.lockedWheel = (event) => {
        if (this.isLockingInput() && event.cancelable) event.preventDefault();
      };
      this.lockedTouch = (event) => {
        if (this.isLockingInput() && !event.target.closest('.rc3-tour-panel') && event.cancelable) event.preventDefault();
      };
      this.lockedKey = (event) => {
        if (!this.isLockingInput() || !KEYBOARD_SCROLL_KEYS.has(event.key)) return;
        if (event.target.closest('.rc3-tour-panel, input, textarea, select, [contenteditable="true"]')) return;
        event.preventDefault();
      };
      this.pauseForInteraction = (event) => {
        if (!this.isPlaying() || event.target.closest('.rc3-tour-panel, #rc3-welcome')) return;
        if (!event.target.closest('a,button,input,textarea,select,[role="button"],[role="checkbox"]')) return;
        this.pause('Пауза · ты взаимодействуешь с примером');
      };
      document.addEventListener('wheel', this.lockedWheel, { passive: false, capture: true });
      document.addEventListener('touchmove', this.lockedTouch, { passive: false, capture: true });
      document.addEventListener('keydown', this.lockedKey, true);
      document.addEventListener('pointerdown', this.pauseForInteraction, true);
      document.addEventListener('visibilitychange', () => {
        if (document.hidden && this.isPlaying()) this.pause('Пауза · вкладка скрыта');
      });
      window.addEventListener('resize', () => this.onResize());
    }

    lockUserScroll() {
      if (this.savedOverflow) return;
      this.savedOverflow = {
        root: document.documentElement.style.overflowY,
        body: document.body.style.overflowY
      };
      document.documentElement.style.overflowY = 'hidden';
      document.body.style.overflowY = 'hidden';
    }

    unlockUserScroll() {
      if (!this.savedOverflow) return;
      document.documentElement.style.overflowY = this.savedOverflow.root;
      document.body.style.overflowY = this.savedOverflow.body;
      this.savedOverflow = null;
      delete document.documentElement.dataset.rc3Mode;
    }

    rebuildDurationModel(startY = 0) {
      let cursor = startY;
      this.durationByEpisode = TOUR_MANIFEST.map((episode) => {
        const target = targetFor(episode);
        const phases = {
          move: travelMs(cursor, target, this.speed),
          founder: (episode.founderRevealMs || 0) / this.speed,
          read: estimateReadMs(episode, this.speed),
          watch: episode.founderRevealMs ? 0 : clamp(episode.watchMs / this.speed, 850, 3200),
          hold: 460 / this.speed
        };
        cursor = target;
        return { target, phases, total: Object.values(phases).reduce((sum, value) => sum + value, 0) };
      });
    }

    startAuto() {
      this.cancelPhase();
      this.currentIndex = 0;
      this.phase = 'move';
      this.routeStartY = window.scrollY;
      this.rebuildDurationModel(this.routeStartY);
      this.lockUserScroll();
      this.setPanelVisible(true);
      this.collapsed = false;
      delete panel.dataset.collapsed;
      this.panelNodes.speed.value = String(this.speed);
      this.beginEpisode(0, { starting: true });
      requestAnimationFrame(() => this.panelNodes.play.focus({ preventScroll: true }));
    }

    cancelPhase() {
      this.generation += 1;
      if (this.rafId) cancelAnimationFrame(this.rafId);
      if (this.timerId) clearTimeout(this.timerId);
      this.rafId = 0;
      this.timerId = 0;
    }

    beginEpisode(index, options = {}) {
      const remainPaused = options.keepPaused ?? this.state === 'auto-paused';
      const keepMotionPaused = remainPaused && !options.seeking;
      this.cancelPhase();
      this.currentIndex = clamp(index, 0, totalStops - 1);
      const episode = TOUR_MANIFEST[this.currentIndex];
      const token = this.generation;
      this.phase = 'move';
      this.phaseFromY = window.scrollY;
      this.phaseToY = targetFor(episode);
      this.phaseRemaining = travelMs(this.phaseFromY, this.phaseToY, this.speed);
      this.phaseDuration = this.phaseRemaining;
      this.phaseStartProgress = 0;
      this.setState(options.seeking ? 'auto-seeking' : (remainPaused ? 'auto-paused' : this.activeState()), options.seeking ? 'Переход к выбранному эпизоду' : '');
      if (this.phaseRemaining <= 1) {
        window.scrollTo({ top: this.phaseToY, behavior: 'instant' });
        this.afterMove(token, remainPaused);
        return;
      }
      if (keepMotionPaused) {
        this.updatePanel(false);
        return;
      }
      this.phaseStartedAt = performance.now();
      this.animateMove(token, remainPaused);
    }

    animateMove(token, remainPaused = false) {
      const duration = Math.max(1, this.phaseRemaining);
      this.phaseDuration = duration;
      this.phaseStartedAt = performance.now();
      const from = window.scrollY;
      const to = this.phaseToY;
      const tick = (now) => {
        if (token !== this.generation || !this.isPlaying()) return;
        const progress = clamp((now - this.phaseStartedAt) / duration, 0, 1);
        const eased = progress < .5 ? 4 * progress ** 3 : 1 - ((-2 * progress + 2) ** 3) / 2;
        window.scrollTo({ top: from + (to - from) * eased, behavior: 'instant' });
        this.phaseProgress = progress;
        this.updatePanel(false);
        if (progress < 1) this.rafId = requestAnimationFrame(tick);
        else {
          this.rafId = 0;
          window.scrollTo({ top: to, behavior: 'instant' });
          this.afterMove(token, remainPaused);
        }
      };
      this.rafId = requestAnimationFrame(tick);
    }

    afterMove(token, remainPaused = false) {
      if (token !== this.generation) return;
      const episode = TOUR_MANIFEST[this.currentIndex];
      if (episode.chapter === 'founder') {
        this.phase = 'founder';
        this.phaseProgress = 0;
        this.phaseDuration = (episode.founderRevealMs || 4840) / this.speed;
        this.phaseRemaining = this.phaseDuration;
        this.phaseStartedAt = performance.now();
        this.updatePanel();
        const reveal = window.BooStudyFounderReveal?.start?.();
        if (this.isPlaying()) this.trackFounderProgress(token);
        if (remainPaused || this.state === 'auto-paused') {
          window.BooStudyFounderReveal?.pause?.();
          this.setState('auto-paused', 'Пауза · авторская сцена выбрана');
        }
        Promise.resolve(reveal).then(() => {
          if (token !== this.generation) return;
          this.phase = 'read';
          this.phaseProgress = 0;
          const readMs = this.readDurationFor(episode);
          if (this.isPlaying()) this.startTimedPhase('read', readMs, token);
          else {
            this.phaseRemaining = readMs;
            this.phaseDuration = readMs;
            this.updatePanel();
          }
        });
        return;
      }
      this.phase = 'read';
      this.phaseProgress = 0;
      if (remainPaused || this.state === 'auto-paused') {
        this.phaseRemaining = this.readDurationFor(episode);
        this.phaseDuration = this.phaseRemaining;
        this.setState('auto-paused', 'Пауза · эпизод выбран');
        this.updatePanel();
      } else this.startTimedPhase('read', this.readDurationFor(episode), token);
    }

    trackFounderProgress(token) {
      const tick = (now) => {
        if (token !== this.generation || this.phase !== 'founder' || !this.isPlaying()) return;
        this.updatePanel(false);
        this.rafId = requestAnimationFrame(tick);
      };
      this.rafId = requestAnimationFrame(tick);
    }

    readDurationFor(episode) {
      const sourceText = getEpisodeText(episode);
      const words = wordCount(sourceText);
      const factor = episode.importance || 1;
      return clamp((words * 60000 / 185 * factor) / this.speed, 1800, 8200);
    }

    startTimedPhase(name, duration, token = this.generation) {
      if (token !== this.generation) return;
      this.phase = name;
      this.phaseRemaining = Math.max(0, duration);
      this.phaseDuration = this.phaseRemaining;
      this.phaseProgress = 0;
      this.phaseStartedAt = performance.now();
      this.setState(this.state === 'auto-seeking' ? this.activeState() : this.state);
      if (!this.isPlaying()) {
        this.updatePanel();
        return;
      }
      this.updatePanel();
      this.timerId = window.setTimeout(() => {
        if (token !== this.generation) return;
        this.timerId = 0;
        this.phaseProgress = 1;
        this.onPhaseEnd(token);
      }, this.phaseRemaining);
    }

    onPhaseEnd(token) {
      if (token !== this.generation || !this.isPlaying()) return;
      if (this.phase === 'read') {
        const episode = TOUR_MANIFEST[this.currentIndex];
        if (episode.founderRevealMs || !episode.watchMs) this.startTimedPhase('hold', 460 / this.speed, token);
        else this.startTimedPhase('watch', clamp(episode.watchMs / this.speed, 850, 3200), token);
      } else if (this.phase === 'watch') {
        this.startTimedPhase('hold', 460 / this.speed, token);
      } else if (this.phase === 'hold') {
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
      }
    }

    pause(message = '') {
      if (!this.isPlaying() || this.state === 'auto-paused' || this.state === 'auto-complete') return;
      if (this.phase === 'move' || this.phase === 'read' || this.phase === 'watch' || this.phase === 'hold') {
        const elapsed = performance.now() - this.phaseStartedAt;
        this.phaseRemaining = Math.max(0, this.phaseDuration - elapsed);
      } else if (this.phase === 'founder') {
        this.phaseRemaining = Math.max(0, this.phaseDuration - (performance.now() - this.phaseStartedAt));
      }
      if (this.rafId) cancelAnimationFrame(this.rafId);
      if (this.timerId) clearTimeout(this.timerId);
      this.rafId = 0;
      this.timerId = 0;
      this.pauseVisibleAnimations();
      window.BooStudyFounderReveal?.pause?.();
      this.setState('auto-paused', message || 'Пауза · позиция и эпизод сохранены');
    }

    pauseVisibleAnimations() {
      this.pausedAnimations = document.getAnimations().filter((animation) => {
        if (animation.playState !== 'running') return false;
        const target = animation.effect?.target;
        if (!(target instanceof Element) || target.closest('.rc3-tour-panel, #rc3-welcome')) return false;
        const rect = target.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
      });
      this.pausedAnimations.forEach((animation) => animation.pause());
    }

    resume() {
      if (this.state !== 'auto-paused') return;
      this.pausedAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
      this.pausedAnimations = [];
      window.BooStudyFounderReveal?.resume?.();
      this.setState(this.activeState(), '');
      const token = this.generation;
      if (this.phase === 'founder') {
        if (window.BooStudyFounderReveal?.complete) {
          this.phase = 'read';
          this.startTimedPhase('read', this.readDurationFor(TOUR_MANIFEST[this.currentIndex]), token);
        } else {
          window.BooStudyFounderReveal?.resume?.();
          this.trackFounderProgress(token);
          this.updatePanel();
        }
        return;
      }
      if (this.phase === 'move') this.animateMove(token);
      else this.startTimedPhase(this.phase, this.phaseRemaining, token);
    }

    setSpeed(speed) {
      if (!SPEEDS.includes(speed)) return;
      const previousSpeed = this.speed;
      if (speed === previousSpeed) return;
      const ratio = previousSpeed / speed;
      if (this.phase === 'founder' && this.phaseRemaining > 0) {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseRemaining - elapsed) * ratio;
        this.phaseDuration = this.phaseRemaining;
        this.phaseStartedAt = performance.now();
        if (this.rafId) cancelAnimationFrame(this.rafId);
        this.rafId = 0;
      } else if (['move', 'read', 'watch', 'hold'].includes(this.phase) && this.phaseRemaining > 0) {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseRemaining - elapsed) * ratio;
        if (this.rafId) cancelAnimationFrame(this.rafId);
        if (this.timerId) clearTimeout(this.timerId);
        this.rafId = 0;
        this.timerId = 0;
      }
      this.speed = speed;
      this.panelNodes.speed.value = String(speed);
      this.rebuildDurationModel(this.routeStartY);
      if (this.phase === 'founder') window.BooStudyFounderReveal?.setSpeed?.(speed);
      if (this.isPlaying() && ['move', 'read', 'watch', 'hold'].includes(this.phase)) {
        if (this.phase === 'move') {
          this.phaseToY = targetFor(TOUR_MANIFEST[this.currentIndex]);
          this.animateMove(this.generation);
        } else this.startTimedPhase(this.phase, this.phaseRemaining, this.generation);
      }
      this.statusMessage = `Скорость ${String(speed).replace('.', ',')}× · текущий эпизод сохранён`;
      this.updatePanel();
    }

    seek(index) {
      if (!this.isAutoMode() || this.state === 'auto-complete') return;
      const remainPaused = this.state === 'auto-paused';
      if (TOUR_MANIFEST[this.currentIndex]?.chapter === 'founder' && index !== this.currentIndex) window.BooStudyFounderReveal?.finish?.();
      this.beginEpisode(index, { seeking: true, keepPaused: remainPaused });
    }

    previous() { this.seek(Math.max(0, this.currentIndex - 1)); }
    next() {
      if (this.state === 'auto-complete') return;
      if (this.currentIndex >= totalStops - 1) this.complete();
      else this.seek(this.currentIndex + 1);
    }

    restart() {
      if (!this.isAutoMode()) {
        this.speed = Number(this.panelNodes.speed.value) || 1;
        this.startAuto();
        return;
      }
      window.BooStudyFounderReveal?.finish?.();
      this.lockUserScroll();
      this.setState(this.activeState(), 'Экскурсия начинается сначала');
      this.currentIndex = 0;
      this.routeStartY = 0;
      this.beginEpisode(0, { starting: true });
    }

    complete() {
      this.cancelPhase();
      window.BooStudyFounderReveal?.finish?.();
      this.unlockUserScroll();
      this.phase = 'complete';
      this.currentIndex = totalStops - 1;
      this.setState('auto-complete', 'Экскурсия завершена');
      this.setPanelVisible(true);
      this.panelNodes.complete.hidden = false;
      this.panelNodes.complete.textContent = 'Спасибо за знакомство. Можно повторить экскурсию или продолжить изучение вручную.';
    }

    exitToManual() {
      if (this.phase !== 'idle' && !this.isAutoMode() && this.state !== 'auto-complete') return;
      this.cancelPhase();
      this.unlockUserScroll();
      this.pausedAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
      this.pausedAnimations = [];
      window.BooStudyFounderReveal?.finish?.();
      this.phase = 'idle';
      this.setState('manual', 'Ручной просмотр · прокрутка свободна');
      this.setPanelVisible(false);
      modeReturn.hidden = false;
    }

    onResize() {
      if (!this.isAutoMode()) return;
      this.rebuildDurationModel(this.routeStartY);
      if (this.phase === 'move') {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseDuration - elapsed);
        if (this.rafId) cancelAnimationFrame(this.rafId);
        this.rafId = 0;
        this.phaseFromY = window.scrollY;
        this.phaseToY = targetFor(TOUR_MANIFEST[this.currentIndex]);
        if (this.isPlaying()) this.animateMove(this.generation);
      }
      this.updatePanel();
    }

    episodeTimeline() {
      const episode = this.durationByEpisode[this.currentIndex] || { phases: { move: 0, read: 0, watch: 0, hold: 0 }, total: 1 };
      const phaseOrder = ['move', 'founder', 'read', 'watch', 'hold'];
      const completedPrior = this.durationByEpisode.slice(0, this.currentIndex).reduce((sum, item) => sum + item.total, 0);
      const timelinePhase = this.phase;
      const currentPhaseIndex = phaseOrder.indexOf(timelinePhase);
      const before = phaseOrder.slice(0, Math.max(0, currentPhaseIndex)).reduce((sum, phase) => sum + episode.phases[phase], 0);
      let phaseElapsed = 0;
      if (currentPhaseIndex >= 0) {
        phaseElapsed = this.isPlaying() ? clamp((performance.now() - this.phaseStartedAt) / Math.max(1, this.phaseDuration), 0, 1) * episode.phases[timelinePhase] : Math.max(0, episode.phases[timelinePhase] - this.phaseRemaining);
      }
      const total = this.durationByEpisode.reduce((sum, item) => sum + item.total, 0) || 1;
      return clamp((completedPrior + before + phaseElapsed) / total, 0, 1);
    }

    estimatedRemainingMs() {
      if (this.state === 'auto-complete') return 0;
      const current = this.durationByEpisode[this.currentIndex];
      if (!current) return estimateTourMs(this.speed);
      const phaseOrder = ['move', 'founder', 'read', 'watch', 'hold'];
      const phaseIndex = phaseOrder.indexOf(this.phase);
      const currentRemaining = phaseIndex < 0 ? current.total : Math.max(0, this.phaseRemaining) + phaseOrder.slice(phaseIndex + 1).reduce((sum, key) => sum + current.phases[key], 0);
      return currentRemaining + this.durationByEpisode.slice(this.currentIndex + 1).reduce((sum, item) => sum + item.total, 0);
    }

    phaseLabel() {
      if (this.phase === 'move') return 'Переход к следующей сцене';
      if (this.phase === 'read') return 'READ · спокойно читаем';
      if (this.phase === 'watch' || this.phase === 'founder') return 'WATCH · рассматриваем сцену';
      if (this.phase === 'hold') return 'HOLD · результат остаётся перед тобой';
      if (this.phase === 'complete') return 'Экскурсия завершена';
      if (this.state === 'auto-paused') return 'Пауза · положение сохранено';
      return 'Выбери, как смотреть';
    }

    updatePanel(force = true) {
      if (!this.panelNodes.chapter) return;
      const now = performance.now();
      if (!force && now - this.lastPanelPaint < 100) return;
      this.lastPanelPaint = now;
      const episode = TOUR_MANIFEST[this.currentIndex];
      this.panelNodes.chapter.textContent = episode?.chapterTitle || 'Экскурсия по BooStudy';
      this.panelNodes.label.textContent = episode?.label || 'Подготовка маршрута';
      this.panelNodes.phase.textContent = this.phaseLabel();
      const stateText = this.state === 'auto-playing' || this.state === 'reduced-motion' ? 'Идёт экскурсия' : this.state === 'auto-paused' ? (this.statusMessage || 'Пауза') : this.state === 'auto-seeking' ? 'Переход' : this.state === 'auto-complete' ? 'Готово' : 'Ручной просмотр';
      this.panelNodes.state.textContent = stateText;
      this.panelNodes.play.textContent = this.state === 'auto-paused' ? '▶ Продолжить' : this.state === 'auto-complete' ? '↻ Повторить' : 'Ⅱ Пауза';
      this.panelNodes.play.setAttribute('aria-label', this.state === 'auto-paused' ? 'Продолжить экскурсию' : this.state === 'auto-complete' ? 'Повторить экскурсию' : 'Пауза экскурсии');
      this.panelNodes.prev.disabled = this.currentIndex <= 0 || !this.isAutoMode();
      this.panelNodes.next.disabled = this.currentIndex >= totalStops - 1 || !this.isAutoMode();
      this.panelNodes.progress.disabled = !this.isAutoMode() || this.state === 'auto-complete';
      this.panelNodes.restart.hidden = !this.isAutoMode() || this.state === 'auto-complete';
      this.panelNodes.complete.hidden = this.state !== 'auto-complete';
      if (this.state === 'auto-complete') this.panelNodes.complete.textContent = 'Спасибо за знакомство. Можно повторить экскурсию или продолжить изучение вручную.';
      const progress = this.state === 'auto-complete' ? 1 : this.episodeTimeline();
      this.panelNodes.progress.value = String(Math.round(progress * 1000));
      const stopNumber = this.state === 'auto-complete' ? totalStops : this.currentIndex + 1;
      const remaining = this.state === 'auto-complete' ? '0 мин' : `${Math.max(1, Math.ceil(this.estimatedRemainingMs() / 60000))} мин осталось`;
      this.panelNodes.progressOutput.value = `${Math.round(progress * 100)}% · ${remaining}`;
      panel.dataset.state = this.state;
      panel.dataset.phase = this.phase;
      panel.setAttribute('aria-label', `Экскурсия: ${episode?.chapterTitle || 'готово'}, эпизод ${stopNumber} из ${totalStops}`);
    }
  }

  const tour = new GuidedTourController();

  function openWelcome() {
    if (tour.isAutoMode()) tour.exitToManual();
    welcome.hidden = false;
    if (typeof welcome.showModal === 'function') welcome.showModal();
    else welcome.setAttribute('open', '');
    const preferred = motionPreference.matches ? welcome.querySelector('[data-rc3-choice="manual"]') : welcome.querySelector('[data-rc3-choice="auto"]');
    requestAnimationFrame(() => preferred?.focus({ preventScroll: true }));
  }

  welcome.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const choices = [...welcome.querySelectorAll('[data-rc3-choice]:not([disabled])')];
    const first = choices[0];
    const last = choices.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  });

  function closeWelcome() {
    if (typeof welcome.close === 'function' && welcome.open) welcome.close();
    else welcome.removeAttribute('open');
    welcome.hidden = true;
  }

  function focusPageStart() {
    const heading = document.querySelector('#s30-hero-title');
    if (!heading) return;
    if (!heading.hasAttribute('tabindex')) heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }

  function chooseMode(mode) {
    closeWelcome();
    try { sessionStorage.setItem('boostudy-rc3-mode-selected', 'yes'); } catch { /* Session storage is optional. */ }
    if (mode === 'auto') {
      modeReturn.hidden = true;
      tour.startAuto();
      return;
    }
    tour.setState('manual', 'Ручной просмотр · прокрутка свободна');
    tour.setPanelVisible(false);
    modeReturn.hidden = false;
    focusPageStart();
  }

  welcome.querySelectorAll('[data-rc3-choice]').forEach((button) => button.addEventListener('click', () => chooseMode(button.dataset.rc3Choice)));
  welcome.addEventListener('cancel', (event) => {
    event.preventDefault();
    chooseMode('manual');
  });
  modeReturn.addEventListener('click', openWelcome);

  window.BooStudyGuidedTour = {
    manifest: TOUR_MANIFEST,
    isAutoMode: () => tour.isAutoMode(),
    get state() { return tour.state; },
    get phase() { return tour.phase; },
    get currentIndex() { return tour.currentIndex; },
    get progress() { return tour.episodeTimeline(); },
    start: () => tour.startAuto(),
    pause: (message) => tour.pause(message),
    resume: () => tour.resume(),
    next: () => tour.next(),
    previous: () => tour.previous(),
    seek: (index) => tour.seek(index),
    setSpeed: (speed) => tour.setSpeed(speed),
    restart: () => tour.restart(),
    exit: () => tour.exitToManual(),
    openModePicker: openWelcome
  };

  let selectedBefore = false;
  try { selectedBefore = sessionStorage.getItem('boostudy-rc3-mode-selected') === 'yes'; } catch { /* Session storage is optional. */ }
  if (selectedBefore) {
    tour.setState('manual', 'Ручной просмотр · прокрутка свободна');
    modeReturn.hidden = false;
  } else openWelcome();
})();
