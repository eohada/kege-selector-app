(() => {
  const root = document.getElementById('ai-course-app');
  const sampleNode = document.getElementById('ac-course-samples');
  if (!root || !sampleNode) return;

  let samples = [];
  try { samples = JSON.parse(sampleNode.textContent || '[]'); } catch (_) { return; }
  const select = document.getElementById('ac-course-select');
  const versionInput = document.getElementById('ac-course-version');
  const preview = document.getElementById('ac-course-preview');
  const result = document.getElementById('ac-result');
  const status = document.getElementById('ac-status');
  const runButton = document.getElementById('ac-analyze');
  const practiceLink = document.getElementById('ac-practice-link');
  let latestRecord = null;

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const currentCourse = () => ({...samples[Number(select.value)], course_version: Number(versionInput.value)});

  function renderPreview() {
    const course = currentCourse();
    preview.replaceChildren();
    const heading = element('p', 'ac-muted', `${course.topics.length} тем · ${course.materials.length} материалов · ${course.assignments.length} заданий`);
    preview.append(heading);
    course.topics.forEach((topic) => {
      const card = element('div', 'ac-topic');
      card.append(element('strong', '', topic.title));
      card.append(element('span', 'ac-ref', `ID ${topic.topic_id} · порядок ${topic.order}`));
      card.append(element('p', 'ac-muted', topic.prerequisite_ids.length ? `Предпосылки: ${topic.prerequisite_ids.join(', ')}` : 'Явных предпосылок нет.'));
      preview.append(card);
    });
    course.materials.forEach((material) => {
      const card = element('div', 'ac-material');
      card.dataset.materialId = material.material_id;
      card.tabIndex = -1;
      card.append(element('strong', '', material.title));
      card.append(element('span', 'ac-ref', `${material.material_id} · ${material.topic_id}`));
      card.append(element('p', 'ac-muted', material.content));
      preview.append(card);
    });
  }

  function renderRecord(record, course) {
    latestRecord = record;
    result.hidden = false;
    result.replaceChildren();
    const title = element('h2', '', `Анализ #${record.id} · ${record.status}`);
    result.append(title);
    const output = record.result || {};
    const partial = record.status !== 'succeeded' && Number(output.completed_chunks) > 0;
    if (record.status !== 'succeeded' && !partial) {
      result.append(element('p', 'ac-error', record.error_message || 'Анализ завершился ошибкой.'));
      result.append(element('p', 'ac-ref', `Код: ${record.error_code || 'unknown'} · запись сохранена для диагностики.`));
      return;
    }
    if (partial) result.append(element('p', 'ac-error', `Частичный результат: ${output.completed_chunks} из ${output.total_chunks} частей. ${record.error_message || 'Продолжите анализ повторным нажатием.'}`));
    result.append(element('h3', '', 'Интерпретация модели · не подтверждена'));
    result.append(element('p', 'ac-lead', output.summary || 'Сводка не сформирована.'));
    result.append(element('p', 'ac-ref', 'Сводка является непроверенной интерпретацией GigaChat. Структурные факты определяются проверками ниже; не применяйте текст модели как обязательное изменение курса.'));
    result.append(element('p', 'ac-ref', `Модель: ${record.model || 'не указана'} · вход ${record.input_tokens ?? '—'} · генерация ${record.output_tokens ?? '—'} токенов · ${(record.duration_ms || 0) / 1000} с · валидация ${record.validation_status}`));

    const findings = element('section', 'ac-list');
    findings.append(element('h3', '', 'Структурные проверки'));
    const structural = output.structural_findings || [];
    if (!structural.length) findings.append(element('p', 'ac-good', 'Явных нарушений заданных связей не найдено.'));
    structural.forEach((item) => findings.append(element('div', 'ac-finding', `${item.code}: ${item.message}`)));
    result.append(findings);

    const reviewMap = new Map();
    (record.quality?.proposal_reviews || []).forEach((review) => reviewMap.set(review.proposal_id, review));
    const proposals = output.material_proposals || [];
    const proposalSection = element('section', 'ac-list');
    proposalSection.append(element('h3', '', 'Предложения по материалам · ручная проверка'));
    if (!proposals.length) proposalSection.append(element('p', 'ac-empty', 'Модель не нашла предложение с достаточным основанием.'));
    proposals.forEach((proposal) => {
      const material = (course.materials || []).find((item) => item.material_id === proposal.material_id);
      const card = element('article', 'ac-proposal');
      const latestReview = reviewMap.get(proposal.proposal_id);
      const reviewLabel = latestReview
        ? (latestReview.application_status === 'applied' ? 'Принято · выбранный материал обновлён'
          : latestReview.application_status === 'rolled_back' ? 'Принято · изменение безопасно отменено'
            : latestReview.application_status === 'rejected' ? 'Отклонено · курс не изменён'
              : 'Решение сохранено · материал не связан с локальным курсом')
        : proposal.status;
      card.append(element('strong', '', `${proposal.material_id} · ${reviewLabel}`));
      card.append(element('p', 'ac-muted', proposal.observation));
      const diff = element('div', 'ac-proposal-grid');
      diff.append(element('div', 'ac-material', `Исходное содержание\n${material?.content || 'Источник не найден'}`));
      diff.append(element('div', 'ac-material', `Предлагаемый вариант\n${proposal.proposed_text}`));
      card.append(diff);
      const editLabel = element('label', 'ac-field', 'Текст после ручной проверки');
      const approvedText = document.createElement('textarea');
      approvedText.className = 'ac-proposal-edit';
      approvedText.style.cssText = 'min-height:180px;width:100%;resize:vertical;padding:12px;border:1px solid var(--bs-border);border-radius:12px;background:var(--bs-bg-surface);color:var(--bs-text-primary);font:inherit;line-height:1.55;white-space:pre-wrap';
      approvedText.value = latestReview?.approved_text || proposal.proposed_text || '';
      approvedText.setAttribute('aria-label', `Текст после ручной проверки для ${proposal.material_id}`);
      approvedText.disabled = Boolean(latestReview);
      editLabel.append(approvedText);
      card.append(editLabel);
      if (latestReview?.application_status === 'applied') {
        card.append(element('p', 'ac-good', `Изменён только ${proposal.material_id}. Новая версия курса: ${latestReview.material_change?.new_course_version ?? 'сохранена'}.`));
      }
      card.append(element('p', 'ac-ref', `Основания: ${(proposal.source_refs || []).join(', ')}`));
      (proposal.source_locations || []).forEach((location) => {
        if (!material || location.material_id !== proposal.material_id) return;
        const start = Number(location.start_utf16);
        const end = Number(location.end_utf16);
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > material.content.length) return;
        const excerpt = element('p', 'ac-ref');
        excerpt.append(document.createTextNode('Точный фрагмент: '));
        const mark = document.createElement('mark');
        mark.textContent = material.content.slice(start, end);
        excerpt.append(mark);
        const openSource = element('button', 'ac-button', 'Открыть материал');
        openSource.type = 'button';
        openSource.addEventListener('click', () => {
          const sourceCard = Array.from(preview.querySelectorAll('[data-material-id]'))
            .find((node) => node.dataset.materialId === location.material_id);
          sourceCard?.scrollIntoView({behavior: 'smooth', block: 'center'});
          sourceCard?.focus({preventScroll: true});
        });
        excerpt.append(openSource);
        card.append(excerpt);
      });
      const actions = element('div', 'ac-actions');
      if (!latestReview) {
        [['accepted', 'Применить проверенный текст'], ['rejected', 'Отклонить']].forEach(([decision, label]) => {
          const button = element('button', 'ac-button', label);
          button.type = 'button';
          button.addEventListener('click', () => reviewProposal(record.id, proposal.proposal_id, decision, course, approvedText.value));
          actions.append(button);
        });
      } else if (latestReview.application_status === 'applied') {
        const rollback = element('button', 'ac-button', 'Отменить изменение');
        rollback.type = 'button';
        rollback.addEventListener('click', () => rollbackProposal(record.id, proposal.proposal_id, course));
        actions.append(rollback);
      }
      card.append(actions);
      proposalSection.append(card);
    });
    result.append(proposalSection);
    const links = element('div', 'ac-actions');
    const practice = element('a', 'ac-button ac-button-primary', 'Проверить связи в Practice');
    practice.href = `${practiceLink.href.split('?')[0]}?course_analysis_id=${record.id}`;
    links.append(practice);
    result.append(links);
  }

  async function reviewProposal(recordId, proposalId, decision, course, proposedText) {
    const base = root.dataset.reviewBase.replace('/0/', `/${recordId}/`).replace('__proposal__', encodeURIComponent(proposalId));
    try {
      const response = await fetch(base, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf},
        body: JSON.stringify({decision, proposed_text: proposedText})});
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось сохранить решение.');
      const review = (body.record.quality?.proposal_reviews || []).find((item) => item.proposal_id === proposalId);
      status.textContent = review?.application_status === 'applied'
        ? 'Решение сохранено. Обновлён только выбранный синтетический материал; источник получил новую версию.'
        : 'Отклонение сохранено. Исходный курс не изменён.';
      renderRecord(body.record, course);
    } catch (error) {
      status.textContent = error.message || 'Не удалось сохранить решение.';
      status.className = 'ac-status ac-error';
    }
  }

  async function rollbackProposal(recordId, proposalId, course) {
    const base = root.dataset.rollbackBase.replace('/0/', `/${recordId}/`).replace('__proposal__', encodeURIComponent(proposalId));
    try {
      const response = await fetch(base, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf}, body: '{}'});
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось отменить изменение.');
      status.textContent = 'Изменение выбранного материала отменено; восстановлено исходное содержимое и создана новая версия курса.';
      renderRecord(body.record, course);
    } catch (error) {
      status.textContent = error.message || 'Не удалось отменить изменение.';
      status.className = 'ac-status ac-error';
    }
  }

  select.addEventListener('change', () => { versionInput.value = samples[Number(select.value)].course_version; renderPreview(); });
  versionInput.addEventListener('input', renderPreview);
  runButton.addEventListener('click', async () => {
    const course = currentCourse();
    runButton.disabled = true;
    result.hidden = true;
    status.className = 'ac-status';
    status.textContent = 'Запрос поставлен в общую последовательную очередь GigaChat…';
    try {
      const response = await fetch(root.dataset.analyzeUrl, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf},
        body: JSON.stringify({course})});
      const body = await response.json();
      if (body.record) renderRecord(body.record, course);
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось выполнить анализ курса.');
      status.textContent = 'Анализ сохранён. Предложения остаются черновиками до ручного применения; связи и структура курса не меняются.';
      status.className = 'ac-status ac-good';
    } catch (error) {
      status.textContent = error.message || 'Не удалось выполнить анализ курса.';
      status.className = 'ac-status ac-error';
    } finally {
      runButton.disabled = false;
    }
  });
  renderPreview();
})();
