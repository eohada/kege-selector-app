(() => {
  const root = {
    hero: '[data-s30-story]', homework: '[data-s38-homework]', analytics: '[data-s32-story]',
    dashboard: '[data-s36-story]', schedule: '[data-s37-story]', theory: '[data-s39-theory]',
    profile: '[data-s39-profile]', founder: '[data-s42-founder]'
  };
  const surfaceSelectors = {
    hero: '[data-s30-workspace]', homework: '.s38-homework-layout', analytics: '[data-s33-surface]',
    dashboard: '[data-dashboard-surface]', schedule: '.s37-layout', theory: '[data-s39-theory-app]',
    profile: '[data-s39-profile-app]'
  };
  const motionSelectors = {
    hero: '[data-s30-workspace]', homework: '.s38-homework-layout', analytics: '.s32-composition',
    dashboard: '.s36-story-layout', schedule: '.s37-layout', theory: '[data-s39-theory-app]',
    profile: '[data-s39-profile-app]'
  };
  const chapterTitles = {
    hero: 'BooStudy OS', homework: 'Homework OS', analytics: 'Аналитика', dashboard: 'Личный кабинет',
    schedule: 'Расписание', theory: 'Теория', profile: 'Профиль ученика', founder: 'Создатель BooStudy'
  };
  const firstInChapter = new Set();
  const demonstrationProgress = {
    hero: { typing:.375, 'math-empty':.595, 'math-write':.675, 'math-tree':.755, 'math-count':.835, 'math-formula':.915 },
    homework: { tools:.59 },
    analytics: { 'first-work':.325, trend:.55, topics:.75, tasks:.90 },
    dashboard: { continue:.265, schedule:.395, curriculum:.525, materials:.675, progress:.815 },
    schedule: { day:.255, lesson:.395, context:.535, homework:.695, free:.845 },
    theory: { library:.14, structure:.285, reading:.428, bookmark:.571, notes:.714, progress:.857 },
    profile: { identity:.17, xp:.35, achievements:.47, streak:.55, time:.65, referral:.74, telegram:.83 }
  };
  const cameraProfiles = {
    chapter: { mode: 'chapter-bridge', screensPerSecond: 0.92, minMs: 650, maxMs: 2600, density: 'low' },
    copy: { mode: 'message-change', screensPerSecond: 0.72, minMs: 420, maxMs: 1550, density: 'medium' },
    product: { mode: 'product-reveal', screensPerSecond: 0.48, minMs: 720, maxMs: 2050, density: 'high' },
    finale: { mode: 'founder-arrival', screensPerSecond: 0.68, minMs: 700, maxMs: 2100, density: 'medium' }
  };

  function stateFor(chapter, key) {
    const states = {
      hero: { selector: '[data-s30-stage]', attribute: 'data-scene' },
      homework: { selector: '[data-s38-homework]', attribute: 'data-s38-scene' },
      dashboard: { selector: '[data-s36-story]', attribute: 'data-scene' },
      schedule: { selector: '[data-s37-story]', attribute: 'data-s37-scene' },
      theory: { selector: '[data-s39-theory]', attribute: 'data-stage' },
      profile: { selector: '[data-s39-profile]', attribute: 'data-stage' }
    };
    return { ...states[chapter], value: key };
  }

  function makeBeat({ id, chapter, key, progress, headline, body, copy, camera, productCheck, attentionLoad = 'copy-and-product' }) {
    const entryInChapter = !firstInChapter.has(chapter);
    firstInChapter.add(chapter);
    const selector = copy || `[data-${chapter}-copy="${key}"]`;
    const bodySelector = chapter === 'hero' ? 'p.s30-lede'
      : chapter === 'dashboard' || chapter === 'schedule' ? 'p.s35-copy-body'
        : 'p:not(.s38-eyebrow):not(.s39-eyebrow)';
    const textTargets = chapter === 'analytics'
      ? ['[data-s32-title]', '[data-s32-description]']
      : [`${selector} h1, ${selector} h2`, `${selector} ${bodySelector}`];
    return {
      id, chapter, chapterTitle: chapterTitles[chapter], label: headline, kind: 'message', key,
      root: root[chapter], progress, copy: selector, textTargets,
      expectedHeadline: headline, expectedBody: body, expectedText: `${headline} ${body}`,
      state: chapter === 'analytics'
        ? { selector: '[data-s32-title]', text: headline }
        : stateFor(chapter, key),
      mobileSticky: chapter === 'profile',
      surface: surfaceSelectors[chapter], motionSelector: motionSelectors[chapter],
      productCheck: productCheck || null,
      demonstrateTo: demonstrationProgress[chapter]?.[key] || null,
      action: demonstrationProgress[chapter]?.[key] ? `${chapter}-scroll-driven-product-state` : null,
      attentionLoad,
      camera: cameraProfiles[camera || (entryInChapter ? 'chapter' : 'copy')]
    };
  }

  const beats = [
    ...[
      ['os-hero','hero',.025,'hero','У каждого урока своё пространство.','У каждого занятия — свои инструменты и место, чтобы спокойно разобраться в теме.','[data-s30-copy="hero"]','chapter'],
      ['os-enter','hero',.105,'enter','Твоё пространство для больших идей.','Здесь начинается урок. А как он будет выглядеть — зависит от того, что предстоит изучить.','[data-s30-copy="enter"]'],
      ['os-task','hero',.18,'task','Всё нужное — перед глазами.','Условие, код и результат рядом. Можно сосредоточиться на решении.','[data-s30-copy="task"]'],
      ['os-typing','hero',.295,'typing','Больше места для понимания.','Задача и решение остаются рядом. Весь ход работы — в поле зрения.','[data-s30-copy="typing"]','product'],
      ['os-result','hero',.415,'result','Всё нужное — перед глазами.','Условие и рабочее окно рядом: контекст не теряется, пока ищешь ответ.','[data-s30-copy="result"]',null,{selector:'[data-s30-output-result]',text:'N = 64 · R = 258'}],
      ['os-switch','hero',.485,'switch','Каждому уроку — свои инструменты.','Для программирования важен код. Для математики — пространство, где удобно объяснять и разбираться.','[data-s30-copy="switch"]'],
      ['os-math-empty','hero',.56,'math-empty','Когда мысль становится наглядной.','На доске можно выстроить каждый шаг и увидеть, как из отдельных исходов складывается ответ.','[data-s30-copy="math-empty"]'],
      ['os-math-write','hero',.645,'math-write','Каждый шаг на своём месте.','Запись и схема остаются на одной доске, рядом с условием задачи.','[data-s30-copy="math-write"]','product'],
      ['os-math-tree','hero',.72,'math-tree','Сложное проще разобрать.','Ветви собирают возможные исходы в одну ясную картину.','[data-s30-copy="math-tree"]','product'],
      ['os-math-count','hero',.80,'math-count','Важное легче увидеть.','Схема и условие остаются рядом — внимание держится на ходе решения.','[data-s30-copy="math-count"]'],
      ['os-math-formula','hero',.88,'math-formula','От наглядности — к ответу.','Три подходящих исхода из четырёх становятся понятным расчётом.','[data-s30-copy="math-formula"]','product'],
      ['os-math-done','hero',.945,'math-done','Тема собрана в одном месте.','Условие, дерево исходов и расчёт складываются в цельное объяснение.','[data-s30-copy="math-done"]',null,{selector:'[data-s30-canvas-progress]',text:'Решение завершено'}],
      ['os-outro','hero',.985,'outro','Не подстраивай урок под интерфейс. Пусть интерфейс подстраивается под урок.','Задания, код и интерактивная доска — в одном пространстве, с тем, что нужно именно сейчас.','[data-s30-copy="outro"]','product']
    ].map(([id,chapter,progress,key,headline,body,copy,camera,productCheck]) => makeBeat({id,chapter,progress,key,headline,body,copy,camera,productCheck})),

    ...[
      ['homework-arrival',.10,'arrival','Урок заканчивается. Практика продолжается.','Для самостоятельного задания открывается своя рабочая комната: условие, инструменты и ответ собраны в одном месте.'],
      ['homework-brief',.30,'brief','Задача остаётся в поле зрения.','Вкладки переводят между заданиями, а окно условия держит формулировку рядом с ходом решения.'],
      ['homework-tools',.50,'tools','Рабочее место подстраивается под задачу.','В Homework OS предусмотрены окна задания, кода, терминала, ответа и файлов. Их роли подтверждены реализацией комнаты.'],
      ['homework-draft',.70,'draft','Решение и ответ связаны с заданием.','Рабочая комната сохраняет код, ответ и файлы через маршрут домашней работы. Здесь показан синтетический черновик — без записи в платформу.'],
      ['homework-handoff',.90,'handoff','Отправка — осознанный последний шаг.','В продукте сдача доступна по состоянию задания. Preview останавливается на черновике и не отправляет работу.']
    ].map(([id,progress,key,headline,body]) => makeBeat({id,chapter:'homework',progress,key,headline,body,copy:`[data-homework-copy-scene="${key}"]`})),

    ...[
      ['analytics-pause',.02,'Пауза · занятие завершено','Каждый шаг имеет значение.','Занятие заканчивается. А история того, чему ты научился, продолжается.'],
      ['analytics-first-work',.20,'Смотрим · первая работа','Прогресс, который видно.','Проверенная работа добавляет результат в общую историю.'],
      ['analytics-trend',.43,'Читаем · динамика','Замечай, как меняется результат.','Сравнивай проверенные работы по датам, а не только по одному ответу.'],
      ['analytics-topics',.58,'Смотрим · темы','Понимай, что уже получается.','Результаты по темам помогают увидеть, какие разделы ты уже практиковал.'],
      ['analytics-tasks',.78,'Читаем · карта заданий','Отдельные задания — часть общей картины.','В карте видны попытки и точность по каждому начатому заданию.'],
      ['analytics-summary',.94,'Пауза · учебный путь','Учиться легче, когда понимаешь свой прогресс.','BooStudy помогает собрать результаты занятий в наглядную картину учебного пути.']
    ].map(([id,progress,label,headline,body],index) => makeBeat({
      id,chapter:'analytics',key:id,progress,headline,body,copy:'.s32-copy',camera:index===0?'chapter':index<5?'product':'copy',
      attentionLoad:index===3||index===4?'dense-data':'copy-and-product'
    })),

    ...[
      ['dashboard-intro',.06,'intro','Твоё обучение. Всё на своих местах.','Занятия, программа и необходимые материалы собраны в одном личном пространстве.'],
      ['dashboard-continue',.195,'continue','Продолжай с того, на чём остановился.','Нужное занятие и учебный контекст всегда под рукой.'],
      ['dashboard-schedule',.335,'schedule','Ближайшие занятия — перед глазами.','Видно, что запланировано и к чему готовиться дальше.'],
      ['dashboard-curriculum',.465,'curriculum','Понимай, куда движется твоя подготовка.','Программа помогает ориентироваться в пройденных и предстоящих темах.'],
      ['dashboard-materials',.605,'materials','Всё для занятия — под рукой.','Материалы и подготовительные шаги собраны рядом с учебным контекстом.'],
      ['dashboard-progress',.75,'progress','Важное видно сразу. Подробности — рядом.','Быстро оцени общую картину и переходи к детальным результатам, когда нужно.'],
      ['dashboard-complete',.91,'complete','Не просто личный кабинет. Твой центр обучения.','От следующего занятия до программы подготовки — всё организовано так, чтобы ты мог сосредоточиться на учёбе.']
    ].map(([id,progress,key,headline,body],index) => makeBeat({id,chapter:'dashboard',progress,key,headline,body,copy:`[data-copy-block="${key}"]`,camera:index===0?'chapter':'product',attentionLoad:index===6?'full-composition':'spotlight'})),

    ...[
      ['schedule-week',.06,'week','Вся учебная неделя — перед глазами.','Дни, занятия и сроки собраны в одном ритме. Выбери дату — и увидишь план именно на неё.',null],
      ['schedule-day',.19,'day','План меняется вместе с выбранным днём.','Нажатие на день в недельной ленте действительно переключает список событий и свободное состояние.',{selector:'[data-s37-day-title]',text:'Четверг, 5 ноября'}],
      ['schedule-lesson',.33,'lesson','Ещё до урока понятно, что тебя ждёт.','Тема, время, преподаватель и статус собраны в карточке занятия — вместе с доступным переходом в комнату.',{selector:'[data-s37-day-title]',text:'Четверг, 5 ноября'}],
      ['schedule-context',.47,'context','Контекст урока остаётся рядом.','Материалы и заметка, связанные с занятием, остаются в его карточке.',{selector:'[data-s37-day-title]',text:'Четверг, 5 ноября'}],
      ['schedule-homework',.62,'homework','Статус и срок видны без лишних поисков.','Назначенное задание занимает компактное место в расписании дня. Здесь показаны только существующие статусы сдачи.',{selector:'[data-s37-day-title]',text:'Пятница, 6 ноября'}],
      ['schedule-free',.775,'free','Понятный план есть и без занятий.','Если событий нет, ученик видит спокойное пустое состояние — день свободен от обязательных уроков.',{selector:'[data-s37-day-title]',text:'Воскресенье, 8 ноября'}],
      ['schedule-overview',.93,'overview','А дальше — твой учебный ритм.','Расписание соединяет занятия и сроки недели — от общего плана до следующего шага.',{selector:'[data-s37-day-title]',text:'Среда, 4 ноября'}]
    ].map(([id,progress,key,headline,body,productCheck],index) => makeBeat({id,chapter:'schedule',progress,key,headline,body,copy:`[data-s37-copy-block="${key}"]`,productCheck,camera:index===0?'chapter':'product'})),

    ...[
      ['theory-library',.071,'library','Теория — в одном понятном месте.','Темы и учебные материалы собраны в библиотеке ученика.'],
      ['theory-structure',.214,'structure','Каждая тема — по полочкам.','Внутри материала легко найти нужный раздел и вернуться к нему.'],
      ['theory-reading',.357,'reading','Ничего лишнего между тобой и пониманием.','Короткие смысловые блоки, примеры и пояснения помогают держать нить.'],
      ['theory-bookmark',.50,'bookmark','Закладка остаётся рядом.','Отметь материал и найди его в своём списке сохранённого.'],
      ['theory-notes',.643,'notes','Твои мысли остаются рядом с материалом.','Запиши короткую мысль к теме и вернись к ней во время повторения.'],
      ['theory-progress',.786,'progress','Продолжай с того места, где остановился.','Процент чтения и последняя позиция сохраняются в состоянии ученика.'],
      ['theory-check',.929,'check','Попробуешь закрепить тему?','Можно ответить на вопрос из блока №103 или продолжить без ответа.']
    ].map(([id,progress,key,headline,body],index) => makeBeat({id,chapter:'theory',progress,key,headline,body,copy:`[data-s39-theory-copy-step="${key}"]`,camera:index===0?'chapter':key==='notes'?'product':'copy',attentionLoad:key==='reading'?'dense-material':'copy-and-product'})),

    ...[
      ['profile-identity',.09,'identity','Замечай, как растёшь.','Здесь собирается твоя история: занятия, маленькие победы и привычка двигаться дальше.'],
      ['profile-xp',.25,'xp','Каждый учебный шаг приносит опыт.','Уровень показывает путь, а до следующего рубежа всегда виден понятный ориентир.',{selector:'[data-s40-xp-counter]',text:'765'}],
      ['profile-achievements',.42,'achievements','Твои усилия становятся наградами.','Шесть открытых достижений из каталога BooStudy — и у каждого своя история.'],
      ['profile-streak',.52,'streak','Двенадцать дней — шаг за шагом.','Серия активности показывает, как небольшие регулярные действия складываются в привычку.',{selector:'[data-s40-streak-counter]',text:'12'}],
      ['profile-time',.61,'time','Время, вложенное в понимание.','Завершённые уроки и отслеживаемая активность собраны в одном показателе.'],
      ['profile-referral',.70,'referral','Делись своим приглашением.','Персональный код и условия бонуса доступны прямо в профиле.'],
      ['profile-telegram',.80,'telegram','Связь с платформой — под твоим контролем.','Посмотри, как устроено подключение, не привязывая настоящий аккаунт.'],
      ['profile-complete',.92,'complete','Каждый шаг обучения имеет значение.','Уровень, награды и ежедневные усилия складываются в историю, которую ты создаёшь сама.']
    ].map(([id,progress,key,headline,body,productCheck],index) => makeBeat({id,chapter:'profile',progress,key,headline,body,copy:`[data-s39-profile-copy-step="${key}"]`,productCheck,camera:index===0?'chapter':key==='achievements'?'product':'copy',attentionLoad:key==='complete'?'full-composition':'copy-and-product'})),

    {
      id:'founder-story', chapter:'founder', chapterTitle:chapterTitles.founder, label:'Личная история и приглашение', kind:'founder',
      root:root.founder, section:true, copy:'.s42-founder-copy', textTargets:['#s42-founder-title'],
      expectedHeadline:'Создано преподавателем. Для настоящего обучения.', expectedText:'Создано преподавателем. Для настоящего обучения.',
      state:{selector:'[data-s42-founder]',attribute:'data-reveal-state',value:'pending'},
      surface:'.s42-founder-layout', camera:cameraProfiles.finale,
      subbeats:[
        {id:'founder-title',target:'#s42-founder-title',text:'Создано преподавателем. Для настоящего обучения.'},
        {id:'founder-proof',target:'.s42-founder-lead',text:'За этой системой — опыт настоящего преподавателя.'},
        {id:'founder-story-1',target:'[data-typewriter]',block:0,text:'Я — создатель BooStudy и практикующий преподаватель. На индивидуальных занятиях я увидел, сколько внимания забирают разрозненные инструменты и учебная рутина.'},
        {id:'founder-story-2',target:'[data-typewriter]',block:1,text:'Поэтому я создаю платформу, где уроки, практика, теория и прогресс связаны между собой. Для меня важно не только найти ответ, но и научиться самостоятельно разбираться в задачах и применять знания.'},
        {id:'founder-invitation',target:'#s42-invitation-title',block:2,text:'Давай обсудим твоё обучение.'},
        {id:'founder-cta',target:'.s42-invitation-copy',block:3,text:'Расскажи, чему хочешь научиться, какие цели перед собой ставишь и что сейчас вызывает трудности. Мы сможем вместе обсудить твои задачи, подход к обучению и то, как BooStudy может в этом помочь. Напиши мне напрямую — буду рад познакомиться и ответить на вопросы.'}
      ]
    }
  ];

  window.BooStudyNarrativeBeats = Object.freeze({
    version:'RC3.4', beats, attentionStateCount:beats.reduce((sum, beat) => sum + (beat.subbeats?.length || 1), 0),
    reading:{wordsPerMinute:165,minimumMs:2400,punctuationMsPerMark:80,minimumStableVisibilityMs:160},
    visibility:{minimumOpacity:.985,minimumVisibleFraction:.97,minimumUnoccludedSamples:.84}
  });
})();
