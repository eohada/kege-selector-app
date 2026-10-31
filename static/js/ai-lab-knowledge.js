(() => {
  const root = document.getElementById('knowledgeBase');
  const stateNode = document.getElementById('knowledgeState');
  if (!root || !stateNode) return;

  let state;
  try { state = JSON.parse(stateNode.textContent || '{}'); } catch (_) { return; }
  const csrf = root.dataset.csrf || '';
  const entries = new Map((state.entries || []).map((item) => [item.stable_key, item]));
  const sourceByKey = new Map((state.sources || []).map((item) => [item.source_key, item]));
  let selectedKey = null;
  let selectedEntry = null;
  let selectedVersion = null;
  let versionHistory = [];
  let selectedVersionId = null;

  const make = (tag, className, text) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  };
  const button = (label, className, handler) => {
    const item = make('button', className, label);
    item.type = 'button';
    item.addEventListener('click', handler);
    return item;
  };
  const safeJson = (value) => JSON.stringify(value, null, 2);

  async function api(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.method && options.method !== 'GET' ? { 'X-CSRFToken': csrf } : {}),
        ...(options.headers || {}),
      },
    });
    let body = {};
    try { body = await response.json(); } catch (_) { /* handled as a plain server error below */ }
    if (!response.ok || body.ok === false) throw new Error(body.error || body.message || `Запрос не выполнен (${response.status}).`);
    return body;
  }

  function renderSources() {
    const container = document.getElementById('knowledgeSources');
    container.replaceChildren();
    (state.sources || []).forEach((source) => {
      const card = make('article', 'kb-source');
      const badge = make('span', 'kb-source-status', source.source_status === 'official_project' ? 'Официальный проект' : source.source_status === 'official_final' ? 'Окончательная редакция' : source.source_status === 'primary_standard' ? 'Первичный стандарт' : 'Документация разработчика');
      badge.dataset.status = source.source_status;
      const title = make('strong', '', source.title);
      const edition = make('small', 'tc-muted', `${source.publisher} · ${source.edition}`);
      const link = make('a', '', 'Открыть первоисточник');
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.append(badge, title, edition, link);
      if (source.content_sha256) {
        const hash = make('code', '', `SHA-256 архива: ${source.content_sha256}`);
        card.append(hash);
      }
      if (source.metadata?.coverage_role) card.append(make('small', 'tc-muted', source.metadata.coverage_role));
      container.append(card);
    });
  }

  function renderCoverage() {
    const container = document.getElementById('knowledgeCoverage');
    container.replaceChildren();
    (state.coverage_groups || []).forEach((group) => {
      const section = make('section', 'kb-coverage-section');
      section.append(make('h3', '', `${group.code}. ${group.title}`));
      const list = make('ul', 'kb-coverage-list');
      group.items.forEach((row) => {
        const line = make('li', 'kb-coverage-row');
        const code = button(row.code, 'kb-coverage-code', () => {
          const input = document.getElementById('knowledgeSearch');
          input.value = row.code;
          renderEntries();
          document.getElementById('knowledgeEntryList').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
        const title = make('span', 'kb-coverage-title', row.title);
        const status = make('span', 'kb-coverage-status', state.status_labels[row.status] || row.status);
        status.dataset.status = row.status;
        line.append(code, title, status);
        if (!row.in_fipi_2026_kim) line.append(make('span', 'kb-coverage-label', 'не включён в КИМ 2026'));
        const quality = row.quality || {};
        const qualityDetails = make('details', 'kb-coverage-details');
        qualityDetails.append(make('summary', '', 'Показатели и ограничения'));
        const metrics = [
          'Материалов: ' + row.entry_count,
          'Полных структурных карточек: ' + (quality.full_card_count || 0),
          'Примеров: ' + (quality.example_count || 0) + ' · с авторскими шагами проверки: ' + (quality.examples_with_authored_checks || 0),
          'Диагностик: ' + (quality.diagnostic_count || 0),
          'Карт предпосылок: ' + (quality.prerequisite_map_count || 0),
          'Синтетические техпроверки: текущая версия ' + (quality.machine_check_case_count || 0) + ' · прежние версии ' + (quality.machine_check_outdated_count || 0),
          'Редакционно проверено: ' + (quality.reviewed_count || 0) + ' · утверждено: ' + (quality.approved_count || 0),
          'Связей с заданиями: предварительных ' + (quality.preliminary_task_link_count || 0) + ' · точных проверенных ' + (quality.verified_task_binding_count || 0),
        ];
        const metricsList = make('ul', '');
        metrics.forEach((metric) => metricsList.append(make('li', '', metric)));
        qualityDetails.append(metricsList);
        line.append(qualityDetails);
        list.append(line);
      });
      section.append(list);
      container.append(section);
    });
  }

  function renderEntries() {
    const query = (document.getElementById('knowledgeSearch').value || '').trim().toLocaleLowerCase('ru');
    const stopTerms = new Set(['для', 'или', 'это', 'как', 'что', 'при', 'если', 'почему', 'не']);
    const queryTerms = (query.match(/[a-zа-яё0-9_./%&+-]+/g) || [])
      .filter((term) => term.length > 2 && !stopTerms.has(term));
    const requiredMatches = Math.min(2, queryTerms.length);
    const queueFilter = document.getElementById('knowledgeQueueFilter').value;
    const subjectFilter = document.getElementById('knowledgeSubjectFilter').value;
    const container = document.getElementById('knowledgeEntryList');
    container.replaceChildren();
    const visible = [...entries.values()].filter((entry) => {
      const body = entry.content || {};
      const text = (entry.title + ' ' + entry.stable_key + ' ' + (entry.codifier_codes || []).join(' ') +
        ' ' + (entry.tags || []).join(' ') + ' ' + JSON.stringify(body)).toLocaleLowerCase('ru');
      const matchesQuery = !queryTerms.length || queryTerms.filter((term) => text.includes(term)).length >= requiredMatches;
      const matchesSubject = subjectFilter === 'all' || (entry.codifier_codes || []).some((code) => code.startsWith(subjectFilter + '.'));
      const isPending = ['draft', 'source_checked', 'in_review', 'rework', 'reviewed'].includes(entry.status);
      const matchesQueue = queueFilter === 'all' ||
        (queueFilter === 'review' && isPending) ||
        (queueFilter === 'approved' && entry.status === 'approved') ||
        (queueFilter === 'rejected' && ['rejected', 'retired'].includes(entry.status));
      return matchesQuery && matchesSubject && matchesQueue;
    });
    document.getElementById('knowledgeResultCount').textContent = 'Показано ' + visible.length + ' из ' + entries.size + ' материалов';
    if (!visible.length) {
      container.append(make('p', 'kb-empty', 'Материалы не найдены. Добавьте новую заметку или измените запрос.'));
      return;
    }
    visible.forEach((entry) => {
      const item = button('', `kb-entry-button${entry.stable_key === selectedKey ? ' is-selected' : ''}`, () => loadEntry(entry.stable_key));
      item.setAttribute('role', 'listitem');
      item.append(make('strong', '', entry.title));
      const meta = make('span', 'kb-entry-meta', 'v' + entry.version_no + ' · ' + entry.codifier_codes.join(', ') + ' · ' + (state.status_labels[entry.status] || entry.status));
      item.append(meta);
      if (['draft', 'source_checked', 'in_review', 'rework', 'reviewed'].includes(entry.status)) {
        const queueLabel = entry.status === 'rework' ? 'Требуется доработка'
          : entry.status === 'reviewed' ? 'Ожидает решения владельца'
            : 'В очереди проверки';
        item.append(make('span', 'kb-queue-badge', queueLabel));
      }
      container.append(item);
    });
  }

  function addSection(container, heading, text) {
    const section = make('section', '');
    section.append(make('h3', '', heading), make('p', '', text));
    container.append(section);
  }

  function renderDetail(version, history = versionHistory) {
    const container = document.getElementById('knowledgeDetail');
    const review = document.getElementById('knowledgeReview');
    const feedback = document.getElementById('knowledgeFeedback');
    container.replaceChildren();
    feedback.textContent = '';
    if (!version) {
      container.append(make('p', 'tc-muted', 'Выберите материал, чтобы посмотреть доказательную основу и версии.'));
      review.hidden = true;
      return;
    }
    const heading = make('div', 'tc-section-title');
    const titleGroup = make('div', '');
    titleGroup.append(make('p', 'tc-eyebrow', `${version.stable_key} · версия ${version.version_no}`), make('h2', '', version.title));
    const status = make('span', 'kb-entry-status', state.status_labels[version.status] || version.status);
    status.dataset.status = version.status;
    heading.append(titleGroup, status);
    container.append(heading);

    const versionBar = make('div', 'kb-version-bar');
    versionBar.append(make('label', 'tc-muted', 'Версия:'));
    const select = make('select', 'kb-input');
    select.setAttribute('aria-label', 'Выбрать версию материала');
    history.forEach((item) => {
      const option = make('option', '', `v${item.version_no} · ${state.status_labels[item.status] || item.status}`);
      option.value = String(item.version_id);
      option.selected = item.version_id === version.version_id;
      select.append(option);
    });
    select.addEventListener('change', () => {
      const target = history.find((item) => item.version_id === Number(select.value));
      selectedVersionId = target?.version_id || null;
      selectedVersion = target || null;
      renderDetail(selectedVersion, history);
    });
    versionBar.append(select);
    const selectedIndex = history.findIndex((item) => item.version_id === version.version_id);
    const olderVersion = history[selectedIndex + 1];
    if (olderVersion) {
      versionBar.append(button('Сравнить выбранную версию с предыдущей', 'tc-button', () => renderComparison(container, version, olderVersion)));
    }
    const current = history[0];
    versionBar.append(button('Создать новую версию', 'tc-button tc-primary', () => openEditor(selectedEntry, current)));
    container.append(versionBar);
    if (version.version_id !== current?.version_id) container.append(make('p', 'tc-notice', 'Это сохранённый исторический снимок. Его содержимое не редактируется; новая работа создаёт следующую версию.'));

    const content = version.content || {};
    addSection(container, 'Цель обучения', content.learning_goal || '—');
    addSection(container, 'Объяснение', content.explanation || '—');
    if (content.assessed_skill) {
      addSection(container, 'Проверяемый навык', `${content.assessed_skill.name} · ${content.assessed_skill.skill_key}`);
      addStructuredList(container, 'Наблюдаемые действия', (content.assessed_skill.observable_actions || []).map((body, index) => ({
        heading: `Действие ${index + 1}`, body,
      })), 'heading', 'body');
    }
    if (content.skill_progression?.length) {
      const stageLabels = {
        concept: 'Понимание понятия', routine: 'Стандартное действие', choice: 'Выбор метода',
        transfer: 'Перенос на новую задачу', verification: 'Независимая проверка',
      };
      addStructuredList(container, 'Ступени развития навыка', content.skill_progression.map((item) => ({
        heading: stageLabels[item.stage_key] || item.stage_key, body: item.description,
      })), 'heading', 'body');
    }
    if (content.solution_steps?.length) {
      addStructuredList(container, 'Пошаговый способ решения', content.solution_steps.map((body, index) => ({
        heading: `Шаг ${index + 1}`, body,
      })), 'heading', 'body');
    }
    if (content.student_explanation) addSection(container, 'Кратко для ученика', content.student_explanation);
    if (content.teacher_explanation) addSection(container, 'Пояснение для преподавателя', content.teacher_explanation);

    const exampleWrap = make('section', '');
    exampleWrap.append(make('h3', '', 'Примеры'));
    const exampleGrid = make('div', 'kb-detail-grid');
    (content.examples || []).forEach((example, index) => {
      const card = make('article', 'kb-content-card');
      card.append(make('h4', '', `Пример ${index + 1}`), make('p', '', example.prompt), make('p', '', `Рассуждение: ${example.reasoning}`), make('p', '', `Ответ: ${example.answer}`));
      if (example.checks?.length) {
        const list = make('ul', '');
        example.checks.forEach((check) => list.append(make('li', '', check)));
        card.append(list);
      }
      exampleGrid.append(card);
    });
    exampleWrap.append(exampleGrid);
    container.append(exampleWrap);

    const misconceptionWrap = make('section', '');
    misconceptionWrap.append(make('h3', '', 'Типичные заблуждения'));
    const misconceptionGrid = make('div', 'kb-detail-grid');
    (content.misconceptions || []).forEach((item) => {
      const card = make('article', 'kb-content-card');
      card.append(make('h4', '', item.belief), make('p', '', `Контрпример: ${item.counterexample}`), make('p', '', `Уточнение: ${item.correction}`));
      misconceptionGrid.append(card);
    });
    misconceptionWrap.append(misconceptionGrid);
    container.append(misconceptionWrap);
    addStructuredList(container, 'Диагностические вопросы', content.diagnostics || [], 'prompt', 'signals');
    if (content.diagnostic_patterns?.length) {
      addStructuredList(container, 'Как различать случайную ошибку и пробел в понимании', content.diagnostic_patterns.map((item) => ({
        heading: item.response_pattern,
        body: `${item.interpretation} Проверка: ${item.follow_up}`,
      })), 'heading', 'body');
    }
    addStructuredList(container, 'Предлагаемые педагогические действия', content.interventions || [], 'signal', 'action');
    addSection(container, 'Граница применимости', content.assessment_boundary || '—');
    if (content.subject_checks?.length) {
    addStructuredList(container, 'Описания предметных автопроверок · исполнение не записано', content.subject_checks.map((item) => ({
        heading: item.test_id,
      body: item.method + ' Область: ' + item.scope + ' Результат запуска в базе знаний не хранится; ссылка не означает PASS.',
      })), 'heading', 'body');
    }
    const technicalAudits = (state.technical_audits || []).filter((item) => item.stable_key === version.stable_key);
    if (technicalAudits.length) {
      const auditSection = make('section', '');
      auditSection.append(make('h3', '', 'Независимые синтетические техпроверки'));
      auditSection.append(make('p', 'tc-muted', 'Проверки подтверждают только указанные входы и вычисления. Это не запуск Code Judge, не доказательство полной корректности материала и не экспертное утверждение.'));
      const auditList = make('div', 'kb-detail-grid');
      technicalAudits.forEach((audit) => {
        const appliesToSelectedVersion = audit.version_no === version.version_no && audit.content_sha256 === version.content_sha256;
        const card = make('article', 'kb-content-card kb-audit-card');
        card.append(
          make('h4', '', audit.case_id),
          make('p', '', `${audit.audit_series || 'Синтетическая проверка'} · ${audit.domain} · ${audit.recorded_at} · ${audit.result === 'passed' ? 'Зафиксированный результат: PASS' : 'Нет результата'}`),
          make('p', '', appliesToSelectedVersion ? 'Отчёт привязан к этой версии и её SHA-256.' : `Отчёт относится к v${audit.version_no}; выбранная версия: v${version.version_no}. Результат не переносится на неё.`),
          make('p', '', `Метод: ${audit.method}`),
          make('p', '', `Вход: ${JSON.stringify(audit.input)}`),
          make('p', '', `Получено: ${JSON.stringify(audit.observed)}`),
          make('p', '', `Граница: ${audit.scope}`),
          make('small', 'tc-muted', audit.result_basis)
        );
        auditList.append(card);
      });
      auditSection.append(auditList);
      container.append(auditSection);
    }
    const pilotDossier = (state.expert_pilot_dossiers || []).find((item) => item.stable_key === version.stable_key);
    if (pilotDossier) {
      const pilotSection = make('section', 'kb-pilot-dossier');
      pilotSection.append(
        make('h3', '', 'Досье экспертного пилота'),
        make('p', 'tc-notice', 'Статус: ожидает решения преподавателя. Ситуация ниже синтетическая и не является наблюдением за учеником; досье не утверждает материал.'),
        make('p', '', `Сценарий ${pilotDossier.scenario_id}: ${pilotDossier.scenario}`),
        make('p', '', `Что подтверждается: ${pilotDossier.observed_evidence}`),
        make('p', '', `Диагностика: ${pilotDossier.diagnostic}`),
        make('p', '', `Предложенный следующий шаг для обсуждения: ${pilotDossier.next_action}`),
        make('p', 'tc-muted', `Приоритет и экзаменационная связь: ${pilotDossier.priority_note}`),
        make('p', 'tc-muted', pilotDossier.matches_current_version
          ? `Досье и техпроверка привязаны к этой версии (${pilotDossier.content_sha256}).`
          : `Досье составлено для v${pilotDossier.version_no}; выбранная версия v${version.version_no}. Нужна повторная проверка перед использованием.`)
      );
      const questions = make('ul', '');
      pilotDossier.human_questions.forEach((question) => questions.append(make('li', '', question)));
      const questionSection = make('section', '');
      questionSection.append(make('h4', '', 'Вопросы преподавателю'), questions);
      pilotSection.append(questionSection);
      container.append(pilotSection);
    }
    if (content.prerequisites?.length) {
      const prerequisiteSection = make('section', '');
      prerequisiteSection.append(make('h3', '', 'Предварительные знания'));
      const prerequisiteList = make('ul', 'kb-prerequisite-list');
      content.prerequisites.forEach((key) => {
        const row = make('li', '');
        const prerequisite = entries.get(key);
        if (prerequisite) {
          row.append(button(prerequisite.title, 'kb-prerequisite-link', () => loadEntry(key)));
          row.append(make('span', 'tc-muted', ' · ' + (state.status_labels[prerequisite.status] || prerequisite.status)));
        } else {
          row.append(make('span', 'kb-missing-prerequisite', key + ' · материал отсутствует в каталоге'));
        }
        prerequisiteList.append(row);
      });
      prerequisiteSection.append(prerequisiteList);
      container.append(prerequisiteSection);
    }
    if (content.curriculum_suggestions?.length) {
      addStructuredList(container, 'Предложения по связям с уроками', content.curriculum_suggestions.map((body, index) => ({
        heading: `Предложение ${index + 1}`, body,
      })), 'heading', 'body');
    }
    if (content.lesson_links?.length) {
      addStructuredList(container, 'Связи с уроками курса', content.lesson_links.map((item) => ({
        heading: `Курс ${item.course_id} · урок ${item.lesson_id} · ${item.skill_id}`,
        body: `${item.relationship === 'curriculum' ? 'Связь в структуре курса' : 'Предварительная связь'}. ${item.rationale}`,
      })), 'heading', 'body');
    }
    if (content.task_links?.length) {
      addStructuredList(container, 'Предварительные связи с заданиями', content.task_links.map((item) => ({
        heading: `Курс ${item.course_id} · задание №${item.task_number} · ${item.skill_id}`,
        body: `${item.relationship === 'curriculum' ? 'Связь в структуре курса' : 'Нужна проверка преподавателя'}. ${item.rationale}`,
      })), 'heading', 'body');
    }

    const sourceSection = make('section', '');
    sourceSection.append(make('h3', '', 'Источники и происхождение'));
    const sourceList = make('ul', 'kb-citation-list');
    (version.source_refs || []).forEach((source) => {
      const li = make('li', '');
      const link = make('a', '', `${source.publisher}: ${source.title} · ${source.edition}`);
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      li.append(link, make('span', 'tc-muted', ` · ${source.source_status}`));
      sourceList.append(li);
    });
    sourceSection.append(sourceList, make('code', 'kb-hash', `SHA-256 материала: ${version.content_sha256}`));
    if (version.latest_review) sourceSection.append(make('p', 'tc-muted', version.latest_review.decision + ': ' + version.latest_review.rationale));
    container.append(sourceSection);
    if (version.review_history?.length) {
      const reviewSection = make('section', '');
      reviewSection.append(make('h3', '', 'История редакционных решений'));
      const reviewList = make('ul', 'kb-review-history');
      version.review_history.forEach((event) => {
        const row = make('li', 'kb-review-history-item');
        row.append(make('strong', '', (state.status_labels[event.decision] || event.decision) + ' · ' + (event.created_at || 'дата не указана')));
        row.append(make('p', '', event.rationale));
        Object.entries(event.details || {}).forEach(([key, item]) => {
          const criterion = (state.editorial_criteria || []).find((candidate) => candidate.key === key);
          if (!item.comment && item.status === 'unchecked') return;
          row.append(make('small', '', (criterion?.label || key) + ': ' + (item.status || 'не проверено') + (item.comment ? ' — ' + item.comment : '')));
        });
        reviewList.append(row);
      });
      reviewSection.append(reviewList);
      container.append(reviewSection);
    }

    const isCurrent = version.version_id === current?.version_id;
    review.hidden = !isCurrent;
    if (!isCurrent) return;
    document.getElementById('reviewRationale').value = '';
    renderReviewChecklist(version);
    document.querySelectorAll('[data-knowledge-decision]').forEach((action) => {
      action.disabled = false;
      action.onclick = () => submitReview(version.version_id, action.dataset.knowledgeDecision);
    });
  }

  function addStructuredList(container, heading, items, firstKey, secondKey) {
    const section = make('section', '');
    section.append(make('h3', '', heading));
    const grid = make('div', 'kb-detail-grid');
    items.forEach((item) => {
      const card = make('article', 'kb-content-card');
      card.append(make('h4', '', item[firstKey]), make('p', '', item[secondKey]));
      grid.append(card);
    });
    section.append(grid);
    container.append(section);
  }

  function renderReviewChecklist(version) {
    const container = document.getElementById('knowledgeReviewChecklist');
    container.replaceChildren();
    const details = version.latest_review?.details || {};
    const stateOptions = [
      ['unchecked', 'Не проверено'],
      ['checked', 'Проверено'],
      ['needs_work', 'Нужна доработка'],
      ['not_applicable', 'Не применимо'],
    ];
    (state.editorial_criteria || []).forEach((criterion) => {
      const saved = details[criterion.key] || {};
      const card = make('article', 'kb-review-criterion');
      card.append(make('strong', '', criterion.label));
      const select = make('select', 'kb-input');
      select.dataset.reviewStatus = criterion.key;
      select.setAttribute('aria-label', 'Состояние: ' + criterion.label);
      stateOptions.forEach(([value, label]) => {
        const option = make('option', '', label);
        option.value = value;
        option.selected = (saved.status || 'unchecked') === value;
        select.append(option);
      });
      const comment = make('textarea', 'kb-input');
      comment.rows = 2;
      comment.maxLength = 1200;
      comment.dataset.reviewComment = criterion.key;
      comment.setAttribute('aria-label', 'Замечание: ' + criterion.label);
      comment.placeholder = 'Короткое основание или замечание';
      comment.value = saved.comment || '';
      card.append(select, comment);
      container.append(card);
    });
  }

  function renderComparison(container, newer, older) {
    const oldContent = older.content || {};
    const newContent = newer.content || {};
    const fields = {
      title: 'Заголовок', learning_goal: 'Цель обучения', explanation: 'Объяснение',
      examples: 'Примеры', misconceptions: 'Типичные заблуждения', diagnostics: 'Диагностика',
      interventions: 'Педагогические действия', assessment_boundary: 'Границы применимости',
      prerequisites: 'Предварительные знания', lesson_links: 'Связи с уроками',
      task_links: 'Предварительные связи с заданиями', platform_task_links: 'Точные связи с заданиями',
      assessed_skill: 'Проверяемый навык', skill_progression: 'Ступени навыка',
      solution_steps: 'Шаги решения', student_explanation: 'Объяснение ученику',
      teacher_explanation: 'Пояснение преподавателю', diagnostic_patterns: 'Диагностические паттерны',
      subject_checks: 'Предметные проверки', curriculum_suggestions: 'Предложения по курсу',
    };
    const panel = make('section', 'kb-compare');
    panel.append(make('h3', '', 'Сравнение v' + older.version_no + ' → v' + newer.version_no));
    let changeCount = 0;
    Object.entries(fields).forEach(([field, label]) => {
      const before = field === 'title' ? older.title : oldContent[field];
      const after = field === 'title' ? newer.title : newContent[field];
      if (JSON.stringify(before) === JSON.stringify(after)) return;
      changeCount += 1;
      const row = make('article', 'kb-compare-row');
      row.append(make('h4', '', label));
      const pair = make('div', 'kb-compare-pair');
      const oldColumn = make('div', 'kb-compare-value');
      oldColumn.append(make('small', '', 'До · v' + older.version_no), make('pre', '', safeJson(before ?? null)));
      const newColumn = make('div', 'kb-compare-value');
      newColumn.append(make('small', '', 'После · v' + newer.version_no), make('pre', '', safeJson(after ?? null)));
      pair.append(oldColumn, newColumn);
      row.append(pair);
      panel.append(row);
    });
    if (!changeCount) panel.append(make('p', 'tc-muted', 'Содержимое не изменилось; различаются только статус или редакционное решение.'));
    const oldPanel = container.querySelector('.kb-compare');
    if (oldPanel) oldPanel.remove();
    container.append(panel);
  }

  async function loadEntry(stableKey) {
    const item = entries.get(stableKey);
    if (!item) return;
    selectedKey = stableKey;
    selectedEntry = item;
    try {
      const path = root.dataset.entryUrlTemplate.replace(/0$/, String(item.id));
      const body = await api(path);
      versionHistory = body.entry.versions || [];
      selectedVersion = versionHistory[0] || null;
      selectedVersionId = selectedVersion?.version_id || null;
      renderDetail(selectedVersion);
      renderEntries();
    } catch (error) {
      document.getElementById('knowledgeDetail').replaceChildren(make('p', 'tc-error', error.message));
    }
  }

  function openEditor(entry, version) {
    const details = document.getElementById('knowledgeEditor');
    const form = document.getElementById('knowledgeEntryForm');
    const content = version?.content || {};
    const set = (name, value) => { form.elements.namedItem(name).value = value ?? ''; };
    document.getElementById('editorHeading').textContent = entry ? `Новая версия · ${version.title}` : 'Новый материал';
    set('title', entry ? version.title : '');
    set('stable_key', entry?.stable_key || '');
    set('codifier_codes', entry?.codifier_codes?.join(', ') || '');
    set('tags', version?.tags?.join(', ') || '');
    set('source_refs', (version?.source_refs || []).map((source) => source.source_key).join(', '));
    set('learning_goal', content.learning_goal || '');
    set('explanation', content.explanation || '');
    set('examples', safeJson(content.examples || [{ prompt: '', reasoning: '', answer: '', checks: [''] }]));
    set('misconceptions', safeJson(content.misconceptions || [{ belief: '', counterexample: '', correction: '' }]));
    set('diagnostics', safeJson(content.diagnostics || [{ prompt: '', signals: '' }]));
    set('interventions', safeJson(content.interventions || [{ signal: '', action: '' }]));
    set('assessment_boundary', content.assessment_boundary || '');
    set('prerequisites', (content.prerequisites || []).join(', '));
    set('lesson_links', safeJson(content.lesson_links || []));
    set('task_links', safeJson(content.task_links || []));
    const fullCard = Boolean(content.assessed_skill);
    form.elements.namedItem('full_pedagogical_card').checked = fullCard;
    document.getElementById('fullPedagogicalFields').hidden = !fullCard;
    set('skill_key', content.assessed_skill?.skill_key || '');
    set('skill_name', content.assessed_skill?.name || '');
    set('observable_actions', safeJson(content.assessed_skill?.observable_actions || []));
    set('skill_progression', safeJson(content.skill_progression || []));
    set('solution_steps', safeJson(content.solution_steps || []));
    set('student_explanation', content.student_explanation || '');
    set('teacher_explanation', content.teacher_explanation || '');
    set('diagnostic_patterns', safeJson(content.diagnostic_patterns || []));
    set('subject_checks', safeJson(content.subject_checks || []));
    set('curriculum_suggestions', safeJson(content.curriculum_suggestions || []));
    set('change_reason', entry ? '' : 'Новый материал для локальной AI Lab');
    form.elements.namedItem('stable_key').readOnly = Boolean(entry);
    form.elements.namedItem('codifier_codes').readOnly = Boolean(entry);
    details.open = true;
    details.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function parseFormJson(form, field, optional = false) {
    const value = form.elements.namedItem(field).value.trim();
    if (optional && !value) return [];
    try { return JSON.parse(value); }
    catch (_) { throw new Error(`Поле «${field}» содержит некорректный JSON.`); }
  }

  document.querySelector('[name="full_pedagogical_card"]').addEventListener('change', (event) => {
    document.getElementById('fullPedagogicalFields').hidden = !event.currentTarget.checked;
  });

  document.getElementById('knowledgeEntryForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = document.getElementById('knowledgeFeedback');
    feedback.textContent = '';
    try {
      const values = (name) => form.elements.namedItem(name).value.trim();
      const content = {
        learning_goal: values('learning_goal'), explanation: values('explanation'),
        examples: parseFormJson(form, 'examples'), misconceptions: parseFormJson(form, 'misconceptions'),
        diagnostics: parseFormJson(form, 'diagnostics'), interventions: parseFormJson(form, 'interventions'),
        assessment_boundary: values('assessment_boundary'),
        prerequisites: values('prerequisites').split(',').map((value) => value.trim()).filter(Boolean),
        lesson_links: parseFormJson(form, 'lesson_links', true),
        task_links: parseFormJson(form, 'task_links', true),
      };
      if (form.elements.namedItem('full_pedagogical_card').checked) {
        content.assessed_skill = {
          skill_key: values('skill_key'), name: values('skill_name'),
          observable_actions: parseFormJson(form, 'observable_actions'),
        };
        content.skill_progression = parseFormJson(form, 'skill_progression');
        content.solution_steps = parseFormJson(form, 'solution_steps');
        content.student_explanation = values('student_explanation');
        content.teacher_explanation = values('teacher_explanation');
        content.diagnostic_patterns = parseFormJson(form, 'diagnostic_patterns');
        content.subject_checks = parseFormJson(form, 'subject_checks');
        content.curriculum_suggestions = parseFormJson(form, 'curriculum_suggestions');
      }
      const payload = {
        stable_key: values('stable_key'),
        title: values('title'),
        codifier_codes: values('codifier_codes').split(',').map((value) => value.trim()).filter(Boolean),
        tags: values('tags').split(',').map((value) => value.trim()).filter(Boolean),
        source_refs: values('source_refs').split(',').map((value) => value.trim()).filter(Boolean),
        change_reason: values('change_reason'),
        content,
      };
      await api(root.dataset.createUrl, { method: 'POST', body: JSON.stringify(payload) });
      await reloadState(payload.stable_key);
      document.getElementById('knowledgeEditor').open = false;
      feedback.textContent = 'Сохранена новая неизменяемая версия со статусом «Черновик». Предыдущие версии сохранены.';
    } catch (error) {
      feedback.textContent = error.message;
    }
  });

  async function submitReview(versionId, decision) {
    const feedback = document.getElementById('knowledgeFeedback');
    const rationale = document.getElementById('reviewRationale').value.trim();
    const reviewDetails = {};
    document.querySelectorAll('[data-review-status]').forEach((select) => {
      const key = select.dataset.reviewStatus;
      const comment = document.querySelector('[data-review-comment="' + key + '"]');
      reviewDetails[key] = { status: select.value, comment: comment?.value.trim() || '' };
    });
    feedback.textContent = '';
    document.querySelectorAll('[data-knowledge-decision]').forEach((item) => { item.disabled = true; });
    try {
      const reviewPath = root.dataset.reviewUrlTemplate.replace(/\/0\/review$/, `/${versionId}/review`);
      await api(reviewPath, { method: 'POST', body: JSON.stringify({ decision, rationale, review_details: reviewDetails }) });
      await reloadState(selectedKey);
      feedback.textContent = decision === 'rework'
        ? 'Замечания сохранены; версия возвращена в очередь доработки.'
        : decision === 'in_review'
          ? 'Ход проверки сохранён; материал остаётся в очереди.'
          : 'Решение сохранено в журнале; версия и её содержимое не изменены.';
    } catch (error) {
      feedback.textContent = error.message;
      document.querySelectorAll('[data-knowledge-decision]').forEach((item) => { item.disabled = false; });
    }
  }

  async function reloadState(keepKey = selectedKey) {
    const response = await api(root.dataset.apiUrl);
    state = response.knowledge_base;
    entries.clear();
    (state.entries || []).forEach((item) => entries.set(item.stable_key, item));
    sourceByKey.clear();
    (state.sources || []).forEach((item) => sourceByKey.set(item.source_key, item));
    renderSources();
    renderCoverage();
    renderEntries();
    if (keepKey && entries.has(keepKey)) await loadEntry(keepKey);
  }

  document.getElementById('knowledgeSearch').addEventListener('input', renderEntries);
  document.getElementById('knowledgeQueueFilter').addEventListener('change', renderEntries);
  document.getElementById('knowledgeSubjectFilter').addEventListener('change', renderEntries);
  (state.coverage_groups || []).forEach((group) => {
    const option = make('option', '', group.code + '. ' + group.title);
    option.value = group.code;
    document.getElementById('knowledgeSubjectFilter').append(option);
  });
  document.getElementById('newKnowledgeEntry').addEventListener('click', () => openEditor(null, null));
  document.getElementById('cancelKnowledgeEdit').addEventListener('click', () => { document.getElementById('knowledgeEditor').open = false; });
  renderSources();
  renderCoverage();
  renderEntries();
  if (entries.size) loadEntry(entries.keys().next().value);
})();
