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
  const previousStandaloneFinale = document.querySelector('#s39-finale');
  if (previousStandaloneFinale) previousStandaloneFinale.hidden = true;
  document.querySelector('#s38-theory').hidden = true;
  const theory = document.querySelector('[data-s39-theory]');
  const profile = document.querySelector('[data-s39-profile]');
  const profileApp = profile.querySelector('[data-s39-profile-app]');
  profile.classList.add('s40-profile-story');
  profile.querySelector('[data-s39-profile-copy]').innerHTML = `
    <article data-s39-profile-copy-step="identity"><p class="s39-eyebrow">ТВОЙ ЛИЧНЫЙ ПРОФИЛЬ</p><h2>Замечай, как растёшь.</h2><p>Здесь собирается твоя история: занятия, маленькие победы и привычка двигаться дальше.</p></article>
    <article data-s39-profile-copy-step="xp" hidden><p class="s39-eyebrow">УРОВЕНЬ И ОПЫТ</p><h2>Каждый учебный шаг приносит опыт.</h2><p>Уровень показывает путь, а до следующего рубежа всегда виден понятный ориентир.</p></article>
    <article data-s39-profile-copy-step="achievements" hidden><p class="s39-eyebrow">КОЛЛЕКЦИЯ ДОСТИЖЕНИЙ</p><h2>Твои усилия становятся наградами.</h2><p>Шесть открытых достижений из каталога BooStudy — и у каждого своя история.</p></article>
    <article data-s39-profile-copy-step="streak" hidden><p class="s39-eyebrow">УЧЕБНЫЙ РИТМ</p><h2>Двенадцать дней — шаг за шагом.</h2><p>Серия активности показывает, как небольшие регулярные действия складываются в привычку.</p></article>
    <article data-s39-profile-copy-step="time" hidden><p class="s39-eyebrow">ВРЕМЯ НА ОБУЧЕНИЕ</p><h2>Время, вложенное в понимание.</h2><p>Завершённые уроки и отслеживаемая активность собраны в одном показателе.</p></article>
    <article data-s39-profile-copy-step="referral" hidden><p class="s39-eyebrow">УЧИТЬСЯ ВМЕСТЕ</p><h2>Делись своим приглашением.</h2><p>Персональный код и условия бонуса доступны прямо в профиле.</p></article>
    <article data-s39-profile-copy-step="telegram" hidden><p class="s39-eyebrow">TELEGRAM И УВЕДОМЛЕНИЯ</p><h2>Связь с платформой — под твоим контролем.</h2><p>Посмотри, как устроено подключение, не привязывая настоящий аккаунт.</p></article>
    <article data-s39-profile-copy-step="complete" hidden><p class="s39-eyebrow">ТВОЙ ПУТЬ В BOOSTUDY</p><h2>Каждый шаг обучения имеет значение.</h2><p>Уровень, награды и ежедневные усилия складываются в историю, которую ты создаёшь сама.</p><a class="s40-profile-cta" href="/register">Создать аккаунт <b aria-hidden="true">↗</b></a><small class="s40-copy-note">Профиль — синтетический пример; кнопка ведёт к регистрации BooStudy.</small></article>
    <div class="s39-copy-progress"><span data-s39-profile-label>Личный профиль ученика</span><i><b data-s39-profile-progress></b></i></div>`;
  profileApp.classList.add('s40-profile-app');
  profileApp.innerHTML = `
    <header class="s40-profile-header">
      <div class="s40-avatar" aria-hidden="true"><span>А</span><i></i></div>
      <div class="s40-identity"><small>УЧЕНИЦА · ПОДГОТОВКА К ЕГЭ</small><h3>Аня Морозова</h3><p>Личный профиль · данные синтетические</p><div class="s40-identity-tags"><span>Информатика</span><span>Ученический профиль</span></div></div>
      <span class="s40-level-pill" data-profile-region="level"><b>IX</b><span>УРОВЕНЬ 9</span></span>
    </header>
    <div class="s40-profile-meter"><span><i aria-hidden="true"></i>ИСТОРИЯ РАСТЁТ</span><b data-s40-stage-count>01 / 08</b><div><i data-s40-stage-meter></i></div></div>
    <div class="s40-profile-grid">
      <section class="s40-profile-card s40-intro-card" data-profile-region="identity"><div class="s40-intro-orbit" aria-hidden="true"><i></i><i></i><i></i><b><svg viewBox="0 0 24 24"><path d="m12 2 2.6 6.5L21 11l-6.4 2.5L12 20l-2.6-6.5L3 11l6.4-2.5z"/></svg></b></div><div><small>ЛИЧНОЕ ПРОСТРАНСТВО</small><h4>Мой путь в BooStudy</h4><p>Большие результаты начинаются с понятных шагов. Каждый из них остаётся частью твоей истории.</p></div><span class="s40-intro-tag">МОЙ ПРОГРЕСС</span></section>
      <section class="s40-profile-card s40-xp-card" data-profile-region="xp" aria-label="Уровень и опыт ученицы">
        <div class="s40-card-heading"><div><small>ОПЫТ И УРОВЕНЬ</small><h4>Ученик чародея</h4></div><span class="s40-xp-emblem" aria-hidden="true"><b>IX</b><i><svg viewBox="0 0 24 24"><path d="m12 2 2.6 6.5L21 11l-6.4 2.5L12 20l-2.6-6.5L3 11l6.4-2.5z"/></svg></i></span></div>
        <div class="s40-xp-total"><strong><span data-s40-xp-counter>0</span><small> XP</small></strong><span>до уровня 10 · осталось <b>45 XP</b></span></div>
        <div class="s40-xp-meter" role="img" aria-label="Прогресс уровня 9 — 73,4 процента"><i></i></div>
        <div class="s40-xp-caption"><span>Уровень 9</span><b>73,4% пути</b><span>Уровень 10</span></div>
        <div class="s40-xp-ledger" aria-label="Состав опыта"><span>Практика <b>170 XP</b></span><span>Занятия и теория <b>280 XP</b></span><span>Серия <b>60 XP</b></span><span>Достижения <b>155 XP</b></span><span>Приглашение <b>100 XP</b></span></div>
      </section>
      <section class="s40-profile-card s40-awards-card" data-profile-region="achievements" aria-label="Полученные достижения">
        <div class="s40-card-heading s40-awards-heading"><div><small>МОЯ КОЛЛЕКЦИЯ</small><h4>Достижения</h4></div><span class="s40-awards-count"><b>6</b><i>/</i>52</span></div>
        <p class="s40-awards-intro">Каждая награда отмечает конкретный шаг.</p>
        <div class="s40-awards-grid">
          <button class="s40-award" type="button" data-s40-award data-award="first-step" aria-pressed="false" aria-label="Первый шаг, первая работа на проверке, плюс 20 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="m16 3 3.7 7.5 8.3 1.2-6 5.8 1.4 8.2-7.4-3.9-7.4 3.9 1.4-8.2-6-5.8 8.3-1.2z"/></svg></span><span class="s40-award-copy"><b>Первый шаг</b><small>Первая работа на проверке</small><em>+20 XP</em></span></button>
          <button class="s40-award" type="button" data-s40-award data-award="first-pages" aria-pressed="false" aria-label="Первые страницы, прочитана первая тема, плюс 20 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 7.5c4.5-1.8 8.2-.8 11 1.4v17c-2.8-2.2-6.5-3.2-11-1.4zM27 7.5c-4.5-1.8-8.2-.8-11 1.4v17c2.8-2.2 6.5-3.2 11-1.4z"/></svg></span><span class="s40-award-copy"><b>Первые страницы</b><small>Прочитана первая тема</small><em>+20 XP</em></span></button>
          <button class="s40-award" type="button" data-s40-award data-award="first-lesson" aria-pressed="false" aria-label="Боевое крещение, завершено первое занятие, плюс 25 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 4 27 9v7c0 6.2-4.2 10-11 12C9.2 26 5 22.2 5 16V9zM11 16l3.2 3.2L21.5 12"/></svg></span><span class="s40-award-copy"><b>Боевое крещение</b><small>Завершено первое занятие</small><em>+25 XP</em></span></button>
          <button class="s40-award" type="button" data-s40-award data-award="week" aria-pressed="false" aria-label="Неделя в огне, семь активных дней подряд, плюс 35 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M18 3c1 6-5 7-3 12 1-2 3-3 5-4 4 4 6 7 5 11-1 5-5 8-10 7-6-1-9-6-7-11 1-3 4-6 5-10 2 2 3 4 3 6 2-3 3-7 2-11z"/></svg></span><span class="s40-award-copy"><b>Неделя в огне</b><small>7 активных дней подряд</small><em>+35 XP</em></span></button>
          <button class="s40-award" type="button" data-s40-award data-award="first-ten" aria-pressed="false" aria-label="Первый десяток, десять правильных решений, плюс 25 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="11"/><circle cx="16" cy="16" r="6"/><path d="m22 10 6-6"/></svg></span><span class="s40-award-copy"><b>Первый десяток</b><small>10 правильных решений</small><em>+25 XP</em></span></button>
          <button class="s40-award" type="button" data-s40-award data-award="wizard" aria-pressed="false" aria-label="Ученик чародея, достигнут пятый уровень, плюс 30 XP"><span class="s40-award-medallion"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="m7 24 16-16 3 3L10 27H7zM18 5l2-2m6 8 3-1M14 5l-1-3"/><circle cx="8.5" cy="24.5" r="1.5"/></svg></span><span class="s40-award-copy"><b>Ученик чародея</b><small>Достигнут 5 уровень</small><em>+30 XP</em></span></button>
        </div>
        <div class="s40-award-spotlight" data-s40-spotlight-note aria-live="polite">Выбери награду, чтобы рассмотреть её подробнее. Она останется на своём месте в коллекции.</div>
        <small class="s40-profile-note">В каталоге BooStudy — 52 достижения, включая тайные.</small>
      </section>
      <section class="s40-profile-card s40-streak-card" data-profile-region="streak" aria-label="Серия учебной активности">
        <div class="s40-card-heading"><div><small>РИТМ ОБУЧЕНИЯ</small><h4>Серия активности</h4></div><span class="s40-streak-badge"><b data-s40-streak-counter>0</b><small>дней</small></span></div>
        <p><strong>Активна сегодня</strong><span> · серия продолжается</span></p>
        <div class="s40-streak-days" role="img" aria-label="12 последовательных активных дней"><i>1</i><i>2</i><i>3</i><i>4</i><i>5</i><i>6</i><i>7</i><i>8</i><i>9</i><i>10</i><i>11</i><i>12</i></div>
        <small class="s40-profile-note">Серия отражает последовательные дни активности.</small>
      </section>
      <section class="s40-profile-card s40-time-card" data-profile-region="time" aria-label="Время обучения">
        <div class="s40-card-heading"><div><small>ВРЕМЯ НА ОБУЧЕНИЕ</small><h4>Вложено в знания</h4></div><span class="s40-time-total">12<small>ч</small> 40<small>мин</small></span></div>
        <div class="s40-time-split"><span><b>8 ч</b><small>завершённые уроки</small></span><i>+</i><span><b>4 ч 40 мин</b><small>отслеживаемая активность</small></span></div>
        <small class="s40-profile-note">Уроки: 8 × 60 минут. Время активности показано отдельно.</small>
      </section>
      <section class="s40-profile-card s40-referral-card" data-profile-region="referral" aria-label="Реферальная программа">
        <div class="s40-card-heading"><div><small>ПРИГЛАСИТЬ ДРУГА</small><h4>Учиться веселее вместе</h4></div><span class="s40-referral-bonus">+100 XP</span></div>
        <p>Персональный код приглашения. Бонус начисляется по правилам реферальной программы.</p>
        <div class="s40-code-row"><code>BS-ANNA07K2</code><button type="button" data-s40-copy-code aria-label="Скопировать пример реферального кода">Копировать</button></div>
        <small data-s40-copy-status aria-live="polite">Код — синтетический пример для preview.</small>
      </section>
      <section class="s40-profile-card s40-telegram-card" data-profile-region="telegram" aria-label="Telegram и уведомления">
        <div class="s40-card-heading"><div><small>СВЯЗЬ С ПРОФИЛЕМ</small><h4>Telegram и уведомления</h4></div><span class="s40-tg-status"><i></i>Не подключён</span></div>
        <p>В профиле можно подключить Telegram для уведомлений и быстрого входа в BooStudy.</p>
        <button class="s40-tg-preview-button" type="button" data-s40-telegram-preview aria-expanded="false">Посмотреть шаги подключения <b aria-hidden="true">＋</b></button>
        <ol class="s40-tg-steps" data-s40-telegram-steps hidden><li>Открыть Telegram из профиля.</li><li>Подтвердить связь одноразовым кодом.</li><li>Выбрать настройки уведомлений.</li></ol>
        <small data-s40-telegram-status aria-live="polite">Никакой запрос в Telegram не отправляется.</small>
      </section>
    </div>
    <footer class="s40-profile-footer"><span>СИНТЕТИЧЕСКАЯ ИСТОРИЯ УЧЕНИЦЫ</span><b>4 работы · 32 попытки · 22 верных ответа · 68,8%</b><a class="s40-profile-cta s40-profile-cta-mobile" data-s40-mobile-cta href="/register">Создать аккаунт <b aria-hidden="true">↗</b></a></footer>`;
  const calibrateMobileProfileRange = () => {
    if (!window.matchMedia('(max-width: 720px)').matches) {
      delete profile.dataset.s40ProgressRange;
      profile.style.removeProperty('--s40-profile-story-height');
      return;
    }
    const current = profileApp.dataset.focus;
    profileApp.dataset.focus = 'complete';
    const storyHeight = profile.offsetHeight;
    profile.dataset.s40ProgressRange = String(Math.max(1, storyHeight - window.innerHeight));
    profile.style.setProperty('--s40-profile-story-height', `${storyHeight}px`);
    profileApp.dataset.focus = current;
  };
  calibrateMobileProfileRange();
  window.addEventListener('resize', calibrateMobileProfileRange, { passive: true });
  document.fonts?.ready.then(calibrateMobileProfileRange);
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

  const profileStages = ['identity','xp','achievements','streak','time','referral','telegram','complete'];
  const profileStageThresholds = [0, 0.18, 0.36, 0.48, 0.56, 0.66, 0.75, 0.84];
  const profileLabels = ['Личный профиль ученика','Уровень и опыт','Коллекция достижений','Серия учебной активности','Время на обучение','Реферальная программа','Telegram и уведомления','Полный профиль · создать аккаунт'];
  const profileCopies = [...profile.querySelectorAll('[data-s39-profile-copy-step]')];
  let lastProfileIndex = -1;
  const countFrames = new Map();
  const animateCount = (selector, target, duration = 1100) => {
    const node = profile.querySelector(selector);
    if (!node) return;
    const previousFrame = countFrames.get(selector);
    if (previousFrame) cancelAnimationFrame(previousFrame);
    if (duration <= 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { node.textContent = String(target); countFrames.delete(selector); return; }
    const startValue = Number(node.textContent.replace(/\D/g, '')) || 0;
    const startTime = performance.now();
    const tick = (now) => {
      const linear = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - linear, 3);
      node.textContent = String(Math.round(startValue + (target - startValue) * eased));
      if (linear < 1) countFrames.set(selector, requestAnimationFrame(tick));
      else countFrames.delete(selector);
    };
    countFrames.set(selector, requestAnimationFrame(tick));
  };
  function setProfileStage(index, progress = 0) {
    const key = profileStages[Math.max(0, Math.min(profileStages.length - 1, index))];
    profile.dataset.stage = key;
    profileApp.dataset.focus = key;
    profileCopies.forEach((copy) => { const active = copy.dataset.s39ProfileCopyStep === key; copy.hidden = !active; copy.setAttribute('aria-hidden', String(!active)); });
    profile.querySelector('[data-s39-profile-label]').textContent = profileLabels[profileStages.indexOf(key)];
    profile.querySelector('[data-s39-profile-progress]').style.transform = `scaleX(${Math.max(0, Math.min(1, progress))})`;
    profile.querySelector('[data-s40-stage-count]').textContent = `${String(index + 1).padStart(2, '0')} / 08`;
    profile.querySelector('[data-s40-stage-meter]').style.transform = `scaleX(${Math.max(0, Math.min(1, progress))})`;
    if (index >= 1 && lastProfileIndex < 1) animateCount('[data-s40-xp-counter]', 765, index === 1 ? 1100 : 0);
    else if (index >= 2 && lastProfileIndex === 1) animateCount('[data-s40-xp-counter]', 765, 0);
    if (index >= 3 && lastProfileIndex < 3) animateCount('[data-s40-streak-counter]', 12, index === 3 ? 750 : 0);
    lastProfileIndex = index;
  }
  document.addEventListener('boostudy:story-progress', (event) => { const progress = event.detail.s39profile; if (typeof progress !== 'number') return; const bounded = Math.max(0, Math.min(.9999, progress)); const index = profileStageThresholds.reduce((active, threshold, stage) => bounded >= threshold ? stage : active, 0); setProfileStage(index, progress); });
  profile.querySelectorAll('[data-s40-award]').forEach((button) => button.addEventListener('click', () => {
    const award = button.dataset.award;
    const selected = profileApp.dataset.spotlight === award;
    if (selected) delete profileApp.dataset.spotlight;
    else profileApp.dataset.spotlight = award;
    profile.querySelectorAll('[data-s40-award]').forEach((item) => item.setAttribute('aria-pressed', String(!selected && item === button)));
    profile.querySelector('[data-s40-spotlight-note]').textContent = selected
      ? 'Коллекция снова собрана целиком. Выбери награду, чтобы рассмотреть её подробнее.'
      : `${button.querySelector('b').textContent} · ${button.querySelector('small').textContent} · ${button.querySelector('em').textContent}. Награда остаётся в коллекции.`;
  }));
  profile.querySelector('[data-s40-copy-code]').addEventListener('click', async () => {
    const status = profile.querySelector('[data-s40-copy-status]');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText('BS-ANNA07K2');
      status.textContent = 'Пример кода скопирован.';
    } catch {
      status.textContent = 'Код показан для ручного копирования: BS-ANNA07K2';
    }
  });
  profile.querySelector('[data-s40-telegram-preview]').addEventListener('click', (event) => {
    const button = event.currentTarget;
    const steps = profile.querySelector('[data-s40-telegram-steps]');
    const open = steps.hidden;
    steps.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.querySelector('b').textContent = open ? '−' : '＋';
    profile.querySelector('[data-s40-telegram-status]').textContent = open
      ? 'Предпросмотр шагов · подключения и сетевого запроса нет.'
      : 'Никакой запрос в Telegram не отправляется.';
  });
  setTheoryStage(0, 0);
  setProfileStage(0, 0);
})();
