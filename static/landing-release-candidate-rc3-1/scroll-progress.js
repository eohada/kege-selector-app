(() => {
  const chapters = [
    ['s30', '[data-s30-story]'],
    ['s32', '[data-s32-story]'],
    ['s36', '[data-s36-story]'],
    ['s37', '[data-s37-story]'],
    ['s38homework', '[data-s38-homework]'],
    ['s39theory', '[data-s39-theory]'],
    ['s39profile', '[data-s39-profile]'],
  ].map(([key, selector]) => ({ key, node: document.querySelector(selector), top: 0, range: 1, lastProgress: null, visible: false }));
  let frame = 0;
  let activeChapter = null;
  let resizeAnchor = null;

  function measure() {
    chapters.forEach((chapter) => {
      if (!chapter.node) return;
      chapter.visible = chapter.node.getClientRects().length > 0;
      if (!chapter.visible) {
        chapter.lastProgress = null;
        return;
      }
      const top = chapter.node.getBoundingClientRect().top + window.scrollY;
      const tourRange = Number(chapter.node.dataset.rc3TourProgressRange);
      const calibratedRange = Number(chapter.node.dataset.s40ProgressRange);
      const range = Number.isFinite(tourRange) && tourRange > 0
        ? tourRange
        : Number.isFinite(calibratedRange) && calibratedRange > 0
          ? calibratedRange
        : Math.max(1, chapter.node.offsetHeight - window.innerHeight);
      if (Math.abs(top - chapter.top) > 0.5 || Math.abs(range - chapter.range) > 0.5) chapter.lastProgress = null;
      chapter.top = top;
      chapter.range = range;
    });
  }

  function publish() {
    frame = 0;
    const y = window.scrollY;
    activeChapter = chapters.find((chapter) => chapter.visible && y >= chapter.top && y < chapter.top + chapter.range) || activeChapter;
    const progress = {};
    chapters.forEach((chapter) => {
      if (!chapter.visible || !chapter.node || (chapter.lastProgress === 1 && y >= chapter.top + chapter.range)) return;
      const value = Math.min(1, Math.max(0, (y - chapter.top) / chapter.range));
      if (value === 0 && y < chapter.top) {
        if (chapter.lastProgress !== null && chapter.lastProgress !== 0) {
          progress[chapter.key] = 0;
          chapter.lastProgress = 0;
        }
        return;
      }
      if (chapter.lastProgress === null || Math.abs(value - chapter.lastProgress) > 0.001) {
        progress[chapter.key] = value;
        chapter.lastProgress = value;
      }
    });
    if (Object.keys(progress).length) {
      document.dispatchEvent(new CustomEvent('boostudy:story-progress', { detail: progress }));
    }
    resizeAnchor = null;
  }

  function schedule() {
    if (frame) return;
    frame = window.requestAnimationFrame(publish);
  }

  function preserveChapterProgress() {
    const chapter = resizeAnchor?.chapter || activeChapter;
    const progress = resizeAnchor?.progress ?? chapter?.lastProgress;
    resizeAnchor = chapter && progress !== null && progress > 0 && progress < 1
      ? { chapter, progress }
      : null;
    measure();
    if (resizeAnchor) {
      const nextY = resizeAnchor.chapter.top + resizeAnchor.progress * resizeAnchor.chapter.range;
      window.scrollTo({ top: nextY, behavior: 'instant' });
    }
    schedule();
  }

  window.addEventListener('scroll', schedule, { passive: true });
  document.addEventListener('boostudy:story-range-change', () => {
    measure();
    schedule();
  });
  window.addEventListener('resize', preserveChapterProgress, { passive: true });
  window.addEventListener('load', () => { measure(); schedule(); }, { once: true });
  document.fonts?.ready.then(() => { measure(); schedule(); });
  if ('ResizeObserver' in window) {
    const layoutObserver = new ResizeObserver(() => { measure(); schedule(); });
    if (document.body) layoutObserver.observe(document.body);
    chapters.forEach((chapter) => { if (chapter.node) layoutObserver.observe(chapter.node); });
  }
  measure();
  schedule();
})();
