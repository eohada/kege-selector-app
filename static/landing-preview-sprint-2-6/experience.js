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

  const toolTabs = [...document.querySelectorAll('[data-s26-tab]')];
  const toolPanels = [...document.querySelectorAll('[data-s26-panel]')];
  const toolState = document.querySelector('[data-s26-state-label]');
  const toolLabels = {
    create: 'Состояние: перо · цвет и толщина',
    shapes: 'Состояние: фигуры · линии и стрелки',
    edit: 'Состояние: выбран объект · открыты свойства',
    space: 'Состояние: страницы · панорамирование · масштаб'
  };

  function selectToolTab(tab, moveFocus = false) {
    const selectedName = tab.dataset.s26Tab;
    toolTabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    toolPanels.forEach((panel) => {
      panel.hidden = panel.dataset.s26Panel !== selectedName;
    });
    if (toolState) toolState.textContent = toolLabels[selectedName] || 'Подготовленное состояние инструмента';
    if (moveFocus) tab.focus();
  }

  toolTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectToolTab(tab));
    tab.addEventListener('keydown', (event) => {
      let nextIndex = index;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % toolTabs.length;
      else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + toolTabs.length) % toolTabs.length;
      else if (event.key === 'Home') nextIndex = 0;
      else if (event.key === 'End') nextIndex = toolTabs.length - 1;
      else return;
      event.preventDefault();
      selectToolTab(toolTabs[nextIndex], true);
    });
  });

  const revealSections = document.querySelectorAll('[data-s26-reveal]');
  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    revealSections.forEach((section) => revealObserver.observe(section));
  } else {
    revealSections.forEach((section) => section.classList.add('is-visible'));
  }

  updateScene();
})();
