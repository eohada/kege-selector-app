(() => {
  const story = document.querySelector('[data-s30-story]');
  const stage = document.querySelector('[data-s30-stage]');
  if (!story || !stage) return;

  const sceneNames = [
    'hero', 'enter', 'task', 'typing', 'result', 'switch', 'math-empty',
    'math-write', 'math-tree', 'math-count', 'math-formula', 'math-done', 'outro'
  ];
  const sceneEnds = [.07, .14, .22, .38, .45, .52, .60, .68, .76, .84, .92, .97];
  const copyBlocks = [...document.querySelectorAll('[data-s30-copy]')];
  const progressLabel = document.querySelector('[data-s30-progress-label]');
  const progressBar = document.querySelector('[data-s30-progress-bar]');
  const codeNode = document.querySelector('[data-s30-code] code');
  const output = document.querySelector('[data-s30-output]');
  const outputResult = document.querySelector('[data-s30-output-result]');
  const handTitle = document.querySelector('[data-s30-hand-title]');
  const strokes = [...document.querySelectorAll('[data-draw]')];
  const treeLabels = [...document.querySelectorAll('[data-appear]')];
  const formulas = [...document.querySelectorAll('[data-formula-at]')];
  const roomTitle = document.querySelector('[data-s30-room-title]');
  const roomState = document.querySelector('[data-s30-room-state]');
  const taskTitle = document.querySelector('[data-s30-task-title]');
  const rebuildLabel = document.querySelector('[data-s30-rebuild-label]');
  const canvasState = document.querySelector('[data-s30-canvas-state]');
  const canvasProgress = document.querySelector('[data-s30-canvas-progress]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const codeLines = [
    'for n in range(1, 1000):',
    '    s = bin(n)[2:]',
    '    s += str(s.count("1") % 2)',
    '    s += str(s.count("1") % 2)',
    '    r = int(s, 2)',
    '    if r > 253:',
    '        print(n, r)',
    '        break'
  ];
  const fullCode = codeLines.join('\n');
  const totalCodeChars = fullCode.length;
  const handText = '2 броска монеты';
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  let activeScene = '';
  let animationFrame = 0;
  let storyTop = 0;
  let scrollRange = 1;
  let lastProgress = null;
  let lastReducedMotion = null;
  let lastViewportWidth = 0;
  let lastViewportHeight = 0;
  let forceUpdate = false;

  function measureStory() {
    storyTop = story.getBoundingClientRect().top + window.scrollY;
    scrollRange = Math.max(1, story.offsetHeight - window.innerHeight);
  }

  function escapeHtml(value) {
    return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  }

  function highlight(line) {
    const pattern = /(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:for|in|if|break)\b|\b(?:range|bin|str|int|print)\b|\b\d+\b)/g;
    let html = '';
    let cursor = 0;
    for (const match of line.matchAll(pattern)) {
      const token = match[0];
      const start = match.index;
      html += escapeHtml(line.slice(cursor, start));
      let tokenClass = 's30-token-number';
      if (token.startsWith('#')) tokenClass = 's30-token-comment';
      else if (token.startsWith('"') || token.startsWith("'")) tokenClass = 's30-token-string';
      else if (/^(for|in|if|break)$/.test(token)) tokenClass = 's30-token-keyword';
      else if (/^(range|bin|str|int|print)$/.test(token)) tokenClass = 's30-token-builtin';
      html += '<span class="' + tokenClass + '">' + escapeHtml(token) + '</span>';
      cursor = start + token.length;
    }
    return html + escapeHtml(line.slice(cursor));
  }

  function drawCode(progress) {
    if (!codeNode) return;
    const visibleChars = Math.round(totalCodeChars * clamp(progress, 0, 1));
    let consumed = 0;
    let html = '';
    codeLines.forEach((line, index) => {
      const visibleLength = clamp(visibleChars - consumed, 0, line.length);
      if (visibleLength > 0 || index === 0 || (line.length === 0 && visibleChars > consumed)) {
        html += '<span class="s30-code-line"><span class="s30-line-number">' + String(index + 1).padStart(2, '0') + '</span>' + highlight(line.slice(0, visibleLength)) + '</span>';
        if (visibleLength === line.length && index < codeLines.length - 1 && visibleChars > consumed + line.length) html += '\n';
      }
      consumed += line.length + 1;
    });
    codeNode.innerHTML = html;
    codeNode.setAttribute('aria-label', progress >= 1
      ? 'Демонстрационный код Python: ' + fullCode.replaceAll('\n', '; ')
      : 'Демонстрационный код Python появляется постепенно по мере просмотра');
  }

  function setCanvasDrawing(progress) {
    const p = clamp(progress, 0, 1);
    const handwritingProgress = clamp((p - .025) / .14, 0, 1);
    if (handTitle) {
      handTitle.textContent = handText.slice(0, Math.round(handText.length * handwritingProgress));
      handTitle.setAttribute('aria-hidden', String(handwritingProgress < 1));
    }
    strokes.forEach((stroke) => {
      const [start, end] = stroke.dataset.draw.split(' ').map(Number);
      const length = stroke.getTotalLength();
      const strokeProgress = clamp((p - start) / (end - start), 0, 1);
      stroke.style.strokeDasharray = String(length);
      stroke.style.strokeDashoffset = String(length * (1 - strokeProgress));
    });
    treeLabels.forEach((label) => {
      const threshold = Number(label.dataset.appear);
      const visible = clamp((p - threshold) / .055, 0, 1);
      label.style.opacity = String(visible);
    });
    formulas.forEach((formula) => {
      const threshold = Number(formula.dataset.formulaAt);
      const visible = clamp((p - threshold) / .035, 0, 1);
      formula.style.opacity = String(visible);
      formula.style.transform = 'translateY(' + (5 * (1 - visible)) + 'px)';
      if (formula.classList.contains('s30-formula__answer')) {
        formula.style.setProperty('--answer-underline', String(clamp((p - .98) / .02, 0, 1)));
      }
    });
    if (canvasProgress) {
      canvasProgress.textContent = p < .03 ? 'Готово к записи' : p < .2 ? 'Появляется запись' : p < .72 ? 'Строим исходы' : p < .98 ? 'Считаем вероятность' : 'Решение завершено';
    }
    if (canvasState) canvasState.textContent = p < .03 ? 'Страница 1 · чистый холст' : p < .98 ? 'Страница 1 · решение на доске' : 'Страница 1 · готово';
  }

  function setWorkspaceState(scene) {
    const math = scene.startsWith('math-') || scene === 'switch' || scene === 'outro';
    if (roomTitle) roomTitle.textContent = math ? 'Комната ученика · математика' : 'Комната ученика';
    if (roomState) roomState.textContent = 'демонстрационная композиция';
    if (taskTitle) taskTitle.textContent = math ? 'Задание · вероятность' : 'Задание №5';
    if (rebuildLabel) rebuildLabel.textContent = scene === 'hero' || scene === 'enter'
      ? 'Чистая учебная среда · Preview'
      : 'Синтетический пример · визуальная реконструкция';
    const dockLabels = document.querySelectorAll('.s30-dock span');
    if (dockLabels[0]) dockLabels[0].textContent = 'Задание';
    if (dockLabels[1]) dockLabels[1].textContent = math ? 'BooCanvas' : 'Программа';
    if (dockLabels[2]) dockLabels[2].textContent = math ? 'Перо' : 'Python';
  }

  function update(force = false, progressOverride = null) {
    const isReducedMotion = reduceMotion.matches;
    const progress = progressOverride === null ? clamp((window.scrollY - storyTop) / scrollRange, 0, 1) : progressOverride;
    const stopIndex = sceneEnds.findIndex((stop) => progress < stop);
    const index = stopIndex === -1 ? sceneNames.length - 1 : stopIndex;
    const scene = isReducedMotion && progress >= .538 && progress < .97
      ? 'math-done'
      : sceneNames[index];
    const displayIndex = isReducedMotion && scene === 'math-done'
      ? sceneNames.indexOf('math-done')
      : index;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    if (!force && progress === lastProgress && scene === activeScene
      && isReducedMotion === lastReducedMotion
      && viewportWidth === lastViewportWidth && viewportHeight === lastViewportHeight) {
      animationFrame = 0;
      return;
    }
    lastProgress = progress;
    lastReducedMotion = isReducedMotion;
    lastViewportWidth = viewportWidth;
    lastViewportHeight = viewportHeight;

    if (scene !== activeScene) {
      activeScene = scene;
      stage.dataset.scene = scene;
      copyBlocks.forEach((copy) => copy.setAttribute('aria-hidden', String(copy.dataset.s30Copy !== scene)));
      const stageDescription = scene === 'hero' || scene === 'enter'
        ? 'чистое учебное пространство'
        : scene === 'switch' || scene.startsWith('math-')
          ? 'демонстрационное занятие по математике'
          : scene === 'outro'
            ? 'завершённое учебное пространство'
            : 'демонстрационное занятие по информатике';
      stage.setAttribute('aria-label', 'BooStudy OS: ' + stageDescription);
      if (progressLabel) progressLabel.innerHTML = String(displayIndex + 1).padStart(2, '0') + ' <i>/ 13</i>';
      setWorkspaceState(scene);
    }

    const codeProgress = clamp((progress - .22) / (.38 - .22), 0, 1);
    drawCode(isReducedMotion && codeProgress > 0 ? 1 : codeProgress);
    const mathProgress = clamp((progress - .60) / (.92 - .60), 0, 1);
    setCanvasDrawing(isReducedMotion && progress >= .538 ? 1 : mathProgress);
    if (outputResult) outputResult.textContent = scene === 'result' ? 'N = 64 · R = 258' : '';
    if (output) output.setAttribute('aria-hidden', String(scene !== 'result'));
    stage.style.setProperty('--s30-progress', String(progress));
    if (progressBar) progressBar.style.width = Math.round(progress * 100) + '%';
    animationFrame = 0;
  }

  function scheduleUpdate(force = false) {
    forceUpdate ||= force;
    if (animationFrame) return;
    animationFrame = window.requestAnimationFrame(() => {
      const shouldForce = forceUpdate;
      forceUpdate = false;
      update(shouldForce);
    });
  }

  const targetFor = (name) => ({
    top: 'hero',
    informatics: 'task',
    math: 'math-empty',
    payoff: 'outro'
  }[name] || name);

  document.querySelectorAll('[data-s30-goto]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const targetName = targetFor(link.dataset.s30Goto);
      const target = document.querySelector('[data-s30-step="' + targetName + '"]');
      if (!target) return;
      event.preventDefault();
      history.replaceState(null, '', '#s31-' + link.dataset.s30Goto);
      target.scrollIntoView({ behavior: reduceMotion.matches ? 'instant' : 'smooth', block: 'start' });
    });
  });

  document.addEventListener('boostudy:story-progress', (event) => {
    if (typeof event.detail.s30 === 'number') update(false, event.detail.s30);
  });
  window.addEventListener('resize', () => {
    measureStory();
    scheduleUpdate(true);
  });
  reduceMotion.addEventListener?.('change', () => scheduleUpdate());
  measureStory();
  update(true);
})();
