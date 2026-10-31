(() => {
  const root = document.getElementById('tutorCore');
  const stateNode = document.getElementById('tutorState');
  if (!root || !stateNode) return;

  let state;
  try { state = JSON.parse(stateNode.textContent || '{}'); } catch (_) { return; }
  const caseById = new Map((state.cases || []).map((item) => [item.id, item]));
  const history = [];
  let selectedId = (state.cases || [])[0]?.id;
  let selectedRecordId = null;
  const csrf = root.dataset.csrf || '';
  const actionFeedback = document.getElementById('actionFeedback');
  const generateButton = document.getElementById('generateProposal');
  const localPreviewButton = document.getElementById('saveLocalPreview');

  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  };

  function renderEvidence(caseData) {
    const container = document.getElementById('evidenceList');
    container.replaceChildren();
    (caseData.evidence || []).forEach((event) => {
      const article = node('article', 'tc-evidence');
      const meta = node('div', 'tc-evidence-meta');
      const label = event.source_ref?.startsWith('tutor-fixture:')
        ? (event.evidence_status === 'technical_confirmed' ? 'Контрольный результат · синтетика' : 'Предварительное наблюдение · синтетика')
        : event.evidence_status === 'insufficient_data'
          ? 'Запись платформы · проверка не подтверждена'
          : event.evidence_status === 'expert_confirmed' ? 'Подтверждено преподавателем' : 'Технически проверено';
      const badge = node('span', 'tc-status', label);
      badge.dataset.kind = event.evidence_status;
      meta.append(badge, node('time', 'tc-muted', new Date(event.occurred_at).toLocaleString('ru-RU')));
      const reference = node('code', '', event.source_ref || event.event_id);
      meta.append(reference);
      const body = node('div', '');
      const scoreText = event.score === null ? 'Оценки нет' : `Результат: ${event.score}/${event.maximum}`;
      body.append(node('p', '', scoreText), node('p', '', event.reason || ''),
        node('p', 'tc-muted', `Основание: ${event.method || 'не указано'}`));
      article.append(meta, body);
      container.append(article);
    });
  }

  function renderKnowledgeContext(caseData) {
    const container = document.getElementById('knowledgeContext');
    container.replaceChildren();
    const materials = caseData.knowledge_context || [];
    if (!materials.length) {
      const empty = node('article', 'tc-evidence');
      empty.append(node('p', 'tc-muted', 'Подходящий материал с допустимым статусом не найден. Tutor Core не подменяет это догадочным объяснением.'));
      container.append(empty);
      return;
    }
    materials.forEach((material) => {
      const article = node('article', 'tc-evidence');
      const meta = node('div', 'tc-evidence-meta');
      meta.append(node('span', 'tc-status', `${material.status} · v${material.version_no}`));
      meta.append(node('code', '', material.knowledge_ref));
      const body = node('div', '');
      body.append(node('strong', '', material.title));
      body.append(node('p', '', material.content?.learning_goal || ''));
      body.append(node('p', '', material.content?.explanation || ''));
      (material.source_refs || []).forEach((source) => {
        const link = node('a', 'tc-muted', `${source.publisher}: ${source.title}`);
        link.href = source.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        body.append(link);
      });
      body.append(node('p', 'tc-muted', material.scope_note || ''));
      article.append(meta, body);
      container.append(article);
    });
  }

  function renderPlan(caseData) {
    const compare = document.getElementById('planCompare');
    compare.replaceChildren();
    const current = node('div', 'tc-plan-side');
    current.append(node('h3', '', 'План до решения'));
    current.append(node('p', '', caseData.next_lesson
      ? `${caseData.next_lesson.title}. ${caseData.next_lesson.content || 'Содержимое урока не заполнено.'}`
      : caseData.profile_kind === 'platform_synthetic' && !caseData.course_copy_id
        ? 'Индивидуальная копия курса этому аккаунту не назначена.'
        : 'Следующего урока в плане нет.'));
    const proposed = node('div', 'tc-plan-side');
    proposed.append(node('h3', '', 'Предложение Tutor Core'));
    proposed.append(node('p', '', caseData.proposal.text));
    compare.append(current, proposed);

    const allocation = document.getElementById('timeAllocation');
    allocation.replaceChildren();
    const time = caseData.proposal.time_allocation || {};
    [
      `Всего: ${time.total_minutes ?? 60} минут`,
      `Исходный урок: ${time.planned_lesson_minutes ?? 60} минут`,
      `Адаптация: ${time.adaptation_minutes ?? 0} минут`,
      caseData.profile_kind === 'platform_synthetic'
        ? (caseData.course_copy_id ? `Индивидуальная копия курса #${caseData.course_copy_id}` : 'Курс: индивидуальная копия не назначена')
        : 'План: 6 последовательных уроков',
      caseData.profile_kind === 'platform_synthetic'
        ? 'Расписание сохранено без изменений'
        : 'Частота 2/неделю — только ограничение этой симуляции',
    ].forEach((label) => allocation.append(node('span', '', label)));
    document.getElementById('uncertainty').textContent = caseData.proposal.uncertainty || '';
    const limits = document.getElementById('limitations');
    limits.replaceChildren();
    (caseData.limitations || []).forEach((item) => limits.append(node('li', '', item)));
  }

  function renderStableSkillHistory(caseData) {
    const container = document.getElementById('stableSkillHistory');
    container.replaceChildren();
    const historyEntries = caseData.stable_skill_history || [];
    const lessonTitle = caseData.next_lesson?.title || 'следующее занятие не задано';
    const applicableCount = Number(caseData.current_lesson_evidence_count || 0);

    if (!historyEntries.length) {
      container.append(node('p', 'tc-muted', 'Подтверждённых наблюдений по устойчивым навыкам пока нет.'));
    } else {
      historyEntries.forEach((entry) => {
        const article = node('article', 'tc-evidence');
        const meta = node('div', 'tc-evidence-meta');
        meta.append(
          node('strong', '', entry.title || 'Подтверждённый навык'),
          node('span', 'tc-micro', `${entry.confirmed_item_observations || 0} проверенных ответов на отдельных вариантах`),
        );
        const body = node('div', '');
        body.append(node('p', '', `Совпали с эталоном: ${entry.met || 0}; не совпали: ${entry.not_met || 0}.`));
        const linkedToCopy = (entry.curriculum_mapping_statuses || []).includes('linked_to_assigned_copy');
        body.append(node('p', 'tc-muted', linkedToCopy
          ? 'Навык сопоставлен с индивидуальной программой. Применимость к конкретному занятию проверяется отдельно.'
          : 'История сохранена, но навык не связан с этой программой и не используется для изменения занятия.'));
        article.append(meta, body);
        container.append(article);
      });
    }

    container.append(node('p', 'tc-muted',
      `К занятию «${lessonTitle}» сейчас относятся ${applicableCount} доказательств. История ответов сама по себе не подтверждает освоение навыка.`,
    ));
  }

  function renderCase(profileId) {
    const item = caseById.get(profileId);
    if (!item) return;
    selectedId = profileId;
    document.querySelectorAll('[data-profile-id]').forEach((button) => {
      const active = button.dataset.profileId === profileId;
      button.classList.toggle('is-selected', active);
      button.setAttribute('aria-pressed', String(active));
    });
    document.getElementById('selectedProfileTitle').textContent = item.label;
    document.getElementById('evidenceStatus').textContent = item.skill_summary.status_label || 'Недостаточно данных';
    document.getElementById('skillSummary').textContent = item.profile_kind === 'platform_synthetic'
      ? `${item.event_count || 0} сохранённых событий по устойчивому ID. ${item.skill_summary.confirmed_evidence || 0} подтверждённых результатов по навыку.`
      : `${item.skill_summary.confirmed_evidence || 0} контрольных результатов; ${item.skill_summary.assignment_count || 0} разных синтетических вариантов. Вывод ограничен указанным навыком.`;
    renderStableSkillHistory(item);
    renderEvidence(item);
    renderKnowledgeContext(item);
    renderPlan(item);
    const selectedHistory = history.filter((entry) => entry.profile_id === profileId);
    const latest = selectedHistory[selectedHistory.length - 1];
    selectedRecordId = latest && latest.status === 'succeeded' ? latest.id : null;
    renderSaved(latest);
    if (!item.can_generate) {
      generateButton.disabled = true;
      if (localPreviewButton) localPreviewButton.disabled = true;
      generateButton.textContent = 'Недостаточно подтверждённых данных';
      if (actionFeedback) actionFeedback.textContent = 'GigaChat не вызывается: сначала нужны подтверждённый результат и явная связь с навыком индивидуального курса.';
    } else if (localPreviewButton) {
      localPreviewButton.disabled = false;
    }
  }

  function renderSaved(record) {
    const narrative = document.getElementById('narrative');
    const review = document.getElementById('reviewActions');
    narrative.replaceChildren();
    review.hidden = true;
    if (!record) {
      narrative.hidden = true;
      generateButton.disabled = false;
      generateButton.textContent = 'Сформировать комментарий GigaChat и сохранить предложение';
      if (localPreviewButton) {
        localPreviewButton.disabled = false;
        localPreviewButton.textContent = 'Сохранить предпросмотр без GigaChat';
      }
      if (actionFeedback) actionFeedback.textContent = '';
      return;
    }
    if (record.status !== 'succeeded') {
      narrative.hidden = false;
      narrative.append(node('p', '', record.error_message || 'Запрос не завершился. Повтор заблокирован, чтобы не дублировать расход токенов.'));
      generateButton.disabled = true;
      generateButton.textContent = 'Запрос уже выполнялся';
      return;
    }
    if (record.semantic_validation?.status === 'deterministic_preview') {
      const safe = record.safe_narrative || {};
      narrative.hidden = false;
      narrative.append(node('p', '', 'Сохранён локальный предпросмотр Tutor Core. GigaChat не вызывался; факты и действие сформированы детерминированной системой.'));
      if (safe.student_feedback) narrative.append(node('p', '', `Черновик для ученика · только для просмотра преподавателем: ${safe.student_feedback}`));
      if (safe.teacher_explanation) narrative.append(node('p', '', `Основание для преподавателя: ${safe.teacher_explanation}`));
      generateButton.disabled = false;
      generateButton.textContent = 'Запросить комментарий GigaChat для сравнения';
      if (localPreviewButton) {
        localPreviewButton.disabled = true;
        localPreviewButton.textContent = 'Предпросмотр сохранён';
      }
      if (!record.decision) review.hidden = false;
      if (actionFeedback) actionFeedback.textContent = 'Локальный предпросмотр сохранён с расходом 0 токенов; решение курса остаётся за преподавателем.';
      return;
    }
    if (record.semantic_validation?.status !== 'valid') {
      const safe = record.safe_narrative || {};
      narrative.hidden = false;
      narrative.append(node('p', '', 'Текст GigaChat не прошёл проверку и не показывается ученику как подтверждённая обратная связь.'));
      (record.semantic_validation?.issues || []).forEach((issue) => narrative.append(node('p', 'tc-muted', issue)));
      if (safe.student_feedback) narrative.append(node('p', '', `Проверенная формулировка Tutor Core · черновик для преподавателя: ${safe.student_feedback}`));
      if (safe.teacher_explanation) narrative.append(node('p', '', `Основание для преподавателя: ${safe.teacher_explanation}`));
      if (record.unverified_narrative) {
        const details = node('details', '');
        details.append(node('summary', '', 'Показать непроверенный текст модели для экспертного разбора'));
        const raw = record.unverified_narrative;
        if (typeof raw === 'string') details.append(node('p', '', raw));
        else Object.entries(raw).forEach(([key, value]) => details.append(node('p', '', `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)));
        narrative.append(details);
      }
      generateButton.disabled = true;
      generateButton.textContent = 'Запрос уже сохранён';
      if (record.can_regenerate) {
        generateButton.disabled = false;
        generateButton.textContent = 'Сформировать новую версию с проверкой';
      }
      if (actionFeedback) actionFeedback.textContent = 'Текст модели отмечен как непроверенный; детерминированное предложение и баллы не менялись.';
      if (!record.decision) review.hidden = false;
      return;
    }
    const body = record.narrative || {};
    narrative.hidden = false;
    narrative.append(node('p', '', `Комментарий ученику · черновик для преподавателя: ${body.student_feedback || '—'}`));
    narrative.append(node('p', '', `Объяснение для преподавателя: ${body.teacher_explanation || '—'}`));
    narrative.append(node('p', 'tc-muted', `Ограничение: ${body.uncertainty_note || record.proposal?.proposal?.uncertainty || '—'}`));
    const refs = (body.evidence_refs || []).join(', ');
    narrative.append(node('p', 'tc-muted', `Ссылки модели на основания: ${refs || 'не указаны'}. Баллы и план зафиксированы детерминированной частью.`));
    const knowledgeRefs = (body.knowledge_refs || []).join(', ');
    narrative.append(node('p', 'tc-muted', `Версии материалов базы знаний: ${knowledgeRefs || 'не использованы'}.`));
    generateButton.disabled = true;
    generateButton.textContent = 'Предложение сохранено';
    if (!record.decision) review.hidden = false;
    else if (actionFeedback) actionFeedback.textContent = record.decision === 'accepted'
      ? record.applied_change
        ? 'Принято преподавателем: изменение записано только в индивидуальную синтетическую копию курса.'
        : 'Решение сохранено. План не менялся, поскольку для этого предложения нет разрешённого действия адаптации.'
      : 'Отклонено и сохранено в истории; исходный план курса не изменён.';
  }

  function renderHistory() {
    const target = document.getElementById('tutorHistory');
    target.replaceChildren();
    if (!history.length) {
      target.append(node('p', 'tc-muted', 'Сохранённых предложений пока нет.'));
      return;
    }
    history.slice().reverse().forEach((entry) => {
      const card = node('article', 'tc-history-item');
      card.append(node('h3', '', `${entry.profile_label} · ${entry.decision === 'accepted' ? 'принято' : entry.decision === 'rejected' ? 'отклонено' : entry.status === 'succeeded' ? 'ожидает решения' : 'ошибка'}`));
      card.append(node('p', 'tc-muted', entry.created_at ? new Date(entry.created_at).toLocaleString('ru-RU') : 'Время не указано'));
      card.append(node('p', '', entry.proposal?.proposal?.text || 'Запрос не сформировал предложение.'));
      if (entry.decision_at) card.append(node('p', 'tc-muted', `Решение сохранено: ${new Date(entry.decision_at).toLocaleString('ru-RU')}`));
      if (entry.applied_change) {
        card.append(node('p', 'tc-muted', `Изменена индивидуальная копия #${entry.applied_change.course_id}, урок ${entry.applied_change.lesson_id}; версия ${entry.applied_change.old_course_version} → ${entry.applied_change.new_course_version}. Шаблон курса не менялся.`));
        if (entry.rollback_at) {
          card.append(node('p', 'tc-muted', `Изменение восстановлено: ${new Date(entry.rollback_at).toLocaleString('ru-RU')}.`));
        } else {
          const rollback = node('button', 'tc-button tc-secondary', 'Отменить адаптацию');
          rollback.type = 'button';
          rollback.addEventListener('click', () => rollbackDecision(entry, rollback));
          card.append(rollback);
        }
      }
      target.append(card);
    });
  }

  async function loadHistory() {
    const response = await fetch(root.dataset.historyUrl, { credentials: 'same-origin' });
    const body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось загрузить историю Tutor Core.');
    history.splice(0, history.length, ...(body.history || []));
    renderHistory();
    renderCase(selectedId);
  }

  async function rollbackDecision(entry, button) {
    if (!entry.decision_id) return;
    button.disabled = true;
    try {
      const rollbackUrl = root.dataset.rollbackUrl.replace('/0/rollback', `/${entry.decision_id}/rollback`);
      const response = await fetch(rollbackUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({}),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось восстановить индивидуальный план.');
      await loadHistory();
    } catch (error) {
      button.disabled = false;
      const message = node('p', 'tc-error', error.message || 'Не удалось восстановить индивидуальный план.');
      button.after(message);
    }
  }

  document.querySelectorAll('[data-profile-id]').forEach((button) => {
    button.addEventListener('click', () => renderCase(button.dataset.profileId));
  });

  generateButton.addEventListener('click', async () => {
    await submitProposal(true, generateButton);
  });

  async function submitProposal(includeModel, button) {
    button.disabled = true;
    if (actionFeedback) actionFeedback.textContent = includeModel
      ? 'Запрос поставлен в последовательную очередь GigaChat…'
      : 'Сохраняем локальный предпросмотр без вызова GigaChat…';
    try {
      const response = await fetch(root.dataset.proposalsUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({profile_id: selectedId, model: root.dataset.model, include_model: includeModel}),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Предложение не сохранено.');
      await loadHistory();
      if (actionFeedback) actionFeedback.textContent = includeModel
        ? 'Комментарий сохранён. Проверьте основания и неопределённость перед решением.'
        : 'Локальный предпросмотр сохранён; внешняя модель не вызывалась.';
    } catch (error) {
      if (actionFeedback) actionFeedback.textContent = error.message || 'Не удалось сформировать предложение.';
      button.disabled = includeModel;
      if (includeModel) button.textContent = 'Запрос уже выполнялся';
      loadHistory().catch(() => {});
    }
  }

  if (localPreviewButton) {
    localPreviewButton.addEventListener('click', () => submitProposal(false, localPreviewButton));
  }

  document.querySelectorAll('[data-review]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!selectedRecordId) return;
      document.querySelectorAll('[data-review]').forEach((item) => { item.disabled = true; });
      if (actionFeedback) actionFeedback.textContent = 'Сохраняем решение преподавателя…';
      try {
        const reviewUrl = root.dataset.reviewUrl.replace('/0/review', `/${selectedRecordId}/review`);
        const response = await fetch(reviewUrl, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
          body: JSON.stringify({decision: button.dataset.review}),
        });
        const body = await response.json();
        if (!response.ok || !body.ok) throw new Error(body.error || 'Решение не сохранено.');
        await loadHistory();
      } catch (error) {
        if (actionFeedback) actionFeedback.textContent = error.message || 'Не удалось сохранить решение.';
        document.querySelectorAll('[data-review]').forEach((item) => { item.disabled = false; });
      }
    });
  });

  renderCase(selectedId);
  loadHistory().catch((error) => {
    const target = document.getElementById('tutorHistory');
    target.replaceChildren(node('p', 'tc-muted', error.message || 'Не удалось загрузить историю.'));
  });
})();
