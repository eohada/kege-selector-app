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
  const revealTimers = [];
  let revealStarted = false;
  let revealFinished = false;

  function finishReveal() {
    if (revealFinished) return;
    revealFinished = true;
    revealTimers.forEach(window.clearTimeout);
    revealItems.forEach((item) => item.classList.add('is-revealed'));
    actions.classList.add('is-revealed');
    founder.dataset.phase = 'move-on';
    founder.dataset.revealState = 'complete';
  }

  function beginReveal() {
    if (revealStarted) return;
    revealStarted = true;
    entryScrollY = window.scrollY;
    founder.dataset.revealState = 'revealing';
    if (prefersReducedMotion.matches) {
      finishReveal();
      return;
    }

    revealItems.forEach((item, index) => {
      revealTimers.push(window.setTimeout(() => {
        item.classList.add('is-revealed');
        founder.dataset.phase = index < 2 ? 'read' : index < 4 ? 'watch' : index < 7 ? 'understand' : 'move-on';
        if (index === revealItems.length - 1) {
          actions.classList.add('is-revealed');
          founder.dataset.revealState = 'complete';
          revealFinished = true;
        }
      }, index * 280));
    });
  }

  founder.classList.add('is-reveal-ready');
  if (prefersReducedMotion.matches) finishReveal();
  else if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      beginReveal();
      observer.disconnect();
    }, { threshold: 0.18 });
    observer.observe(founder);
  } else beginReveal();

  let entryScrollY = null;
  window.addEventListener('scroll', () => {
    if (!revealStarted || revealFinished) return;
    if (entryScrollY === null) entryScrollY = window.scrollY;
    if (Math.abs(window.scrollY - entryScrollY) >= Math.max(180, window.innerHeight * 0.18)) finishReveal();
  }, { passive: true });

  prefersReducedMotion.addEventListener?.('change', () => {
    if (prefersReducedMotion.matches) finishReveal();
  });
})();
