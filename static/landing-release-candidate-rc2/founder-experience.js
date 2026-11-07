(() => {
  const profile = document.querySelector('[data-s39-profile]');
  const legacyFinale = document.querySelector('#s39-finale');
  if (!profile || !legacyFinale || document.querySelector('[data-s42-founder]')) return;

  legacyFinale.hidden = true;
  profile.insertAdjacentHTML('afterend', `
    <section class="s42-founder-story" id="s42-founder" data-s42-founder data-phase="read" aria-label="Создатель BooStudy">
      <div class="s42-founder-pin">
        <div class="s42-bridge" aria-hidden="true"><span>ТВОЙ УЧЕБНЫЙ ПУТЬ</span><i>→</i><strong>ОПЫТ СОЗДАТЕЛЯ</strong></div>
        <div class="s42-founder-layout">
          <div class="s42-founder-copy">
            <p class="s42-eyebrow">ЗНАКОМЬСЯ, СОЗДАТЕЛЬ BOOSTUDY</p>
            <h2>Создано преподавателем. Для настоящего обучения.</h2>
            <p class="s42-founder-lead">За этой системой — опыт настоящего преподавателя.</p>
            <div class="s42-founder-story-text">
              <p>Я — создатель BooStudy и практикующий преподаватель. На индивидуальных занятиях я увидел, сколько внимания забирают разрозненные инструменты и учебная рутина.</p>
              <p>Поэтому я создаю платформу, где уроки, практика, теория и прогресс связаны между собой. Для меня важно не только найти ответ, но и научиться самостоятельно разбираться в задачах и применять знания.</p>
            </div>
            <p class="s42-founder-signature">Создатель BooStudy <span>·</span> Преподаватель <span>·</span> Разработчик образовательных инструментов</p>
            <div class="s42-founder-contact" data-s42-contact hidden aria-hidden="true">
              <p>Есть вопрос об обучении или платформе? Напиши напрямую.</p>
              <a class="s42-telegram-link" href="https://t.me/eohada" target="_blank" rel="noopener noreferrer" aria-label="Написать создателю BooStudy в Telegram, @eohada">
                <span class="s42-telegram-icon" aria-hidden="true">↗</span>
                <span>Написать мне в Telegram</span>
                <b>@eohada</b>
              </a>
            </div>
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
        <div class="s42-founder-progress" aria-hidden="true"><span>О СОЗДАТЕЛЕ</span><i><b data-s42-founder-progress></b></i></div>
      </div>
    </section>
    <section class="s42-commercial-finale" id="s42-finale" data-s42-finale aria-label="Начать обучение в BooStudy">
      <div class="s42-finale-panel">
        <div class="s42-finale-copy">
          <p class="s42-eyebrow">ТВОЙ СЛЕДУЮЩИЙ ШАГ</p>
          <h2>Твоё пространство для роста начинается здесь.</h2>
          <p>Учись, практикуйся, отслеживай прогресс и развивайся в единой образовательной среде BooStudy.</p>
        </div>
        <div class="s42-finale-actions" aria-label="Выбери следующий шаг">
          <a class="s42-register-link" href="/register">Начать обучение <b aria-hidden="true">↗</b></a>
          <a class="s42-contact-link" href="https://t.me/eohada" target="_blank" rel="noopener noreferrer">Написать создателю <span>@eohada</span></a>
        </div>
      </div>
      <div class="s42-finale-foot"><span>BooStudy</span><span>От опыта преподавания — к среде для обучения</span></div>
    </section>
  `);

  const founder = document.querySelector('[data-s42-founder]');
  const contact = founder.querySelector('[data-s42-contact]');
  const progressBar = founder.querySelector('[data-s42-founder-progress]');
  const isMobile = window.matchMedia('(max-width: 720px)');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function setFounderProgress(progress) {
    const value = Math.max(0, Math.min(1, progress));
    const phase = value < 0.22 ? 'read' : value < 0.58 ? 'watch' : value < 0.84 ? 'understand' : 'move-on';
    founder.dataset.phase = phase;
    progressBar.style.transform = `scaleX(${value})`;
    const contactVisible = prefersReducedMotion.matches || isMobile.matches || value >= 0.58;
    contact.hidden = !contactVisible;
    contact.setAttribute('aria-hidden', String(!contactVisible));
  }

  document.addEventListener('boostudy:story-progress', (event) => {
    const progress = event.detail.s42founder;
    if (typeof progress === 'number') setFounderProgress(progress);
  });
  function currentFounderProgress() {
    const top = founder.getBoundingClientRect().top + window.scrollY;
    return (window.scrollY - top) / Math.max(1, founder.offsetHeight - window.innerHeight);
  }

  setFounderProgress(currentFounderProgress());
  isMobile.addEventListener?.('change', () => setFounderProgress(currentFounderProgress()));
  prefersReducedMotion.addEventListener?.('change', () => setFounderProgress(currentFounderProgress()));
})();
