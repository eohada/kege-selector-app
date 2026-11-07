(() => {
  const chapters = [
    ['s30', '[data-s30-story]'],
    ['s32', '[data-s32-story]'],
    ['s36', '[data-s36-story]'],
    ['s37', '[data-s37-story]']
  ].map(([key, selector]) => ({ key, node: document.querySelector(selector), top: 0, range: 1 }));
  let frame = 0;

  function measure() {
    chapters.forEach((chapter) => {
      if (!chapter.node) return;
      chapter.top = chapter.node.getBoundingClientRect().top + window.scrollY;
      chapter.range = Math.max(1, chapter.node.offsetHeight - window.innerHeight);
    });
  }

  function publish() {
    frame = 0;
    const y = window.scrollY;
    const progress = {};
    chapters.forEach((chapter) => {
      if (chapter.node) progress[chapter.key] = Math.min(1, Math.max(0, (y - chapter.top) / chapter.range));
    });
    document.dispatchEvent(new CustomEvent('boostudy:story-progress', { detail: progress }));
  }

  function schedule() {
    if (frame) return;
    frame = window.requestAnimationFrame(publish);
  }

  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', () => { measure(); schedule(); }, { passive: true });
  measure();
  schedule();
})();
