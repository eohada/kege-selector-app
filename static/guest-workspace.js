(() => {
  const root = document.querySelector('.guest-workspace');
  if (!root) return;
  const cards = [...root.querySelectorAll('.guest-task-card')];
  const switches = [...root.querySelectorAll('.guest-task-switch')];
  const config = window.guestWorkspaceConfig || {};
  const phaseNames = {orientation:'Знакомство', theory:'Теория', practice:'Практика', analytics:'Результат', return:'Следующий шаг', finish:'Готово'};
  let activeCard = cards[0];
  const state = new Map();

  const fields = (card) => ({
    answer: card.querySelector('[data-answer]'), comment: card.querySelector('[data-comment]'),
    code: card.querySelector('[data-code]'), flag: card.querySelector('[data-flag-toggle]'),
  });
  const payload = (card) => {
    const f = fields(card); const checked = card.querySelector('input[type=radio]:checked');
    return {answer_text: checked ? checked.value : (f.answer?.value || ''), comment: f.comment?.value || '', flagged: f.flag?.getAttribute('aria-pressed') === 'true', answer_json: f.code?.value ? {workspace_code: f.code.value} : null};
  };
  const setStatus = (card, message) => card.querySelectorAll('[data-save-state]').forEach((node) => { node.textContent = message; });
  const updateProgress = () => {
    const done = cards.filter((card) => card.dataset.done === '1').length;
    document.querySelector('#progress-label').textContent = done;
    document.querySelector('#progress-bar').style.width = `${cards.length ? done / cards.length * 100 : 0}%`;
    document.querySelector('#progress-percent').textContent = `${cards.length ? Math.round(done / cards.length * 100) : 0}%`;
    const current = cards.find((card) => card.dataset.done !== '1');
    document.querySelector('#phase-label').textContent = current ? (phaseNames[current.dataset.phase] || 'Практика') : 'Все задания готовы к сдаче';
    switches.forEach((button) => {
      const card = cards.find((item) => String(item.dataset.task) === button.dataset.taskTarget);
      button.classList.toggle('is-filled', card?.dataset.done === '1');
      button.classList.toggle('is-draft', card?.dataset.draft === '1' && card?.dataset.done !== '1');
    });
  };
  const syncProgressFromFields = (card) => {
    const current = payload(card);
    const hasPhotos = (card._attachments || []).length > 0;
    card.dataset.done = (current.answer_text || hasPhotos) ? '1' : '0';
    card.dataset.draft = !current.answer_text && (current.comment || current.answer_json?.workspace_code || hasPhotos) ? '1' : '0';
    updateProgress();
  };
  const save = async (card, silent = false) => {
    if (!card || card.dataset.saving === '1') return;
    const button = card.querySelector('[data-save-url]'); if (!button) return;
    card.dataset.saving = '1';
    try {
      await guestJson(button.dataset.saveUrl, {method:'POST', body:JSON.stringify(payload(card))});
      const p = payload(card);
      const hasPhotos = (card._attachments || []).length > 0;
      card.dataset.done = (p.answer_text || hasPhotos) ? '1' : '0';
      card.dataset.draft = !p.answer_text && (p.comment || p.answer_json?.workspace_code || hasPhotos) ? '1' : '0';
      if (!silent) setStatus(card, 'Сохранено'); updateProgress();
    } catch (error) { setStatus(card, error.message); }
    finally { delete card.dataset.saving; }
  };
  const renderMath = (target = root) => {
    if (typeof renderMathInElement === 'function') {
      renderMathInElement(target, {
        delimiters: [
          {left: "$$", right: "$$", display: true},
          {left: "$", right: "$", display: false},
          {left: "\\(", right: "\\)", display: false},
          {left: "\\[", right: "\\]", display: true}
        ],
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
        throwOnError: false
      });
    }
  };
  const highlightConditionCode = (target = root) => {
    target.querySelectorAll('.guest-task-condition pre code').forEach((block) => {
      if (block.dataset.highlighted) return;
      block.innerHTML = paintPython(block.textContent.trim());
      block.dataset.highlighted = '1';
    });
  };
  const activate = async (id) => {
    const next = cards.find((card) => String(card.dataset.task) === String(id));
    if (!next || next === activeCard) return;
    await save(activeCard, true);
    activeCard.hidden = true; next.hidden = false; activeCard = next;
    switches.forEach((button) => button.setAttribute('aria-selected', String(button.dataset.taskTarget === String(id))));
    initBoard(next);
    renderMath(next);
    highlightConditionCode(next);
    next.scrollIntoView({behavior:'smooth', block:'start'});
  };
  switches.forEach((button) => button.addEventListener('click', () => activate(button.dataset.taskTarget)));

  const escapeHtml = (value) => value.replace(/[&<>]/g, (symbol) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[symbol]));
  const paintPython = (code) => escapeHtml(code || ' ').replace(/(#[^\n]*|(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(?:and|as|assert|break|class|continue|def|del|elif|else|except|False|finally|for|from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield)\b|\b(?:print|input|len|range|sum|min|max|sorted|enumerate|zip|int|str|float|list|dict|set|tuple|abs|map|filter|all|any|round)\b|\b\d+(?:\.\d+)?\b|[+\-*/%]=?|==|!=|<=|>=|[=<>])/g, (token) => {
    if (token.startsWith('#')) return `<span class="guest-token-comment">${token}</span>`;
    if (/^["']/.test(token)) return `<span class="guest-token-string">${token}</span>`;
    if (/^\d/.test(token)) return `<span class="guest-token-number">${token}</span>`;
    if (/^(print|input|len|range|sum|min|max|sorted|enumerate|zip|int|str|float|list|dict|set|tuple|abs|map|filter|all|any|round)$/.test(token)) return `<span class="guest-token-builtin">${token}</span>`;
    if (/^[+\-*/%=<>!]+$/.test(token)) return `<span class="guest-token-operator">${token}</span>`;
    return `<span class="guest-token-keyword">${token}</span>`;
  });

  const formatSize = (bytes) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
  };

  const setupPhotos = (card) => {
    card._attachments = card._attachments || [];
    const render = () => {
      const lists = card.querySelectorAll('[data-photo-list]');
      const empties = card.querySelectorAll('[data-photo-empty]');
      const has = card._attachments.length > 0;
      empties.forEach((el) => { el.style.display = has ? 'none' : 'block'; });
      lists.forEach((list) => {
        list.innerHTML = '';
        if (!has) return;
        card._attachments.forEach((att) => {
          const item = document.createElement('div');
          item.className = 'guest-photo-item';
          item.title = `${att.name} (${formatSize(att.size)})`;
          if (att.is_image) {
            const img = document.createElement('img');
            img.src = att.url;
            img.alt = att.name;
            img.loading = 'lazy';
            item.appendChild(img);
            item.addEventListener('click', (e) => {
              if (e.target.closest('.guest-photo-del')) return;
              const modal = document.querySelector('#photo-viewer-modal');
              if (modal) {
                document.querySelector('#photo-modal-img').src = att.url;
                document.querySelector('#photo-modal-title').textContent = att.name;
                modal.showModal();
              }
            });
          } else {
            const icon = document.createElement('span');
            icon.className = 'guest-photo-file-icon';
            icon.textContent = '📄';
            item.appendChild(icon);
            item.addEventListener('click', (e) => {
              if (e.target.closest('.guest-photo-del')) return;
              window.open(att.url, '_blank');
            });
          }
          const badge = document.createElement('span');
          badge.className = 'guest-photo-badge';
          badge.textContent = formatSize(att.size);
          item.appendChild(badge);

          const del = document.createElement('button');
          del.type = 'button';
          del.className = 'guest-photo-del';
          del.title = 'Удалить';
          del.textContent = '✕';
          del.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
              const baseParts = location.pathname.split('/');
              const tokenIdx = baseParts.indexOf('s') + 1;
              const token = tokenIdx > 0 ? baseParts[tokenIdx] : '';
              await guestJson(`/guest/s/${token}/attachments/${card.dataset.task}/files/${att.id}/delete`, {method: 'POST'});
              card._attachments = card._attachments.filter((x) => x.id !== att.id);
              render();
              syncProgressFromFields(card);
            } catch (err) {
              alert(err.message || 'Не удалось удалить');
            }
          });
          item.appendChild(del);
          list.appendChild(item);
        });
      });
    };
    card._renderPhotos = render;

    const handleFiles = async (files) => {
      if (!files || !files.length) return;
      const uploadUrl = card.querySelector('[data-photo-zone]')?.dataset.uploadUrl;
      if (!uploadUrl) return;
      const body = new FormData();
      [...files].forEach((f) => body.append('file', f));
      setStatus(card, 'Загружаем фото…');
      try {
        const res = await guestJson(uploadUrl, {method: 'POST', body});
        if (res.files && res.files.length) {
          card._attachments = [...card._attachments, ...res.files];
          render();
          setStatus(card, 'Фото сохранено');
          syncProgressFromFields(card);
        }
      } catch (err) {
        setStatus(card, err.message || 'Ошибка загрузки');
      }
    };

    card.querySelectorAll('[data-photo-input]').forEach((input) => {
      input.addEventListener('change', (e) => {
        handleFiles(e.target.files);
        input.value = '';
      });
    });

    card.querySelectorAll('[data-photo-zone]').forEach((zone) => {
      zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('is-dragover'); });
      zone.addEventListener('dragleave', () => zone.classList.remove('is-dragover'));
      zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('is-dragover');
        if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files);
      });
    });
  };
  const renderCodeEditor = (card) => {
    const editor = card.querySelector('[data-code]'); const highlight = card.querySelector('[data-code-highlight]'); const gutter = card.querySelector('[data-code-gutter]');
    if (!editor || !highlight || !gutter) return;
    highlight.innerHTML = paintPython(editor.value) + '\n';
    gutter.textContent = Array.from({length: Math.max(1, editor.value.split('\n').length)}, (_, index) => index + 1).join('\n');
    highlight.scrollTop = editor.scrollTop; highlight.scrollLeft = editor.scrollLeft; gutter.scrollTop = editor.scrollTop;
  };
  const initCodeEditor = (card) => {
    const editor = card.querySelector('[data-code]'); if (!editor) return;
    const insert = (text, start, end = start) => { editor.setRangeText(text, start, end, 'end'); editor.dispatchEvent(new Event('input', {bubbles:true})); };
    editor.addEventListener('input', () => renderCodeEditor(card));
    editor.addEventListener('scroll', () => renderCodeEditor(card));
    editor.addEventListener('keydown', (event) => {
      const pairs = {'(' : ')', '[' : ']', '{' : '}', '"' : '"', "'" : "'"};
      const closers = new Set(Object.values(pairs)); const start = editor.selectionStart; const end = editor.selectionEnd; const selected = editor.value.slice(start, end);
      if (event.key === 'Tab') { event.preventDefault(); insert('    ', start, end); return; }
      if (event.key === 'Enter') { event.preventDefault(); const line = editor.value.slice(0, start).split('\n').pop(); const indent = (line.match(/^\s*/) || [''])[0] + (line.trimEnd().endsWith(':') ? '    ' : ''); insert(`\n${indent}`, start, end); return; }
      if (pairs[event.key]) { event.preventDefault(); const pair = pairs[event.key]; insert(`${event.key}${selected}${pair}`, start, end); editor.setSelectionRange(start + 1, start + 1 + selected.length); return; }
      if (closers.has(event.key) && !selected && editor.value[start] === event.key) { event.preventDefault(); editor.setSelectionRange(start + 1, start + 1); }
    });
    renderCodeEditor(card);
  };
  cards.forEach((card, index) => {
    initCodeEditor(card);
    setupPhotos(card);
    card.querySelectorAll('[data-tool-tab]').forEach((button) => button.addEventListener('click', () => {
      card.querySelectorAll('[data-tool-tab]').forEach((item) => item.classList.toggle('is-active', item === button));
      card.querySelectorAll('[data-tool-pane]').forEach((item) => item.classList.toggle('is-active', item.dataset.toolPane === button.dataset.toolTab));
      if (button.dataset.toolTab === 'board') initBoard(card);
    }));
    card.querySelector('[data-flag-toggle]')?.addEventListener('click', (event) => { const button = event.currentTarget; button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true')); save(card, true); });
    [fields(card).answer, fields(card).comment, fields(card).code, ...card.querySelectorAll('input[type=radio]')].filter(Boolean).forEach((field) => { let timer; field.addEventListener(field.type === 'radio' ? 'change' : 'input', () => { syncProgressFromFields(card); clearTimeout(timer); timer = setTimeout(() => save(card, true), 800); }); });
    card.querySelector('[data-save-url]')?.addEventListener('click', () => save(card));
    card.querySelector('[data-prev-task]')?.addEventListener('click', () => activate(cards[Math.max(0, index - 1)].dataset.task));
    card.querySelector('[data-next-task]')?.addEventListener('click', () => activate(cards[Math.min(cards.length - 1, index + 1)].dataset.task));
    card.querySelector('[data-run-url]')?.addEventListener('click', async (event) => {
      const code = card.querySelector('[data-code]').value; const output = card.querySelector('[data-code-output]');
      output.textContent = 'Запуск…'; output.classList.remove('is-error');
      try { const result = await guestJson(event.currentTarget.dataset.runUrl, {method:'POST', body:JSON.stringify({code})}); output.textContent = result.stderr || result.stdout || 'Код выполнен без вывода.'; output.classList.toggle('is-error', Boolean(result.stderr)); if (result.turtle_image_b64) output.textContent += '\n\n[turtle] Рисунок сформирован.'; }
      catch (error) { output.textContent = error.message; output.classList.add('is-error'); }
    });
  });

  const boardState = new WeakMap();
  function initBoard(card) {
    const canvas = card.querySelector('[data-board]'); if (!canvas || boardState.has(canvas)) return;
    const ctx = canvas.getContext('2d'); const board = {shapes:[], tool:'pen', color:'#4f46e5', size:3, drawing:null, view:{x:0,y:0,zoom:1}, loaded:false}; boardState.set(canvas, board);
    const toolbar = card.querySelector('.guest-board-toolbar');
    const resize = () => { const rect = canvas.getBoundingClientRect(); const ratio = Math.min(2, window.devicePixelRatio || 1); canvas.width = Math.max(1, Math.round(rect.width * ratio)); canvas.height = Math.max(1, Math.round(rect.height * ratio)); render(); };
    const point = (event) => { const rect = canvas.getBoundingClientRect(); const x = (event.clientX - rect.left) * canvas.width / rect.width; const y = (event.clientY - rect.top) * canvas.height / rect.height; return {x:(x - board.view.x) / board.view.zoom, y:(y - board.view.y) / board.view.zoom}; };
    const renderShape = (shape, preview = false) => { ctx.save(); ctx.globalCompositeOperation = shape.erase ? 'destination-out' : 'source-over'; ctx.strokeStyle = shape.color; ctx.fillStyle = shape.color; ctx.lineWidth = shape.size; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; if (shape.type === 'pen') { ctx.beginPath(); shape.points.forEach((p, i) => i ? ctx.lineTo(p.x,p.y) : ctx.moveTo(p.x,p.y)); ctx.stroke(); } else if (shape.type === 'line') { ctx.beginPath(); ctx.moveTo(shape.a.x,shape.a.y); ctx.lineTo(shape.b.x,shape.b.y); ctx.stroke(); } else if (shape.type === 'rect') { ctx.strokeRect(shape.a.x,shape.a.y,shape.b.x-shape.a.x,shape.b.y-shape.a.y); } else if (shape.type === 'circle') { ctx.beginPath(); ctx.ellipse((shape.a.x+shape.b.x)/2,(shape.a.y+shape.b.y)/2,Math.abs(shape.b.x-shape.a.x)/2,Math.abs(shape.b.y-shape.a.y)/2,0,0,Math.PI*2); ctx.stroke(); } else if (shape.type === 'text') { ctx.font = `${Math.max(15, shape.size * 5)}px Inter`; ctx.fillText(shape.text, shape.a.x, shape.a.y); } ctx.restore(); };
    const render = () => { ctx.clearRect(0,0,canvas.width,canvas.height); ctx.save(); ctx.translate(board.view.x, board.view.y); ctx.scale(board.view.zoom, board.view.zoom); board.shapes.forEach((shape) => renderShape(shape)); if (board.drawing && board.drawing.type !== 'pan') renderShape(board.drawing, true); ctx.restore(); };
    const load = async () => { const url = card.querySelector('[data-drawing-read-url]')?.dataset.drawingReadUrl; if (!url) return; try { const data = await guestJson(url); if (data.drawing?.shapes) { board.shapes = data.drawing.shapes; render(); } } catch (_) {} finally { board.loaded = true; } };
    toolbar.querySelectorAll('[data-board-tool]').forEach((button) => button.addEventListener('click', () => { board.tool = button.dataset.boardTool; toolbar.querySelectorAll('[data-board-tool]').forEach((item) => item.classList.toggle('is-active', item === button)); canvas.style.cursor = board.tool === 'pan' ? 'grab' : 'crosshair'; }));
    toolbar.querySelector('[data-board-color]')?.addEventListener('input', (event) => board.color = event.target.value); toolbar.querySelector('[data-board-size]')?.addEventListener('input', (event) => board.size = Number(event.target.value));
    const drawingPreview = () => {
      const preview = document.createElement('canvas'); const maxWidth = 1200;
      const scale = Math.min(1, maxWidth / canvas.width); preview.width = Math.max(1, Math.round(canvas.width * scale)); preview.height = Math.max(1, Math.round(canvas.height * scale));
      const previewContext = preview.getContext('2d'); previewContext.fillStyle = '#ffffff'; previewContext.fillRect(0, 0, preview.width, preview.height); previewContext.drawImage(canvas, 0, 0, preview.width, preview.height);
      return preview.toDataURL('image/jpeg', .88);
    };
    const saveDrawing = async () => { const button = toolbar.querySelector('[data-drawing-url]'); if (!button) return; try { await guestJson(button.dataset.drawingUrl, {method:'POST', body:JSON.stringify({version:2, shapes:board.shapes, dataUrl:drawingPreview()})}); setStatus(card, 'Холст сохранён'); } catch (error) { setStatus(card, error.message); } };
    card._saveDrawing = saveDrawing;
    toolbar.querySelector('[data-board-undo]')?.addEventListener('click', () => { board.shapes.pop(); render(); }); toolbar.querySelector('[data-board-clear]')?.addEventListener('click', () => { board.shapes = []; render(); });
    toolbar.querySelector('[data-drawing-url]')?.addEventListener('click', saveDrawing);
    canvas.addEventListener('pointerdown', (event) => { const p = point(event); canvas.setPointerCapture(event.pointerId); if (board.tool === 'text') { board.shapes.push({type:'text',a:p,text:'Заметка',color:board.color,size:board.size}); render(); return; } if (board.tool === 'pan') { board.drawing = {type:'pan'}; return; } board.drawing = board.tool === 'pen' || board.tool === 'erase' ? {type:'pen',points:[p],color:board.color,size:board.tool === 'erase' ? 22 : board.size,erase:board.tool === 'erase'} : {type:board.tool,a:p,b:p,color:board.color,size:board.size}; });
    canvas.addEventListener('pointermove', (event) => { if (!board.drawing) return; if (board.drawing.type === 'pan') { const rect = canvas.getBoundingClientRect(); board.view.x += event.movementX * canvas.width / rect.width; board.view.y += event.movementY * canvas.height / rect.height; render(); return; } const p = point(event); if (board.drawing.type === 'pen') board.drawing.points.push(p); else board.drawing.b = p; render(); });
    const finish = () => { if (!board.drawing) return; if (board.drawing.type !== 'pan') { board.shapes.push(board.drawing); window.clearTimeout(board.saveTimer); board.saveTimer = window.setTimeout(saveDrawing, 800); } board.drawing = null; render(); };
    canvas.addEventListener('pointerup', finish); canvas.addEventListener('pointercancel', finish); canvas.addEventListener('wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); const x = (event.clientX - rect.left) * canvas.width / rect.width; const y = (event.clientY - rect.top) * canvas.height / rect.height; const before = point(event); const zoom = Math.max(.35, Math.min(3, board.view.zoom * (event.deltaY > 0 ? .9 : 1.1))); board.view.zoom = zoom; board.view.x = x - before.x * zoom; board.view.y = y - before.y * zoom; render(); }, {passive:false}); resize(); new ResizeObserver(resize).observe(canvas); load();
  }

  guestJson(root.dataset.stateUrl).then((snapshot) => {
    (snapshot.responses || []).forEach((response) => {
      const card = cards.find((item) => String(item.dataset.task) === String(response.task_id));
      if (!card) return;
      card._attachments = response.attachments || [];
      card._renderPhotos?.();
      const f = fields(card);
      const radio = [...card.querySelectorAll('input[type=radio]')].find((item) => item.value === response.answer_text);
      if (radio) radio.checked = true;
      if (f.answer) f.answer.value = response.answer_text || '';
      if (f.comment) f.comment.value = response.comment || '';
      if (f.code && response.answer_json?.workspace_code) {
        f.code.value = response.answer_json.workspace_code;
        renderCodeEditor(card);
      }
      if (f.flag) f.flag.setAttribute('aria-pressed', String(Boolean(response.flagged)));
      const hasPhotos = (card._attachments || []).length > 0;
      card.dataset.done = (response.answer_text || hasPhotos) ? '1' : '0';
      card.dataset.draft = !response.answer_text && (response.comment || response.answer_json?.workspace_code || hasPhotos) ? '1' : '0';
    });
    updateProgress();
    initBoard(activeCard);
    renderMath(root);
    highlightConditionCode(root);
  }).catch(() => {
    initBoard(activeCard);
    renderMath(root);
    highlightConditionCode(root);
  });

  // Modal dialog close events
  document.querySelector('#photo-modal-close')?.addEventListener('click', () => {
    document.querySelector('#photo-viewer-modal')?.close();
  });
  document.querySelector('#photo-viewer-modal')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.close();
  });

  // Run renderMath and syntax highlighting when DOM or KaTeX is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { renderMath(root); highlightConditionCode(root); });
  } else {
    renderMath(root);
    highlightConditionCode(root);
  }

  guestJson(root.dataset.presenceUrl, {method:'POST', body:'{}'}).catch(() => {});
  setInterval(() => guestJson(root.dataset.presenceUrl, {method:'POST', body:'{}'}).catch(() => {}), 60000);
  let force = false;
  const modal = document.querySelector('#submit-modal');
  const submit = async () => {
    try {
      const result = await guestJson(config.submitUrl, {method:'POST', body:JSON.stringify(force ? {force:true} : {})});
      location.href = result.result_url;
    } catch (error) {
      if (error.message.includes('Заполните') && !force) {
        force = true;
        document.querySelector('#submit-modal-title').textContent = 'Есть незаполненные задания';
        document.querySelector('#submit-modal-text').textContent = 'Сдать работу с пропусками?';
        modal.showModal();
      }
    }
  };
  document.querySelector('#submit').addEventListener('click', () => {
    force = false;
    document.querySelector('#submit-modal-title').textContent = 'Сдать работу?';
    document.querySelector('#submit-modal-text').textContent = 'После сдачи ответы нельзя будет изменить.';
    modal.showModal();
  });
  document.querySelector('#submit-cancel').addEventListener('click', () => modal.close());
  document.querySelector('#submit-confirm').addEventListener('click', () => { modal.close(); submit(); });
})();
