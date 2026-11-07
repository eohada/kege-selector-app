(() => {
  const welcome = document.querySelector('#rc3-welcome');
  const durationLabel = document.querySelector('[data-rc3-duration]');
  const modeReturn = document.querySelector('[data-rc3-reopen]');
  const panel = document.querySelector('[data-rc3-tour-panel]');
  if (!welcome || !durationLabel || !modeReturn || !panel) return;
  document.querySelector('.s30-nav')?.append(modeReturn);

  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const SPEEDS = [0.75, 1, 1.5, 2];
  const KEYBOARD_SCROLL_KEYS = new Set(['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' ']);

  const TOUR_MANIFEST = [
    { id: 'os-assignment', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Задание появляется в рабочем пространстве', root: '[data-s30-story]', anchor: '[data-s30-step="task"]', copy: '[data-s30-copy="task"]', type: 'keyframe', focusMs: 7200, importance: 1.05 },
    { id: 'os-code', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Решение развивается на экране', root: '[data-s30-story]', anchor: '[data-s30-step="typing-continue"]', copy: '[data-s30-copy="typing"]', type: 'pass-through' },
    { id: 'os-canvas', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Формула и холст урока', root: '[data-s30-story]', anchor: '[data-s30-step="math-tree"]', copy: '[data-s30-copy="math-tree"]', type: 'pass-through' },
    { id: 'os-complete', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Связанная учебная сцена', root: '[data-s30-story]', anchor: '[data-s30-step="math-done"]', copy: '[data-s30-copy="math-done"]', type: 'keyframe', focusMs: 8200, importance: 1.12 },

    { id: 'homework-journey', chapter: 'homework', chapterTitle: 'Homework OS', label: 'От условия к самостоятельному решению', root: '[data-s38-homework]', progress: 0.48, copy: '[data-homework-copy-scene="draft"]', type: 'pass-through' },
    { id: 'homework-result', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Готовое решение и обратная связь', root: '[data-s38-homework]', progress: 0.92, copy: '[data-homework-copy-scene="handoff"]', type: 'keyframe', focusMs: 9400, importance: 1.12 },

    { id: 'analytics-growth', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'График и навыки собираются в одну историю', root: '[data-s32-story]', progress: 0.46, mobileAnchor: '.s32-chart-wrap', mobileSurface: '.s32-chart-wrap', copy: '.s32-copy', type: 'pass-through' },
    { id: 'analytics-summary', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Сформированный прогресс ученика', root: '[data-s32-story]', progress: 0.88, mobileAnchor: '.s32-task-grid', mobileSurface: '.s32-task-grid', copy: '.s32-copy', type: 'keyframe', focusMs: 10500, importance: 1.16 },

    { id: 'dashboard-overview', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Центр обучения целиком', root: '[data-s36-story]', progress: 0.92, copy: '[data-copy-block="complete"]', type: 'keyframe', focusMs: 10300, importance: 1.15 },

    { id: 'schedule-week', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Неделя раскрывается до выбранного занятия', root: '[data-s37-story]', progress: 0.26, copy: '[data-s37-copy-block="lesson"]', type: 'pass-through' },
    { id: 'schedule-day', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Выбранный день и карточка урока', root: '[data-s37-story]', progress: 0.62, copy: '[data-s37-copy-block="homework"]', type: 'keyframe', focusMs: 8800, importance: 1.08 },

    { id: 'theory-library', chapter: 'theory', chapterTitle: 'Теория', label: 'Чтение, заметки и прогресс по теме', root: '[data-s39-theory]', progress: 0.35, copy: '[data-s39-theory-copy-step="reading"]', type: 'keyframe', focusMs: 8800, importance: 1.08 },

    { id: 'profile-growth', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'XP, достижения и история активности', root: '[data-s39-profile]', progress: 0.48, mobileBreakpoint: 720, mobileSticky: true, copy: '[data-s39-profile-copy-step="achievements"]', type: 'pass-through' },
    { id: 'profile-complete', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Полный личный профиль', root: '[data-s39-profile]', progress: 1, mobileBreakpoint: 720, mobileSticky: true, copy: '[data-s39-profile-copy-step="complete"]', type: 'keyframe', focusMs: 9000, importance: 1.12 },

    { id: 'founder-story', chapter: 'founder', chapterTitle: 'Создатель BooStudy', label: 'Личная история и приглашение', root: '[data-s42-founder]', section: true, copy: '.s42-founder-copy', type: 'keyframe', focusMs: 0, founderRevealMs: 25000, importance: 1.18 }
  ];

  const PRODUCT_SURFACES = {
    hero: '[data-s30-workspace]',
    homework: '.s38-homework-layout',
    analytics: '.s32-composition',
    dashboard: '.s36-story-layout',
    schedule: '.s37-layout',
    theory: '[data-s39-theory-app]',
    profile: '[data-s39-profile-app]',
    founder: '.s42-founder-layout'
  };
  TOUR_MANIFEST.forEach((episode) => {
    episode.visualContract = {
      surface: PRODUCT_SURFACES[episode.chapter],
      copy: episode.copy,
      textRequired: true
    };
  });

  const chapterNames = [...new Set(TOUR_MANIFEST.map((item) => item.chapter))];
  const totalStops = TOUR_MANIFEST.length;
  const keyframeCount = TOUR_MANIFEST.filter((episode) => episode.type === 'keyframe').length;

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
    if (episode.type !== 'keyframe' || episode.chapter === 'founder') return 0;
    const words = wordCount(getEpisodeText(episode));
    const base = words * (60000 / 185) * (episode.importance || 1);
    return clamp(Math.max(base, episode.focusMs || 0) / speed, 6000, 12200);
  }

  function scrollMax() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function clearMobileTourPresentation() {
    let rangeChanged = false;
    document.querySelectorAll('[data-rc3-tour-mobile]').forEach((node) => {
      delete node.dataset.rc3TourMobile;
      delete node.dataset.rc3MobileStep;
      if (node.dataset.rc3TourProgressRange) {
        delete node.dataset.rc3TourProgressRange;
        rangeChanged = true;
      }
    });
    if (rangeChanged) document.dispatchEvent(new Event('boostudy:story-range-change'));
  }

  function prepareMobileTourPresentation(episode) {
    clearMobileTourPresentation();
    if (!(episode.mobileAnchor || episode.mobileSticky)
      || !window.matchMedia(`(max-width: ${episode.mobileBreakpoint || 900}px)`).matches) return;
    const root = document.querySelector(episode.root);
    if (!root) return;
    root.dataset.rc3TourMobile = 'true';
    root.dataset.rc3MobileStep = episode.id;
    if (!episode.mobileSticky || !episode.progress) return;

    const copy = root.querySelector('.s39-copy');
    const surface = root.querySelector('[data-s39-profile-app]');
    if (!copy || !surface) return;
    const rootTop = root.getBoundingClientRect().top + window.scrollY;
    const appTop = surface.getBoundingClientRect().top + window.scrollY - rootTop;
    const copyHeight = copy.getBoundingClientRect().height;
    const gap = clamp(window.innerHeight * 0.035, 18, 30);
    const visibleOffset = clamp(appTop - copyHeight - gap, 24, window.innerHeight * 0.24);
    root.dataset.rc3TourProgressRange = String(visibleOffset / clamp(episode.progress, 0.05, 1));
    document.dispatchEvent(new Event('boostudy:story-range-change'));
  }

  function targetFor(episode) {
    const root = document.querySelector(episode.root);
    if (!root) return 0;
    const rootTop = root.getBoundingClientRect().top + window.scrollY;
    let target;
    const tourRange = Number(root.dataset.rc3TourProgressRange);
    if (episode.mobileSticky && Number.isFinite(tourRange) && tourRange > 0) {
      target = rootTop + tourRange * clamp(episode.progress || 0, 0, 1);
    } else if (episode.mobileAnchor && window.matchMedia(`(max-width: ${episode.mobileBreakpoint || 900}px)`).matches) {
      const anchor = root.querySelector(episode.mobileAnchor);
      target = anchor ? anchor.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.36 : rootTop;
    } else if (episode.section) {
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

  function nextRenderFrame() {
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
  }

  async function settleScene() {
    await nextRenderFrame();
    await nextRenderFrame();
    await new Promise((resolve) => setTimeout(resolve, 120));
    await nextRenderFrame();
  }

  function inspectVisibleNode(node, kind) {
    if (!node) return { pass: false, reason: 'selector-not-found' };
    const rect = node.getBoundingClientRect();
    let visible = {
      left: Math.max(0, rect.left),
      top: Math.max(0, rect.top),
      right: Math.min(window.innerWidth, rect.right),
      bottom: Math.min(window.innerHeight, rect.bottom)
    };
    let opacity = 1;
    let hiddenByAncestor = false;
    let ariaHidden = false;
    let pointerEventsDisabled = false;
    let ancestor = node;
    while (ancestor instanceof HTMLElement) {
      const style = getComputedStyle(ancestor);
      opacity *= Number.parseFloat(style.opacity || '1');
      if (style.pointerEvents === 'none') pointerEventsDisabled = true;
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' || style.contentVisibility === 'hidden') hiddenByAncestor = true;
      if (ancestor.getAttribute('aria-hidden') === 'true') ariaHidden = true;
      if (ancestor !== node && /(hidden|clip|auto|scroll)/.test(`${style.overflowX} ${style.overflowY}`)) {
        const clip = ancestor.getBoundingClientRect();
        if (style.overflowX !== 'visible') {
          visible.left = Math.max(visible.left, clip.left);
          visible.right = Math.min(visible.right, clip.right);
        }
        if (style.overflowY !== 'visible') {
          visible.top = Math.max(visible.top, clip.top);
          visible.bottom = Math.min(visible.bottom, clip.bottom);
        }
      }
      ancestor = ancestor.parentElement;
    }
    const width = Math.max(0, visible.right - visible.left);
    const height = Math.max(0, visible.bottom - visible.top);
    const visibleArea = width * height;
    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
    const fullArea = Math.max(1, rect.width * rect.height);
    const minArea = kind === 'surface'
      ? Math.max(3600, viewportArea * 0.055)
      : kind === 'detail' ? Math.max(1400, viewportArea * 0.014) : Math.max(600, viewportArea * 0.0018);
    const minVisibleFraction = kind === 'surface' ? 0.12 : kind === 'detail' ? 0.12 : 0.15;
    let targetHits = 0;
    const sampleCount = 3;
    for (let row = 1; row <= sampleCount; row += 1) {
      for (let column = 1; column <= sampleCount; column += 1) {
        const x = visible.left + width * column / (sampleCount + 1);
        const y = visible.top + height * row / (sampleCount + 1);
        const hit = x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight ? document.elementFromPoint(x, y) : null;
        if (hit && (node === hit || node.contains(hit))) targetHits += 1;
      }
    }
    const text = (node.innerText || node.textContent || '').trim().replace(/\s+/g, ' ');
    const pass = !hiddenByAncestor && opacity >= 0.08
      && width >= 1 && height >= 1 && visibleArea >= minArea
      && visibleArea / fullArea >= minVisibleFraction
      && (targetHits > 0 || pointerEventsDisabled)
      && (kind !== 'copy' || text.length > 0);
    return {
      pass,
      reason: pass ? '' : (!text && kind === 'copy' ? 'no-text' : hiddenByAncestor ? 'hidden-ancestor' : opacity < 0.08 ? 'transparent' : visibleArea < minArea ? 'visible-area-too-small' : visibleArea / fullArea < minVisibleFraction ? 'mostly-outside-viewport' : targetHits === 0 && !pointerEventsDisabled ? 'occluded' : 'not-visible'),
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      visibleRect: { x: Math.round(visible.left), y: Math.round(visible.top), width: Math.round(width), height: Math.round(height) },
      visibleArea: Math.round(visibleArea),
      visibleFraction: Number((visibleArea / fullArea).toFixed(3)),
      opacity: Number(opacity.toFixed(3)),
      ariaHidden,
      visibleSamples: pointerEventsDisabled ? null : targetHits,
      pointerEventsDisabled,
      text: text.slice(0, 280)
    };
  }

  function inspectEpisode(episode) {
    const root = document.querySelector(episode.root);
    const mobileSurface = episode.mobileSurface && window.matchMedia(`(max-width: ${episode.mobileBreakpoint || 900}px)`).matches;
    const surfaceSelector = mobileSurface ? episode.mobileSurface : episode.visualContract.surface;
    const surface = root?.querySelector(surfaceSelector) || (episode.root === surfaceSelector ? root : document.querySelector(surfaceSelector));
    const copy = root?.querySelector(episode.visualContract.copy) || document.querySelector(episode.visualContract.copy);
    const rootTop = root ? root.getBoundingClientRect().top + window.scrollY : 0;
    const tourRange = Number(root?.dataset.rc3TourProgressRange);
    const calibratedRange = Number(root?.dataset.s40ProgressRange);
    const storyRange = Number.isFinite(tourRange) && tourRange > 0
      ? tourRange
      : Number.isFinite(calibratedRange) && calibratedRange > 0
        ? calibratedRange
        : root ? Math.max(1, root.offsetHeight - window.innerHeight) : 1;
    const surfaceReport = inspectVisibleNode(surface, mobileSurface ? 'detail' : 'surface');
    const copyReport = inspectVisibleNode(copy, 'copy');
    return {
      episodeId: episode.id,
      chapter: episode.chapter,
      expectedObject: episode.label,
      scrollY: Math.round(window.scrollY),
      progress: Number(clamp((window.scrollY - rootTop) / storyRange, 0, 1).toFixed(3)),
      phase: 'verify',
      surfaceSelector,
      copySelector: episode.visualContract.copy,
      surface: surfaceReport,
      copy: copyReport,
      pass: surfaceReport.pass && copyReport.pass
    };
  }

  function travelMs(from, to, speed = 1) {
    if (motionPreference.matches) return 0;
    const pixelsPerSecond = Math.max(1, window.innerHeight) * 1.35 * speed;
    return Math.max(16, Math.abs(to - from) / pixelsPerSecond * 1000);
  }

  function estimateTourMs(speed = 1) {
    let cursor = 0;
    return TOUR_MANIFEST.reduce((sum, episode) => {
      const target = targetFor(episode);
      const move = travelMs(cursor, target, speed);
      const focus = estimateReadMs(episode, speed);
      const founder = episode.chapter === 'founder'
        ? (window.BooStudyFounderReveal?.estimatedDuration?.(speed) || episode.founderRevealMs / speed)
        : 0;
      cursor = target;
      return sum + move + focus + founder;
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
      this.statusMessage = '';
      this.collapsed = false;
      this.durationByEpisode = [];
      this.visualReports = [];
      this.visualDiagnostics = [];
      this.lastVisualReport = null;
      this.routeStartY = 0;
      this.lastPanelPaint = 0;
      this.panelNodes = {};
      this.renderPanel();
      this.bindPanel();
      this.bindGlobalInputs();
      document.documentElement.dataset.rc3TourState = 'idle';
      document.documentElement.dataset.rc3Mode = 'idle';
      document.documentElement.dataset.rc3VisualAcceptance = 'pending';
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
          <select data-rc3-speed aria-label="Скорость экскурсии"><option value="0.75">0,75×</option><option value="1" selected>1×</option><option value="1.5">1,5×</option><option value="2">2×</option></select>
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
      this.captureFounderPan = (event) => {
        if (!this.isAutoMode() || !this.timelineEvents) return;
        this.timelineEvents.push({ event: 'founder-pan', atMs: Math.round(performance.now() - this.startedAt), ...event.detail });
      };
      document.addEventListener('boostudy:founder-pan', this.captureFounderPan);
      this.lockedWheel = (event) => {
        if (this.isLockingInput() && event.cancelable) event.preventDefault();
      };
      this.lockedTouch = (event) => {
        if (this.isLockingInput() && !event.target.closest('.rc3-tour-panel') && event.cancelable) event.preventDefault();
      };
      this.lockedKey = (event) => {
        if (!this.isLockingInput() || !KEYBOARD_SCROLL_KEYS.has(event.key)) return;
        if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
        if (event.key === ' ' && event.target.closest('.rc3-tour-panel button, .rc3-tour-panel a, .rc3-tour-panel [role="button"]')) return;
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

    async verifyEpisode(episode, token) {
      let finalReport = null;
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        await settleScene();
        if (token !== this.generation) return null;
        finalReport = { ...inspectEpisode(episode), attempt, phase: 'verify' };
        this.visualDiagnostics.push(finalReport);
        if (finalReport.pass) {
          this.visualReports.push(finalReport);
          this.lastVisualReport = finalReport;
          return finalReport;
        }
        if (attempt < 3) {
          const refreshedTarget = targetFor(episode);
          this.phaseToY = refreshedTarget;
          window.scrollTo({ top: refreshedTarget, behavior: 'instant' });
        }
      }
      this.lastVisualReport = finalReport;
      return finalReport;
    }

    stopOnVisualFailure(report) {
      this.cancelPhase();
      this.lastVisualReport = report;
      this.pausedAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
      this.pausedAnimations = [];
      this.phase = 'visual-error';
      this.setState('visual-error', `Не удалось показать «${report?.expectedObject || 'сцену'}». Экскурсия остановлена. Перейди в ручной режим.`);
      this.setPanelVisible(true);
      this.panelNodes.complete.hidden = false;
      this.panelNodes.complete.textContent = `${this.statusMessage} Проверь вручную: ${report?.surface?.reason || report?.copy?.reason || 'видимость не подтверждена'}.`;
    }

    rebuildDurationModel(startY = 0) {
      let cursor = startY;
      this.durationByEpisode = TOUR_MANIFEST.map((episode) => {
        const target = targetFor(episode);
        const phases = {
          move: travelMs(cursor, target, this.speed),
          founder: episode.chapter === 'founder'
            ? (window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || episode.founderRevealMs / this.speed)
            : 0,
          focus: estimateReadMs(episode, this.speed)
        };
        cursor = target;
        return { target, phases, total: Object.values(phases).reduce((sum, value) => sum + value, 0) };
      });
    }

    startAuto() {
      this.cancelPhase();
      this.startedAt = performance.now();
      this.timelineEvents = [];
      window.__rc32TourDiagnostics = { startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, keyframeCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, type }) => ({ id, chapter, label, type })) };
      this.currentIndex = 0;
      this.phase = 'move';
      this.routeStartY = window.scrollY;
      this.rebuildDurationModel(this.routeStartY);
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
      prepareMobileTourPresentation(episode);
      const token = this.generation;
      this.phase = 'move';
      this.phaseFromY = window.scrollY;
      this.phaseToY = targetFor(episode);
      this.phaseRemaining = travelMs(this.phaseFromY, this.phaseToY, this.speed);
      this.phaseDuration = this.phaseRemaining;
      this.phaseStartProgress = 0;
      this.timelineEvents ||= [];
      this.timelineEvents.push({ event: 'segment-start', atMs: Math.round(performance.now() - (this.startedAt || performance.now())), episodeId: episode.id, segmentType: episode.type, fromY: Math.round(this.phaseFromY), targetY: Math.round(this.phaseToY) });
      window.__rc32TourDiagnostics && (window.__rc32TourDiagnostics.events = this.timelineEvents);
      this.lastMotionSample = { at: performance.now(), y: window.scrollY, episodeId: episode.id, reported: false };
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
        const eased = TOUR_MANIFEST[this.currentIndex]?.type === 'pass-through'
          ? progress
          : progress < .5 ? 4 * progress ** 3 : 1 - ((-2 * progress + 2) ** 3) / 2;
        window.scrollTo({ top: from + (to - from) * eased, behavior: 'instant' });
        const currentY = window.scrollY;
        if (Math.abs(currentY - this.lastMotionSample.y) >= 2) {
          this.lastMotionSample = { at: now, y: currentY, episodeId: TOUR_MANIFEST[this.currentIndex]?.id, reported: false };
        } else if (!this.lastMotionSample.reported && now - this.lastMotionSample.at >= 1200) {
          this.lastMotionSample.reported = true;
          this.timelineEvents.push({ event: 'temporal-dead-zone-candidate', atMs: Math.round(now - this.startedAt), episodeId: TOUR_MANIFEST[this.currentIndex]?.id, phase: this.phase, scrollY: Math.round(currentY), stagnantMs: Math.round(now - this.lastMotionSample.at) });
        }
        this.phaseProgress = progress;
        this.updatePanel(false);
        if (progress < 1) this.rafId = requestAnimationFrame(tick);
        else {
          this.rafId = 0;
          window.scrollTo({ top: to, behavior: 'instant' });
          this.timelineEvents.push({ event: 'segment-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: TOUR_MANIFEST[this.currentIndex]?.id, scrollY: Math.round(window.scrollY) });
          this.afterMove(token, remainPaused);
        }
      };
      this.rafId = requestAnimationFrame(tick);
    }

    async afterMove(token, remainPaused = false) {
      if (token !== this.generation) return;
      const episode = TOUR_MANIFEST[this.currentIndex];
      if (episode.type === 'pass-through') {
        this.timelineEvents.push({ event: 'pass-through', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
        if (remainPaused || this.state === 'auto-paused') {
          this.phase = 'move';
          this.phaseRemaining = 0;
          this.setState('auto-paused', 'Пауза · промежуточное состояние сохранено');
          return;
        }
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1, { keepPaused: false });
        return;
      }
      this.phase = 'verify';
      this.phaseProgress = 0;
      this.updatePanel();
      const report = await this.verifyEpisode(episode, token);
      if (token !== this.generation) return;
      if (!report?.pass) {
        this.stopOnVisualFailure(report);
        return;
      }
      if (episode.chapter === 'founder') {
        const reveal = window.BooStudyFounderReveal?.start?.();
        await Promise.all([
          nextRenderFrame(),
          window.BooStudyFounderReveal?.waitForTitle?.() || Promise.resolve()
        ]);
        await nextRenderFrame();
        if (token !== this.generation) return;
        const heading = inspectVisibleNode(document.querySelector('#s42-founder-title'), 'copy');
        const founderStartReport = { ...report, phase: 'founder-start', heading, pass: report.pass && heading.pass };
        this.visualDiagnostics.push(founderStartReport);
        if (!founderStartReport.pass) {
          this.stopOnVisualFailure(founderStartReport);
          return;
        }
        this.visualReports[this.visualReports.length - 1] = founderStartReport;
        this.lastVisualReport = founderStartReport;
        this.phase = 'founder';
        this.phaseProgress = 0;
        this.phaseDuration = window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || episode.founderRevealMs / this.speed;
        this.phaseRemaining = this.phaseDuration;
        this.phaseStartedAt = performance.now();
        this.timelineEvents.push({ event: 'founder-typewriter-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
        this.updatePanel();
        if (this.isPlaying()) this.trackFounderProgress(token);
        if (remainPaused || this.state === 'auto-paused') {
          window.BooStudyFounderReveal?.pause?.();
          this.setState('auto-paused', 'Пауза · авторская сцена выбрана');
        }
        Promise.resolve(reveal).then(() => {
          if (token !== this.generation) return;
          this.timelineEvents.push({ event: 'founder-typewriter-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
          this.complete();
        });
        return;
      }
      this.phase = 'focus';
      this.phaseProgress = 0;
      this.timelineEvents.push({ event: 'keyframe-focus-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
      if (remainPaused || this.state === 'auto-paused') {
        this.phaseRemaining = this.readDurationFor(episode);
        this.phaseDuration = this.phaseRemaining;
        this.setState('auto-paused', 'Пауза · эпизод выбран');
        this.updatePanel();
      } else this.startTimedPhase('focus', this.readDurationFor(episode), token);
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
      return estimateReadMs(episode, this.speed);
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
      if (this.phase === 'focus') {
        this.timelineEvents.push({ event: 'keyframe-focus-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: TOUR_MANIFEST[this.currentIndex]?.id, scrollY: Math.round(window.scrollY) });
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
      }
    }

    pause(message = '') {
      if (!this.isPlaying() || this.state === 'auto-paused' || this.state === 'auto-complete') return;
      if (this.phase === 'move' || this.phase === 'focus') {
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
          this.complete();
        } else {
          window.BooStudyFounderReveal?.resume?.();
          this.trackFounderProgress(token);
          this.updatePanel();
        }
        return;
      }
      if (this.phase === 'verify') {
        this.afterMove(token, false);
        return;
      }
      if (this.phase === 'move') this.animateMove(token);
      else if (this.phase === 'focus') this.startTimedPhase('focus', this.phaseRemaining, token);
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
      } else if (['move', 'focus'].includes(this.phase) && this.phaseRemaining > 0) {
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
      if (this.isPlaying() && ['move', 'focus'].includes(this.phase)) {
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
      if (this.currentIndex >= totalStops - 1) {
        if (this.lastVisualReport?.pass && this.lastVisualReport.episodeId === TOUR_MANIFEST.at(-1).id) this.complete();
      }
      else this.seek(this.currentIndex + 1);
    }

    restart() {
      if (!this.isAutoMode()) {
        this.speed = Number(this.panelNodes.speed.value) || 1;
        this.startAuto();
        return;
      }
      window.BooStudyFounderReveal?.finish?.();
      this.setState(this.activeState(), 'Экскурсия начинается сначала');
      this.startedAt = performance.now();
      this.timelineEvents = [];
      window.__rc32TourDiagnostics = { startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, keyframeCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, type }) => ({ id, chapter, label, type })) };
      this.currentIndex = 0;
      this.routeStartY = 0;
      this.beginEpisode(0, { starting: true });
    }

    complete() {
      if (!this.lastVisualReport?.pass || this.lastVisualReport.episodeId !== TOUR_MANIFEST.at(-1).id) {
        this.stopOnVisualFailure(this.lastVisualReport || { expectedObject: 'финальную сцену', surface: { reason: 'нет подтверждения видимости' } });
        return;
      }
      this.timelineEvents.push({ event: 'tour-complete', atMs: Math.round(performance.now() - this.startedAt), episodeId: TOUR_MANIFEST.at(-1).id, scrollY: Math.round(window.scrollY) });
      window.__rc32TourDiagnostics.durationMs = Math.round(performance.now() - this.startedAt);
      this.cancelPhase();
      window.BooStudyFounderReveal?.finish?.();
      this.phase = 'complete';
      this.currentIndex = totalStops - 1;
      this.setState('auto-complete', 'Экскурсия завершена');
      this.setPanelVisible(true);
      this.panelNodes.complete.hidden = false;
      this.panelNodes.complete.textContent = 'Спасибо за знакомство. Можно повторить экскурсию или продолжить изучение вручную.';
    }

    exitToManual() {
      if (this.phase !== 'idle' && !this.isAutoMode() && this.state !== 'auto-complete' && this.state !== 'visual-error') return;
      this.cancelPhase();
      this.pausedAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
      this.pausedAnimations = [];
      window.BooStudyFounderReveal?.finish?.();
      clearMobileTourPresentation();
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
      const episode = this.durationByEpisode[this.currentIndex] || { phases: { move: 0, focus: 0, founder: 0 }, total: 1 };
      const phaseOrder = ['move', 'focus', 'founder'];
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
      const phaseOrder = ['move', 'focus', 'founder'];
      const phaseIndex = phaseOrder.indexOf(this.phase);
      const currentRemaining = phaseIndex < 0 ? current.total : Math.max(0, this.phaseRemaining) + phaseOrder.slice(phaseIndex + 1).reduce((sum, key) => sum + current.phases[key], 0);
      return currentRemaining + this.durationByEpisode.slice(this.currentIndex + 1).reduce((sum, item) => sum + item.total, 0);
    }

    phaseLabel() {
      if (this.phase === 'move') return 'TRAVEL · непрерывное движение по главе';
      if (this.phase === 'verify') return 'Проверяем видимость сцены';
      if (this.phase === 'visual-error') return 'Сцена не подтверждена · экскурсия остановлена';
      if (this.phase === 'focus') return 'FOCUS · ключевой результат';
      if (this.phase === 'founder') return 'FOCUS · создатель BooStudy печатает обращение';
      if (this.phase === 'complete') return 'Экскурсия завершена';
      if (this.phase === 'visual-error') return 'Сцена не подтверждена · экскурсия остановлена';
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
      const stateText = this.state === 'auto-playing' || this.state === 'reduced-motion' ? 'Идёт экскурсия' : this.state === 'auto-paused' ? (this.statusMessage || 'Пауза') : this.state === 'auto-seeking' ? 'Переход' : this.state === 'auto-complete' ? 'Готово' : this.state === 'visual-error' ? 'Остановка · видимость не подтверждена' : 'Ручной просмотр';
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
      panel.dataset.episodeId = episode?.id || '';
      panel.dataset.index = String(this.currentIndex);
      panel.dataset.keyframes = String(keyframeCount);
      panel.dataset.visualStatus = this.lastVisualReport?.episodeId === episode?.id ? (this.lastVisualReport.pass ? 'passed' : 'failed') : 'pending';
      document.documentElement.dataset.rc3VisualAcceptance = this.lastVisualReport?.episodeId === episode?.id ? (this.lastVisualReport.pass ? 'passed' : 'failed') : 'pending';
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
    get visualReports() { return tour.visualReports; },
    get visualDiagnostics() { return tour.visualDiagnostics; },
    get timelineEvents() { return tour.timelineEvents; },
    get keyframeCount() { return keyframeCount; },
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
