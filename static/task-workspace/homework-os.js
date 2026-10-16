(() => {
  const ws = window.TASK_WORKSPACE;
  if (!ws || ws.context_type !== 'submission_task') return;
  const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const params = new URLSearchParams({
    context_type: ws.context_type,
    context_id: String(ws.context_id),
    assignment_task_id: String(ws.assignment_task_id),
  });
  const notes = document.getElementById('tw-notes');
  const dialog = document.getElementById('hw-os-transfer');
  const source = document.getElementById('hw-os-transfer-source');
  const status = document.getElementById('hw-os-transfer-status');
  const confirm = document.getElementById('hw-os-transfer-confirm');
  let noteTimer;

  async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) throw new Error(data.error || 'Не удалось выполнить действие');
    return data;
  }

  if (notes) {
    if (!ws.can_edit) notes.readOnly = true;
    fetch(`/task-workspace/api/notes?${params}`, { credentials: 'same-origin' })
      .then(readJson)
      .then((data) => {
        if (document.activeElement !== notes) notes.value = data.notes || '';
      })
      .catch(() => {});
    if (ws.can_edit) notes.addEventListener('input', () => {
      clearTimeout(noteTimer);
      noteTimer = setTimeout(async () => {
        try {
          await readJson(await fetch('/task-workspace/api/notes', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
            body: JSON.stringify({ ...Object.fromEntries(params), notes: notes.value }),
          }));
        } catch (error) {
          window.BooNotify?.error?.(error.message || 'Не удалось сохранить заметки');
        }
      }, 650);
    });
  }

  async function loadSources() {
    const data = await readJson(await fetch(`/task-workspace/api/bridge?${params}`, { credentials: 'same-origin' }));
    const lessonLink = document.getElementById('hw-os-lesson-link');
    const sendLesson = document.getElementById('hw-os-send-lesson');
    if (lessonLink && data.lesson) {
      lessonLink.href = data.lesson.url;
      lessonLink.hidden = false;
      if (sendLesson) sendLesson.hidden = false;
    }
    if (!source) return;
    source.replaceChildren(new Option('Выберите пространство', ''));
    const addGroup = (label, items, type) => {
      if (!items.length) return;
      const group = document.createElement('optgroup');
      group.label = label;
      for (const item of items) group.append(new Option(item.title, `${type}:${item.id}`));
      source.append(group);
    };
    addGroup('Эта работа', (data.assignment_tasks || []).map((item) => ({ id: item.assignment_task_id, title: `Задание ${item.position}` })), 'assignment_task');
    if (data.lesson) {
      if (data.lesson_os_code) addGroup('OS урока', [{ id: data.lesson.id, title: 'Код редактора урока и заметки' }], 'lesson_os');
      addGroup('Урок', [{ id: data.lesson.id, title: `Заметки: ${data.lesson.title}` }], 'lesson_notes');
      addGroup('Задания урока', data.lesson_tasks || [], 'lesson_task');
    }
  }

  loadSources().catch(() => {});
  dialog?.querySelector('.hw-os-dialog-close')?.addEventListener('click', () => dialog.close());
  document.getElementById('hw-os-send-lesson')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      if (noteTimer) clearTimeout(noteTimer);
      const saved = await window.BooTaskWorkspace?.save?.();
      if (saved === false) throw new Error('Сначала сохраните задание');
      const data = await readJson(await fetch('/task-workspace/api/bridge', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
        body: JSON.stringify({ ...Object.fromEntries(params), direction: 'to_lesson' }),
      }));
      window.BooNotify?.success?.(data.message);
    } catch (error) {
      window.BooNotify?.error?.(error.message || 'Не удалось сохранить в урок');
    } finally { button.disabled = false; }
  });
  document.getElementById('hw-os-transfer-open')?.addEventListener('click', async () => {
    dialog?.showModal();
    try { await loadSources(); }
    catch (error) { if (status) status.textContent = error.message; }
  });
  confirm?.addEventListener('click', async () => {
    if (!source?.value) { source?.focus(); return; }
    const [source_type, source_id] = source.value.split(':');
    confirm.disabled = true;
    if (status) status.textContent = 'Копируем…';
    try {
      const data = await readJson(await fetch('/task-workspace/api/bridge', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
        body: JSON.stringify({ ...Object.fromEntries(params), source_type, source_id: Number(source_id) }),
      }));
      if (status) status.textContent = data.message;
      location.reload();
    } catch (error) {
      if (status) status.textContent = error.message;
      confirm.disabled = false;
    }
  });
})();
