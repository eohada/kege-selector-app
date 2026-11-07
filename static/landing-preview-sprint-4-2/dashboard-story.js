(() => {
  const story = document.querySelector('[data-s36-story]');
  if (!story) return;

  const surface = story.querySelector('[data-dashboard-surface]');
  const copyBlocks = [...story.querySelectorAll('[data-copy-block]')];
  const progressLabel = story.querySelector('[data-s36-progress-label]');
  const progressBar = story.querySelector('[data-s36-progress-bar]');
  const cta = story.querySelector('[data-s36-cta]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));

  const scenes = [
    { key: 'intro', start: 0, end: .12, focus: 'intro', side: 'right', label: 'Личное пространство' },
    { key: 'continue', start: .12, end: .27, focus: 'continue', side: 'right', label: 'Продолжить обучение' },
    { key: 'schedule', start: .27, end: .40, focus: 'schedule', side: 'left', label: 'Ближайшие занятия' },
    { key: 'curriculum', start: .40, end: .53, focus: 'curriculum', side: 'left', label: 'Программа подготовки' },
    { key: 'materials', start: .53, end: .68, focus: 'materials', side: 'left', label: 'Материалы и подготовка' },
    { key: 'progress', start: .68, end: .82, focus: 'progress', side: 'right', label: 'Краткая картина прогресса' },
    { key: 'complete', start: .82, end: 1, focus: 'overview', side: 'dominant', label: 'Твой центр обучения' }
  ];

  let storyTop = 0;
  let scrollRange = 1;
  let lastProgress = 0;
  let lastWasInStory = false;
  let activeScene = null;
  let activeCopy = null;
  let activeState = null;
  let staticMode = null;
  let pendingCopyScene = null;
  let frameId = 0;

  function measureStory() {
    storyTop = story.getBoundingClientRect().top + window.scrollY;
    scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
  }

  function sceneAt(progress) {
    const scene = scenes.find((item) => progress < item.end) || scenes.at(-1);
    return { ...scene, local: clamp((progress - scene.start) / (scene.end - scene.start)) };
  }

  function attentionAt(local) {
    if (local < .2) return 'read';
    if (local < .6) return 'watch';
    if (local < .88) return 'understand';
    return 'move';
  }

  function copyStateAt(local) {
    if (local < .045) return 'entering';
    if (local < .6) return 'readable';
    if (local < .88) return 'secondary';
    return 'exiting';
  }

  function setStaticState(enabled) {
    if (staticMode === enabled) return;
    staticMode = enabled;
    story.toggleAttribute('data-s36-static', enabled);

    if (enabled) {
      story.dataset.scene = 'complete';
      story.dataset.attention = 'read';
      story.removeAttribute('data-s36-moving');
      surface.dataset.focus = 'overview';
      copyBlocks.forEach((block) => {
        block.hidden = false;
        block.setAttribute('aria-hidden', 'false');
        block.dataset.copyState = 'readable';
      });
      activeScene = 'complete';
      activeCopy = null;
      activeState = 'readable';
      pendingCopyScene = null;
      progressLabel.textContent = 'Твой центр обучения';
      progressBar.style.transform = 'scaleX(1)';
      cta.hidden = false;
    } else {
      activeScene = null;
      activeCopy = null;
      activeState = null;
    }
  }

  function activateScene(scene) {
    if (activeScene === scene.key) return;
    const sideChanged = story.dataset.s36Side !== scene.side;
    const copyPending = sideChanged || story.hasAttribute('data-s36-moving');
    activeScene = scene.key;
    activeCopy = copyBlocks.find((block) => block.dataset.copyBlock === scene.key) || null;
    activeState = 'entering';
    pendingCopyScene = copyPending ? scene.key : null;

    story.dataset.scene = scene.key;
    story.dataset.s36Side = scene.side;
    story.toggleAttribute('data-s36-moving', copyPending);
    surface.dataset.focus = scene.focus;
    progressLabel.textContent = scene.label;
    copyBlocks.forEach((block) => {
      const isActive = block === activeCopy;
      block.hidden = !isActive || copyPending;
      block.setAttribute('aria-hidden', String(!isActive || copyPending));
      block.dataset.copyState = isActive ? 'entering' : 'inactive';
    });
  }

  function revealPendingCopy(event) {
    if (event.target !== event.currentTarget || event.propertyName !== 'transform'
      || !pendingCopyScene || pendingCopyScene !== activeScene) return;
    if (story.dataset.s36Side !== scenes.find((scene) => scene.key === activeScene)?.side) return;
    if (activeCopy) {
      activeCopy.hidden = false;
      activeCopy.setAttribute('aria-hidden', 'false');
    }
    story.removeAttribute('data-s36-moving');
    pendingCopyScene = null;
  }

  function update(progressOverride = null) {
    const isStatic = reduceMotion.matches;
    setStaticState(isStatic);
    if (isStatic) return;

    const progress = progressOverride === null ? clamp((window.scrollY - storyTop) / scrollRange) : progressOverride;
    lastProgress = progress;
    lastWasInStory = window.scrollY >= storyTop && window.scrollY <= storyTop + scrollRange;
    const scene = sceneAt(progress);
    activateScene(scene);

    const attention = attentionAt(scene.local);
    if (story.dataset.attention !== attention) story.dataset.attention = attention;

    const copyState = copyStateAt(scene.local);
    if (activeCopy && activeState !== copyState) {
      activeState = copyState;
      activeCopy.dataset.copyState = copyState;
    }

    const progressScale = String(progress);
    if (progressBar.style.transform !== `scaleX(${progressScale})`) {
      progressBar.style.transform = `scaleX(${progressScale})`;
    }

    const showCta = scene.key === 'complete' && progress >= .955;
    if (cta.hidden === showCta) cta.hidden = !showCta;
  }

  function scheduleUpdate() {
    if (frameId) return;
    frameId = window.requestAnimationFrame(() => {
      frameId = 0;
      update();
    });
  }

  const resize = () => {
    const preserveStoryProgress = window.scrollY >= storyTop && window.scrollY <= storyTop + scrollRange;
    measureStory();
    lastWasInStory = preserveStoryProgress;
    if (preserveStoryProgress && !reduceMotion.matches) {
      window.scrollTo({ top: storyTop + scrollRange * lastProgress, behavior: 'instant' });
    }
    scheduleUpdate();
  };

  const checklistInputs = [...surface.querySelectorAll('.s35-checklist-items input[type="checkbox"]')];
  const checklistCount = surface.querySelector('[data-checklist-count]');
  const checklistBar = surface.querySelector('[data-checklist-bar]');
  const checklistCard = surface.querySelector('.s35-checklist-card');

  function updateChecklist() {
    const completed = checklistInputs.filter((input) => input.checked).length;
    checklistCount.textContent = `${completed} из ${checklistInputs.length} выполнено`;
    checklistBar.style.width = `${checklistInputs.length ? completed / checklistInputs.length * 100 : 0}%`;
    checklistCard.dataset.completed = String(completed);
  }

  checklistInputs.forEach((input) => input.addEventListener('change', updateChecklist));
  story.querySelector('.s35-product-frame').addEventListener('transitionend', revealPendingCopy);
  document.addEventListener('boostudy:story-progress', (event) => {
    if (typeof event.detail.s36 === 'number') update(event.detail.s36);
  });
  window.addEventListener('resize', resize);
  reduceMotion.addEventListener?.('change', scheduleUpdate);

  measureStory();
  updateChecklist();
  update();
})();
