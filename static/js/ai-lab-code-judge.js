(() => {
  const root = document.getElementById('boo-code-judge');
  if (!root) return;
  const initial = JSON.parse(document.getElementById('cj-initial-data').textContent || '{}');
  const api = '/admin/ai-lab/api/code-judge';
  const $ = (selector) => root.querySelector(selector);
  const fields = {
    select: $('#cj-set-select'), title: $('#cj-title'), description: $('#cj-description'),
    assignment: $('#cj-assignment'),
    mode: $('#cj-mode'), functionName: $('#cj-function'), comparator: $('#cj-comparator'),
    tolerance: $('#cj-tolerance'), code: $('#cj-code'), run: $('#cj-run'), submit: $('#cj-submit')
  };
  const state = {
    enabled: initial.enabled === true, testSets: initial.test_sets || [],
    testSet: initial.selected ? structuredClone(initial.selected) : null,
    history: initial.history || [], runner: initial.runner || {}, limits: initial.limits || {},
    assignments: initial.assignments || [],
    drafts: new Map(), currentRun: null, selectedCase: 0, selectedCriterion: 0,
    selectedResultTest: 0, busy: false, dirty: false
  };

  const key = () => crypto.randomUUID();
  const codeDraftKey = () => `boostudy-code-judge-draft:${state.testSet?.id || state.testSet?.scenario_id || 'new'}`;
  const safeJson = (value) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const statusLabel = (status) => ({
    accepted: 'Все тесты пройдены', wrong_answer: 'Есть ошибки', completed: 'Тесты выполнены',
    incomplete: 'Проверка не завершена', sandbox_unavailable: 'Runner недоступен',
    internal_error: 'Ошибка Code Judge', passed: 'Пройден', syntax_error: 'Синтаксическая ошибка',
    runtime_error: 'Ошибка выполнения', time_limit_exceeded: 'Превышено время',
    memory_limit_exceeded: 'Превышена память', output_limit_exceeded: 'Слишком большой вывод'
  })[status] || status || 'Нет статуса';
  const isPassed = (status) => status === 'passed' || status === 'accepted';

  function say(message, kind = 'info') {
    const node = $('#cj-message');
    node.textContent = message || '';
    node.dataset.kind = kind;
    node.classList.toggle('is-visible', Boolean(message));
  }
  function headers(json = true) {
    const value = { 'X-CSRFToken': document.getElementById('cj-csrf').value };
    if (json) value['Content-Type'] = 'application/json';
    return value;
  }
  async function request(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...options });
    let data;
    try { data = await response.json(); }
    catch { throw new Error(`Сервер вернул HTTP ${response.status} без читаемого ответа.`); }
    if (!response.ok && !data.run) throw new Error(data.error || `Запрос завершился с HTTP ${response.status}.`);
    return data;
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function button(text, className, handler) {
    const node = element('button', className, text);
    node.type = 'button';
    node.addEventListener('click', handler);
    return node;
  }
  function field(labelText, value, onInput, kind = 'input') {
    const label = element('label', '', labelText);
    const control = document.createElement(kind);
    control.value = value ?? '';
    if (kind === 'textarea') control.spellcheck = false;
    control.addEventListener('input', () => onInput(control.value));
    label.append(control);
    return control;
  }
  function setDirty() {
    state.dirty = true;
    state.drafts.set(String(state.testSet?.id || 'new'), structuredClone(state.testSet));
  }
  function saveCodeDraft() {
    try { localStorage.setItem(codeDraftKey(), fields.code.value); }
    catch { $('#cj-draft-state').textContent = 'Не удалось сохранить черновик в браузере'; return; }
    $('#cj-draft-state').textContent = 'Черновик сохранён';
  }
  function restoreCodeDraft() {
    let saved = null;
    try { saved = localStorage.getItem(codeDraftKey()); } catch { /* storage disabled */ }
    fields.code.value = saved === null ? state.testSet?.starter_code || '' : saved;
    updateEditor();
  }
  function updateEditor() {
    const source = fields.code.value;
    const pre = $('#cj-highlight');
    pre.replaceChildren();
    const token = /#[^\n]*|(?:'[^'\\\n]*(?:\\.[^'\\\n]*)*'|"[^"\\\n]*(?:\\.[^"\\\n]*)*")|\b(?:def|return|if|else|elif|for|while|in|not|and|or|True|False|None|import|from|class|try|except|raise|with|as|pass|break|continue)\b|\b\d+(?:\.\d+)?\b/g;
    let cursor = 0;
    for (const match of source.matchAll(token)) {
      pre.append(document.createTextNode(source.slice(cursor, match.index)));
      const text = match[0];
      const tone = text.startsWith('#') ? 'comment' : text.startsWith('"') || text.startsWith("'") ? 'string' : /^\d/.test(text) ? 'number' : 'keyword';
      pre.append(element('span', `cj-py-${tone}`, text));
      cursor = match.index + text.length;
    }
    pre.append(document.createTextNode(source.slice(cursor) + '\n'));
    $('#cj-line-numbers').textContent = Array.from({ length: source.split('\n').length }, (_, index) => index + 1).join('\n');
    pre.scrollTop = fields.code.scrollTop;
    pre.scrollLeft = fields.code.scrollLeft;
    $('#cj-line-numbers').scrollTop = fields.code.scrollTop;
  }

  function renderTask() {
    const suite = state.testSet;
    if (!suite) return;
    $('#cj-task-title').textContent = suite.title || 'Новое задание';
    $('#cj-task-description').textContent = suite.description || 'Добавьте условие в конструкторе.';
    $('#cj-task-mode').textContent = suite.mode === 'function' ? `Функция ${suite.function_name || ''}` : 'Программа · stdin/stdout';
    $('#cj-task-version').textContent = `тесты v${suite.test_set_version || 1} · рубрика v${suite.rubric_version || 1}`;
    const examples = $('#cj-task-examples');
    examples.replaceChildren();
    const publicCases = (suite.test_cases || []).filter((test) => test.visibility === 'public');
    if (publicCases.length) examples.append(element('h3', '', 'Пример'));
    publicCases.slice(0, 2).forEach((test) => {
      const row = element('div', 'cj-example-row');
      for (const [label, value] of [
        [suite.mode === 'program' ? 'Ввод' : 'Аргументы', suite.mode === 'program' ? test.stdin : test.args],
        [suite.mode === 'program' ? 'Вывод' : 'Ожидается', suite.mode === 'program' ? test.expected_output : test.expected]
      ]) {
        const cell = element('div');
        cell.append(element('small', '', label), element('code', '', safeJson(value)));
        row.append(cell);
      }
      examples.append(row);
    });
    const casesRoot = $('#cj-public-cases');
    casesRoot.replaceChildren();
    publicCases.forEach((test, index) => {
      const card = element('div', 'cj-public-case');
      card.append(element('strong', '', `${index + 1}. ${test.name}`), element('small', '', suite.mode === 'program' ? `Ввод: ${test.stdin}` : `Аргументы: ${safeJson(test.args)}`));
      casesRoot.append(card);
    });
    const hidden = (suite.test_cases || []).length - publicCases.length;
    $('#cj-case-count').textContent = `${publicCases.length} Public · ${hidden} Hidden`;
  }
  function renderSetOptions() {
    const selected = String(state.testSet?.id || 'new');
    fields.select.replaceChildren();
    state.testSets.forEach((suite) => {
      const option = element('option', '', suite.title);
      option.value = String(suite.id);
      fields.select.append(option);
    });
    if (!state.testSet?.id) {
      const option = element('option', '', 'Новое задание');
      option.value = 'new';
      fields.select.prepend(option);
    }
    fields.select.value = selected;
  }
  function renderSet() {
    if (!state.testSet) return;
    renderSetOptions();
    fields.title.value = state.testSet.title || '';
    fields.description.value = state.testSet.description || '';
    fields.assignment.value = state.testSet.assignment_id ? `${state.testSet.assignment_id}@${state.testSet.assignment_version}` : '';
    fields.mode.value = state.testSet.mode || 'function';
    fields.functionName.value = state.testSet.function_name || '';
    fields.comparator.value = state.testSet.comparator || 'exact';
    fields.tolerance.value = String(state.testSet.tolerance ?? 0.000001);
    $('#cj-function-field').hidden = fields.mode.value !== 'function';
    $('#cj-delete-set').disabled = !state.testSet.id || state.testSet.is_seeded;
    renderTask();
    renderCases();
    renderRubric();
    restoreCodeDraft();
  }
  function newCase() {
    const number = (state.testSet.test_cases || []).length + 1;
    const common = { id: `case-${key().slice(0, 12)}`, name: `Тест ${number}`, visibility: 'public' };
    return state.testSet.mode === 'program' ? { ...common, stdin: '', expected_output: '' } : { ...common, args: [], expected: null };
  }
  function renderCases() {
    const cases = state.testSet.test_cases || [];
    state.selectedCase = Math.max(0, Math.min(state.selectedCase, cases.length - 1));
    const list = $('#cj-test-list');
    list.replaceChildren();
    cases.forEach((test, index) => {
      const item = button('', index === state.selectedCase ? 'is-active' : '', () => { state.selectedCase = index; renderCases(); });
      item.append(element('span', '', `${index + 1}. ${test.name || `Тест ${index + 1}`}`), element('small', '', test.visibility === 'hidden' ? 'Hidden' : 'Public'));
      item.setAttribute('aria-label', `Редактировать тест ${index + 1}: ${test.name}`);
      list.append(item);
    });
    const editor = $('#cj-case-editor');
    editor.replaceChildren();
    const test = cases[state.selectedCase];
    if (!test) { editor.append(element('p', 'cj-empty', 'Добавьте первый тест.')); return; }
    const name = field('Название теста', test.name, (value) => {
      test.name = value;
      const label = list.children[state.selectedCase]?.querySelector('span');
      if (label) label.textContent = `${state.selectedCase + 1}. ${value || `Тест ${state.selectedCase + 1}`}`;
      setDirty(); renderTask();
    }, 'input');
    name.setAttribute('aria-label', 'Название выбранного теста');
    editor.append(name.parentElement);
    const group = field('Группа тестов · необязательно', test.group_id || '', (value) => { test.group_id = value.trim(); setDirty(); renderRubric(); }, 'input');
    group.maxLength = 80;
    editor.append(group.parentElement);
    const visibility = document.createElement('select');
    for (const value of ['public', 'hidden']) {
      const option = element('option', '', value === 'public' ? 'Public' : 'Hidden');
      option.value = value;
      visibility.append(option);
    }
    visibility.value = test.visibility;
    visibility.addEventListener('change', () => { test.visibility = visibility.value; setDirty(); renderCases(); renderTask(); });
    const visibleLabel = element('label', '', 'Видимость'); visibleLabel.append(visibility); editor.append(visibleLabel);
    const jsonField = (title, property, value) => {
      const control = field(title, value, (text) => {
        try { test[property] = JSON.parse(text); control.setCustomValidity(''); setDirty(); }
        catch { control.setCustomValidity('Укажите корректный JSON.'); }
      }, 'textarea');
      editor.append(control.parentElement);
    };
    if (state.testSet.mode === 'program') {
      editor.append(field('Вход stdin', test.stdin || '', (value) => { test.stdin = value; setDirty(); }, 'textarea').parentElement);
      editor.append(field('Ожидаемый stdout', test.expected_output || '', (value) => { test.expected_output = value; setDirty(); }, 'textarea').parentElement);
    } else {
      jsonField('Аргументы · JSON-массив', 'args', JSON.stringify(test.args || [], null, 2));
      jsonField('Ожидаемый результат · JSON', 'expected', JSON.stringify(test.expected ?? null, null, 2));
    }
    const actions = element('div', 'cj-case-actions');
    actions.append(button('Дублировать', 'cj-button', () => {
      if (cases.length >= Number(state.limits.max_test_cases || 30)) { say('Достигнут лимит тестов.', 'warning'); return; }
      const copy = structuredClone(test); copy.id = `case-${key().slice(0, 12)}`; copy.name += ' · копия';
      cases.splice(state.selectedCase + 1, 0, copy); state.selectedCase += 1; setDirty(); renderCases(); renderTask();
    }));
    actions.append(button('Удалить', 'cj-button', () => {
      if (!window.confirm(`Удалить тест «${test.name}»?`)) return;
      cases.splice(state.selectedCase, 1);
      (state.testSet.rubric_json || []).forEach((criterion) => { criterion.checks = criterion.checks.filter((check) => check.case_id !== test.id); });
      setDirty(); renderCases(); renderRubric(); renderTask();
    }));
    editor.append(actions);
  }
  function renderRubric() {
    const rubric = state.testSet.rubric_json || (state.testSet.rubric_json = []);
    state.selectedCriterion = Math.max(0, Math.min(state.selectedCriterion, rubric.length - 1));
    const list = $('#cj-rubric-list'); list.replaceChildren();
    rubric.forEach((criterion, index) => {
      const node = button(`${index + 1}. ${criterion.title} · ${criterion.max_score}`, index === state.selectedCriterion ? 'is-active' : '', () => { state.selectedCriterion = index; renderRubric(); });
      list.append(node);
    });
    const editor = $('#cj-rubric-editor'); editor.replaceChildren();
    const criterion = rubric[state.selectedCriterion];
    if (!criterion) { editor.append(element('p', 'cj-empty', 'Критерии не заданы. Добавьте критерий для проверяемой оценки.')); return; }
    editor.append(field('Критерий', criterion.title, (value) => { criterion.title = value; setDirty(); }, 'input').parentElement);
    editor.append(field('Описание', criterion.description || '', (value) => { criterion.description = value; setDirty(); }, 'textarea').parentElement);
    const score = field('Максимум баллов', criterion.max_score, (value) => { criterion.max_score = Number(value); setDirty(); }, 'input');
    score.type = 'number'; score.min = '0.1'; score.max = '100'; score.step = '0.1'; editor.append(score.parentElement);
    const ruleLabel = element('label', '', 'Правило начисления');
    const rule = document.createElement('select');
    for (const [value, title] of [['all_or_nothing', 'Все связанные проверки'], ['proportional', 'Пропорционально пройденным проверкам']]) {
      const option = element('option', '', title); option.value = value; rule.append(option);
    }
    rule.value = criterion.policy || 'all_or_nothing';
    rule.addEventListener('change', () => { criterion.policy = rule.value; setDirty(); });
    ruleLabel.append(rule); editor.append(ruleLabel);
    const assignment = state.assignments.find((item) => item.assignment_id === state.testSet.assignment_id && item.assignment_version === state.testSet.assignment_version);
    if (assignment) {
      const mappingLabel = element('label', '', 'Критерий задания AI Homework');
      const mapping = document.createElement('select');
      const unbound = element('option', '', 'Не связан · будет показан без оценки'); unbound.value = ''; mapping.append(unbound);
      assignment.criteria.forEach((item) => { const option = element('option', '', `${item.title} · ${item.max_score} б.`); option.value = item.id; mapping.append(option); });
      mapping.value = criterion.assignment_criterion_id || '';
      mapping.addEventListener('change', () => { criterion.assignment_criterion_id = mapping.value || null; setDirty(); });
      mappingLabel.append(mapping); editor.append(mappingLabel);
    }
    editor.append(element('p', 'cj-hint', 'Если связанный результат не получен, критерий получает статус «недостаточно данных», а не ноль.'));
    const checks = element('div', 'cj-rubric-checks');
    const cases = state.testSet.test_cases || [];
    const targets = cases.map((test) => ({ case_id: test.id, title: test.name }));
    const groups = new Map();
    cases.filter((test) => test.group_id).forEach((test) => groups.set(test.group_id, (groups.get(test.group_id) || 0) + 1));
    groups.forEach((count, group_id) => targets.push({ group_id, title: `Группа «${group_id}» · ${count}` }));
    targets.forEach((target) => {
      const existing = criterion.checks.find((check) => (target.case_id && check.case_id === target.case_id) || (target.group_id && check.group_id === target.group_id));
      const row = element('label', 'cj-rubric-check');
      const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = Boolean(existing);
      const projection = document.createElement('select');
      const options = state.testSet.mode === 'program' ? [['whole', 'Весь stdout']] : [
        ['whole', 'Всё значение'], ['type', 'Тип результата'], ['tuple_bool_pair', 'Кортеж из двух bool'],
        ['tuple.0', 'Кортеж: элемент 1'], ['tuple.0.type', 'Кортеж: тип элемента 1'],
        ['tuple.1', 'Кортеж: элемент 2'], ['tuple.1.type', 'Кортеж: тип элемента 2'],
        ['list.0', 'Список: элемент 1'], ['list.0.type', 'Список: тип элемента 1'],
        ['list.1', 'Список: элемент 2'], ['list.1.type', 'Список: тип элемента 2']
      ];
      const expectedValue = cases.find((test) => (target.case_id && test.id === target.case_id) || (target.group_id && test.group_id === target.group_id))?.expected;
      if (expectedValue && typeof expectedValue === 'object' && !Array.isArray(expectedValue) && expectedValue.__type__ !== 'tuple') {
        Object.keys(expectedValue).forEach((keyName) => options.push([`dict.${keyName}`, `Словарь: ${keyName}`], [`dict.${keyName}.type`, `Словарь: тип ${keyName}`]));
      }
      for (const [value, title] of options) {
        const option = element('option', '', title); option.value = value; projection.append(option);
      }
      projection.value = existing?.projection || 'whole';
      projection.disabled = !enabled.checked;
      enabled.addEventListener('change', () => {
        criterion.checks = criterion.checks.filter((check) => target.case_id ? check.case_id !== target.case_id : check.group_id !== target.group_id);
        if (enabled.checked) criterion.checks.push({ ...(target.case_id ? { case_id: target.case_id } : { group_id: target.group_id }), projection: projection.value });
        projection.disabled = !enabled.checked;
        setDirty();
      });
      projection.addEventListener('change', () => { const check = criterion.checks.find((entry) => target.case_id ? entry.case_id === target.case_id : entry.group_id === target.group_id); if (check) check.projection = projection.value; setDirty(); });
      row.append(enabled, element('span', '', target.title), projection); checks.append(row);
    });
    editor.append(checks);
    editor.append(button('Удалить критерий', 'cj-button', () => {
      if (!window.confirm(`Удалить критерий «${criterion.title}»?`)) return;
      rubric.splice(state.selectedCriterion, 1); setDirty(); renderRubric();
    }));
  }
  function suitePayload(includeEditorCode = false) {
    if (root.querySelector(':invalid')) throw new Error('Исправьте поля с некорректным JSON или числом.');
    return {
      id: state.testSet.id || null, title: state.testSet.title, description: state.testSet.description,
      mode: state.testSet.mode, function_name: state.testSet.function_name || '',
      comparator: state.testSet.comparator, tolerance: Number(state.testSet.tolerance || 0),
      starter_code: includeEditorCode || !state.testSet.id ? fields.code.value : (state.testSet.starter_code || ''),
      test_cases: state.testSet.test_cases || [], rubric_json: state.testSet.rubric_json || [],
      assignment_id: fields.assignment.selectedOptions[0]?.dataset.id || null,
      assignment_version: fields.assignment.selectedOptions[0]?.dataset.version || null,
      test_set_version: state.testSet.test_set_version || 1,
    };
  }

  function chip(text, tone = '') { return element('span', `cj-chip${tone ? ` is-${tone}` : ''}`, text); }
  function renderResult(run) {
    state.currentRun = run;
    const result = run.result || {};
    $('#cj-result-caption').textContent = `#${run.id} · ${run.run_type === 'submit' ? 'полная проверка' : 'публичные тесты'}`;
    $('#cj-result-summary').replaceChildren(
      chip(statusLabel(run.status), run.status === 'accepted' ? 'good' : run.status === 'wrong_answer' ? 'bad' : ''),
      chip(`${result.passed || 0}/${result.total || 0} тестов`), chip(`${run.duration_ms ?? result.execution_time_ms ?? 0} мс`)
    );
    const testRoot = $('#cj-result-tests'); testRoot.replaceChildren();
    const rubric = result.rubric;
    if (rubric?.criteria?.length) {
      const summary = element('div', 'cj-rubric-result');
      summary.append(chip(`Подтверждено ${rubric.confirmed_score}/${rubric.max_score} баллов`, rubric.unconfirmed_max_score ? '' : 'good'));
      if (rubric.unconfirmed_max_score) summary.append(chip(`${rubric.unconfirmed_max_score} баллов не подтверждено`));
      rubric.criteria.forEach((criterion) => {
        const row = element('div', 'cj-criterion-score');
        const status = { fulfilled: 'выполнен', not_fulfilled: 'не выполнен', insufficient_data: 'недостаточно данных' }[criterion.status] || criterion.status;
        row.append(element('strong', '', `${criterion.title}: ${criterion.score_awarded === null ? status : criterion.score_awarded + '/' + criterion.max_score + ' · ' + status}`));
        row.append(element('small', '', `${criterion.rationale || criterion.description || ''} ${(criterion.evidence || []).map((item) => `${item.case_id}: ${item.status}`).join(' · ')}`.trim()));
        summary.append(row);
      });
      testRoot.append(summary);
    }
    const tests = result.tests || [];
    state.selectedResultTest = Math.max(0, Math.min(state.selectedResultTest, tests.length - 1));
    if (tests.length) {
      const layout = element('div', 'cj-result-layout');
      const list = element('div', 'cj-result-list'); const detail = element('div', 'cj-result-detail');
      const show = (index) => {
        state.selectedResultTest = index;
        [...list.children].forEach((item, itemIndex) => item.classList.toggle('is-active', itemIndex === index));
        detail.replaceChildren();
        const test = tests[index];
        detail.append(element('h3', '', `${test.name || test.id} · ${statusLabel(test.status)}`));
        if (test.visibility === 'hidden') detail.append(element('p', '', 'Скрытый тест · доступен только администратору AI Lab.'));
        for (const [label, value] of [['Ожидалось', test.expected], ['Получено', test.actual]]) {
          if (value === undefined) continue;
          const block = element('div', 'cj-output-block');
          block.append(element('strong', '', label), element('pre', '', safeJson(value)));
          detail.append(block);
        }
        if (test.diff) detail.append(element('pre', '', test.diff));
        if (test.error_message) detail.append(element('p', '', test.error_message));
        detail.append(element('p', '', `Время выполнения: ${test.execution_time_ms ?? 0} мс`));
      };
      tests.forEach((test, index) => {
        const item = button('', 'cj-result-test-button', () => show(index));
        item.append(element('span', '', test.name || test.id || `Тест ${index + 1}`), element('span', isPassed(test.status) ? 'is-pass' : 'is-fail', isPassed(test.status) ? '✓' : '×'));
        list.append(item);
      });
      layout.append(list, detail); testRoot.append(layout); show(state.selectedResultTest);
    } else testRoot.append(element('p', 'cj-empty', run.technical_error || 'Тесты не выполнялись.'));
    const output = $('#cj-result-output'); output.replaceChildren();
    tests.forEach((test) => {
      for (const [label, value] of [['stdout', test.stdout], ['stderr', test.stderr]]) {
        if (!value) continue;
        const block = element('div', 'cj-output-block');
        block.append(element('strong', '', `${test.name} · ${label}`), element('pre', '', value)); output.append(block);
      }
    });
    if (!output.childElementCount) output.append(element('p', 'cj-empty', 'stdout и stderr пусты.'));
    const technical = $('#cj-result-technical'); technical.replaceChildren();
    for (const [label, value] of [
      ['Запуск', run.id], ['Сценарий', run.scenario_id], ['Режим', run.mode],
      ['Версия набора', run.test_set_version], ['Runner', run.runner_version || 'не подключён'],
      ['SHA-256 кода', run.code_hash], ['Время', `${run.duration_ms ?? 0} мс`]
    ]) {
      const row = element('div', 'cj-queue'); row.append(element('span', '', label), element('strong', '', String(value ?? ''))); technical.append(row);
    }
    if (run.technical_error) technical.append(element('p', '', run.technical_error));
  }
  function renderHistory() {
    const list = $('#cj-history-list'); list.replaceChildren();
    state.history.forEach((run) => {
      const suite = state.testSets.find((item) => item.id === run.test_set_id);
      const item = button('', 'cj-history-item', () => {
        if (suite && suite.id !== state.testSet?.id) { saveCodeDraft(); state.testSet = structuredClone(suite); renderSet(); }
        fields.code.value = run.code || ''; updateEditor(); renderResult(run);
        switchMode('solution'); switchLeftTab('condition');
        say(`Открыт запуск #${run.id}. Код из истории можно изменить и проверить снова.`);
      });
      item.append(element('strong', '', `${suite?.title || run.scenario_id} · ${statusLabel(run.status)}`));
      item.append(element('small', '', `${run.created_at ? new Date(run.created_at).toLocaleString() : 'дата неизвестна'} · ${run.result?.passed ?? 0}/${run.result?.total ?? 0} · ${run.run_type === 'submit' ? 'Submit' : 'Run'}`));
      list.append(item);
    });
    if (!state.history.length) list.append(element('p', 'cj-empty', 'Запусков пока нет.'));
  }
  function updateRunner(runner, limits) {
    state.runner = runner || {}; if (limits) state.limits = limits;
    const ready = state.runner.ready === true && state.runner.secure_profile_verified === true;
    const badge = $('#cj-runner-state');
    badge.classList.toggle('is-ready', ready);
    badge.querySelector('i').className = `ph ${ready ? 'ph-shield-check' : 'ph-lock-key'}`;
    badge.querySelector('span').textContent = ready ? 'Python Runner готов' : 'Runner недоступен';
    fields.run.disabled = fields.submit.disabled = !ready || !state.enabled || state.busy;
    const queue = state.runner.queue || {};
    $('#cj-queue').replaceChildren(element('span', '', state.runner.message || 'Состояние не получено.'), element('span', '', `Выполняется: ${queue.active ?? 0} · ожидают: ${queue.waiting ?? 0}`));
    const profile = state.runner.security_profile || {};
    $('#cj-security-profile').textContent = `Изоляция: ${Object.entries(profile).filter(([, value]) => value === true).map(([name]) => name.replaceAll('_', ' ')).join(' · ') || 'нет подтверждения'}. Версия: ${state.runner.runner_version || 'нет данных'}.`;
  }
  function switchMode(mode) {
    root.dataset.mode = mode;
    $('#cj-constructor-panel').hidden = mode !== 'constructor';
    root.querySelectorAll('[data-cj-mode]').forEach((tab) => {
      const selected = tab.dataset.cjMode === mode;
      tab.classList.toggle('is-active', selected);
      tab.setAttribute('aria-selected', String(selected));
    });
  }
  function switchLeftTab(name) {
    root.querySelectorAll('[data-cj-left-tab]').forEach((tab) => { const selected = tab.dataset.cjLeftTab === name; tab.classList.toggle('is-active', selected); tab.setAttribute('aria-selected', String(selected)); });
    root.querySelectorAll('[data-cj-left-panel]').forEach((panel) => panel.classList.toggle('is-active', panel.dataset.cjLeftPanel === name));
  }
  async function loadData() {
    try {
      const data = await request(api);
      state.testSets = data.test_sets || [];
      state.history = data.history || [];
      updateRunner(data.runner, data.limits);
      renderHistory();
    } catch (error) { say(error.message, 'error'); }
  }
  async function pollQueue() {
    try { const data = await request(`${api}/queue`); updateRunner(data.runner, data.limits); }
    catch { updateRunner({ ready: false, secure_profile_verified: false, message: 'Нет связи с локальным runner.' }); }
  }
  async function saveSet() {
    try {
      const data = await request(`${api}/test-sets`, { method: 'POST', headers: headers(), body: JSON.stringify(suitePayload(true)) });
      const oldKey = codeDraftKey();
      state.testSet = structuredClone(data.test_set);
      const index = state.testSets.findIndex((item) => item.id === state.testSet.id);
      if (index < 0) state.testSets.unshift(data.test_set); else state.testSets[index] = data.test_set;
      try { if (oldKey !== codeDraftKey()) localStorage.setItem(codeDraftKey(), fields.code.value); } catch { /* storage disabled */ }
      state.dirty = false; state.drafts.delete(String(state.testSet.id));
      renderSet(); say(`Набор сохранён · версия ${state.testSet.test_set_version}.`, 'success');
    } catch (error) { say(error.message, 'error'); }
  }
  async function deleteSet() {
    if (!state.testSet?.id || state.testSet.is_seeded) return;
    if (!window.confirm(`Удалить набор «${state.testSet.title}»? История запусков сохранится.`)) return;
    try {
      await request(`${api}/test-sets/${state.testSet.id}`, { method: 'DELETE', headers: headers(false) });
      state.testSets = state.testSets.filter((item) => item.id !== state.testSet.id);
      state.testSet = structuredClone(state.testSets[0] || null); renderSet(); renderHistory();
      say('Набор удалён. История запусков сохранена.', 'success');
    } catch (error) { say(error.message, 'error'); }
  }
  async function run(runType) {
    if (state.busy || fields.run.disabled) return;
    let suite;
    try { suite = suitePayload(); }
    catch (error) { say(error.message, 'error'); return; }
    state.busy = true; updateRunner(state.runner);
    say(runType === 'submit' ? 'Полная проверка выполняется…' : 'Запускаем публичные тесты…');
    try {
      const data = await request(`${api}/run`, { method: 'POST', headers: headers(), body: JSON.stringify({
        request_key: key(), run_type: runType, test_set_id: state.testSet.id || null,
        test_set_version: state.testSet.test_set_version || 1, test_set: suite, code: fields.code.value
      }) });
      if (!data.run) throw new Error(data.error || 'Запуск не завершён.');
      state.selectedResultTest = 0;
      renderResult(data.run);
      say(data.run.technical_error || statusLabel(data.run.status), data.run.status === 'wrong_answer' ? 'warning' : data.run.status === 'accepted' ? 'success' : 'info');
      await loadData();
    } catch (error) { say(error.message, 'error'); }
    finally { state.busy = false; await pollQueue(); }
  }

  fields.select.addEventListener('change', () => {
    saveCodeDraft();
    const id = fields.select.value;
    state.testSet = structuredClone(state.drafts.get(id) || state.testSets.find((item) => String(item.id) === id) || state.testSet);
    state.selectedCase = 0; state.selectedCriterion = 0;
    renderSet(); say('');
  });
  for (const [node, property] of [[fields.title, 'title'], [fields.description, 'description'], [fields.functionName, 'function_name'], [fields.comparator, 'comparator'], [fields.tolerance, 'tolerance']]) {
    node.addEventListener(node.tagName === 'SELECT' ? 'change' : 'input', () => { state.testSet[property] = node.value; setDirty(); renderTask(); });
  }
  fields.mode.addEventListener('change', () => {
    if (!window.confirm('Смена режима очистит аргументы и ожидаемые результаты текущих тестов. Продолжить?')) { fields.mode.value = state.testSet.mode; return; }
    state.testSet.mode = fields.mode.value;
    state.testSet.test_cases = state.testSet.test_cases.map((test) => ({ id: test.id, name: test.name, visibility: test.visibility, ...(state.testSet.mode === 'program' ? { stdin: '', expected_output: '' } : { args: [], expected: null }) }));
    state.testSet.rubric_json = [];
    setDirty(); renderSet();
  });
  fields.assignment.addEventListener('change', () => {
    const assignment = state.assignments.find((item) => `${item.assignment_id}@${item.assignment_version}` === fields.assignment.value);
    state.testSet.assignment_id = assignment?.assignment_id || null;
    state.testSet.assignment_version = assignment?.assignment_version || null;
    (state.testSet.rubric_json || []).forEach((criterion) => {
      if (!assignment?.criteria.some((item) => item.id === criterion.assignment_criterion_id)) criterion.assignment_criterion_id = null;
    });
    setDirty(); renderRubric();
  });
  $('#cj-new-set').addEventListener('click', () => {
    saveCodeDraft();
    state.testSet = { id: null, title: 'Новое задание', description: '', mode: 'function', function_name: 'solve', comparator: 'exact', tolerance: 0.000001, starter_code: 'def solve():\n    pass', test_cases: [], rubric_json: [], assignment_id: null, assignment_version: null, test_set_version: 1, rubric_version: 1, is_seeded: false };
    state.selectedCase = 0; state.selectedCriterion = 0; renderSet();
    say('Новый набор готов. Добавьте тесты и сохраните его.');
  });
  $('#cj-save-set').addEventListener('click', saveSet);
  $('#cj-delete-set').addEventListener('click', deleteSet);
  $('#cj-add-case').addEventListener('click', () => {
    if (state.testSet.test_cases.length >= Number(state.limits.max_test_cases || 30)) { say('Достигнут лимит тестов.', 'warning'); return; }
    state.testSet.test_cases.push(newCase()); state.selectedCase = state.testSet.test_cases.length - 1;
    setDirty(); renderCases(); renderRubric(); renderTask();
  });
  $('#cj-add-criterion').addEventListener('click', () => {
    state.testSet.rubric_json ||= [];
    if (state.testSet.rubric_json.length >= 20) { say('Максимум 20 критериев.', 'warning'); return; }
    state.testSet.rubric_json.push({ id: `criterion-${key().slice(0, 12)}`, title: 'Новый критерий', description: '', max_score: 1, policy: 'all_or_nothing', checks: [] });
    state.selectedCriterion = state.testSet.rubric_json.length - 1; setDirty(); renderRubric();
  });
  $('#cj-import-rubric').addEventListener('click', () => {
    const assignment = state.assignments.find((item) => `${item.assignment_id}@${item.assignment_version}` === fields.assignment.value);
    if (!assignment) { say('Выберите утверждённую версию задания.', 'warning'); return; }
    if (state.testSet.rubric_json?.length && !window.confirm('Заменить текущие критерии? Привязки тестов потребуется назначить заново.')) return;
    state.testSet.assignment_id = assignment.assignment_id;
    state.testSet.assignment_version = assignment.assignment_version;
    state.testSet.rubric_json = assignment.criteria.map((item) => ({
      id: item.id, assignment_criterion_id: item.id, title: item.title,
      description: item.description, max_score: item.max_score,
      policy: item.policy || 'all_or_nothing', checks: []
    }));
    state.selectedCriterion = 0; setDirty(); renderRubric();
    say('Критерии загружены. Добавьте тесты и привяжите каждую проверку к нужному критерию.', 'info');
  });
  $('#cj-run').addEventListener('click', () => run('run'));
  $('#cj-submit').addEventListener('click', () => run('submit'));
  fields.code.addEventListener('input', () => { updateEditor(); saveCodeDraft(); });
  fields.code.addEventListener('scroll', updateEditor);
  fields.code.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') { event.preventDefault(); fields.code.setRangeText('    ', fields.code.selectionStart, fields.code.selectionEnd, 'end'); fields.code.dispatchEvent(new Event('input')); }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); run('run'); }
  });
  root.querySelectorAll('[data-cj-mode]').forEach((tab) => tab.addEventListener('click', () => switchMode(tab.dataset.cjMode)));
  root.querySelectorAll('[data-cj-left-tab]').forEach((tab) => tab.addEventListener('click', () => switchLeftTab(tab.dataset.cjLeftTab)));
  root.querySelectorAll('[data-cj-tab]').forEach((tab) => tab.addEventListener('click', () => {
    root.querySelectorAll('[data-cj-tab]').forEach((item) => item.setAttribute('aria-selected', String(item === tab)));
    root.querySelectorAll('[data-cj-panel]').forEach((panel) => panel.classList.toggle('is-active', panel.dataset.cjPanel === tab.dataset.cjTab));
  }));
  const resize = $('#cj-resize-handle');
  resize.addEventListener('pointerdown', (event) => {
    event.preventDefault(); resize.setPointerCapture(event.pointerId);
    const move = (pointer) => {
      const bounds = $('#cj-right').getBoundingClientRect();
      const height = Math.max(210, Math.min(bounds.height - 200, pointer.clientY - bounds.top));
      $('#cj-editor-panel').style.height = `${height}px`;
    };
    const stop = () => { resize.removeEventListener('pointermove', move); resize.removeEventListener('pointerup', stop); };
    resize.addEventListener('pointermove', move); resize.addEventListener('pointerup', stop);
  });
  resize.addEventListener('keydown', (event) => {
    if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    $('#cj-editor-panel').style.height = `${Math.max(210, $('#cj-editor-panel').getBoundingClientRect().height + (event.key === 'ArrowDown' ? 24 : -24))}px`;
  });

  renderSet(); renderHistory(); updateRunner(state.runner, state.limits); loadData();
  window.setInterval(pollQueue, 3000);
})();
