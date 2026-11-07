(() => {
  const story = document.querySelector('[data-s32-story]');
  if (!story) return;

  const TASKS = [
    'Графы. Поиск путей', 'Таблицы истинности', 'Базы данных (Excel/SQL)', 'Кодирование (Фано)',
    'Алгоритмы для исполнителей', 'Циклы и Черепаха', 'Кодирование изображений/звука', 'Комбинаторика (слова)',
    'Электронные таблицы (сложные условия)', 'Поиск в тексте (Word)', 'Количество информации (пароли)',
    'Алгоритмы для исполнителей (строки)', 'IP-адресация и маски', 'Системы счисления', 'Алгебра логики (преобразования)',
    'Рекурсия', 'Обработка последовательностей', 'Динамическое программирование (робот)', 'Теория игр (1 ход)',
    'Теория игр (2 хода)', 'Теория игр (анализ)', 'Многопоточность (Excel/Python)', 'Динамическое программирование (кол-во путей)',
    'Обработка символьных строк', 'Теория чисел (делители/маски)', 'Сортировка и жадные алгоритмы', 'Анализ данных (эффективные алгоритмы)'
  ];

  const SECTIONS = [
    { id: 'python', title: 'Программирование на Python', weight: 60, color: '#735ee8', tasks: [2, 5, 8, 12, 14, 15, 16, 17, 24, 25, 26, 27] },
    { id: 'tables', title: 'Электронные таблицы и БД', weight: 15, color: '#55b994', tasks: [3, 9, 18, 22] },
    { id: 'logic', title: 'Логика, теория и формулы', weight: 25, color: '#e1a56d', tasks: [1, 4, 7, 10, 11, 13, 19, 20, 21, 23] }
  ];

  // Четыре иллюстративные проверки; каждая попытка привязана к заданию и разделу.
  const DEMO_EVENTS = [
    { date: '2026-10-12', answers: [[5, true], [5, false], [5, false], [3, true], [3, true], [4, true], [7, false], [7, false]] },
    { date: '2026-10-19', answers: [[5, true], [5, false], [5, true], [3, true], [3, false], [4, true], [4, false], [7, true]] },
    { date: '2026-10-26', answers: [[5, true], [5, true], [5, false], [3, true], [3, false], [4, true], [4, true], [7, true]] },
    { date: '2026-11-02', answers: [[5, true], [5, true], [5, true], [3, true], [3, false], [4, true], [4, true], [7, true]] }
  ].map((event, index) => ({ ...event, index, gate: [.18, .32, .46, .60][index] }));

  const expected = DEMO_EVENTS.reduce((sum, event) => ({
    correct: sum.correct + event.answers.filter((answer) => answer[1]).length,
    total: sum.total + event.answers.length
  }), { correct: 0, total: 0 });
  if (expected.correct !== 22 || expected.total !== 32 || DEMO_EVENTS.some((event, index) => index && event.date < DEMO_EVENTS[index - 1].date)) {
    throw new Error('Student analytics demo data failed its consistency check.');
  }

  const SEQUENCES = [
    { at: 0, label: 'Пауза · занятие завершено', title: 'Каждый шаг имеет значение.', description: 'Занятие заканчивается. А история того, чему ты научился, продолжается.' },
    { at: .14, label: 'Смотрим · первая работа', title: 'Прогресс, который видно.', description: 'Проверенная работа добавляет результат в общую историю.' },
    { at: .33, label: 'Читаем · динамика', title: 'Замечай, как меняется результат.', description: 'Сравнивай проверенные работы по датам, а не только по одному ответу.' },
    { at: .56, label: 'Смотрим · темы', title: 'Понимай, что уже получается.', description: 'Результаты по темам помогают увидеть, какие разделы ты уже практиковал.' },
    { at: .76, label: 'Читаем · карта заданий', title: 'Отдельные задания — часть общей картины.', description: 'В карте видны попытки и точность по каждому начатому заданию.' },
    { at: .91, label: 'Пауза · учебный путь', title: 'Учиться легче, когда понимаешь свой прогресс.', description: 'BooStudy помогает собрать результаты занятий в наглядную картину учебного пути.' }
  ];

  const titleNode = story.querySelector('[data-s32-title]');
  const descriptionNode = story.querySelector('[data-s32-description]');
  const progressLabel = story.querySelector('[data-s32-progress-label]');
  const progressBar = story.querySelector('[data-s32-progress-bar]');
  const mascot = story.querySelector('[data-s32-mascot]');
  const cta = story.querySelector('[data-s32-cta]');
  const transitionLesson = story.querySelector('.s32-transition__lesson');
  const transitionAnalytics = story.querySelector('.s32-transition__analytics');
  const appShell = story.querySelector('.s32-app-shell');
  const composition = story.querySelector('[data-s33-composition]');
  const analyticsView = story.querySelector('[data-s33-view="analytics"]');
  const dashboardView = story.querySelector('[data-s33-view="dashboard"]') || document.createElement('section');
  const contextLabel = story.querySelector('[data-s33-context]');
  const badgeLabel = story.querySelector('[data-s33-badge]');
  const transitionTo = story.querySelector('[data-s33-transition-to]');
  const chart = story.querySelector('[data-s32-chart]');
  const chartData = story.querySelector('[data-s32-chart-data]');
  const chartEmpty = story.querySelector('[data-s32-chart-empty]');
  const sectionList = story.querySelector('[data-s32-sections]');
  const activityList = story.querySelector('[data-s32-activity]');
  const taskGrid = story.querySelector('[data-s32-task-grid]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const narrowViewport = window.matchMedia('(max-width: 900px)');
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const percent = (correct, total) => total ? (correct / total) * 100 : 0;
  const pctLabel = (value) => `${(Math.round(value * 10) / 10).toLocaleString('ru-RU')}%`;
  const dateLabel = (date) => new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T00:00:00Z`)).replace('.', '');
  const svg = (name) => document.createElementNS('http://www.w3.org/2000/svg', name);

  function renderSectionShell() {
    SECTIONS.forEach((section) => {
      const row = document.createElement('div');
      row.className = 's32-section-row';
      row.style.setProperty('--section-color', section.color);
      row.innerHTML = `<div class="s32-section-row__top"><span class="s32-section-row__name"><i></i><span></span></span><span class="s32-section-row__value">—</span></div><div class="s32-section-row__bar"><i></i></div><div class="s32-section-row__weight"></div>`;
      row.querySelector('.s32-section-row__name span').textContent = section.title;
      row.querySelector('.s32-section-row__weight').textContent = `вес ${section.weight}% в КЕГЭ`;
      sectionList.append(row);
    });

    TASKS.forEach((name, index) => {
      const taskNumber = index + 1;
      const cell = document.createElement('div');
      cell.className = 's32-task';
      cell.dataset.task = String(taskNumber);
      cell.title = `Задание №${taskNumber} · ${name} · ещё не начато`;
      cell.setAttribute('aria-label', cell.title);
      const number = document.createElement('strong');
      number.textContent = `№${taskNumber}`;
      const value = document.createElement('small');
      value.textContent = '—';
      cell.append(number, value);
      taskGrid.append(cell);
    });
  }

  function derive(events) {
    const byTask = new Map();
    const bySection = Object.fromEntries(SECTIONS.map((section) => [section.id, { correct: 0, total: 0 }]));
    let correct = 0;
    let total = 0;

    events.forEach((event) => {
      event.answers.forEach(([taskNumber, isCorrect]) => {
        const task = byTask.get(taskNumber) || { correct: 0, total: 0 };
        task.total += 1;
        task.correct += Number(isCorrect);
        byTask.set(taskNumber, task);
        total += 1;
        correct += Number(isCorrect);
        const section = SECTIONS.find((candidate) => candidate.tasks.includes(taskNumber));
        if (section) {
          bySection[section.id].total += 1;
          bySection[section.id].correct += Number(isCorrect);
        }
      });
    });

    return { byTask, bySection, correct, total, accuracy: percent(correct, total) };
  }

  function renderMetrics(events, stats, latestEvent) {
    const values = {
      works: events.length ? String(events.length) : '—',
      attempts: events.length ? String(stats.total) : '—',
      correct: events.length ? String(stats.correct) : '—',
      accuracy: events.length ? pctLabel(stats.accuracy) : '—'
    };
    Object.entries(values).forEach(([name, value]) => {
      const node = story.querySelector(`[data-s32-metric="${name}"]`);
      node.textContent = value;
      node.closest('.s32-metric').classList.toggle('is-updated', Boolean(latestEvent && latestEvent.index === events.length - 1));
    });

    const worksNote = story.querySelector('[data-s32-metric-note="works"]');
    const accuracyNote = story.querySelector('[data-s32-metric-note="accuracy"]');
    worksNote.textContent = events.length ? `${dateLabel(events[0].date)} — ${dateLabel(events.at(-1).date)}` : 'Начни с первой работы';
    accuracyNote.textContent = events.length ? `${stats.correct} верно из ${stats.total} попыток` : 'Появится после проверки';

    const delta = story.querySelector('[data-s32-delta]');
    if (events.length < 2) delta.textContent = events.length ? 'Базовый результат' : '—';
    else {
      const first = percent(events[0].answers.filter((answer) => answer[1]).length, events[0].answers.length);
      const last = percent(events.at(-1).answers.filter((answer) => answer[1]).length, events.at(-1).answers.length);
      const change = Math.round((last - first) * 10) / 10;
      delta.textContent = `${change > 0 ? '+' : ''}${change.toLocaleString('ru-RU')} п.п. к первой работе`;
    }
    story.querySelector('[data-s32-period]').textContent = events.length
      ? `${dateLabel(events[0].date)} — ${dateLabel(events.at(-1).date)}`
      : '—';
  }

  let chartKey = null;
  let chartPoints = [];
  let chartLine = null;
  let chartArea = null;
  let chartLineLength = 0;
  let chartLastGate = 0;

  function renderChart(events, progress) {
    const nextKey = events.map((event) => event.index).join(',');
    if (nextKey !== chartKey) {
      chartKey = nextKey;
      chartData.replaceChildren();
      chartPoints = [];
      chartLine = null;
      chartArea = null;
      chartLineLength = 0;

      if (!events.length) {
        chartEmpty.hidden = false;
        chart.setAttribute('aria-label', 'Динамика появится после первой проверенной работы');
        return;
      }

      chartEmpty.hidden = true;
      const points = events.map((event) => {
        const score = percent(event.answers.filter((answer) => answer[1]).length, event.answers.length);
        return {
          x: 82 + event.index * 164,
          y: 210 - (score * 1.88),
          score,
          date: dateLabel(event.date),
          gate: event.gate
        };
      });

      if (points.length > 1) {
        const lineD = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
        chartArea = svg('path');
        chartArea.setAttribute('class', 's32-chart__area');
        chartArea.setAttribute('d', `${lineD} L ${points.at(-1).x} 210 L ${points[0].x} 210 Z`);
        chartData.append(chartArea);

        chartLine = svg('path');
        chartLine.setAttribute('class', 's32-chart__line');
        chartLine.setAttribute('d', lineD);
        chartLineLength = chartLine.getTotalLength();
        chartLine.style.strokeDasharray = String(chartLineLength);
        chartLastGate = points.at(-1).gate;
        chartData.append(chartLine);
      }

      chartPoints = points.map((point) => {
        const circle = svg('circle');
        circle.setAttribute('class', 's32-chart__point');
        circle.setAttribute('cx', String(point.x));
        circle.setAttribute('cy', String(point.y));
        circle.setAttribute('r', '6');
        const value = svg('text');
        value.setAttribute('class', 's32-chart__value');
        value.setAttribute('x', String(point.x));
        value.setAttribute('y', String(Math.max(17, point.y - 13)));
        value.textContent = pctLabel(point.score);
        const date = svg('text');
        date.setAttribute('class', 's32-chart__date');
        date.setAttribute('x', String(point.x));
        date.setAttribute('y', '229');
        date.textContent = point.date;
        chartData.append(circle, value, date);
        return { ...point, circle, value };
      });
      chart.setAttribute('aria-label', `Точность по датам: ${points.map((point) => `${point.date} — ${pctLabel(point.score)}`).join('; ')}`);
    }

    if (!chartPoints.length) return;
    chartEmpty.hidden = true;
    if (chartArea) {
      const lineArrival = reduceMotion.matches ? 1 : clamp((progress - chartLastGate) / .09, 0, 1);
      chartArea.style.opacity = String(.08 + lineArrival * .36);
    }
    if (chartLine) {
      const lastIndex = chartPoints.length - 1;
      const segmentProgress = reduceMotion.matches ? 1 : clamp((progress - chartLastGate) / .09, 0, 1);
      const completedLength = Math.max(0, (lastIndex - 1) + segmentProgress) / lastIndex;
      chartLine.style.strokeDashoffset = String(chartLineLength * (1 - completedLength));
    }
    chartPoints.forEach((point, index) => {
      const pointProgress = index === 0 || reduceMotion.matches ? 1 : clamp((progress - point.gate) / .07, 0, 1);
      point.circle.style.opacity = String(pointProgress);
      point.value.style.opacity = String(pointProgress);
    });
  }

  function renderSections(stats, progress) {
    SECTIONS.forEach((section, index) => {
      const values = stats.bySection[section.id];
      const accuracy = percent(values.correct, values.total);
      const row = sectionList.children[index];
      const hasData = values.total > 0;
      const ready = progress >= .64 ? 1 : progress >= .5 ? .58 : progress >= .34 ? .3 : 0;
      row.style.setProperty('--s32-reveal', hasData ? String(.45 + ready * .55) : '.46');
      row.querySelector('.s32-section-row__value').textContent = hasData ? `${pctLabel(accuracy)} · ${values.correct}/${values.total}` : '—';
      row.querySelector('.s32-section-row__bar i').style.setProperty('--section-fill', hasData ? `${accuracy}%` : '0%');
      row.setAttribute('aria-label', hasData
        ? `${section.title}: ${pctLabel(accuracy)}, ${values.correct} верно из ${values.total}, вес ${section.weight} процентов в КЕГЭ`
        : `${section.title}: пока нет данных`);
      row.style.opacity = hasData ? '1' : '.56';
    });
  }

  function renderActivity(events) {
    activityList.replaceChildren();
    if (!events.length) {
      const empty = document.createElement('li');
      empty.className = 's32-activity-empty';
      empty.textContent = 'Здесь появятся проверенные работы.';
      activityList.append(empty);
      return;
    }

    events.forEach((event) => {
      const correct = event.answers.filter((answer) => answer[1]).length;
      const item = document.createElement('li');
      item.className = 's32-activity-item';
      const date = document.createElement('span');
      date.className = 's32-activity-dot';
      date.textContent = `${event.index + 1}`;
      const copy = document.createElement('span');
      copy.className = 's32-activity-copy';
      const name = document.createElement('strong');
      name.textContent = 'Домашняя работа';
      const note = document.createElement('small');
      note.textContent = `${dateLabel(event.date)} · проверено`;
      copy.append(name, note);
      const score = document.createElement('span');
      score.className = 's32-activity-score';
      score.textContent = `${correct} / ${event.answers.length}`;
      item.append(date, copy, score);
      activityList.append(item);
    });
  }

  function renderReadiness(stats, progress) {
    let practiced = 0;
    stats.byTask.forEach((value) => { if (value.total) practiced += 1; });
    story.querySelector('[data-s32-practiced]').textContent = `${practiced} из 27 начато`;
    [...taskGrid.children].forEach((cell, index) => {
      const taskNumber = index + 1;
      const values = stats.byTask.get(taskNumber);
      const valueNode = cell.querySelector('small');
      if (values) {
        const accuracy = percent(values.correct, values.total);
        cell.classList.add('is-started');
        valueNode.textContent = `${Math.round(accuracy)}%`;
        cell.title = `Задание №${taskNumber}: ${TASKS[index]} · решено ${values.correct} из ${values.total} · точность ${pctLabel(accuracy)}`;
        cell.setAttribute('aria-label', cell.title);
        cell.style.opacity = String(progress >= .76 ? 1 : .66);
      } else {
        cell.classList.remove('is-started');
        valueNode.textContent = '—';
        cell.title = `Задание №${taskNumber}: ${TASKS[index]} · ещё не начато`;
        cell.setAttribute('aria-label', cell.title);
        cell.style.opacity = '.7';
      }
    });
  }

  let storyTop = 0;
  let scrollRange = 1;
  let lastProgress = null;
  let lastStaticMode = null;
  let renderedEventCount = -1;
  let renderedSectionReveal = null;
  let renderedReadinessVisible = null;
  let renderedDashboardItemMode = null;

  function measureStory() {
    storyTop = story.getBoundingClientRect().top + window.scrollY;
    scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
  }

  function update(force = false, progressOverride = null) {
    const isStatic = reduceMotion.matches || narrowViewport.matches;
    const progress = isStatic ? 1 : (progressOverride === null ? clamp((window.scrollY - storyTop) / scrollRange, 0, 1) : progressOverride);
    if (!force && progress === lastProgress && isStatic === lastStaticMode) return;
    lastProgress = progress;
    lastStaticMode = isStatic;
    story.toggleAttribute('data-s33-static', isStatic);
    const analyticsProgress = progress;
    const dashboardProgress = 0;
    const dashboardActive = false;
    const inViewTransition = !isStatic && progress >= .63 && progress <= .67;
    const viewBlend = inViewTransition ? clamp((progress - .63) / .04, 0, 1) : dashboardActive ? 1 : 0;
    const dashboardPhase = dashboardProgress < .14 ? 'start'
      : dashboardProgress < .38 ? 'context'
        : dashboardProgress < .56 ? 'focus'
          : dashboardProgress < .82 ? 'rich' : 'complete';
    const sequence = dashboardActive
      ? [
        { at: 0, label: 'Личное пространство', title: 'Вся учёба — на своих местах.', description: 'Цель и учебные инструменты собраны в одном личном кабинете.' },
        { at: .14, label: 'Учебный контекст', title: 'Понятно, где ты и что дальше.', description: 'Ближайший урок, расписание и программа показывают ход обучения.' },
        { at: .38, label: 'Следующий шаг', title: 'К занятию — без лишних поисков.', description: 'Открой чек-лист подготовки прямо с главной страницы.' },
        { at: .56, label: 'Другие возможности', title: 'Всё важное уже рядом.', description: 'Задания, теория, расписание и сводка прогресса остаются под рукой.' },
        { at: .82, label: 'Твоё учебное пространство', title: 'Твоё обучение начинается здесь.', description: 'Один понятный центр для занятий и ежедневной работы.' },
      ].reverse().find((item) => dashboardProgress >= item.at)
      : [...SEQUENCES].reverse().find((item) => analyticsProgress >= item.at) || SEQUENCES[0];
    if (titleNode.textContent !== sequence.title) titleNode.textContent = sequence.title;
    if (descriptionNode.textContent !== sequence.description) descriptionNode.textContent = sequence.description;
    progressLabel.textContent = sequence.label;
    progressBar.style.transform = `scaleX(${dashboardActive ? dashboardProgress : analyticsProgress})`;
    mascot.classList.toggle('is-visible', dashboardActive ? dashboardProgress >= .72 : analyticsProgress >= .83);
    cta.hidden = !dashboardActive || dashboardProgress < .91;
    const transitionProgress = isStatic ? 1 : clamp(progress / .12, 0, 1);
    transitionLesson.style.opacity = String(1 - transitionProgress);
    transitionLesson.style.transform = `translateX(${-8 * transitionProgress}px)`;
    transitionAnalytics.textContent = dashboardActive ? 'Личное пространство' : 'Твоя аналитика';
    transitionAnalytics.style.opacity = String(.52 + .48 * transitionProgress);
    transitionAnalytics.style.transform = `translateX(${8 * (1 - transitionProgress)}px)`;
    const appEntrance = isStatic ? 1 : clamp(progress / .16, 0, 1);
    const seamOpacity = inViewTransition ? Math.abs(2 * viewBlend - 1) : 1;
    appShell.style.opacity = String((.82 + .18 * appEntrance) * seamOpacity);
    appShell.style.setProperty('--s33-view-blend', String(viewBlend));
    appShell.style.transform = `translateY(calc(-50% + ${8 * (1 - appEntrance)}px)) scale(${.99 + .01 * appEntrance})`;

    const analyticsHidden = !isStatic && dashboardActive;
    const dashboardHidden = !isStatic && !dashboardActive;
    if (analyticsView.hidden !== analyticsHidden) analyticsView.hidden = analyticsHidden;
    if (dashboardView.hidden !== dashboardHidden) dashboardView.hidden = dashboardHidden;
    if (analyticsView.getAttribute('aria-hidden') !== String(analyticsHidden)) analyticsView.setAttribute('aria-hidden', String(analyticsHidden));
    if (dashboardView.getAttribute('aria-hidden') !== String(dashboardHidden)) dashboardView.setAttribute('aria-hidden', String(dashboardHidden));
    contextLabel.textContent = dashboardActive ? 'Твоё обучение' : 'Личная аналитика';
    badgeLabel.textContent = dashboardActive ? 'Демо-реконструкция' : 'Синтетические данные · демо';
    transitionTo.textContent = dashboardActive ? 'Личное пространство' : 'Твоя аналитика';

    const analyticsSideChange = clamp((analyticsProgress - .23) / .18, 0, 1);
    const dashboardSideChange = dashboardActive ? clamp((dashboardProgress - .56) / .26, 0, 1) : 0;
    let productLeft = 31 * (1 - analyticsSideChange);
    let productWidth = productLeft < 15 ? 72 : 67;
    let copyLeft = 75 * (1 - productLeft / 31);
    let copyWidth = productLeft < 15 ? 23 : 27;
    let copyOpacity = analyticsSideChange < .35
      ? 1 - analyticsSideChange / .35
      : analyticsSideChange > .65 ? (analyticsSideChange - .65) / .35 : 0;
    if (dashboardActive) {
      if (dashboardProgress < .38) {
        productLeft = 0;
        productWidth = 72;
        copyLeft = 75;
        copyWidth = 23;
        copyOpacity = 1;
      } else if (dashboardProgress < .56) {
        const focusProgress = clamp((dashboardProgress - .38) / .18, 0, 1);
        productLeft = 4 * focusProgress;
        productWidth = 72 + 20 * focusProgress;
        copyLeft = 75;
        copyWidth = 21;
        copyOpacity = 1 - focusProgress;
      } else if (dashboardProgress < .82) {
        productLeft = 29 * dashboardSideChange;
        productWidth = 92 - 25 * dashboardSideChange;
        copyLeft = 75 * (1 - dashboardSideChange);
        copyWidth = 23;
        copyOpacity = dashboardSideChange < .4 ? 0 : (dashboardSideChange - .4) / .6;
      } else {
        productLeft = 21;
        productWidth = 78;
        copyLeft = 0;
        copyWidth = 19;
        copyOpacity = 1;
      }
    }
    composition.style.setProperty('--s33-product-left', `${productLeft}%`);
    composition.style.setProperty('--s33-product-width', `${productWidth}%`);
    composition.style.setProperty('--s33-copy-left', `${copyLeft}%`);
    composition.style.setProperty('--s33-copy-width', `${copyWidth}%`);
    composition.style.setProperty('--s33-copy-opacity', String(isStatic ? 1 : clamp(copyOpacity, 0, 1) * seamOpacity));
    composition.dataset.layout = dashboardActive ? dashboardProgress >= .56 ? 'text-left' : 'product-left' : productLeft < 15 ? 'product-left' : 'text-left';
    const commandCenter = dashboardView.querySelector('.s34-command-center');
    if (commandCenter) commandCenter.dataset.phase = dashboardPhase;

    const events = DEMO_EVENTS.filter((event) => analyticsProgress >= event.gate);
    const eventsChanged = events.length !== renderedEventCount;
    const sectionReveal = analyticsProgress >= .64 ? 3 : analyticsProgress >= .5 ? 2 : analyticsProgress >= .34 ? 1 : 0;
    const readinessVisible = analyticsProgress >= .76;
    const stats = eventsChanged ? derive(events) : null;
    if (eventsChanged) {
      const latestEvent = events.at(-1) || null;
      renderMetrics(events, stats, latestEvent);
      renderSections(stats, analyticsProgress);
      renderActivity(events);
      renderReadiness(stats, analyticsProgress);
      renderedEventCount = events.length;
      renderedSectionReveal = sectionReveal;
      renderedReadinessVisible = readinessVisible;
    } else {
      if (sectionReveal !== renderedSectionReveal) {
        renderSections(stats || derive(events), analyticsProgress);
        renderedSectionReveal = sectionReveal;
      }
      if (readinessVisible !== renderedReadinessVisible) {
        renderReadiness(stats || derive(events), analyticsProgress);
        renderedReadinessVisible = readinessVisible;
      }
    }
    renderChart(events, analyticsProgress);

    const dashboardItemMode = isStatic ? 'static' : 'story';
    if (dashboardItemMode !== renderedDashboardItemMode) {
      dashboardView.querySelectorAll('[data-dashboard-item]').forEach((item) => {
        const revealAt = Number(item.dataset.revealAt || 0);
        const itemProgress = isStatic ? 1 : clamp((dashboardProgress - revealAt) / .12, 0, 1);
        item.classList.toggle('is-visible', isStatic || dashboardProgress >= revealAt);
        item.style.setProperty('--s33-item-progress', String(itemProgress));
      });
      renderedDashboardItemMode = dashboardItemMode;
    }
  }

  let frame = 0;
  let forceUpdate = false;
  const schedule = (force = false) => {
    forceUpdate ||= force;
    if (frame) return;
    frame = window.requestAnimationFrame(() => {
      frame = 0;
      const shouldForce = forceUpdate;
      forceUpdate = false;
      update(shouldForce);
    });
  };

  const resize = () => {
    measureStory();
    schedule(true);
  };

  renderSectionShell();
  document.addEventListener('boostudy:story-progress', (event) => {
    if (typeof event.detail.s32 === 'number') update(false, event.detail.s32);
  });
  window.addEventListener('resize', resize);
  reduceMotion.addEventListener?.('change', () => schedule(true));
  narrowViewport.addEventListener?.('change', () => schedule(true));
  measureStory();
  update(true);
})();
