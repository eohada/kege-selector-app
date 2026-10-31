(() => {
  const story = document.querySelector('[data-scroll-story]');
  if (!story) return;

  const frame = story.querySelector('[data-sticky-frame]');
  const viewport = story.querySelector('[data-camera-viewport]');
  const workspace = story.querySelector('[data-workspace]');
  const hero = story.querySelector('[data-hero-copy]');
  const beats = [...story.querySelectorAll('[data-story-beat]')];
  const targets = Object.fromEntries(
    [...story.querySelectorAll('[data-camera-target]')].map((target) => [target.dataset.cameraTarget, target]),
  );
  const mascot = story.querySelector('[data-mascot]');
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const smooth = (value) => value * value * (3 - 2 * value);
  const lerp = (from, to, amount) => from + (to - from) * amount;
  const beatByName = new Map(beats.map((beat) => [beat.dataset.storyBeat, beat]));
  let cameraStops = [];
  let frameRequested = false;
  let lastProgress = 0;
  let activeNarrative = null;

  function elementBounds(element) {
    return {
      x: element.offsetLeft,
      y: element.offsetTop,
      width: element.offsetWidth,
      height: element.offsetHeight,
    };
  }

  function surfaceBounds(element) {
    const surface = element.querySelector('.rebirth-window__surface');
    if (!surface) return elementBounds(element);

    let x = 0;
    let y = 0;
    let current = surface;
    while (current && current !== workspace) {
      x += current.offsetLeft;
      y += current.offsetTop;
      current = current.offsetParent;
    }
    return { x, y, width: surface.offsetWidth, height: surface.offsetHeight };
  }

  function combineBounds(elements) {
    const rects = elements.map(elementBounds);
    const left = Math.min(...rects.map((rect) => rect.x));
    const top = Math.min(...rects.map((rect) => rect.y));
    const right = Math.max(...rects.map((rect) => rect.x + rect.width));
    const bottom = Math.max(...rects.map((rect) => rect.y + rect.height));
    return { x: left, y: top, width: right - left, height: bottom - top };
  }

  function poseFor(rect, scale, anchorX, anchorY, viewportWidth, viewportHeight) {
    return {
      x: viewportWidth * anchorX - (rect.x + rect.width / 2) * scale,
      y: viewportHeight * anchorY - (rect.y + rect.height / 2) * scale,
      scale,
    };
  }

  function fittedPose(rect, widthRatio, heightRatio, anchorX, anchorY, viewportWidth, viewportHeight) {
    const scale = Math.min(
      viewportWidth * widthRatio / Math.max(1, rect.width),
      viewportHeight * heightRatio / Math.max(1, rect.height),
    );
    return poseFor(rect, scale, anchorX, anchorY, viewportWidth, viewportHeight);
  }

  function rebuildCameraStops() {
    const viewportWidth = viewport.clientWidth;
    const viewportHeight = viewport.clientHeight;
    const overview = elementBounds(targets.overview);
    const cluster = combineBounds([targets.overview, targets.canvas, targets.python, mascot]);
    const isCompact = viewportWidth <= 1100;
    const startScale = Math.min(
      isCompact ? .65 : .68,
      viewportWidth * (isCompact ? .55 : .56) / overview.width,
      viewportHeight * (isCompact ? .23 : .72) / overview.height,
    );
    const start = poseFor(
      overview,
      startScale,
      isCompact ? .5 : .71,
      isCompact ? .77 : .56,
      viewportWidth,
      viewportHeight,
    );
    const overviewNear = fittedPose(
      overview,
      isCompact ? .92 : .87,
      isCompact ? .4 : .7,
      .5,
      isCompact ? .48 : .5,
      viewportWidth,
      viewportHeight,
    );
    const overviewClose = fittedPose(
      overview,
      isCompact ? .96 : .91,
      isCompact ? .44 : .74,
      .5,
      isCompact ? .47 : .5,
      viewportWidth,
      viewportHeight,
    );
    const overviewDrift = fittedPose(
      overview,
      isCompact ? .98 : .93,
      isCompact ? .46 : .76,
      .51,
      isCompact ? .48 : .51,
      viewportWidth,
      viewportHeight,
    );
    const wide = fittedPose(
      cluster,
      .91,
      isCompact ? .57 : .82,
      .5,
      .49,
      viewportWidth,
      viewportHeight,
    );
    const canvas = fittedPose(
      surfaceBounds(targets.canvas),
      isCompact ? .94 : .9,
      isCompact ? .62 : .82,
      isCompact ? .5 : .66,
      isCompact ? .42 : .55,
      viewportWidth,
      viewportHeight,
    );
    const canvasDrift = fittedPose(
      surfaceBounds(targets.canvas),
      isCompact ? .96 : .92,
      isCompact ? .65 : .85,
      isCompact ? .505 : .66,
      isCompact ? .43 : .54,
      viewportWidth,
      viewportHeight,
    );
    const python = fittedPose(
      surfaceBounds(targets.python),
      isCompact ? .94 : .9,
      isCompact ? .58 : .7,
      .5,
      isCompact ? .42 : .48,
      viewportWidth,
      viewportHeight,
    );
    const pythonDrift = fittedPose(
      surfaceBounds(targets.python),
      isCompact ? .96 : .92,
      isCompact ? .61 : .72,
      .505,
      isCompact ? .43 : .49,
      viewportWidth,
      viewportHeight,
    );
    const wideEnd = fittedPose(
      cluster,
      .93,
      isCompact ? .59 : .84,
      .505,
      .5,
      viewportWidth,
      viewportHeight,
    );

    cameraStops = [
      [0, start],
      [.1, overviewNear],
      [.19, overviewClose],
      [.3, overviewDrift],
      [.38, wide],
      [.52, canvas],
      [.62, canvasDrift],
      [.7, python],
      [.83, pythonDrift],
      [.92, wide],
      [1, wideEnd],
    ];
  }

  function cameraAt(progress) {
    let lower = cameraStops[0];
    let upper = cameraStops[cameraStops.length - 1];
    for (let index = 1; index < cameraStops.length; index += 1) {
      if (progress <= cameraStops[index][0]) {
        lower = cameraStops[index - 1];
        upper = cameraStops[index];
        break;
      }
    }

    const distance = upper[0] - lower[0] || 1;
    const amount = smooth(clamp((progress - lower[0]) / distance));
    return {
      x: lerp(lower[1].x, upper[1].x, amount),
      y: lerp(lower[1].y, upper[1].y, amount),
      scale: lerp(lower[1].scale, upper[1].scale, amount),
    };
  }

  function activeBeatFor(progress) {
    if (progress < .14) return null;
    if (progress < .5) return 'workspace';
    if (progress < .68) return 'canvas';
    if (progress < .92) return 'python';
    return 'ending';
  }

  function cameraFocusFor(progress) {
    if (progress < .37) return 'overview';
    if (progress < .53 || progress >= .92) return 'wide';
    if (progress < .68) return 'canvas';
    return 'python';
  }

  function updateNarrativeAccess(activeBeat) {
    const nextNarrative = activeBeat ? beatByName.get(activeBeat) : hero;
    if (nextNarrative === activeNarrative) return;

    if (activeNarrative?.contains(document.activeElement)) {
      const focusTarget = nextNarrative?.querySelector('h1, h2');
      focusTarget?.focus({ preventScroll: true });
    }

    hero.inert = nextNarrative !== hero;
    hero.setAttribute('aria-hidden', String(nextNarrative !== hero));
    beats.forEach((beat) => {
      const isActive = beat === nextNarrative;
      beat.inert = !isActive;
      beat.setAttribute('aria-hidden', String(!isActive));
    });
    const endingCta = story.querySelector('[data-ending-cta]');
    if (endingCta) endingCta.tabIndex = activeBeat === 'ending' ? 0 : -1;
    activeNarrative = nextNarrative;
  }

  function opacityForRange(progress, start, end, fade = .045) {
    return Math.min(
      smooth(clamp((progress - start) / fade)),
      smooth(clamp((end - progress) / fade)),
    );
  }

  function renderProgress() {
    frameRequested = false;
    if (!document.documentElement.hasAttribute('data-scroll-motion')) return;

    const range = Math.max(1, story.offsetHeight - frame.offsetHeight);
    const progress = clamp(-story.getBoundingClientRect().top / range);
    const camera = cameraAt(progress);
    lastProgress = progress;

    workspace.dataset.cameraFocus = cameraFocusFor(progress);
    workspace.style.setProperty('--camera-x', `${camera.x.toFixed(2)}px`);
    workspace.style.setProperty('--camera-y', `${camera.y.toFixed(2)}px`);
    workspace.style.setProperty('--camera-scale', camera.scale.toFixed(4));

    const heroOpacity = 1 - smooth(clamp((progress - .015) / .12));
    story.style.setProperty('--hero-opacity', heroOpacity.toFixed(3));
    story.style.setProperty('--hero-y', `${(-24 * progress).toFixed(1)}px`);
    story.style.setProperty('--cue-opacity', heroOpacity.toFixed(3));

    const beatRanges = {
      workspace: [.16, .34],
      canvas: [.51, .65],
      python: [.69, .86],
      ending: [.94, 1.04],
    };
    beats.forEach((beat) => {
      const [start, end] = beatRanges[beat.dataset.storyBeat];
      const opacity = opacityForRange(progress, start, end);
      beat.style.setProperty('--beat-opacity', opacity.toFixed(3));
      beat.style.setProperty('--beat-y', `${(12 * (1 - opacity)).toFixed(1)}px`);
    });

    updateNarrativeAccess(activeBeatFor(progress));
  }

  function scheduleRender() {
    if (frameRequested) return;
    frameRequested = true;
    window.requestAnimationFrame(renderProgress);
  }

  function scrollToProgress(progress) {
    const range = Math.max(1, story.offsetHeight - frame.offsetHeight);
    const storyTop = window.scrollY + story.getBoundingClientRect().top;
    window.scrollTo({
      top: storyTop + range * clamp(progress),
      behavior: motionPreference.matches ? 'auto' : 'smooth',
    });
  }

  function enableScrollMotion() {
    const canAnimate = !motionPreference.matches
      && window.CSS?.supports('position', 'sticky')
      && viewport.clientWidth >= 320;

    if (!canAnimate) {
      document.documentElement.removeAttribute('data-scroll-motion');
      workspace.removeAttribute('style');
      story.removeAttribute('style');
      hero.inert = false;
      hero.removeAttribute('aria-hidden');
      beats.forEach((beat) => {
        beat.inert = false;
        beat.removeAttribute('aria-hidden');
        beat.removeAttribute('style');
      });
      activeNarrative = null;
      scheduleRender();
      return;
    }

    const oldRange = Math.max(1, story.offsetHeight - frame.offsetHeight);
    const restoredProgress = story.offsetHeight > frame.offsetHeight
      ? clamp(-story.getBoundingClientRect().top / oldRange)
      : lastProgress;
    document.documentElement.setAttribute('data-scroll-motion', 'on');
    rebuildCameraStops();
    updateNarrativeAccess(activeBeatFor(restoredProgress));

    const storyTop = window.scrollY + story.getBoundingClientRect().top;
    const newRange = Math.max(1, story.offsetHeight - frame.offsetHeight);
    window.scrollTo({ top: storyTop + newRange * restoredProgress, behavior: 'instant' });
    lastProgress = restoredProgress;
    scheduleRender();
  }

  function preserveProgressOnResize() {
    const progress = lastProgress;
    enableScrollMotion();
    if (document.documentElement.hasAttribute('data-scroll-motion')) {
      const range = Math.max(1, story.offsetHeight - frame.offsetHeight);
      const storyTop = window.scrollY + story.getBoundingClientRect().top;
      window.scrollTo({ top: storyTop + range * progress, behavior: 'instant' });
      lastProgress = progress;
    }
    scheduleRender();
  }

  story.querySelectorAll('[data-scroll-to-product]').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (document.documentElement.hasAttribute('data-scroll-motion')) {
        event.preventDefault();
        scrollToProgress(.16);
      }
    });
  });

  window.addEventListener('scroll', scheduleRender, { passive: true });
  window.addEventListener('resize', preserveProgressOnResize, { passive: true });
  window.addEventListener('pageshow', scheduleRender);
  motionPreference.addEventListener?.('change', enableScrollMotion);

  enableScrollMotion();
})();
