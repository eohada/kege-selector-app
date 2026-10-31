(() => {
  const root = document.getElementById('ai-lesson-app');
  const sampleNode = document.getElementById('li-samples');
  if (!root || !sampleNode) return;
  let samples = [];
  try { samples = JSON.parse(sampleNode.textContent || '[]'); } catch (_) { return; }

  const sampleSelect = document.getElementById('li-sample');
  const platformLesson = document.getElementById('li-platform-lesson');
  const lessonId = document.getElementById('li-lesson-id');
  const lessonVersion = document.getElementById('li-lesson-version');
  const sessionMinutes = document.getElementById('li-session-minutes');
  const transcript = document.getElementById('li-transcript');
  const syntheticConfirm = document.getElementById('li-synthetic-confirm');
  const fileInput = document.getElementById('li-file');
  const runButton = document.getElementById('li-analyze');
  const resumeBase = root.dataset.resumeBase;
  const status = document.getElementById('li-status');
  const result = document.getElementById('li-result');
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const stateLabels = {
    unresolved_or_unknown: 'Затруднение остаётся открытым или данных недостаточно',
    corrected_after_hint: 'Ответ скорректирован после помощи · самостоятельность не подтверждена',
    partial_progress: 'Есть частичный прогресс · требуется отдельная проверка',
    independent_application_candidate: 'Есть кандидат на самостоятельное применение · нужна ручная проверка',
    durable_mastery_candidate: 'Есть кандидат на устойчивое применение · нужна ручная проверка',
    verbal_claim_only: 'Ученик заявил о понимании · решение навыка не подтверждено',
    insufficient_evidence: 'Недостаточно данных для вывода',
    resolved_in_lesson: 'Исправление подтверждено вручную',
  };
  const eventLabels = {
    independent_demonstration: 'самостоятельное применение',
    after_hint_demonstration: 'ответ после подсказки',
    repeated_difficulty: 'повторное затруднение',
    partial_progress: 'частичный прогресс',
    self_correction: 'самокоррекция',
    resolved_difficulty: 'словесное заявление о решении',
    verbal_understanding_claim: 'словесное заявление о понимании',
    difficulty_self_report: 'самоотчёт о затруднении',
    other: 'нужна ручная интерпретация',
  };
  const hintStatusLabels = {
    explicit_no_hint: 'есть явное условие работать без подсказки',
    explicit_independent_prompt: 'ученик должен выполнить действие самостоятельно',
    teacher_prompt_before_response: 'перед ответом была реплика преподавателя',
    teacher_context_cited: 'цитируется контекст преподавателя; характер помощи не установлен',
    no_recent_teacher_prompt_in_cited_context: 'в ближайшем цитируемом контексте нет реплики преподавателя',
    unknown: 'не установлен по сохранённым данным',
  };
  const reviewStatusLabels = {
    pending: 'ожидает ручной проверки',
    approved: 'подтверждено владельцем',
    rejected: 'отклонено владельцем',
  };

  function openSource(segment) {
    const start = Number(segment.source_start_char);
    const end = Number(segment.source_end_char);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
      status.textContent = `Источник: строка ${segment.source_line ?? '—'}${segment.source_line_end ? `–${segment.source_line_end}` : ''}. Для этой записи точный диапазон символов не сохранён.`;
      return;
    }
    transcript.focus();
    transcript.setSelectionRange(start, end);
    transcript.scrollIntoView({behavior: 'smooth', block: 'center'});
    status.textContent = `Открыт исходный фрагмент: ${segment.speaker || 'говорящий не указан'}${segment.timestamp ? ` · ${segment.timestamp}` : ''}.`;
  }

  function renderRecord(record) {
    result.hidden = false;
    result.replaceChildren();
    const title = element('h2', '', `Анализ #${record.id} · ${record.status}`);
    result.append(title);
    const linkedSource = record.scenario_snapshot?.source_identity;
    if (linkedSource?.source_table === 'Lessons') {
      result.append(element('p', 'li-ref', `BooStudy Lesson #${linkedSource.source_record_id} · ${linkedSource.student_alias}`));
    }
    const chunks = record.quality?.chunk_progress;
    if (chunks) result.append(element('p', 'li-ref', `Части: ${chunks.completed ?? 0} из ${chunks.total ?? '—'} · вход ${record.input_tokens ?? 0} · генерация ${record.output_tokens ?? 0} токенов`));
    const sourceSegments = record.input_snapshot?.segments || [];
    const originalText = record.input_snapshot?.source_text;
    if (sourceSegments.length) {
      const lineCount = typeof originalText === 'string' ? originalText.split(/\r?\n/).length : null;
      result.append(element('p', 'li-ref', `Нормализовано реплик: ${sourceSegments.length}${lineCount ? ` · исходных строк: ${lineCount}` : ''} · версия парсера ${record.quality?.normalization_version || 'историческая'}`));
      const turns = element('details', 'li-list');
      turns.append(element('summary', '', 'Нормализованные реплики и координаты источника'));
      sourceSegments.forEach((segment) => {
        const row = element('article', 'li-card');
        row.append(element('strong', '', `${segment.segment_id} · ${segment.speaker_role || 'unknown'}${segment.timestamp ? ` · ${segment.timestamp}` : ''}`));
        row.append(element('p', 'li-muted', `${segment.speaker || 'Говорящий не указан'}: ${segment.text}`));
        row.append(element('p', 'li-ref', `Строки ${segment.source_line ?? '—'}${segment.source_line_end ? `–${segment.source_line_end}` : ''} · символы ${segment.source_start_char ?? '—'}–${segment.source_end_char ?? '—'}`));
        turns.append(row);
      });
      result.append(turns);
    }
    if (record.status !== 'succeeded') {
      result.append(element('p', 'li-error', record.error_message || 'Анализ завершился ошибкой.'));
      result.append(element('p', 'li-ref', `Код ${record.error_code || 'unknown'} · завершённые части и их расход сохранены; при продолжении будут запрошены только незавершённые части, в пределах бюджета повторов.`));
      if (typeof originalText === 'string') {
        const resume = element('button', 'li-button', 'Продолжить сохранённый анализ');
        resume.type = 'button';
        resume.addEventListener('click', async () => {
          transcript.value = originalText;
          lessonId.value = record.input_snapshot.lesson_id || lessonId.value;
          lessonVersion.value = record.input_snapshot.lesson_version || lessonVersion.value;
          if (sessionMinutes) sessionMinutes.value = record.input_snapshot.planned_session_minutes || 60;
          syntheticConfirm.checked = true;
          resume.disabled = true;
          status.textContent = 'Продолжаем сохранённый анализ из его неизменённого снимка…';
          status.className = 'li-status';
          try {
            const resumeUrl = resumeBase.replace('/0/resume', `/${record.id}/resume`);
            const response = await fetch(resumeUrl, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf}, body: '{}'});
            const body = await response.json();
            if (body.record) renderRecord(body.record);
            if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось продолжить сохранённый анализ.');
            status.textContent = 'Сохранённый анализ завершён. Выводы остаются предварительными до ручного подтверждения.';
            status.className = 'li-status li-good';
          } catch (error) {
            status.textContent = error.message || 'Не удалось продолжить сохранённый анализ.';
            status.className = 'li-status li-error';
          } finally {
            resume.disabled = false;
          }
        });
        result.append(resume);
      }
      return;
    }
    const output = record.result || {};
    const byId = new Map(sourceSegments.map((item) => [item.segment_id, item]));
    const usage = record.quality?.usage_summary;
    const aggregation = record.quality?.aggregation_report;
    const candidateCount = aggregation?.candidate_observation_count
      ?? (record.quality?.chunk_results || []).reduce((count, chunk) => count + ((chunk.result?.observed_difficulties || []).length), 0);
    result.append(element('p', 'li-lead', output.summary));
    result.append(element('p', 'li-ref', `Модель: ${record.model || '—'} · вход ${record.input_tokens ?? '—'} · генерация ${record.output_tokens ?? '—'} токенов · ${(record.duration_ms || 0) / 1000} с · ${output.verification_status}${output.completed_chunks > 1 ? ` · обработано частей ${output.completed_chunks}/${output.total_chunks}` : ''}${usage ? ` · запросов к модели ${usage.model_request_count}${usage.total_tokens_per_60min !== null ? ` · нормировка на час: ${usage.total_tokens_per_60min} токенов` : ' · расход на час не рассчитывался: в стенограмме нет временного диапазона 45 минут или больше'} · ${usage.tariff_status === 'not_configured' ? 'стоимость не рассчитана: тариф не задан' : ''}` : ''}`));
    if (candidateCount || output.observed_difficulties?.length) {
      const groupCount = aggregation?.final_skill_group_count ?? (output.observed_difficulties || []).length;
      result.append(element('p', 'li-ref', `Агрегация: ${candidateCount} наблюдений по частям сведены в ${groupCount} группы навыков по стабильным ID; исходные цитаты и противоречивые события сохраняются.${aggregation?.unpreserved_candidate_references?.length ? ` Не сопоставлены ${aggregation.unpreserved_candidate_references.length} ссылки — нужна ручная проверка.` : ''}`));
      if (aggregation?.candidate_topic_count !== undefined) result.append(element('p', 'li-ref', `Темы: ${aggregation.candidate_topic_count} кандидатов → ${aggregation.final_topic_count} тем после удаления точных и подтверждённых контекстом повторов.`));
      if ((aggregation?.possible_identity_conflicts || []).length) {
        const conflicts = element('details', 'li-card');
        conflicts.append(element('summary', '', `Возможные конфликты идентификации навыка: ${aggregation.possible_identity_conflicts.length} · нужна ручная проверка`));
        aggregation.possible_identity_conflicts.forEach((conflict) => {
          conflicts.append(element('p', 'li-ref', `${conflict.left.skill_id}/${conflict.left.skill_facet_id} и ${conflict.right.skill_id}/${conflict.right.skill_facet_id} отнесены к одним фрагментам: ${conflict.left.source_refs.join(', ')}`));
        });
        result.append(conflicts);
      }
      if ((aggregation?.chunk_summary_candidates || []).length) {
        const candidates = element('details', 'li-card');
        candidates.append(element('summary', '', 'Краткие ответы модели по частям (сохранены отдельно)'));
        aggregation.chunk_summary_candidates.forEach((item) => candidates.append(element('p', 'li-muted', `${item.chunk_id}: ${item.summary}`)));
        result.append(candidates);
      }
    }
    const topics = element('section', 'li-list');
    topics.append(element('h3', '', 'Обсуждавшиеся темы'));
    if (!(output.topics || []).length) topics.append(element('p', 'li-empty', 'Темы не выделены с достаточным основанием.'));
    (output.topics || []).forEach((topic) => {
      const card = element('article', 'li-card');
      card.append(element('strong', '', topic.title));
      card.append(element('p', 'li-ref', `${topic.topic_id} · предварительный вывод`));
      if (topic.id_resolution_status && topic.id_resolution_status !== 'model_supplied') {
        card.append(element('p', 'li-ref', 'ID создан сервером из названия и ссылок, так как модель его пропустила · сверьте тему вручную'));
      }
      if ((topic.topic_aliases || []).length > 1) card.append(element('p', 'li-ref', `Объединённые обозначения: ${topic.topic_aliases.join(', ')}`));
      if (topic.title_conflict) card.append(element('p', 'li-ref', `Названия расходятся: ${(topic.title_variants || []).join(' / ')} · проверьте вручную`));
      (topic.source_refs || [topic.source_ref]).forEach((ref) => {
        const source = byId.get(ref);
        if (source) card.append(element('p', 'li-muted', `${ref}${source.timestamp ? ` · ${source.timestamp}` : ''}${source.speaker ? ` · ${source.speaker}` : ''}: ${source.text}`));
      });
      topics.append(card);
    });
    result.append(topics);

    const summaries = element('section', 'li-list');
    summaries.append(element('h3', '', 'Фрагменты и конспект'));
    (output.content_segments || []).forEach((item) => {
      const card = element('article', 'li-card');
      card.append(element('strong', '', item.summary));
      card.append(element('p', 'li-ref', `Источник: ${(item.source_refs || [item.source_ref]).join(', ')}`));
      summaries.append(card);
    });
    result.append(summaries);

    const latest = new Map();
    (record.quality?.observation_reviews || []).forEach((review) => latest.set(review.observation_id, review));
    const difficulties = element('section', 'li-list');
    difficulties.append(element('h3', '', 'Возможные затруднения · требуется ручная проверка'));
    if (!(output.observed_difficulties || []).length) difficulties.append(element('p', 'li-empty', 'Подтверждённых текстом затруднений не обнаружено. Вопрос без явной ошибки не считается доказательством непонимания.'));
    if ((output.observed_difficulties || []).length) {
      const batch = element('div', 'li-actions');
      const selectAllLabel = element('label', 'li-select-all');
      const selectAll = element('input');
      selectAll.type = 'checkbox';
      selectAll.setAttribute('aria-label', 'Выбрать все наблюдения');
      selectAllLabel.append(selectAll, document.createTextNode(' Выбрать все'));
      batch.append(selectAllLabel);
      [['confirmed', 'Подтвердить выбранное'], ['rejected', 'Отклонить выбранное'], ['resolved', 'Отметить исправленным']].forEach(([choice, label]) => {
        const button = element('button', 'li-button', label);
        button.type = 'button';
        button.disabled = true;
        button.dataset.batchDecision = choice;
        button.addEventListener('click', () => reviewObservationsBatch(record.id, choice));
        batch.append(button);
      });
      difficulties.append(batch);
      const updateBatchState = () => {
        const selected = [...difficulties.querySelectorAll('[data-observation-select]:checked')];
        const selectedItems = selected.map((input) => (output.observed_difficulties || []).find((item) => item.observation_id === input.value)).filter(Boolean);
        const resolutionAllowed = selectedItems.length > 0 && selectedItems.every((item) => (item.resolution_source_refs || []).length > 0);
        difficulties.querySelectorAll('[data-batch-decision]').forEach((button) => {
          button.disabled = selectedItems.length === 0 || (button.dataset.batchDecision === 'resolved' && !resolutionAllowed);
        });
      };
      selectAll.addEventListener('change', () => {
        difficulties.querySelectorAll('[data-observation-select]').forEach((input) => { input.checked = selectAll.checked; });
        updateBatchState();
      });
      difficulties.addEventListener('change', (event) => {
        if (event.target.matches('[data-observation-select]')) {
          selectAll.checked = [...difficulties.querySelectorAll('[data-observation-select]')].every((input) => input.checked);
          updateBatchState();
        }
      });
    }
    (output.observed_difficulties || []).forEach((item) => {
      const card = element('article', 'li-card');
      const review = latest.get(item.observation_id);
      const decision = review?.decision === 'confirmed' ? 'Подтверждено вручную' : review?.decision === 'rejected' ? 'Отклонено вручную' : review?.decision === 'resolved' ? 'Исправлено в пределах урока · решение преподавателя' : stateLabels[item.resolution_status] || 'Предварительный вывод AI';
      const selectLabel = element('label', 'li-select-item');
      const select = element('input');
      select.type = 'checkbox';
      select.value = item.observation_id;
      select.dataset.observationSelect = '';
      select.setAttribute('aria-label', `Выбрать наблюдение ${item.skill_id}`);
      selectLabel.append(select, document.createTextNode(' Включить в пакетную проверку'));
      card.append(selectLabel);
      card.append(element('strong', '', `${item.skill_id}${item.skill_facet_id ? ` / ${item.skill_facet_id}` : ''} · ${decision}`));
      card.append(element('p', 'li-muted', item.description));
      if (item.semantic_support_reason) card.append(element('p', 'li-ref', `Проверка основания: ${item.technical_support_status || '—'} · смысловой вывод: требует ручной проверки. ${item.semantic_support_reason}`));
      if ((item.description_variants || []).length > 1) {
        card.append(element('p', 'li-ref', `Формулировки из частей урока: ${item.description_variants.join(' · ')}`));
      }
      (item.progress_evidence || []).forEach((evidence) => {
        const evidenceCard = element('p', 'li-ref', `${eventLabels[evidence.kind] || evidence.kind || 'свидетельство'} · ${evidence.validation_status === 'supported_by_transcript' ? 'роль и порядок подтверждены' : 'содержательная поддержка не установлена'}${evidence.validation_reason ? ` · ${evidence.validation_reason}` : ''}`);
        card.append(evidenceCard);
        (evidence.source_refs || []).forEach((ref) => {
          const source = byId.get(ref);
          if (!source) return;
          const button = element('button', 'li-button', `${ref}${source.timestamp ? ` · ${source.timestamp}` : ''}: ${source.text}`);
          button.type = 'button';
          button.addEventListener('click', () => openSource(source));
          card.append(button);
        });
      });
      (item.source_refs || [item.source_ref]).forEach((ref) => {
        const source = byId.get(ref);
        if (source) card.append(element('blockquote', '', `${ref}${source.timestamp ? ` · ${source.timestamp}` : ''}${source.speaker ? ` · ${source.speaker}` : ''}: ${source.text}`));
      });
      const actions = element('div', 'li-actions');
      const choices = [
        ['confirmed', 'Подтвердить факт затруднения'],
        ...(item.resolution_source_refs?.length ? [['resolved', 'Отметить исправленным вручную']] : []),
        ['rejected', 'Отклонить наблюдение'],
      ];
      choices.forEach(([choice, label]) => {
        const button = element('button', 'li-button', label);
        button.type = 'button';
        button.addEventListener('click', () => reviewObservation(record.id, item.observation_id, choice));
        actions.append(button);
      });
      card.append(actions);
      difficulties.append(card);
    });
    result.append(difficulties);
    const learnerEvents = record.quality?.learner_events || [];
    const eventsSection = element('section', 'li-list');
    eventsSection.append(element('h3', '', 'Действия и изменения по ходу урока'));
    eventsSection.append(element('p', 'li-ref', 'Цитаты и роль участника проверены сервером. Смысловое наблюдение остаётся предварительной интерпретацией AI и требует ручной проверки.'));
    if (!learnerEvents.length) eventsSection.append(element('p', 'li-empty', 'Система не сформировала отдельные выводы о действиях ученика.'));
    learnerEvents.forEach((event) => {
      const card = element('article', 'li-card');
      const validation = event.reference_validation_status === 'valid' && event.role_order_validation_status === 'supported'
        ? 'Ссылки, роли и порядок подтверждены' : 'Роли или порядок требуют проверки';
      card.append(element('strong', '', `${event.skill_id || event.skill}${event.skill_facet_id ? ` / ${event.skill_facet_id}` : ''} · ${validation}`));
      card.append(element('p', 'li-muted', event.summary));
      const actionLabel = event.action?.label || eventLabels[event.kind] || event.kind;
      card.append(element('p', 'li-ref', `${actionLabel} · ${event.validation_reason || ''} · смысловая поддержка: ${event.semantic_support_status === 'manual_review_required' ? 'не установлена, нужна ручная проверка' : event.semantic_support_status || 'не установлена'}. ${event.semantic_support_reason || ''}`));
      const context = event.context || {};
      const teacherRefs = context.teacher_refs?.length ? ` · реплики преподавателя: ${context.teacher_refs.join(', ')}` : '';
      const permittedTools = context.permitted_tools?.length ? ` · разрешённые инструменты: ${context.permitted_tools.join(', ')}` : '';
      card.append(element('p', 'li-ref', `Контекст подсказки: ${hintStatusLabels[context.hint_status] || 'не установлен по сохранённым данным'}${teacherRefs}${permittedTools}.`));
      const supported = event.what_dialogue_supports?.length
        ? event.what_dialogue_supports.join(' ')
        : 'Ссылки подтверждают наличие цитируемых реплик; отдельный предметный вывод не установлен.';
      card.append(element('p', 'li-muted', `Что подтверждает диалог: ${supported}`));
      const notEstablished = event.what_is_not_established?.length
        ? event.what_is_not_established.join('; ')
        : 'Предметная правильность, полнота решения и устойчивое освоение не установлены.';
      card.append(element('p', 'li-ref', `Что не установлено: ${notEstablished}.`));
      card.append(element('p', 'li-ref', `Проверка события: ${reviewStatusLabels[event.review_status] || 'ожидает ручной проверки'}.`));
      (event.citations || []).forEach((citation) => {
        const source = byId.get(citation.segment_id) || citation;
        const button = element('button', 'li-button li-event-citation', `${citation.segment_id} · ${citation.speaker_role || 'unknown'}${citation.timestamp ? ` · ${citation.timestamp}` : ''}: ${citation.quote}`);
        Object.assign(button.style, {display: 'block', width: '100%', maxWidth: '100%', marginTop: '8px',
          textAlign: 'left', whiteSpace: 'normal', overflowWrap: 'anywhere'});
        button.type = 'button';
        button.addEventListener('click', () => openSource(source));
        card.append(button);
      });
      eventsSection.append(card);
    });
    result.append(eventsSection);
    const knowledge = record.quality?.knowledge_retrieval;
    if (knowledge) {
      const knowledgeSection = element('details', 'li-list');
      knowledgeSection.append(element('summary', '', 'Материалы базы знаний'));
      knowledgeSection.append(element('p', 'li-ref', `${knowledge.status || 'Статус не указан'} · справочный контекст не является доказательством реплики или навыка ученика; отметка source_checked не равна экспертному утверждению.`));
      const details = element('pre', 'li-muted', JSON.stringify(knowledge.items ?? [], null, 2));
      knowledgeSection.append(details);
      result.append(knowledgeSection);
    }
    const plan = record.quality?.lesson_synthesis;
    if (plan) {
      const planSection = element('section', 'li-list');
      const decision = plan.decision === 'propose_change' ? 'Предложение изменить акценты' : plan.decision === 'no_change' ? 'Оснований менять акценты не найдено' : 'Данных недостаточно для изменения акцентов';
      planSection.append(element('h3', '', `Проект следующего занятия · ${plan.total_minutes} минут`));
      planSection.append(element('p', 'li-lead', decision));
      planSection.append(element('p', 'li-muted', plan.reason));
      planSection.append(element('p', 'li-ref', `${plan.baseline_plan_available ? 'Исходный план учтён.' : 'Исходный план не был передан; сравнение до и после невозможно.'} Это черновое предложение для ручного решения; курс и расписание не изменены.${plan.assigned_practice_available ? ' Назначенная практика учтена.' : ' Назначенная практика не передавалась.'}`));
      if (plan.plan_method === 'deterministic_evidence_priority.v1' || plan.plan_method === 'deterministic_evidence_priority.v2') {
        planSection.append(element('p', 'li-ref', 'Порядок тем рассчитан по состоянию свидетельств, повторным затруднениям и необходимости помощи. Этот расчёт не является экспертным подтверждением освоения.'));
        const priorities = element('div', 'li-list');
        (plan.priority_items || []).slice(0, 4).forEach((item, index) => {
          const row = element('article', 'li-card');
          row.append(element('strong', '', `${index + 1}. ${item.skill_id}${item.skill_facet_id ? ` / ${item.skill_facet_id}` : ''} · ${stateLabels[item.resolution_status] || item.resolution_status || 'недостаточно данных'}`));
          const reasons = item.reasons || {};
          row.append(element('p', 'li-ref', `Основание приоритета: повторные затруднения — ${reasons.repeated_difficulty_count ?? 0}; ответы после помощи — ${reasons.helped_demonstration_count ?? 0}; предпосылка другой найденной темы — ${reasons.prerequisite_for_retrieved_skill ? 'да' : 'нет'}.`));
          priorities.append(row);
        });
        if ((plan.priority_items || []).length) planSection.append(priorities);
      }
      (plan.stages || []).forEach((stage, index) => {
        const card = element('article', 'li-card');
        card.append(element('strong', '', `${index + 1}. ${stage.title} · ${stage.minutes} мин.`));
        card.append(element('p', 'li-muted', stage.reason));
        card.append(element('p', 'li-ref', `На занятии проверить: ${stage.expected_check}`));
        (stage.citations || []).forEach((citation) => {
          const source = byId.get(citation.segment_id) || citation;
          const button = element('button', 'li-button', `${citation.segment_id}${citation.timestamp ? ` · ${citation.timestamp}` : ''}: ${citation.quote}`);
          button.type = 'button';
          button.addEventListener('click', () => openSource(source));
          card.append(button);
        });
        planSection.append(card);
      });
      if ((plan.limitations || []).length) planSection.append(element('p', 'li-note', plan.limitations.join(' ')));
      result.append(planSection);
    }
    if ((output.unsubstantiated_observations || []).length) {
      const unsupported = element('section', 'li-list');
      unsupported.append(element('h3', '', 'Не подтверждено прямой репликой ученика'));
      output.unsubstantiated_observations.forEach((item) => {
        const card = element('article', 'li-card');
        card.append(element('strong', '', `${item.skill_id} · не включено в наблюдения`));
        card.append(element('p', 'li-muted', item.description));
        card.append(element('p', 'li-ref', item.reason));
        (item.source_refs || []).forEach((ref) => {
          const source = byId.get(ref);
          if (source) card.append(element('blockquote', '', `${ref}: ${source.text}`));
        });
        unsupported.append(card);
      });
      result.append(unsupported);
    }
    result.append(element('p', 'li-note', (output.limitations || []).join(' ')));
  }

  async function reviewObservation(recordId, observationId, decision) {
    const url = root.dataset.reviewBase.replace('/0/', `/${recordId}/`).replace('__observation__', encodeURIComponent(observationId));
    status.className = 'li-status';
    status.textContent = 'Сохраняем ручное решение…';
    try {
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf},
        body: JSON.stringify({decision})});
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось сохранить решение.');
      renderRecord(body.record);
      status.textContent = decision === 'confirmed' ? 'Наблюдение подтверждено и добавлено в Analytics как качественное свидетельство без числового балла.' : decision === 'resolved' ? 'Исправление подтверждено и сохранено как качественное свидетельство без статуса текущего затруднения.' : 'Наблюдение отклонено и не попадёт в Analytics.';
      status.className = 'li-status li-good';
    } catch (error) {
      status.textContent = error.message || 'Не удалось сохранить решение.';
      status.className = 'li-status li-error';
    }
  }

  async function reviewObservationsBatch(recordId, decision) {
    const selected = [...result.querySelectorAll('[data-observation-select]:checked')].map((input) => input.value);
    if (!selected.length) return;
    status.className = 'li-status';
    status.textContent = `Сохраняем пакетное решение для ${selected.length} наблюдений…`;
    const url = root.dataset.batchReviewUrl.replace('/0', `/${recordId}`);
    try {
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf},
        body: JSON.stringify({observation_ids: selected, decision})});
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось сохранить пакетное решение.');
      renderRecord(body.record);
      status.textContent = decision === 'confirmed' ? `Подтверждено наблюдений: ${selected.length}. Они добавлены в Analytics без числовой оценки.` : decision === 'resolved' ? `Подтверждено исправлений: ${selected.length}. Они сохранены как качественные свидетельства.` : `Отклонено наблюдений: ${selected.length}.`;
      status.className = 'li-status li-good';
    } catch (error) {
      status.textContent = error.message || 'Не удалось сохранить пакетное решение.';
      status.className = 'li-status li-error';
    }
  }

  sampleSelect.addEventListener('change', () => {
    const sample = samples.find((item) => item.id === sampleSelect.value);
    if (!sample) { syntheticConfirm.checked = false; return; }
    lessonId.value = platformLesson.value ? `boostudy-lesson:${platformLesson.value}` : sample.id;
    lessonVersion.value = '1';
    transcript.value = sample.transcript;
    syntheticConfirm.checked = true;
  });
  platformLesson.addEventListener('change', () => {
    if (platformLesson.value) {
      lessonId.value = `boostudy-lesson:${platformLesson.value}`;
      lessonId.readOnly = true;
      lessonVersion.value = '1';
      status.textContent = `Транскрипт будет связан с уроком BooStudy и профилем ${platformLesson.selectedOptions[0]?.textContent || 'демо-ученика'}. Подтвердите синтетический текст перед запуском.`;
      status.className = 'li-status';
      return;
    }
    lessonId.readOnly = false;
    if (lessonId.value.startsWith('boostudy-lesson:')) lessonId.value = 'synthetic-lesson';
    status.textContent = 'Связь с платформенной записью снята.';
    status.className = 'li-status';
  });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt') || file.size > 131072) {
      status.textContent = 'Выберите текстовый .txt файл размером не более 128 КБ.';
      status.className = 'li-status li-error';
      fileInput.value = '';
      return;
    }
    transcript.value = await file.text();
    status.textContent = 'Текст загружен локально в поле ввода. Файл не отправлялся автоматически.';
    status.className = 'li-status';
  });
  runButton.addEventListener('click', async () => {
    const payload = {lesson_id: lessonId.value.trim(), lesson_version: Number(lessonVersion.value),
      planned_session_minutes: Number(sessionMinutes?.value || 60),
      transcript: transcript.value, synthetic_confirmed: syntheticConfirm.checked};
    if (platformLesson.value) payload.platform_lesson_id = platformLesson.value;
    else payload.subject_id = 'synthetic-lesson-learner';
    runButton.disabled = true;
    result.hidden = true;
    status.className = 'li-status';
    status.textContent = 'Запрос поставлен в последовательную очередь GigaChat…';
    try {
      const response = await fetch(root.dataset.analyzeUrl, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf}, body: JSON.stringify(payload)});
      const body = await response.json();
      if (body.record) renderRecord(body.record);
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось обработать транскрипт.');
      status.textContent = 'Анализ сохранён. Выводы остаются предварительными до ручного подтверждения.';
      status.className = 'li-status li-good';
    } catch (error) {
      status.textContent = error.message || 'Не удалось обработать транскрипт.';
      status.className = 'li-status li-error';
    } finally {
      runButton.disabled = false;
    }
  });
  document.querySelectorAll('[data-load-record]').forEach((button) => button.addEventListener('click', async () => {
    const url = root.dataset.detailBase.replace('/0', `/${button.dataset.loadRecord}`);
    try {
      const response = await fetch(url);
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error || 'Не удалось загрузить анализ.');
      renderRecord(body.record);
      status.textContent = 'Загружена сохранённая версия анализа.';
      result.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      status.textContent = error.message || 'Не удалось загрузить анализ.';
    }
  }));
})();
