(() => {
  const story = document.querySelector('[data-s35-story]');
  if (!story) return;

  const surface = story.querySelector('[data-dashboard-surface]');
  const viewport = story.querySelector('[data-dashboard-viewport]');
  const frame = story.querySelector('[data-dashboard-camera]');
  const title = story.querySelector('[data-s35-title]');
  const description = story.querySelector('[data-s35-description]');
  const eyebrow = story.querySelector('[data-s35-eyebrow]');
  const progressLabel = story.querySelector('[data-s35-progress-label]');
  const progressBar = story.querySelector('[data-s35-progress-bar]');
  const cta = story.querySelector('[data-s35-cta]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const smooth = (value) => {
    const t = clamp(value);
    return t * t * (3 - 2 * t);
  };

  const scenes = [
    {
      key: 'intro', start: 0, end: .12, focus: 'intro', label: 'Личное пространство',
      eyebrow: 'ЦЕНТР ТВОЕЙ ПОДГОТОВКИ', title: 'Твоё обучение. Всё на своих местах.',
      description: 'Занятия, программа и необходимые материалы собраны в одном личном пространстве.',
      read: { productLeft: 0, productWidth: 72, copyLeft: 76, copyWidth: 22 },
      watch: { productLeft: 0, productWidth: 72, copyLeft: 76, copyWidth: 22 }
    },
    {
      key: 'continue', start: .12, end: .27, focus: 'continue', label: 'Продолжить обучение',
      eyebrow: 'ЭПИЗОД B · ПРОДОЛЖИТЬ ОБУЧЕНИЕ', title: 'Продолжай с того, на чём остановился.',
      description: 'Нужное занятие и учебный контекст всегда под рукой. Текущий экран не обещает сохранить состояние другого инструмента между сессиями.',
      read: { productLeft: 27, productWidth: 69, copyLeft: 0, copyWidth: 23 },
      watch: { productLeft: 4, productWidth: 92, copyLeft: 0, copyWidth: 21 }
    },
    {
      key: 'schedule', start: .27, end: .40, focus: 'schedule', label: 'Ближайшие занятия',
      eyebrow: 'ЭПИЗОД C · РАСПИСАНИЕ', title: 'Ближайшие занятия — перед глазами.',
      description: 'Сверь время и тему, чтобы понимать, что запланировано и к чему готовиться дальше.',
      read: { productLeft: 29, productWidth: 71, copyLeft: 0, copyWidth: 24 },
      watch: { productLeft: 8, productWidth: 90, copyLeft: 0, copyWidth: 23 }
    },
    {
      key: 'curriculum', start: .40, end: .53, focus: 'curriculum', label: 'Программа подготовки',
      eyebrow: 'ЭПИЗОД D · ПРОГРАММА', title: 'Понимай, куда движется твоя подготовка.',
      description: 'Структура тем помогает увидеть, что уже пройдено, где ты сейчас и что ждёт дальше.',
      read: { productLeft: 0, productWidth: 72, copyLeft: 76, copyWidth: 22 },
      watch: { productLeft: 4, productWidth: 92, copyLeft: 76, copyWidth: 21 }
    },
    {
      key: 'materials', start: .53, end: .68, focus: 'materials', label: 'Материалы и подготовка',
      eyebrow: 'ЭПИЗОД E · МАТЕРИАЛЫ', title: 'Всё для занятия — под рукой.',
      description: 'Открой конспект и отметь подготовительные шаги рядом с учебным контекстом.',
      read: { productLeft: 24, productWidth: 76, copyLeft: 0, copyWidth: 20 },
      watch: { productLeft: 4, productWidth: 92, copyLeft: 0, copyWidth: 20 }
    },
    {
      key: 'progress', start: .68, end: .82, focus: 'progress', label: 'Краткая картина прогресса',
      eyebrow: 'ЭПИЗОД F · ПРОГРЕСС', title: 'Важное видно сразу. Подробности — рядом.',
      description: 'Короткая сводка помогает оценить общую картину, а детальный разбор остаётся в аналитике.',
      read: { productLeft: 27, productWidth: 73, copyLeft: 0, copyWidth: 23 },
      watch: { productLeft: 7, productWidth: 91, copyLeft: 0, copyWidth: 21 }
    },
    {
      key: 'complete', start: .82, end: 1, focus: 'overview', label: 'Твой центр обучения',
      eyebrow: 'ФИНАЛ · ЛИЧНОЕ ПРОСТРАНСТВО', title: 'Не просто личный кабинет. Твой центр обучения.',
      description: 'От следующего занятия до программы подготовки — всё организовано так, чтобы ты мог сосредоточиться на учёбе.',
      read: { productLeft: 24, productWidth: 76, copyLeft: 0, copyWidth: 20 },
      watch: { productLeft: 24, productWidth: 76, copyLeft: 0, copyWidth: 20 }
    }
  ];

  const getProgress = () => {
    const top = story.getBoundingClientRect().top + window.scrollY;
    const range = Math.max(1, story.offsetHeight - window.innerHeight);
    return clamp((window.scrollY - top) / range);
  };

  function getScene(progress) {
    const scene = scenes.find((item) => progress < item.end) || scenes.at(-1);
    const local = clamp((progress - scene.start) / (scene.end - scene.start));
    return { ...scene, local };
  }

  function interpolateLayout(scene, zoom) {
    const { read, watch } = scene;
    const mix = (key) => read[key] + (watch[key] - read[key]) * zoom;
    return {
      productLeft: mix('productLeft'),
      productWidth: mix('productWidth'),
      copyLeft: mix('copyLeft'),
      copyWidth: mix('copyWidth')
    };
  }

  function setCamera(scene, focusAmount) {
    const isMobileLayout = window.matchMedia('(max-width: 900px)').matches;
    const current = new DOMMatrixReadOnly(getComputedStyle(surface).transform);
    const viewportRect = viewport.getBoundingClientRect();
    let scale = 1;
    let x = 0;
    let y = 0;

    if (scene.key === 'complete' && (isMobileLayout || window.innerHeight <= 820)) {
      const maxY = Math.max(0, surface.scrollHeight - viewport.clientHeight);
      const pan = smooth((scene.local - .1) / .78);
      y = -maxY * pan;
    } else if (focusAmount > 0.01 && scene.focus !== 'intro' && scene.focus !== 'overview') {
      const target = surface.querySelector(`[data-dashboard-region="${scene.focus}"]`);
      if (target) {
        const rect = target.getBoundingClientRect();
        const previousScale = current.a || 1;
        const previousX = current.e || 0;
        const previousY = current.f || 0;
        const centerX = (rect.left + rect.width / 2 - viewportRect.left - previousX) / previousScale;
        const centerY = (rect.top + rect.height / 2 - viewportRect.top - previousY) / previousScale;
        const targetScale = isMobileLayout ? 1 : window.innerHeight <= 820 ? 1.42 : 1.52;
        scale = 1 + (targetScale - 1) * focusAmount;
        x = (viewport.clientWidth / 2 - centerX * scale) * focusAmount;
        y = (viewport.clientHeight / 2 - centerY * scale) * focusAmount;
      }
    }

    surface.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0) scale(${scale.toFixed(4)})`;
  }

  function update() {
    const isStatic = reduceMotion.matches;
    story.toggleAttribute('data-s35-static', isStatic);
    const progress = isStatic ? 1 : getProgress();
    const scene = getScene(progress);
    const attention = scene.local < .2 ? 'read'
      : scene.local < .63 ? 'watch'
        : scene.local < .84 ? 'understand' : 'move';
    const focusAmount = scene.key === 'complete' ? 0 : smooth((scene.local - .17) / .22) * (1 - smooth((scene.local - .78) / .17));
    const layoutAmount = scene.key === 'complete' ? smooth((scene.local - .2) / .22) : smooth((scene.local - .16) / .22);
    const layout = interpolateLayout(scene, layoutAmount);
    const copyOpacity = scene.key === 'complete'
      ? scene.local > .62 ? 1 : attention === 'read' ? 1 : .24
      : attention === 'read' ? 1 : attention === 'watch' ? .22 : attention === 'understand' ? .58 : .18;

    story.dataset.scene = scene.key;
    story.dataset.attention = attention;
    surface.dataset.focus = focusAmount > .08 ? scene.focus : scene.key === 'intro' ? 'intro' : 'overview';
    eyebrow.textContent = scene.eyebrow;
    title.textContent = scene.title;
    description.textContent = scene.description;
    progressLabel.textContent = scene.label;
    progressBar.style.width = `${Math.round(progress * 100)}%`;
    cta.hidden = !isStatic && progress < .955;

    const opacity = isStatic ? 1 : copyOpacity;
    story.style.setProperty('--s35-copy-opacity', String(opacity));
    story.style.setProperty('--s35-product-left', `${layout.productLeft}%`);
    story.style.setProperty('--s35-product-width', `${layout.productWidth}%`);
    story.style.setProperty('--s35-copy-left', `${layout.copyLeft}%`);
    story.style.setProperty('--s35-copy-width', `${layout.copyWidth}%`);
    story.dataset.layout = layout.productLeft < 15 ? 'product-left' : 'text-left';
    setCamera(scene, focusAmount);
  }

  const checklistInputs = [...surface.querySelectorAll('.s35-checklist-items input[type="checkbox"]')];
  const checklistCount = surface.querySelector('[data-checklist-count]');
  const checklistBar = surface.querySelector('[data-checklist-bar]');
  function updateChecklist() {
    const completed = checklistInputs.filter((input) => input.checked).length;
    checklistCount.textContent = `${completed} из ${checklistInputs.length} выполнено`;
    checklistBar.style.width = `${checklistInputs.length ? completed / checklistInputs.length * 100 : 0}%`;
    surface.querySelector('.s35-checklist-card').dataset.completed = String(completed);
  }
  checklistInputs.forEach((input) => input.addEventListener('change', updateChecklist));

  let frameId = 0;
  const scheduleUpdate = () => {
    if (frameId) return;
    frameId = window.requestAnimationFrame(() => {
      frameId = 0;
      update();
    });
  };

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
  reduceMotion.addEventListener?.('change', scheduleUpdate);
  updateChecklist();
  update();
})();
