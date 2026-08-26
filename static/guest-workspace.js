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
    document.querySelector('#progress-label').textContent = `${done} / ${cards.length}`;
    document.querySelector('#progress-bar').style.width = `${cards.length ? done / cards.length * 100 : 0}%`;
    const current = cards.find((card) => card.dataset.done !== '1');
    document.querySelector('#phase-label').textContent = current ? (phaseNames[current.dataset.phase] || 'Практика') : 'Все задания готовы к сдаче';
    switches.forEach((button) => {
      const card = cards.find((item) => String(item.dataset.task) === button.dataset.taskTarget);
      button.classList.toggle('is-filled', card?.dataset.done === '1');
      button.classList.toggle('is-draft', card?.dataset.draft === '1' && card?.dataset.done !== '1');
    });
  };
  const save = async (card, silent = false) => {
    if (!card || card.dataset.saving === '1') return;
    const button = card.querySelector('[data-save-url]'); if (!button) return;
    card.dataset.saving = '1';
    try {
      await guestJson(button.dataset.saveUrl, {method:'POST', body:JSON.stringify(payload(card))});
      const p = payload(card); card.dataset.done = p.answer_text ? '1' : '0'; card.dataset.draft = !p.answer_text && (p.comment || p.answer_json?.workspace_code) ? '1' : '0';
      if (!silent) setStatus(card, 'Сохранено'); updateProgress();
    } catch (error) { setStatus(card, error.message); }
    finally { delete card.dataset.saving; }
  };
  const activate = async (id) => {
    const next = cards.find((card) => String(card.dataset.task) === String(id));
    if (!next || next === activeCard) return;
    await save(activeCard, true);
    activeCard.hidden = true; next.hidden = false; activeCard = next;
    switches.forEach((button) => button.setAttribute('aria-selected', String(button.dataset.taskTarget === String(id))));
    initBoard(next); next.scrollIntoView({behavior:'smooth', block:'start'});
  };
  switches.forEach((button) => button.addEventListener('click', () => activate(button.dataset.taskTarget)));

  const escapeHtml = (value) => value.replace(/[&<>]/g, (symbol) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[symbol]));
  const paintPython = (code) => escapeHtml(code || ' ').replace(/(#[^\n]*|(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(?:and|as|assert|break|class|continue|def|elif|else|except|False|finally|for|from|if|import|in|is|lambda|None|not|or|pass|raise|return|True|try|while|with|yield)\b|\b(?:print|input|len|range|sum|min|max|sorted|enumerate|zip|int|str|float|list|dict|set)\b|\b\d+(?:\.\d+)?\b)/g, (token) => {
    const type = token.startsWith('#') ? 'comment' : /^["']/.test(token) ? 'string' : /^\d/.test(token) ? 'number' : /^(print|input|len|range|sum|min|max|sorted|enumerate|zip|int|str|float|list|dict|set)$/.test(token) ? 'builtin' : 'keyword';
    return `<span class="guest-token-${type}">${token}</span>`;
  });
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
    card.querySelectorAll('[data-tool-tab]').forEach((button) => button.addEventListener('click', () => {
      card.querySelectorAll('[data-tool-tab]').forEach((item) => item.classList.toggle('is-active', item === button));
      card.querySelectorAll('[data-tool-pane]').forEach((item) => item.classList.toggle('is-active', item.dataset.toolPane === button.dataset.toolTab));
      if (button.dataset.toolTab === 'board') initBoard(card);
    }));
    card.querySelector('[data-flag-toggle]')?.addEventListener('click', (event) => { const button = event.currentTarget; button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true')); save(card, true); });
    card.querySelectorAll('input, textarea').forEach((field) => { let timer; field.addEventListener(field.type === 'radio' ? 'change' : 'input', () => { clearTimeout(timer); timer = setTimeout(() => save(card, true), 800); }); });
    card.querySelector('[data-save-url]')?.addEventListener('click', () => save(card));
    card.querySelector('[data-prev-task]')?.addEventListener('click', () => activate(cards[Math.max(0, index - 1)].dataset.task));
    card.querySelector('[data-next-task]')?.addEventListener('click', () => activate(cards[Math.min(cards.length - 1, index + 1)].dataset.task));
    card.querySelector('[data-run-url]')?.addEventListener('click', async (event) => {
      const code = card.querySelector('[data-code]').value; const output = card.querySelector('[data-code-output]');
      output.textContent = 'Запуск…'; output.classList.remove('is-error');
      try { const result = await guestJson(event.currentTarget.dataset.runUrl, {method:'POST', body:JSON.stringify({code})}); output.textContent = result.stderr || result.stdout || 'Код выполнен без вывода.'; output.classList.toggle('is-error', Boolean(result.stderr)); if (result.turtle_image_b64) output.textContent += '\n\n[turtle] Рисунок сформирован.'; }
      catch (error) { output.textContent = error.message; output.classList.add('is-error'); }
    });
    const uploadFiles = async () => {
      const input = card.querySelector('[data-file]'); const note = card.querySelector('[data-file-state]'); const button = card.querySelector('[data-upload-url]'); if (!input?.files.length || !button) { if (note) note.textContent = 'Выберите файл'; return; }
      const body = new FormData(); [...input.files].forEach((file) => body.append('file', file)); note.textContent = 'Сохраняем файлы…';
      try { const result = await guestJson(button.dataset.uploadUrl, {method:'POST', body}); note.textContent = `Файлов сохранено: ${(result.files || []).length}`; input.value = ''; } catch (error) { note.textContent = error.message; }
    };
    card._uploadFiles = uploadFiles;
    card.querySelector('[data-file-select]')?.addEventListener('click', () => card.querySelector('[data-file]')?.click());
    card.querySelector('[data-file]')?.addEventListener('change', (event) => { const note = card.querySelector('[data-file-state]'); const count = event.currentTarget.files.length; if (note) note.textContent = count ? `Выбрано файлов: ${count}` : 'Файлы не выбраны'; if (count) uploadFiles(); });
    card.querySelector('[data-upload-url]')?.addEventListener('click', uploadFiles);
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
    const saveDrawing = async () => { const button = toolbar.querySelector('[data-drawing-url]'); if (!button) return; try { await guestJson(button.dataset.drawingUrl, {method:'POST', body:JSON.stringify({version:2, shapes:board.shapes})}); setStatus(card, 'Холст сохранён'); } catch (error) { setStatus(card, error.message); } };
    card._saveDrawing = saveDrawing;
    toolbar.querySelector('[data-board-undo]')?.addEventListener('click', () => { board.shapes.pop(); render(); }); toolbar.querySelector('[data-board-clear]')?.addEventListener('click', () => { board.shapes = []; render(); });
    toolbar.querySelector('[data-drawing-url]')?.addEventListener('click', saveDrawing);
    canvas.addEventListener('pointerdown', (event) => { const p = point(event); canvas.setPointerCapture(event.pointerId); if (board.tool === 'text') { board.shapes.push({type:'text',a:p,text:'Заметка',color:board.color,size:board.size}); render(); return; } if (board.tool === 'pan') { board.drawing = {type:'pan'}; return; } board.drawing = board.tool === 'pen' || board.tool === 'erase' ? {type:'pen',points:[p],color:board.color,size:board.tool === 'erase' ? 22 : board.size,erase:board.tool === 'erase'} : {type:board.tool,a:p,b:p,color:board.color,size:board.size}; });
    canvas.addEventListener('pointermove', (event) => { if (!board.drawing) return; if (board.drawing.type === 'pan') { const rect = canvas.getBoundingClientRect(); board.view.x += event.movementX * canvas.width / rect.width; board.view.y += event.movementY * canvas.height / rect.height; render(); return; } const p = point(event); if (board.drawing.type === 'pen') board.drawing.points.push(p); else board.drawing.b = p; render(); });
    const finish = () => { if (!board.drawing) return; if (board.drawing.type !== 'pan') { board.shapes.push(board.drawing); window.clearTimeout(board.saveTimer); board.saveTimer = window.setTimeout(saveDrawing, 800); } board.drawing = null; render(); };
    canvas.addEventListener('pointerup', finish); canvas.addEventListener('pointercancel', finish); canvas.addEventListener('wheel', (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); const x = (event.clientX - rect.left) * canvas.width / rect.width; const y = (event.clientY - rect.top) * canvas.height / rect.height; const before = point(event); const zoom = Math.max(.35, Math.min(3, board.view.zoom * (event.deltaY > 0 ? .9 : 1.1))); board.view.zoom = zoom; board.view.x = x - before.x * zoom; board.view.y = y - before.y * zoom; render(); }, {passive:false}); resize(); new ResizeObserver(resize).observe(canvas); load();
  }

  guestJson(root.dataset.stateUrl).then((snapshot) => {
    (snapshot.responses || []).forEach((response) => { const card = cards.find((item) => String(item.dataset.task) === String(response.task_id)); if (!card) return; const f = fields(card); const radio = [...card.querySelectorAll('input[type=radio]')].find((item) => item.value === response.answer_text); if (radio) radio.checked = true; if (f.answer) f.answer.value = response.answer_text || ''; if (f.comment) f.comment.value = response.comment || ''; if (f.code && response.answer_json?.workspace_code) { f.code.value = response.answer_json.workspace_code; renderCodeEditor(card); } if (f.flag) f.flag.setAttribute('aria-pressed', String(Boolean(response.flagged))); card.dataset.done = response.answer_text ? '1' : '0'; card.dataset.draft = !response.answer_text && (response.comment || response.answer_json?.workspace_code) ? '1' : '0'; }); updateProgress(); initBoard(activeCard);
  }).catch(() => initBoard(activeCard));
  guestJson(root.dataset.presenceUrl, {method:'POST', body:'{}'}).catch(() => {}); setInterval(() => guestJson(root.dataset.presenceUrl, {method:'POST', body:'{}'}).catch(() => {}), 60000);
  let force = false; const modal = document.querySelector('#submit-modal'); const submit = async () => { try { const result = await guestJson(config.submitUrl, {method:'POST', body:JSON.stringify(force ? {force:true} : {})}); location.href = result.result_url; } catch (error) { if (error.message.includes('Заполните') && !force) { force = true; document.querySelector('#submit-modal-title').textContent = 'Есть незаполненные задания'; document.querySelector('#submit-modal-text').textContent = 'Сдать работу с пропусками?'; modal.showModal(); } } };
  document.querySelector('#submit').addEventListener('click', () => { force = false; document.querySelector('#submit-modal-title').textContent = 'Сдать работу?'; document.querySelector('#submit-modal-text').textContent = 'После сдачи ответы нельзя будет изменить.'; modal.showModal(); }); document.querySelector('#submit-cancel').addEventListener('click', () => modal.close()); document.querySelector('#submit-confirm').addEventListener('click', () => { modal.close(); submit(); });
})();
