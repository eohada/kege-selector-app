(() => {
  const story = document.querySelector('[data-s25-story]');
  const stage = document.querySelector('[data-s25-stage]');
  if (!story || !stage) return;

  const copies = [...document.querySelectorAll('[data-s25-copy]')];
  const progressLabel = document.querySelector('[data-s25-progress-label]');
  const progressBar = document.querySelector('[data-s25-progress-bar]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const sceneNames = ['hero', 'workspace', 'canvas'];
  let currentScene = '';
  let scheduled = false;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function updateScene() {
    const storyTop = story.getBoundingClientRect().top + window.scrollY;
    const scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
    const progress = clamp((window.scrollY - storyTop) / scrollRange, 0, 1);
    const index = progress < 0.34 ? 0 : progress < 0.68 ? 1 : 2;
    const scene = sceneNames[index];

    if (scene !== currentScene) {
      currentScene = scene;
      stage.dataset.scene = scene;
      copies.forEach((copy) => {
        copy.setAttribute('aria-hidden', String(copy.dataset.s25Copy !== scene));
      });
      if (progressLabel) progressLabel.innerHTML = `0${index + 1} <i>/ 03</i>`;
      stage.setAttribute('aria-label', `Знакомство с BooStudy OS: этап ${index + 1} из 3`);
    }

    stage.style.setProperty('--s25-progress', String(progress));
    if (progressBar) progressBar.style.width = `${Math.round((index + 1) / 3 * 100)}%`;
    scheduled = false;
  }

  function scheduleUpdate() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateScene);
  }

  document.querySelectorAll('[data-s25-goto]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const targetName = link.dataset.s25Goto;
      const target = document.querySelector(`[data-s25-step="${targetName}"]`);
      if (!target) return;
      event.preventDefault();
      history.replaceState(null, '', `#${target.id}`);
      target.scrollIntoView({ behavior: reduceMotion.matches ? 'instant' : 'smooth', block: 'start' });
    });
  });

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate, { passive: true });
  reduceMotion.addEventListener?.('change', scheduleUpdate);
  updateScene();
})();
