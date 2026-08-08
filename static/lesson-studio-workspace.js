(() => {
  const root = document.querySelector('#lesson-studio');
  if (!root || !window.io) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const clientId = crypto.randomUUID();
  let activeContext = null;
  let socket = null;
  let version = 0;
  let applyingRemote = false;
  let followStudent = false;
  const $ = (selector) => document.querySelector(selector);
  const lessonId = Number(root.dataset.lessonId);
  const teacher = root.dataset.teacher === 'true';
  if (teacher && !$('#sync-student')) {
    const finish = $('#finish-lesson');
    const button = document.createElement('button');
    button.id = 'sync-student'; button.type = 'button';
    button.className = 'studio-btn studio-btn-quiet';
    button.textContent = 'Вести ученика';
    finish?.before(button);
  }

  function syncStudio(patch) {
    return fetch(`/lesson/${lessonId}/studio/state`, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify(patch)}).then(r => r.json());
  }
  const studioSocket = io('/lesson');
  const globalLaser = document.createElement('div');
  globalLaser.className = 'lesson-global-laser';
  globalLaser.hidden = true;
  document.body.append(globalLaser);
  const laserStyle = document.createElement('style');
  laserStyle.textContent = '.lesson-global-laser{position:fixed;z-index:9999;width:16px;height:16px;margin:-8px;border:3px solid #ef4444;border-radius:999px;box-shadow:0 0 18px 7px rgba(239,68,68,.72);pointer-events:none}.lesson-global-laser::after{content:attr(data-name);position:absolute;left:14px;top:12px;white-space:nowrap;background:#172033;color:#fff;border-radius:6px;padding:2px 5px;font:800 10px sans-serif}';
  document.head.append(laserStyle);
  studioSocket.on('connect', () => studioSocket.emit('join_lesson', {lesson_id:lessonId}));
  studioSocket.on('lesson_studio_updated', (payload) => {
    if (payload?.lesson_id !== lessonId || !payload.state?.follow_student || root.dataset.teacher === 'true') return;
    const tab = document.querySelector(`.studio-tab[data-pane="${payload.state.active_pane}"]`);
    tab?.click();
  });
  studioSocket.on('lesson_studio_pointer', (payload) => {
    if (payload?.lesson_id !== lessonId || !payload.pointer) return;
    const p = payload.pointer;
    globalLaser.style.left = `${p.x * window.innerWidth}px`;
    globalLaser.style.top = `${p.y * window.innerHeight}px`;
    globalLaser.dataset.name = p.name || 'Указатель';
    globalLaser.hidden = false;
    clearTimeout(globalLaser._hide);
    globalLaser._hide = setTimeout(() => { globalLaser.hidden = true; }, p.kind === 'laser' ? 900 : 1500);
  });
  document.addEventListener('click', (event) => {
    const syncButton = event.target.closest('#sync-student');
    if (syncButton) {
      followStudent = !followStudent;
      syncButton.classList.toggle('studio-btn-primary', followStudent);
      syncButton.textContent = followStudent ? 'Веду ученика' : 'Вести ученика';
      syncStudio({follow_student:followStudent, active_pane:document.querySelector('.studio-tab.active')?.dataset.pane || 'control'});
      return;
    }
    const tab = event.target.closest('.studio-tab');
    if (tab && followStudent && root.dataset.teacher === 'true') {
      window.setTimeout(() => syncStudio({follow_student:true, active_pane:tab.dataset.pane}), 0);
    }
  }, true);

  function buildNativeWorkspace(frame) {
    if ($('#native-workspace')) return;
    const shell = document.createElement('section');
    shell.id = 'native-workspace';
    shell.className = 'native-workspace';
    shell.innerHTML = `<section class="native-editor"><div class="native-editor-head"><b>main.py</b><span id="workspace-presence">Нет участников</span></div><textarea id="workspace-code" spellcheck="false" placeholder="Выберите задание, чтобы начать писать код."></textarea><label class="native-answer">Ответ<input id="workspace-answer" placeholder="Короткий ответ, если нужен"></label><div class="native-actions"><span id="workspace-status">Подключаемся…</span><button id="workspace-save" class="studio-btn studio-btn-quiet">Сохранить</button><button id="workspace-run" class="studio-btn studio-btn-primary">Запустить</button></div></section><section class="native-output"><div class="native-editor-head"><b>Результат</b><button id="workspace-versions" class="text-xs font-black text-indigo-600">Версии</button></div><pre id="workspace-output">Запустите код — результат появится здесь.</pre><div id="workspace-version-list" class="hidden"></div></section>`;
    frame.hidden = true;
    frame.after(shell);
    bindNativeWorkspace();
  }

  function contextPayload() { return {context_type: 'lesson_task', context_id: activeContext, client_id: clientId}; }
  function setStatus(text) { const el = $('#workspace-status'); if (el) el.textContent = text; }
  function connectWorkspace() {
    if (!activeContext) return;
    if (!socket) {
      socket = io('/task-workspace');
      socket.on('connect', () => socket.emit('join_workspace', contextPayload()));
      socket.on('workspace_snapshot', (payload) => applySnapshot(payload?.state));
      socket.on('workspace_patch', (payload) => {
        if (payload?.client_id === clientId || !payload?.code_after) return;
        const editor = $('#workspace-code'); if (!editor) return;
        applyingRemote = true; editor.value = payload.code_after; applyingRemote = false;
        version = Number(payload.version) || version; setStatus('Синхронизировано');
      });
      socket.on('workspace_presence', (payload) => {
        const names = (payload?.participants || []).map(x => x.display_name || x.username).filter(Boolean);
        const el = $('#workspace-presence'); if (el) el.textContent = names.length ? names.join(' · ') : 'Нет участников';
      });
    } else if (socket.connected) socket.emit('join_workspace', contextPayload());
  }
  function applySnapshot(state) {
    if (!state) return;
    const editor = $('#workspace-code'), answer = $('#workspace-answer');
    if (editor) { applyingRemote = true; editor.value = state.code || ''; applyingRemote = false; }
    if (answer) answer.value = state.answer || '';
    version = Number(state.version) || 0; setStatus('Совместный режим');
  }
  async function request(path, body, method = 'POST') {
    const r = await fetch(path, {method, headers: {'Content-Type':'application/json','X-CSRFToken':csrf}, body: JSON.stringify(body)});
    return r.json();
  }
  function bindNativeWorkspace() {
    const editor = $('#workspace-code'), answer = $('#workspace-answer');
    editor.addEventListener('input', () => {
      if (applyingRemote || !socket || !activeContext) return;
      socket.emit('workspace_patch', {...contextPayload(), base_version: version, full_code: editor.value, next: editor.value, op_id: crypto.randomUUID(), cursor_start: editor.selectionStart, cursor_end: editor.selectionEnd, updated_at: Date.now()});
      setStatus('Синхронизация…');
    });
    $('#workspace-save').onclick = async () => {
      if (!activeContext) return;
      const res = await request('/task-workspace/api/save', {...contextPayload(), code: editor.value, answer: answer.value});
      setStatus(res.success ? 'Сохранено' : (res.error || 'Ошибка сохранения'));
      if (res.success) socket?.emit('workspace_saved', contextPayload());
    };
    $('#workspace-run').onclick = async () => {
      if (!activeContext) return;
      setStatus('Запускаем…');
      const res = await request('/task-workspace/api/run', {...contextPayload(), code: editor.value});
      $('#workspace-output').textContent = res.stderr || res.stdout || res.error || 'Выполнено без вывода';
      setStatus(res.success ? (res.status === 'error' ? 'Ошибка кода' : 'Готово') : 'Ошибка запуска');
    };
    $('#workspace-versions').onclick = async () => {
      if (!activeContext) return;
      const res = await fetch(`/task-workspace/api/versions?context_type=lesson_task&context_id=${activeContext}`).then(r => r.json());
      const box = $('#workspace-version-list'); box.classList.remove('hidden');
      box.innerHTML = (res.versions?.items || []).map(v => `<button class="workspace-version" data-version="${v.id}">Версия ${v.version || v.id}</button>`).join('') || 'Версий пока нет.';
    };
  }
  const observer = new MutationObserver(() => {
    const frame = $('#workspace-frame');
    if (!frame) return;
    const match = frame.src.match(/context_id=(\d+)/);
    if (!match) return;
    activeContext = Number(match[1]); buildNativeWorkspace(frame); connectWorkspace();
  });
  observer.observe(root, {childList:true, subtree:true, attributes:true, attributeFilter:['src']});
  window.setInterval(() => {
    const frame = $('#workspace-frame');
    if (!frame || $('#native-workspace')) return;
    const match = frame.src.match(/context_id=(\d+)/);
    if (!match) return;
    activeContext = Number(match[1]);
    buildNativeWorkspace(frame);
    connectWorkspace();
  }, 150);
  window.setTimeout(() => {
    if (!teacher) return;
    document.querySelectorAll('.phase-btn').forEach((button) => {
      button.onclick = async () => {
        const current = await fetch(`/lesson/${lessonId}/studio/state`).then(r => r.json());
        const state = current.state;
        if (!state) return;
        const phase = button.dataset.phase;
        const phaseTimers = {...(state.phase_timers || {}), [state.phase]: Math.max(0, Number(state.timer?.seconds) || 0)};
        const timer = {...(state.timer || {}), seconds: phaseTimers[phase], running:false, completed_at:null};
        const saved = await syncStudio({phase, phase_timers:phaseTimers, timer});
        if (!saved.success) return;
        document.querySelector('#phase-label').textContent = ({preparation:'Подготовка',practice:'Практика',reflection:'Итог'})[phase];
        document.querySelectorAll('.phase-btn').forEach(x => x.classList.toggle('active', x === button));
        document.querySelector('#lesson-timer').textContent = `${String(Math.floor(timer.seconds / 60)).padStart(2,'0')}:${String(timer.seconds % 60).padStart(2,'0')}`;
      };
    });
  }, 0);
})();
