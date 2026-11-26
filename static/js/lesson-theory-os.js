(() => {
  const root = document.getElementById('lesson-theory-os');
  if (!root) return;
  const lessonId = Number(root.dataset.lessonId);
  const teacher = root.dataset.role === 'teacher';
  const api = `/lesson/${lessonId}/studio/theory-os`;
  const $ = (selector) => root.querySelector(selector);
  const status = $('#theory-os-status');
  let snapshot = null;
  let localId = null;
  let previewId = null;
  let preview = null;
  let libraryMode = false;
  let refreshing = false;
  let refreshAgain = false;
  let selectedAnchor = null;
  let localSelectionTimer = null;
  let localSelectionSentAt = 0;
  let localSelectionSeq = 0;
  let lastLocalSelectionKey = '';
  let localSelectionRestore = null;
  let suppressLocalSelectionEvents = false;
  let remoteSelection = null;
  const remoteSelectionSequences = new Map();
  const selectionClientId = window.crypto?.randomUUID?.() || `theory-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  let lastReadingKey = '';

  async function request(body, url = api) {
    const response = await fetch(url, body ? {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' },
      body: JSON.stringify(body),
    } : {});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.success) throw new Error(result.error || 'Не удалось обновить теорию');
    return result;
  }

  function button(label, action, className = '') {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = label;
    node.className = className;
    node.addEventListener('click', action);
    return node;
  }

  function setMode(isLibrary) {
    if (!teacher) return;
    libraryMode = isLibrary;
    $('#theory-os-collection-panel').classList.toggle('hidden', isLibrary);
    $('#theory-os-library-panel').classList.toggle('hidden', !isLibrary);
    for (const [id, active] of [['#theory-os-tab-collection', !isLibrary], ['#theory-os-tab-library', isLibrary]]) {
      const tab = $(id);
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
    }
    renderReading();
  }

  function renderLibrary() {
    if (!teacher || !snapshot) return;
    const list = $('#theory-os-library-results');
    const query = $('#theory-os-library-search').value.trim().toLocaleLowerCase();
    list.replaceChildren();
    const matches = snapshot.library.filter(item => item.title.toLocaleLowerCase().includes(query)
      || item.sections.some(section => section.title.toLocaleLowerCase().includes(query)));
    if (!matches.length) {
      const empty = document.createElement('p');
      empty.className = 'theory-os-empty';
      empty.textContent = 'Материал не найден. Попробуйте другое название.';
      list.appendChild(empty);
    }
    matches.forEach(item => {
      const entry = button(item.title, () => openPreview(item.id), 'theory-os-library-item');
      entry.classList.toggle('is-active', String(previewId) === String(item.id));
      entry.setAttribute('role', 'option');
      entry.setAttribute('aria-selected', String(String(previewId) === String(item.id)));
      const count = document.createElement('small');
      count.textContent = `${item.sections.length} разделов`;
      entry.appendChild(count);
      list.appendChild(entry);
    });
  }

  async function openPreview(id) {
    previewId = id;
    status.textContent = 'Открываем материал…';
    try {
      preview = await request(null, `${api}?preview_block_id=${encodeURIComponent(id)}`);
      setMode(true);
      renderLibrary();
      renderReading();
      status.textContent = 'Предпросмотр';
    } catch (error) { status.textContent = error.message; }
  }

  function renderPresets() {
    const list = $('#theory-os-preset-list');
    if (!list || list.classList.contains('hidden')) return;
    list.replaceChildren();
    const form = document.createElement('div');
    form.className = 'theory-os-preset-form';
    const input = document.createElement('input');
    input.placeholder = 'Название подборки';
    input.maxLength = 100;
    input.setAttribute('aria-label', 'Название подборки');
    form.append(input, button('Сохранить', () => {
      if (input.value.trim()) mutate({ action: 'save_preset', name: input.value.trim() });
    }, 'is-primary'));
    list.appendChild(form);
    (snapshot.presets || []).forEach(item => list.appendChild(button(item.name, () => {
      mutate({ action: 'load_preset', preset_id: item.id });
      list.classList.add('hidden');
    }, 'theory-os-preset-item')));
  }

  function renderCollection() {
    if (!snapshot) return;
    const nav = $('#theory-os-fragments');
    nav.replaceChildren();
    const count = $('#theory-os-collection-count');
    if (count) count.textContent = `${snapshot.fragments.length} фрагментов`;
    if (!snapshot.fragments.length) {
      const empty = document.createElement('p');
      empty.className = 'theory-os-empty';
      empty.textContent = teacher ? 'Подборка пуста. Откройте библиотеку и добавьте материал.' : 'Преподаватель пока не открыл материал.';
      nav.appendChild(empty);
    }
    snapshot.fragments.forEach((fragment, index) => {
      const row = document.createElement('article');
      row.className = `theory-os-fragment${fragment.id === localId ? ' is-active' : ''}${fragment.revealed ? ' is-revealed' : ''}`;
      row.dataset.fragmentId = fragment.id;
      if (teacher) {
        row.draggable = true;
        row.addEventListener('dragstart', event => event.dataTransfer.setData('text/plain', fragment.id));
        row.addEventListener('dragover', event => event.preventDefault());
        row.addEventListener('drop', event => {
          event.preventDefault();
          const dragged = event.dataTransfer.getData('text/plain');
          if (dragged && dragged !== fragment.id) mutate({ action: 'move', fragment_id: dragged, target_index: index });
        });
      }
      const heading = document.createElement('div');
      heading.className = 'theory-os-fragment-heading';
      const title = button(fragment.title, () => {
        localId = fragment.id;
        if (teacher) mutate({ action: 'open', fragment_id: fragment.id });
        else { renderCollection(); renderReading(); }
      }, 'theory-os-fragment-title');
      heading.appendChild(title);
      if (teacher) {
        heading.appendChild(button(fragment.revealed ? 'Открыто' : 'Раскрыть', () => mutate({
          action: 'reveal', fragment_id: fragment.id, revealed: !fragment.revealed,
        }), `theory-os-reveal${fragment.revealed ? ' is-revealed' : ''}`));
      }
      const meta = document.createElement('small');
      meta.textContent = `${fragment.source_title} · ${fragment.revealed ? 'видно ученику' : 'пока скрыто'}`;
      row.append(heading, meta);
      if (teacher) {
        const actions = document.createElement('details');
        actions.className = 'theory-os-fragment-menu';
        const trigger = document.createElement('summary');
        trigger.textContent = 'Действия';
        actions.appendChild(trigger);
        actions.append(
          button('Выше', () => mutate({ action: 'move', fragment_id: fragment.id, direction: 'up' })),
          button('Ниже', () => mutate({ action: 'move', fragment_id: fragment.id, direction: 'down' })),
          button(fragment.revealed ? 'Скрыть от ученика' : 'Открыть ученику', () => mutate({ action: 'reveal', fragment_id: fragment.id, revealed: !fragment.revealed })),
          button('Убрать из урока', () => mutate({ action: 'remove', fragment_id: fragment.id })),
        );
        row.appendChild(actions);
      }
      nav.appendChild(row);
    });
  }

  function getTheoryTextRoot(rootNode = $('#theory-os-reading')) {
    return rootNode?.querySelector('.theory-os-content') || rootNode;
  }

  function getTextIndex(rootNode) {
    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let text = '';
    while (walker.nextNode()) {
      const node = walker.currentNode;
      nodes.push({ node, start: text.length, end: text.length + node.textContent.length });
      text += node.textContent;
    }
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return { nodes, text, fingerprint: `${text.length}:${(hash >>> 0).toString(16)}` };
  }

  function locateRangeByOffsets(rootNode, start, end, expectedFingerprint) {
    if (!rootNode || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null;
    const index = getTextIndex(rootNode);
    if (end > index.text.length || (expectedFingerprint && expectedFingerprint !== index.fingerprint)) return null;
    const pointAt = (offset) => {
      const item = index.nodes.find(node => offset <= node.end && offset >= node.start);
      if (!item) return null;
      return [item.node, Math.max(0, Math.min(item.node.textContent.length, offset - item.start))];
    };
    const from = pointAt(start);
    const to = pointAt(end);
    if (!from || !to) return null;
    const range = document.createRange();
    range.setStart(from[0], from[1]);
    range.setEnd(to[0], to[1]);
    return range;
  }

  function rangeOffsets(rootNode, range) {
    const offsetAt = (node, offset) => {
      const prefix = document.createRange();
      prefix.selectNodeContents(rootNode);
      prefix.setEnd(node, offset);
      return prefix.toString().length;
    };
    return {
      start: offsetAt(range.startContainer, range.startOffset),
      end: offsetAt(range.endContainer, range.endOffset),
    };
  }

  function locateRange(quote, prefix = '', suffix = '') {
    const rootNode = getTheoryTextRoot();
    const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let text = '';
    while (walker.nextNode()) {
      nodes.push({ node: walker.currentNode, start: text.length });
      text += walker.currentNode.textContent;
    }
    let offset = -1;
    while ((offset = text.indexOf(quote, offset + 1)) !== -1) {
      if (prefix && !text.slice(Math.max(0, offset - prefix.length), offset).endsWith(prefix)) continue;
      if (suffix && !text.slice(offset + quote.length).startsWith(suffix)) continue;
      const first = [...nodes].reverse().find(item => item.start <= offset);
      const last = [...nodes].reverse().find(item => item.start < offset + quote.length);
      if (!first || !last) return null;
      const range = document.createRange();
      range.setStart(first.node, offset - first.start);
      range.setEnd(last.node, offset + quote.length - last.start);
      return range;
    }
    return null;
  }

  function renderHighlights(current) {
    CSS.highlights?.delete('boostudy-theory-focus');
    CSS.highlights?.delete('boostudy-theory-annotation');
    if (!window.Highlight || !CSS.highlights) return;
    const ranges = (current?.highlights || []).map(item => locateRange(item.quote, item.prefix, item.suffix)).filter(Boolean);
    if (ranges.length) CSS.highlights.set('boostudy-theory-annotation', new Highlight(...ranges));
    const focus = snapshot?.focus;
    const banner = $('#theory-os-focus');
    if (!focus || focus.fragment_id !== localId) { banner.classList.add('hidden'); return; }
    banner.textContent = focus.quote ? `${focus.author || 'Преподаватель'} показывает: «${focus.quote}»` : 'Преподаватель показывает этот фрагмент';
    banner.classList.remove('hidden');
    const range = focus.quote && locateRange(focus.quote);
    if (range) {
      CSS.highlights.set('boostudy-theory-focus', new Highlight(range));
      if (!teacher && snapshot.follow) range.startContainer.parentElement?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function clearRemoteSelection() {
    CSS.highlights?.delete('boostudy-theory-remote-selection');
  }

  function renderRemoteSelection() {
    clearRemoteSelection();
    if (!remoteSelection || libraryMode || String(remoteSelection.fragment_id) !== String(localId)) return;
    const rootNode = getTheoryTextRoot();
    const range = Number.isInteger(remoteSelection.selection_start) && Number.isInteger(remoteSelection.selection_end)
      ? locateRangeByOffsets(rootNode, remoteSelection.selection_start, remoteSelection.selection_end, remoteSelection.text_fingerprint)
      : locateRange(remoteSelection.quote || '', remoteSelection.prefix, remoteSelection.suffix);
    if (!range) return;
    if (window.Highlight && CSS.highlights) CSS.highlights.set('boostudy-theory-remote-selection', new Highlight(range));
  }

  function applyRemoteSelection(payload) {
    const clientId = String(payload.client_id || payload.sender_id || payload.author_role || 'peer');
    const sequence = Number(payload.seq) || 0;
    if (sequence && sequence <= (remoteSelectionSequences.get(clientId) || 0)) return;
    if (sequence) remoteSelectionSequences.set(clientId, sequence);
    if (payload.clear) {
      if (!remoteSelection || clientId === String(remoteSelection.client_id || remoteSelection.sender_id || remoteSelection.author_role || 'peer')) {
        remoteSelection = null;
        clearRemoteSelection();
      }
      return;
    }
    remoteSelection = payload;
    renderRemoteSelection();
  }

  function clearLocalSelection() {
    if (!lastLocalSelectionKey) return;
    const fragmentId = selectedAnchor?.fragment_id || localId;
    lastLocalSelectionKey = '';
    selectedAnchor = null;
    window.boostudyLessonControl?.sendUi?.({
      kind: 'text_selection', surface: 'theory', fragment_id: String(fragmentId || ''),
      clear: true, client_id: selectionClientId, seq: ++localSelectionSeq,
    });
  }

  function syncReadingSupplements(reading, current) {
    reading.querySelectorAll(':scope > .theory-os-explanation, :scope > .theory-os-annotation, :scope > .theory-os-comment').forEach(node => node.remove());
    const content = reading.querySelector('.theory-os-content');
    if (!content || !current) return;
    let after = content;
    if (current.explanation) {
      const note = document.createElement('aside');
      note.className = 'theory-os-explanation';
      note.textContent = current.explanation;
      after.after(note);
      after = note;
    }
    if (current.annotation) {
      const note = document.createElement('p');
      note.className = 'theory-os-annotation';
      note.textContent = `Пометка преподавателя: ${current.annotation}`;
      after.after(note);
      after = note;
    }
    (current.highlights || []).filter(item => item.comment).forEach(item => {
      const note = document.createElement('aside');
      note.className = 'theory-os-comment';
      note.textContent = `${item.author}: «${item.quote}» — ${item.comment}`;
      after.after(note);
      after = note;
    });
  }

  function captureLocalSelectionForRender(reading) {
    const content = getTheoryTextRoot(reading);
    const selection = window.getSelection();
    if (!selection?.rangeCount || selection.isCollapsed || !content?.contains(selection.anchorNode) || !content.contains(selection.focusNode)) return null;
    const range = selection.getRangeAt(0);
    const offsets = rangeOffsets(content, range);
    const index = getTextIndex(content);
    return {
      fragment_id: String(localId || ''),
      start: offsets.start,
      end: offsets.end,
      fingerprint: index.fingerprint,
      quote: range.toString(),
      prefix: index.text.slice(Math.max(0, offsets.start - 64), offsets.start),
      suffix: index.text.slice(offsets.end, offsets.end + 64),
    };
  }

  function restoreLocalSelectionAfterRender() {
    const saved = localSelectionRestore;
    localSelectionRestore = null;
    if (!saved || saved.fragment_id !== String(localId || '')) return;
    const content = getTheoryTextRoot();
    const index = getTextIndex(content);
    const range = saved.fingerprint === index.fingerprint
      ? locateRangeByOffsets(content, saved.start, saved.end, saved.fingerprint)
      : locateRange(saved.quote, saved.prefix, saved.suffix);
    if (!range) return;
    suppressLocalSelectionEvents = true;
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const offsets = rangeOffsets(content, range);
    selectedAnchor = {
      quote: range.toString(),
      prefix: index.text.slice(Math.max(0, offsets.start - 64), offsets.start),
      suffix: index.text.slice(offsets.end, offsets.end + 64),
      fragment_id: String(localId || ''),
      selection_start: offsets.start,
      selection_end: offsets.end,
      text_fingerprint: index.fingerprint,
    };
    lastLocalSelectionKey = `${selectedAnchor.fragment_id}:${offsets.start}:${offsets.end}:${index.fingerprint}`;
    setTimeout(() => { suppressLocalSelectionEvents = false; }, 0);
    queueLocalSelection();
  }

  function renderReading() {
    if (!snapshot) return;
    const reading = $('#theory-os-reading');
    const previewing = teacher && libraryMode && preview;
    $('#theory-os-preview-banner')?.classList.toggle('hidden', !previewing);
    $('#theory-os-preview-actions')?.classList.toggle('hidden', !previewing);
    const current = snapshot.fragments.find(item => item.id === localId);
    const key = previewing ? `preview:${previewId}` : `${localId}:${current?.html || ''}`;
    if (key !== lastReadingKey) {
      localSelectionRestore = captureLocalSelectionForRender(reading);
      const scroll = reading.parentElement.scrollTop;
      reading.replaceChildren();
      if (previewing) {
        preview.sections.forEach(section => {
          const part = document.createElement('section');
          part.className = 'theory-os-preview-section';
          part.innerHTML = section.html;
          reading.appendChild(part);
        });
        const actions = $('#theory-os-preview-actions');
        actions.replaceChildren();
        preview.sections.forEach((section, index) => {
          const row = document.createElement('div');
          row.className = 'theory-os-preview-section-action';
          const label = document.createElement('strong');
          label.textContent = section.title;
          row.append(label, button('Добавить раздел', () => mutate({ action: 'add', block_id: previewId, section_index: index }), 'is-primary'));
          const blocks = snapshot.library.find(item => String(item.id) === String(previewId))?.sections[index]?.blocks || [];
          if (blocks.length > 1) {
            const chooser = document.createElement('details');
            chooser.className = 'theory-os-block-chooser';
            const summary = document.createElement('summary');
            summary.textContent = 'Отдельные блоки';
            chooser.appendChild(summary);
            blocks.forEach(block => chooser.appendChild(button(block.title, () => mutate({
              action: 'add', block_id: previewId, section_index: index, block_index: block.index,
            }))));
            row.appendChild(chooser);
          }
          actions.appendChild(row);
        });
      } else if (current) {
        const body = document.createElement('div');
        body.className = 'theory-os-content';
        body.innerHTML = current.html;
        reading.appendChild(body);
      } else reading.textContent = teacher ? 'Выберите фрагмент или откройте библиотеку.' : 'Пока нет открытого материала.';
      reading.parentElement.scrollTop = scroll;
      lastReadingKey = key;
      if (current && !previewing) {
        syncReadingSupplements(reading, current);
        restoreLocalSelectionAfterRender();
      }
    } else if (current && !previewing) {
      syncReadingSupplements(reading, current);
    }
    if (teacher) {
      $('#theory-os-follow').checked = Boolean(snapshot.follow);
      $('#theory-os-explanation').value = current?.explanation || '';
      $('#theory-os-annotation').value = current?.annotation || '';
      $('#theory-os-explanation').disabled = !current;
      $('#theory-os-annotation').disabled = !current;
      const highlights = $('#theory-os-highlight-list');
      highlights.replaceChildren();
      (current?.highlights || []).forEach(item => highlights.appendChild(button(`Убрать: «${item.quote.slice(0, 35)}»`, () => mutate({
        action: 'clear_highlight', fragment_id: current.id, highlight_id: item.id,
      }))));
    } else $('#theory-os-reading-mode').textContent = snapshot.follow ? 'Следование преподавателю' : 'Свободное чтение';
    $('#theory-os-focus').classList.add('hidden');
    if (!previewing) renderHighlights(current);
    renderRemoteSelection();
  }

  function render() {
    if (!snapshot) return;
    if (!snapshot.fragments.some(item => item.id === localId)) localId = snapshot.fragments.find(item => item.id === snapshot.active_id)?.id || snapshot.fragments[0]?.id || null;
    renderCollection();
    renderLibrary();
    renderPresets();
    renderReading();
  }

  async function refresh() {
    if (refreshing) { refreshAgain = true; return; }
    refreshing = true;
    try {
      snapshot = await request();
      if (!teacher && snapshot.follow) localId = snapshot.active_id;
      if (!teacher && snapshot.focus?.fragment_id) localId = snapshot.focus.fragment_id;
      render();
      status.textContent = snapshot.follow ? 'Синхронизировано · следование' : 'Синхронизировано';
    } catch (error) { status.textContent = error.message; }
    finally { refreshing = false; if (refreshAgain) { refreshAgain = false; refresh(); } }
  }

  async function mutate(body) {
    status.textContent = 'Сохраняем…';
    try {
      snapshot = await request(body);
      if (body.action === 'add' || body.action === 'add_article' || body.action === 'load_preset') {
        localId = snapshot.fragments.at(-1)?.id || null;
        preview = null;
        setMode(false);
      }
      if (body.action === 'open') localId = body.fragment_id;
      render();
      status.textContent = 'Сохранено';
    } catch (error) { status.textContent = error.message; }
  }

  function captureSelection() {
    const selection = window.getSelection();
    const quote = selection?.toString() || '';
    const reading = getTheoryTextRoot();
    const current = snapshot?.fragments.find(item => String(item.id) === String(localId));
    if (!quote.trim() || !selection?.rangeCount || !reading.contains(selection.anchorNode) || !reading.contains(selection.focusNode)
      || libraryMode || !current || (teacher && !current.revealed)) {
      clearLocalSelection();
      return;
    }
    const range = selection.getRangeAt(0);
    const offsets = rangeOffsets(reading, range);
    const index = getTextIndex(reading);
    const anchor = {
      quote,
      prefix: index.text.slice(Math.max(0, offsets.start - 64), offsets.start),
      suffix: index.text.slice(offsets.end, offsets.end + 64),
      fragment_id: String(localId),
      selection_start: offsets.start,
      selection_end: offsets.end,
      text_fingerprint: index.fingerprint,
    };
    const key = `${anchor.fragment_id}:${offsets.start}:${offsets.end}:${index.fingerprint}`;
    if (key === lastLocalSelectionKey) return;
    selectedAnchor = anchor;
    lastLocalSelectionKey = key;
    window.boostudyLessonControl?.sendUi?.({
      kind: 'text_selection', surface: 'theory', client_id: selectionClientId,
      seq: ++localSelectionSeq, fragment_id: anchor.fragment_id,
      selection_start: offsets.start, selection_end: offsets.end,
      text_fingerprint: index.fingerprint,
    });
  }

  function queueLocalSelection() {
    if (localSelectionTimer) return;
    const wait = Math.max(0, 36 - (performance.now() - localSelectionSentAt));
    localSelectionTimer = setTimeout(() => {
      localSelectionTimer = null;
      captureSelection();
      localSelectionSentAt = performance.now();
    }, wait);
  }

  if (teacher) {
    $('#theory-os-tab-collection').addEventListener('click', () => setMode(false));
    $('#theory-os-tab-library').addEventListener('click', () => setMode(true));
    $('#theory-os-library-search').addEventListener('input', renderLibrary);
    $('#theory-os-add-article').addEventListener('click', () => previewId && mutate({ action: 'add_article', block_id: previewId }));
    $('#theory-os-save-preset').addEventListener('click', () => {
      const list = $('#theory-os-preset-list');
      list.classList.remove('hidden');
      renderPresets();
      list.querySelector('input')?.focus();
    });
    $('#theory-os-open-presets').addEventListener('click', () => {
      $('#theory-os-preset-list').classList.toggle('hidden');
      renderPresets();
    });
    $('#theory-os-follow').addEventListener('change', event => mutate({ action: 'follow', enabled: event.target.checked }));
    $('#theory-os-explanation').addEventListener('change', event => localId && mutate({ action: 'explanation', fragment_id: localId, text: event.target.value }));
    $('#theory-os-annotation').addEventListener('change', event => localId && mutate({ action: 'annotation', fragment_id: localId, text: event.target.value }));
    $('#theory-os-save-comment').addEventListener('click', () => {
      const comment = $('#theory-os-comment-input').value.trim();
      if (!selectedAnchor || !localId || !comment) return;
      mutate({ action: 'highlight', fragment_id: localId, ...selectedAnchor, comment });
      $('#theory-os-comment-input').value = '';
    });
  }
  document.addEventListener('selectionchange', () => {
    if (suppressLocalSelectionEvents) return;
    const reading = $('#theory-os-reading');
    const selection = window.getSelection();
    if (selection?.rangeCount && !selection.isCollapsed && reading.contains(selection.anchorNode) && reading.contains(selection.focusNode)) {
      if (!localSelectionTimer) queueLocalSelection();
    } else if (lastLocalSelectionKey && !localSelectionTimer) queueLocalSelection();
  });
  window.addEventListener('boostudy:text-selection', event => {
    if (event.detail?.surface === 'theory') applyRemoteSelection(event.detail);
  });
  window.addEventListener('boostudy:studio-updated', event => {
    if (Number(event.detail?.lesson_id) === lessonId) refresh();
  });
  refresh();
})();
