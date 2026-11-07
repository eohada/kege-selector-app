(() => {
  const story = document.querySelector('[data-s29-story]');
  const stage = document.querySelector('[data-s29-stage]');
  if (!story || !stage) return;

  const copies = [...document.querySelectorAll('[data-s29-copy]')];
  const progressLabel = document.querySelector('[data-s29-progress-label]');
  const progressBar = document.querySelector('[data-s29-progress-bar]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const scenes = ['intro', 'room', 'board', 'tool', 'return'];
  const stops = [.17, .39, .61, .82];
  let currentScene = '';
  let scheduled = false;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function updateScene() {
    const storyTop = story.getBoundingClientRect().top + window.scrollY;
    const scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
    const progress = clamp((window.scrollY - storyTop) / scrollRange, 0, 1);
    const stopIndex = stops.findIndex((stop) => progress < stop);
    const index = stopIndex === -1 ? scenes.length - 1 : stopIndex;
    const scene = scenes[index];

    if (scene !== currentScene) {
      currentScene = scene;
      stage.dataset.scene = scene;
      copies.forEach((copy) => {
        copy.setAttribute('aria-hidden', String(copy.dataset.s29Copy !== scene));
      });
      if (progressLabel) progressLabel.innerHTML = `0${index + 1} <i>/ 05</i>`;
      stage.setAttribute('aria-label', `Комната ученика BooStudy OS: этап ${index + 1} из 5`);
    }

    stage.style.setProperty('--s29-progress', String(progress));
    if (progressBar) progressBar.style.width = `${Math.round((index + 1) / scenes.length * 100)}%`;
    scheduled = false;
  }

  function scheduleUpdate() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateScene);
  }

  document.querySelectorAll('[data-s29-goto]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const targetName = link.dataset.s29Goto;
      const target = document.querySelector(`[data-s29-step="${targetName}"]`);
      if (!target) return;
      event.preventDefault();
      history.replaceState(null, '', `#${target.id}`);
      target.scrollIntoView({ behavior: reduceMotion.matches ? 'instant' : 'smooth', block: 'start' });
    });
  });

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
  reduceMotion.addEventListener?.('change', scheduleUpdate);
  updateScene();
})();
