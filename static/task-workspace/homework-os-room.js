(() => {
  const config = JSON.parse(document.getElementById('trainer-os-config')?.textContent || '{}');
  if (!config.room_mode && !config.homework_mode) return;
  const isHomework = Boolean(config.homework_mode && config.homework_workspace);
  const ws = isHomework ? config.homework_workspace : null;
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
    if (!response.ok || !data.success) throw new Error(data.error || 'Не удалось выполнить действие');
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
  let notesTouched = false;
  let sources = null;

  function syncAnswerCode() {
    const inner = answerFrame?.contentWindow;
    const field = inner?.document?.getElementById('tw-code');
    if (field && field.value !== codeEditor.value) {
      field.value = codeEditor.value;
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (inner?.TASK_WORKSPACE) inner.TASK_WORKSPACE.code = codeEditor.value;
  }

  function flushCode() {
    if (!isHomework || !ws || !ws.can_edit) return codeSave;
    clearTimeout(codeTimer);
    const code = codeEditor?.value || '';
    syncAnswerCode();
    codeSave = codeSave.catch(() => {}).then(() => post('/task-workspace/api/code', { ...scope, code }));
    codeSave.then(() => {
      const badge = document.getElementById('hw-answer-code-status');
      if (badge) badge.textContent = `Код сохранён автоматически (${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })})`;
    }).catch((error) => notify(error.message || 'Код не сохранён', true));
    return codeSave;
  }

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
    const notes = notesEditor?.value || '';
    notesSave = notesSave.catch(() => {}).then(() => post('/task-workspace/api/notes', { ...scope, notes }));
    notesSave.then(() => {
      const status = document.getElementById('notes-status-text');
      if (status) status.textContent = 'Сохранено';
    }).catch((error) => notify(error.message || 'Заметки не сохранены', true));
    return notesSave;
  }

  async function saveAll() {
    if (!ws.can_edit) return;
    try {
      await flushCode();
      const saved = await answerFrame?.contentWindow?.BooTaskWorkspace?.save?.();
      if (saved === false) console.warn('Ответ не сохранён');
      await flushNotes();
      await window.BooCanvasOverlay?.save?.();
    } catch (err) {
      console.warn('saveAll warning:', err);
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

  function formatTaskCondition() {
    const content = document.getElementById('task-current-content');
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
          ],
        });
      } catch (e) {
        console.warn('KaTeX render error:', e);
      }
    }
  }

  function init() {
    window.formatTaskCondition = formatTaskCondition;

    if (isHomework) {
      initFiles();
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
    if (board && window.BooCanvasOverlay) {
      if (isHomework && ws) {
        window.BooCanvasOverlay.setContext(ws.task_id, `submission_task_${ws.assignment_task_id}`, ws.context_id);
      } else {
        // Lesson room whiteboard context
        let initialTaskId = config.lesson_id;
        let initialContextType = 'lesson';
        let initialContextId = config.lesson_id;
        try {
          const rawTasks = typeof config.classwork_tasks === 'string' ? JSON.parse(config.classwork_tasks || '[]') : config.classwork_tasks;
          const tasks = Array.isArray(rawTasks) ? rawTasks : [];
          if (tasks.length > 0 && tasks[0]) {
            initialTaskId = tasks[0].task_id || tasks[0].lesson_task_id || config.lesson_id;
            initialContextType = 'lesson_task';
            initialContextId = tasks[0].lesson_task_id || config.lesson_id;
          }
        } catch (_) {}
        if (initialTaskId) {
          window.BooCanvasOverlay.setContext(Number(initialTaskId), initialContextType, initialContextId ? Number(initialContextId) : null);
        }
      }
      window.BooCanvasOverlay.openIn(board);
    }

    if (isHomework && ws) {
      if (codeEditor && !ws.can_edit) codeEditor.readOnly = true;
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
      if (ws.can_edit) window.addEventListener('boostudy:homework-code-input', () => {
        syncAnswerCode();
        clearTimeout(codeTimer);
        codeTimer = setTimeout(flushCode, 750);
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

    function initReorderableDock() {
      const dock = document.getElementById('board-dock');
      if (!dock) return;

      const storageKey = isHomework ? 'boostudy_dock_order_homework_v2' : 'boostudy_dock_order_lesson_v2';

      function getDraggableItems() {
        return Array.from(dock.querySelectorAll('.board-dock-item')).filter((el) => {
          if (el.classList.contains('board-dock-divider') || el.id === 'lesson-os-add') return false;
          const style = window.getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetWidth > 0;
        });
      }

      // 1. Restore saved dock order
      try {
        const savedRaw = localStorage.getItem(storageKey) || localStorage.getItem('boostudy_dock_order_v1');
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
            localStorage.setItem('boostudy_dock_order_v1', JSON.stringify(currentOrder));
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

      const contentEl = document.getElementById('task-current-content');
      if (contentEl) contentEl.style.opacity = '0.4';

      try {
        await saveAll();

        const apiUrl = `/task-workspace/api/context?context_type=submission_task&context_id=${ws.context_id}&assignment_task_id=${newAssignmentTaskId}`;
        const data = await readJson(fetch(apiUrl, { credentials: 'same-origin' }));
        const newWs = data.workspace;
        if (!newWs) throw new Error('Данные задания не получены');

        // Update active workspace metadata
        ws.assignment_task_id = newAssignmentTaskId;
        ws.task_id = newWs.task_id;
        ws.task_position = newWs.task_position;
        ws.task_title = newWs.task_title;
        ws.can_edit = newWs.can_edit;
        ws.attachments = newWs.attachments || [];
        ws.content_html = newWs.content_html;
        ws.code = newWs.code || newWs.starter_code || '';
        ws.notes = newWs.notes || '';
        ws.answer_spec = newWs.answer_spec || ws.answer_spec;

        scope.assignment_task_id = newAssignmentTaskId;
        scope.task_id = newWs.task_id;

        // Update canvas overlay context
        const board = document.getElementById('whiteboard-canvas-viewport');
        if (board && window.BooCanvasOverlay) {
          window.BooCanvasOverlay.setContext(ws.task_id, `submission_task_${ws.assignment_task_id}`, ws.context_id);
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

        // Update code editor
        if (codeEditor) {
          codeEditor.value = newWs.code || newWs.starter_code || '';
          if (typeof onCodeEditorInput === 'function') onCodeEditorInput(codeEditor.value);
          else if (typeof updateCodeHighlight === 'function') updateCodeHighlight();
          syncAnswerCode();
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
            const newFrameSrc = `/task-workspace/?context_type=submission_task&context_id=${ws.context_id}&assignment_task_id=${newAssignmentTaskId}&embedded=answer`;
            if (answerFrame.src !== newFrameSrc) {
              answerFrame.src = newFrameSrc;
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

        console.log('[switchTaskSeamless] success for:', newAssignmentTaskId);
      } catch (error) {
        console.error('Seamless switch error:', error);
        notify(error.message || 'Не удалось переключить задание', true);
      } finally {
        if (contentEl) contentEl.style.opacity = '1';
        isSwitchingTask = false;
      }
    }

    if (isHomework) {
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

      document.getElementById('homework-submit')?.addEventListener('click', async () => {
        try {
          await saveAll();
          answerFrame?.contentWindow?.document?.getElementById('tw-submit-work')?.click();
        } catch (error) { notify(error.message || 'Не удалось сдать работу', true); }
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
