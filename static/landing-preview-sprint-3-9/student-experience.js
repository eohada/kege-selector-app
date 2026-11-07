(() => {
  const oldFinale = document.querySelector('#s38-finale');
  if (!oldFinale || document.querySelector('[data-s39-theory]')) return;
  const markup = `
  <section class="s39-story s39-theory" id="s39-theory" data-s39-theory aria-label="Система изучения теории BooStudy">
    <div class="s39-track" aria-hidden="true"><div></div><div></div><div></div><div></div><div></div><div></div><div></div></div>
    <div class="s39-pin"><div class="s39-bridge"><span>ТВОЯ ПРОГРАММА</span><i>→</i><strong>БИБЛИОТЕКА ТЕОРИИ</strong></div><div class="s39-layout">
      <div class="s39-copy" data-s39-theory-copy aria-live="polite" aria-atomic="true">
        <article data-s39-theory-copy-step="library"><p class="s39-eyebrow">ЗНАНИЯ ВСЕГДА ПОД РУКОЙ</p><h2>Теория — в одном понятном месте.</h2><p>Темы и учебные материалы собраны в библиотеке ученика.</p></article>
        <article data-s39-theory-copy-step="structure" hidden><p class="s39-eyebrow">ТЕМА СОБРАНА ПО ЧАСТЯМ</p><h2>Каждая тема — по полочкам.</h2><p>Внутри материала легко найти нужный раздел и вернуться к нему.</p></article>
        <article data-s39-theory-copy-step="reading" hidden><p class="s39-eyebrow">УДОБНО ЧИТАТЬ</p><h2>Ничего лишнего между тобой и пониманием.</h2><p>Короткие смысловые блоки, примеры и пояснения помогают держать нить.</p></article>
        <article data-s39-theory-copy-step="bookmark" hidden><p class="s39-eyebrow">СОХРАНИТЬ ВАЖНОЕ</p><h2>Закладка остаётся рядом.</h2><p>Отметь материал и найди его в своём списке сохранённого.</p></article>
        <article data-s39-theory-copy-step="notes" hidden><p class="s39-eyebrow">ЛИЧНЫЕ ЗАМЕТКИ</p><h2>Твои мысли остаются рядом с материалом.</h2><p>Запиши короткую мысль к теме и вернись к ней во время повторения.</p></article>
        <article data-s39-theory-copy-step="progress" hidden><p class="s39-eyebrow">ТВОЙ УЧЕБНЫЙ ПРОГРЕСС</p><h2>Продолжай с того места, где остановился.</h2><p>Процент чтения и последняя позиция сохраняются в состоянии ученика.</p></article>
        <article data-s39-theory-copy-step="check" hidden><p class="s39-eyebrow">НЕОБЯЗАТЕЛЬНАЯ МИКРОПРОВЕРКА</p><h2>Попробуешь закрепить тему?</h2><p>Можно ответить на вопрос из блока №103 или продолжить без ответа.</p></article>
        <div class="s39-copy-progress"><span data-s39-theory-label>Библиотека материалов</span><i><b data-s39-theory-progress></b></i></div>
      </div>
      <div class="s39-frame"><header class="s39-frame-head"><span class="s39-mark">B</span><strong>BooStudy · Теория</strong><span class="s39-demo">ПРЕЗЕНТАЦИОННАЯ РЕКОНСТРУКЦИЯ</span></header>
        <div class="s39-app s39-theory-app" data-s39-theory-app data-focus="library">
          <header class="s39-app-heading"><div><small>БИБЛИОТЕКА УЧЕНИКА · ИНФОРМАТИКА</small><h3>Теория и материалы</h3></div><span class="s39-course-chip">ЕГЭ · 2026</span></header>
          <div class="s39-theory-columns"><aside class="s39-library" aria-label="Разделы теории"><div class="s39-library-title">Мои материалы <span>12</span></div><button type="button" data-s39-library-item aria-pressed="true"><i>01</i><span><b>Условия в Python</b><small>Блок №103 · 8 минут</small></span></button><button type="button" data-s39-library-item aria-pressed="false"><i>02</i><span><b>Кодирование данных</b><small>Тема · 4 материала</small></span></button><button type="button" data-s39-library-item aria-pressed="false"><i>03</i><span><b>Алгоритмы</b><small>Раздел программы</small></span></button><div class="s39-library-saved"><span>☆</span><div><b>Закладки</b><small data-s39-saved-count>1 сохранённый материал</small></div></div></aside>
            <div class="s39-theory-panel">
              <section class="s39-theory-view" data-s39-theory-view="library"><div class="s39-view-kicker">ПРОДОЛЖИТЬ ИЗУЧЕНИЕ</div><article class="s39-material-card"><div class="s39-material-icon">103</div><div><span>ИНФОРМАТИКА · PYTHON</span><h4>Условия</h4><p>Правила, примеры кода и короткие проверки в одном материале.</p></div><b>8 мин</b></article><div class="s39-topic-list"><div class="s39-list-head"><b>Твои темы</b><span>Учебная программа</span></div><button type="button" data-s39-open-reading><span>01</span><b>Условия и ветвления</b><small>Материал доступен</small><i>↗</i></button><button type="button" data-s39-open-reading><span>02</span><b>Границы и сравнения</b><small>Часть блока №103</small><i>↗</i></button><button type="button" data-s39-open-reading><span>03</span><b>Логические выражения</b><small>Часть блока №103</small><i>↗</i></button></div></section>
              <section class="s39-theory-view" data-s39-theory-view="structure" hidden><div class="s39-view-kicker">МАРШРУТ ПО МАТЕРИАЛУ</div><h4>Условия</h4><p>Структура помогает быстро перейти к нужному смыслу.</p><ol class="s39-outline"><li><b>01</b><span>Что проверяет условие</span><i>2 мин</i></li><li><b>02</b><span>Пример из материала</span><i>3 мин</i></li><li><b>03</b><span>Границы и сравнения</span><i>2 мин</i></li><li><b>04</b><span>Короткая проверка</span><i>1 мин</i></li></ol><p class="s39-state-note">Блок №103 · демонстрационный учебный материал.</p></section>
              <section class="s39-theory-view" data-s39-theory-view="reading" hidden><div class="s39-reading-head"><div><span>БЛОК 103 · УСЛОВИЯ</span><small>РАЗДЕЛ 02 ИЗ 04</small></div><button type="button" class="s39-bookmark" data-s39-bookmark aria-pressed="false">☆ <span>В закладки</span></button></div><h4>Пример рядом с объяснением</h4><p>В материале условие показано через небольшой фрагмент кода и разобрано на примере.</p><pre><code>if score &gt;= 60: · print('зачёт') · else: · print('повторить')</code></pre><div class="s39-reading-callout"><b>Пояснение</b><span>Отступы связывают команды с выбранной веткой.</span></div><div class="s39-reading-bottom"><span>← Предыдущий раздел</span><button type="button" data-s39-next-reading>Следующий раздел →</button></div></section>
              <section class="s39-theory-view" data-s39-theory-view="bookmark" hidden><div class="s39-view-kicker">МОИ ЗАКЛАДКИ</div><h4>Сохранённое — в одном списке.</h4><article class="s39-saved-card"><span>★</span><div><small>ИНФОРМАТИКА · БЛОК 103</small><b>Условия</b><p>Тема добавлена в закладки в этом preview.</p></div><button type="button" data-s39-return-reading>Открыть</button></article></section>
              <section class="s39-theory-view" data-s39-theory-view="notes" hidden><div class="s39-view-kicker">МОЯ ЗАМЕТКА · БЛОК 103</div><h4>Запомнить свою мысль.</h4><label class="s39-note-label" for="s39-note-input">Заметка к теме</label><textarea id="s39-note-input" data-s39-note-input maxlength="160" placeholder="Например: проверить крайние значения до запуска"></textarea><div class="s39-note-actions"><small>Состояние хранится только в этой вкладке preview.</small><button type="button" data-s39-save-note>Сохранить заметку</button></div><p class="s39-note-status" data-s39-note-status aria-live="polite">Здесь появится твоя короткая заметка.</p></section>
              <section class="s39-theory-view" data-s39-theory-view="progress" hidden><div class="s39-view-kicker">ТВОЙ ПРОГРЕСС ЧТЕНИЯ</div><h4>Путь по теме сохранён.</h4><div class="s39-progress-card"><div class="s39-progress-line"><span>Блок №103 · Условия</span><b>78%</b></div><div class="s39-progress-track"><i></i></div><p>Последняя позиция: «Пример рядом с объяснением»</p><button type="button" data-s39-resume>Продолжить с этой позиции</button></div><p class="s39-state-note">StudentTheoryState хранит процент чтения и последнюю позицию; состояние на экране синтетическое.</p></section>
              <section class="s39-theory-view" data-s39-theory-view="check" hidden><div class="s39-check-invite" data-s39-check-invite><span>МИКРОПРОВЕРКА В БЛОКЕ 103</span><h4>Хочешь проверить, как понял тему?</h4><p>Один короткий ответ. Можно пропустить и продолжить чтение.</p><div><button type="button" data-s39-check-try>Попробовать</button><button type="button" data-s39-check-skip>Продолжить без ответа</button></div></div><div class="s39-check-question" data-s39-check-question hidden><span>ВОПРОС ИЗ МАТЕРИАЛА · ЛОКАЛЬНЫЙ PREVIEW</span><h4>Какой оператор сравнивает два значения?</h4><div role="group" aria-label="Вариант ответа"><button type="button" data-s39-answer="=">=</button><button type="button" data-s39-answer="==">==</button><button type="button" data-s39-answer="!=">!=</button></div><p data-s39-check-feedback aria-live="polite">Выбери вариант, если хочешь ответить.</p><button type="button" data-s39-check-skip>Продолжить без ответа</button></div></section>
            </div>
          </div>
          <footer class="s39-app-foot"><span data-s39-theory-foot>Материал теории · состояние preview локальное</span><button type="button" data-s39-theory-continue hidden>Продолжить знакомство →</button></footer>
        </div>
      </div>
    </div></div>
  </section>
  <section class="s39-story s39-profile" id="s39-profile" data-s39-profile aria-label="Личный профиль и достижения ученика">
    <div class="s39-track" aria-hidden="true"><div></div><div></div><div></div><div></div><div></div><div></div><div></div></div>
    <div class="s39-pin"><div class="s39-bridge"><span>ЗНАНИЯ И ОПЫТ</span><i>→</i><strong>ТВОЙ ЛИЧНЫЙ ПУТЬ</strong></div><div class="s39-layout">
      <div class="s39-copy" data-s39-profile-copy aria-live="polite" aria-atomic="true">
        <article data-s39-profile-copy-step="overview"><p class="s39-eyebrow">ПРОФИЛЬ УЧЕНИКА</p><h2>Замечай, как растёшь.</h2><p>Достижения, привычки и результаты собраны вокруг личного прогресса.</p></article>
        <article data-s39-profile-copy-step="achievements" hidden><p class="s39-eyebrow">ТВОИ ДОСТИЖЕНИЯ</p><h2>Каждое достижение — часть твоей истории.</h2><p>Открытые и ближайшие цели помогают видеть следующий шаг.</p></article>
        <article data-s39-profile-copy-step="streak" hidden><p class="s39-eyebrow">УЧЕБНАЯ СЕРИЯ</p><h2>Небольшой шаг сегодня поддерживает привычку.</h2><p>Активный стрик отражает последовательные дни учебной активности.</p></article>
        <article data-s39-profile-copy-step="time" hidden><p class="s39-eyebrow">ВРЕМЯ НА ОБУЧЕНИЕ</p><h2>Учебное время складывается в заметный путь.</h2><p>Учитываются завершённые уроки и отслеживаемое время на платформе.</p></article>
        <article data-s39-profile-copy-step="xp" hidden><p class="s39-eyebrow">XP И УРОВЕНЬ</p><h2>Опыт превращается в следующий уровень.</h2><p>Видно, за какие учебные действия начисляется опыт и сколько осталось до рубежа.</p></article>
        <article data-s39-profile-copy-step="referral" hidden><p class="s39-eyebrow">ПРИГЛАСИТЬ ДРУГА</p><h2>Делись приглашением и учись вместе.</h2><p>Персональный код связывает регистрацию друга с бонусом в XP.</p></article>
        <article data-s39-profile-copy-step="telegram" hidden><p class="s39-eyebrow">TELEGRAM И УВЕДОМЛЕНИЯ</p><h2>Связь с платформой — в твоих руках.</h2><p>Статус, подключение и настройки уведомлений доступны из профиля.</p></article>
        <div class="s39-copy-progress"><span data-s39-profile-label>Личный профиль ученика</span><i><b data-s39-profile-progress></b></i></div>
      </div>
      <div class="s39-frame s39-profile-frame"><header class="s39-frame-head"><span class="s39-mark">B</span><strong>BooStudy · Мой профиль</strong><span class="s39-demo">СИНТЕТИЧЕСКИЙ ПРИМЕР</span></header>
        <div class="s39-profile-app" data-s39-profile-app data-focus="overview">
          <header class="s39-profile-header"><div class="s39-avatar" aria-hidden="true">А</div><div><small>УЧЕНИК · ПОДГОТОВКА К ЕГЭ</small><h3>Аня Морозова</h3><p>Профиль и прогресс · данные синтетические</p></div><span class="s39-level-pill" data-profile-region="level">УРОВЕНЬ 9</span></header>
          <div class="s39-profile-grid">
            <section class="s39-profile-card s39-achievements" data-profile-region="achievements"><div class="s39-card-top"><div><small>КОЛЛЕКЦИЯ ДОСТИЖЕНИЙ</small><h4>Твои шаги уже отмечены</h4></div><b>6 / 52</b></div><div class="s39-achievement-list"><article><i>1</i><span><b>Первый шаг</b><small>Первая работа на проверке</small></span><em>+20 XP</em></article><article><i>2</i><span><b>Первые страницы</b><small>Прочитана первая тема</small></span><em>+20 XP</em></article><article><i>3</i><span><b>Боевое крещение</b><small>Завершено первое занятие</small></span><em>+25 XP</em></article><article><i>4</i><span><b>Неделя в огне</b><small>7 активных дней подряд</small></span><em>+35 XP</em></article><article><i>5</i><span><b>Первый десяток</b><small>10 правильных решений</small></span><em>+25 XP</em></article><article><i>6</i><span><b>Ученик чародея</b><small>Достигнут 5 уровень</small></span><em>+30 XP</em></article></div><p class="s39-card-note">Каталог платформы включает 52 достижения, в том числе тайные.</p></section>
            <section class="s39-profile-card s39-streak-card" data-profile-region="streak"><div class="s39-card-top"><div><small>СЕРИЯ УЧЕБНОЙ АКТИВНОСТИ</small><h4>Ритм, который ты создала</h4></div><b class="s39-flame">12</b></div><p><strong>12 дней подряд</strong> · активна сегодня</p><div class="s39-week-dots"><i>ПН</i><i>ВТ</i><i>СР</i><i>ЧТ</i><i>ПТ</i><i>СБ</i><i>ВС</i></div><small class="s39-card-note">Серия жива при активности сегодня или вчера; заморозка может защитить пропуск.</small></section>
            <section class="s39-profile-card s39-learning-time" data-profile-region="time"><div class="s39-card-top"><div><small>ВРЕМЯ НА ОБУЧЕНИЕ</small><h4>Каждый час имеет значение</h4></div><b>12 ч 40 мин</b></div><div class="s39-time-split"><span><b>8 ч</b><small>8 завершённых уроков × 60 мин</small></span><i>+</i><span><b>4 ч 40 мин</b><small>учёт активности на платформе</small></span></div><small class="s39-card-note">Сумма включает длительность завершённых уроков и отслеживаемое время.</small></section>
            <section class="s39-profile-card s39-xp-card" data-profile-region="xp"><div class="s39-card-top"><div><small>ОПЫТ И УРОВЕНЬ</small><h4>Ученик чародея</h4></div><b>765 XP</b></div><div class="s39-level-row"><span>Уровень 9</span><span>до уровня 10 · 45 XP</span></div><div class="s39-level-track"><i></i></div><div class="s39-xp-ledger"><span>4 работы × 15 XP <b>60</b></span><span>22 верных ответа × 5 XP <b>110</b></span><span>8 уроков × 30 XP <b>240</b></span><span>4 прочитанные темы × 10 XP <b>40</b></span><span>12 дней серии × 5 XP <b>60</b></span><span>6 достижений <b>155</b></span><span>1 приглашённый ученик <b>100</b></span><strong>Всего <b>765 XP</b></strong></div></section>
            <section class="s39-profile-card s39-referral-card" data-profile-region="referral"><div class="s39-card-top"><div><small>ПРИГЛАСИТЬ ДРУГА</small><h4>Учиться веселее вместе</h4></div><b>+100 XP</b></div><p>Один ученик зарегистрировался по персональному коду в синтетическом примере.</p><div class="s39-code-row"><code>BS-ANNA07K2</code><span>Код · пример</span></div><small>За применение кода: +100 XP пригласившему и +50 XP новому ученику.</small></section>
            <section class="s39-profile-card s39-telegram-card" data-profile-region="telegram"><div class="s39-card-top"><div><small>TELEGRAM · СВЯЗЬ С ПРОФИЛЕМ</small><h4>Настройки под контролем</h4></div><b>Не подключён</b></div><p>Привязка проходит через одноразовый код профиля. Здесь показаны шаги без реального подключения.</p><div class="s39-telegram-actions"><button type="button" data-s39-telegram-preview>Посмотреть шаги подключения</button><span data-s39-telegram-status aria-live="polite">Пример · Telegram не связан</span></div></section>
          </div>
          <footer class="s39-profile-foot">Итоги аналитики согласованы: 4 работы · 32 попытки · 22 верных ответа · 68,8%.</footer>
        </div>
      </div>
    </div></div>
  </section>
  <section class="s39-finale" id="s39-finale" aria-label="Финал знакомства с BooStudy"><div class="s39-finale-content"><p class="s39-eyebrow">ОДНА ПЛАТФОРМА · ТВОЙ ПОЛНЫЙ ПУТЬ</p><h2>Каждый шаг обучения имеет значение.</h2><p>Занятия, практика, теория и личный прогресс складываются в твой собственный маршрут.</p><div class="s39-journey"><span>Урок</span><i>→</i><span>Практика</span><i>→</i><span>Теория</span><i>→</i><span>Твой прогресс</span></div><a class="s39-final-cta" href="/register">Создать аккаунт <b aria-hidden="true">↗</b></a><small>Профиль — синтетическая реконструкция. Регистрация откроет реальную страницу BooStudy.</small></div><aside class="s39-finale-profile" aria-label="Профиль ученицы остаётся рядом"><div class="s39-finale-user"><span class="s39-avatar" aria-hidden="true">А</span><span><small>ТВОЙ ПРОГРЕСС</small><b>Аня Морозова</b></span><strong>Ур. 9</strong></div><div class="s39-finale-stats"><span><b>765</b><small>XP</small></span><span><b>12</b><small>дней подряд</small></span><span><b>6</b><small>достижений</small></span></div><div class="s39-finale-quote">«Большой путь начинается с одного понятного шага»</div></aside></section>`;

  oldFinale.insertAdjacentHTML('beforebegin', markup);
  oldFinale.hidden = true;
  document.querySelector('#s38-theory').hidden = true;
  const theory = document.querySelector('[data-s39-theory]');
  const profile = document.querySelector('[data-s39-profile]');
  const labels = ['Библиотека материалов','Структура темы','Комфортное чтение','Закладки','Личные заметки','Позиция и прогресс','Микропроверка по желанию'];
  const stages = ['library','structure','reading','bookmark','notes','progress','check'];
  const theoryCopies = [...theory.querySelectorAll('[data-s39-theory-copy-step]')];
  const theoryViews = [...theory.querySelectorAll('[data-s39-theory-view]')];
  const theoryApp = theory.querySelector('[data-s39-theory-app]');
  const theoryNoteInput = theory.querySelector('[data-s39-note-input]');
  let theoryLock = null;
  let bookmarkSaved = false;
  let checkDone = false;

  function setTheoryStage(index, progress = 0) {
    const key = stages[Math.max(0, Math.min(stages.length - 1, index))];
    theory.dataset.stage = key;
    theoryApp.dataset.focus = key;
    theoryCopies.forEach((copy) => { const active = copy.dataset.s39TheoryCopyStep === key; copy.hidden = !active; copy.setAttribute('aria-hidden', String(!active)); });
    theoryViews.forEach((view) => { const active = view.dataset.s39TheoryView === key; view.hidden = !active; view.setAttribute('aria-hidden', String(!active)); });
    theory.querySelector('[data-s39-theory-label]').textContent = labels[stages.indexOf(key)];
    theory.querySelector('[data-s39-theory-progress]').style.transform = `scaleX(${Math.max(0, Math.min(1, progress))})`;
    theory.querySelector('[data-s39-theory-foot]').textContent = key === 'check' ? 'Вопрос добровольный · ответ не отправляется' : 'Материал теории · состояние preview локальное';
  }
  document.addEventListener('boostudy:story-progress', (event) => {
    const progress = event.detail.s39theory;
    if (typeof progress !== 'number') return;
    const bounded = Math.max(0, Math.min(.9999, progress));
    const index = Math.min(stages.length - 1, Math.floor(bounded * stages.length));
    if (theoryLock === stages[index] || document.activeElement === theoryNoteInput) return;
    theoryLock = null;
    setTheoryStage(index, progress);
  });
  const lockTheory = () => { theoryLock = theory.dataset.stage; };
  theoryNoteInput.addEventListener('focus', lockTheory);
  theory.querySelectorAll('[data-s39-library-item]').forEach((button) => button.addEventListener('click', () => { lockTheory(); theory.querySelectorAll('[data-s39-library-item]').forEach((item) => item.setAttribute('aria-pressed', String(item === button))); }));
  theory.querySelectorAll('[data-s39-open-reading], [data-s39-next-reading], [data-s39-return-reading], [data-s39-resume]').forEach((button) => button.addEventListener('click', () => { lockTheory(); const view = button.hasAttribute('data-s39-resume') ? 'progress' : 'reading'; theoryApp.dataset.focus = view; theoryViews.forEach((item) => { item.hidden = item.dataset.s39TheoryView !== view; item.setAttribute('aria-hidden', String(item.dataset.s39TheoryView !== view)); }); }));
  theory.querySelector('[data-s39-bookmark]').addEventListener('click', (event) => { lockTheory(); bookmarkSaved = !bookmarkSaved; const button = event.currentTarget; button.setAttribute('aria-pressed', String(bookmarkSaved)); button.innerHTML = bookmarkSaved ? '★ <span>В закладках</span>' : '☆ <span>В закладки</span>'; theory.querySelector('[data-s39-saved-count]').textContent = bookmarkSaved ? '2 сохранённых материала' : '1 сохранённый материал'; theory.querySelector('.s39-saved-card p').textContent = bookmarkSaved ? 'Материал добавлен в закладки в этом preview.' : 'Показана исходная синтетическая закладка preview.'; });
  theory.querySelector('[data-s39-save-note]').addEventListener('click', () => { lockTheory(); const note = theoryNoteInput.value.trim(); theory.querySelector('[data-s39-note-status]').textContent = note ? `Сохранено в этой вкладке: «${note}»` : 'Добавь короткую заметку перед сохранением.'; });
  theory.querySelector('[data-s39-check-try]').addEventListener('click', () => { lockTheory(); theory.querySelector('[data-s39-check-invite]').hidden = true; theory.querySelector('[data-s39-check-question]').hidden = false; theory.querySelector('[data-s39-answer]').focus({ preventScroll: true }); });
  theory.querySelectorAll('[data-s39-check-skip]').forEach((button) => button.addEventListener('click', () => { lockTheory(); checkDone = true; theory.querySelector('[data-s39-check-feedback]').textContent = 'Пропуск принят. Можно продолжить без ответа.'; theory.querySelector('[data-s39-check-invite] p').textContent = 'Пропуск принят. Ничего не отправлено — можешь продолжить знакомство.'; theory.querySelector('[data-s39-theory-continue]').hidden = false; theory.querySelector('[data-s39-theory-continue]').focus({ preventScroll: true }); }));
  theory.querySelectorAll('[data-s39-answer]').forEach((button) => button.addEventListener('click', () => { lockTheory(); const correct = button.dataset.s39Answer === '=='; theory.querySelector('[data-s39-check-feedback]').textContent = correct ? 'Верно: == сравнивает значения. Результат останется только в этом preview.' : 'Это другой оператор. Можно попробовать ещё раз или продолжить без ответа.'; theory.querySelector('[data-s39-check-feedback]').dataset.result = correct ? 'correct' : 'wrong'; if (correct) { checkDone = true; theory.querySelector('[data-s39-theory-continue]').hidden = false; } }));
  theory.querySelector('[data-s39-theory-continue]').addEventListener('click', () => { lockTheory(); theory.querySelector('[data-s39-theory-foot]').textContent = checkDone ? 'Спасибо · продолжай знакомство' : 'Продолжение доступно без ответа'; });

  const profileStages = ['overview','achievements','streak','time','xp','referral','telegram'];
  const profileLabels = ['Личный профиль ученика','Достижения и цели','Активная серия','Время на обучение','Опыт и уровень','Приглашения','Telegram и уведомления'];
  const profileCopies = [...profile.querySelectorAll('[data-s39-profile-copy-step]')];
  function setProfileStage(index, progress = 0) {
    const key = profileStages[Math.max(0, Math.min(profileStages.length - 1, index))];
    profile.dataset.stage = key;
    profile.querySelector('[data-s39-profile-app]').dataset.focus = key;
    profileCopies.forEach((copy) => { const active = copy.dataset.s39ProfileCopyStep === key; copy.hidden = !active; copy.setAttribute('aria-hidden', String(!active)); });
    profile.querySelector('[data-s39-profile-label]').textContent = profileLabels[profileStages.indexOf(key)];
    profile.querySelector('[data-s39-profile-progress]').style.transform = `scaleX(${Math.max(0, Math.min(1, progress))})`;
  }
  document.addEventListener('boostudy:story-progress', (event) => { const progress = event.detail.s39profile; if (typeof progress !== 'number') return; const bounded = Math.max(0, Math.min(.9999, progress)); setProfileStage(Math.min(profileStages.length - 1, Math.floor(bounded * profileStages.length)), progress); });
  profile.querySelector('[data-s39-telegram-preview]').addEventListener('click', () => { profile.querySelector('[data-s39-telegram-status]').textContent = 'Preview: профиль → одноразовый код → подтверждение в боте. Подключение не запускалось.'; });
  setTheoryStage(0, 0);
  setProfileStage(0, 0);
})();
