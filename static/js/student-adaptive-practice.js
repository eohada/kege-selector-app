(() => {
  const root = document.querySelector('#adaptive-practice');
  if (!root) return;

  const baseUrl = root.dataset.apiUrl;
  const csrfToken = root.dataset.csrfToken;
  const setup = root.querySelector('[data-practice-setup]');
  const sessionPanel = root.querySelector('[data-practice-session]');
  const errorBox = root.querySelector('[data-practice-error]');
  const summaryBox = root.querySelector('[data-practice-summary]');
  const skillSelect = root.querySelector('[data-practice-skill]');
  const modeSelect = root.querySelector('[data-practice-mode]');
  const startButton = root.querySelector('[data-practice-start]');
  const answerForm = root.querySelector('[data-practice-answer-form]');
  const answerControl = root.querySelector('[data-practice-answer-control]');
  const feedbackBox = root.querySelector('[data-practice-feedback]');
  const nextWrap = root.querySelector('[data-practice-next-wrap]');
  const historyList = root.querySelector('[data-practice-history]');
  const historyEmpty = root.querySelector('[data-practice-history-empty]');

  let session = null;
  let activeAttemptKey = makeRequestKey();
  let activeStartKey = makeRequestKey();

  function makeRequestKey() {
    return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function sessionUrl(suffix = '') {
    return `${baseUrl}/${encodeURIComponent(session.session_id)}${suffix}`;
  }

  async function api(url, method, body) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = csrfToken;
    }
    const response = await fetch(url, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error('Сервер вернул неожиданный ответ. Обновите страницу и проверьте историю практики.');
    }
    if (!response.ok || !result.ok) {
      throw new Error(result.error || 'Не удалось выполнить действие.');
    }
    return result;
  }

  function showError(message) {
    errorBox.textContent = message || '';
    errorBox.hidden = !message;
  }

  function updateModeHelp() {
    const help = root.querySelector('[data-practice-mode-help]');
    if (!help) return;
    const descriptions = {
      topic: 'Начнём с выбранной темы. Проверка показывает только результат этого варианта.',
      diagnostic: 'Это короткая стартовая проверка, а не диагноз уровня или заключение об освоении темы.',
      continue: 'Подберём следующий вариант по выбранной теме с учётом доступных сохранённых результатов.',
    };
    help.textContent = descriptions[modeSelect.value] || descriptions.topic;
  }

  function renderCompletedSummary(completedSession) {
    summaryBox.replaceChildren();
    const heading = document.createElement('strong');
    heading.textContent = 'Тренировка завершена';
    const count = Number(completedSession.attempt_count || 0);
    const result = document.createElement('p');
    result.textContent = count
      ? `Выполнено упражнений: ${count}. Ответы сохранены в истории свободной практики ниже.`
      : 'В этой сессии не было отправленных ответов. Можно выбрать тему и начать снова.';
    summaryBox.append(heading, result);
    if (completedSession.last_feedback?.verification_status === 'verified') {
      const latest = document.createElement('p');
      latest.textContent = completedSession.last_feedback.is_correct
        ? 'Последний ответ совпал с эталоном на этом варианте.'
        : 'Последний ответ не совпал с эталоном на этом варианте.';
      summaryBox.append(latest);
    }
    summaryBox.hidden = false;
  }

  function setBusy(button, busy, busyText) {
    if (!button) return;
    if (busy) {
      button.dataset.previousText = button.textContent;
      button.disabled = true;
      button.textContent = busyText;
    } else {
      button.disabled = false;
      if (button.dataset.previousText) button.textContent = button.dataset.previousText;
      delete button.dataset.previousText;
    }
  }

  function renderAnswerControl(exercise) {
    answerControl.replaceChildren();
    const type = exercise.answer_type;
    if (type === 'single_choice' || type === 'multi_select') {
      (exercise.options || []).forEach((option, index) => {
        const label = document.createElement('label');
        label.className = 'adaptive-practice__choice';
        const input = document.createElement('input');
        input.type = type === 'single_choice' ? 'radio' : 'checkbox';
        input.name = 'practice-answer';
        input.value = String(option.value);
        input.required = type === 'single_choice' && index === 0;
        const text = document.createElement('span');
        text.textContent = option.label || String(option.value);
        label.append(input, text);
        answerControl.append(label);
      });
      return;
    }
    const input = document.createElement('input');
    input.type = type === 'numeric' ? 'number' : 'text';
    input.name = 'practice-answer';
    input.autocomplete = 'off';
    input.required = true;
    if (type === 'numeric') input.step = 'any';
    if (type === 'short_text') input.maxLength = 256;
    input.setAttribute('aria-label', type === 'numeric' ? 'Числовой ответ' : 'Краткий ответ');
    answerControl.append(input);
  }

  function collectAnswer() {
    const exercise = session?.current_exercise;
    if (!exercise) return null;
    const selected = [...answerControl.querySelectorAll('input:checked')].map((input) => input.value);
    if (exercise.answer_type === 'single_choice') return selected[0] || '';
    if (exercise.answer_type === 'multi_select') return selected;
    return answerControl.querySelector('input')?.value ?? '';
  }

  function renderFeedback(feedback) {
    feedbackBox.replaceChildren();
    if (!feedback) return;
    const heading = document.createElement('strong');
    if (feedback.verification_status !== 'verified') {
      heading.textContent = 'Ответ не удалось надёжно проверить.';
      feedbackBox.append(heading, document.createTextNode(` ${feedback.reason || ''}`));
      return;
    }
    heading.textContent = feedback.is_correct ? 'На этом варианте ответ верный.' : 'На этом варианте ответ не совпал с эталоном.';
    feedbackBox.append(heading);
    if (feedback.correct_answer !== null && feedback.correct_answer !== undefined) {
      const answer = document.createElement('p');
      answer.textContent = `Эталон: ${Array.isArray(feedback.correct_answer) ? feedback.correct_answer.join(', ') : feedback.correct_answer}`;
      feedbackBox.append(answer);
    }
    if (feedback.explanation) {
      const explanation = document.createElement('p');
      explanation.textContent = feedback.explanation;
      feedbackBox.append(explanation);
    }
  }

  function addHistoryEntry(exercise, feedback) {
    if (!historyList) return;
    if (historyEmpty) historyEmpty.hidden = true;
    historyList.hidden = false;
    const row = document.createElement('li');
    row.className = 'student-practice-item';
    const copy = document.createElement('div');
    copy.className = 'student-practice-copy';
    const title = document.createElement('span');
    title.className = 'student-practice-eyebrow';
    title.textContent = exercise.title || 'Короткая практика';
    const result = document.createElement('p');
    result.textContent = feedback.verification_status === 'verified'
      ? (feedback.is_correct ? 'Ответ подтверждён на этом варианте' : 'Ответ не совпал с эталоном')
      : 'Результат не удалось проверить';
    copy.append(title, result);
    const time = document.createElement('time');
    time.dateTime = new Date().toISOString();
    time.textContent = 'сейчас';
    row.append(copy, time);
    historyList.prepend(row);
  }

  function render(nextSession) {
    session = nextSession;
    if (!session || session.status === 'completed') {
      setup.hidden = false;
      sessionPanel.hidden = true;
      summaryBox.hidden = true;
      if (session?.status === 'completed') {
        showError('');
        renderCompletedSummary(session);
      }
      return;
    }

    setup.hidden = true;
    sessionPanel.hidden = false;
    const exercise = session.current_exercise;
    const title = root.querySelector('[data-practice-exercise-title]');
    const prompt = root.querySelector('[data-practice-prompt]');
    const progress = root.querySelector('[data-practice-progress]');
    const decision = root.querySelector('[data-practice-decision]');
    progress.textContent = `Упражнение ${Math.max(1, Number(session.attempt_count || 0) + (session.awaiting_next ? 0 : 1))}`;
    decision.textContent = session.decision?.reason || '';

    if (!exercise) {
      title.textContent = 'Пока нет нового варианта';
      prompt.textContent = session.decision?.reason || 'Для этой сессии больше нет новых упражнений.';
      answerForm.hidden = true;
      nextWrap.hidden = true;
      feedbackBox.textContent = 'Сессию можно завершить или начать новую по другой теме.';
      return;
    }

    title.textContent = exercise.title || 'Короткое упражнение';
    prompt.textContent = exercise.prompt || '';
    answerForm.hidden = Boolean(session.awaiting_next);
    nextWrap.hidden = !session.awaiting_next;
    renderAnswerControl(exercise);
    renderFeedback(session.last_feedback);
    if (session.last_hint && !session.awaiting_next) {
      const hint = document.createElement('p');
      hint.textContent = `Подсказка: ${session.last_hint}`;
      feedbackBox.append(hint);
    }
  }

  startButton.addEventListener('click', async () => {
    showError('');
    summaryBox.hidden = true;
    setBusy(startButton, true, 'Готовим упражнение…');
    try {
      const result = await api(baseUrl, 'POST', {
        skill_id: skillSelect.value,
        mode: modeSelect.value,
        idempotency_key: activeStartKey,
        course_id: root.dataset.courseId ? Number(root.dataset.courseId) : null,
        lesson_id: root.dataset.lessonId ? Number(root.dataset.lessonId) : null,
      });
      activeStartKey = makeRequestKey();
      activeAttemptKey = makeRequestKey();
      render(result.session);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(startButton, false);
    }
  });

  modeSelect.addEventListener('change', updateModeHelp);
  updateModeHelp();

  answerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!session?.current_exercise || session.awaiting_next) return;
    const submitButton = root.querySelector('[data-practice-submit]');
    setBusy(submitButton, true, 'Проверяем и сохраняем…');
    showError('');
    try {
      const result = await api(sessionUrl('/answer'), 'POST', {
        answer: collectAnswer(),
        idempotency_key: activeAttemptKey,
      });
      session.awaiting_next = true;
      session.attempt_count = Number(session.attempt_count || 0) + 1;
      session.last_feedback = result.feedback;
      session.last_hint = null;
      addHistoryEntry(session.current_exercise, result.feedback);
      activeAttemptKey = makeRequestKey();
      render(session);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(submitButton, false);
    }
  });

  root.querySelector('[data-practice-hint]').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, 'Ищем подсказку…');
    showError('');
    try {
      const result = await api(sessionUrl('/hint'), 'POST', {});
      session.last_hint = result.hint;
      const hint = document.createElement('p');
      hint.textContent = `Подсказка: ${result.hint}`;
      feedbackBox.replaceChildren(hint);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  root.querySelector('[data-practice-next]').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, 'Подбираем следующий шаг…');
    showError('');
    try {
      const result = await api(sessionUrl('/next'), 'POST', {});
      activeAttemptKey = makeRequestKey();
      render(result.session);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  root.querySelector('[data-practice-finish]').addEventListener('click', async (event) => {
    if (!session?.session_id) return;
    const button = event.currentTarget;
    setBusy(button, true, 'Завершаем…');
    showError('');
    try {
      const result = await api(sessionUrl('/finish'), 'POST', {});
      render(result.session);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(button, false);
    }
  });

  let initialSession = null;
  try {
    initialSession = JSON.parse(root.dataset.initialSession || 'null');
  } catch {
    showError('Не удалось восстановить сохранённую сессию. Обновите страницу; история ответов сохранена.');
  }
  if (initialSession) render(initialSession);
})();
