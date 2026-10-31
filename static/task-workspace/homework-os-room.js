(() => {
  const config = JSON.parse(document.getElementById('trainer-os-config')?.textContent || '{}');
  if (!config.homework_mode && !config.review_mode) return;
  const isHomework = Boolean((config.homework_mode || config.review_mode) && config.homework_workspace);
  const ws = isHomework ? config.homework_workspace : null;
  window.boostudyTaskWorkspace = ws;
  const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const scope = ws ? {
    context_type: ws.context_type,
    context_id: ws.context_id,
    assignment_task_id: ws.assignment_task_id,
  } : {};
  const query = ws ? new URLSearchParams(scope) : new URLSearchParams();
  const notify = (message, isError = false) => {
    if (isError) window.BooNotify?.error?.(message);
    else window.BooNotify?.success?.(message);
  };
  const readJson = async (responsePromise) => {
    const response = await responsePromise;
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      const err = new Error(data.message || data.error || 'Не удалось выполнить действие');
      err.status = response.status;
      err.data = data;
      throw err;
    }
    return data;
  };
  const post = (url, data) => readJson(fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
    body: JSON.stringify(data),
  }));
  const codeEditor = document.getElementById('code-editor-textarea');
  const notesEditor = document.getElementById('notes-textarea');
  const answerFrame = document.getElementById('homework-answer-frame');
  let codeTimer = 0;
  let notesTimer = 0;
  let codeSave = Promise.resolve();
  let notesSave = Promise.resolve();
  let codeTouched = false;
  let notesTouched = false;
  const taskCodeStore = {};
  const taskAnswerStore = {};
  const dirtyAnswers = {};
  window.taskAnswerStore = taskAnswerStore;
  window.dirtyAnswers = dirtyAnswers;

  window.onEmbeddedAnswerChange = function(taskId, val) {
    if (taskId !== undefined && taskId !== null) {
      taskAnswerStore[taskId] = val;
      dirtyAnswers[taskId] = val;
    }
  };

  function setHwSaveStatus(status, text) {
    const dot = document.getElementById('hw-code-save-dot');
    const label = document.getElementById('hw-code-save-text');
    if (label && text) label.textContent = text;
    if (dot) {
      if (status === 'saving') {
        dot.className = 'w-2 h-2 rounded-full bg-amber-500 animate-pulse inline-block';
      } else if (status === 'saved') {
        dot.className = 'w-2 h-2 rounded-full bg-emerald-500 inline-block';
      } else if (status === 'error' || status === 'conflict') {
        dot.className = 'w-2 h-2 rounded-full bg-rose-500 inline-block';
      } else if (status === 'offline') {
        dot.className = 'w-2 h-2 rounded-full bg-orange-500 inline-block';
      } else {
        dot.className = 'w-2 h-2 rounded-full bg-slate-400 inline-block';
      }
    }
    if (typeof setVfsSaveStatus === 'function') setVfsSaveStatus(status, text);
  }
  window.setHwSaveStatus = setHwSaveStatus;

  function syncAnswerCode() {
    const inner = answerFrame?.contentWindow;
    const field = inner?.document?.getElementById('tw-code');
    const mainPyCode = (typeof window.getEditorMainPyCode === 'function')
      ? window.getEditorMainPyCode()
      : (codeEditor?.value || '');
    if (field && field.value !== mainPyCode) {
      field.value = mainPyCode;
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (inner?.TASK_WORKSPACE) inner.TASK_WORKSPACE.code = mainPyCode;
  }

  function flushCode(explicitTaskId) {
    if (!isHomework || !ws || !ws.can_edit) return codeSave;
    clearTimeout(codeTimer);
    codeTimer = 0;
    const targetTaskId = explicitTaskId || ws.assignment_task_id;
    if (!targetTaskId) return codeSave;

    const isActive = (String(ws.assignment_task_id) === String(targetTaskId));
    const code = isActive
      ? ((typeof window.getEditorMainPyCode === 'function') ? window.getEditorMainPyCode() : (codeEditor?.value || ''))
      : (taskCodeStore[targetTaskId]?.code ?? '');

    if (isActive) {
      syncAnswerCode();
    }

    const reqRevision = taskCodeStore[targetTaskId]?.revision || (isActive ? currentRevision : 1) || 1;
    const payload = {
      ...scope,
      assignment_task_id: targetTaskId,
      code,
      files: { 'main.py': code },
      open_tabs: ['main.py'],
      active_file: 'main.py',
      revision: reqRevision,
    };

    setHwSaveStatus('saving', 'Сохранение...');

    const savePromise = post('/task-workspace/api/code', payload)
      .then((data) => {
        const rev = Number(data?.revision || reqRevision || 1);
        if (taskCodeStore[targetTaskId]) {
          taskCodeStore[targetTaskId].revision = Math.max(taskCodeStore[targetTaskId].revision || 1, rev);
          if (taskCodeStore[targetTaskId].code === code) {
            taskCodeStore[targetTaskId].dirty = false;
          }
          taskCodeStore[targetTaskId].lastSavedCode = code;
          taskCodeStore[targetTaskId].hasSavedCode = true;
        }
        if (String(ws.assignment_task_id) === String(targetTaskId)) {
          codeTouched = false;
          currentRevision = Math.max(currentRevision, rev);
          setHwSaveStatus('saved', 'Сохранено');
          const badge = document.getElementById('hw-answer-code-status');
          if (badge) {
            badge.textContent = `Код сохранён автоматически (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })})`;
          }
        }
        if (typeof clearVfsEmergencyBackup === 'function') clearVfsEmergencyBackup();
        return data;
      })
      .catch(async (error) => {
        if (error && error.status === 409) {
          const match = error.message ? error.message.match(/current\s+(\d+)/) : null;
          const serverRev = Number(
            error.data?.current_revision ||
            error.data?.revision ||
            (match ? match[1] : null) ||
            (reqRevision + 1)
          );
          console.warn(`[Autosave] 409 stale revision for task ${targetTaskId}. Server revision=${serverRev}, requested=${reqRevision}.`);
          if (taskCodeStore[targetTaskId]) {
            taskCodeStore[targetTaskId].revision = Math.max(taskCodeStore[targetTaskId].revision || 1, serverRev);
          }
          if (String(ws.assignment_task_id) === String(targetTaskId)) {
            currentRevision = Math.max(currentRevision, serverRev);
          }
          payload.revision = serverRev;
          try {
            const retryData = await post('/task-workspace/api/code', payload);
            const retryRev = Number(retryData?.revision || serverRev || 1);
            if (taskCodeStore[targetTaskId]) {
              taskCodeStore[targetTaskId].revision = Math.max(taskCodeStore[targetTaskId].revision || 1, retryRev);
              if (taskCodeStore[targetTaskId].code === code) {
                taskCodeStore[targetTaskId].dirty = false;
              }
              taskCodeStore[targetTaskId].lastSavedCode = code;
              taskCodeStore[targetTaskId].hasSavedCode = true;
            }
            if (String(ws.assignment_task_id) === String(targetTaskId)) {
              codeTouched = false;
              currentRevision = Math.max(currentRevision, retryRev);
              setHwSaveStatus('saved', 'Сохранено');
            }
            return retryData;
          } catch (retryErr) {
            if (retryErr && retryErr.status === 409) {
              const retryMatch = retryErr.message ? retryErr.message.match(/current\s+(\d+)/) : null;
              const secondRev = Number(
                retryErr.data?.current_revision ||
                retryErr.data?.revision ||
                (retryMatch ? retryMatch[1] : null) ||
                (serverRev + 1)
              );
              payload.revision = secondRev;
              const secondRetry = await post('/task-workspace/api/code', payload);
              const secondResRev = Number(secondRetry?.revision || secondRev || 1);
              if (taskCodeStore[targetTaskId]) {
                taskCodeStore[targetTaskId].revision = Math.max(taskCodeStore[targetTaskId].revision || 1, secondResRev);
                if (taskCodeStore[targetTaskId].code === code) {
                  taskCodeStore[targetTaskId].dirty = false;
                }
                taskCodeStore[targetTaskId].lastSavedCode = code;
                taskCodeStore[targetTaskId].hasSavedCode = true;
              }
              if (String(ws.assignment_task_id) === String(targetTaskId)) {
                codeTouched = false;
                currentRevision = Math.max(currentRevision, secondResRev);
                setHwSaveStatus('saved', 'Сохранено');
              }
              return secondRetry;
            }
            console.error('[Autosave] Retry failed:', retryErr);
            setHwSaveStatus('error', 'Ошибка сохранения');
            throw retryErr;
          }
        }
        setHwSaveStatus('error', 'Ошибка сохранения');
        notify(error.message || 'Код не сохранён', true);
        throw error;
      });

    codeSave = codeSave.catch(() => {}).then(() => savePromise);
    return codeSave;
  }
  window.flushHomeworkCode = flushCode;

  function bindCodeAnswerButtons() {
    document.getElementById('hw-save-code-as-answer-btn')?.addEventListener('click', async () => {
      const btn = document.getElementById('hw-save-code-as-answer-btn');
      const badge = document.getElementById('hw-answer-code-status');
      if (btn) btn.disabled = true;
      try {
        await flushCode();
        if (badge) badge.textContent = `Код сохранён в ответ (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })})`;
        notify('Код успешно сохранён как ответ на задание!');
      } catch (err) {
        notify(err.message || 'Не удалось сохранить код', true);
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function flushNotes() {
    if (!ws.can_edit) return notesSave;
    clearTimeout(notesTimer);
    notesTimer = 0;
    const targetTaskId = ws.assignment_task_id;
    const notes = notesEditor?.value || '';
    const savePromise = post('/task-workspace/api/notes', { ...scope, assignment_task_id: targetTaskId, notes })
      .then((data) => {
        if (String(ws.assignment_task_id) === String(targetTaskId)) {
          notesTouched = false;
          const status = document.getElementById('notes-status-text');
          if (status) status.textContent = 'Сохранено';
        }
        return data;
      })
      .catch((error) => {
        notify(error.message || 'Заметки не сохранены', true);
        throw error;
      });
    notesSave = notesSave.catch(() => {}).then(() => savePromise);
    return notesSave;
  }

  async function flushAllDirtyTasks() {
    const promises = [];
    for (const [taskIdStr, entry] of Object.entries(taskCodeStore)) {
      const taskId = Number(taskIdStr);
      if (entry.dirty) {
        promises.push(flushCode(taskId));
      }
    }
    if (codeTimer || codeTouched) {
      promises.push(flushCode(ws.assignment_task_id));
    }
    if (promises.length > 0) {
      await Promise.all(promises);
    }
  }

  async function saveAll() {
    if (!ws || (!ws.can_edit && !ws.can_review)) return;
    try {
      const promises = [];
      if (ws.can_edit) {
        promises.push(flushAllDirtyTasks());
        if (notesTimer || notesTouched) promises.push(flushNotes());
        else if (notesSave) promises.push(notesSave);
        const afSave = answerFrame?.contentWindow?.BooTaskWorkspace?.save?.();
        if (afSave && typeof afSave.then === 'function') promises.push(afSave);
      }
      if (typeof window.BooCanvasOverlay?.save === 'function') {
        promises.push(window.BooCanvasOverlay.save());
      }
      if (promises.length > 0) {
        await Promise.all(promises);
      }
    } catch (err) {
      console.warn('saveAll warning:', err);
      throw err;
    }
  }

  async function loadSources() {
    const data = await readJson(fetch(`/task-workspace/api/bridge?${query}`, { credentials: 'same-origin' }));
    sources = data;
    const lessonLink = document.getElementById('hw-os-lesson-link');
    if (lessonLink && data.lesson) {
      lessonLink.href = data.lesson.url;
      lessonLink.hidden = false;
      document.getElementById('hw-os-send-lesson')?.removeAttribute('hidden');
    }
    const select = document.getElementById('hw-os-transfer-source');
    if (!select) return;
    select.replaceChildren(new Option('Выберите пространство', ''));
    const append = (label, items, type, makeTitle) => {
      if (!items.length) return;
      const group = document.createElement('optgroup');
      group.label = label;
      for (const item of items) group.append(new Option(makeTitle(item), `${type}:${item.id || item.assignment_task_id}`));
      select.append(group);
    };
    append('Задания этой работы', data.assignment_tasks || [], 'assignment_task', (item) => `Задание ${item.position}`);
    if (data.lesson) {
      if (data.lesson_os_code) append('OS урока', [{ id: data.lesson.id }], 'lesson_os', () => 'Редактор и заметки урока');
      append('Конспект урока', [{ id: data.lesson.id, title: data.lesson.title }], 'lesson_notes', (item) => item.title);
      append('Задания урока', data.lesson_tasks || [], 'lesson_task', (item) => item.title);
    }
  }

  let reloadFiles = null;

  function initFiles() {
    const list = document.getElementById('homework-files-list');
    const editor = document.getElementById('homework-file-editor');
    const content = document.getElementById('homework-file-content');
    const status = document.getElementById('homework-file-status');
    let selectedFile = null;
    const setStatus = (message) => { if (status) status.textContent = message; };

    const getFileScope = () => ({
      task_id: ws.task_id,
      context_type: `submission_task_${ws.assignment_task_id}`,
      context_id: ws.context_id,
    });

    const openFile = async (item) => {
      try {
        const data = await readJson(fetch(`/workspace/${item.id}/content`, { credentials: 'same-origin' }));
        selectedFile = item.id;
        editor.hidden = false;
        document.getElementById('homework-file-name').textContent = item.current_filename || item.original_filename || 'Файл';
        const isText = data.type === 'text';
        content.value = isText ? (data.content || '') : 'Для этого формата доступно скачивание файла.';
        content.readOnly = !ws.can_edit || !isText;
        document.getElementById('homework-file-save')?.toggleAttribute('disabled', !isText);
        document.getElementById('homework-file-download').href = data.download_url || `/workspace/${item.id}/download`;
        list.querySelectorAll('button[data-file-id]').forEach((button) => button.classList.toggle('is-active', button.dataset.fileId === String(item.id)));
      } catch (error) { setStatus(error.message); }
    };

    const loadFiles = async () => {
      try {
        const data = await readJson(fetch(`/workspace/files?${new URLSearchParams(getFileScope())}`, { credentials: 'same-origin' }));
        list.replaceChildren();
        for (const attachment of ws.attachments || []) {
          const link = document.createElement('a');
          link.href = attachment.download_url || '#';
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.className = 'homework-file-attachment';
          link.innerHTML = `<i class="ph-bold ph-paperclip"></i> <span>${attachment.name || 'Материал задания'}</span>`;
          list.append(link);
        }
        for (const item of data.files || []) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset.fileId = item.id;
          const icon = document.createElement('i');
          icon.className = 'ph-bold ph-file-text text-indigo-600 text-base';
          const label = document.createElement('span');
          label.textContent = item.current_filename || item.original_filename || 'Файл';
          const size = document.createElement('small');
          size.textContent = item.file_size ? `${Math.ceil(item.file_size / 1024)} КБ` : '';
          button.append(icon, label, size);
          button.addEventListener('click', () => openFile(item));
          list.append(button);
        }
        if (!list.children.length) {
          list.innerHTML = `
            <div class="homework-files-empty">
              <div class="homework-files-empty-icon"><i class="ph-bold ph-folder-dashed"></i></div>
              <div class="homework-files-empty-title">Файлов пока нет</div>
              <div class="homework-files-empty-desc">Прикреплённые материалы или файлы решений появятся здесь</div>
            </div>
          `;
        }
      } catch (error) { setStatus(error.message || 'Не удалось загрузить файлы'); }
    };

    reloadFiles = loadFiles;

    document.getElementById('homework-file-create')?.addEventListener('click', async () => {
      const filename = await window.BooNotify?.prompt?.({ title: 'Новый файл', message: 'Название файла в этом задании', placeholder: 'solution.py', confirmText: 'Создать' });
      if (!filename) return;
      try { await post('/workspace/create', { ...getFileScope(), filename }); await loadFiles(); setStatus('Файл создан'); }
      catch (error) { setStatus(error.message); }
    });
    document.getElementById('homework-file-upload')?.addEventListener('change', async (event) => {
      const input = event.currentTarget;
      const file = input.files?.[0];
      if (!file) return;
      const body = new FormData();
      body.append('file', file);
      Object.entries(getFileScope()).forEach(([key, value]) => body.append(key, String(value)));
      try {
        await readJson(fetch('/workspace/upload', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': token }, body }));
        input.value = '';
        await loadFiles();
        setStatus('Файл загружен');
      } catch (error) { setStatus(error.message); }
    });
    document.getElementById('homework-file-save')?.addEventListener('click', async () => {
      if (!selectedFile) return;
      try { await post(`/workspace/${selectedFile}/save-content`, { content: content.value }); setStatus('Файл сохранён'); }
      catch (error) { setStatus(error.message); }
    });
    loadFiles();
  }

  const pyKeywords = new Set([
    'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
    'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from',
    'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not',
    'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
    'True', 'False', 'None'
  ]);
  const pyBuiltins = new Set([
    'print', 'len', 'range', 'int', 'str', 'float', 'list', 'dict', 'set',
    'tuple', 'bool', 'type', 'input', 'open', 'sum', 'min', 'max', 'abs',
    'round', 'sorted', 'enumerate', 'zip', 'map', 'filter', 'all', 'any'
  ]);

  function highlightPythonCode(source) {
    const escaped = String(source || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const tokenRe = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#.*|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b|[()[\]{}.,:+\-*/%=<>!]+)/g;

    return escaped.split('\n').map((line) => {
      let prevKeyword = '';
      return line.replace(tokenRe, (token) => {
        if (token.startsWith('#')) return '<span class="tok-comment">' + token + '</span>';
        if (token.startsWith('"') || token.startsWith("'")) return '<span class="tok-string">' + token + '</span>';
        if (/^\d/.test(token)) return '<span class="tok-number">' + token + '</span>';
        if (pyKeywords.has(token)) {
          prevKeyword = token;
          return '<span class="tok-keyword">' + token + '</span>';
        }
        if (pyBuiltins.has(token)) return '<span class="tok-builtin">' + token + '</span>';
        if ((prevKeyword === 'def' || prevKeyword === 'class') && /^[A-Za-z_][A-Za-z0-9_]*$/.test(token)) {
          prevKeyword = '';
          return '<span class="tok-func">' + token + '</span>';
        }
        prevKeyword = '';
        if (/^[()[\]{}.,:+\-*/%=<>!]+$/.test(token)) return '<span class="tok-op">' + token + '</span>';
        return token;
      });
    }).join('\n');
  }

  if (!window.boostudyHighlightPythonSyntax) {
    window.boostudyHighlightPythonSyntax = highlightPythonCode;
  }

  function formatTaskCondition(targetEl) {
    const content = (targetEl instanceof HTMLElement)
      ? targetEl
      : (document.getElementById('task-current-content') || document.getElementById('task-window-content'));
    if (!content) return;

    // 1. Python syntax highlighting for code blocks
    const highlight = window.boostudyHighlightPythonSyntax || highlightPythonCode;
    content.querySelectorAll('pre code, pre, .task-python-code').forEach((block) => {
      block.classList.add('task-python-code');
      if (block.querySelector('[class*="syn-"], [class*="tok-"]')) {
        return;
      }
      const raw = block.innerText || block.textContent || '';
      if (!raw.trim()) return;
      block.innerHTML = highlight(raw).replace(/\n$/, '');
    });

    // 2. Format details and sample blocks
    content.querySelectorAll('details').forEach((details) => {
      const summary = details.querySelector('summary');
      if (summary) {
        summary.setAttribute('title', 'Нажмите, чтобы развернуть/свернуть');
      }
      details.querySelectorAll('div, p').forEach((p) => {
        if (p.closest('pre') || p.querySelector('pre, code, details')) return;
        const raw = (p.innerText || p.textContent || '').trim();
        if (raw.includes('print(') || raw.includes('def ') || raw.includes('import ')) {
          p.innerHTML = `<pre class="task-python-code">${highlight(raw).replace(/\n$/, '')}</pre>`;
          return;
        }
        if (p.innerHTML.includes('Выражение:') && p.innerHTML.includes('Результат:')) {
          p.classList.add('task-sample-io');
          p.innerHTML = p.innerHTML.replace(
            /Выражение:\s*([^<\n]+)\s*Результат:\s*([^<\n]+)/g,
            '<span class="task-sample-expr">Выражение: <code>$1</code></span><span class="task-sample-res">Результат: <strong>$2</strong></span>'
          );
        }
      });
    });

    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(content, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '$', right: '$', display: false },
            { left: '\\(', right: '\\)', display: false },
            { left: '\\[', right: '\\]', display: true },
          ],
          throwOnError: false,
        });
      } catch (e) {
        console.warn('KaTeX render error:', e);
      }
    }
  }

  function initLessonNotesViewer(lessonId) {
    const windowEl = document.getElementById('lesson-notes-window');
    if (!windowEl || !lessonId) return;

    const dockIcon = document.getElementById('dock-icon-lesson-notes-window');
    const titleEl = document.getElementById('lesson-notes-title');
    const pagesListEl = document.getElementById('lesson-notes-pages-list');
    const viewportEl = document.getElementById('lesson-notes-viewport');
    const wrapEl = document.getElementById('lesson-notes-canvas-wrap');
    const canvas = document.getElementById('lesson-notes-canvas');
    const emptyEl = document.getElementById('lesson-notes-empty');
    const loadingEl = document.getElementById('lesson-notes-loading');
    const zoomInBtn = document.getElementById('lesson-notes-zoom-in');
    const zoomOutBtn = document.getElementById('lesson-notes-zoom-out');
    const zoomResetBtn = document.getElementById('lesson-notes-zoom-reset');
    const zoomValEl = document.getElementById('lesson-notes-zoom-val');

    if (!canvas || !viewportEl || !wrapEl) return;

    let pages = [];
    let strokes = [];
    let activePageId = 'page_1';
    let currentZoom = 1.0;
    let panX = 0;
    let panY = 0;
    let isLoaded = false;
    let isLoading = false;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    const imageCache = new Map();

    function updateTransform() {
      wrapEl.style.transform = `translate(${panX}px, ${panY}px) scale(${currentZoom})`;
      if (zoomValEl) zoomValEl.textContent = `${Math.round(currentZoom * 100)}%`;
    }

    function setZoom(newZoom) {
      currentZoom = Math.min(3.5, Math.max(0.25, newZoom));
      updateTransform();
    }

    function resetZoom() {
      currentZoom = 1.0;
      panX = 0;
      panY = 0;
      updateTransform();
    }

    function renderBackground(ctx, width, height, bgType) {
      if (bgType === 'dark') {
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(0, 0, width, height);
        ctx.fillStyle = '#334155';
        for (let x = 24; x < width; x += 24) {
          for (let y = 24; y < height; y += 24) {
            ctx.fillRect(x, y, 1.5, 1.5);
          }
        }
        return;
      }

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, width, height);

      if (bgType === 'grid') {
        ctx.strokeStyle = '#f1f5f9';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 24; x < width; x += 24) {
          ctx.moveTo(x, 0); ctx.lineTo(x, height);
        }
        for (let y = 24; y < height; y += 24) {
          ctx.moveTo(0, y); ctx.lineTo(width, y);
        }
        ctx.stroke();
      } else if (bgType === 'lines') {
        ctx.strokeStyle = '#f1f5f9';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let y = 28; y < height; y += 28) {
          ctx.moveTo(0, y); ctx.lineTo(width, y);
        }
        ctx.stroke();
      } else if (bgType === 'dots' || !bgType) {
        ctx.fillStyle = '#cbd5e1';
        for (let x = 24; x < width; x += 24) {
          for (let y = 24; y < height; y += 24) {
            ctx.fillRect(x, y, 1.5, 1.5);
          }
        }
      }
    }

    function drawStroke(ctx, s) {
      if (!s) return;
      const points = Array.isArray(s.points) ? s.points : [];
      if (points.length === 0) return;

      ctx.save();

      // Eraser
      if (s.eraser) {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.strokeStyle = 'rgba(0,0,0,1)';
        ctx.lineWidth = s.width || 20;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        points.forEach((p, i) => {
          if (i === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        });
        ctx.stroke();
        ctx.restore();
        return;
      }

      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = s.color || '#1e293b';
      ctx.lineWidth = s.width || 3;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      if (s.style === 'dashed') ctx.setLineDash([8, 6]);
      else if (s.style === 'dotted') ctx.setLineDash([2, 4]);
      else ctx.setLineDash([]);

      // Highlighter
      if (s.type === 'highlighter' || s.highlighter) {
        ctx.globalCompositeOperation = 'multiply';
        ctx.globalAlpha = s.opacity || 0.38;
        ctx.lineWidth = Math.max(14, (s.width || 6) * 3);
      }

      // Text
      if (s.type === 'text') {
        ctx.fillStyle = s.color || '#0f172a';
        const fontSize = Math.max(12, Number(s.fontSize) || 18);
        ctx.font = `600 ${fontSize}px system-ui, sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(String(s.text || ''), points[0].x, points[0].y);
        ctx.restore();
        return;
      }

      // Sticky Note
      if (s.type === 'note') {
        const p1 = points[0];
        const p2 = points[1] || { x: p1.x + 160, y: p1.y + 120 };
        const x = Math.min(p1.x, p2.x);
        const y = Math.min(p1.y, p2.y);
        const w = Math.max(100, Math.abs(p2.x - p1.x));
        const h = Math.max(60, Math.abs(p2.y - p1.y));
        ctx.fillStyle = s.colorTheme === 'blue' ? '#dbeafe' : s.colorTheme === 'pink' ? '#fce7f3' : s.colorTheme === 'green' ? '#dcfce7' : '#fef9c3';
        ctx.strokeStyle = '#cbd5e1';
        ctx.lineWidth = 1;
        if (ctx.roundRect) ctx.roundRect(x, y, w, h, 8);
        else ctx.rect(x, y, w, h);
        ctx.fill();
        ctx.stroke();
        if (s.text) {
          ctx.fillStyle = '#1e293b';
          ctx.font = '13px system-ui, sans-serif';
          ctx.textBaseline = 'top';
          const words = String(s.text).split(' ');
          let line = '';
          let lineY = y + 8;
          for (const word of words) {
            const testLine = line ? line + ' ' + word : word;
            if (ctx.measureText(testLine).width > w - 16) {
              ctx.fillText(line, x + 8, lineY);
              line = word;
              lineY += 16;
              if (lineY > y + h - 16) break;
            } else {
              line = testLine;
            }
          }
          if (line && lineY <= y + h - 16) ctx.fillText(line, x + 8, lineY);
        }
        ctx.restore();
        return;
      }

      // Image
      if (s.type === 'image' && s.src) {
        const p1 = points[0];
        const p2 = points[1] || { x: p1.x + 200, y: p1.y + 150 };
        const x = Math.min(p1.x, p2.x);
        const y = Math.min(p1.y, p2.y);
        const w = Math.max(20, Math.abs(p2.x - p1.x));
        const h = Math.max(20, Math.abs(p2.y - p1.y));
        let cached = imageCache.get(s.src);
        if (!cached) {
          cached = new Image();
          cached.src = s.src;
          cached.onload = () => renderPage();
          imageCache.set(s.src, cached);
        }
        if (cached && cached.complete && cached.naturalWidth > 0) {
          try { ctx.drawImage(cached, x, y, w, h); } catch (_) {}
        }
        ctx.restore();
        return;
      }

      // Shapes & Connectors
      if (s.type === 'connector' || ['line', 'arrow', 'double-arrow'].includes(s.shape)) {
        const p1 = points[0];
        const p2 = points[points.length - 1];
        if (p1 && p2) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();

          if (s.shape === 'arrow' || s.shape === 'double-arrow') {
            const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
            const headLen = Math.max(10, (s.width || 3) * 3);
            ctx.beginPath();
            ctx.moveTo(p2.x, p2.y);
            ctx.lineTo(p2.x - headLen * Math.cos(angle - Math.PI / 6), p2.y - headLen * Math.sin(angle - Math.PI / 6));
            ctx.moveTo(p2.x, p2.y);
            ctx.lineTo(p2.x - headLen * Math.cos(angle + Math.PI / 6), p2.y - headLen * Math.sin(angle + Math.PI / 6));
            ctx.stroke();
          }
          if (s.shape === 'double-arrow') {
            const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
            const headLen = Math.max(10, (s.width || 3) * 3);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p1.x + headLen * Math.cos(angle - Math.PI / 6), p1.y + headLen * Math.sin(angle - Math.PI / 6));
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p1.x + headLen * Math.cos(angle + Math.PI / 6), p1.y + headLen * Math.sin(angle + Math.PI / 6));
            ctx.stroke();
          }
        }
        ctx.restore();
        return;
      }

      if (s.type === 'shape') {
        const p1 = points[0];
        const p2 = points[1] || p1;
        const x = Math.min(p1.x, p2.x);
        const y = Math.min(p1.y, p2.y);
        const w = Math.max(1, Math.abs(p2.x - p1.x));
        const h = Math.max(1, Math.abs(p2.y - p1.y));
        ctx.beginPath();
        if (s.shape === 'circle') {
          const rad = Math.min(w, h) / 2;
          ctx.arc(x + rad, y + rad, Math.max(0.5, rad), 0, Math.PI * 2);
        } else if (s.shape === 'ellipse') {
          ctx.ellipse(x + w / 2, y + h / 2, Math.max(0.5, w / 2), Math.max(0.5, h / 2), 0, 0, Math.PI * 2);
        } else if (s.shape === 'triangle') {
          ctx.moveTo(x + w / 2, y); ctx.lineTo(x + w, y + h); ctx.lineTo(x, y + h); ctx.closePath();
        } else if (s.shape === 'rounded-rect') {
          const r = Math.min(12, w / 2, h / 2);
          if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
          else ctx.rect(x, y, w, h);
        } else {
          ctx.rect(x, y, w, h);
        }
        ctx.stroke();
        ctx.restore();
        return;
      }

      // Freehand drawing stroke
      ctx.beginPath();
      points.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
      ctx.restore();
    }

    function renderPage() {
      const page = pages.find((p) => p.id === activePageId) || pages[0];
      const pageId = page ? page.id : 'page_1';
      const bgType = page?.background || 'dots';

      const pageStrokes = strokes.filter((s) => {
        if (s.page_id) return s.page_id === pageId;
        return pageId === (pages[0]?.id || 'page_1');
      });

      let minX = 0, minY = 0, maxX = 1200, maxY = 800;
      let hasPoints = false;
      for (const s of pageStrokes) {
        for (const p of s.points || []) {
          if (Number.isFinite(p.x) && Number.isFinite(p.y)) {
            if (!hasPoints) {
              minX = p.x; maxX = p.x;
              minY = p.y; maxY = p.y;
              hasPoints = true;
            } else {
              if (p.x < minX) minX = p.x;
              if (p.x > maxX) maxX = p.x;
              if (p.y < minY) minY = p.y;
              if (p.y > maxY) maxY = p.y;
            }
          }
        }
      }

      const vpW = Math.max(800, viewportEl.clientWidth || 800);
      const vpH = Math.max(600, viewportEl.clientHeight || 600);
      const canvasW = Math.max(vpW, Math.ceil(maxX + 120), 1400);
      const canvasH = Math.max(vpH, Math.ceil(maxY + 120), 900);

      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(canvasW * dpr);
      canvas.height = Math.floor(canvasH * dpr);
      canvas.style.width = `${canvasW}px`;
      canvas.style.height = `${canvasH}px`;
      wrapEl.style.width = `${canvasW}px`;
      wrapEl.style.height = `${canvasH}px`;

      const ctx = canvas.getContext('2d');
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      renderBackground(ctx, canvasW, canvasH, bgType);

      if (pageStrokes.length === 0 && strokes.length === 0) {
        if (emptyEl) emptyEl.classList.remove('hidden');
      } else {
        if (emptyEl) emptyEl.classList.add('hidden');
        pageStrokes.forEach((s) => drawStroke(ctx, s));
      }
    }

    function renderPageTabs() {
      if (!pagesListEl) return;
      pagesListEl.replaceChildren();

      if (pages.length === 0) {
        pages = [{ id: 'page_1', title: 'Страница 1', background: 'dots' }];
      }

      pages.forEach((p, idx) => {
        const isActive = p.id === activePageId;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `px-2.5 py-1 text-xs rounded-lg transition-all flex items-center gap-1.5 border font-medium ${
          isActive
            ? 'bg-white text-emerald-700 font-bold shadow-sm border-slate-300'
            : 'text-slate-600 bg-transparent hover:bg-slate-200/60 border-transparent'
        }`;
        btn.innerHTML = `<i class="ph-bold ph-file-text text-[11px] ${isActive ? 'text-emerald-500' : 'text-slate-400'}"></i><span>${p.title || `Страница ${idx + 1}`}</span>`;
        btn.addEventListener('click', () => {
          activePageId = p.id;
          renderPageTabs();
          renderPage();
        });
        pagesListEl.appendChild(btn);
      });
    }

    async function loadSummary() {
      if (isLoading) return;
      isLoading = true;
      if (loadingEl) loadingEl.classList.remove('hidden');
      if (emptyEl) emptyEl.classList.add('hidden');

      try {
        const resp = await fetch(`/api/lessons/${lessonId}/board-summary`, { credentials: 'same-origin' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error(data.error || 'Ошибка загрузки данных');

        pages = Array.isArray(data.pages) && data.pages.length ? data.pages : [{ id: 'page_1', title: 'Страница 1', background: 'dots' }];
        strokes = Array.isArray(data.strokes) ? data.strokes : [];
        activePageId = data.active_page_id && pages.some((p) => p.id === data.active_page_id) ? data.active_page_id : pages[0].id;

        if (titleEl && data.title) {
          titleEl.textContent = `Конспект · ${data.title}`;
        }

        isLoaded = true;
        renderPageTabs();
        renderPage();
        resetZoom();
      } catch (err) {
        console.warn('Lesson notes load error:', err);
        if (emptyEl) {
          emptyEl.classList.remove('hidden');
          const span = emptyEl.querySelector('span');
          if (span) span.textContent = 'Не удалось загрузить конспект урока.';
        }
      } finally {
        isLoading = false;
        if (loadingEl) loadingEl.classList.add('hidden');
      }
    }

    // Attach zoom controls
    zoomInBtn?.addEventListener('click', () => setZoom(currentZoom * 1.25));
    zoomOutBtn?.addEventListener('click', () => setZoom(currentZoom / 1.25));
    zoomResetBtn?.addEventListener('click', resetZoom);

    // Mouse wheel zoom
    viewportEl.addEventListener('wheel', (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        setZoom(currentZoom * factor);
      }
    }, { passive: false });

    // Drag to pan
    viewportEl.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      isDragging = true;
      dragStartX = e.clientX - panX;
      dragStartY = e.clientY - panY;
      viewportEl.setPointerCapture?.(e.pointerId);
    });

    viewportEl.addEventListener('pointermove', (e) => {
      if (!isDragging) return;
      panX = e.clientX - dragStartX;
      panY = e.clientY - dragStartY;
      updateTransform();
    });

    const stopDrag = (e) => {
      if (isDragging) {
        isDragging = false;
        viewportEl.releasePointerCapture?.(e.pointerId);
      }
    };
    viewportEl.addEventListener('pointerup', stopDrag);
    viewportEl.addEventListener('pointercancel', stopDrag);

    // Trigger load when dock icon clicked or window opened
    dockIcon?.addEventListener('click', () => {
      if (!isLoaded && !isLoading) loadSummary();
    });

    // Observer for window visibility
    const observer = new MutationObserver(() => {
      const isVisible = !windowEl.classList.contains('hidden') && windowEl.style.display !== 'none';
      if (isVisible && !isLoaded && !isLoading) {
        loadSummary();
      }
    });
    observer.observe(windowEl, { attributes: true, attributeFilter: ['class', 'style'] });

    window.refreshLessonNotes = loadSummary;
  }

  function init() {
    window.formatTaskCondition = formatTaskCondition;

    if (isHomework) {
      initFiles();
      if (config.linked_lesson_id) {
        initLessonNotesViewer(config.linked_lesson_id);
      }
    }
    formatTaskCondition();

    if (isHomework && ws) {
      const isInitialCodeAnswer = ws.answer_spec?.type === 'code' || ws.presentation_mode === 'code';
      const initialAnswerWin = document.getElementById('homework-answer-window');
      if (initialAnswerWin) {
        initialAnswerWin.classList.toggle('homework-answer-code', isInitialCodeAnswer);
        const initialCodeHelp = initialAnswerWin.querySelector('.homework-answer-code-help');
        if (initialCodeHelp) {
          initialCodeHelp.hidden = !isInitialCodeAnswer;
          initialCodeHelp.style.display = isInitialCodeAnswer ? 'flex' : 'none';
        }
        if (answerFrame) {
          answerFrame.style.display = isInitialCodeAnswer ? 'none' : '';
        }
      }
      bindCodeAnswerButtons();
    }

    const board = document.getElementById('whiteboard-canvas-viewport');
    if (board && window.BooCanvasOverlay && isHomework && ws) {
      window.BooCanvasOverlay.setContext(ws.task_id, `submission_task_${ws.assignment_task_id}`, ws.context_id);
      window.BooCanvasOverlay.openIn(board);
      if (config.review_mode) {
        if (typeof window.BooCanvasOverlay.setReviewMode === 'function') {
          window.BooCanvasOverlay.setReviewMode(true);
        }
      } else {
        if (typeof window.BooCanvasOverlay.setReadOnly === 'function') {
          window.BooCanvasOverlay.setReadOnly(!ws.can_edit);
        }
      }
    }

    if (isHomework && ws) {
      if (codeEditor && !ws.can_edit) codeEditor.readOnly = true;

      // Seed taskCodeStore for initial task
      const initialCode = (typeof window.getEditorMainPyCode === 'function')
        ? window.getEditorMainPyCode()
        : (ws.code || codeEditor?.value || '');
      taskCodeStore[ws.assignment_task_id] = {
        code: initialCode,
        revision: Number(ws.revision || 1),
        dirty: false,
        lastSavedCode: initialCode,
        hasSavedCode: Boolean(ws.has_saved_code || (ws.code !== null && ws.code !== undefined)),
      };

      if (notesEditor) {
        notesEditor.readOnly = !ws.can_edit;
        readJson(fetch(`/task-workspace/api/notes?${new URLSearchParams(scope)}`, { credentials: 'same-origin' }))
          .then((data) => { if (!notesTouched) notesEditor.value = data.notes || ''; })
          .catch((error) => notify(error.message || 'Не удалось загрузить заметки', true));
        if (ws.can_edit) notesEditor.addEventListener('input', () => {
          notesTouched = true;
          clearTimeout(notesTimer);
          notesTimer = setTimeout(flushNotes, 750);
        });
      }
      window.addEventListener('boostudy:homework-code-input', () => {
        if (!ws || !ws.can_edit) return;
        codeTouched = true;
        const curCode = (typeof window.getEditorMainPyCode === 'function')
          ? window.getEditorMainPyCode()
          : (codeEditor?.value || '');
        if (taskCodeStore[ws.assignment_task_id]) {
          taskCodeStore[ws.assignment_task_id].code = curCode;
          taskCodeStore[ws.assignment_task_id].dirty = true;
        }
        setHwSaveStatus('saving', 'Сохранение...');
        syncAnswerCode();
        clearTimeout(codeTimer);
        codeTimer = setTimeout(() => flushCode(ws.assignment_task_id), 750);
      });
      answerFrame?.addEventListener('load', () => {
        try {
          const frameLoc = answerFrame.contentWindow?.location;
          if (!frameLoc || !frameLoc.href || frameLoc.href === 'about:blank') return;
          syncAnswerCode();
        } catch (e) {
          console.warn('answerFrame load sync:', e);
        }
      });
      loadSources().catch((error) => notify(error.message || 'Не удалось загрузить пространства', true));

      const dialog = document.getElementById('hw-os-transfer');
      document.getElementById('hw-os-transfer-open')?.addEventListener('click', async () => {
        dialog?.showModal();
        try { await loadSources(); }
        catch (error) { document.getElementById('hw-os-transfer-status').textContent = error.message; }
      });
      dialog?.querySelector('.hw-os-dialog-close')?.addEventListener('click', () => dialog.close());
      document.getElementById('hw-os-transfer-confirm')?.addEventListener('click', async (event) => {
        const select = document.getElementById('hw-os-transfer-source');
        if (!select?.value) { select?.focus(); return; }
        const [source_type, source_id] = select.value.split(':');
        const button = event.currentTarget;
        const status = document.getElementById('hw-os-transfer-status');
        button.disabled = true;
        status.textContent = 'Копируем материалы…';
        try {
          await saveAll();
          await post('/task-workspace/api/bridge', { ...scope, source_type, source_id: Number(source_id) });
          window.location.reload();
        } catch (error) {
          status.textContent = error.message || 'Не удалось клонировать пространство';
          button.disabled = false;
        }
      });
      document.getElementById('hw-os-send-lesson')?.addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          await saveAll();
          const result = await post('/task-workspace/api/bridge', { ...scope, direction: 'to_lesson' });
          notify(result.message || 'Материалы сохранены в уроке');
        } catch (error) { notify(error.message || 'Не удалось сохранить в урок', true); }
        finally { button.disabled = false; }
      });
    }

    // ======================================================================
    // Code Gutter Line Comments (Review & Feedback Notes)
    // ======================================================================
    const getSubmissionId = () => ws?.submission_id || (ws?.context_type && ws?.context_type.startsWith('submission') ? ws?.context_id : null) || config.homework_workspace?.submission_id;

    async function loadLineComments(targetTaskId) {
      const subId = getSubmissionId();
      if (!subId) return;
      const tid = targetTaskId || ws?.assignment_task_id;
      if (!tid) return;

      try {
        const url = `/submissions/${subId}/comments?assignment_task_id=${tid}`;
        const res = await fetch(url, { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;

        window.codeLineCommentsMap = {};
        (data.comments || []).forEach(c => {
          const text = c.text || '';
          const m = text.match(/^\[line:(\d+)\]\s*([\s\S]*)$/);
          if (m) {
            const lineNum = parseInt(m[1], 10);
            if (!window.codeLineCommentsMap[lineNum]) window.codeLineCommentsMap[lineNum] = [];
            window.codeLineCommentsMap[lineNum].push({
              id: c.id,
              line: lineNum,
              text: m[2],
              rawText: text,
              author: c.author,
              created_human: c.created_human
            });
          }
        });

        if (typeof window.updateLineNumbers === 'function') {
          window.updateLineNumbers();
        }
        if (window.activeGutterLine && typeof window.renderGutterLineComments === 'function') {
          window.renderGutterLineComments(window.activeGutterLine);
        }
      } catch (e) {
        console.warn('[LineComments] failed to load:', e);
      }
    }

    async function saveLineComment(line, text) {
      const subId = getSubmissionId();
      if (!subId || !text || !text.trim()) return;
      const currentTaskId = ws?.assignment_task_id;
      const formattedText = `[line:${line}] ${text.trim()}`;
      try {
        const res = await fetch(`/submissions/${subId}/comments`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': token
          },
          body: JSON.stringify({
            text: formattedText,
            assignment_task_id: currentTaskId
          })
        });
        const data = await res.json();
        if (data.success && data.comment) {
          notify('Пометка к строке сохранена');
          await loadLineComments(currentTaskId);
          if (window.activeGutterLine && typeof window.renderGutterLineComments === 'function') {
            window.renderGutterLineComments(window.activeGutterLine);
          }
        } else {
          notify(data.error || 'Ошибка при сохранении пометки', true);
        }
      } catch (e) {
        notify('Ошибка при сохранении: ' + e.message, true);
      }
    }

    async function deleteLineComment(commentId, line) {
      const subId = getSubmissionId();
      if (!subId || !commentId) return;
      try {
        const res = await fetch(`/submissions/${subId}/comments/${commentId}`, {
          method: 'DELETE',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': token
          }
        });
        const data = await res.json();
        if (data.success) {
          notify('Пометка удалена');
          await loadLineComments(ws?.assignment_task_id);
          if (window.activeGutterLine && typeof window.renderGutterLineComments === 'function') {
            window.renderGutterLineComments(window.activeGutterLine);
          }
        } else {
          notify(data.error || 'Ошибка при удалении пометки', true);
        }
      } catch (e) {
        notify('Ошибка при удалении: ' + e.message, true);
      }
    }

    window.saveCodeLineComment = saveLineComment;
    window.deleteCodeLineComment = deleteLineComment;
    window.loadCodeLineComments = loadLineComments;

    // Popover UI binding
    const popoverSaveBtn = document.getElementById('code-line-popover-save-btn');
    const popoverInput = document.getElementById('code-line-popover-input');
    if (popoverSaveBtn) {
      popoverSaveBtn.addEventListener('click', async () => {
        if (!window.activeGutterLine) return;
        const text = popoverInput?.value?.trim();
        if (!text) {
          popoverInput?.focus();
          return;
        }
        popoverSaveBtn.disabled = true;
        const origText = popoverSaveBtn.innerHTML;
        popoverSaveBtn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i>';
        try {
          await saveLineComment(window.activeGutterLine, text);
          if (popoverInput) popoverInput.value = '';
        } finally {
          popoverSaveBtn.disabled = false;
          popoverSaveBtn.innerHTML = origText;
        }
      });
    }

    popoverInput?.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        popoverSaveBtn?.click();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        window.closeCodeLinePopover?.();
      }
    });

    if (getSubmissionId() && ws?.assignment_task_id) {
      loadLineComments(ws.assignment_task_id);
    }

    function initReorderableDock() {
      const dock = document.getElementById('board-dock');
      if (!dock) return;

      const storageKey = isHomework
        ? (config.review_mode ? 'boostudy_dock_order_review_v2' : 'boostudy_dock_order_homework_v2')
        : 'boostudy_dock_order_lesson_v2';

      function getDraggableItems() {
        return Array.from(dock.querySelectorAll('.board-dock-item')).filter((el) => {
          if (el.classList.contains('board-dock-divider') || el.id === 'lesson-os-add') return false;
          const style = window.getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetWidth > 0;
        });
      }

      // 1. Restore saved dock order
      try {
        const savedRaw = localStorage.getItem(storageKey);
        const savedDock = JSON.parse(savedRaw || '[]');
        if (Array.isArray(savedDock) && savedDock.length > 0) {
          const itemMap = new Map();
          dock.querySelectorAll('.board-dock-item').forEach((item) => {
            if (item.id) itemMap.set(item.id, item);
          });
          const divider = dock.querySelector('.board-dock-divider') || dock.querySelector('#lesson-os-add');
          savedDock.forEach((id) => {
            const item = itemMap.get(id);
            if (item && item.parentElement === dock) {
              dock.insertBefore(item, divider || null);
            }
          });
        }
      } catch (e) {
        console.warn('Не удалось восстановить порядок панели dock', e);
      }

      let activePointerId = null;
      let draggedItem = null;
      let startX = 0;
      let startY = 0;
      let isDragging = false;
      let initialSlots = [];
      let startIndex = -1;
      let currentIndex = -1;

      function onPointerMove(e) {
        if (!draggedItem || (activePointerId !== null && e.pointerId !== activePointerId)) return;
        const deltaX = e.clientX - startX;
        const deltaY = e.clientY - startY;

        if (!isDragging) {
          if (Math.hypot(deltaX, deltaY) >= 6) {
            isDragging = true;
            draggedItem.dataset.justDragged = 'true';
            draggedItem.classList.add('is-pointer-dragging');

            if (activePointerId !== null && draggedItem.setPointerCapture) {
              try { draggedItem.setPointerCapture(activePointerId); } catch (_) {}
            }
            document.body.classList.add('select-none');

            const items = getDraggableItems();
            startIndex = items.indexOf(draggedItem);
            currentIndex = startIndex;

            // Capture initial unshifted layout bounding rects
            initialSlots = items.map((el) => {
              const r = el.getBoundingClientRect();
              return { el, left: r.left, right: r.right, width: r.width, midX: r.left + r.width / 2 };
            });
          } else {
            return;
          }
        }

        // 1. Dragged item follows cursor with slight elevation
        draggedItem.style.setProperty('transform', `translate3d(${deltaX}px, ${deltaY - 10}px, 0) scale(1.15)`, 'important');
        draggedItem.style.setProperty('z-index', '99999', 'important');

        // 2. Identify target slot by horizontal midpoints between initial slots
        let targetIndex = 0;
        for (let i = 0; i < initialSlots.length - 1; i++) {
          const threshold = (initialSlots[i].midX + initialSlots[i + 1].midX) / 2;
          if (e.clientX > threshold) {
            targetIndex = i + 1;
          }
        }
        targetIndex = Math.max(0, Math.min(targetIndex, initialSlots.length - 1));

        // 3. Shift siblings smoothly to reveal open drop slot
        if (targetIndex !== currentIndex) {
          currentIndex = targetIndex;
          const items = getDraggableItems();

          items.forEach((sibling, idx) => {
            if (sibling === draggedItem) return;

            sibling.style.setProperty('transition', 'transform 0.24s cubic-bezier(0.2, 0, 0, 1)', 'important');

            if (startIndex < currentIndex && idx > startIndex && idx <= currentIndex) {
              const shift = initialSlots[idx - 1].left - initialSlots[idx].left;
              sibling.style.setProperty('transform', `translate3d(${shift}px, 0, 0)`, 'important');
            } else if (startIndex > currentIndex && idx < startIndex && idx >= currentIndex) {
              const shift = initialSlots[idx + 1].left - initialSlots[idx].left;
              sibling.style.setProperty('transform', `translate3d(${shift}px, 0, 0)`, 'important');
            } else {
              sibling.style.setProperty('transform', 'translate3d(0, 0, 0)', 'important');
            }
          });
        }
      }

      function onPointerUp(e) {
        if (!draggedItem || (activePointerId !== null && e.pointerId !== activePointerId)) return;
        window.removeEventListener('pointermove', onPointerMove, true);
        window.removeEventListener('pointerup', onPointerUp, true);
        window.removeEventListener('pointercancel', onPointerUp, true);

        const item = draggedItem;
        const wasDragging = isDragging;
        const fromIdx = startIndex;
        const toIdx = currentIndex;

        if (activePointerId !== null && item.hasPointerCapture && item.hasPointerCapture(activePointerId)) {
          try { item.releasePointerCapture(activePointerId); } catch (_) {}
        }
        document.body.classList.remove('select-none');

        draggedItem = null;
        activePointerId = null;
        isDragging = false;

        if (!wasDragging) {
          item.dataset.justDragged = 'false';
          return;
        }

        // FLIP DROP ANIMATION
        // 1. Capture current live screen positions BEFORE committing DOM change
        const draggedRect = item.getBoundingClientRect();
        const items = getDraggableItems();
        const beforePositions = items.map((el) => {
          return { el, rect: el.getBoundingClientRect() };
        });

        // 2. Commit DOM reordering
        if (toIdx !== fromIdx && toIdx >= 0 && toIdx < items.length) {
          if (toIdx > fromIdx) {
            dock.insertBefore(item, items[toIdx].nextSibling);
          } else {
            dock.insertBefore(item, items[toIdx]);
          }
        }

        // 3. Remove live drag styles from all items so we can measure resting slots
        items.forEach((el) => {
          el.style.removeProperty('transition');
          el.style.removeProperty('transform');
          el.style.removeProperty('z-index');
        });
        item.classList.remove('is-pointer-dragging');

        // 4. Capture resting screen positions AFTER DOM change (Last in FLIP)
        const afterMap = new Map();
        getDraggableItems().forEach((el) => {
          afterMap.set(el, el.getBoundingClientRect());
        });

        // 5. Invert: Set transform to (before - after) so elements visually stay frozen where they were released
        const animatables = [];
        beforePositions.forEach(({ el, rect: beforeRect }) => {
          const afterRect = afterMap.get(el);
          if (!afterRect) return;
          const sourceRect = (el === item) ? draggedRect : beforeRect;
          const dx = sourceRect.left - afterRect.left;
          const dy = sourceRect.top - afterRect.top;

          if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
            el.style.setProperty('transform', `translate3d(${dx}px, ${dy}px, 0)`, 'important');
            el.style.setProperty('transition', 'none', 'important');
            if (el === item) {
              el.style.setProperty('z-index', '99999', 'important');
            }
            animatables.push(el);
          }
        });

        // 6. Force reflow so invert transform takes effect immediately
        void dock.offsetHeight;

        // 7. Play: Transition all items to (0, 0, 0)
        animatables.forEach((el) => {
          el.style.setProperty('transition', 'transform 0.28s cubic-bezier(0.2, 0, 0, 1)', 'important');
          el.style.setProperty('transform', 'translate3d(0, 0, 0)', 'important');
        });

        // 8. On complete: Clean up inline transforms, trigger bounce, persist order
        setTimeout(() => {
          animatables.forEach((el) => {
            el.style.removeProperty('transform');
            el.style.removeProperty('transition');
            el.style.removeProperty('z-index');
          });

          item.classList.add('just-dropped');
          setTimeout(() => item.classList.remove('just-dropped'), 360);

          try {
            const currentOrder = getDraggableItems().map((i) => i.id).filter(Boolean);
            localStorage.setItem(storageKey, JSON.stringify(currentOrder));
          } catch (err) {
            console.warn('Не удалось сохранить порядок dock', err);
          }

          setTimeout(() => {
            item.dataset.justDragged = 'false';
          }, 150);
        }, 290);
      }

      // Attach pointerdown and click blocker
      dock.querySelectorAll('.board-dock-item').forEach((item) => {
        if (item.classList.contains('board-dock-divider') || item.id === 'lesson-os-add') return;

        item.removeAttribute('draggable');

        item.addEventListener('pointerdown', (e) => {
          if (e.button !== 0) return;
          draggedItem = item;
          activePointerId = e.pointerId;
          startX = e.clientX;
          startY = e.clientY;
          isDragging = false;
          item.dataset.justDragged = 'false';

          window.addEventListener('pointermove', onPointerMove, { passive: true, capture: true });
          window.addEventListener('pointerup', onPointerUp, { capture: true });
          window.addEventListener('pointercancel', onPointerUp, { capture: true });
        });

        item.addEventListener('click', (e) => {
          if (item.dataset.justDragged === 'true') {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            return false;
          }
        }, true);
      });
    }

    initReorderableDock();

    let isSwitchingTask = false;

    async function switchTaskSeamless(newAssignmentTaskId, targetUrl) {
      if (isSwitchingTask) return;
      if (String(ws.assignment_task_id) === String(newAssignmentTaskId)) return;
      isSwitchingTask = true;
      console.log('[switchTaskSeamless] starting switch to:', newAssignmentTaskId);

      // 1. Instant optimistic tab feedback: highlight clicked tab immediately
      document.querySelectorAll('.homework-os-task-tab').forEach((tab) => {
        const isCurrent = String(tab.dataset.taskId) === String(newAssignmentTaskId);
        tab.classList.toggle('is-active', isCurrent);
        tab.setAttribute('aria-current', isCurrent ? 'page' : 'false');
      });

      const contentEl = document.getElementById('task-current-content');
      if (contentEl) contentEl.style.opacity = '0.5';

      try {
        const outgoingTaskId = ws.assignment_task_id;
        clearTimeout(codeTimer);
        codeTimer = 0;

        // 1. Capture outgoing task code into taskCodeStore
        const currentEditorCode = (typeof window.getEditorMainPyCode === 'function')
          ? window.getEditorMainPyCode()
          : (codeEditor?.value || '');

        if (taskCodeStore[outgoingTaskId]) {
          if (taskCodeStore[outgoingTaskId].code !== currentEditorCode) {
            taskCodeStore[outgoingTaskId].code = currentEditorCode;
            taskCodeStore[outgoingTaskId].dirty = true;
          }
        } else {
          taskCodeStore[outgoingTaskId] = {
            code: currentEditorCode,
            revision: currentRevision || 1,
            dirty: codeTouched,
            lastSavedCode: currentEditorCode,
            hasSavedCode: true,
          };
        }

        // 2. Perform durable flush of outgoing task and await server ACK before switching context!
        if (ws.can_edit && (codeTouched || taskCodeStore[outgoingTaskId]?.dirty)) {
          setHwSaveStatus('saving', 'Сохранение задания перед переходом...');
          await flushCode(outgoingTaskId);
          await codeSave;
        }
        if (ws.can_edit && (notesTouched || notesTimer)) {
          await flushNotes();
          await notesSave;
        }

        if (ws.can_edit && answerFrame && answerFrame.contentWindow) {
          try {
            const frameWin = answerFrame.contentWindow;
            if (typeof frameWin.saveServer === 'function') {
              await frameWin.saveServer();
            } else if (typeof frameWin.BooTaskWorkspace?.saveServer === 'function') {
              await frameWin.BooTaskWorkspace.saveServer();
            }
            const ansInput = frameWin.document?.querySelector('input[name="answer"], textarea[name="answer"]');
            if (ansInput) {
              taskAnswerStore[outgoingTaskId] = ansInput.value;
              dirtyAnswers[outgoingTaskId] = ansInput.value;
            }
          } catch (e) {
            console.warn('[Homework OS] Error flushing outgoing answer frame:', e);
          }
        }

        // 3. Fetch context for target task
        const apiUrl = `/task-workspace/api/context?context_type=submission_task&context_id=${ws.context_id}&assignment_task_id=${newAssignmentTaskId}`;
        const data = await readJson(fetch(apiUrl, { credentials: 'same-origin' }));

        const newWs = data.workspace;
        if (!newWs) throw new Error('Данные задания не получены');

        // 4. Update active workspace metadata
        ws.assignment_task_id = newAssignmentTaskId;
        ws.task_id = newWs.task_id;
        ws.task_position = newWs.task_position;
        ws.task_title = newWs.task_title;
        ws.can_edit = newWs.can_edit;
        ws.attachments = newWs.attachments || [];
        ws.content_html = newWs.content_html;
        ws.notes = newWs.notes || '';
        ws.answer_spec = newWs.answer_spec || ws.answer_spec;
        ws.archived_files = newWs.archived_files || {};
        ws.has_saved_code = newWs.has_saved_code;

        scope.assignment_task_id = newAssignmentTaskId;
        scope.task_id = newWs.task_id;

        // Update canvas overlay context
        const board = document.getElementById('whiteboard-canvas-viewport');
        if (board && window.BooCanvasOverlay) {
          window.BooCanvasOverlay.setContext(ws.task_id, `submission_task_${ws.assignment_task_id}`, ws.context_id);
          if (config.review_mode) {
            if (typeof window.BooCanvasOverlay.setReviewMode === 'function') {
              window.BooCanvasOverlay.setReviewMode(true);
            }
          } else {
            if (typeof window.BooCanvasOverlay.setReadOnly === 'function') {
              window.BooCanvasOverlay.setReadOnly(!ws.can_edit);
            }
          }
        }

        // Update task tabs active indicator
        document.querySelectorAll('.homework-os-task-tab').forEach((tab) => {
          const isCurrent = String(tab.dataset.taskId) === String(newAssignmentTaskId);
          tab.classList.toggle('is-active', isCurrent);
          tab.setAttribute('aria-current', isCurrent ? 'page' : 'false');
        });

        if (targetUrl) {
          history.pushState({ assignment_task_id: newAssignmentTaskId }, '', targetUrl);
        }

        // Update task title & body
        const titleEl = document.getElementById('task-current-title');
        if (titleEl) {
          titleEl.textContent = `Задание ${newWs.task_position}${newWs.task_title ? ' · ' + newWs.task_title : ''}`;
        }
        if (contentEl) {
          contentEl.innerHTML = newWs.content_html || '<p>Условие задания пока не заполнено.</p>';
          formatTaskCondition();
        }

        // 5. Determine code for target task with proper fallback (no starter code overwrite if code was cleared!)
        let targetCode;
        let targetRev;
        if (taskCodeStore[newAssignmentTaskId]) {
          targetCode = taskCodeStore[newAssignmentTaskId].code;
          targetRev = Math.max(Number(taskCodeStore[newAssignmentTaskId].revision || 1), Number(newWs.revision || 1));
        } else {
          const hasSaved = Boolean(newWs.has_saved_code || (newWs.code !== null && newWs.code !== undefined));
          targetCode = hasSaved ? (newWs.code || '') : (newWs.starter_code || '');
          targetRev = Number(newWs.revision || 1);
          taskCodeStore[newAssignmentTaskId] = {
            code: targetCode,
            revision: targetRev,
            dirty: false,
            lastSavedCode: targetCode,
            hasSavedCode: hasSaved,
          };
        }

        currentRevision = targetRev;
        codeTouched = false;

        // 6. Update single-file editor state
        virtualFS['main.py'] = targetCode;
        openTabs.length = 0;
        openTabs.push('main.py');
        activeFileName = 'main.py';

        if (typeof window.setEditorMainPyCode === 'function') {
          window.setEditorMainPyCode(targetCode);
        } else if (codeEditor) {
          codeEditor.value = targetCode;
          if (typeof onCodeEditorInput === 'function') onCodeEditorInput(codeEditor.value);
          else if (typeof updateCodeHighlight === 'function') updateCodeHighlight();
        }

        // 7. Update read-only state for partial revision!
        if (codeEditor) {
          codeEditor.readOnly = !ws.can_edit;
        }

        // 8. Update archived files button in single-file header
        window.currentArchivedFiles = newWs.archived_files || {};
        const archBtn = document.getElementById('hw-archived-files-btn');
        const archCount = Object.keys(newWs.archived_files || {}).length;
        if (archBtn) {
          if (archCount > 0) {
            archBtn.style.display = '';
            archBtn.innerHTML = `<i class="ph-bold ph-archive text-amber-600"></i><span>Архив файлов (${archCount})</span>`;
          } else {
            archBtn.style.display = 'none';
          }
        }

        setHwSaveStatus('saved', 'Сохранено');
        syncAnswerCode();

        // Keep teacher feedback banner updated across task switches
        const feedbackBanner = document.getElementById('hw-general-feedback-banner');
        const feedbackText = newWs.submission_meta?.teacher_feedback || ws.submission_meta?.teacher_feedback || '';
        if (feedbackBanner) {
          feedbackBanner.style.display = feedbackText ? '' : 'none';
          const bodyEl = feedbackBanner.querySelector('.text-indigo-950') || feedbackBanner;
          if (bodyEl && feedbackText) bodyEl.textContent = feedbackText;
        }

        // Update notes
        if (notesEditor) {
          notesEditor.value = newWs.notes || '';
          notesTouched = false;
        }

        // Update answer window
        const answerTitle = document.querySelector('#homework-answer-window-header span:nth-child(2)');
        if (answerTitle) {
          answerTitle.innerHTML = `<i class="ph-bold ph-check-square" aria-hidden="true"></i> Ответ · задание ${newWs.task_position}`;
        }
        const answerWin = document.getElementById('homework-answer-window');
        const isCodeAnswer = newWs.answer_spec?.type === 'code' || newWs.presentation_mode === 'code';
        if (answerWin) {
          answerWin.classList.toggle('homework-answer-code', isCodeAnswer);
          let codeHelp = answerWin.querySelector('.homework-answer-code-help');
          if (!codeHelp) {
            codeHelp = document.createElement('div');
            codeHelp.className = 'homework-answer-code-help';
            codeHelp.innerHTML = `
              <div class="homework-answer-code-icon-row">
                <i class="ph-bold ph-code" aria-hidden="true"></i>
                <div>
                  <strong>Ответ — программа из окна «Код»</strong>
                  <div id="hw-answer-code-badge" class="homework-answer-code-badge"><i class="ph-bold ph-check-circle"></i> <span id="hw-answer-code-status">Код сохраняется автоматически</span></div>
                </div>
              </div>
              <p>Решение пишется и проверяется в окне «Код». Текущий код из редактора автоматически привязан и отправляется как ответ на это задание.</p>
              <div class="homework-answer-code-actions">
                <button id="hw-save-code-as-answer-btn" type="button" class="is-primary"><i class="ph-bold ph-floppy-disk"></i> Сохранить код как ответ сейчас</button>
                <button type="button" onclick="openWindow('code-window')"><i class="ph-bold ph-arrow-square-out"></i> Перейти в редактор кода</button>
              </div>
              <div class="homework-answer-submit-hint">
                <i class="ph-bold ph-info"></i>
                <span>Когда выполните все задания, нажмите кнопку <strong>«Сдать работу»</strong> вверху справа.</span>
              </div>
            `;
            const header = answerWin.querySelector('#homework-answer-window-header');
            if (header && header.nextSibling) {
              answerWin.insertBefore(codeHelp, header.nextSibling);
            } else {
              answerWin.prepend(codeHelp);
            }
            bindCodeAnswerButtons();
          }
          codeHelp.hidden = !isCodeAnswer;
          codeHelp.style.display = isCodeAnswer ? 'flex' : 'none';
        }
        if (answerFrame) {
          if (!isCodeAnswer) {
            const newFrameSrc = `/task-workspace?context_type=submission_task&context_id=${ws.context_id}&assignment_task_id=${newAssignmentTaskId}&embedded=answer`;
            try {
              const currentUrl = new URL(answerFrame.src, window.location.origin);
              const targetUrl = new URL(newFrameSrc, window.location.origin);
              if (currentUrl.pathname !== targetUrl.pathname || currentUrl.search !== targetUrl.search) {
                answerFrame.src = newFrameSrc;
              }
            } catch (e) {
              if (answerFrame.src !== newFrameSrc) {
                answerFrame.src = newFrameSrc;
              }
            }
            answerFrame.style.display = '';
          } else {
            answerFrame.style.display = 'none';
          }
        }

        // Reload files
        if (typeof reloadFiles === 'function') reloadFiles();

        // Reload transfer sources
        loadSources().catch(() => {});

        // Update Teacher Review OS UI
        if (window.reviewGradeManager?.updateForTask) {
          window.reviewGradeManager.updateForTask(newWs);
        }

        // Reload line comments for new task
        loadLineComments(newAssignmentTaskId);
        if (typeof window.closeCodeLinePopover === 'function') {
          window.closeCodeLinePopover();
        }

        // Update Revision Returned Banner
        const revBanner = document.getElementById('hw-revision-returned-banner');
        const revComment = document.getElementById('hw-revision-returned-comment');
        const revCommentText = document.getElementById('hw-revision-returned-comment-text');
        if (revBanner) {
          const needsRevision = Boolean(newWs.needs_revision);
          revBanner.style.display = needsRevision ? 'block' : 'none';
          if (revComment && revCommentText) {
            const comment = String(newWs.teacher_comment || '').trim();
            if (needsRevision && comment) {
              revCommentText.textContent = comment;
              revComment.style.display = 'block';
            } else {
              revCommentText.textContent = '';
              revComment.style.display = 'none';
            }
          }
        }

        console.log('[switchTaskSeamless] success for:', newAssignmentTaskId);
      } catch (error) {
        console.error('Seamless switch error:', error);
        notify(error.message || 'Не удалось переключить задание', true);
      } finally {
        if (contentEl) contentEl.style.opacity = '1';
        isSwitchingTask = false;
      }
    }

    function initReviewGradeManager(ws, notify) {
      const isReview = Boolean(window.trainerOsConfig?.review_mode || config.review_mode);
      if (!isReview) return null;

      console.log('[initReviewGradeManager] initializing for submission:', ws.submission_id);

      const reviewState = {
        submissionId: ws.submission_id,
        currentAssignmentTaskId: ws.assignment_task_id,
        scores: {},
        teacherFeedback: ws.submission_meta?.teacher_feedback || '',
        status: ws.submission_meta?.status || 'SUBMITTED',
        isSaving: false,
        saveTimer: null,
        playback: {
          frames: Array.isArray(ws.playback?.frames) ? ws.playback.frames.slice() : [],
          index: 0,
          timer: null,
          isPlaying: false
        }
      };

      (ws.tasks_nav || []).forEach(item => {
        reviewState.scores[item.assignment_task_id] = {
          score: (item.score !== undefined && item.score !== null) ? Number(item.score) : null,
          comment: item.teacher_comment || '',
          max_score: Number(item.max_score || 1),
          nav_status: item.nav_status || 'pending_review',
          needs_revision: Boolean(item.needs_revision)
        };
      });

      const statusBadge = document.getElementById('review-task-status-badge');
      const scoreInput = document.getElementById('review-task-score-input');
      const maxScoreEl = document.getElementById('review-task-max-score');
      const quickScoresContainer = document.getElementById('review-quick-scores');
      const commentInput = document.getElementById('review-task-comment');
      const commentStatus = document.getElementById('review-task-comment-status');
      const returnToggle = document.getElementById('review-task-return-toggle');
      const feedbackInput = document.getElementById('review-general-feedback');
      const totalScoreDisplay = document.getElementById('review-total-score-display');
      const maxScoreDisplay = document.getElementById('review-max-score-display');
      const percentDisplay = document.getElementById('review-percent-display');
      const returnBtn = document.getElementById('review-action-return-btn');
      const gradeBtn = document.getElementById('review-action-grade-btn');
      const topGradeBtn = document.getElementById('hw-review-top-grade-btn');

      function updateReturnToggleVisual(isChecked) {
        const lbl = document.getElementById('review-task-return-label');
        const badge = document.getElementById('review-task-return-status-badge');
        if (lbl) {
          if (isChecked) {
            lbl.classList.remove('border-amber-200/80', 'bg-amber-50/60');
            lbl.classList.add('border-amber-400', 'bg-amber-100/90', 'ring-2', 'ring-amber-400/40');
          } else {
            lbl.classList.remove('border-amber-400', 'bg-amber-100/90', 'ring-2', 'ring-amber-400/40');
            lbl.classList.add('border-amber-200/80', 'bg-amber-50/60');
          }
        }
        if (badge) {
          badge.classList.toggle('hidden', !isChecked);
        }
        const curAtId = reviewState.currentAssignmentTaskId;
        const tab = document.querySelector(`.homework-os-task-tab[data-task-id="${curAtId}"]`);
        if (tab) {
          let revBadge = tab.querySelector('.homework-task-return-dot');
          if (isChecked) {
            if (!revBadge) {
              revBadge = document.createElement('span');
              revBadge.className = 'homework-task-return-dot inline-block w-2 h-2 rounded-full bg-amber-500 ml-1 shrink-0';
              revBadge.title = 'Выбрано для возврата на доработку';
              tab.appendChild(revBadge);
            }
          } else if (revBadge) {
            revBadge.remove();
          }
        }
      }

      if (commentInput) {
        commentInput.value = reviewState.scores[reviewState.currentAssignmentTaskId]?.comment || ws.teacher_comment || '';
      }
      if (returnToggle) {
        returnToggle.checked = Boolean(reviewState.scores[reviewState.currentAssignmentTaskId]?.needs_revision);
        updateReturnToggleVisual(returnToggle.checked);
        returnToggle.addEventListener('change', (e) => {
          const atId = reviewState.currentAssignmentTaskId;
          if (!reviewState.scores[atId]) {
            reviewState.scores[atId] = { max_score: 1, score: null, comment: '', needs_revision: false };
          }
          reviewState.scores[atId].needs_revision = e.target.checked;
          updateReturnToggleVisual(e.target.checked);
        });
      }

      const playbackContainer = document.getElementById('review-playback-container');
      const playbackPlayBtn = document.getElementById('review-playback-play-btn');
      const playbackRange = document.getElementById('review-playback-range');
      const playbackStepCounter = document.getElementById('review-playback-step-counter');
      const playbackResetBtn = document.getElementById('review-playback-reset-btn');

      function calculateTotals() {
        let total = 0;
        let maxTotal = 0;
        Object.values(reviewState.scores).forEach(entry => {
          if (entry.score !== null && entry.score !== undefined) {
            total += Number(entry.score);
          }
          maxTotal += Number(entry.max_score || 1);
        });
        const pct = maxTotal > 0 ? Math.round((total / maxTotal) * 100) : 0;
        if (totalScoreDisplay) totalScoreDisplay.textContent = total;
        if (maxScoreDisplay) maxScoreDisplay.textContent = maxTotal;
        if (percentDisplay) percentDisplay.textContent = `(${pct}%)`;
      }

      function updateTabBadge(assignmentTaskId, score, maxScore) {
        const tab = document.querySelector(`.homework-os-task-tab[data-task-id="${assignmentTaskId}"]`);
        if (!tab) return;
        let badge = tab.querySelector('.homework-task-badge');
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'homework-task-badge';
          tab.appendChild(badge);
        }
        badge.className = 'homework-task-badge';
        if (score !== null && score !== undefined) {
          if (score >= maxScore && maxScore > 0) {
            badge.classList.add('is-correct');
            badge.title = `Верно (+${score})`;
            badge.innerHTML = '<i class="ph-bold ph-check"></i>';
          } else if (score === 0) {
            badge.classList.add('is-wrong');
            badge.title = 'Неверно (0)';
            badge.innerHTML = '<i class="ph-bold ph-x"></i>';
          } else {
            badge.classList.add('is-partial');
            badge.title = `Частично (${score}/${maxScore})`;
            badge.innerHTML = '<i class="ph-bold ph-minus"></i>';
          }
        } else {
          badge.classList.add('is-manual');
          badge.title = 'Ждёт проверки';
          badge.innerHTML = '<i class="ph-bold ph-pencil-simple"></i>';
        }
      }

      function renderQuickScores(maxScore, currentScore) {
        if (!quickScoresContainer) return;
        quickScoresContainer.innerHTML = '';
        const numMax = Math.max(1, Number(maxScore) || 1);
        for (let s = 0; s <= numMax; s++) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.dataset.score = s;
          const isAct = (currentScore !== null && currentScore !== undefined && Number(currentScore) === s);
          btn.className = `review-score-btn px-3 py-1.5 rounded-lg border font-bold text-xs transition-all ${
            isAct
              ? (s > 0 ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs is-active' : 'bg-rose-600 text-white border-rose-600 shadow-xs is-active')
              : 'border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-700'
          }`;
          btn.textContent = s;
          btn.addEventListener('click', () => {
            setScoreForCurrentTask(s);
          });
          quickScoresContainer.appendChild(btn);
        }
      }

      function updateStatusBadge(score, maxScore, navStatus) {
        if (!statusBadge) return;
        if (score !== null && score !== undefined) {
          if (score >= maxScore && maxScore > 0) {
            statusBadge.className = 'text-[11px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1 bg-emerald-50 text-emerald-700 border-emerald-200';
            statusBadge.innerHTML = `<i class="ph-bold ph-check-circle text-emerald-600"></i> <span>Верно (+${score})</span>`;
          } else if (score === 0) {
            statusBadge.className = 'text-[11px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1 bg-rose-50 text-rose-700 border-rose-200';
            statusBadge.innerHTML = `<i class="ph-bold ph-x-circle text-rose-600"></i> <span>Неверно (0)</span>`;
          } else {
            statusBadge.className = 'text-[11px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1 bg-amber-50 text-amber-700 border-amber-200';
            statusBadge.innerHTML = `<i class="ph-bold ph-minus-circle text-amber-600"></i> <span>Частично (+${score})</span>`;
          }
        } else {
          statusBadge.className = 'text-[11px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1 bg-slate-100 text-slate-600 border-slate-200';
          statusBadge.innerHTML = '<i class="ph-bold ph-clock text-slate-400"></i> <span>Ждёт проверки</span>';
        }
      }

      function setScoreForCurrentTask(val) {
        const atId = reviewState.currentAssignmentTaskId;
        const numVal = (val === '' || val === null || val === undefined) ? null : Math.max(0, Number(val));
        const entry = reviewState.scores[atId] || { max_score: 1, comment: '' };
        entry.score = numVal;
        reviewState.scores[atId] = entry;

        if (scoreInput) scoreInput.value = (numVal !== null) ? numVal : '';
        renderQuickScores(entry.max_score, numVal);
        updateStatusBadge(numVal, entry.max_score, entry.nav_status);
        updateTabBadge(atId, numVal, entry.max_score);
        calculateTotals();
        scheduleAutosave();
      }

      function setupPlayback(frames) {
        reviewState.playback.frames = Array.isArray(frames) ? frames.slice() : [];
        reviewState.playback.index = reviewState.playback.frames.length ? reviewState.playback.frames.length - 1 : 0;
        if (reviewState.playback.timer) {
          clearInterval(reviewState.playback.timer);
          reviewState.playback.timer = null;
          reviewState.playback.isPlaying = false;
        }
        if (playbackPlayBtn) playbackPlayBtn.innerHTML = '<i class="ph-bold ph-play"></i>';
        if (!playbackContainer) return;
        if (!reviewState.playback.frames.length) {
          playbackContainer.style.display = 'none';
          return;
        }
        playbackContainer.style.display = 'block';
        if (playbackRange) {
          playbackRange.max = reviewState.playback.frames.length - 1;
          playbackRange.value = reviewState.playback.frames.length - 1;
        }
        if (playbackStepCounter) {
          playbackStepCounter.textContent = `${reviewState.playback.frames.length} / ${reviewState.playback.frames.length}`;
        }
      }

      function applyPlaybackFrame(idx) {
        if (!reviewState.playback.frames.length) return;
        const clamped = Math.max(0, Math.min(idx, reviewState.playback.frames.length - 1));
        reviewState.playback.index = clamped;
        const frame = reviewState.playback.frames[clamped];
        if (frame && typeof window.setEditorMainPyCode === 'function') {
          window.setEditorMainPyCode(frame.code || '');
        }
        if (playbackRange) playbackRange.value = clamped;
        if (playbackStepCounter) playbackStepCounter.textContent = `${clamped + 1} / ${reviewState.playback.frames.length}`;
      }

      function togglePlaybackPlay() {
        if (!reviewState.playback.frames.length) return;
        if (reviewState.playback.isPlaying) {
          clearInterval(reviewState.playback.timer);
          reviewState.playback.timer = null;
          reviewState.playback.isPlaying = false;
          if (playbackPlayBtn) playbackPlayBtn.innerHTML = '<i class="ph-bold ph-play"></i>';
        } else {
          if (reviewState.playback.index >= reviewState.playback.frames.length - 1) {
            applyPlaybackFrame(0);
          }
          reviewState.playback.isPlaying = true;
          if (playbackPlayBtn) playbackPlayBtn.innerHTML = '<i class="ph-bold ph-pause"></i>';
          reviewState.playback.timer = setInterval(() => {
            if (reviewState.playback.index < reviewState.playback.frames.length - 1) {
              applyPlaybackFrame(reviewState.playback.index + 1);
            } else {
              togglePlaybackPlay();
            }
          }, 120);
        }
      }

      function updateForTask(newWs) {
        reviewState.currentAssignmentTaskId = newWs.assignment_task_id;
        const atId = newWs.assignment_task_id;
        const curEntry = reviewState.scores[atId] || {
          score: (newWs.answer_score !== undefined && newWs.answer_score !== null) ? Number(newWs.answer_score) : null,
          comment: newWs.teacher_comment || '',
          max_score: Number(newWs.answer_max_score || newWs.max_score || 1),
          nav_status: newWs.nav_status || 'pending_review'
        };
        if (newWs.teacher_comment) curEntry.comment = newWs.teacher_comment;
        reviewState.scores[atId] = curEntry;

        const titleEl = document.getElementById('review-window-task-title');
        if (titleEl) titleEl.textContent = `Проверка · Задание ${newWs.task_position}`;

        if (maxScoreEl) maxScoreEl.textContent = curEntry.max_score;
        if (scoreInput) scoreInput.value = (curEntry.score !== null) ? curEntry.score : '';
        renderQuickScores(curEntry.max_score, curEntry.score);
        updateStatusBadge(curEntry.score, curEntry.max_score, curEntry.nav_status);

        if (commentInput) commentInput.value = curEntry.comment || '';

        const isCode = newWs.answer_spec?.type === 'code' || newWs.presentation_mode === 'code';
        const codeSec = document.getElementById('review-code-answer-section');
        const stdSec = document.getElementById('review-standard-answer-section');
        const chip = document.getElementById('review-task-type-chip');
        if (chip) chip.textContent = isCode ? 'Кодовое решение' : 'Поле ввода';
        if (codeSec) codeSec.style.display = isCode ? 'block' : 'none';
        if (stdSec) stdSec.style.display = isCode ? 'none' : 'grid';

        if (!isCode) {
          const studentBox = document.getElementById('review-student-answer-box');
          const correctBox = document.getElementById('review-correct-answer-box');
          if (studentBox) studentBox.textContent = newWs.plain_answer || '—';
          if (correctBox) correctBox.textContent = newWs.correct_answer || '—';
        }

        if (returnToggle) {
          returnToggle.checked = Boolean(curEntry.needs_revision);
          updateReturnToggleVisual(returnToggle.checked);
        }

        setupPlayback(newWs.playback?.frames);
        calculateTotals();
      }

      function buildPayload(status, scoresOnly = false, returnTaskIds = null) {
        const scores = Object.entries(reviewState.scores).map(([atId, data]) => ({
          assignment_task_id: Number(atId),
          score: (data.score !== null && data.score !== undefined) ? Number(data.score) : 0,
          comment: data.comment || ''
        }));
        const payload = {
          scores,
          teacher_feedback: reviewState.teacherFeedback,
          status: status || reviewState.status || 'GRADED',
          scores_only: Boolean(scoresOnly)
        };
        if (status === 'RETURNED' && Array.isArray(returnTaskIds)) {
          payload.return_assignment_task_ids = returnTaskIds;
        }
        return payload;
      }

      function showReturnRevisionModal(onConfirm) {
        const existing = document.getElementById('homework-return-modal');
        if (existing) existing.remove();

        const selectedIds = Object.entries(reviewState.scores)
          .filter(([_, s]) => s.needs_revision)
          .map(([id]) => Number(id));

        const totalTasks = Object.keys(reviewState.scores).length || 1;
        const curId = Number(reviewState.currentAssignmentTaskId);
        const defaultSelected = selectedIds.length > 0 ? selectedIds : (curId ? [curId] : []);

        const taskLabels = defaultSelected.map(id => {
          const tab = document.querySelector(`.homework-os-task-tab[data-task-id="${id}"]`);
          return tab ? tab.textContent.trim().replace(/\s+/g, ' ') : `Задание #${id}`;
        }).join(', ');

        const modal = document.createElement('div');
        modal.id = 'homework-return-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'hw-return-modal-title');
        modal.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:9999999;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,0.65);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);padding:1rem;pointer-events:auto;';
        modal.innerHTML = `
          <div class="bg-white rounded-2xl shadow-2xl border border-slate-200/80 max-w-md w-full p-6 space-y-4 relative" style="pointer-events:auto;isolation:isolate;">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center text-xl shrink-0">
                <i class="ph-bold ph-arrow-u-up-left"></i>
              </div>
              <div>
                <h3 id="hw-return-modal-title" class="text-base font-extrabold text-slate-900">Возврат на доработку</h3>
                <p class="text-xs text-slate-500">Выберите, какие задания отправить ученику на исправление</p>
              </div>
            </div>

            <div class="space-y-2 pt-2">
              <button type="button" id="hw-return-selected-btn" class="w-full text-left p-3.5 rounded-xl border border-amber-300 bg-amber-50/80 hover:bg-amber-100/80 transition-all cursor-pointer group">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-amber-950 flex items-center gap-1.5">
                    <i class="ph-bold ph-check-square text-amber-700"></i>
                    Вернуть выбранные задачи (${defaultSelected.length} из ${totalTasks})
                  </span>
                  <i class="ph-bold ph-arrow-right text-amber-700 group-hover:translate-x-0.5 transition-transform text-xs"></i>
                </div>
                <p id="homework-return-selected-tasks-summary" class="text-[11px] text-amber-900 font-semibold mt-1 pl-5">Выбрано: <strong>${taskLabels || 'Текущая задача'}</strong></p>
                <p class="text-[11px] text-amber-800/80 mt-0.5 pl-5">Остальные задачи останутся принятыми с сохранёнными баллами</p>
              </button>

              <button type="button" id="hw-return-all-btn" class="w-full text-left p-3.5 rounded-xl border border-slate-200 hover:border-slate-300 bg-slate-50 hover:bg-slate-100 transition-all cursor-pointer group">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                    <i class="ph-bold ph-arrows-clockwise text-slate-600"></i>
                    Вернуть всю работу целиком (${totalTasks} задач)
                  </span>
                  <i class="ph-bold ph-arrow-right text-slate-500 group-hover:translate-x-0.5 transition-transform text-xs"></i>
                </div>
                <p class="text-[11px] text-slate-500 mt-1 pl-5">Ученик сможет заново отредактировать решения всех заданий</p>
              </button>
            </div>

            <div class="flex justify-end pt-2">
              <button type="button" id="hw-return-cancel-btn" class="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer">
                Отмена
              </button>
            </div>
          </div>
        `;
        document.body.appendChild(modal);

        const closeModal = () => {
          window.removeEventListener('keydown', handleEsc);
          modal.remove();
        };

        const handleEsc = (e) => {
          if (e.key === 'Escape') closeModal();
        };
        window.addEventListener('keydown', handleEsc);

        modal.querySelector('#hw-return-cancel-btn').onclick = closeModal;
        modal.onclick = (e) => { if (e.target === modal) closeModal(); };

        modal.querySelector('#hw-return-selected-btn').onclick = () => {
          closeModal();
          onConfirm(defaultSelected);
        };
        modal.querySelector('#hw-return-all-btn').onclick = () => {
          closeModal();
          onConfirm([]);
        };

        const selectedBtn = modal.querySelector('#hw-return-selected-btn');
        if (selectedBtn) selectedBtn.focus();
      }
      window.showReturnRevisionModal = showReturnRevisionModal;

      async function submitGrade(status, returnTaskIds = null) {
        if (reviewState.isSaving) return;
        clearTimeout(reviewState.saveTimer);
        reviewState.isSaving = true;
        if (gradeBtn) gradeBtn.disabled = true;
        if (returnBtn) returnBtn.disabled = true;
        if (topGradeBtn) topGradeBtn.disabled = true;

        try {
          const payload = buildPayload(status, false, returnTaskIds);
          const res = await fetch(`/submissions/${reviewState.submissionId}/grade`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
            credentials: 'same-origin',
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (!res.ok || !data.success) {
            throw new Error(data.error || 'Ошибка при сохранении оценки');
          }

          const isReturned = (status === 'RETURNED');
          notify(isReturned ? 'Работа возвращена на доработку ученику!' : 'Проверка завершена! Оценки сохранены.', false);

          setTimeout(() => {
            window.location.href = ws.return_url || '/submissions';
          }, 1200);
        } catch (err) {
          console.error('Submit grade error:', err);
          notify(err.message || 'Не удалось сохранить оценку', true);
        } finally {
          reviewState.isSaving = false;
          if (gradeBtn) gradeBtn.disabled = false;
          if (returnBtn) returnBtn.disabled = false;
          if (topGradeBtn) topGradeBtn.disabled = false;
        }
      }

      function scheduleAutosave() {
        clearTimeout(reviewState.saveTimer);
        reviewState.saveTimer = setTimeout(async () => {
          try {
            const payload = buildPayload(reviewState.status, true);
            const res = await fetch(`/submissions/${reviewState.submissionId}/grade`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
              credentials: 'same-origin',
              body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
              throw new Error(data.error || `Сервер не подтвердил сохранение (HTTP ${res.status})`);
            }
            setCommentSaveStatus(true);
          } catch (err) {
            console.warn('Review grade autosave failed:', err);
            setCommentSaveStatus(false, err.message || 'Не удалось сохранить оценку и комментарий');
          }
        }, 1000);
      }

      function setCommentSaveStatus(saved, message = '') {
        if (!commentStatus) return;
        commentStatus.innerHTML = saved
          ? '<i class="ph-bold ph-check"></i> Сохранено'
          : '<i class="ph-bold ph-warning-circle"></i> Не сохранено';
        commentStatus.classList.toggle('text-emerald-600', saved);
        commentStatus.classList.toggle('text-rose-600', !saved);
        commentStatus.title = message;
        commentStatus.style.opacity = '1';
        clearTimeout(reviewState.commentStatusTimer);
        reviewState.commentStatusTimer = setTimeout(() => { commentStatus.style.opacity = '0'; }, saved ? 1800 : 6000);
      }

      if (scoreInput) {
        scoreInput.addEventListener('input', (e) => {
          setScoreForCurrentTask(e.target.value);
        });
      }

      if (commentInput) {
        commentInput.addEventListener('input', (e) => {
          const atId = reviewState.currentAssignmentTaskId;
          if (!reviewState.scores[atId]) reviewState.scores[atId] = { max_score: 1, score: null, comment: '' };
          reviewState.scores[atId].comment = e.target.value;
          scheduleAutosave();
        });
      }

      if (feedbackInput) {
        feedbackInput.addEventListener('input', (e) => {
          reviewState.teacherFeedback = e.target.value;
          scheduleAutosave();
        });
      }

      if (returnBtn) {
        returnBtn.addEventListener('click', () => {
          showReturnRevisionModal((taskIds) => {
            submitGrade('RETURNED', taskIds);
          });
        });
      }

      if (gradeBtn) {
        gradeBtn.addEventListener('click', () => {
          submitGrade('GRADED');
        });
      }

      if (topGradeBtn) {
        topGradeBtn.addEventListener('click', () => {
          submitGrade('GRADED');
        });
      }

      if (playbackPlayBtn) {
        playbackPlayBtn.addEventListener('click', togglePlaybackPlay);
      }
      if (playbackRange) {
        playbackRange.addEventListener('input', (e) => {
          applyPlaybackFrame(Number(e.target.value));
        });
      }
      if (playbackResetBtn) {
        playbackResetBtn.addEventListener('click', () => {
          if (reviewState.playback.frames.length) {
            applyPlaybackFrame(reviewState.playback.frames.length - 1);
          }
        });
      }

      let liveStateSnapshot = null;
      let activeArchivedAttempt = null;

      function renderAttemptsHistory() {
        const card = document.getElementById('review-attempts-history-card');
        const badge = document.getElementById('review-attempts-count-badge');
        const list = document.getElementById('review-attempts-list');
        if (!card || !list) return;
        const attempts = Array.isArray(ws?.submission_meta?.attempts) ? ws.submission_meta.attempts : [];
        if (!attempts.length) {
          card.style.display = 'none';
          return;
        }
        card.style.display = 'block';
        if (badge) badge.textContent = `${attempts.length} попытк${attempts.length === 1 ? 'а' : (attempts.length >= 5 ? 'ок' : 'и')}`;
        list.innerHTML = '';
        attempts.forEach((att) => {
          const item = document.createElement('div');
          item.className = 'p-2.5 rounded-xl bg-slate-50 border border-slate-200/80 hover:bg-slate-100 hover:border-indigo-300 transition-all text-xs space-y-1.5 cursor-pointer group';
          item.dataset.attemptNo = String(att.attempt_no || 1);
          if (activeArchivedAttempt && activeArchivedAttempt.attempt_no === att.attempt_no) {
            item.classList.add('ring-2', 'ring-indigo-500', 'bg-indigo-50/70', 'border-indigo-400');
          }
          const dt = att.submitted_at ? new Date(att.submitted_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—';
          const statusMap = {
            'SUBMITTED': 'Сдано на проверку',
            'RETURNED': 'Возвращено на доработку',
            'GRADED': 'Проверено',
            'IN_PROGRESS': 'В процессе'
          };
          const statusLabel = statusMap[att.status] || att.status || 'Сдано';
          const scoreText = (att.total_score !== null && att.total_score !== undefined) ? `${att.total_score} из ${att.max_score || 0} (${Math.round(att.percentage || 0)}%)` : 'Оценка не выставлена';
          const safeFeedback = String(att.teacher_feedback || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
          item.innerHTML = `
            <div class="flex items-center justify-between font-bold text-slate-800">
              <span class="flex items-center gap-1.5"><i class="ph-bold ph-check-circle text-indigo-600"></i> Попытка #${att.attempt_no || 1}</span>
              <span class="text-[11px] font-mono text-slate-500">${dt}</span>
            </div>
            <div class="flex items-center justify-between text-[11px] text-slate-600">
              <span>Статус: <strong class="text-slate-800">${statusLabel}</strong></span>
              <span>${scoreText}</span>
            </div>
            ${safeFeedback ? `<div class="text-[11px] text-slate-500 italic border-l-2 border-indigo-300 pl-2 mt-1 line-clamp-2">${safeFeedback}</div>` : ''}
          `;

          item.addEventListener('click', () => {
            selectArchivedAttempt(att);
          });

          list.appendChild(item);
        });
      }

      function selectArchivedAttempt(att) {
        if (!liveStateSnapshot) {
          liveStateSnapshot = {
            code: (typeof window.getEditorMainPyCode === 'function') ? window.getEditorMainPyCode() : (ws.code || ''),
            plainAnswer: ws.plain_answer || '',
            score: reviewState.scores[reviewState.currentAssignmentTaskId]?.score,
            comment: reviewState.scores[reviewState.currentAssignmentTaskId]?.comment || '',
            teacherFeedback: reviewState.teacherFeedback || '',
            canEdit: ws.can_edit,
            archivedFiles: window.currentArchivedFiles || ws.archived_files || {},
          };
        }

        activeArchivedAttempt = att;
        renderAttemptsHistory();

        let banner = document.getElementById('review-attempt-archive-banner');
        if (!banner) {
          banner = document.createElement('div');
          banner.id = 'review-attempt-archive-banner';
          banner.className = 'bg-amber-50/95 backdrop-blur border-b border-amber-300/80 px-4 py-2.5 flex items-center justify-between text-xs text-amber-950 font-medium z-50 sticky top-0 shadow-xs';
          const card = document.getElementById('review-grade-window') || document.body;
          card.prepend(banner);
        }
        const dt = att.submitted_at ? new Date(att.submitted_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '';
        banner.innerHTML = `
          <div class="flex items-center gap-2">
            <span class="w-6 h-6 rounded-lg bg-amber-200/80 text-amber-800 flex items-center justify-center text-sm font-bold shrink-0">
              <i class="ph-bold ph-archive"></i>
            </span>
            <span>Просмотр <strong>Попытки #${att.attempt_no}</strong> (${dt}). <span class="text-amber-800/80">Архивное состояние сдачи.</span></span>
          </div>
          <button type="button" id="review-attempt-restore-current-btn" class="px-3 py-1.5 bg-white border border-amber-300 rounded-lg text-amber-900 font-bold hover:bg-amber-100 transition-colors shadow-2xs cursor-pointer">
            Вернуться к текущему состоянию
          </button>
        `;

        banner.querySelector('#review-attempt-restore-current-btn').onclick = () => {
          restoreCurrentLiveState();
        };

        const curAtId = String(reviewState.currentAssignmentTaskId);
        const taskAttemptData = (att.attempt_data && att.attempt_data.tasks) ? (att.attempt_data.tasks[curAtId] || att.attempt_data.tasks[Number(curAtId)]) : null;

        let attemptCode = '';
        let attemptArchivedFiles = {};

        if (taskAttemptData) {
          attemptCode = (taskAttemptData.student_code !== undefined)
            ? (taskAttemptData.student_code || '')
            : ((taskAttemptData.files && taskAttemptData.files['main.py']) || '');

          if (taskAttemptData.files && typeof taskAttemptData.files === 'object') {
            for (const [fn, content] of Object.entries(taskAttemptData.files)) {
              if (fn !== 'main.py') {
                attemptArchivedFiles[fn] = content;
              }
            }
          }

          const studentBox = document.getElementById('review-student-answer-box');
          if (studentBox) studentBox.textContent = taskAttemptData.answer || '—';

          try {
            const answerFrame = document.querySelector('iframe[src*="embedded=answer"]');
            if (answerFrame && answerFrame.contentDocument) {
              const inp = answerFrame.contentDocument.getElementById('tw-answer');
              if (inp) inp.value = taskAttemptData.answer || '';
            }
          } catch (_) {}
        } else if (att.student_code !== undefined) {
          attemptCode = att.student_code || '';
        }

        if (typeof window.setEditorMainPyCode === 'function') {
          window.setEditorMainPyCode(attemptCode);
        } else if (codeEditor) {
          codeEditor.value = attemptCode;
          if (typeof onCodeEditorInput === 'function') onCodeEditorInput(attemptCode);
          else if (typeof updateCodeHighlight === 'function') updateCodeHighlight();
        }

        if (codeEditor) {
          codeEditor.readOnly = true;
        }

        window.currentArchivedFiles = attemptArchivedFiles;
        const archBtn = document.getElementById('hw-archived-files-btn');
        const archCount = Object.keys(attemptArchivedFiles).length;
        if (archBtn) {
          if (archCount > 0) {
            archBtn.style.display = '';
            archBtn.innerHTML = `<i class="ph-bold ph-archive text-amber-600"></i><span>Архив файлов (${archCount})</span>`;
          } else {
            archBtn.style.display = 'none';
          }
        }
      }

      function restoreCurrentLiveState() {
        if (!liveStateSnapshot) return;
        if (typeof window.setEditorMainPyCode === 'function') {
          window.setEditorMainPyCode(liveStateSnapshot.code);
        } else if (codeEditor) {
          codeEditor.value = liveStateSnapshot.code;
          if (typeof onCodeEditorInput === 'function') onCodeEditorInput(liveStateSnapshot.code);
          else if (typeof updateCodeHighlight === 'function') updateCodeHighlight();
        }

        if (codeEditor) {
          codeEditor.readOnly = !liveStateSnapshot.canEdit;
        }

        window.currentArchivedFiles = liveStateSnapshot.archivedFiles || {};
        const archBtn = document.getElementById('hw-archived-files-btn');
        const archCount = Object.keys(window.currentArchivedFiles).length;
        if (archBtn) {
          if (archCount > 0) {
            archBtn.style.display = '';
            archBtn.innerHTML = `<i class="ph-bold ph-archive text-amber-600"></i><span>Архив файлов (${archCount})</span>`;
          } else {
            archBtn.style.display = 'none';
          }
        }

        const studentBox = document.getElementById('review-student-answer-box');
        if (studentBox) studentBox.textContent = liveStateSnapshot.plainAnswer || '—';

        try {
          const answerFrame = document.querySelector('iframe[src*="embedded=answer"]');
          if (answerFrame && answerFrame.contentDocument) {
            const inp = answerFrame.contentDocument.getElementById('tw-answer');
            if (inp) inp.value = liveStateSnapshot.plainAnswer || '';
          }
        } catch (_) {}

        const banner = document.getElementById('review-attempt-archive-banner');
        if (banner) banner.remove();

        activeArchivedAttempt = null;
        liveStateSnapshot = null;
        renderAttemptsHistory();
      }

      renderQuickScores(ws.answer_max_score || 1, ws.answer_score);
      updateStatusBadge(ws.answer_score, ws.answer_max_score || 1, ws.nav_status);
      setupPlayback(ws.playback?.frames);
      calculateTotals();
      renderAttemptsHistory();

      return {
        updateForTask,
        setScoreForCurrentTask,
        submitGrade,
        state: reviewState
      };
    }

    if (isHomework) {
      window.currentArchivedFiles = ws.archived_files || {};
      window.reviewGradeManager = initReviewGradeManager(ws, notify);

      // Static sequential task tabs without drag-and-drop
      document.querySelectorAll('.homework-os-task-tab').forEach((link) => {
        link.removeAttribute('draggable');
        link.addEventListener('click', async (event) => {
          event.preventDefault();
          const targetTaskId = link.dataset.taskId;
          if (!targetTaskId || link.getAttribute('aria-current') === 'page') return;
          await switchTaskSeamless(targetTaskId, link.href);
        });
      });

      window.addEventListener('popstate', (event) => {
        const taskId = event.state?.assignment_task_id;
        if (taskId && String(taskId) !== String(ws.assignment_task_id)) {
          switchTaskSeamless(taskId, null);
        }
      });

      function showPostSubmitConfirmation(res) {
        const existing = document.getElementById('homework-submitted-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'homework-submitted-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:9999999;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,0.65);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);padding:1rem;pointer-events:auto;';

        const tasksCount = ws.task_count || (Array.isArray(ws.tasks_nav) ? ws.tasks_nav.length : 1);
        const submitDate = new Date().toLocaleString('ru-RU', { dateStyle: 'long', timeStyle: 'short' });
        const isAutoGraded = res && res.status === 'GRADED';
        const statusText = isAutoGraded
          ? `Автопроверка завершена! Набрано баллов: ${res.score || 0} из ${res.max_score || 0} (${Math.round(res.percentage || 0)}%)`
          : 'Работа отправлена на проверку преподавателю.';

        modal.innerHTML = `
          <div class="bg-white/95 backdrop-blur-2xl rounded-2xl shadow-[0_20px_50px_rgba(15,23,42,0.16)] border border-white/80 max-w-md w-full p-6 space-y-4 text-center" style="pointer-events:auto;isolation:isolate;">
            <div class="w-14 h-14 rounded-2xl bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 flex items-center justify-center text-3xl mx-auto shadow-xs">
              <i class="ph-bold ph-paper-plane-tilt"></i>
            </div>
            <div>
              <h3 id="hw-post-submit-title" class="text-lg font-extrabold text-slate-900 tracking-tight">Работа успешно отправлена!</h3>
              <p class="text-xs text-slate-500 mt-1">${statusText}</p>
            </div>
            <div class="bg-slate-50/80 backdrop-blur-sm rounded-xl p-3.5 border border-slate-200/50 text-left space-y-1.5 text-xs text-slate-600">
              <div class="flex justify-between items-center"><span>Дата и время:</span><strong class="text-slate-800 font-semibold">${submitDate}</strong></div>
              <div class="flex justify-between items-center"><span>Количество заданий:</span><strong class="text-slate-800 font-semibold">${tasksCount}</strong></div>
              <div class="flex justify-between items-center"><span>Статус сдачи:</span><strong class="text-emerald-700 font-bold">${isAutoGraded ? 'Проверено' : 'На проверке'}</strong></div>
            </div>
            <div class="flex gap-2.5 pt-2">
              <button type="button" id="hw-post-submit-stay" class="flex-1 py-2.5 px-4 rounded-xl text-xs font-bold text-slate-700 bg-white/80 hover:bg-white border border-slate-200/80 transition-all cursor-pointer" style="box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;">
                Остаться в окне
              </button>
              <button type="button" id="hw-post-submit-exit" class="flex-1 py-2.5 px-4 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 transition-all cursor-pointer" style="box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3) !important;">
                К списку заданий
              </button>
            </div>
          </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector('#hw-post-submit-stay').onclick = () => {
          modal.remove();
          const submitBtn = document.getElementById('homework-submit');
          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-50', 'cursor-not-allowed');
            submitBtn.innerHTML = '<i class="ph-bold ph-check-circle text-emerald-500"></i><span>Работа сдана</span>';
          }
        };
        modal.querySelector('#hw-post-submit-exit').onclick = () => {
          window.location.href = ws.return_url || '/submissions';
        };
      }
      window.showPostSubmitConfirmation = showPostSubmitConfirmation;

      document.getElementById('homework-submit')?.addEventListener('click', async () => {
        const submitButton = document.getElementById('homework-submit');
        if (submitButton?.dataset.submitting === 'true') return;
        if (submitButton) {
          submitButton.dataset.submitting = 'true';
          submitButton.disabled = true;
          submitButton.innerHTML = '<i class="ph-bold ph-spinner-gap animate-spin"></i><span>Отправка...</span>';
        }
        try {
          setHwSaveStatus('saving', 'Сохранение...');

          // Single-file: get current code from active editor
          const mainCode = (typeof window.getEditorMainPyCode === 'function')
            ? window.getEditorMainPyCode()
            : (document.getElementById('code-editor-textarea')?.value || '');

          if (taskCodeStore[ws.assignment_task_id]) {
            taskCodeStore[ws.assignment_task_id].code = mainCode;
            taskCodeStore[ws.assignment_task_id].dirty = true;
          }

          // Flush all dirty tasks and await save
          await flushAllDirtyTasks();
          await flushCode(ws.assignment_task_id);
          if (codeSave) await codeSave;
          await saveAll();

          // Flush active answer frame if present
          if (answerFrame && answerFrame.contentWindow) {
            try {
              const frameWin = answerFrame.contentWindow;
              if (typeof frameWin.saveServer === 'function') {
                await frameWin.saveServer();
              }
              const ansInput = frameWin.document?.querySelector('input[name="answer"], textarea[name="answer"]');
              if (ansInput) {
                taskAnswerStore[ws.assignment_task_id] = ansInput.value;
                dirtyAnswers[ws.assignment_task_id] = ansInput.value;
              }
            } catch (_) {}
          }

          setHwSaveStatus('saved', 'Сохранено');

          const submitPayload = {
            task_files: {
              assignment_task_id: ws.assignment_task_id,
              code: mainCode,
              files: { 'main.py': mainCode },
              open_tabs: ['main.py'],
              active_file: 'main.py',
              revision: currentRevision || 1,
            },
            dirty_answers: dirtyAnswers
          };

          const res = await post(`/submissions/${ws.context_id}/submit`, submitPayload);

          // Lock editor on submit
          ws.can_edit = false;
          if (codeEditor) {
            codeEditor.readOnly = true;
          }
          const textarea = document.getElementById('code-editor-textarea');
          if (textarea) textarea.readOnly = true;

          showPostSubmitConfirmation(res);
        } catch (error) {
          if (submitButton) {
            submitButton.disabled = false;
            delete submitButton.dataset.submitting;
            const isRet = Boolean(ws.submission_meta && ws.submission_meta.is_returned);
            submitButton.innerHTML = `<i class="ph-bold ph-paper-plane-tilt"></i><span>${isRet ? 'Отправить на повторную проверку' : 'Сдать работу'}</span>`;
          }
          setHwSaveStatus('conflict', 'Ошибка сдачи');
          notify(error.message || 'Не удалось сдать работу', true);
        }
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
