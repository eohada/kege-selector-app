(() => {
  const page = document.getElementById('rubric-builder');
  if (!page) return;
  const $ = (id) => document.getElementById(id);
  const state = { rubric: null, rubrics: JSON.parse($('rb-initial-rubrics').textContent || '[]'), busy: false, verification: null, pendingGeneration: null, pendingRepair: null };
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const message = (text, error = false) => { $('rb-message').textContent = text; $('rb-message').classList.toggle('is-error', error); };
  const task = () => ({
    title: $('rb-title').value, subject: $('rb-subject').value, topic: $('rb-topic').value,
    answer_type: $('rb-type').value, max_score: $('rb-max').value,
    condition: $('rb-condition').value, reference_answer: $('rb-reference').value,
    teacher_requirements: $('rb-requirements').value
  });
  const setTask = (value) => {
    $('rb-title').value = value.title || ''; $('rb-subject').value = value.subject || '';
    $('rb-topic').value = value.topic || ''; $('rb-type').value = value.answer_type || 'python';
    $('rb-max').value = value.max_score || ''; $('rb-condition').value = value.condition || '';
    $('rb-reference').value = value.reference_answer || ''; $('rb-requirements').value = value.teacher_requirements || '';
  };
  const request = async (url, body) => {
    const response = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type':'application/json', 'X-CSRFToken': $('rb-csrf').value}, body: JSON.stringify(body)});
    let result;
    try { result = await response.json(); } catch (_) { throw new Error(`Сервер вернул HTTP ${response.status} без JSON.`); }
    if (!response.ok || !result.ok) throw new Error(result.error || `Ошибка HTTP ${response.status}`);
    return result.rubric;
  };
  const safeBusy = async (action) => {
    if (state.busy) return;
    state.busy = true;
    ['rb-generate','rb-save','rb-approve','rb-repair','rb-review'].forEach((id) => { $(id).disabled = true; });
    try { await action(); } catch (error) { message(error.message || 'Не удалось выполнить действие.', true); }
    finally { state.busy = false; updateActions(); }
  };
  const blankCriterion = () => ({
    id: `criterion-${Date.now()}`, title: '', description: '', max_score: 1,
    full_credit: '', partial_credit: '', typical_errors: [], automatable: false,
    evidence: '', manual_reason: '', policy: 'all_or_nothing'
  });
  const criterionHtml = (item, index) => {
    const issues = (state.rubric?.expert_review?.issues || []).filter((issue) => issue.criterion_id === item.id);
    return `<article class="rb-criterion" data-index="${index}">
    <div class="rb-criterion-head"><label class="rb-select-criterion"><input type="checkbox" data-repair-id="${escape(item.id)}"> Исправить</label><strong>Критерий ${index + 1}${issues.length ? ' · есть замечание' : ''}</strong><button type="button" data-action="merge" aria-label="Объединить критерий ${index + 1} со следующим" title="Объединить со следующим"><i class="ph ph-git-merge" aria-hidden="true"></i></button><button type="button" data-action="delete" aria-label="Удалить критерий ${index + 1}"><i class="ph ph-trash" aria-hidden="true"></i></button></div>
    ${issues.map((issue) => `<p class="rb-criterion-issue">${escape(issue.detail)}</p>`).join('')}
    <div class="rb-criterion-fields">
      <div class="rb-criterion-grid"><label>Название<input data-field="title" maxlength="200" value="${escape(item.title)}"></label><label>Баллы<input data-field="max_score" type="number" min="0.1" max="100" step="0.1" value="${escape(item.max_score)}"></label></div>
      <label>Что оценивается<textarea data-field="description" rows="2" maxlength="1000">${escape(item.description)}</textarea></label>
      <label>Полный балл<textarea data-field="full_credit" rows="2" maxlength="1000">${escape(item.full_credit)}</textarea></label>
      <label>Частичный балл<textarea data-field="partial_credit" rows="2" maxlength="1000">${escape(item.partial_credit)}</textarea></label>
      <label>Типичные ошибки <small>по одной на строку</small><textarea data-field="typical_errors" rows="2">${escape((item.typical_errors || []).join('\n'))}</textarea></label>
      <div class="rb-criterion-grid"><label>Способ проверки<select data-field="automatable"><option value="true" ${item.automatable ? 'selected' : ''}>Можно проверить тестами</option><option value="false" ${!item.automatable ? 'selected' : ''}>Требует преподавателя</option></select></label><label>Подтверждения<textarea data-field="evidence" rows="2" maxlength="1000">${escape(item.evidence)}</textarea></label></div>
      <label>Правило начисления в Code Judge<select data-field="policy"><option value="all_or_nothing" ${item.policy !== 'proportional' ? 'selected' : ''}>Все связанные проверки</option><option value="proportional" ${item.policy === 'proportional' ? 'selected' : ''}>Пропорционально пройденным проверкам</option></select></label>
      <label>Почему требуется ручная проверка<textarea data-field="manual_reason" rows="2" maxlength="1000">${escape(item.manual_reason)}</textarea></label>
    </div></article>`;
  };
  const collectCriteria = () => [...$('rb-criteria').querySelectorAll('.rb-criterion')].map((card, index) => {
    const read = (name) => card.querySelector(`[data-field="${name}"]`).value;
    return { id: state.rubric?.criteria?.[index]?.id || `criterion-${index + 1}`,
      title: read('title'), description: read('description'), max_score: Number(read('max_score')),
      full_credit: read('full_credit'), partial_credit: read('partial_credit'),
      typical_errors: read('typical_errors').split('\n').map((line) => line.trim()).filter(Boolean),
      automatable: read('automatable') === 'true', evidence: read('evidence'), manual_reason: read('manual_reason'), policy: read('policy') };
  });
  const renderVersions = () => {
    $('rb-versions').innerHTML = state.rubrics.map((item) => `<div class="rb-history-item"><strong>${escape(item.task.title)} · v${item.version_no}</strong> <span class="rb-status">${item.status === 'approved' ? 'Утверждена' : 'Черновик'}</span><p>${escape(item.assignment_id)} · ${escape(item.model || 'Без модели')}</p><button class="rb-button rb-button-soft" type="button" data-version="${item.id}">Открыть версию</button></div>`).join('') || '<p class="rb-note">Версий пока нет.</p>';
  };
  const renderValidation = () => {
    const validation = state.rubric?.current_validation || state.rubric?.validation || {};
    $('rb-validation').innerHTML = [
      ...(validation.errors || []).map((line) => `<p class="error">${escape(line)}</p>`),
      ...(validation.warnings || []).map((line) => `<p class="warning">${escape(line)}</p>`),
      validation.ok ? '<p>Проверка суммы и структуры пройдена. Содержание должен проверить преподаватель.</p>' : ''
    ].join('');
  };
  const renderComparison = (item) => {
    const repair = [...(item.edits || [])].reverse().find((edit) => edit.kind === 'model_repair' && edit.after);
    $('rb-comparison').innerHTML = repair ? `<h3>Сравнение v${repair.from_version} → v${item.version_no}</h3>${repair.before.map((old, index) => {
      const current = repair.after[index];
      if (!current || JSON.stringify(old) === JSON.stringify(current)) return '';
      const labels = {title:'Название',description:'Описание',max_score:'Баллы',full_credit:'Полный балл',partial_credit:'Частичный балл',typical_errors:'Типичные ошибки',automatable:'Автоматическая проверка',evidence:'Подтверждения',manual_reason:'Ручная проверка',policy:'Правило начисления'};
      const changes = Object.keys(labels).filter((key) => JSON.stringify(old[key]) !== JSON.stringify(current[key]));
      return `<details class="rb-diff"><summary>${escape(old.title)} → ${escape(current.title)} · ${changes.length} изменений</summary>${changes.map((key) => `<p><b>${labels[key]}</b><br>Было: ${escape(Array.isArray(old[key]) ? old[key].join('; ') : old[key])}<br>Стало: ${escape(Array.isArray(current[key]) ? current[key].join('; ') : current[key])}</p>`).join('')}</details>`;
    }).join('')}` : '';
  };
  const render = () => {
    const item = state.rubric;
    if (!item) { renderVersions(); return; }
    setTask(item.task);
    $('rb-version').textContent = `v${item.version_no} · ${item.status === 'approved' ? 'утверждена' : 'черновик'}`;
    $('rb-summary').textContent = `Максимум ${item.task.max_score} баллов · ${item.criteria.length} критериев · ${item.model || 'ручная версия'}`;
    $('rb-criteria').innerHTML = item.criteria.map(criterionHtml).join('');
    $('rb-tests').innerHTML = (item.proposed_tests || []).map((test) => `<div class="rb-test"><strong>${escape(test.name)}</strong> <span class="rb-status">Не проверен</span><p>${escape(test.purpose)} · ${escape(test.criterion_title)}</p><code>Вход: ${escape(test.input_json)}\nОжидается: ${escape(test.expected_json)}</code></div>`).join('') || '<p class="rb-note">Модель не предложила тестов.</p>';
    $('rb-test-reference').value = item.task.reference_answer || '';
    $('rb-verification-result').textContent = '';
    state.verification = null;
    $('rb-verify-tests').disabled = item.task.answer_type !== 'python' || !(item.proposed_tests || []).length;
    renderValidation(); renderComparison(item); renderVersions(); updateActions();
    const categories = {duplicate:'дублирование',point_allocation:'баллы',incomplete:'неполный критерий',unverifiable:'непроверяемое условие',invented_constraint:'придуманное ограничение',ambiguous:'неоднозначность',alternative_unfair:'альтернативы',reference_misread:'ошибка эталона'};
    $('rb-review-current').textContent = item.expert_review ? `Последняя оценка: ${item.expert_review.verdict === 'pass' ? 'прошла' : 'требует исправления'} · ${(item.expert_review.issues || []).map((issue) => categories[issue.category] || issue.category).join(', ') || 'без замечаний'} · ${item.expert_review.note || 'без комментария'}` : 'Экспертная оценка ещё не сохранена.';
    fetch(`/admin/ai-lab/api/rubrics/${item.id}/test-verification`, {credentials:'same-origin'})
      .then((response) => response.json()).then((payload) => {
        if (state.rubric?.id !== item.id || !payload.ok || !payload.verification) return;
        state.verification = payload.verification;
        $('rb-verification-result').textContent = `${payload.verification.overall_ok ? 'Сохранена успешная проверка' : 'Сохранена проверка с расхождениями'}: ${payload.verification.tests.map((test) => `${test.name} — ${test.status}`).join('; ')}. ${payload.verification.note}`;
        [...$('rb-tests').querySelectorAll('.rb-test .rb-status')].forEach((badge, index) => {
          const test = payload.verification.tests[index];
          badge.textContent = test?.status === 'passed' ? 'Совпал с эталоном' : `Расхождение: ${test?.status || 'нет результата'}`;
        });
      }).catch(() => {});
  };
  const updateActions = () => {
    $('rb-save').disabled = state.busy || !state.rubric;
    $('rb-repair').disabled = state.busy || !state.rubric || ![...$('rb-criteria').querySelectorAll('[data-repair-id]:checked')].length;
    $('rb-review').disabled = state.busy || !state.rubric;
    const validation = state.rubric?.current_validation || state.rubric?.validation || {};
    $('rb-ack').disabled = state.busy || !state.rubric || !(validation.warnings || []).length;
    $('rb-approve').disabled = state.busy || !state.rubric || state.rubric.status !== 'draft' || !validation.ok || ((validation.warnings || []).length && !$('rb-ack').checked);
  };
  $('rb-generate').addEventListener('click', () => safeBusy(async () => {
    message('GigaChat готовит предложение. После ответа проверьте каждый критерий.');
    const fingerprint = JSON.stringify({task:task(),model:$('rb-model').value});
    if (!state.pendingGeneration || state.pendingGeneration.fingerprint !== fingerprint) {
      state.pendingGeneration = {fingerprint, key:crypto.randomUUID()};
    }
    state.rubric = await request('/admin/ai-lab/api/rubrics/generate', {task: task(), model: $('rb-model').value, request_key:state.pendingGeneration.key});
    state.pendingGeneration = null;
    state.rubrics.unshift(state.rubric); render(); message('Предложение сохранено как черновик.');
  }));
  $('rb-save').addEventListener('click', () => safeBusy(async () => {
    const item = await request(`/admin/ai-lab/api/rubrics/${state.rubric.id}/revise`, {task: task(), criteria: collectCriteria()});
    state.rubric = item; state.rubrics.unshift(item); render(); message(`Правки сохранены в версии ${item.version_no}.`);
  }));
  $('rb-criteria').addEventListener('change', updateActions);
  $('rb-repair').addEventListener('click', () => safeBusy(async () => {
    const criterion_ids = [...$('rb-criteria').querySelectorAll('[data-repair-id]:checked')].map((input) => input.dataset.repairId);
    const reason = $('rb-repair-reason').value.trim();
    if (!reason) throw new Error('Опишите причину исправления.');
    const fingerprint = JSON.stringify({version:state.rubric.id,criterion_ids,reason,model:$('rb-model').value});
    if (!state.pendingRepair || state.pendingRepair.fingerprint !== fingerprint) state.pendingRepair = {fingerprint,key:crypto.randomUUID()};
    message('GigaChat исправляет выбранные критерии. Ответ будет сохранён как новый черновик.');
    const item = await request(`/admin/ai-lab/api/rubrics/${state.rubric.id}/repair`, {criterion_ids, reason, model:$('rb-model').value, request_key:state.pendingRepair.key});
    state.pendingRepair = null; state.rubric = item; state.rubrics.unshift(item); render(); message(`Исправление сохранено в версии ${item.version_no}. Проверьте различия и замечания.`);
  }));
  $('rb-review').addEventListener('click', () => safeBusy(async () => {
    const verdict = $('rb-review-verdict').value;
    const category = $('rb-review-category').value;
    const note = $('rb-review-note').value.trim();
    const criterion = $('rb-criteria').querySelector('[data-repair-id]:checked');
    if (verdict === 'fail' && (!category || !note)) throw new Error('Для отклонения укажите категорию и конкретное замечание.');
    const issues = verdict === 'fail' ? [{category, criterion_id:criterion?.dataset.repairId || '', detail:note}] : [];
    const item = await request(`/admin/ai-lab/api/rubrics/${state.rubric.id}/review`, {verdict, issues, note});
    state.rubric = item; state.rubrics = state.rubrics.map((old) => old.id === item.id ? item : old);
    render(); message('Экспертная оценка сохранена в истории.');
  }));
  $('rb-approve').addEventListener('click', () => safeBusy(async () => {
    const item = await request(`/admin/ai-lab/api/rubrics/${state.rubric.id}/approve`, {acknowledge_warnings: $('rb-ack').checked});
    state.rubric = item; state.rubrics = state.rubrics.map((other) => other.id === item.id ? item : other);
    render(); message('Рубрика утверждена. Её можно выбрать в AI Homework Studio и Code Judge.');
  }));
  $('rb-ack').addEventListener('change', updateActions);
  $('rb-verify-tests').addEventListener('click', () => safeBusy(async () => {
    if (!state.rubric) return;
    const reportResponse = await fetch(`/admin/ai-lab/api/rubrics/${state.rubric.id}/verify-tests`, {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type':'application/json', 'X-CSRFToken': $('rb-csrf').value},
      body: JSON.stringify({reference_code: $('rb-test-reference').value,
        reference_confirmed: $('rb-reference-confirmed').checked,
        edge_cases: [{name:'Граничный пример преподавателя', input_json:$('rb-edge-input').value,
          expected_json:$('rb-edge-expected').value}]})
    });
    const payload = await reportResponse.json();
    if (!reportResponse.ok || !payload.ok) throw new Error(payload.error || 'Проверка тестов не удалась.');
    state.verification = payload.verification;
    $('rb-verification-result').textContent = `${state.verification.overall_ok ? 'Совпало с эталоном' : 'Есть расхождения или неполный запуск'}: ${state.verification.tests.map((test) => `${test.name} — ${test.status}`).join('; ')}. ${state.verification.note}`;
    message('Протокол проверки тестов сохранён.');
  }));
  $('rb-add').addEventListener('click', () => { if (!state.rubric) return; state.rubric.criteria = collectCriteria(); state.rubric.criteria.push(blankCriterion()); render(); });
  $('rb-criteria').addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]'); if (!action) return;
    const card = event.target.closest('.rb-criterion'); if (!card) return;
    const index = Number(card.dataset.index);
    state.rubric.criteria = collectCriteria();
    if (action.dataset.action === 'delete') state.rubric.criteria.splice(index, 1);
    if (action.dataset.action === 'merge') {
      const next = state.rubric.criteria[index + 1];
      if (!next) { message('После этого критерия нет следующего для объединения.', true); return; }
      const current = state.rubric.criteria[index];
      current.title = `${current.title} и ${next.title}`;
      current.description = `${current.description} ${next.description}`.trim();
      current.max_score += next.max_score;
      current.full_credit = `${current.full_credit} ${next.full_credit}`.trim();
      current.partial_credit = `${current.partial_credit} ${next.partial_credit}`.trim();
      current.typical_errors = [...current.typical_errors, ...next.typical_errors];
      current.automatable = current.automatable && next.automatable;
      current.evidence = `${current.evidence} ${next.evidence}`.trim();
      current.manual_reason = `${current.manual_reason} ${next.manual_reason}`.trim();
      state.rubric.criteria.splice(index + 1, 1);
    }
    render();
  });
  $('rb-versions').addEventListener('click', (event) => {
    const button = event.target.closest('[data-version]'); if (!button) return;
    state.rubric = state.rubrics.find((item) => item.id === Number(button.dataset.version)) || null; render();
  });
  document.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach((tab) => { tab.classList.toggle('is-active', tab === button); tab.setAttribute('aria-selected', String(tab === button)); });
    ['criteria','tests','versions'].forEach((name) => { $(`rb-${name}-panel`).hidden = name !== button.dataset.tab; });
  }));
  if (page.dataset.enabled === 'true') {
    fetch('/admin/ai-lab/api/models', {credentials:'same-origin'}).then((response) => response.json()).then((payload) => {
      if (!payload.ok) throw new Error(payload.error || 'Модели недоступны.');
      const preferred = payload.models.includes(page.dataset.model) ? page.dataset.model : payload.models.includes('GigaChat-3-Pro') ? 'GigaChat-3-Pro' : payload.models[0];
      $('rb-model').innerHTML = payload.models.map((model) => `<option value="${escape(model)}" ${model === preferred ? 'selected' : ''}>${escape(model)}</option>`).join('');
    }).catch((error) => { $('rb-model').innerHTML = '<option value="">Недоступно</option>'; message(error.message, true); });
  } else message('Генератор доступен только в локальной AI Lab.', true);
  renderVersions();
})();
