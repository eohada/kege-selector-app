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
              <p data-s42-reveal>Я — создатель BooStudy и практикующий преподаватель. На индивидуальных занятиях я увидел, сколько внимания забирают разрозненные инструменты и учебная рутина.</p>
              <p data-s42-reveal>Поэтому я создаю платформу, где уроки, практика, теория и прогресс связаны между собой. Для меня важно не только найти ответ, но и научиться самостоятельно разбираться в задачах и применять знания.</p>
            </div>
            <p class="s42-founder-signature" data-s42-reveal>Создатель BooStudy <span>·</span> Преподаватель <span>·</span> Разработчик образовательных инструментов</p>
            <section class="s42-personal-invitation" aria-labelledby="s42-invitation-title">
              <p class="s42-eyebrow" data-s42-reveal>ТВОЙ СЛЕДУЮЩИЙ ШАГ</p>
              <h3 id="s42-invitation-title" data-s42-reveal>Давай обсудим твоё обучение.</h3>
              <p class="s42-invitation-copy" data-s42-reveal>Расскажи, чему хочешь научиться, какие цели перед собой ставишь и что сейчас вызывает трудности. Мы сможем вместе обсудить твои задачи, подход к обучению и то, как BooStudy может в этом помочь. Напиши мне напрямую — буду рад познакомиться и ответить на вопросы.</p>
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
  const revealItems = [...founder.querySelectorAll('[data-s42-reveal]')];
  const actions = founder.querySelector('[data-s42-reveal-actions]');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const revealAnimations = [];
  let revealStarted = false;
  let revealFinished = false;
  let resolveReveal;
  let resolveTitleReveal;
  let manualRevealTimer = 0;
  let manualRevealPaused = false;
  const revealComplete = new Promise((resolve) => { resolveReveal = resolve; });
  const titleRevealComplete = new Promise((resolve) => { resolveTitleReveal = resolve; });

  function finishReveal() {
    if (revealFinished) return;
    revealFinished = true;
    revealAnimations.forEach((animation) => animation.cancel());
    revealItems.forEach((item) => item.classList.add('is-revealed'));
    actions.classList.add('is-revealed');
    resolveTitleReveal?.();
    resolveTitleReveal = null;
    founder.dataset.phase = 'move-on';
    founder.dataset.revealState = 'complete';
    resolveReveal?.();
  }

  function beginReveal(force = false) {
    if (revealFinished) return revealComplete;
    if (revealStarted || (!force && window.BooStudyGuidedTour?.isAutoMode())) return revealComplete;
    revealStarted = true;
    founder.dataset.revealState = 'revealing';
    if (prefersReducedMotion.matches) {
      finishReveal();
      return revealComplete;
    }

    revealItems.forEach((item, index) => {
      const animation = item.animate([
        { opacity: 0, transform: 'translate3d(0, 18px, 0)', clipPath: 'inset(0 0 20% 0)' },
        { opacity: 1, transform: 'translate3d(0, 0, 0)', clipPath: 'inset(0)' }
      ], {
        duration: 680,
        delay: index * 520,
        easing: 'cubic-bezier(.2,.72,.24,1)',
        fill: 'both'
      });
      animation.onfinish = () => {
        item.classList.add('is-revealed');
        if (index === 0) {
          resolveTitleReveal?.();
          resolveTitleReveal = null;
        }
        founder.dataset.phase = index < 2 ? 'read' : index < 4 ? 'watch' : index < 7 ? 'understand' : 'move-on';
      };
      revealAnimations.push(animation);
    });
    const actionsAnimation = actions.animate([
      { opacity: 0, transform: 'translate3d(0, 18px, 0)', clipPath: 'inset(0 0 20% 0)' },
      { opacity: 1, transform: 'translate3d(0, 0, 0)', clipPath: 'inset(0)' }
    ], {
      duration: 680,
      delay: revealItems.length * 520,
      easing: 'cubic-bezier(.2,.72,.24,1)',
      fill: 'both'
    });
    actionsAnimation.onfinish = finishReveal;
    revealAnimations.push(actionsAnimation);
    return revealComplete;
  }

  founder.classList.add('is-reveal-ready');
  if (prefersReducedMotion.matches) finishReveal();
  else {
    const title = founder.querySelector('#s42-founder-title');
    const titleIsSafe = () => {
      if (!title) return false;
      const rect = title.getBoundingClientRect();
      const safeTop = window.innerHeight * 0.12;
      const safeBottom = window.innerHeight * 0.82;
      return rect.width > 0 && rect.height > 0 && rect.top >= safeTop && rect.bottom <= safeBottom;
    };
    const syncManualReveal = () => {
      if (window.BooStudyGuidedTour?.isAutoMode() || revealFinished) return;
      if (!revealStarted) {
        window.clearTimeout(manualRevealTimer);
        manualRevealTimer = 0;
        if (!titleIsSafe()) return;
        manualRevealTimer = window.setTimeout(() => {
          manualRevealTimer = 0;
          if (!window.BooStudyGuidedTour?.isAutoMode() && titleIsSafe()) beginReveal();
        }, 180);
        return;
      }
      const safe = titleIsSafe();
      if (!safe && !manualRevealPaused) {
        revealAnimations.forEach((animation) => { if (animation.playState === 'running') animation.pause(); });
        manualRevealPaused = true;
      } else if (safe && manualRevealPaused) {
        revealAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); });
        manualRevealPaused = false;
      }
    };
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(() => syncManualReveal(), {
        rootMargin: '-12% 0px -18% 0px',
        threshold: [0, 0.25, 0.75]
      });
      observer.observe(title || founder);
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
    pause: () => revealAnimations.forEach((animation) => { if (animation.playState === 'running') animation.pause(); }),
    resume: () => revealAnimations.forEach((animation) => { if (animation.playState === 'paused') animation.play(); }),
    setSpeed: (speed) => revealAnimations.forEach((animation) => {
      if (animation.playState === 'idle' || animation.playState === 'finished') return;
      if (typeof animation.updatePlaybackRate === 'function') animation.updatePlaybackRate(speed);
      else animation.playbackRate = speed;
    }),
    get complete() { return revealFinished; },
    get started() { return revealStarted; },
    get promise() { return revealComplete; }
  };
})();
