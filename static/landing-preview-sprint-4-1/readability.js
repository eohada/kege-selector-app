(() => {
  const codeSource = [
    'score = 75',
    '# Проверяем минимальный порог',
    'if score >= 60:',
    '    print("Зачёт")',
    'else:',
    '    print("Повторить")',
  ].join('\n');

  const tokenizePython = (code) => {
    const tokens = [];
    const keywords = new Set(['if', 'else', 'elif', 'for', 'while', 'def', 'return', 'in', 'and', 'or', 'not', 'True', 'False', 'None']);
    const builtins = new Set(['print', 'len', 'range', 'int', 'str', 'float']);
    const operators = ['**=', '//=', '>=', '<=', '==', '!=', '+=', '-=', '*=', '/=', '//', '**', '->', ':='];
    let index = 0;

    while (index < code.length) {
      const start = index;
      const char = code[index];
      let kind = '';

      if (/\s/.test(char)) {
        index += 1;
        while (index < code.length && /\s/.test(code[index])) index += 1;
      } else if (char === '#') {
        kind = 'comment';
        while (index < code.length && code[index] !== '\n') index += 1;
      } else if (char === '"' || char === "'") {
        kind = 'string';
        const quote = char;
        index += 1;
        while (index < code.length) {
          if (code[index] === '\\') { index += 2; continue; }
          const current = code[index++];
          if (current === quote) break;
        }
      } else if (/[A-Za-z_]/.test(char)) {
        index += 1;
        while (index < code.length && /[A-Za-z0-9_]/.test(code[index])) index += 1;
        const word = code.slice(start, index);
        if (keywords.has(word)) kind = 'keyword';
        else if (builtins.has(word) && code.slice(index).match(/^\s*\(/)) kind = 'function';
        else kind = 'identifier';
      } else if (/\d/.test(char)) {
        kind = 'number';
        index += 1;
        while (index < code.length && /[\d._]/.test(code[index])) index += 1;
      } else {
        const operator = operators.find((candidate) => code.startsWith(candidate, index));
        if (operator) index += operator.length;
        else index += 1;
        if ('=<>+-*/%()[]{}.,:'.includes(char) || operator) kind = 'operator';
      }

      tokens.push({ kind, text: code.slice(start, index) });
    }

    return tokens;
  };

  const highlightPython = (code) => {
    code.textContent = codeSource;
    const fragment = document.createDocumentFragment();
    tokenizePython(codeSource).forEach(({ kind, text }) => {
      if (!kind) fragment.append(document.createTextNode(text));
      else {
        const span = document.createElement('span');
        span.className = `py-${kind}`;
        span.textContent = text;
        fragment.append(span);
      }
    });
    code.replaceChildren(fragment);
  };

  const setupTheory = () => {
    const theory = document.querySelector('[data-s39-theory]');
    if (!theory) return;

    const code = theory.querySelector('[data-s39-theory-view="reading"] pre code');
    if (code) highlightPython(code);

    const reading = theory.querySelector('[data-s39-theory-view="reading"]');
    if (reading) {
      const readingHead = reading.querySelector('.s39-reading-head');
      if (readingHead) {
        readingHead.querySelector('span').textContent = 'УСЛОВИЯ В PYTHON · ПРИМЕР';
        readingHead.querySelector('small').textContent = 'СИНТЕТИЧЕСКИЙ УЧЕБНЫЙ ПРИМЕР';
      }
      const footerLabel = reading.querySelector('.s39-reading-bottom > span');
      if (footerLabel) footerLabel.textContent = 'Предсказание результата';
      const nextReading = reading.querySelector('[data-s39-next-reading]');
      if (nextReading) {
        const checkButton = document.createElement('button');
        checkButton.type = 'button';
        checkButton.dataset.s39OpenCheck = '';
        checkButton.textContent = 'Проверить себя →';
        checkButton.setAttribute('aria-label', 'Проверить понимание примера с условием');
        nextReading.before(checkButton);
        checkButton.addEventListener('click', () => {
          const views = [...theory.querySelectorAll('[data-s39-theory-view]')];
          views.forEach((view) => {
            const active = view.dataset.s39TheoryView === 'check';
            view.hidden = !active;
            view.setAttribute('aria-hidden', String(!active));
          });
          theory.querySelector('.s39-app').dataset.focus = 'check';
          theory.querySelector('[data-s39-check-try]').focus({ preventScroll: true });
        });
      }
    }

    const invite = theory.querySelector('[data-s39-check-invite]');
    const question = theory.querySelector('[data-s39-check-question]');
    const answerGroup = question?.querySelector('[role="group"]');
    if (!invite || !question || !answerGroup) return;

    invite.querySelector('span').textContent = 'ПРОВЕРКА К ПРИМЕРУ · score = 75';
    invite.querySelector('h4').textContent = 'Хочешь проверить, как сработало условие?';
    invite.querySelector('p').textContent = 'В примере score равен 75. Можно ответить или спокойно продолжить без проверки.';
    const inviteButtons = invite.querySelectorAll('[data-s39-check-skip]');
    inviteButtons.forEach((button) => { button.textContent = 'Пропустить'; });
    question.querySelector('span').textContent = 'ВОПРОС ПО ПРИМЕРУ · СИНТЕТИЧЕСКИЙ PREVIEW';
    question.querySelector('h4').textContent = 'Что напечатает программа при score = 75?';
    answerGroup.setAttribute('aria-label', 'Выбери результат выполнения программы');
    answerGroup.innerHTML = [
      '<button type="button" data-s39-answer="pass">Зачёт</button>',
      '<button type="button" data-s39-answer="retry">Повторить</button>',
      '<button type="button" data-s39-answer="both">Обе строки</button>',
    ].join('');
    question.querySelector('[data-s39-check-feedback]').textContent = 'Ответ по желанию. Попробуй предсказать результат или пропусти.';
    question.querySelectorAll('[data-s39-check-skip]').forEach((button) => { button.textContent = 'Продолжить без ответа'; });

    let checkComplete = false;
    question.addEventListener('click', (event) => {
      const button = event.target.closest('[data-s39-answer]');
      if (!button) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      question.querySelectorAll('[data-s39-answer]').forEach((item) => {
        item.setAttribute('aria-pressed', String(item === button));
        item.removeAttribute('data-correct');
      });
      const feedback = question.querySelector('[data-s39-check-feedback]');
      const correct = button.dataset.s39Answer === 'pass';
      feedback.dataset.result = correct ? 'correct' : 'wrong';
      if (correct) {
        checkComplete = true;
        button.dataset.correct = 'true';
        feedback.textContent = 'Верно: 75 ≥ 60, поэтому выполняется первая ветка и выводится «Зачёт».';
        theory.querySelector('[data-s39-theory-continue]').hidden = false;
      } else {
        feedback.textContent = 'Проверь значение score и условие score >= 60. Можно попробовать ещё раз или продолжить без ответа.';
      }
    }, true);

    question.querySelectorAll('[data-s39-check-skip]').forEach((button) => {
      button.addEventListener('click', () => {
        checkComplete = true;
        const feedback = question.querySelector('[data-s39-check-feedback]');
        feedback.dataset.result = '';
        feedback.textContent = 'Проверка пропущена. Ответ не записан — можно продолжить.';
      }, true);
    });

    const continueButton = theory.querySelector('[data-s39-theory-continue]');
    continueButton.addEventListener('click', (event) => {
      if (!checkComplete) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      theory.querySelector('[data-s39-theory-foot]').textContent = 'Спасибо · продолжай знакомство';
    }, true);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupTheory, { once: true });
  else setupTheory();
})();
