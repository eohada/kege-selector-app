(() => {
  const profile = document.querySelector('[data-s39-profile]');
  if (!profile || document.querySelector('[data-s42-founder]')) return;

  profile.insertAdjacentHTML('afterend', `
    <section class="s42-founder-story" id="s42-founder" data-s42-founder data-phase="read" data-reveal-state="pending" aria-labelledby="s42-founder-title">
      <div class="s42-founder-pin">
        <div class="s42-bridge" aria-hidden="true"><span>ТВОЙ УЧЕБНЫЙ ПУТЬ</span><i>→</i><strong>ОПЫТ СОЗДАТЕЛЯ</strong></div>
        <div class="s42-founder-layout">
          <div class="s42-founder-copy">
            <p class="s42-eyebrow">ЗНАКОМЬСЯ, СОЗДАТЕЛЬ BOOSTUDY</p>
            <h2 id="s42-founder-title" data-s42-reveal>Создано преподавателем. Для настоящего обучения.</h2>
            <p class="s42-founder-lead" data-s42-reveal>За этой системой — опыт настоящего преподавателя.</p>
            <div class="s42-founder-story-text">
              <p data-typewriter>Я — создатель BooStudy и практикующий преподаватель. На индивидуальных занятиях я увидел, сколько внимания забирают разрозненные инструменты и учебная рутина.</p>
              <p data-typewriter>Поэтому я создаю платформу, где уроки, практика, теория и прогресс связаны между собой. Для меня важно не только найти ответ, но и научиться самостоятельно разбираться в задачах и применять знания.</p>
            </div>
            <p class="s42-founder-signature" data-s42-reveal>Создатель BooStudy <span>·</span> Преподаватель <span>·</span> Разработчик образовательных инструментов</p>
            <section class="s42-personal-invitation" aria-labelledby="s42-invitation-title">
              <p class="s42-eyebrow" data-s42-invitation-eyebrow>ТВОЙ СЛЕДУЮЩИЙ ШАГ</p>
              <h3 id="s42-invitation-title" data-typewriter>Давай обсудим твоё обучение.</h3>
              <p class="s42-invitation-copy" data-typewriter>Расскажи, чему хочешь научиться, какие цели перед собой ставишь и что сейчас вызывает трудности. Мы сможем вместе обсудить твои задачи, подход к обучению и то, как BooStudy может в этом помочь. Напиши мне напрямую — буду рад познакомиться и ответить на вопросы.</p>
              <div class="s42-founder-actions" data-s42-reveal-actions>
                <a class="s42-telegram-link" href="https://t.me/eohada" target="_blank" rel="noopener noreferrer" aria-label="Написать создателю BooStudy в Telegram, @eohada">
                  <span class="s42-telegram-icon" aria-hidden="true">↗</span><span>Написать мне в Telegram</span><b>@eohada</b>
                </a>
                <a class="s42-register-link" href="/register">Начать обучение <b aria-hidden="true">↗</b></a>
              </div>
            </section>
          </div>
          <aside class="s42-creator-card" aria-label="Создатель BooStudy — преподаватель и разработчик образовательных инструментов">
            <div class="s42-creator-glow" aria-hidden="true"></div>
            <div class="s42-creator-orbit s42-creator-orbit--outer" aria-hidden="true"></div>
            <div class="s42-creator-orbit s42-creator-orbit--inner" aria-hidden="true"></div>
            <div class="s42-creator-mark" aria-hidden="true">B</div>
            <p class="s42-creator-label">ОБРАЗОВАНИЕ × ТЕХНОЛОГИИ</p>
            <p class="s42-creator-handle">@eohada</p>
            <div class="s42-creator-roles" aria-label="Роли создателя">
              <span>Преподавание</span><i aria-hidden="true">+</i><span>Разработка</span>
            </div>
            <div class="s42-creator-path" aria-label="Связь занятий, практики и прогресса">
              <span>Урок</span><i aria-hidden="true">→</i><span>Практика</span><i aria-hidden="true">→</i><span>Прогресс</span>
            </div>
            <small>Собственная среда для осмысленного обучения</small>
          </aside>
        </div>
      </div>
    </section>
  `);

  const founder = document.querySelector('[data-s42-founder]');
  const title = founder.querySelector('#s42-founder-title');
  const lead = founder.querySelector('.s42-founder-lead');
  const signature = founder.querySelector('.s42-founder-signature');
  const invitationEyebrow = founder.querySelector('[data-s42-invitation-eyebrow]');
  const actions = founder.querySelector('[data-s42-reveal-actions]');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const speed = { value: 1 };
  const typewriterBlocks = [...founder.querySelectorAll('[data-typewriter]')].map(installTypewriter);
  const revealAnimations = new Set();
  let revealStarted = false;
  let revealFinished = false;
  let paused = false;
  let forceComplete = false;
  let timerId = 0;
  let pendingResolve = null;
  let pendingRemaining = 0;
  let pendingDueAt = 0;
  let resolveReveal;
  let resolveTitleReveal;
  let manualRevealTimer = 0;
  const revealComplete = new Promise((resolve) => { resolveReveal = resolve; });
  const titleRevealComplete = new Promise((resolve) => { resolveTitleReveal = resolve; });

  function installTypewriter(node) {
    const text = node.textContent;
    const clusters = typeof Intl.Segmenter === 'function'
      ? [...new Intl.Segmenter('ru', { granularity: 'grapheme' }).segment(text)].map((part) => part.segment)
      : Array.from(text);
    const accessible = document.createElement('span');
    accessible.className = 's42-typewriter-accessible';
    accessible.textContent = text;
    const measure = document.createElement('span');
    measure.className = 's42-typewriter-measure';
    measure.setAttribute('aria-hidden', 'true');
    measure.textContent = text;
    const output = document.createElement('span');
    output.className = 's42-typewriter-output';
    output.setAttribute('aria-hidden', 'true');
    const outputText = document.createTextNode('');
    const cursor = document.createElement('span');
    cursor.className = 's42-typewriter-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    cursor.hidden = true;
    output.append(outputText, cursor);
    node.classList.add('s42-typewriter');
    node.replaceChildren(accessible, measure, output);
    return { node, text, clusters, accessible, measure, output, outputText, cursor, index: 0 };
  }

  function markVisible(node) {
    if (!node) return;
    node.classList.add('is-revealed');
  }

  function fadeIn(node, duration = 240) {
    if (!node || node.classList.contains('is-revealed') || prefersReducedMotion.matches) {
      markVisible(node);
      return Promise.resolve();
    }
    const animation = node.animate([
      { opacity: 0 },
      { opacity: 1 }
    ], { duration, easing: 'ease-out', fill: 'both' });
    revealAnimations.add(animation);
    return animation.finished.then(() => markVisible(node), () => {}).finally(() => revealAnimations.delete(animation));
  }

  function schedulePending() {
    if (paused || !pendingResolve || timerId) return;
    pendingDueAt = performance.now() + pendingRemaining;
    timerId = window.setTimeout(() => {
      timerId = 0;
      pendingRemaining = 0;
      const resolve = pendingResolve;
      pendingResolve = null;
      resolve?.();
    }, pendingRemaining);
  }

  function wait(ms) {
    if (forceComplete) return Promise.resolve();
    pendingRemaining = Math.max(0, ms);
    const promise = new Promise((resolve) => { pendingResolve = resolve; });
    schedulePending();
    return promise;
  }

  async function focusBlockForMobile(block) {
    if (window.innerWidth > 720 || !window.BooStudyGuidedTour?.isAutoMode() || forceComplete) return;
    const panel = document.querySelector('[data-rc3-tour-panel]');
    const panelHeight = panel && !panel.hidden ? panel.getBoundingClientRect().height : 0;
    const safeTop = Math.max(40, window.innerHeight * 0.08);
    const safeBottom = window.innerHeight - panelHeight - 18;
    const rect = block.node.getBoundingClientRect();
    if (rect.top >= safeTop && rect.bottom <= safeBottom) return;
    const targetTop = Math.max(0, window.scrollY + rect.top - safeTop);
    document.dispatchEvent(new CustomEvent('boostudy:founder-pan', {
      detail: { blockIndex: typewriterBlocks.indexOf(block), fromY: Math.round(window.scrollY), targetY: Math.round(targetTop) }
    }));
    window.scrollTo({ top: targetTop, behavior: 'smooth' });
    const deadline = performance.now() + 1800;
    let stableFrames = 0;
    let lastY = window.scrollY;
    while (!forceComplete && performance.now() < deadline) {
      await new Promise(resolve => requestAnimationFrame(resolve));
      const currentY = window.scrollY;
      stableFrames = Math.abs(currentY - lastY) < 1 ? stableFrames + 1 : 0;
      lastY = currentY;
      if (Math.abs(targetTop - currentY) <= 2 || stableFrames >= 4) break;
    }
  }

  function characterDelay(cluster) {
    const rate = Math.min(60, Math.max(36, 48 * speed.value));
    const base = 1000 / rate;
    if (/[,;:]/u.test(cluster)) return base + 70;
    if (/[.!?…]/u.test(cluster)) return base + 150;
    if (/\n/u.test(cluster)) return base + 110;
    return base;
  }

  function reportProgress(block) {
    founder.dataset.typewriterIndex = String(typewriterBlocks.reduce((count, item) => count + item.index, 0));
    founder.dataset.typewriterTotal = String(typewriterBlocks.reduce((count, item) => count + item.clusters.length, 0));
    document.dispatchEvent(new CustomEvent('boostudy:typewriter-progress', {
      detail: { block: typewriterBlocks.indexOf(block), index: block.index, total: block.clusters.length }
    }));
  }

  async function typeBlock(block) {
    await focusBlockForMobile(block);
    block.cursor.hidden = false;
    block.node.dataset.typewriterState = 'typing';
    while (block.index < block.clusters.length && !forceComplete) {
      await wait(characterDelay(block.clusters[block.index]));
      if (forceComplete) return;
      block.index += 1;
      block.outputText.data = block.clusters.slice(0, block.index).join('');
      reportProgress(block);
    }
    if (!forceComplete) {
      block.cursor.hidden = true;
      block.node.dataset.typewriterState = 'complete';
      founder.dataset.phase = typewriterBlocks.indexOf(block) < 2 ? 'understand' : 'move-on';
      await wait(420);
    }
  }

  function fillAllTypewriterBlocks() {
    typewriterBlocks.forEach((block) => {
      block.index = block.clusters.length;
      block.outputText.data = block.text;
      block.cursor.hidden = true;
      block.node.dataset.typewriterState = 'complete';
    });
    reportProgress(typewriterBlocks.at(-1));
  }

  function finishReveal() {
    if (revealFinished) return;
    forceComplete = true;
    if (timerId) window.clearTimeout(timerId);
    timerId = 0;
    const resolveWait = pendingResolve;
    pendingResolve = null;
    pendingRemaining = 0;
    resolveWait?.();
    revealAnimations.forEach((animation) => animation.cancel());
    revealAnimations.clear();
    fillAllTypewriterBlocks();
    [title, lead, signature, invitationEyebrow].forEach(markVisible);
    founder.classList.add('is-invitation-ready');
    actions.classList.add('is-revealed');
    actions.setAttribute('aria-hidden', 'false');
    resolveTitleReveal?.();
    resolveTitleReveal = null;
    revealFinished = true;
    founder.dataset.phase = 'move-on';
    founder.dataset.revealState = 'complete';
    resolveReveal?.();
    resolveReveal = null;
  }

  async function runReveal() {
    founder.dataset.revealState = 'revealing';
    founder.dataset.phase = 'read';
    await Promise.all([fadeIn(title, 240), fadeIn(lead, 240)]);
    resolveTitleReveal?.();
    resolveTitleReveal = null;
    if (forceComplete) return;
    await window.BooStudyGuidedTour?.waitForFounderStaticReading?.();
    if (forceComplete) return;
    await typeBlock(typewriterBlocks[0]);
    if (forceComplete) return;
    await typeBlock(typewriterBlocks[1]);
    if (forceComplete) return;
    founder.dataset.phase = 'understand';
    founder.classList.add('is-invitation-ready');
    await Promise.all([fadeIn(signature, 220), fadeIn(invitationEyebrow, 220)]);
    if (forceComplete) return;
    await typeBlock(typewriterBlocks[2]);
    if (forceComplete) return;
    await typeBlock(typewriterBlocks[3]);
    if (forceComplete) return;
    await fadeIn(actions, 240);
    if (forceComplete) return;
    actions.setAttribute('aria-hidden', 'false');
    revealFinished = true;
    founder.dataset.phase = 'move-on';
    founder.dataset.revealState = 'complete';
    resolveReveal?.();
    resolveReveal = null;
  }

  function beginReveal(force = false) {
    if (revealFinished) return revealComplete;
    if (revealStarted || (!force && window.BooStudyGuidedTour?.isAutoMode())) return revealComplete;
    revealStarted = true;
    if (prefersReducedMotion.matches) {
      finishReveal();
      return revealComplete;
    }
    runReveal().catch((error) => {
      founder.dataset.revealError = error?.message || 'Typewriter animation failed';
      finishReveal();
    });
    return revealComplete;
  }

  founder.classList.add('is-reveal-ready');
  actions.setAttribute('aria-hidden', 'true');
  actions.classList.remove('is-revealed');
  if (prefersReducedMotion.matches) finishReveal();
  else {
    const titleIsVisible = () => {
      const rect = title.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.top < window.innerHeight * 0.88 && rect.bottom > 0;
    };
    const syncManualReveal = () => {
      if (window.BooStudyGuidedTour?.isAutoMode() || revealStarted || revealFinished || !titleIsVisible()) return;
      window.clearTimeout(manualRevealTimer);
      manualRevealTimer = window.setTimeout(() => {
        if (!window.BooStudyGuidedTour?.isAutoMode() && titleIsVisible()) beginReveal();
      }, 120);
    };
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(syncManualReveal, { rootMargin: '-8% 0px -12% 0px', threshold: [0, 0.25] });
      observer.observe(title);
    }
    window.addEventListener('scroll', syncManualReveal, { passive: true });
    window.addEventListener('resize', syncManualReveal, { passive: true });
  }

  prefersReducedMotion.addEventListener?.('change', () => {
    if (prefersReducedMotion.matches) finishReveal();
  });

  window.BooStudyFounderReveal = {
    start: () => beginReveal(true),
    waitForTitle: () => titleRevealComplete,
    finish: finishReveal,
    pause: () => {
      if (paused || revealFinished) return;
      paused = true;
      if (timerId) {
        pendingRemaining = Math.max(0, pendingDueAt - performance.now());
        window.clearTimeout(timerId);
        timerId = 0;
      }
      revealAnimations.forEach((animation) => { if (animation.playState === 'running') animation.pause(); });
      founder.dataset.typewriterState = 'paused';
    },
    resume: () => {
      if (!paused || revealFinished) return;
      paused = false;
      revealAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
      schedulePending();
      founder.dataset.typewriterState = 'typing';
    },
    setSpeed: (nextSpeed) => {
      if (!Number.isFinite(nextSpeed) || nextSpeed <= 0 || nextSpeed === speed.value) return;
      if (timerId) {
        pendingRemaining = Math.max(0, pendingDueAt - performance.now()) * speed.value / nextSpeed;
        window.clearTimeout(timerId);
        timerId = 0;
      }
      speed.value = nextSpeed;
      schedulePending();
    },
    estimatedDuration: (playbackSpeed = speed.value) => {
      const rate = Math.min(60, Math.max(36, 48 * playbackSpeed));
      const chars = typewriterBlocks.reduce((total, block) => total + block.clusters.length, 0);
      const punctuation = typewriterBlocks.reduce((total, block) => total + block.clusters.filter((part) => /[,;:]/u.test(part)).length * 70 + block.clusters.filter((part) => /[.!?…]/u.test(part)).length * 150, 0);
      return chars / rate * 1000 + punctuation + typewriterBlocks.length * 420 + 700;
    },
    get complete() { return revealFinished; },
    get started() { return revealStarted; },
    get paused() { return paused; },
    get promise() { return revealComplete; }
  };
})();
