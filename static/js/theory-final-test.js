(() => {
  const courseId = window.PYTHON_FINAL_TEST_COURSE_ID || 6;
  let pythonFinalTestTasks = [];
  let currentTaskIndex = 0;
  const userAnswers = {}; // { [taskId]: string | { [key]: string } }

  function escapeFinalTestText(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function formatExplanationHtml(value) {
    if (!value) return '';
    return escapeFinalTestText(value)
      .replace(/&lt;code&gt;/g, '<code class="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-900 font-mono text-xs font-bold">')
      .replace(/&lt;\/code&gt;/g, '</code>')
      .replace(/&lt;b&gt;/g, '<b>')
      .replace(/&lt;\/b&gt;/g, '</b>');
  }

  function finalTestLevelLabel(level) {
    const labels = {
      'базовый': 'База',
      'егэ-практика': 'ЕГЭ-практика',
    };
    return labels[level] || level || 'Практика';
  }

  function pythonTaskAnnotation(topic) {
    const value = String(topic || '').toLowerCase();
    if (value.includes('перем') || value.includes('тип') || value.includes('синтакс')) return 'типы данных, операции и базовый синтаксис';
    if (value.includes('арифмет') || value.includes('делен')) return 'целочисленная арифметика и остатки';
    if (value.includes('ввод') || value.includes('вывод') || value.includes('print') || value.includes('input')) return 'ввод-вывод, параметры sep и end';
    if (value.includes('логик') || value.includes('ветвлен') || value.includes('услов')) return 'логические операторы, приоритеты и ветвления if-elif-else';
    if (value.includes('цикл') || value.includes('while') || value.includes('for') || value.includes('range')) return 'циклы, счетчики, накопители и границы range';
    if (value.includes('строк') || value.includes('срез')) return 'индексация, срезы и строковые методы';
    if (value.includes('списк') || value.includes('коллекц')) return 'методы списков append, pop, sort и срезы';
    if (value.includes('функц') || value.includes('подпрограм')) return 'параметры, вызов и возврат значений через return';
    if (value.includes('генератор') || value.includes('comprehension')) return 'генераторы списков и фильтрация';
    return 'практическое применение Python в заданиях ЕГЭ';
  }

  function isTaskAnswered(task) {
    const ans = userAnswers[task.id];
    if (!ans) return false;
    if (task.type === 'matching') {
      return typeof ans === 'object' && Object.keys(ans).length === 4;
    }
    return String(ans).trim().length > 0;
  }

  function countAnsweredTasks() {
    return pythonFinalTestTasks.filter(isTaskAnswered).length;
  }

  function renderStepperPills() {
    const pillsContainer = document.getElementById('python-stepper-pills');
    if (!pillsContainer || !pythonFinalTestTasks.length) return;

    pillsContainer.innerHTML = pythonFinalTestTasks.map((task, idx) => {
      const isActive = idx === currentTaskIndex;
      const isAnswered = isTaskAnswered(task);
      const classes = [
        'tx-stepper-pill',
        isActive ? 'is-active' : '',
        isAnswered ? 'is-answered' : '',
      ].filter(Boolean).join(' ');

      return `<button type="button" class="${classes}" data-stepper-index="${idx}" title="Задание ${idx + 1}">${idx + 1}</button>`;
    }).join('');

    pillsContainer.querySelectorAll('[data-stepper-index]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.stepperIndex, 10);
        if (!isNaN(idx)) goToTask(idx);
      });
    });
  }

  function updateStepperStatus() {
    const counter = document.getElementById('python-stepper-counter');
    const answeredCount = document.getElementById('python-stepper-answered-count');
    const prevBtn = document.getElementById('python-stepper-prev');
    const nextBtn = document.getElementById('python-stepper-next');

    if (counter) counter.textContent = `Задание ${currentTaskIndex + 1} из ${pythonFinalTestTasks.length}`;
    if (answeredCount) answeredCount.textContent = `Отвечено: ${countAnsweredTasks()} / ${pythonFinalTestTasks.length}`;
    if (prevBtn) {
      prevBtn.disabled = currentTaskIndex === 0;
      prevBtn.classList.toggle('opacity-50', currentTaskIndex === 0);
      prevBtn.classList.toggle('cursor-not-allowed', currentTaskIndex === 0);
    }
    if (nextBtn) {
      nextBtn.disabled = currentTaskIndex === pythonFinalTestTasks.length - 1;
      nextBtn.classList.toggle('opacity-50', currentTaskIndex === pythonFinalTestTasks.length - 1);
      nextBtn.classList.toggle('cursor-not-allowed', currentTaskIndex === pythonFinalTestTasks.length - 1);
    }
  }

  function renderActiveTaskCard() {
    const container = document.getElementById('python-active-card-container');
    if (!container || !pythonFinalTestTasks.length) return;

    const task = pythonFinalTestTasks[currentTaskIndex];
    const isSingleChoice = task.type === 'single_choice';
    const isMatching = task.type === 'matching';

    let interactionHtml = '';
    if (isSingleChoice && task.options && task.options.length) {
      const currentAns = userAnswers[task.id] || '';
      interactionHtml = `
        <div class="mt-5 pt-4 border-t border-slate-100">
          <label class="block text-xs font-black uppercase tracking-wider text-slate-500 mb-3">Выбери один вариант ответа:</label>
          <div class="tx-choice-grid" role="radiogroup">
            ${task.options.map(opt => {
              const isChecked = currentAns === opt.id;
              return `
                <label class="tx-choice-card ${isChecked ? 'is-checked' : ''}">
                  <input type="radio" name="active_task_${escapeFinalTestText(task.id)}" value="${escapeFinalTestText(opt.id)}" ${isChecked ? 'checked' : ''} class="h-4 w-4 text-indigo-600 border-slate-300 focus:ring-0">
                  <span class="tx-choice-badge ${isChecked ? 'is-checked' : ''}">${escapeFinalTestText(opt.id)}</span>
                  <span class="tx-choice-text">${escapeFinalTestText(opt.text)}</span>
                </label>
              `;
            }).join('')}
          </div>
        </div>
      `;
    } else if (isMatching && task.matching_left && task.matching_right) {
      const currentMatches = userAnswers[task.id] || {};
      interactionHtml = `
        <div class="mt-5 pt-4 border-t border-slate-100">
          <div class="flex items-center justify-between mb-3">
            <span class="text-xs font-black uppercase tracking-wider text-slate-600">Сопоставь фрагменты (1–4) с ответами (A–D):</span>
            <span class="text-[11px] font-bold text-slate-400">Нажми на поле выбора справа</span>
          </div>
          <div class="space-y-2.5">
            ${task.matching_left.map((left, rowIdx) => {
              const right = task.matching_right[rowIdx] || {};
              const selectedLetter = currentMatches[left.id] || '';
              return `
                <div class="matching-pair-row">
                  <div class="matching-card-left">
                    <span class="matching-badge-left">${escapeFinalTestText(left.id)}</span>
                    <div class="matching-text-left">${escapeFinalTestText(left.text)}</div>
                    <div class="tx-custom-select" data-matching-key="${escapeFinalTestText(left.id)}">
                      <button type="button" class="tx-cs-trigger ${selectedLetter ? 'is-selected' : ''}" aria-haspopup="listbox" aria-expanded="false" title="Выбрать букву ответа">
                        <span class="tx-cs-value">${selectedLetter || '—'}</span>
                        <i class="ph-bold ph-caret-down tx-cs-arrow"></i>
                      </button>
                      <div class="tx-cs-menu hidden" role="listbox">
                        <button type="button" class="tx-cs-item ${!selectedLetter ? 'is-active' : ''}" data-value="">
                          <span class="tx-cs-badge tx-badge-none">—</span>
                          <span class="tx-cs-label text-slate-400 font-semibold">Сбросить выбор</span>
                        </button>
                        ${task.matching_right.map(rOpt => {
                          const isItemActive = selectedLetter === rOpt.id;
                          return `
                            <button type="button" class="tx-cs-item ${isItemActive ? 'is-active' : ''}" data-value="${escapeFinalTestText(rOpt.id)}">
                              <span class="tx-cs-badge tx-badge-letter">${escapeFinalTestText(rOpt.id)}</span>
                              <span class="tx-cs-label">${escapeFinalTestText(rOpt.text || '')}</span>
                              ${isItemActive ? '<i class="ph-bold ph-check tx-cs-check"></i>' : ''}
                            </button>
                          `;
                        }).join('')}
                      </div>
                    </div>
                  </div>
                  <div class="matching-card-right">
                    <span class="matching-badge-right">${escapeFinalTestText(right.id || '')}</span>
                    <div class="matching-text-right">${escapeFinalTestText(right.text || '')}</div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    } else {
      const currentVal = userAnswers[task.id] || '';
      interactionHtml = `
        <div class="mt-5 pt-4 border-t border-slate-100">
          <label class="block text-xs font-black uppercase tracking-wider text-slate-600 mb-2" for="active-python-answer">Твой точный ответ:</label>
          <input type="text" id="active-python-answer" value="${escapeFinalTestText(currentVal)}" class="tx-answer-input" placeholder="Введи полученное число или строку…" spellcheck="false" autocomplete="off">
        </div>
      `;
    }

    let typeBadge = isSingleChoice
      ? '<span class="tx-task-type-badge tx-badge-blue"><i class="ph-bold ph-list-dashes"></i> Выбор варианта</span>'
      : (isMatching
        ? '<span class="tx-task-type-badge tx-badge-purple"><i class="ph-bold ph-arrows-left-right"></i> Сопоставление пар</span>'
        : '<span class="tx-task-type-badge tx-badge-emerald"><i class="ph-bold ph-pencil-simple-line"></i> Точный ответ</span>');

    container.innerHTML = `
      <article class="final-test-task" data-card-task-id="${escapeFinalTestText(task.id)}">
        <div class="flex flex-wrap items-center justify-between gap-2.5 pb-3 border-b border-slate-100">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tx-task-num-badge">№ ${currentTaskIndex + 1}</span>
            <span class="tx-task-topic-badge"><i class="ph-bold ph-book-open"></i> ${escapeFinalTestText(task.topic)}</span>
            ${typeBadge}
            <span class="tx-task-level-badge">${escapeFinalTestText(finalTestLevelLabel(task.level))}</span>
          </div>
          <div class="text-xs font-semibold text-slate-400 flex items-center gap-1.5 ml-auto">
            <i class="ph-bold ph-crosshair-simple text-indigo-500"></i>
            <span>${escapeFinalTestText(pythonTaskAnnotation(task.topic))}</span>
          </div>
        </div>

        <div class="mt-4 mb-3">
          <h3 class="text-xl sm:text-2xl font-black text-slate-900 tracking-tight leading-snug">${escapeFinalTestText(task.title)}</h3>
          <div class="mt-2.5 text-base sm:text-[16.5px] font-semibold text-slate-800 leading-relaxed task-content-html">${task.content_html || '<span class="text-slate-400">Условие задания не заполнено.</span>'}</div>
        </div>

        ${interactionHtml}
      </article>
    `;

    // Ensure language-python class on <code> tags inside <pre> for Prism
    container.querySelectorAll('pre code').forEach(codeEl => {
      if (!codeEl.className.includes('language-')) {
        codeEl.classList.add('language-python');
      }
    });
    if (window.Prism) {
      try {
        if (typeof window.Prism.highlightAllUnder === 'function') {
          window.Prism.highlightAllUnder(container);
        } else if (typeof window.Prism.highlightAll === 'function') {
          window.Prism.highlightAll();
        }
      } catch (e) {}
    }

    // Attach listeners
    if (isSingleChoice) {
      container.querySelectorAll(`input[name="active_task_${task.id}"]`).forEach(radio => {
        radio.addEventListener('change', () => {
          userAnswers[task.id] = radio.value;
          renderActiveTaskCard();
          renderStepperPills();
          updateStepperStatus();
        });
      });
    } else if (isMatching) {
      container.querySelectorAll('.tx-custom-select').forEach(cs => {
        const trigger = cs.querySelector('.tx-cs-trigger');
        const menu = cs.querySelector('.tx-cs-menu');
        const key = cs.dataset.matchingKey;

        trigger.addEventListener('click', (e) => {
          e.stopPropagation();
          const isCurrentlyOpen = !menu.classList.contains('hidden');
          // Close all open menus first
          container.querySelectorAll('.tx-cs-menu').forEach(m => m.classList.add('hidden'));
          container.querySelectorAll('.tx-cs-trigger').forEach(t => t.setAttribute('aria-expanded', 'false'));
          if (!isCurrentlyOpen) {
            menu.classList.remove('hidden');
            trigger.setAttribute('aria-expanded', 'true');
          }
        });

        menu.querySelectorAll('.tx-cs-item').forEach(item => {
          item.addEventListener('click', (e) => {
            e.stopPropagation();
            const val = item.dataset.value;
            userAnswers[task.id] = userAnswers[task.id] || {};
            if (val) {
              userAnswers[task.id][key] = val;
            } else {
              delete userAnswers[task.id][key];
            }
            menu.classList.add('hidden');
            trigger.setAttribute('aria-expanded', 'false');
            renderActiveTaskCard();
            renderStepperPills();
            updateStepperStatus();
          });
        });
      });
    } else {
      const input = document.getElementById('active-python-answer');
      if (input) {
        input.addEventListener('input', () => {
          const val = input.value.trim();
          if (val) {
            userAnswers[task.id] = val;
          } else {
            delete userAnswers[task.id];
          }
          renderStepperPills();
          updateStepperStatus();
        });
      }
    }

  }

  // Close custom dropdowns on click outside
  document.addEventListener('click', () => {
    document.querySelectorAll('.tx-cs-menu:not(.hidden)').forEach(m => {
      m.classList.add('hidden');
      const trigger = m.closest('.tx-custom-select')?.querySelector('.tx-cs-trigger');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  });

  function goToTask(index) {
    if (index < 0 || index >= pythonFinalTestTasks.length) return;
    currentTaskIndex = index;
    renderActiveTaskCard();
    renderStepperPills();
    updateStepperStatus();
  }

  function formatResultAnswer(ans, type) {
    if (ans == null || ans === '') return '<span class="text-slate-400 font-sans italic font-medium">не отвечено</span>';
    if (type === 'matching' && typeof ans === 'object') {
      const keys = ['1', '2', '3', '4'];
      const pairs = keys.map(k => `${k} → ${ans[k] || '—'}`).join(', ');
      return pairs || '<span class="text-slate-400 font-sans italic font-medium">не отвечено</span>';
    }
    if (type === 'single_choice') {
      return `Вариант ${escapeFinalTestText(ans)}`;
    }
    return escapeFinalTestText(ans);
  }

  function renderReviewInspector(taskIndex, resultById) {
    const inspector = document.getElementById('tx-result-inspector');
    if (!inspector || !pythonFinalTestTasks[taskIndex]) return;

    const task = pythonFinalTestTasks[taskIndex];
    const res = resultById[task.id] || {};
    const isCorrect = !!(res.correct || res.is_correct);
    const userAns = res.user_answer !== undefined ? res.user_answer : userAnswers[task.id];
    const correctAns = res.correct_answer !== undefined ? res.correct_answer : task.answer;
    const explanation = res.explanation || task.explanation || '';
    const isSingleChoice = task.type === 'single_choice';
    const isMatching = task.type === 'matching';

    // Detailed Review for Answers: Options / Matching / Inputs
    let answersReviewHtml = '';

    if (isSingleChoice && task.options && task.options.length) {
      answersReviewHtml = `
        <div class="mt-4 pt-4 border-t border-slate-200/80">
          <div class="flex items-center justify-between mb-3">
            <span class="text-xs font-black uppercase tracking-wider text-slate-700">
              Варианты ответов и твой выбор:
            </span>
            <span class="text-[11px] font-semibold text-slate-400">
              ${isCorrect ? 'Ты выбрал правильный вариант' : (userAns ? 'Выбран неверный вариант' : 'Ответ не был выбран')}
            </span>
          </div>
          <div class="tx-choice-grid" role="group">
            ${task.options.map(opt => {
              const wasSelected = String(userAns || '').trim().toUpperCase() === String(opt.id).trim().toUpperCase();
              const isCorrectOpt = String(correctAns || '').trim().toUpperCase() === String(opt.id).trim().toUpperCase();

              let cardClasses = 'tx-choice-card cursor-default select-none transition-none';
              let badgeClasses = 'tx-choice-badge';
              let tagHtml = '';

              if (wasSelected && isCorrectOpt) {
                cardClasses += ' border-2 border-emerald-500 bg-emerald-50/90 shadow-2xs';
                badgeClasses += ' bg-emerald-600 text-white font-black';
                tagHtml = `<span class="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-black bg-emerald-100 text-emerald-800 border border-emerald-300"><i class="ph-bold ph-check"></i> Твой ответ (верно)</span>`;
              } else if (wasSelected && !isCorrectOpt) {
                cardClasses += ' border-2 border-rose-400 bg-rose-50 shadow-2xs';
                badgeClasses += ' bg-rose-600 text-white font-black';
                tagHtml = `<span class="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-black bg-rose-100 text-rose-800 border border-rose-300"><i class="ph-bold ph-x"></i> Твой выбор (ошибка)</span>`;
              } else if (!wasSelected && isCorrectOpt) {
                cardClasses += ' border-2 border-emerald-500 bg-emerald-50/70 shadow-2xs';
                badgeClasses += ' bg-emerald-600 text-white font-black';
                tagHtml = `<span class="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-black bg-emerald-600 text-white shadow-2xs"><i class="ph-bold ph-check"></i> Правильный ответ</span>`;
              } else {
                cardClasses += ' border border-slate-200 bg-white/70 opacity-60';
                badgeClasses += ' bg-slate-100 text-slate-500';
              }

              return `
                <div class="${cardClasses}">
                  <span class="${badgeClasses}">${escapeFinalTestText(opt.id)}</span>
                  <span class="tx-choice-text font-bold text-slate-800">${escapeFinalTestText(opt.text)}</span>
                  ${tagHtml}
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    } else if (isMatching && task.matching_left && task.matching_right) {
      const stuMatch = (typeof userAns === 'object' && userAns !== null) ? userAns : {};
      const expMatch = (typeof correctAns === 'object' && correctAns !== null) ? correctAns : {};
      const rightById = Object.fromEntries(task.matching_right.map(r => [r.id, r.text]));

      answersReviewHtml = `
        <div class="mt-4 pt-4 border-t border-slate-200/80">
          <div class="flex items-center justify-between mb-3">
            <span class="text-xs font-black uppercase tracking-wider text-slate-700">
              Сопоставление пар и проверка ответов:
            </span>
            <span class="text-[11px] font-semibold text-slate-400">
              По 1 баллу за полностью верное сопоставление всех 4 пар
            </span>
          </div>
          <div class="space-y-2.5">
            ${task.matching_left.map(left => {
              const uLetter = String(stuMatch[left.id] || '').trim().toUpperCase();
              const cLetter = String(expMatch[left.id] || '').trim().toUpperCase();
              const isPairCorrect = uLetter && uLetter === cLetter;
              const uText = rightById[uLetter] || (uLetter ? 'Неизвестный вариант' : '— не выбрано —');
              const cText = rightById[cLetter] || '';

              return `
                <div class="p-3 rounded-2xl border-2 ${isPairCorrect ? 'border-emerald-200 bg-emerald-50/40' : 'border-rose-200 bg-rose-50/40'} flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div class="flex items-center gap-2.5 min-w-0 md:max-w-[45%]">
                    <span class="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-indigo-600 text-white font-mono text-xs font-black shrink-0">
                      ${escapeFinalTestText(left.id)}
                    </span>
                    <span class="font-bold text-slate-900 text-sm truncate" title="${escapeFinalTestText(left.text)}">
                      ${escapeFinalTestText(left.text)}
                    </span>
                  </div>
                  <div class="flex flex-col sm:flex-row sm:items-center gap-2 text-xs font-semibold">
                    <div class="px-2.5 py-1.5 rounded-xl border ${isPairCorrect ? 'border-emerald-300 bg-white text-emerald-950' : 'border-rose-300 bg-white text-rose-950'} flex items-center gap-1.5">
                      <span class="text-[10px] font-black uppercase tracking-wider text-slate-400">Твой выбор:</span>
                      <span class="font-mono font-black ${isPairCorrect ? 'text-emerald-700' : 'text-rose-700'}">[${escapeFinalTestText(uLetter || '—')}]</span>
                      <span class="truncate max-w-[200px]" title="${escapeFinalTestText(uText)}">${escapeFinalTestText(uText)}</span>
                    </div>
                    ${!isPairCorrect ? `
                      <div class="px-2.5 py-1.5 rounded-xl border border-emerald-300 bg-emerald-100/70 text-emerald-950 flex items-center gap-1.5">
                        <span class="text-[10px] font-black uppercase tracking-wider text-emerald-700">Правильно:</span>
                        <span class="font-mono font-black text-emerald-800">[${escapeFinalTestText(cLetter)}]</span>
                        <span class="truncate max-w-[200px]" title="${escapeFinalTestText(cText)}">${escapeFinalTestText(cText)}</span>
                      </div>
                    ` : ''}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    } else {
      answersReviewHtml = `
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-3 border-t border-slate-200/80">
          <div class="p-3.5 rounded-xl border-2 ${isCorrect ? 'border-emerald-200 bg-emerald-50/50' : 'border-rose-200 bg-rose-50/50'}">
            <div class="text-[10px] font-black uppercase tracking-wider ${isCorrect ? 'text-emerald-700' : 'text-rose-700'} mb-1">
              Твой ответ:
            </div>
            <div class="font-mono text-sm font-black text-slate-900">${formatResultAnswer(userAns, task.type)}</div>
          </div>
          ${!isCorrect ? `
            <div class="p-3.5 rounded-xl border-2 border-emerald-200 bg-emerald-50/50">
              <div class="text-[10px] font-black uppercase tracking-wider text-emerald-700 mb-1">
                Правильный ответ:
              </div>
              <div class="font-mono text-sm font-black text-emerald-950">${formatResultAnswer(correctAns, task.type)}</div>
            </div>
          ` : ''}
        </div>
      `;
    }

    inspector.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-200">
        <div class="flex items-center gap-2.5 flex-wrap">
          <span class="inline-flex h-7 px-3 items-center justify-center rounded-xl ${isCorrect ? 'bg-emerald-600' : 'bg-rose-600'} text-white text-xs font-black shadow-2xs">
            Задание ${taskIndex + 1}
          </span>
          <span class="text-sm font-black text-slate-900">${escapeFinalTestText(task.title)}</span>
          <span class="text-slate-300">·</span>
          <span class="text-xs font-bold text-slate-500">${escapeFinalTestText(task.topic)}</span>
        </div>
        <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-black ${isCorrect ? 'bg-emerald-100 text-emerald-800 border border-emerald-300' : 'bg-rose-100 text-rose-800 border border-rose-300'}">
          <i class="ph-bold ${isCorrect ? 'ph-check' : 'ph-x'}"></i>
          ${isCorrect ? 'Верно (+1 балл)' : 'Ошибка (0 баллов)'}
        </span>
      </div>

      <!-- Task Condition & Code -->
      <div class="mt-3.5 mb-4 text-[15px] font-semibold text-slate-800 leading-relaxed final-test-task p-0 border-0 shadow-none bg-transparent m-0">
        <div class="task-content-html">${task.content_html || escapeFinalTestText(task.prompt || '')}</div>
      </div>

      <!-- Options / Matching / Inputs Detailed Review -->
      ${answersReviewHtml}

      <!-- Explanation -->
      ${explanation ? `
        <div class="mt-4 p-4 rounded-xl border border-indigo-200 bg-indigo-50/50 text-xs sm:text-[13px] leading-relaxed text-slate-800">
          <span class="font-black text-indigo-950 flex items-center gap-1.5 mb-1">
            <i class="ph-bold ph-lightbulb text-indigo-600 text-sm"></i> Пояснение и логика решения:
          </span>
          ${formatExplanationHtml(explanation)}
        </div>
      ` : ''}
    `;

    inspector.querySelectorAll('pre code').forEach(codeEl => {
      if (!codeEl.className.includes('language-')) {
        codeEl.classList.add('language-python');
      }
    });
    if (window.Prism) {
      try {
        if (typeof window.Prism.highlightAllUnder === 'function') {
          window.Prism.highlightAllUnder(inspector);
        } else if (typeof window.Prism.highlightAll === 'function') {
          window.Prism.highlightAll();
        }
      } catch (e) {}
    }
  }

  function renderPythonFinalTestResultCard(payload) {
    const review = document.getElementById('python-final-test-review');
    if (!review) return;

    const passed = !!payload.passed;
    const correct = payload.correct != null ? payload.correct : (payload.score || 0);
    const total = payload.total || 20;
    const percent = Math.round((correct / total) * 100);
    const attemptNum = payload.attempt_number || 1;
    const blockScores = payload.block_scores || {};
    const results = payload.results || payload.details || [];
    const resultById = Object.fromEntries(results.map(r => [r.id || r.task_id, r]));

    const blockNames = {
      '1': 'Синтаксис и типы',
      '2': 'Логика и ветвления',
      '3': 'Циклы for и while',
      '4': 'Строки, списки и функции',
    };

    // Pick first wrong task to inspect, or first task if all correct
    let activeReviewIndex = results.findIndex(r => !r.correct && !r.is_correct);
    if (activeReviewIndex === -1) activeReviewIndex = 0;

    review.innerHTML = `
      <div class="tx-result-hero ${passed ? 'is-passed' : 'is-failed'}">
        <!-- Hero Header -->
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-5 border-b border-slate-200/80">
          <div class="flex items-center gap-4">
            <div class="tx-result-icon ${passed ? 'is-passed' : 'is-failed'}">
              <i class="ph-bold ${passed ? 'ph-seal-check' : 'ph-x-circle'}"></i>
            </div>
            <div>
              <div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider ${passed ? 'bg-emerald-100 text-emerald-800 border border-emerald-300' : 'bg-rose-100 text-rose-800 border border-rose-300'}">
                <i class="ph-fill ${passed ? 'ph-check-circle' : 'ph-warning-circle'}"></i>
                ${passed ? 'Зачёт получен' : 'Тест не сдан'}
              </div>
              <h2 class="text-xl sm:text-2xl font-black text-slate-900 mt-1">
                ${passed ? 'Поздравляем с успешной сдачей!' : 'Попытка завершена: порог 90% не достигнут'}
              </h2>
              <p class="text-xs sm:text-sm font-semibold text-slate-500 mt-0.5">
                ${passed ? 'Результат зафиксирован в профиле и доступен преподавателю.' : 'Для зачёта требуется решить минимум 18 из 20 (90%). Все попытки и ответы сохранены для преподавателя.'}
              </p>
            </div>
          </div>

          <div class="tx-result-score-badge ${passed ? 'is-passed' : 'is-failed'} text-center self-start sm:self-auto">
            <div class="text-[10px] font-black uppercase tracking-wider text-slate-400">Попытка №${attemptNum}</div>
            <div class="text-3xl font-black text-slate-900 tracking-tight">${correct} <span class="text-lg font-bold text-slate-400">/ ${total}</span></div>
            <div class="text-xs font-black ${passed ? 'text-emerald-700' : 'text-rose-600'}">${percent}% (порог 90%)</div>
          </div>
        </div>

        ${payload.new_achievement ? `
          <div class="mt-4 p-4 rounded-2xl bg-gradient-to-r from-amber-400 via-amber-300 to-yellow-400 text-slate-950 shadow-md border-2 border-amber-300/80 flex items-center gap-3.5 animate-fadeIn">
            <div class="w-12 h-12 rounded-xl bg-white/95 shadow-sm flex items-center justify-center text-2xl text-amber-600 flex-shrink-0">
              <i class="ph-fill ph-crown"></i>
            </div>
            <div class="min-w-0 flex-1">
              <div class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-900 text-amber-300 text-[10px] font-black uppercase tracking-wider mb-1">
                <i class="ph-fill ph-sparkle"></i> Секретная ачивка разблокирована!
              </div>
              <div class="text-base sm:text-lg font-black text-slate-900 tracking-tight leading-snug">
                ${escapeFinalTestText(payload.new_achievement.title || 'Повелитель Питона')}
              </div>
              <div class="text-xs font-bold text-slate-800 leading-tight flex items-center gap-2 flex-wrap">
                <span>${escapeFinalTestText(payload.new_achievement.desc || 'Сдать итоговое тестирование по программированию на 90% и выше')}</span>
                <span class="inline-flex items-center gap-1 font-black text-slate-950 bg-white/90 px-2 py-0.5 rounded-md text-[11px] shadow-2xs border border-amber-200">
                  <i class="ph-bold ph-lightning text-amber-600"></i> +${payload.new_achievement.xp_reward || 50} XP
                </span>
              </div>
            </div>
          </div>
        ` : ''}

        <!-- 4-Block Breakdown Mini Cards -->
        <div class="mt-5 pt-1">
          <div class="text-xs font-black uppercase tracking-wider text-slate-400 mb-3 flex items-center justify-between">
            <span>Результаты по 4 тематическим блокам:</span>
            <span class="text-[11px] font-semibold text-slate-500">По 5 заданий в каждом блоке</span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
            ${['1', '2', '3', '4'].map(bKey => {
              const bData = blockScores[bKey] || { correct: 0, total: 5, title: blockNames[bKey] };
              const bPct = Math.round(((bData.correct || 0) / (bData.total || 5)) * 100);
              return `
                <div class="p-3.5 rounded-xl border-2 border-slate-200 bg-white shadow-2xs">
                  <div class="text-[11px] font-extrabold text-slate-600 truncate mb-1">
                    ${escapeFinalTestText(bData.title || blockNames[bKey])}
                  </div>
                  <div class="flex items-baseline justify-between mb-1.5">
                    <span class="text-base font-black text-slate-900">${bData.correct || 0} <span class="text-xs text-slate-400">/ ${bData.total || 5}</span></span>
                    <span class="text-xs font-black ${bData.correct >= 4 ? 'text-emerald-700' : 'text-slate-600'}">${bPct}%</span>
                  </div>
                  <div class="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                    <div class="h-1.5 rounded-full ${bData.correct >= 4 ? 'bg-emerald-500' : 'bg-indigo-500'}" style="width: ${bPct}%"></div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>

        <!-- 20 Interactive Question Selector Pills -->
        <div class="mt-6 pt-5 border-t border-slate-200/80">
          <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div class="text-xs font-black uppercase tracking-wider text-slate-700">
              Разбор решений: <span class="text-slate-400 font-semibold text-[11px] normal-case">(нажми на номер задания для просмотра условия и ответа)</span>
            </div>
            <div class="flex items-center gap-3 text-xs font-bold">
              <span class="inline-flex items-center gap-1 text-emerald-700"><i class="ph-bold ph-check"></i> ${correct} верно</span>
              <span class="inline-flex items-center gap-1 text-rose-600"><i class="ph-bold ph-x"></i> ${total - correct} ошибок</span>
            </div>
          </div>
          <div id="tx-result-pills-row" class="flex flex-wrap gap-2">
            ${pythonFinalTestTasks.map((t, idx) => {
              const r = resultById[t.id] || {};
              const ok = !!(r.correct || r.is_correct);
              const active = idx === activeReviewIndex;
              return `
                <button type="button" class="tx-res-pill ${ok ? 'is-correct' : 'is-wrong'} ${active ? 'is-active' : ''}" data-review-task-index="${idx}" title="Задание ${idx + 1}: ${ok ? 'Верно' : 'Ошибка'}">
                  ${idx + 1}
                </button>
              `;
            }).join('')}
          </div>
        </div>

        <!-- Focused Detail Inspector Drawer -->
        <div id="tx-result-inspector" class="mt-5"></div>

        <!-- Footer Actions Bar -->
        <div class="mt-6 pt-4 border-t border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div class="text-xs text-slate-500 font-medium">
            <i class="ph-bold ph-shield-check text-indigo-600 mr-1"></i>
            Новый вариант обновляется <b>минимум на 80%</b> и отдаёт предпочтение ранее не встречавшимся заданиям.
          </div>
          <div class="flex items-center gap-3">
            ${!passed ? `
              <button type="button" id="python-final-test-retry-btn" class="tx-button tx-button-3d">
                <i class="ph-bold ph-arrows-clockwise text-lg"></i> Собрать новый вариант
              </button>
            ` : `
              <button type="button" id="python-final-test-retry-btn" class="tx-soft-button text-xs font-black">
                <i class="ph-bold ph-arrow-counter-clockwise"></i> Потренироваться ещё (новый вариант)
              </button>
            `}
          </div>
        </div>
      </div>
    `;

    // Render initial inspector
    renderReviewInspector(activeReviewIndex, resultById);

    // Pill click handlers
    const pillsRow = document.getElementById('tx-result-pills-row');
    if (pillsRow) {
      pillsRow.querySelectorAll('[data-review-task-index]').forEach(pill => {
        pill.addEventListener('click', () => {
          const idx = parseInt(pill.dataset.reviewTaskIndex, 10);
          if (isNaN(idx)) return;
          activeReviewIndex = idx;
          pillsRow.querySelectorAll('.tx-res-pill').forEach(p => p.classList.remove('is-active'));
          pill.classList.add('is-active');
          renderReviewInspector(activeReviewIndex, resultById);
        });
      });
    }

    // Retry button handler inside card
    document.getElementById('python-final-test-retry-btn')?.addEventListener('click', () => {
      loadPythonFinalTest(true);
    });
  }

  async function loadPythonFinalTest(retry = false) {
    const startButton = document.getElementById('python-final-test-start');
    const prestart = document.getElementById('python-final-test-prestart');
    const results = document.getElementById('python-final-test-results');
    const status = document.getElementById('python-final-test-status');
    const stepperWrap = document.getElementById('python-final-test-stepper-wrap');
    const review = document.getElementById('python-final-test-review');
    const submitButton = document.getElementById('python-final-test-submit');
    const score = document.getElementById('python-final-test-score');
    const shell = document.getElementById('python-final-test');
    if (!results || !status) return;

    if (startButton) {
      startButton.disabled = true;
      startButton.classList.add('opacity-70');
    }
    status.classList.remove('hidden');
    status.innerHTML = '<i class="ph-bold ph-spinner-gap animate-spin mr-1.5"></i> Собираю персональный вариант из банка заданий…';
    stepperWrap?.classList.add('hidden');
    review?.classList.add('hidden');
    submitButton?.classList.remove('hidden');
    score?.classList.add('hidden');

    try {
      const retryQuery = retry ? '&retry=1' : '';
      const response = await fetch(`/api/python-programming/final-test?course_id=${courseId}${retryQuery}`, {
        headers: { 'Accept': 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Не удалось собрать вариант');

      pythonFinalTestTasks = payload.tasks || [];
      results.classList.remove('hidden');

      if (payload.passed) {
        shell?.classList.add('final-test-passed');
        if (prestart) prestart.classList.add('hidden');
        stepperWrap?.classList.add('hidden');
        submitButton?.classList.add('hidden');
        review?.classList.remove('hidden');
        renderPythonFinalTestResultCard(payload);
        status.innerHTML = '<i class="ph-fill ph-seal-check mr-1.5 text-emerald-500"></i> Итоговый тест успешно пройден (порог 90% выполнен).';
      } else {
        if (prestart) prestart.classList.add('hidden');
        stepperWrap?.classList.remove('hidden');
        currentTaskIndex = 0;
        // reset answers if new variant
        for (const k in userAnswers) delete userAnswers[k];
        renderStepperPills();
        renderActiveTaskCard();
        updateStepperStatus();
        status.innerHTML = `<i class="ph-bold ph-lock-key mr-1.5 text-indigo-600"></i> Вариант сформирован: ${payload.size} заданий по 4 блокам (минимум 80% новых). Порог сдачи: 18 из 20 (90%).`;
      }
      results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      status.innerHTML = `<i class="ph-bold ph-warning-circle mr-1.5 text-rose-500"></i> ${escapeFinalTestText(error.message || 'Произошла ошибка. Попробуй ещё раз.')}`;
    } finally {
      if (startButton) {
        startButton.disabled = false;
        startButton.classList.remove('opacity-70');
      }
    }
  }

  async function gradePythonFinalTest() {
    const submitButton = document.getElementById('python-final-test-submit');
    const score = document.getElementById('python-final-test-score');
    const stepperWrap = document.getElementById('python-final-test-stepper-wrap');
    const review = document.getElementById('python-final-test-review');
    const shell = document.getElementById('python-final-test');
    if (!submitButton || !score || !pythonFinalTestTasks.length) return;

    submitButton.disabled = true;
    submitButton.classList.add('opacity-70');
    score.classList.remove('hidden');
    score.textContent = 'Проверяю ответы…';

    try {
      const response = await fetch('/api/python-programming/final-test/grade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ course_id: courseId, answers: userAnswers }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Не удалось проверить ответы');

      stepperWrap?.classList.add('hidden');
      submitButton.classList.add('hidden');
      review?.classList.remove('hidden');
      score.classList.add('hidden');

      renderPythonFinalTestResultCard(payload);
      review?.classList.toggle('final-test-review-success', payload.passed);
      shell?.classList.toggle('final-test-passed', payload.passed);
      review?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      score.textContent = error.message || 'Не удалось проверить ответы.';
    } finally {
      submitButton.disabled = false;
      submitButton.classList.remove('opacity-70');
    }
  }

  // Prev / Next button listeners
  document.getElementById('python-stepper-prev')?.addEventListener('click', () => {
    if (currentTaskIndex > 0) goToTask(currentTaskIndex - 1);
  });
  document.getElementById('python-stepper-next')?.addEventListener('click', () => {
    if (currentTaskIndex < pythonFinalTestTasks.length - 1) goToTask(currentTaskIndex + 1);
  });

  // Keyboard navigation: ArrowLeft / ArrowRight
  window.addEventListener('keydown', (e) => {
    if (!pythonFinalTestTasks.length) return;
    const stepperWrap = document.getElementById('python-final-test-stepper-wrap');
    if (!stepperWrap || stepperWrap.classList.contains('hidden')) return;

    const tag = (document.activeElement?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (e.key === 'ArrowLeft' && currentTaskIndex > 0) {
      goToTask(currentTaskIndex - 1);
    } else if (e.key === 'ArrowRight' && currentTaskIndex < pythonFinalTestTasks.length - 1) {
      goToTask(currentTaskIndex + 1);
    }
  });

  document.getElementById('python-final-test-start')?.addEventListener('click', () => loadPythonFinalTest(false));
  document.getElementById('python-final-test-submit')?.addEventListener('click', gradePythonFinalTest);
  document.getElementById('python-final-test-retry')?.addEventListener('click', () => loadPythonFinalTest(true));
})();
