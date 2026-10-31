(() => {
  const story = document.querySelector('[data-s25-story]');
  const stage = document.querySelector('[data-s25-stage]');
  if (!story || !stage) return;

  const copies = [...document.querySelectorAll('[data-s25-copy]')];
  const progressLabel = document.querySelector('[data-s25-progress-label]');
  const progressBar = document.querySelector('[data-s25-progress-bar]');
  const video = document.querySelector('[data-s25-canvas-video]');
  const videoState = document.querySelector('[data-s25-video-state]');
  const replayButton = document.querySelector('[data-s25-replay]');
  const fullscreenButton = document.querySelector('[data-s25-fullscreen]');
  const videoWindow = document.querySelector('[data-s25-window="canvas"]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let currentScene = '';
  let scheduled = false;
  let videoInView = false;
  let userPaused = false;
  let userStartedPlayback = false;
  let videoCompleted = false;
  let appPausePending = false;
  let appPlayPending = false;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  function setVideoState(message, kind = '') {
    if (!videoState) return;
    videoState.textContent = message;
    if (kind) videoState.dataset.kind = kind;
    else delete videoState.dataset.kind;
  }

  function refreshVideoState() {
    if (!video || video.error) {
      setVideoState('Запись не загрузилась. Финальный кадр доски доступен на постере.', 'error');
    } else if (videoCompleted || video.ended) {
      setVideoState('Запись преподавателя завершена · финальный кадр доски.');
    } else if (reduceMotion.matches && !userStartedPlayback) {
      setVideoState('Постер · нажмите Play, чтобы посмотреть запись.', 'reduced');
    } else if (!video.paused) {
      setVideoState('Запись BooCanvas Overlay · преподаватель · без звука');
    } else if (userPaused) {
      setVideoState('Запись на паузе · продолжите кнопкой Play');
    } else {
      setVideoState('Запись BooCanvas Overlay · преподаватель · без звука');
    }
  }

  function setScene(scene) {
    if (scene === currentScene) return;
    currentScene = scene;
    stage.dataset.scene = scene;
    copies.forEach((copy) => {
      copy.setAttribute('aria-hidden', String(copy.dataset.s25Copy !== scene));
    });

    const index = scene === 'hero' ? 0 : scene === 'workspace' ? 1 : 2;
    if (progressLabel) progressLabel.innerHTML = `0${index + 1} <i>/ 03</i>`;
    stage.setAttribute('aria-label', `Знакомство с BooStudy OS: этап ${index + 1} из 3`);
  }

  function syncPlayback() {
    if (!video) return;
    const sceneAllowsPlayback = currentScene === 'canvas';
    const pageIsVisible = document.visibilityState === 'visible';
    const motionAllowsPlayback = !reduceMotion.matches || userStartedPlayback;
    const shouldPlay = sceneAllowsPlayback && videoInView && pageIsVisible && motionAllowsPlayback && !userPaused && !videoCompleted;

    if (shouldPlay && video.paused && !video.error) {
      appPlayPending = true;
      video.play().catch(() => {
        appPlayPending = false;
        if (currentScene === 'canvas' && !videoCompleted && !userPaused) {
          setVideoState('Нажмите Play, чтобы начать запись.', 'reduced');
        }
      });
    } else if (!shouldPlay && !video.paused) {
      appPausePending = true;
      video.pause();
    }
    refreshVideoState();
  }

  function updateScene() {
    const storyTop = story.getBoundingClientRect().top + window.scrollY;
    const scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
    const progress = clamp((window.scrollY - storyTop) / scrollRange, 0, 1);
    const progressIndex = progress < 0.34 ? 0 : progress < 0.68 ? 1 : 2;
    const requestedScene = ['hero', 'workspace', 'canvas'][progressIndex];
    const scene = requestedScene === 'canvas' && videoCompleted ? 'return' : requestedScene;

    setScene(scene);
    stage.style.setProperty('--s25-progress', String(progress));
    if (progressBar) progressBar.style.width = `${Math.round((progressIndex + 1) / 3 * 100)}%`;
    scheduled = false;
    syncPlayback();
  }

  function scheduleUpdate() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateScene);
  }

  function playFromUserAction() {
    if (!video || video.error) return;
    videoCompleted = false;
    userPaused = false;
    userStartedPlayback = true;
    if (video.ended) video.currentTime = 0;
    setScene('canvas');
    appPlayPending = true;
    video.play().then(() => {
      appPlayPending = false;
      refreshVideoState();
    }).catch(() => {
      appPlayPending = false;
      if (currentScene === 'canvas' && !videoCompleted) {
        setVideoState('Нажмите Play на плеере, чтобы начать запись.', 'reduced');
      }
    });
    scheduleUpdate();
  }

  if (video) {
    video.muted = true;
    video.addEventListener('play', () => {
      if (!appPlayPending) {
        userPaused = false;
        userStartedPlayback = true;
        if (videoCompleted) {
          videoCompleted = false;
          setScene('canvas');
        }
      }
      refreshVideoState();
      scheduleUpdate();
    });
    video.addEventListener('pause', () => {
      if (appPausePending) appPausePending = false;
      else if (!video.ended) userPaused = true;
      refreshVideoState();
      syncPlayback();
    });
    video.addEventListener('ended', () => {
      videoCompleted = true;
      userPaused = false;
      setScene('return');
      refreshVideoState();
      scheduleUpdate();
    });
    video.addEventListener('error', refreshVideoState);
    video.addEventListener('loadedmetadata', refreshVideoState);
    video.addEventListener('playing', refreshVideoState);
  }

  if (videoWindow && 'IntersectionObserver' in window) {
    const videoObserver = new IntersectionObserver((entries) => {
      videoInView = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.2);
      syncPlayback();
    }, { threshold: [0, 0.2, 0.5] });
    videoObserver.observe(videoWindow);
  } else {
    videoInView = true;
  }

  replayButton?.addEventListener('click', playFromUserAction);
  fullscreenButton?.addEventListener('click', async () => {
    if (!video) return;
    try {
      if (video.requestFullscreen) await video.requestFullscreen();
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
      else setVideoState('Полноэкранный режим доступен через меню плеера.');
    } catch {
      setVideoState('Полноэкранный режим недоступен в этом браузере.');
    }
  });

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
  document.addEventListener('visibilitychange', syncPlayback);
  reduceMotion.addEventListener?.('change', syncPlayback);
  refreshVideoState();
  updateScene();
})();
