(() => {
  const story = document.querySelector('[data-s23-story]');
  const stage = document.querySelector('[data-s23-stage]');
  const set = document.querySelector('[data-s23-set]');
  if (!story || !stage || !set) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const isSmall = window.matchMedia('(max-width: 700px)');
  const html = document.documentElement;
  const captures = {
    overview: document.querySelector('[data-s23-window="overview"]'),
    canvas: document.querySelector('[data-s23-window="canvas"]'),
    python: document.querySelector('[data-s23-window="python"]'),
  };
  const overviewImage = document.querySelector('[data-s23-screen-image]');
  const detailImages = {
    tracer: document.querySelector('[data-s23-detail="tracer"]'),
    task: document.querySelector('[data-s23-detail="task"]'),
  };
  const sharedFocus = document.querySelector('[data-s23-shared-focus]');
  const sharedImage = document.querySelector('[data-s23-shared-image]');
  const mascot = document.querySelector('[data-s23-mascot]');
  const narratives = [...document.querySelectorAll('[data-s23-narrative]')];
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const mix = (a, b, amount) => a + (b - a) * amount;
  const eases = {
    linear: (t) => t,
    soft: (t) => t * t * (3 - 2 * t),
    out: (t) => 1 - (1 - t) ** 3,
    inOut: (t) => t < 0.5 ? 4 * t ** 3 : 1 - ((-2 * t + 2) ** 3) / 2,
    expo: (t) => t === 1 ? 1 : 1 - 2 ** (-10 * t),
  };

  const tracks = {
    overview: [
      { at: 0, x: -1.2, y: 0, scale: 0.61, rx: 3, ry: -17, rz: -2, opacity: 1, ease: 'out' },
      { at: 0.1, x: -1.6, y: 0, scale: 0.64, rx: 2, ry: -14, rz: -1, opacity: 1, ease: 'inOut' },
      { at: 0.22, x: -8, y: 1, scale: 0.82, rx: 0, ry: -6, rz: 0, opacity: 1, ease: 'out' },
      { at: 0.31, x: -10, y: 1, scale: 0.9, rx: 0, ry: 0, rz: 0, opacity: 1, ease: 'soft' },
      { at: 0.41, x: -10, y: 0, scale: 0.86, rx: 0, ry: 0, rz: 0, opacity: 1, ease: 'inOut' },
      { at: 0.49, x: -12, y: 2, scale: 0.67, rx: 1, ry: 2, rz: 1, opacity: 0.72, ease: 'inOut' },
      { at: 0.55, x: -17, y: 3, scale: 0.54, rx: 2, ry: -8, rz: -2, opacity: 0.08, ease: 'soft' },
      { at: 0.7, x: -18, y: 2, scale: 0.5, rx: 1, ry: -9, rz: -1, opacity: 0.04, ease: 'inOut' },
      { at: 0.76, x: -21, y: 0, scale: 0.46, rx: 0, ry: -4, rz: 0, opacity: 0.02, ease: 'soft' },
      { at: 0.88, x: -19, y: 0, scale: 0.47, rx: 0, ry: -4, rz: 0, opacity: 0.04, ease: 'expo' },
      { at: 0.95, x: -4, y: -7, scale: 0.56, rx: 0, ry: -2, rz: 0, opacity: 1, ease: 'out' },
      { at: 1, x: -3, y: -7, scale: 0.56, rx: 0, ry: -2, rz: 0, opacity: 1 },
    ],
    overviewMobile: [
      { at: 0, x: 0, y: -4, scale: 0.8, rx: 2, ry: -10, rz: -1, opacity: 1, ease: 'out' },
      { at: 0.1, x: 0, y: -4, scale: 0.83, rx: 1, ry: -8, rz: -1, opacity: 1, ease: 'inOut' },
      { at: 0.23, x: 0, y: -9, scale: 0.98, rx: 0, ry: -2, rz: 0, opacity: 1, ease: 'out' },
      { at: 0.33, x: 0, y: -9, scale: 1.02, rx: 0, ry: 0, rz: 0, opacity: 1, ease: 'soft' },
      { at: 0.44, x: 0, y: -8, scale: 0.95, rx: 0, ry: 0, rz: 0, opacity: 1, ease: 'inOut' },
      { at: 0.51, x: -1, y: -9, scale: 0.72, rx: 0, ry: 2, rz: 1, opacity: 0.64, ease: 'inOut' },
      { at: 0.56, x: -1, y: -12, scale: 0.61, rx: 1, ry: -4, rz: -1, opacity: 0.08, ease: 'soft' },
      { at: 0.7, x: 0, y: -12, scale: 0.57, rx: 0, ry: -4, rz: 0, opacity: 0.04, ease: 'inOut' },
      { at: 0.76, x: 0, y: -14, scale: 0.54, rx: 0, ry: -3, rz: 0, opacity: 0.02, ease: 'soft' },
      { at: 0.88, x: 0, y: -13, scale: 0.54, rx: 0, ry: -3, rz: 0, opacity: 0.04, ease: 'expo' },
      { at: 0.95, x: 0, y: -28, scale: 0.76, rx: 0, ry: -1, rz: 0, opacity: 1, ease: 'out' },
      { at: 1, x: 0, y: -28, scale: 0.76, rx: 0, ry: -1, rz: 0, opacity: 1 },
    ],
    canvas: [
      { at: 0, x: 19, y: 2, scale: 0.58, rz: 5, ry: -12, opacity: 0, ease: 'expo' },
      { at: 0.46, x: 19, y: 2, scale: 0.58, rz: 5, ry: -12, opacity: 0, ease: 'out' },
      { at: 0.49, x: 15, y: 2, scale: 0.72, rz: 4, ry: -9, opacity: 0.18, ease: 'out' },
      { at: 0.57, x: 0, y: 0, scale: 0.96, rz: 0, ry: 0, opacity: 1, ease: 'soft' },
      { at: 0.64, x: 0, y: 0, scale: 0.96, rz: 0, ry: 0, opacity: 1, ease: 'inOut' },
      { at: 0.7, x: -8, y: 1, scale: 0.78, rz: -2, ry: 3, opacity: 0.54, ease: 'inOut' },
      { at: 0.74, x: 18, y: 1, scale: 0.54, rz: -4, ry: 10, opacity: 0, ease: 'out' },
      { at: 0.89, x: 18, y: 14, scale: 0.4, rz: -4, ry: 8, opacity: 0, ease: 'out' },
      { at: 0.96, x: 7, y: 14, scale: 0.43, rz: -3, ry: -2, opacity: 1, ease: 'soft' },
      { at: 1, x: 7, y: 14, scale: 0.43, rz: -3, ry: -2, opacity: 1 },
    ],
    canvasMobile: [
      { at: 0, x: 0, y: 0, scale: 0.54, rz: 4, ry: -8, opacity: 0, ease: 'expo' },
      { at: 0.46, x: 0, y: 0, scale: 0.54, rz: 4, ry: -8, opacity: 0, ease: 'out' },
      { at: 0.49, x: 5, y: 0, scale: 0.7, rz: 3, ry: -6, opacity: 0.18, ease: 'out' },
      { at: 0.57, x: -10, y: 0, scale: 0.95, rz: 0, ry: 0, opacity: 1, ease: 'soft' },
      { at: 0.64, x: -10, y: 0, scale: 0.95, rz: 0, ry: 0, opacity: 1, ease: 'inOut' },
      { at: 0.7, x: -8, y: 0, scale: 0.76, rz: -2, ry: 3, opacity: 0.54, ease: 'inOut' },
      { at: 0.74, x: 15, y: 0, scale: 0.5, rz: -4, ry: 8, opacity: 0, ease: 'out' },
      { at: 0.89, x: 15, y: 10, scale: 0.38, rz: -4, ry: 8, opacity: 0, ease: 'out' },
      { at: 0.96, x: -15, y: 0, scale: 0.43, rz: -3, ry: -1, opacity: 1, ease: 'soft' },
      { at: 1, x: -15, y: 0, scale: 0.43, rz: -3, ry: -1, opacity: 1 },
    ],
    python: [
      { at: 0, x: 19, y: -2, scale: 0.48, rz: -5, ry: 12, opacity: 0, ease: 'expo' },
      { at: 0.68, x: 19, y: -2, scale: 0.48, rz: -5, ry: 12, opacity: 0, ease: 'out' },
      { at: 0.69, x: 18, y: 0, scale: 0.65, rz: -4, ry: 10, opacity: 0.2, ease: 'out' },
      { at: 0.78, x: -8, y: 0, scale: 0.96, rz: 0, ry: 0, opacity: 1, ease: 'soft' },
      { at: 0.85, x: -8, y: 0, scale: 0.96, rz: 0, ry: 0, opacity: 1, ease: 'inOut' },
      { at: 0.9, x: 8, y: 16, scale: 0.4, rz: 3, ry: -2, opacity: 1, ease: 'out' },
      { at: 1, x: 8, y: 16, scale: 0.4, rz: 3, ry: -2, opacity: 1 },
    ],
    pythonMobile: [
      { at: 0, x: 13, y: -2, scale: 0.48, rz: -5, ry: 10, opacity: 0, ease: 'expo' },
      { at: 0.68, x: 13, y: -2, scale: 0.48, rz: -5, ry: 10, opacity: 0, ease: 'out' },
      { at: 0.69, x: 10, y: 0, scale: 0.62, rz: -3, ry: 8, opacity: 0.2, ease: 'out' },
      { at: 0.78, x: -22, y: 0, scale: 0.94, rz: 0, ry: 0, opacity: 1, ease: 'soft' },
      { at: 0.85, x: -22, y: 0, scale: 0.94, rz: 0, ry: 0, opacity: 1, ease: 'inOut' },
      { at: 0.9, x: 12, y: -2, scale: 0.39, rz: 3, ry: -2, opacity: 1, ease: 'out' },
      { at: 1, x: 12, y: -2, scale: 0.39, rz: 3, ry: -2, opacity: 1 },
    ],
    tracer: [
      { at: 0, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0, ease: 'out' },
      { at: 0.12, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0, ease: 'expo' },
      { at: 0.18, x: 0, y: -0.5, z: 18, scale: 1.04, opacity: 1, pop: 1, ease: 'out' },
      { at: 0.25, x: -0.5, y: -0.8, z: 24, scale: 1.08, opacity: 1, pop: 1, ease: 'inOut' },
      { at: 0.35, x: -0.5, y: -0.8, z: 24, scale: 1.08, opacity: 1, pop: 1, ease: 'inOut' },
      { at: 0.42, x: -0.3, y: 0, z: 0, scale: 1.01, opacity: 0, pop: 0, ease: 'inOut' },
      { at: 1, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0 },
    ],
    task: [
      { at: 0, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0, ease: 'out' },
      { at: 0.16, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0, ease: 'out' },
      { at: 0.22, x: 0.4, y: 0.4, z: 16, scale: 1.04, opacity: 1, pop: 1, ease: 'out' },
      { at: 0.3, x: 0.6, y: 0.6, z: 30, scale: 1.09, opacity: 1, pop: 1, ease: 'soft' },
      { at: 0.38, x: 0.6, y: 0.6, z: 30, scale: 1.09, opacity: 1, pop: 1, ease: 'inOut' },
      { at: 0.44, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0, ease: 'inOut' },
      { at: 1, x: 0, y: 0, z: 0, scale: 1, opacity: 0, pop: 0 },
    ],
  };

  function sample(track, progress) {
    let nextIndex = track.findIndex((frame) => frame.at >= progress);
    if (nextIndex <= 0) return { ...track[Math.max(0, nextIndex)] };
    if (nextIndex < 0) return { ...track[track.length - 1] };
    const from = track[nextIndex - 1];
    const to = track[nextIndex];
    const amount = clamp((progress - from.at) / Math.max(0.0001, to.at - from.at));
    const eased = (eases[from.ease] || eases.soft)(amount);
    const pose = {};
    for (const key of Object.keys(to)) {
      if (key === 'at' || key === 'ease') continue;
      pose[key] = typeof to[key] === 'number' ? mix(from[key] ?? to[key], to[key], eased) : to[key];
    }
    return pose;
  }

  const format = (value, digits = 3) => Number(value).toFixed(digits);
  function setPose(element, track, progress, windowPose = false) {
    if (!element) return;
    const pose = sample(track, progress);
    if (!windowPose && window.innerWidth > 700 && window.innerWidth <= 1100) {
      if (element === captures.overview) {
        if (progress <= 0.1) {
          pose.x = mix(0, -1, progress / 0.1);
          pose.scale = mix(0.5, 0.54, progress / 0.1);
        } else if (progress < 0.52) {
          pose.x = -2;
          pose.scale = Math.min(pose.scale, 0.56);
        }
      }
      if (element === captures.canvas && progress >= 0.49 && progress < 0.74) {
        if (progress <= 0.57) {
          const amount = clamp((progress - 0.49) / 0.08);
          pose.x = mix(15, 10, amount);
          pose.scale = mix(0.5, 0.62, amount);
        } else if (progress <= 0.64) {
          pose.x = 10;
          pose.scale = 0.62;
        } else {
          const amount = clamp((progress - 0.64) / 0.1);
          pose.x = mix(10, 18, amount);
          pose.scale = mix(0.62, 0.54, amount);
        }
      }
      if (element === captures.python && progress >= 0.69 && progress < 0.9) {
        if (progress <= 0.78) {
          const amount = clamp((progress - 0.69) / 0.09);
          pose.x = mix(18, 2.5, amount);
          pose.scale = mix(0.65, 0.62, amount);
        } else if (progress <= 0.85) {
          pose.x = 2.5;
          pose.scale = 0.62;
        } else {
          const amount = clamp((progress - 0.85) / 0.05);
          pose.x = mix(2.5, 15, amount);
          pose.scale = mix(0.62, 0.4, amount);
        }
      }
    }
    const property = (name, value) => element.style.setProperty(`--${windowPose ? 'crop' : 'pose'}-${name}`, value);
    property('x', `${format(pose.x)}vw`);
    property('y', `${format(pose.y)}vh`);
    if (windowPose) {
      property('z', `${format(pose.z, 1)}px`);
      property('scale', format(pose.scale));
      property('opacity', format(pose.opacity));
      property('pop', format(pose.pop));
      return;
    }
    property('z', `${format(pose.z || 0, 1)}px`);
    property('scale', format(pose.scale));
    property('rx', `${format(pose.rx || 0, 2)}deg`);
    property('ry', `${format(pose.ry || 0, 2)}deg`);
    property('rz', `${format(pose.rz || 0, 2)}deg`);
    element.style.setProperty('--window-opacity', format(pose.opacity));
  }

  function fadeInOut(progress, enterStart, enterEnd, exitStart, exitEnd) {
    if (progress < enterStart || progress >= exitEnd) return 0;
    if (progress < enterEnd) return eases.out(clamp((progress - enterStart) / (enterEnd - enterStart)));
    if (progress <= exitStart) return 1;
    return 1 - eases.inOut(clamp((progress - exitStart) / (exitEnd - exitStart)));
  }

  function activeChapter(progress) {
    if (progress < 0.16) return 'hero';
    if (progress < 0.48) return 'workspace';
    if (progress < 0.7) return 'canvas';
    if (progress < 0.9) return 'python';
    return 'ending';
  }

  let currentChapter = '';
  function syncChapter(progress) {
    const chapter = activeChapter(progress);
    if (chapter === currentChapter) return;
    currentChapter = chapter;
    for (const section of narratives) {
      const active = section.dataset.s23Narrative === chapter;
      section.setAttribute('aria-hidden', String(!active));
      section.inert = !active;
      const cta = section.querySelector('[data-s23-ending-cta]');
      if (cta) {
        if (active) cta.removeAttribute('tabindex');
        else cta.setAttribute('tabindex', '-1');
      }
    }
  }

  function setFocus(progress) {
    if (!sharedFocus || !sharedImage || !overviewImage || !overviewImage.complete || !overviewImage.naturalWidth) return;
    if (progress < 0.25 || progress > 0.5) {
      sharedFocus.style.setProperty('--focus-opacity', '0');
      return;
    }

    const imageRect = overviewImage.getBoundingClientRect();
    const crop = { x: 801 / 1920, y: 97 / 1080, width: 600 / 1920, height: 650 / 1080 };
    const source = {
      left: imageRect.left + imageRect.width * crop.x,
      top: imageRect.top + imageRect.height * crop.y,
      width: imageRect.width * crop.width,
      height: imageRect.height * crop.height,
    };
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const aspect = 600 / 650;
    const maxWidth = vh * (isSmall.matches ? 0.48 : 0.64) * aspect;
    const targetWidth = Math.min(vw * (isSmall.matches ? 0.9 : 0.34), maxWidth);
    const targetHeight = targetWidth / aspect;
    const targetCenterX = isSmall.matches ? vw * 0.5 : vw * 0.69;
    const targetCenterY = vh * (isSmall.matches ? 0.44 : 0.47);
    const fullAt = 0.365;
    const amount = progress < fullAt
      ? eases.inOut(clamp((progress - 0.27) / (fullAt - 0.27)))
      : 1 - eases.inOut(clamp((progress - 0.405) / (0.475 - 0.405)));
    const left = mix(source.left, targetCenterX - targetWidth / 2, amount);
    const top = mix(source.top, targetCenterY - targetHeight / 2, amount);
    const width = mix(source.width, targetWidth, amount);
    const height = mix(source.height, targetHeight, amount);
    const imageScale = width / Math.max(1, source.width);
    const cropLeft = imageRect.width * crop.x * imageScale;
    const cropTop = imageRect.height * crop.y * imageScale;
    const scaledImageWidth = imageRect.width * imageScale;
    const scaledImageHeight = imageRect.height * imageScale;

    sharedFocus.style.left = `${left}px`;
    sharedFocus.style.top = `${top}px`;
    sharedFocus.style.width = `${width}px`;
    sharedFocus.style.height = `${height}px`;
    sharedFocus.style.setProperty('--focus-opacity', format(clamp(amount * 1.7)));
    sharedFocus.style.setProperty('--focus-light', format(amount));
    sharedImage.style.backgroundImage = `url("${overviewImage.currentSrc || overviewImage.src}")`;
    sharedImage.style.left = `${-cropLeft}px`;
    sharedImage.style.top = `${-cropTop}px`;
    sharedImage.style.width = `${scaledImageWidth}px`;
    sharedImage.style.height = `${scaledImageHeight}px`;
    sharedImage.style.backgroundSize = '100% 100%';
    sharedImage.style.backgroundPosition = '0 0';
  }

  function setMascot(progress) {
    if (!mascot) return;
    const mobile = isSmall.matches;
    const keyframes = mobile
      ? [
          { at: 0, x: 65, y: 70, scale: 0.82, rz: -2, ease: 'out' },
          { at: 0.13, x: 68, y: 52, scale: 0.86, rz: 1, ease: 'out' },
          { at: 0.31, x: 68, y: 61, scale: 0.8, rz: -1, ease: 'soft' },
          { at: 0.52, x: 75, y: 80, scale: 0.78, rz: 1, ease: 'inOut' },
          { at: 0.72, x: 75, y: 80, scale: 0.8, rz: -1, ease: 'out' },
          { at: 0.9, x: 78, y: 79, scale: 0.82, rz: 1, ease: 'soft' },
          { at: 1, x: 78, y: 79, scale: 0.82, rz: 1 },
        ]
      : [
          { at: 0, x: 82, y: 66, scale: 0.9, rz: -2, ease: 'out' },
          { at: 0.13, x: 86, y: 50, scale: 1.04, rz: 1, ease: 'out' },
          { at: 0.3, x: 83, y: 66, scale: 0.94, rz: -1, ease: 'soft' },
          { at: 0.48, x: 83, y: 65, scale: 0.9, rz: 0, ease: 'inOut' },
          { at: 0.58, x: 89, y: 68, scale: 0.88, rz: 2, ease: 'out' },
          { at: 0.74, x: 89, y: 68, scale: 0.92, rz: -2, ease: 'inOut' },
          { at: 0.92, x: 88, y: 80, scale: 1, rz: 1, ease: 'soft' },
          { at: 1, x: 88, y: 80, scale: 1, rz: 1 },
        ];
    const pose = sample(keyframes, progress);
    mascot.style.setProperty('--boo-x', `${format(pose.x)}vw`);
    mascot.style.setProperty('--boo-y', `${format(pose.y)}vh`);
    mascot.style.setProperty('--boo-z', `${mobile ? 54 : 96}px`);
    mascot.style.setProperty('--boo-rotate', `${format(pose.rz)}deg`);
    mascot.style.setProperty('--boo-scale', format(pose.scale));
    mascot.style.setProperty('--boo-width', `${Math.min(window.innerWidth * (mobile ? 0.31 : 0.12), mobile ? 126 : 238)}px`);

    const peek = 1 - eases.inOut(clamp((progress - 0.08) / 0.09));
    const point = Math.max(
      fadeInOut(progress, 0.09, 0.17, 0.41, 0.49),
      fadeInOut(progress, 0.89, 0.94, 1.1, 1.2),
    );
    const read = Math.max(
      fadeInOut(progress, 0.44, 0.53, 0.64, 0.72),
      fadeInOut(progress, 0.68, 0.75, 0.85, 0.91),
    );
    mascot.style.setProperty('--boo-peek', format(peek));
    mascot.style.setProperty('--boo-point', format(point));
    mascot.style.setProperty('--boo-read', format(read));
  }

  let frame = 0;
  function render() {
    frame = 0;
    if (reducedMotion.matches) return;
    const storyTop = story.getBoundingClientRect().top + window.scrollY;
    const travel = Math.max(1, story.offsetHeight - window.innerHeight);
    const progress = clamp((window.scrollY - storyTop) / travel);
    const mobile = isSmall.matches;
    const overviewTrack = mobile ? tracks.overviewMobile : tracks.overview;
    const canvasTrack = mobile ? tracks.canvasMobile : tracks.canvas;
    const pythonTrack = mobile ? tracks.pythonMobile : tracks.python;

    setPose(captures.overview, overviewTrack, progress);
    setPose(captures.canvas, canvasTrack, progress);
    setPose(captures.python, pythonTrack, progress);
    setPose(detailImages.tracer, tracks.tracer, progress, true);
    setPose(detailImages.task, tracks.task, progress, true);
    setFocus(progress);

    for (const [name, interval] of Object.entries({
      hero: [0, 0, 0.115, 0.17],
      workspace: [0.145, 0.22, 0.425, 0.49],
      canvas: [0.465, 0.54, 0.635, 0.705],
      python: [0.675, 0.76, 0.85, 0.92],
      ending: [0.89, 0.96, 1.1, 1.2],
    })) {
      const [enterStart, enterEnd, exitStart, exitEnd] = interval;
      const element = narratives.find((item) => item.dataset.s23Narrative === name);
      if (!element) continue;
      const alpha = fadeInOut(progress, enterStart, enterEnd, exitStart, exitEnd);
      element.style.setProperty('--copy-opacity', format(alpha));
      element.style.setProperty('--copy-y', `${format((1 - alpha) * 14, 1)}px`);
    }

    if (progress >= 0.49 && progress < 0.73) set.front = 'canvas';
    else if (progress >= 0.73 && progress < 0.9) set.front = 'python';
    else if (progress >= 0.9) set.front = 'python';
    else set.front = '';
    if (set.dataset.s23Front !== set.front) {
      if (set.front) set.dataset.s23Front = set.front;
      else delete set.dataset.s23Front;
    }

    setMascot(progress);
    stage.style.setProperty('--floor-y', `${format(progress * -2.5, 2)}vh`);
    stage.style.setProperty('--floor-opacity', format(0.55 + Math.sin(progress * Math.PI) * 0.28));
    syncChapter(progress);
    document.querySelector('[data-s23-scroll-cue]')?.style.setProperty('--cue-opacity', format(1 - clamp(progress / 0.17)));
  }

  function scheduleRender() {
    if (!frame) frame = window.requestAnimationFrame(render);
  }

  function enableMotion() {
    if (reducedMotion.matches) {
      html.removeAttribute('data-s23-motion');
      for (const section of narratives) {
        section.removeAttribute('aria-hidden');
        section.inert = false;
        section.style.removeProperty('--copy-opacity');
        section.style.removeProperty('--copy-y');
        section.querySelector('[data-s23-ending-cta]')?.removeAttribute('tabindex');
      }
      for (const capture of Object.values(captures)) {
        for (const property of ['--window-opacity', '--pose-x', '--pose-y', '--pose-z', '--pose-scale', '--pose-rx', '--pose-ry', '--pose-rz']) {
          capture?.style.removeProperty(property);
        }
      }
      for (const detail of Object.values(detailImages)) {
        for (const property of ['--crop-x', '--crop-y', '--crop-z', '--crop-scale', '--crop-opacity', '--crop-pop']) {
          detail?.style.removeProperty(property);
        }
      }
      sharedFocus?.removeAttribute('style');
      sharedImage?.removeAttribute('style');
      mascot?.removeAttribute('style');
      stage.style.removeProperty('--floor-y');
      stage.style.removeProperty('--floor-opacity');
      set.removeAttribute('data-s23-front');
      document.querySelector('[data-s23-scroll-cue]')?.style.removeProperty('--cue-opacity');
      return;
    }

    html.dataset.s23Motion = 'on';
    scheduleRender();
  }

  for (const link of document.querySelectorAll('[data-s23-scroll]')) {
    link.addEventListener('click', (event) => {
      if (reducedMotion.matches) return;
      const progress = clamp(Number(link.dataset.s23Scroll));
      const storyTop = story.getBoundingClientRect().top + window.scrollY;
      const travel = Math.max(0, story.offsetHeight - window.innerHeight);
      event.preventDefault();
      window.scrollTo({ top: storyTop + travel * progress, behavior: 'smooth' });
    });
  }

  window.addEventListener('scroll', scheduleRender, { passive: true });
  window.addEventListener('resize', scheduleRender, { passive: true });
  window.addEventListener('pageshow', scheduleRender);
  reducedMotion.addEventListener?.('change', enableMotion);
  isSmall.addEventListener?.('change', scheduleRender);
  enableMotion();
})();
