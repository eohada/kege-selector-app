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

  const NARRATIVE = window.BooStudyNarrativeBeats;
  if (!NARRATIVE?.beats?.length) return;
  const TOUR_MANIFEST = NARRATIVE.beats.map((beat) => ({ ...beat, kind: beat.kind === 'founder' ? 'founder' : 'message' }));

  const chapterNames = [...new Set(TOUR_MANIFEST.map((item) => item.chapter))];
  const totalStops = TOUR_MANIFEST.length;
  const keyframeCount = TOUR_MANIFEST.length;

  function wordCount(text) {
    return (String(text || '').match(/[\p{L}\p{N}]+(?:[’'-][\p{L}\p{N}]+)*/gu) || []).length;
  }

  function getEpisodeText(episode) {
    if (episode.kind === 'founder') return episode.expectedText || '';
    const root = document.querySelector(episode.root);
    return (episode.textTargets || []).flatMap((selector) => [...(root?.querySelectorAll(selector) || [])])
      .filter((node) => !node.closest('[aria-hidden="true"]'))
      .map((node) => (node.innerText || node.textContent || '').trim())
      .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
  }

  function estimateReadMs(episode, speed = 1) {
    if (episode.kind !== 'message') return 0;
    const text = episode.expectedText || getEpisodeText(episode);
    const words = wordCount(text);
    const clauses = (text.match(/[.!?;:]/gu) || []).length;
    const complexity = episode.attentionLoad === 'dense-data' || episode.attentionLoad === 'dense-material' ? 1.22 : episode.attentionLoad === 'full-composition' ? 1.16 : 1;
    const readingRate = NARRATIVE.reading.wordsPerMinute || 165;
    const punctuationAllowance = clauses * (NARRATIVE.reading.punctuationMsPerMark || 80);
    const base = words * (60000 / readingRate) * complexity + punctuationAllowance;
    return Math.max(NARRATIVE.reading.minimumMs || 2400, base / clamp(speed, 0.75, 1.5));
  }

  function estimateFounderFinalReadMs(episode, speed = 1) {
    if (episode.chapter !== 'founder') return 0;
    return (episode.subbeats || [])
      .filter((beat) => Number.isInteger(beat.block))
      .reduce((total, beat) => total + estimateReadMs({ kind: 'message', expectedText: beat.text }, speed), 0);
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
    if (!(episode.mobileAnchor || episode.mobileSticky || episode.chapter === 'analytics')
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
    const minVisibleFraction = kind === 'copy' ? NARRATIVE.visibility.minimumVisibleFraction : kind === 'surface' ? 0.12 : 0.12;
    let targetHits = 0;
    const sampleCount = 3;
    for (let row = 1; row <= sampleCount; row += 1) {
      for (let column = 1; column <= sampleCount; column += 1) {
        const x = visible.left + width * column / (sampleCount + 1);
        const y = visible.top + height * row / (sampleCount + 1);
        const hit = x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight ? document.elementFromPoint(x, y) : null;
        if (hit && (node === hit || node.contains(hit) || hit.contains(node))) targetHits += 1;
      }
    }
    const text = (node.innerText || node.textContent || '').trim().replace(/\s+/g, ' ');
    const pass = !hiddenByAncestor && !ariaHidden && opacity >= (kind === 'copy' ? NARRATIVE.visibility.minimumOpacity : 0.08)
      && width >= 1 && height >= 1 && visibleArea >= minArea
      && visibleArea / fullArea >= minVisibleFraction
      && targetHits > 0
      && (kind !== 'copy' || text.length > 0);
    return {
      pass,
      reason: pass ? '' : (!text && kind === 'copy' ? 'no-text' : ariaHidden ? 'aria-hidden' : hiddenByAncestor ? 'hidden-ancestor' : opacity < (kind === 'copy' ? NARRATIVE.visibility.minimumOpacity : 0.08) ? 'not-fully-opaque' : visibleArea < minArea ? 'visible-area-too-small' : visibleArea / fullArea < minVisibleFraction ? 'clipped-or-outside-viewport' : targetHits === 0 ? 'occluded' : 'not-visible'),
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
    const surfaceSelector = episode.surface;
    const surface = root?.querySelector(surfaceSelector) || document.querySelector(surfaceSelector);
    const rootTop = root ? root.getBoundingClientRect().top + window.scrollY : 0;
    const tourRange = Number(root?.dataset.rc3TourProgressRange);
    const calibratedRange = Number(root?.dataset.s40ProgressRange);
    const storyRange = Number.isFinite(tourRange) && tourRange > 0
      ? tourRange
      : Number.isFinite(calibratedRange) && calibratedRange > 0
        ? calibratedRange
        : root ? Math.max(1, root.offsetHeight - window.innerHeight) : 1;
    const surfaceReport = inspectVisibleNode(surface, 'surface');
    if (episode.kind === 'founder') {
      const heading = inspectVisibleNode(document.querySelector('#s42-founder-title'), 'copy');
      const actualText = heading.text.replace(/\s+/g, ' ').trim();
      const expectedText = episode.expectedHeadline.replace(/\s+/g, ' ').trim();
      const copyReport = { ...heading, actualText, expectedText, wordCount: wordCount(actualText), pass: heading.pass && actualText === expectedText };
      return { episodeId: episode.id, chapter: episode.chapter, expectedObject: episode.label, scrollY: Math.round(window.scrollY), progress: 1, phase: 'verify', surfaceSelector, surface: surfaceReport, copy: copyReport, pass: surfaceReport.pass && copyReport.pass };
    }
    const textNodes = (episode.textTargets || []).flatMap((selector) => [...(root?.querySelectorAll(selector) || [])]);
    const actualText = textNodes.map((node) => (node.innerText || node.textContent || '').trim()).filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
    const expectedText = String(episode.expectedText || '').replace(/\s+/g, ' ').trim();
    const textReports = textNodes.map((node) => inspectVisibleNode(node, 'copy'));
    const stateNode = episode.state?.selector ? (root?.matches(episode.state.selector) ? root : root?.querySelector(episode.state.selector)) : null;
    const stateValue = episode.state?.attribute ? stateNode?.getAttribute(episode.state.attribute) : stateNode?.textContent?.trim();
    const statePass = Boolean(stateNode)
      && (episode.state?.text ? stateNode.textContent.replace(/\s+/g, ' ').includes(episode.state.text) : true)
      && (episode.state?.value ? stateValue === episode.state.value : true);
    const productNode = episode.productCheck?.selector ? root?.querySelector(episode.productCheck.selector) || document.querySelector(episode.productCheck.selector) : null;
    const productPass = !episode.productCheck || Boolean(productNode && productNode.textContent.replace(/\s+/g, ' ').includes(episode.productCheck.text));
    const copyReport = {
      pass: textNodes.length >= 2 && textReports.every((item) => item.pass) && actualText === expectedText && statePass && productPass,
      reason: actualText !== expectedText ? 'active-message-mismatch' : !statePass ? 'product-scene-state-mismatch' : !productPass ? 'product-result-mismatch' : textReports.find((item) => !item.pass)?.reason || '',
      expectedText, actualText, wordCount: wordCount(actualText), textTargets: textReports,
      state: { selector: episode.state?.selector, expected: episode.state?.value || episode.state?.text, actual: stateValue, pass: statePass },
      productCheck: { selector: episode.productCheck?.selector || null, expected: episode.productCheck?.text || null, actual: productNode?.textContent?.replace(/\s+/g, ' ').trim() || '', pass: productPass }
    };
    return {
      episodeId: episode.id,
      chapter: episode.chapter,
      expectedObject: episode.label,
      scrollY: Math.round(window.scrollY),
      progress: Number(clamp((window.scrollY - rootTop) / storyRange, 0, 1).toFixed(3)),
      phase: 'verify',
      surfaceSelector,
      copySelector: episode.textTargets,
      surface: surfaceReport,
      copy: copyReport,
      pass: surfaceReport.pass && copyReport.pass
    };
  }

  function travelMs(from, to, speed = 1, episode, previousEpisode) {
    if (motionPreference.matches) return 0;
    const profile = episode?.camera || NARRATIVE.cameraProfiles?.product || { screensPerSecond: 0.65, minMs: 500, maxMs: 2200 };
    const screens = Math.abs(to - from) / Math.max(1, window.innerHeight);
    const seconds = screens / Math.max(0.2, profile.screensPerSecond || 0.65);
    const boundaryFactor = previousEpisode && previousEpisode.chapter !== episode?.chapter ? 1.05 : 1;
    return clamp(seconds * 1000 * boundaryFactor / speed, (profile.minMs || 420) / speed, (profile.maxMs || 2200) / speed);
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
      const focus = estimateReadMs(episode, speed) + 150;
      const demonstrationTarget = episode.demonstrateTo ? targetFor({ ...episode, progress: episode.demonstrateTo }) : target;
      const demonstrate = episode.demonstrateTo ? travelMs(target, demonstrationTarget, speed, { ...episode, camera: episode.demonstrateCamera || episode.camera }, episode) : 0;
      const founder = episode.chapter === 'founder'
        ? (window.BooStudyFounderReveal?.estimatedDuration?.(speed) || 45000 / speed)
        : 0;
      const founderRead = estimateFounderFinalReadMs(episode, speed);
      cursor = demonstrationTarget;
      return sum + move + focus + demonstrate + founder + founderRead;
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
      this.visibilityTimerId = 0;
      this.founderStaticVisibilityTimerId = 0;
      this.founderVisibilityLastSample = 0;
      this.founderReadBlockIndex = -1;
      this.founderReadRecord = null;
      this.founderStaticReadGatePending = false;
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
      document.addEventListener('boostudy:typewriter-progress', (event) => this.recordFounderTypewriterProgress(event));
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
      const startedAt = performance.now();
      let readableAt = 0;
      let firstVisibleAt = 0;
      let attempt = 0;
      while (performance.now() - startedAt < 4200) {
        attempt += 1;
        if (token !== this.generation) return null;
        finalReport = { ...inspectEpisode(episode), attempt, phase: 'verify' };
        this.visualDiagnostics.push(finalReport);
        if (finalReport.copy?.pass && finalReport.copy?.actualText) firstVisibleAt ||= performance.now();
        if (finalReport.pass) {
          readableAt ||= performance.now();
          if (performance.now() - readableAt >= (NARRATIVE.reading.minimumStableVisibilityMs || 160)) {
            finalReport.phase = 'readable';
            finalReport.visibleSinceMs = Math.round(firstVisibleAt - this.startedAt);
            finalReport.readableSinceMs = Math.round(readableAt - this.startedAt);
            finalReport.verificationWaitMs = Math.round(performance.now() - startedAt);
            this.visualReports.push(finalReport);
            this.lastVisualReport = finalReport;
            if (episode.kind === 'message') {
              finalReport.textTimeline = { id: episode.id, expected: finalReport.copy?.expectedText, actual: finalReport.copy?.actualText, firstVisibleAtMs: finalReport.visibleSinceMs, fullyReadableAtMs: finalReport.readableSinceMs, opacity: finalReport.copy?.textTargets?.map((item) => item.opacity), visibleFraction: finalReport.copy?.textTargets?.map((item) => item.visibleFraction), state: finalReport.copy?.state, readableMs: 0, requiredMs: estimateReadMs(episode, this.speed), pass: false };
              window.__rc34NarrativeDiagnostics?.visibleText.push(finalReport.textTimeline);
            }
            this.timelineEvents.push({ event: 'message-readable', atMs: finalReport.readableSinceMs, episodeId: episode.id, expectedText: finalReport.copy?.expectedText, actualText: finalReport.copy?.actualText, wordCount: finalReport.copy?.wordCount, opacity: finalReport.copy?.textTargets?.map((item) => item.opacity), visibleFraction: finalReport.copy?.textTargets?.map((item) => item.visibleFraction) });
            return finalReport;
          }
        } else {
          readableAt = 0;
        }
        await new Promise((resolve) => setTimeout(resolve, 80));
      }
      this.lastVisualReport = finalReport;
      return finalReport;
    }

    startFounderStaticVisibilityTracking() {
      if (this.founderStaticVisibilityTimerId) return;
      this.founderVisibilityLastSample = performance.now();
      this.founderStaticVisibilityTimerId = window.setInterval(() => {
        const now = performance.now();
        if (!this.isPlaying() || !['founder', 'read'].includes(this.phase)) {
          this.founderVisibilityLastSample = now;
          return;
        }
        const elapsedMs = Math.min(120, Math.max(0, now - this.founderVisibilityLastSample));
        this.founderVisibilityLastSample = now;
        const episode = TOUR_MANIFEST[this.currentIndex];
        const records = [...(this.founderStaticTextRecords || []), ...(window.__rc34NarrativeDiagnostics?.visibleText || []).filter((record) => record.presentation === 'typewriter')];
        records.forEach((record) => {
          const beat = episode?.subbeats?.find((item) => item.id === record.id);
          const node = Number.isInteger(beat?.block)
            ? [...document.querySelectorAll('[data-typewriter]')][beat.block]
            : document.querySelector(record.target || beat?.target);
          if (inspectVisibleNode(node, 'copy').pass) record.readableMs = (record.readableMs || 0) + elapsedMs;
        });
      }, 100);
    }

    stopFounderStaticVisibilityTracking() {
      if (this.founderStaticVisibilityTimerId) clearInterval(this.founderStaticVisibilityTimerId);
      this.founderStaticVisibilityTimerId = 0;
      this.founderVisibilityLastSample = 0;
    }

    async waitForFounderStaticReading() {
      const token = this.generation;
      this.founderStaticReadGatePending = true;
      const startedAt = performance.now();
      let records = [];
      while (token === this.generation && this.isAutoMode() && !records.length) {
        records = this.founderStaticTextRecords || [];
        if (!records.length) await new Promise((resolve) => setTimeout(resolve, 40));
      }
      if (token !== this.generation || !this.isAutoMode()) return false;
      const requiredFor = (record) => estimateReadMs({ kind: 'message', expectedText: record.expected }, this.speed);
      const requiredMs = Math.max(0, ...records.map(requiredFor));
      this.timelineEvents.push({ event: 'founder-static-read-start', atMs: Math.round(startedAt - this.startedAt), requiredMs: Math.round(requiredMs), messages: records.map((record) => record.id) });
      while (token === this.generation && this.isAutoMode()) {
        if (this.isPlaying() && records.every((record) => (record.readableMs || 0) >= requiredFor(record))) break;
        if (performance.now() - startedAt > requiredMs + 12000) {
          this.founderStaticReadGatePending = false;
          this.stopOnVisualFailure({ expectedObject: 'заголовок и авторское вступление', copy: { reason: 'founder-static-copy-did-not-reach-readable-coverage', records: records.map((record) => ({ id: record.id, readableMs: Math.round(record.readableMs || 0), requiredMs: Math.round(requiredFor(record)) })) } });
          return false;
        }
        await new Promise((resolve) => setTimeout(resolve, 80));
      }
      if (token !== this.generation || !this.isAutoMode()) return false;
      this.founderStaticReadGatePending = false;
      this.timelineEvents.push({ event: 'founder-static-read-end', atMs: Math.round(performance.now() - this.startedAt), readable: records.map((record) => ({ id: record.id, readableMs: Math.round(record.readableMs || 0), requiredMs: Math.round(requiredFor(record)) })) });
      return true;
    }

    recordFounderTypewriterProgress(event) {
      if (this.phase !== 'founder' || !this.isAutoMode()) return;
      const detail = event.detail || {};
      const blockIndex = Number(detail.block);
      const beat = TOUR_MANIFEST[this.currentIndex]?.subbeats?.[blockIndex + 2];
      const node = [...document.querySelectorAll('[data-typewriter]')][blockIndex];
      if (!beat || !node) return;
      const output = node.querySelector('.s42-typewriter-output');
      const actual = (output?.textContent || '').replace(/\s+/g, ' ').trim();
      const atMs = Math.round(performance.now() - this.startedAt);
      if (detail.index === 1) {
        this.founderBlockVisibleAt ||= {};
        this.founderBlockVisibleAt[blockIndex] = atMs;
        this.timelineEvents.push({ event: 'founder-message-first-visible', atMs, episodeId: beat.id, block: blockIndex, visibleText: actual });
      }
      if (detail.index !== detail.total) return;
      const visible = inspectVisibleNode(node, 'copy');
      const pass = actual === beat.text.replace(/\s+/g, ' ').trim() && visible.pass;
      const record = { id: beat.id, expected: beat.text, actual, target: beat.target, block: blockIndex, wordCount: wordCount(actual), firstVisibleAtMs: this.founderBlockVisibleAt?.[blockIndex] ?? null, fullyReadableAtMs: atMs, readableMs: 0, requiredMs: estimateReadMs({ kind: 'message', expectedText: beat.text }, this.speed), presentation: 'typewriter', visibility: visible, pass };
      window.__rc34NarrativeDiagnostics?.visibleText.push(record);
      window.__rc34NarrativeDiagnostics?.attentionStates.push(record);
      this.timelineEvents.push({ event: 'founder-message-complete', atMs, episodeId: beat.id, block: blockIndex, wordCount: record.wordCount, pass, actualText: actual, opacity: visible.opacity, visibleFraction: visible.visibleFraction });
      if (blockIndex < 3) this.beginFounderBlockRead(beat, record, blockIndex);
    }

    beginFounderBlockRead(beat, record, blockIndex) {
      const requiredMs = estimateReadMs({ kind: 'message', expectedText: beat.text }, this.speed);
      const remainingMs = Math.max(0, requiredMs - record.readableMs);
      if (!remainingMs) return;
      this.founderReadBlockIndex = blockIndex;
      this.founderReadRecord = record;
      this.readableState = { episodeId: 'founder-story', startedAt: performance.now(), accumulatedMs: record.readableMs || 0, requiredMs, exactText: record.actual, expectedText: record.expected, textRecord: record };
      window.BooStudyFounderReveal?.pause?.();
      this.timelineEvents.push({ event: 'founder-block-read-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: beat.id, block: blockIndex, requiredReadableMs: Math.round(requiredMs), alreadyReadableMs: Math.round(record.readableMs), durationMs: Math.round(remainingMs + 150) });
      this.startTimedPhase('read', remainingMs + 150, this.generation);
    }

    beginFounderFinalRead(token) {
      if (token !== this.generation || !this.isPlaying()) return;
      const visibleText = window.__rc34NarrativeDiagnostics?.visibleText || [];
      const records = [...(this.founderStaticTextRecords || []), ...visibleText.filter((record) => record.presentation === 'typewriter')];
      const now = performance.now();
      const elapsedFor = (record) => {
        if (record.presentation === 'typewriter' && record.id === 'founder-cta' && !record.readableMs) {
          const beat = TOUR_MANIFEST[this.currentIndex]?.subbeats?.find((item) => item.id === record.id);
          const node = Number.isInteger(beat?.block) ? [...document.querySelectorAll('[data-typewriter]')][beat.block] : null;
          if (inspectVisibleNode(node, 'copy').pass) return Math.max(0, now - this.startedAt - (record.fullyReadableAtMs || 0));
        }
        return Math.max(0, Number(record.readableMs) || 0);
      };
      const remainingByRecord = records.map((record) => ({
        id: record.id,
        requiredMs: estimateReadMs({ kind: 'message', expectedText: record.expected }, this.speed),
        elapsedMs: elapsedFor(record)
      }));
      const remainingMs = Math.max(0, ...remainingByRecord.map((item) => item.requiredMs - item.elapsedMs));
      const ctaRecord = visibleText.find((record) => record.id === 'founder-cta' && record.presentation === 'typewriter');
      if (!ctaRecord) {
        this.stopOnVisualFailure({ expectedObject: 'авторское приглашение', copy: { reason: 'typewriter-cta-completion-not-recorded' } });
        return;
      }
      if (remainingMs <= 0) {
        this.complete();
        return;
      }
      const requiredMs = estimateReadMs({ kind: 'message', expectedText: ctaRecord.expected }, this.speed);
      const accumulatedMs = elapsedFor(ctaRecord);
      const playbackMs = remainingMs + 150;
      this.phase = 'read';
      this.phaseProgress = 0;
      this.founderReadBlockIndex = 3;
      this.founderReadRecord = ctaRecord;
      this.readableState = {
        episodeId: 'founder-story',
        startedAt: now,
        accumulatedMs,
        requiredMs,
        exactText: ctaRecord.actual,
        expectedText: ctaRecord.expected,
        textRecord: ctaRecord
      };
      this.timelineEvents.push({
        event: 'founder-final-read-start',
        atMs: Math.round(now - this.startedAt),
        episodeId: 'founder-story',
        durationMs: Math.round(playbackMs),
        requiredReadableMs: Math.round(requiredMs),
        readableAlreadyMs: Math.round(accumulatedMs),
        remainingByRecord
      });
      this.startTimedPhase('read', playbackMs, token);
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
        const demonstrationTarget = episode.demonstrateTo ? targetFor({ ...episode, progress: episode.demonstrateTo }) : target;
        const previousEpisode = TOUR_MANIFEST[index - 1];
        const phases = {
          move: travelMs(cursor, target, this.speed, episode, previousEpisode),
          founder: episode.chapter === 'founder'
            ? (window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || 45000 / this.speed)
            : 0,
          founderRead: estimateFounderFinalReadMs(episode, this.speed),
          read: estimateReadMs(episode, this.speed) + 150,
          demonstrate: episode.demonstrateTo ? travelMs(target, demonstrationTarget, this.speed, { ...episode, camera: episode.demonstrateCamera || episode.camera }, episode) : 0
        };
        cursor = demonstrationTarget;
        return { target, phases, total: Object.values(phases).reduce((sum, value) => sum + value, 0) };
      });
    }

    startAuto() {
      this.cancelPhase();
      this.startedAt = performance.now();
      this.timelineEvents = [];
      window.__rc34NarrativeDiagnostics = { version: 'RC3.4', startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, visibleText: [], attentionStates: [], checkpointCount: keyframeCount, attentionStateCount: NARRATIVE.attentionStateCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, kind, expectedText, progress, demonstrateTo }) => ({ id, chapter, label, kind, expectedText, progress, demonstrateTo })) };
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
      this.founderStaticReadGatePending = false;
      if (this.rafId) cancelAnimationFrame(this.rafId);
      if (this.timerId) clearTimeout(this.timerId);
      if (this.visibilityTimerId) clearInterval(this.visibilityTimerId);
      this.stopFounderStaticVisibilityTracking();
      this.rafId = 0;
      this.timerId = 0;
      this.visibilityTimerId = 0;
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
      this.moveKind = 'travel';
      this.motionTangents = {
        start: 0,
        end: 0
      };
      this.phaseRemaining = travelMs(this.phaseFromY, this.phaseToY, this.speed, episode, previousEpisode);
      this.phaseDuration = this.phaseRemaining;
      this.phaseStartProgress = 0;
      this.timelineEvents ||= [];
      this.timelineEvents.push({ event: 'segment-start', atMs: Math.round(performance.now() - (this.startedAt || performance.now())), episodeId: episode.id, checkpointKind: episode.kind, fromY: Math.round(this.phaseFromY), targetY: Math.round(this.phaseToY), camera: episode.camera?.mode });
      window.__rc34NarrativeDiagnostics && (window.__rc34NarrativeDiagnostics.events = this.timelineEvents);
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
      this.lastMotionSample = { at: this.phaseStartedAt, y: from, episodeId: TOUR_MANIFEST[this.currentIndex]?.id, reported: false };
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
      if (this.moveKind === 'demonstrate') {
        this.moveKind = 'travel';
        const report = inspectEpisode(episode);
        const actionPass = report.pass && (!episode.demonstrateCheck || (report.copy?.productCheck?.pass && report.copy?.productCheck?.actual.includes(episode.demonstrateCheck)));
        const event = { event: 'demonstration-complete', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, progress: episode.demonstrateTo, scrollY: Math.round(window.scrollY), action: episode.action || 'scroll-driven-state', state: report.copy?.state, product: report.copy?.productCheck, pass: actionPass };
        this.timelineEvents.push(event);
        this.visualDiagnostics.push({ ...report, phase: 'demonstrate', pass: actionPass });
        if (!actionPass) {
          this.stopOnVisualFailure({ ...report, expectedObject: `демонстрацию «${episode.label}»`, copy: { ...report.copy, reason: 'demonstration-milestone-not-confirmed' } });
          return;
        }
        if (remainPaused || this.state === 'auto-paused') {
          this.phase = 'read';
          this.phaseRemaining = 0;
          this.setState('auto-paused', 'Пауза · результат демонстрации сохранён');
          return;
        }
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
        return;
      }
      this.phase = 'verify';
      this.phaseProgress = 0;
      this.updatePanel();
      let reveal = null;
      if (episode.kind === 'founder') {
        reveal = window.BooStudyFounderReveal?.start?.();
        await Promise.all([nextRenderFrame(), window.BooStudyFounderReveal?.waitForTitle?.() || Promise.resolve()]);
        await nextRenderFrame();
        if (token !== this.generation) return;
      }
      const report = await this.verifyEpisode(episode, token);
      if (token !== this.generation) return;
      if (!report?.pass) {
        this.stopOnVisualFailure(report);
        return;
      }
      if (episode.kind === 'founder') {
        const heading = inspectVisibleNode(document.querySelector('#s42-founder-title'), 'copy');
        const proofNode = document.querySelector('.s42-founder-lead');
        const proof = inspectVisibleNode(proofNode, 'copy');
        const staticStates = episode.subbeats.slice(0, 2).map((beat) => {
          const node = document.querySelector(beat.target);
          const actual = (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
          const visibility = inspectVisibleNode(node, 'copy');
          return { id: beat.id, expected: beat.text, actual, target: beat.target, wordCount: wordCount(actual), firstVisibleAtMs: Math.round(performance.now() - this.startedAt), fullyReadableAtMs: Math.round(performance.now() - this.startedAt), readableMs: 0, visibility, pass: actual === beat.text && visibility.pass };
        });
        const founderStartReport = { ...report, phase: 'founder-start', heading, proof, pass: report.pass && heading.pass && proof.pass && staticStates.every((state) => state.pass) };
        this.visualDiagnostics.push(founderStartReport);
        if (!founderStartReport.pass) {
          this.stopOnVisualFailure(founderStartReport);
          return;
        }
        this.visualReports[this.visualReports.length - 1] = founderStartReport;
        this.lastVisualReport = founderStartReport;
        window.__rc34NarrativeDiagnostics?.visibleText.push(...staticStates);
        window.__rc34NarrativeDiagnostics?.attentionStates.push(...staticStates);
        this.founderStaticTextRecords = staticStates;
        this.readableState = null;
        this.phase = 'founder';
        this.phaseProgress = 0;
        this.phaseDuration = window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || episode.founderRevealMs / this.speed;
        this.phaseRemaining = this.phaseDuration;
        this.phaseStartedAt = performance.now();
        this.timelineEvents.push({ event: 'founder-typewriter-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
        this.updatePanel();
        if (this.isPlaying()) {
          this.trackFounderProgress(token);
          this.startFounderStaticVisibilityTracking();
        }
        if (remainPaused || this.state === 'auto-paused') {
          window.BooStudyFounderReveal?.pause?.();
          this.setState('auto-paused', 'Пауза · авторская сцена выбрана');
        }
        Promise.resolve(reveal).then(() => {
          if (token !== this.generation) return;
          this.timelineEvents.push({ event: 'founder-typewriter-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, scrollY: Math.round(window.scrollY) });
          this.beginFounderFinalRead(token);
        });
        return;
      }
      this.phase = 'read';
      this.phaseProgress = 0;
      const readMs = this.readDurationFor(episode);
      const playbackMs = readMs + 150;
      this.readableState = { episodeId: episode.id, startedAt: performance.now(), accumulatedMs: 0, requiredMs: readMs, exactText: report.copy.actualText, expectedText: report.copy.expectedText, textRecord: report.textTimeline };
      this.timelineEvents.push({ event: 'read-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, words: report.copy.wordCount, exactText: report.copy.actualText, durationMs: Math.round(playbackMs), requiredReadableMs: Math.round(readMs), fullyVisible: true, scrollY: Math.round(window.scrollY) });
      if (remainPaused || this.state === 'auto-paused') {
        this.phaseRemaining = playbackMs;
        this.phaseDuration = playbackMs;
        this.setState('auto-paused', 'Пауза · текст сохранён');
        this.updatePanel();
      } else this.startTimedPhase('read', playbackMs, token);
    }

    beginDemonstration(episode, token) {
      if (!episode.demonstrateTo) {
        if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
        return;
      }
      const destination = targetFor({ ...episode, progress: episode.demonstrateTo });
      this.phase = 'move';
      this.moveKind = 'demonstrate';
      this.phaseFromY = window.scrollY;
      this.phaseToY = destination;
      this.phaseRemaining = travelMs(this.phaseFromY, destination, this.speed, { ...episode, camera: episode.demonstrateCamera || episode.camera }, episode);
      this.phaseDuration = this.phaseRemaining;
      this.phaseStartedAt = performance.now();
      this.motionTangents = { start: 0, end: 0 };
      this.timelineEvents.push({ event: 'demonstration-start', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, action: episode.action || 'scroll-driven-state', fromY: Math.round(this.phaseFromY), targetY: Math.round(destination), targetProgress: episode.demonstrateTo, scrollY: Math.round(window.scrollY) });
      if (this.state === 'auto-paused') return;
      this.animateMove(token);
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
      if (name === 'read') {
        if (!this.readableState || this.readableState.episodeId !== TOUR_MANIFEST[this.currentIndex]?.id) {
          this.readableState = { episodeId: TOUR_MANIFEST[this.currentIndex]?.id, startedAt: this.phaseStartedAt, accumulatedMs: 0, requiredMs: duration, exactText: getEpisodeText(TOUR_MANIFEST[this.currentIndex]), expectedText: TOUR_MANIFEST[this.currentIndex]?.expectedText };
        }
        this.visibilityTimerId = window.setInterval(() => {
          if (!this.isPlaying() || this.phase !== 'read' || token !== this.generation) return;
          const episode = TOUR_MANIFEST[this.currentIndex];
          let report;
          if (episode.kind === 'founder' && this.founderReadRecord) {
            const beat = episode.subbeats.find((item) => item.id === this.founderReadRecord.id);
            const node = Number.isInteger(beat?.block) ? [...document.querySelectorAll('[data-typewriter]')][beat.block] : document.querySelector(beat?.target);
            const actual = node?.querySelector('.s42-typewriter-output')?.textContent?.replace(/\s+/g, ' ').trim()
              || (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
            const visibility = inspectVisibleNode(node, 'copy');
            report = { pass: visibility.pass && actual === this.founderReadRecord.expected, expectedObject: beat?.id, copy: { ...visibility, expectedText: this.founderReadRecord.expected, actualText: actual, reason: !visibility.pass ? visibility.reason : actual !== this.founderReadRecord.expected ? 'active-message-mismatch' : '' } };
          } else report = inspectEpisode(episode);
          if (!report.pass) this.stopOnVisualFailure({ ...report, expectedObject: 'читаемое сообщение', copy: { ...report.copy, reason: 'message-became-unreadable-during-reading' } });
        }, 100);
      }
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
      if (this.phase === 'read') {
        if (this.visibilityTimerId) clearInterval(this.visibilityTimerId);
        this.visibilityTimerId = 0;
        if (episode.kind === 'founder' && this.founderReadRecord) {
          const beat = episode.subbeats.find((item) => item.id === this.founderReadRecord.id);
          const requiredMs = estimateReadMs({ kind: 'message', expectedText: this.founderReadRecord.expected }, this.speed);
          const readableMs = Math.round(this.founderReadRecord.readableMs || 0);
          this.founderReadRecord.requiredMs = Math.round(requiredMs);
          this.founderReadRecord.pass = this.founderReadRecord.pass && readableMs >= requiredMs;
          this.timelineEvents.push({ event: 'founder-block-read-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: this.founderReadRecord.id, block: this.founderReadBlockIndex, readableMs, requiredMs: Math.round(requiredMs), coverage: this.founderReadRecord.pass });
          if (!this.founderReadRecord.pass) {
            this.stopOnVisualFailure({ expectedObject: `авторский текст «${beat?.id || 'Founder'}»`, copy: { reason: 'founder-message-readability-coverage-failed' } });
            return;
          }
          const completedBlock = this.founderReadBlockIndex;
          this.founderReadBlockIndex = -1;
          this.founderReadRecord = null;
          this.readableState = null;
          if (completedBlock === 3) {
            this.complete();
            return;
          }
          this.phase = 'founder';
          this.phaseProgress = 0;
          this.phaseStartedAt = performance.now();
          this.phaseDuration = window.BooStudyFounderReveal?.estimatedDuration?.(this.speed) || 0;
          this.phaseRemaining = this.phaseDuration;
          this.timelineEvents.push({ event: 'founder-typewriter-resume', atMs: Math.round(this.phaseStartedAt - this.startedAt), episodeId: 'founder-story', afterBlock: completedBlock });
          window.BooStudyFounderReveal?.resume?.();
          this.trackFounderProgress(token);
          this.updatePanel();
          return;
        }
        const activeReadMs = Math.max(0, performance.now() - this.phaseStartedAt);
        this.readableState ||= { accumulatedMs: 0, episodeId: episode.id, requiredMs: this.phaseDuration };
        this.readableState.accumulatedMs += activeReadMs;
        const readableMs = Math.round(this.readableState.accumulatedMs);
        const coverage = readableMs >= this.readableState.requiredMs;
        const textRecord = this.readableState.textRecord;
        if (textRecord) {
          Object.assign(textRecord, { readableMs, requiredMs: Math.round(this.readableState.requiredMs), pass: coverage });
          const states = window.__rc34NarrativeDiagnostics?.attentionStates;
          if (states && !states.includes(textRecord)) states.push(textRecord);
        }
        this.timelineEvents.push({ event: 'read-end', atMs: Math.round(performance.now() - this.startedAt), episodeId: episode.id, readableMs, requiredMs: Math.round(this.readableState.requiredMs), coverage, actualText: this.readableState.exactText, scrollY: Math.round(window.scrollY) });
        this.phase = 'read-complete';
        if (episode.demonstrateTo) this.beginDemonstration(episode, token);
        else if (this.currentIndex >= totalStops - 1) this.complete();
        else this.beginEpisode(this.currentIndex + 1);
      }
    }

    pause(message = '') {
      if (!this.isPlaying() || this.state === 'auto-paused' || this.state === 'auto-complete') return;
      if (this.phase === 'verify') this.generation += 1;
      if (['move', 'read'].includes(this.phase)) {
        const elapsed = performance.now() - this.phaseStartedAt;
        this.phaseRemaining = Math.max(0, this.phaseDuration - elapsed);
        if (this.phase === 'read' && this.readableState) this.readableState.accumulatedMs += Math.max(0, elapsed);
      } else if (this.phase === 'founder') {
        this.phaseRemaining = Math.max(0, this.phaseDuration - (performance.now() - this.phaseStartedAt));
      }
      if (this.rafId) cancelAnimationFrame(this.rafId);
      if (this.timerId) clearTimeout(this.timerId);
      if (this.visibilityTimerId) clearInterval(this.visibilityTimerId);
      this.rafId = 0;
      this.timerId = 0;
      this.visibilityTimerId = 0;
      this.stopFounderStaticVisibilityTracking();
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
      const waitingOnFounderCopy = this.phase === 'read' && this.founderReadBlockIndex >= 0;
      if (!waitingOnFounderCopy && !(this.phase === 'founder' && this.founderStaticReadGatePending) && this.phase !== 'founder') window.BooStudyFounderReveal?.resume?.();
      this.setState(this.activeState(), '');
      const token = this.generation;
      if (this.phase === 'founder') {
        if (window.BooStudyFounderReveal?.complete) {
          this.complete();
        } else {
          if (!this.founderStaticReadGatePending) window.BooStudyFounderReveal?.resume?.();
          this.startFounderStaticVisibilityTracking();
          this.trackFounderProgress(token);
          this.updatePanel();
        }
        return;
      }
      if (this.phase === 'verify') {
        this.afterMove(token, false);
        return;
      }
      if (TOUR_MANIFEST[this.currentIndex]?.kind === 'founder') this.startFounderStaticVisibilityTracking();
      if (this.phase === 'move') this.animateMove(token);
      else if (this.phase === 'read') this.startTimedPhase('read', this.phaseRemaining, token);
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
      } else if (['move', 'read'].includes(this.phase) && this.phaseRemaining > 0) {
        const elapsed = this.isPlaying() ? performance.now() - this.phaseStartedAt : 0;
        this.phaseRemaining = Math.max(0, this.phaseRemaining - elapsed) * ratio;
        if (this.phase === 'read' && this.readableState && this.isPlaying()) this.readableState.accumulatedMs += Math.max(0, elapsed);
        if (this.phase === 'read' && this.readableState) {
          const remainingReadableMs = Math.max(0, this.readableState.requiredMs - this.readableState.accumulatedMs);
          this.readableState.requiredMs = this.readableState.accumulatedMs + remainingReadableMs * ratio;
        }
        if (this.rafId) cancelAnimationFrame(this.rafId);
        if (this.timerId) clearTimeout(this.timerId);
        if (this.visibilityTimerId) clearInterval(this.visibilityTimerId);
        this.rafId = 0;
        this.timerId = 0;
        this.visibilityTimerId = 0;
      }
      this.speed = speed;
      if (this.phase === 'read' && this.founderReadRecord) {
        const requiredMs = estimateReadMs({ kind: 'message', expectedText: this.founderReadRecord.expected }, speed);
        const elapsedReadableMs = Math.max(0, this.founderReadRecord.readableMs || 0);
        this.phaseRemaining = Math.max(0, requiredMs - elapsedReadableMs) + 150;
        this.phaseDuration = this.phaseRemaining;
        this.phaseStartedAt = performance.now();
        if (this.readableState) {
          this.readableState.requiredMs = requiredMs;
          this.readableState.accumulatedMs = elapsedReadableMs;
        }
      }
      this.syncSpeedPresentation();
      this.rebuildDurationModel(this.routeStartY);
      if (this.phase === 'founder' || this.founderReadBlockIndex >= 0) window.BooStudyFounderReveal?.setSpeed?.(speed);
      if (this.isPlaying() && ['move', 'read'].includes(this.phase)) {
        if (this.phase === 'move') {
          const episode = TOUR_MANIFEST[this.currentIndex];
          this.phaseToY = this.moveKind === 'demonstrate' ? targetFor({ ...episode, progress: episode.demonstrateTo }) : targetFor(episode);
          this.animateMove(this.generation);
        } else this.startTimedPhase('read', this.phaseRemaining, this.generation);
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
      window.__rc34NarrativeDiagnostics = { version: 'RC3.4', startedAt: new Date().toISOString(), startedPerformanceMs: this.startedAt, events: this.timelineEvents, visibleText: [], attentionStates: [], checkpointCount: keyframeCount, attentionStateCount: NARRATIVE.attentionStateCount, manifest: TOUR_MANIFEST.map(({ id, chapter, label, kind, expectedText, progress, demonstrateTo }) => ({ id, chapter, label, kind, expectedText, progress, demonstrateTo })) };
      this.currentIndex = 0;
      this.routeStartY = 0;
      this.beginEpisode(0, { starting: true });
    }

    complete() {
      if (!this.lastVisualReport?.pass || this.lastVisualReport.episodeId !== TOUR_MANIFEST.at(-1).id) {
        this.stopOnVisualFailure(this.lastVisualReport || { expectedObject: 'финальную сцену', surface: { reason: 'нет подтверждения видимости' } });
        return;
      }
      const completedAtMs = Math.round(performance.now() - this.startedAt);
      [...(this.founderStaticTextRecords || []), ...(window.__rc34NarrativeDiagnostics?.visibleText || []).filter((record) => record.presentation === 'typewriter')].forEach((record) => {
        const readableMs = Math.max(0, Math.round(record.readableMs || 0));
        const requiredMs = estimateReadMs({ kind: 'message', expectedText: record.expected }, this.speed);
        record.readableMs = readableMs;
        record.requiredMs = Math.round(requiredMs);
        record.pass = record.pass && readableMs >= requiredMs;
      });
      const visibleText = window.__rc34NarrativeDiagnostics?.visibleText || [];
      const uniqueVisibleIds = new Set(visibleText.map((record) => record.id));
      const attentionCoverage = { expected: NARRATIVE.attentionStateCount, observed: uniqueVisibleIds.size, passed: visibleText.filter((record) => record.pass).length, missing: TOUR_MANIFEST.flatMap((beat) => beat.subbeats?.map((item) => item.id) || [beat.id]).filter((id) => !uniqueVisibleIds.has(id)), pass: uniqueVisibleIds.size === NARRATIVE.attentionStateCount && visibleText.every((record) => record.pass) };
      this.timelineEvents.push({ event: 'tour-complete', atMs: completedAtMs, episodeId: TOUR_MANIFEST.at(-1).id, scrollY: Math.round(window.scrollY), attentionCoverage });
      window.__rc34NarrativeDiagnostics.durationMs = completedAtMs;
      window.__rc34NarrativeDiagnostics.attentionCoverage = attentionCoverage;
      this.cancelPhase();
      window.BooStudyFounderReveal?.finish?.();
      this.phase = 'complete';
      this.currentIndex = totalStops - 1;
      this.setState('auto-complete', 'Экскурсия завершена');
      this.setPanelVisible(true);
      this.panelNodes.complete.hidden = false;
      this.panelNodes.complete.textContent = 'Спасибо за знакомство. Можно повторить экскурсию или продолжить изучение вручную.';
      this.updatePanel(true);
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
        const episode = TOUR_MANIFEST[this.currentIndex];
        this.phaseToY = this.moveKind === 'demonstrate' ? targetFor({ ...episode, progress: episode.demonstrateTo }) : targetFor(episode);
        if (this.isPlaying()) this.animateMove(this.generation);
      }
      this.updatePanel();
    }

    episodeTimeline() {
      const episode = this.durationByEpisode[this.currentIndex] || { phases: { move: 0, read: 0, demonstrate: 0, founder: 0 }, total: 1 };
      const phaseOrder = ['move', 'read', 'demonstrate', 'founder'];
      const completedPrior = this.durationByEpisode.slice(0, this.currentIndex).reduce((sum, item) => sum + item.total, 0);
      const timelinePhase = this.phase === 'move' && this.moveKind === 'demonstrate' ? 'demonstrate' : this.phase;
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
      const phaseOrder = ['move', 'read', 'demonstrate', 'founder'];
      const timelinePhase = this.phase === 'move' && this.moveKind === 'demonstrate' ? 'demonstrate' : this.phase;
      const phaseIndex = phaseOrder.indexOf(timelinePhase);
      const currentRemaining = phaseIndex < 0 ? current.total : Math.max(0, this.phaseRemaining) + phaseOrder.slice(phaseIndex + 1).reduce((sum, key) => sum + current.phases[key], 0);
      return currentRemaining + this.durationByEpisode.slice(this.currentIndex + 1).reduce((sum, item) => sum + item.total, 0);
    }

    phaseLabel() {
      if (this.phase === 'move') return this.moveKind === 'demonstrate' ? 'DEMONSTRATE · показываем действие продукта' : 'ORIENT · движение к смысловой сцене';
      if (this.phase === 'verify') return 'Проверяем видимость сцены';
      if (this.phase === 'visual-error') return 'Сцена не подтверждена · экскурсия остановлена';
      if (this.phase === 'read') return 'COMMUNICATE · читаем сообщение';
      if (this.phase === 'read-complete') return 'RESOLVE · сообщение воспринято';
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
    waitForFounderStaticReading: () => tour.waitForFounderStaticReading(),
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
