(() => {
  const welcome = document.querySelector('#rc3-welcome');
  const durationLabel = document.querySelector('[data-rc3-duration]');
  const modeReturn = document.querySelector('[data-rc3-reopen]');
  const panel = document.querySelector('[data-rc3-tour-panel]');
  if (!welcome || !durationLabel || !modeReturn || !panel) return;
  document.querySelector('.s30-nav')?.append(modeReturn);

  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
  const KEYBOARD_SCROLL_KEYS = new Set(['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' ']);

  const TOUR_MANIFEST = [
    { id: 'os-orientation', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Начало учебной среды', root: '[data-s30-story]', anchor: '[data-s30-step="enter"]', copy: '[data-s30-copy="enter"]', kind: 'read', minimumReadMs: 2200, motion: 'reveal', expectedState: 'Чистое пространство занятия' },
    { id: 'os-assignment', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Условие и рабочее окно', root: '[data-s30-story]', anchor: '[data-s30-step="task"]', copy: '[data-s30-copy="task"]', kind: 'read', minimumReadMs: 2400, motion: 'reveal', expectedState: 'Окно задания рядом с рабочей областью' },
    { id: 'os-code-watch', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Код решения развивается на экране', root: '[data-s30-story]', anchor: '[data-s30-step="typing-continue"]', copy: '[data-s30-copy="typing"]', kind: 'watch', animationSelector: '[data-s30-workspace]', minimumHoldMs: 1500, motion: 'product', expectedState: 'Код и задача находятся рядом' },
    { id: 'os-result-pass', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Результат решения', root: '[data-s30-story]', anchor: '[data-s30-step="result"]', copy: '[data-s30-copy="result"]', kind: 'pass-through', motion: 'product', expectedState: 'Результат вычисления показан' },
    { id: 'os-whiteboard-watch', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Формула и дерево исходов на холсте', root: '[data-s30-story]', anchor: '[data-s30-step="math-tree"]', copy: '[data-s30-copy="math-tree"]', kind: 'watch', animationSelector: '[data-s30-workspace]', minimumHoldMs: 1500, motion: 'product', expectedState: 'Схема и запись видны на одной доске' },
    { id: 'os-complete', chapter: 'hero', chapterTitle: 'BooStudy OS', label: 'Собранное учебное решение', root: '[data-s30-story]', anchor: '[data-s30-step="math-done"]', copy: '[data-s30-copy="math-done"]', kind: 'understand', minimumReadMs: 2400, minimumHoldMs: 900, motion: 'reveal', expectedState: 'Условие, схема и расчёт собраны вместе' },

    { id: 'homework-arrival', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Самостоятельная работа после урока', root: '[data-s38-homework]', progress: 0.08, copy: '[data-homework-copy-scene="arrival"]', kind: 'read', minimumReadMs: 2200, motion: 'chapter', expectedState: 'Открыта комната домашней работы' },
    { id: 'homework-tools-watch', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Инструменты рядом с условием', root: '[data-s38-homework]', progress: 0.56, copy: '[data-homework-copy-scene="tools"]', kind: 'watch', animationSelector: '.s38-homework-layout', minimumHoldMs: 1500, motion: 'product', expectedState: 'Окна условия, кода и ответа видны вместе' },
    { id: 'homework-result', chapter: 'homework', chapterTitle: 'Homework OS', label: 'Готовый результат и отправка', root: '[data-s38-homework]', progress: 0.92, copy: '[data-homework-copy-scene="handoff"]', kind: 'understand', minimumReadMs: 2200, minimumHoldMs: 900, motion: 'reveal', expectedState: 'Итог задания и следующий шаг видны' },

    { id: 'analytics-overview', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Что уже получается', root: '[data-s32-story]', progress: 0.12, copy: '.s32-copy', kind: 'read', minimumReadMs: 2200, motion: 'chapter', expectedState: 'Пояснение связано с аналитикой' },
    { id: 'analytics-growth-watch', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'График и навыки растут', root: '[data-s32-story]', progress: 0.58, mobileAnchor: '.s32-chart-wrap', mobileSurface: '.s32-chart-wrap', copy: '.s32-copy', kind: 'watch', animationSelector: '.s32-chart-wrap', minimumHoldMs: 1500, motion: 'product', expectedState: 'График прогресса полностью сформирован' },
    { id: 'analytics-summary', chapter: 'analytics', chapterTitle: 'Аналитика', label: 'Общая картина прогресса', root: '[data-s32-story]', progress: 0.91, mobileAnchor: '.s32-task-grid', mobileSurface: '.s32-task-grid', copy: '.s32-copy', kind: 'understand', minimumReadMs: 2500, minimumHoldMs: 1000, motion: 'reveal', expectedState: 'Динамика и карта навыков видны одновременно' },

    { id: 'dashboard-overview', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Центр подготовки', root: '[data-s36-story]', progress: 0.08, copy: '[data-copy-block="intro"]', kind: 'read', minimumReadMs: 2600, motion: 'chapter', expectedState: 'Основные области кабинета собраны вокруг ученика' },
    { id: 'dashboard-spotlight', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Расписание и следующий шаг', root: '[data-s36-story]', progress: 0.33, copy: '[data-copy-block="schedule"]', kind: 'watch', animationSelector: '.s36-story-layout', minimumHoldMs: 1500, motion: 'product', expectedState: 'Spotlight связывает ближайшее занятие с расписанием' },
    { id: 'dashboard-complete', chapter: 'dashboard', chapterTitle: 'Личный кабинет', label: 'Собранный кабинет ученика', root: '[data-s36-story]', progress: 0.93, copy: '[data-copy-block="complete"]', kind: 'understand', minimumReadMs: 2500, minimumHoldMs: 1000, motion: 'reveal', expectedState: 'Личный центр обучения виден целиком' },

    { id: 'schedule-week', chapter: 'schedule', chapterTitle: 'Расписание', label: 'План недели', root: '[data-s37-story]', progress: 0.08, copy: '[data-s37-copy-block="week"]', kind: 'read', minimumReadMs: 2200, motion: 'chapter', expectedState: 'Учебная неделя показана целиком' },
    { id: 'schedule-day-watch', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Выбранный день и занятие', root: '[data-s37-story]', progress: 0.32, copy: '[data-s37-copy-block="lesson"]', kind: 'watch', animationSelector: '.s37-layout', minimumHoldMs: 1500, motion: 'product', expectedState: 'Выбран день и раскрыта карточка урока' },
    { id: 'schedule-overview', chapter: 'schedule', chapterTitle: 'Расписание', label: 'Занятия, домашняя работа и свободный день', root: '[data-s37-story]', progress: 0.96, copy: '[data-s37-copy-block="overview"]', kind: 'understand', minimumReadMs: 2600, minimumHoldMs: 1000, motion: 'reveal', expectedState: 'Неделя и сроки домашней работы согласованы' },

    { id: 'theory-library', chapter: 'theory', chapterTitle: 'Теория', label: 'Материалы в библиотеке ученика', root: '[data-s39-theory]', progress: 0.08, copy: '[data-s39-theory-copy-step="library"]', kind: 'read', minimumReadMs: 2200, motion: 'chapter', expectedState: 'Открыта библиотека материалов' },
    { id: 'theory-structure-pass', chapter: 'theory', chapterTitle: 'Теория', label: 'Структура выбранной темы', root: '[data-s39-theory]', progress: 0.20, copy: '[data-s39-theory-copy-step="structure"]', kind: 'pass-through', motion: 'product', expectedState: 'Видны разделы выбранного материала' },
    { id: 'theory-notes-watch', chapter: 'theory', chapterTitle: 'Теория', label: 'Чтение и личные заметки', root: '[data-s39-theory]', progress: 0.68, copy: '[data-s39-theory-copy-step="notes"]', kind: 'watch', animationSelector: '[data-s39-theory-app]', minimumHoldMs: 1500, motion: 'product', expectedState: 'Заметка связана с текущей темой' },
    { id: 'theory-progress', chapter: 'theory', chapterTitle: 'Теория', label: 'Закладка и прогресс чтения', root: '[data-s39-theory]', progress: 0.79, copy: '[data-s39-theory-copy-step="progress"]', kind: 'understand', minimumReadMs: 2200, minimumHoldMs: 900, motion: 'reveal', expectedState: 'Позиция чтения и прогресс темы сохранены' },

    { id: 'profile-identity', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Личный учебный профиль', root: '[data-s39-profile]', progress: 0.08, mobileBreakpoint: 720, mobileSticky: true, copy: '[data-s39-profile-copy-step="identity"]', kind: 'read', minimumReadMs: 2500, motion: 'chapter', expectedState: 'Идентичность и личный прогресс видны' },
    { id: 'profile-achievements-watch', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Опыт и достижения', root: '[data-s39-profile]', progress: 0.42, mobileBreakpoint: 720, mobileSticky: true, copy: '[data-s39-profile-copy-step="achievements"]', kind: 'watch', animationSelector: '[data-s39-profile-app]', minimumHoldMs: 1500, motion: 'product', expectedState: 'XP и достижения раскрыты без переключения данных' },
    { id: 'profile-complete', chapter: 'profile', chapterTitle: 'Профиль ученика', label: 'Полная история прогресса', root: '[data-s39-profile]', progress: 0.98, mobileBreakpoint: 720, mobileSticky: true, copy: '[data-s39-profile-copy-step="complete"]', kind: 'understand', minimumReadMs: 2600, minimumHoldMs: 1000, motion: 'reveal', expectedState: 'Опыт, активность и достижения собраны в профиле' },

    { id: 'founder-story', chapter: 'founder', chapterTitle: 'Создатель BooStudy', label: 'Личная история и приглашение', root: '[data-s42-founder]', section: true, copy: '.s42-founder-copy', kind: 'founder', motion: 'founder', expectedState: 'Печатание завершено, Telegram и обучение доступны' }
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
  const keyframeCount = TOUR_MANIFEST.filter((episode) => episode.kind !== 'pass-through').length;

  function wordCount(text) {
    return (String(text || '').match(/[\p{L}\p{N}]+(?:[’'-][\p{L}\p{N}]+)*/gu) || []).length;
  }

  function getEpisodeText(episode) {
    const root = document.querySelector(episode.root);
    const copy = root?.querySelector(episode.copy);
    if (copy) return copy.innerText.trim();
    const visibleCopy = root?.querySelector('h1, h2, h3, p');
    return visibleCopy?.textContent.trim() || episode.label;
  }

  function cssTimeMs(value) {
    const text = String(value || '').trim();
    if (text.endsWith('ms')) return Number.parseFloat(text) || 0;
    if (text.endsWith('s')) return (Number.parseFloat(text) || 0) * 1000;
    return 0;
  }

  function configuredMotionMs(episode) {
    if (!episode.animationSelector) return 0;
    const root = document.querySelector(episode.root);
    const surface = root?.querySelector(episode.animationSelector);
    if (!surface) return 0;
    const nodes = [surface, ...surface.querySelectorAll('*')];
    return nodes.reduce((longest, node) => {
      const style = getComputedStyle(node);
      const transitionDurations = style.transitionDuration.split(',').map(cssTimeMs);
      const transitionDelays = style.transitionDelay.split(',').map(cssTimeMs);
      const transition = Math.max(0, ...transitionDurations.map((duration, index) => duration + (transitionDelays[index % transitionDelays.length] || 0)));
      const animationDurations = style.animationDuration.split(',').map(cssTimeMs);
      const animationDelays = style.animationDelay.split(',').map(cssTimeMs);
      const iterations = style.animationIterationCount.split(',').map((value) => value.trim());
      const animation = Math.max(0, ...animationDurations.map((duration, index) => {
        if (iterations[index % iterations.length] === 'infinite') return 0;
        return duration * (Number.parseFloat(iterations[index % iterations.length]) || 1) + (animationDelays[index % animationDelays.length] || 0);
      }));
      return Math.max(longest, transition, animation);
    }, 0);
  }

  function activeMotionRemainingMs(episode) {
    if (!episode.animationSelector) return 0;
    const root = document.querySelector(episode.root);
    const surface = root?.querySelector(episode.animationSelector);
    if (!surface) return 0;
    return Math.max(0, ...surface.getAnimations({ subtree: true }).map((animation) => {
      const timing = animation.effect?.getComputedTiming();
      if (!timing || !Number.isFinite(timing.endTime) || animation.playState === 'finished' || animation.playState === 'idle') return 0;
      return Math.max(0, Number(timing.endTime) - (Number(animation.currentTime) || 0));
    }));
  }

  function estimateReadMs(episode, speed = 1) {
    if (!['read', 'understand', 'watch'].includes(episode.kind)) return 0;
    const text = getEpisodeText(episode);
    const words = wordCount(text);
    const clauses = (text.match(/[.!?;:]/gu) || []).length;
    const complexity = episode.readingComplexity || clamp(1 + clauses / Math.max(12, words * 1.6), 1, 1.24);
    const readingRate = episode.wordsPerMinute || 170;
    const punctuationAllowance = Math.min(1400, clauses * 55);
    const base = words * (60000 / readingRate) * complexity + punctuationAllowance;
    const readableSpeed = Math.min(1.25, Math.max(0.75, speed));
    return Math.max(episode.minimumReadMs || 1700, base / readableSpeed);
  }

  function estimateWatchMs(episode, speed = 1) {
    if (episode.kind !== 'watch') return 0;
    return Math.max(episode.minimumHoldMs || 650, configuredMotionMs(episode)) / Math.max(0.75, speed);
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

  function travelMs(from, to, speed = 1, episode, previousEpisode) {
    if (motionPreference.matches) return 0;
    const style = episode?.motion || 'product';
    const baseViewportRate = style === 'chapter' ? 1.45 : style === 'reveal' ? 0.88 : style === 'founder' ? 0.72 : 0.82;
    const pixelsPerSecond = Math.max(1, window.innerHeight) * baseViewportRate * speed;
    return Math.max(16, Math.abs(to - from) / pixelsPerSecond * 1000);
  }

  function hermiteProgress(progress, startTangent, endTangent) {
    const t = progress;
    const t2 = t * t;
    const t3 = t2 * t;
    return (t3 - 2 * t2 + t) * startTangent
      + (-2 * t3 + 3 * t2)
      + (t3 - t2) * endTangent;
  }

  function estimateTourMs(speed = 1) {
    let cursor = 0;
    return TOUR_MANIFEST.reduce((sum, episode) => {
      const target = targetFor(episode);
      const move = travelMs(cursor, target, speed, episode, null);
      const focus = estimateReadMs(episode, speed);
      const watch = estimateWatchMs(episode, speed);
      const understand = episode.kind === 'understand' ? (episode.minimumHoldMs || 750) / Math.max(0.75, speed) : 0;
      const founder = episode.chapter === 'founder'
        ? (window.BooStudyFounderReveal?.estimatedDuration?.(speed) || episode.founderRevealMs / speed)
        : 0;
      cursor = target;
      return sum + move + focus + watch + understand + founder;
    }, 0);
  }

  function formatDuration(ms) {
    const minutes = Math.max(1, Math.round(ms / 60000));
    return `≈${minutes} мин · чтение и сцены учтены`;
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
      this.syncSpeedPresentation();
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
          <button class="rc3-tour-panel__icon" type="button" data-rc3-prev aria-label="Предыдущий смысловой этап" title="Назад">‹</button>
          <button class="rc3-tour-panel__play" type="button" data-rc3-play aria-label="Пауза экскурсии" title="Пауза"><span data-rc3-play-icon aria-hidden="true">Ⅱ</span><span class="rc3-sr-only">Пауза экскурсии</span></button>
          <button class="rc3-tour-panel__icon" type="button" data-rc3-next aria-label="Следующий смысловой этап" title="Дальше">›</button>
          <div class="rc3-speed-control" data-rc3-speed-control>
            <button class="rc3-tour-panel__speed" type="button" data-rc3-speed-trigger aria-haspopup="menu" aria-expanded="false" aria-controls="rc3-speed-menu">1×</button>
            <div class="rc3-tour-panel__popover rc3-tour-panel__speed-menu" id="rc3-speed-menu" role="menu" aria-label="Скорость экскурсии" data-rc3-speed-menu hidden>
              <button type="button" role="menuitemradio" aria-checked="false" data-rc3-speed-option="0.75">0,75×</button>
              <button type="button" role="menuitemradio" aria-checked="true" data-rc3-speed-option="1">1×</button>
              <button type="button" role="menuitemradio" aria-checked="false" data-rc3-speed-option="1.25">1,25×</button>
              <button type="button" role="menuitemradio" aria-checked="false" data-rc3-speed-option="1.5">1,5×</button>
              <button type="button" role="menuitemradio" aria-checked="false" data-rc3-speed-option="2">2×</button>
            </div>
          </div>
          <button class="rc3-tour-panel__icon rc3-tour-panel__more-toggle" type="button" data-rc3-more-toggle aria-haspopup="menu" aria-expanded="false" aria-controls="rc3-tour-more" aria-label="Дополнительные действия" title="Дополнительно">•••</button>
          <div class="rc3-tour-panel__popover rc3-tour-panel__more-menu" id="rc3-tour-more" role="menu" aria-label="Дополнительные действия" data-rc3-more-menu hidden>
            <button type="button" role="menuitem" data-rc3-restart>Сначала</button>
            <button type="button" role="menuitem" data-rc3-exit>В ручной режим</button>
          </div>
          <button class="rc3-tour-panel__collapse" type="button" data-rc3-collapse aria-label="Свернуть панель" aria-expanded="true" title="Свернуть">⌄</button>
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
        playIcon: panel.querySelector('[data-rc3-play-icon]'),
        prev: panel.querySelector('[data-rc3-prev]'),
        next: panel.querySelector('[data-rc3-next]'),
        speedControl: panel.querySelector('[data-rc3-speed-control]'),
        speedTrigger: panel.querySelector('[data-rc3-speed-trigger]'),
        speedMenu: panel.querySelector('[data-rc3-speed-menu]'),
        speedOptions: [...panel.querySelectorAll('[data-rc3-speed-option]')],
        moreTrigger: panel.querySelector('[data-rc3-more-toggle]'),
        moreMenu: panel.querySelector('[data-rc3-more-menu]'),
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
      this.panelNodes.speedTrigger.addEventListener('click', () => this.toggleMenu('speed'));
      this.panelNodes.speedOptions.forEach((option, index) => {
        option.addEventListener('click', () => {
          this.setSpeed(Number(option.dataset.rc3SpeedOption));
          this.closeMenus(true);
        });
        option.addEventListener('keydown', (event) => {
          if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const targetIndex = event.key === 'Home' ? 0 : event.key === 'End' ? SPEEDS.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : SPEEDS.length - 1)) % SPEEDS.length;
          this.panelNodes.speedOptions[targetIndex].focus();
        });
      });
      this.panelNodes.speedTrigger.addEventListener('keydown', (event) => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        if (!this.panelNodes.speedMenu.hidden) return;
        this.toggleMenu('speed', true);
      });
      this.panelNodes.moreTrigger.addEventListener('click', () => this.toggleMenu('more'));
      this.panelNodes.collapse.addEventListener('click', () => {
        this.collapsed = !this.collapsed;
        panel.dataset.collapsed = String(this.collapsed);
        this.panelNodes.collapse.setAttribute('aria-expanded', String(!this.collapsed));
        this.panelNodes.collapse.setAttribute('aria-label', this.collapsed ? 'Развернуть панель' : 'Свернуть панель');
        this.panelNodes.collapse.title = this.collapsed ? 'Развернуть' : 'Свернуть';
        this.panelNodes.collapse.textContent = this.collapsed ? '⌃' : '⌄';
        if (this.collapsed) this.closeMenus(false);
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
      this.panelNodes.moreMenu.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          this.closeMenus(true);
        }
      });
      document.addEventListener('pointerdown', (event) => {
        if (!panel.contains(event.target)) this.closeMenus(false);
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && (!this.panelNodes.speedMenu.hidden || !this.panelNodes.moreMenu.hidden)) {
          event.preventDefault();
          const focusTarget = !this.panelNodes.speedMenu.hidden ? this.panelNodes.speedTrigger : this.panelNodes.moreTrigger;
          this.closeMenus(false);
          focusTarget.focus();
        }
      });
    }

    toggleMenu(name, forceOpen = false) {
      const isSpeed = name === 'speed';
      const menu = isSpeed ? this.panelNodes.speedMenu : this.panelNodes.moreMenu;
      const trigger = isSpeed ? this.panelNodes.speedTrigger : this.panelNodes.moreTrigger;
      const open = forceOpen || menu.hidden;
      this.closeMenus(false);
      if (!open) return;
      const triggerRect = trigger.getBoundingClientRect();
      const availableBelow = window.innerHeight - triggerRect.bottom;
      panel.dataset.popoverDirection = availableBelow < 180 ? 'up' : 'down';
      menu.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      if (isSpeed) {
        const selected = this.panelNodes.speedOptions.find((option) => Number(option.dataset.rc3SpeedOption) === this.speed) || this.panelNodes.speedOptions[1];
        selected.focus();
      } else this.panelNodes.restart.focus();
    }

    closeMenus(returnFocus = false) {
      if (!this.panelNodes.speedMenu) return;
      const speedWasOpen = !this.panelNodes.speedMenu.hidden;
      const moreWasOpen = !this.panelNodes.moreMenu.hidden;
      this.panelNodes.speedMenu.hidden = true;
      this.panelNodes.moreMenu.hidden = true;
      this.panelNodes.speedTrigger.setAttribute('aria-expanded', 'false');
      this.panelNodes.moreTrigger.setAttribute('aria-expanded', 'false');
      if (returnFocus && speedWasOpen) this.panelNodes.speedTrigger.focus();
      else if (returnFocus && moreWasOpen) this.panelNodes.moreTrigger.focus();
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
      this.durationByEpisode = TOUR_MANIFEST.map((episode, index) => {
        const target = targetFor(episode);
        const previousEpisode = TOUR_MANIFEST[index - 1];
        const phases = {
          move: travelMs(cursor, target, this.speed, episode, previousEpisode),
          founder: episode.chapter === 'founder'
            ? (window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || episode.founderRevealMs / this.speed)
            : 0,
          read: estimateReadMs(episode, this.speed),
          watch: estimateWatchMs(episode, this.speed),
          understand: episode.kind === 'understand' ? (episode.minimumHoldMs || 750) / Math.max(0.75, this.speed) : 0
        };
        cursor = target;
        return { target, phases, total: Object.values(phases).reduce((sum, value) => sum + value, 0) };
      });
    }

    startAuto() {
      this.cancelPhase();
      this.startedAt = performance.now();
      this.timelineEvents = [];
      window.__rc33TourDiagnostics = { startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, checkpointCount: keyframeCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, kind, type }) => ({ id, chapter, label, kind: kind || type })) };
      this.currentIndex = 0;
      this.phase = 'move';
      this.routeStartY = window.scrollY;
      this.rebuildDurationModel(this.routeStartY);
      this.setPanelVisible(true);
      this.collapsed = false;
      delete panel.dataset.collapsed;
      this.closeMenus(false);
      this.syncSpeedPresentation();
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
      const previousEpisode = TOUR_MANIFEST[this.currentIndex];
      this.cancelPhase();
      this.currentIndex = clamp(index, 0, totalStops - 1);
      const episode = TOUR_MANIFEST[this.currentIndex];
      prepareMobileTourPresentation(episode);
      const token = this.generation;
      this.phase = 'move';
      this.phaseFromY = window.scrollY;
      this.phaseToY = targetFor(episode);
      this.motionTangents = {
        start: previousEpisode?.kind === 'pass-through' ? 1 : 0,
        end: episode.kind === 'pass-through' ? 1 : 0
      };
      this.phaseRemaining = travelMs(this.phaseFromY, this.phaseToY, this.speed, episode, previousEpisode);
      this.phaseDuration = this.phaseRemaining;
      this.phaseStartProgress = 0;
      this.timelineEvents ||= [];
      this.timelineEvents.push({ event: 'segment-start', atMs: Math.round(performance.now() - (this.startedAt || performance.now())), episodeId: episode.id, checkpointKind: episode.kind, fromY: Math.round(this.phaseFromY), targetY: Math.round(this.phaseToY), motion: episode.motion });
      window.__rc33TourDiagnostics && (window.__rc33TourDiagnostics.events = this.timelineEvents);
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
        const eased = hermiteProgress(progress, this.motionTangents?.start || 0, this.motionTangents?.end || 0);
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
      if (episode.kind === 'pass-through') {
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
      if (episode.kind === 'founder') {
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
      if (episode.kind === 'watch') {
        const animations = this.watchedAnimationsFor(episode);
        this.watchedAnimations = animations;
        animations.forEach((animation) => { animation.playbackRate = this.speed; });
        const readMs = this.readDurationFor(episode);
        this.timelineEvents.push({ event: 'read-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, words: wordCount(getEpisodeText(episode)), durationMs: Math.round(readMs), followedBy: 'watch', scrollY: Math.round(window.scrollY) });
        if (remainPaused || this.state === 'auto-paused') {
          this.phase = 'read';
          this.phaseRemaining = readMs;
          this.phaseDuration = readMs;
          this.setState('auto-paused', 'Пауза · текст и демонстрация сохранены');
          this.updatePanel();
        } else this.startTimedPhase('read', readMs, token);
        return;
      }
      this.phase = 'read';
      this.phaseProgress = 0;
      const readMs = this.readDurationFor(episode);
      this.timelineEvents.push({ event: 'read-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, words: wordCount(getEpisodeText(episode)), durationMs: Math.round(readMs), scrollY: Math.round(window.scrollY) });
      if (remainPaused || this.state === 'auto-paused') {
        this.phaseRemaining = readMs;
        this.phaseDuration = readMs;
        this.setState('auto-paused', 'Пауза · текст сохранён');
        this.updatePanel();
      } else this.startTimedPhase('read', readMs, token);
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

    watchedAnimationsFor(episode) {
      const root = document.querySelector(episode.root);
      const surface = root?.querySelector(episode.animationSelector);
      if (!surface) return [];
      return surface.getAnimations({ subtree: true }).filter((animation) => {
        const timing = animation.effect?.getComputedTiming();
        return timing && Number.isFinite(timing.endTime) && timing.endTime > 0 && animation.playState !== 'finished' && animation.playState !== 'idle';
      });
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
      const episode = TOUR_MANIFEST[this.currentIndex];
      if (this.phase === 'read' && episode.kind === 'watch') {
        this.timelineEvents.push({ event: 'read-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
        const measuredMotionMs = activeMotionRemainingMs(episode) / Math.max(0.75, this.speed);
        const holdMs = Math.max(episode.minimumHoldMs || 1500, measuredMotionMs);
        this.timelineEvents.push({ event: 'watch-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, animationCount: this.watchedAnimations?.length || 0, measuredMotionMs: Math.round(measuredMotionMs), minimumHoldMs: episode.minimumHoldMs || 1500, durationMs: Math.round(holdMs), scrollY: Math.round(window.scrollY) });
        this.startTimedPhase('watch', holdMs, token);
        return;
      }
      if (this.phase === 'read' && episode.kind === 'understand') {
        this.timelineEvents.push({ event: 'read-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
        this.startTimedPhase('understand', (episode.minimumHoldMs || 750) / Math.max(0.75, this.speed), token);
        return;
      }
      if (this.phase === 'watch') {
        const remainingMotionMs = activeMotionRemainingMs(episode) / Math.max(0.75, this.speed);
        if (remainingMotionMs > 80) {
          this.timelineEvents.push({ event: 'watch-extended', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, remainingMotionMs: Math.round(remainingMotionMs) });
          this.startTimedPhase('watch', remainingMotionMs, token);
          return;
        }
        this.timelineEvents.push({ event: 'watch-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
      } else if (this.phase === 'read') {
        this.timelineEvents.push({ event: 'read-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
      } else if (this.phase === 'understand') {
        this.timelineEvents.push({ event: 'understand-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
      }
      if (['read', 'watch', 'understand'].includes(this.phase)) {
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
      }
    }

    pause(message = '') {
      if (!this.isPlaying() || this.state === 'auto-paused' || this.state === 'auto-complete') return;
      if (['move', 'read', 'watch', 'understand'].includes(this.phase)) {
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
      else if (['read', 'watch', 'understand'].includes(this.phase)) this.startTimedPhase(this.phase, this.phaseRemaining, token);
      else this.startTimedPhase(this.phase, this.phaseRemaining, token);
    }

    setSpeed(speed) {
      if (!SPEEDS.includes(speed)) return;
      const previousSpeed = this.speed;
      if (speed === previousSpeed) return;
      const ratio = this.phase === 'read'
        ? clamp(previousSpeed, 0.75, 1.25) / clamp(speed, 0.75, 1.25)
        : previousSpeed / speed;
      if (this.phase === 'founder' && this.phaseRemaining > 0) {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseRemaining - elapsed) * ratio;
        this.phaseDuration = this.phaseRemaining;
        this.phaseStartedAt = performance.now();
        if (this.rafId) cancelAnimationFrame(this.rafId);
        this.rafId = 0;
      } else if (['move', 'read', 'watch', 'understand'].includes(this.phase) && this.phaseRemaining > 0) {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseRemaining - elapsed) * ratio;
        if (this.rafId) cancelAnimationFrame(this.rafId);
        if (this.timerId) clearTimeout(this.timerId);
        this.rafId = 0;
        this.timerId = 0;
      }
      this.speed = speed;
      this.syncSpeedPresentation();
      this.watchedAnimations?.forEach((animation) => {
        try { animation.playbackRate = speed; } catch { /* Finished animations cannot always change rate. */ }
      });
      this.rebuildDurationModel(this.routeStartY);
      if (this.phase === 'founder') window.BooStudyFounderReveal?.setSpeed?.(speed);
      if (this.isPlaying() && ['move', 'read', 'watch', 'understand'].includes(this.phase)) {
        if (this.phase === 'move') {
          this.phaseToY = targetFor(TOUR_MANIFEST[this.currentIndex]);
          this.animateMove(this.generation);
        } else this.startTimedPhase(this.phase, this.phaseRemaining, this.generation);
      }
      this.statusMessage = `Скорость ${String(speed).replace('.', ',')}× · текущий эпизод сохранён`;
      this.updatePanel();
    }

    syncSpeedPresentation() {
      if (!this.panelNodes.speedTrigger) return;
      const label = `${String(this.speed).replace('.', ',')}×`;
      this.panelNodes.speedTrigger.textContent = label;
      this.panelNodes.speedTrigger.setAttribute('aria-label', `Скорость экскурсии: ${label}`);
      this.panelNodes.speedOptions.forEach((option) => {
        const selected = Number(option.dataset.rc3SpeedOption) === this.speed;
        option.setAttribute('aria-checked', String(selected));
        option.tabIndex = selected ? 0 : -1;
      });
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
        this.startAuto();
        return;
      }
      window.BooStudyFounderReveal?.finish?.();
      this.setState(this.activeState(), 'Экскурсия начинается сначала');
      this.startedAt = performance.now();
      this.timelineEvents = [];
      window.__rc33TourDiagnostics = { startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, checkpointCount: keyframeCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, kind, type }) => ({ id, chapter, label, kind: kind || type })) };
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
      window.__rc33TourDiagnostics.durationMs = Math.round(performance.now() - this.startedAt);
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
      const episode = this.durationByEpisode[this.currentIndex] || { phases: { move: 0, read: 0, watch: 0, understand: 0, founder: 0 }, total: 1 };
      const phaseOrder = ['move', 'read', 'watch', 'understand', 'founder'];
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
      const phaseOrder = ['move', 'read', 'watch', 'understand', 'founder'];
      const phaseIndex = phaseOrder.indexOf(this.phase);
      const currentRemaining = phaseIndex < 0 ? current.total : Math.max(0, this.phaseRemaining) + phaseOrder.slice(phaseIndex + 1).reduce((sum, key) => sum + current.phases[key], 0);
      return currentRemaining + this.durationByEpisode.slice(this.currentIndex + 1).reduce((sum, item) => sum + item.total, 0);
    }

    phaseLabel() {
      if (this.phase === 'move') return 'TRAVEL · непрерывное движение по главе';
      if (this.phase === 'verify') return 'Проверяем видимость сцены';
      if (this.phase === 'visual-error') return 'Сцена не подтверждена · экскурсия остановлена';
      if (this.phase === 'read') return 'READ · время для текста';
      if (this.phase === 'watch') return 'WATCH · продуктовая анимация';
      if (this.phase === 'understand') return 'UNDERSTAND · готовый результат';
      if (this.phase === 'founder') return 'FOUNDER · печатается личное обращение';
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
      const playLabel = this.state === 'auto-paused' ? 'Продолжить экскурсию' : this.state === 'auto-complete' ? 'Повторить экскурсию' : 'Пауза экскурсии';
      this.panelNodes.playIcon.textContent = this.state === 'auto-paused' ? '▶' : this.state === 'auto-complete' ? '↻' : 'Ⅱ';
      this.panelNodes.play.setAttribute('aria-label', playLabel);
      this.panelNodes.play.title = playLabel;
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
      panel.dataset.checkpoints = String(keyframeCount);
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
