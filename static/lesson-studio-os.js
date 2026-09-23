(() => {
  const root = document.querySelector('#lesson-studio-os'); if (!root || !window.io) return;
  const raw = document.querySelector('#studio-os-data'); const data = raw ? JSON.parse(raw.textContent) : {};
  const lessonId = Number(root.dataset.lessonId), teacher = root.dataset.teacher === 'true', csrf = document.querySelector('meta[name="csrf-token"]')?.content || '', clientId = crypto.randomUUID();
  let state = data.state || {}, tasks = typeof data.tasks === 'string' ? JSON.parse(data.tasks) : (data.tasks || []), activeTask = null, workspace = {id:null, version:0, socket:null, applying:false, pendingOps:[], lastLocalEditAt:0, seenOpIds:new Set()}, board = {tool:'pen',color:'#312e81',width:4,drawing:null,drag:null,camera:{x:0,y:0,z:1}}, lastLaserAt = 0;
  const $ = s => document.querySelector(s), fmt=s=>`${String(Math.floor(Math.max(0,s||0)/60)).padStart(2,'0')}:${String(Math.max(0,s||0)%60).padStart(2,'0')}`;
  const localKey=`boostudy:room:${lessonId}:learning-flow-ui`, phaseLabels={preparation:'Подготовка',practice:'Практика',reflection:'Итог'};
  let localUi={},hasExplicitWorkspaceChoice=false; try{localUi=JSON.parse(localStorage.getItem(localKey)||'{}')}catch(_){localUi={}}
  if(Number(localUi.rightWidth)>0&&Number(localUi.rightWidth)<300)localUi.rightWidth=320;
  const persistUi=()=>{try{localStorage.setItem(localKey,JSON.stringify(localUi))}catch(_){/* Storage is optional UI convenience. */}};
  function safeTaskHtml(value){
    const template=document.createElement('template');
    template.innerHTML=String(value||'');
    template.content.querySelectorAll('script,style,iframe,object,embed,form,link,meta').forEach(node=>node.remove());
    template.content.querySelectorAll('*').forEach(node=>{
      [...node.attributes].forEach(attribute=>{
        const name=attribute.name.toLowerCase(),raw=String(attribute.value||'').trim().toLowerCase();
        if(name.startsWith('on')||((name==='href'||name==='src')&&raw.startsWith('javascript:')))node.removeAttribute(attribute.name);
      });
      if(node.tagName==='A'&&node.getAttribute('target')==='_blank')node.setAttribute('rel','noopener noreferrer');
    });
    return template.innerHTML;
  }
  async function post(url, body) {
    try {
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body)});
      const payload = await response.json().catch(() => null);
      if (payload && typeof payload === 'object') return payload;
      return {success: false, error: response.status === 413 ? 'Файл или запрос слишком большой для сервера.' : 'Сервер вернул некорректный ответ.'};
    } catch (error) {
      return {success: false, error: 'Нет соединения с сервером. Проверьте сеть и повторите.'};
    }
  }
  async function postForm(url, form) {
    try {const response=await fetch(url,{method:'POST',headers:{'X-CSRFToken':csrf},body:form});const payload=await response.json().catch(()=>null);return payload&&typeof payload==='object'?payload:{success:false,error:response.status===413?'Файл слишком большой для сервера.':'Сервер вернул некорректный ответ.'}}catch(_){return {success:false,error:'Нет соединения с сервером. Проверьте сеть и повторите.'}}
  }
  async function refreshStudioState(){
    try {const response=await fetch(`/lesson/${lessonId}/studio/state`,{headers:{'X-CSRFToken':csrf}});const payload=await response.json();if(!payload.success)return;state=teacher?{...state,...payload.state}:payload.state;render();if(!teacher&&state.follow_student&&!hasExplicitWorkspaceChoice)activate(state.active_pane||'work',true)}catch(_){setConnection('disconnected')}
  }
  
  function toast(text){const n=document.createElement('div');n.className='os-toast';n.setAttribute('role','status');n.setAttribute('aria-live','polite');n.textContent=text;document.body.append(n);setTimeout(()=>n.remove(),2400)}
  function setModalVisible(modal,visible,focusTarget){
    if(!modal)return;
    modal.classList.toggle('hidden',!visible);
    modal.setAttribute('aria-hidden',String(!visible));
    if(visible)requestAnimationFrame(()=>focusTarget?.focus());
  }
  function confirmRoomAction(title,text,accept='Удалить'){return new Promise(resolve=>{const modal=$('#room-confirm-modal');if(!modal)return resolve(false);$('#room-confirm-title').textContent=title;$('#room-confirm-text').textContent=text;const close=result=>{setModalVisible(modal,false);$('#room-confirm-cancel').onclick=null;$('#room-confirm-accept').onclick=null;resolve(result)};$('#room-confirm-cancel').onclick=()=>close(false);$('#room-confirm-accept').textContent=accept;$('#room-confirm-accept').onclick=()=>close(true);setModalVisible(modal,true,$('#room-confirm-cancel'))})}
  function setConnection(status){const badge=$('#room-connection-status');if(!badge)return;const labels={connected:'Синхронизировано',connecting:'Синхронизация',disconnected:'Нет соединения'};badge.textContent=labels[status]||labels.connecting;badge.className=`room-connection is-${status}`}
  async function save(patch){if(!teacher)return null;const r=await post(`/lesson/${lessonId}/studio/state`,patch);if(r.success){state=r.state;render()}else toast(r.error||'Не удалось сохранить');return r}
  function activate(view, remote=false){
    if(!['work','theory','board','materials'].includes(view)) view='work';
    document.querySelectorAll('.room-tab[data-view]').forEach(x=>{const active=x.dataset.view===view;x.classList.toggle('active',active);x.setAttribute('aria-selected',String(active));});
    document.querySelectorAll('[data-view-panel]').forEach(x=>x.classList.toggle('hidden',x.dataset.viewPanel!==view));
    if(view==='board') renderBoard();
    if(view==='materials') renderMaterials();
    if(view==='theory') renderTheory();
    if (!remote) lessonSocket.emit('tab_changed', {lesson_id: lessonId, tab: view});
    localUi.activeWorkspace=view;persistUi();
    if(!remote){hasExplicitWorkspaceChoice=true;const url=new URL(window.location.href);url.searchParams.set('pane',view);window.history.replaceState({},'',url)}
    // Switching a workspace is private navigation. The teacher explicitly
    // publishes a workspace through "Показать ученику", never by browsing.
  }
  
  const getDisplayTimerSeconds = () => {
    if (state.timer && state.timer.seconds != null && Number(state.timer.seconds) > 0) {
      return Number(state.timer.seconds);
    }
    const phase = state.phase || 'preparation';
    return Number(state.phase_timers?.[phase] || state.phase_durations?.[phase] || 540);
  };

  function render(){
    const timer=state.timer||{}, phase=state.phase||'preparation';
    const timerEl = $('#os-timer');
    if (timerEl) {
      const sec = timer.running ? (timer.seconds || 0) : getDisplayTimerSeconds();
      timerEl.textContent = fmt(sec);
    }
    const toggleBtn = $('#os-timer-toggle');
    if(toggleBtn) toggleBtn.innerHTML = timer.running ? '<i class="ph-bold ph-pause"></i>' : '<i class="ph-bold ph-play"></i>';
    document.querySelectorAll('#os-phases button').forEach(b=>b.classList.toggle('active',b.dataset.phase===phase));
    const phaseLabel=$('#room-current-phase');if(phaseLabel)phaseLabel.textContent=phaseLabels[phase]||'Подготовка';
    const signalLabels={need_hint:'Нужна подсказка',need_pause:'Запрошена пауза',ready:'Готов к продолжению'};
    const signal=$('#room-student-signal');if(signal)signal.textContent=state.student_signal?signalLabels[state.student_signal]:'Сигнала нет';
    const studentSignalCurrent=$('#room-student-signal-current');if(studentSignalCurrent)studentSignalCurrent.textContent=state.student_signal?signalLabels[state.student_signal]:'Статус не выбран';
    document.querySelectorAll('[data-student-signal]').forEach(button=>{const selected=button.dataset.studentSignal===state.student_signal;button.classList.toggle('is-selected',selected);button.setAttribute('aria-pressed',String(selected));});
    const checkpoint=state.student_checkpoint||{};
    const checkpointView=$('#room-student-checkpoint');if(checkpointView)checkpointView.textContent=checkpoint.understanding?`Понимание: ${checkpoint.understanding}/5${checkpoint.blocker?` · ${checkpoint.blocker}`:''}`:'Самооценка ещё не отправлена.';
    const understanding=$('#room-checkpoint-understanding');if(understanding&&checkpoint.understanding)understanding.value=String(checkpoint.understanding);
    const blocker=$('#room-checkpoint-blocker');if(blocker&&checkpoint.blocker&&!blocker.value)blocker.value=checkpoint.blocker;
    const agendaBox=$('#room-agenda');if(agendaBox){const agenda=Array.isArray(state.agenda)?state.agenda:[];const doneCount=agenda.filter(item=>item.done).length;const badge=$('#room-agenda-progress-badge');if(badge)badge.textContent=agenda.length?`${doneCount}/${agenda.length}`:'0/0';agendaBox.innerHTML=agenda.map((item,index)=>`<label class="room-agenda-item"><input type="checkbox" data-agenda-index="${index}" ${item.done?'checked':''} ${teacher?'':'disabled'}><span>${String(item.title||'Шаг урока').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]))}</span></label>`).join('')||'<p class="text-sm text-slate-500 italic p-2">План пока не задан.</p>';agendaBox.querySelectorAll('[data-agenda-index]').forEach(input=>input.addEventListener('change',()=>{if(!teacher)return;const nextAgenda=(state.agenda||[]).map((item,index)=>({...item,done:index===Number(input.dataset.agendaIndex)?input.checked:Boolean(item.done)}));save({agenda:nextAgenda})}))}
    const guidance=String(state.guidance?.next_step||'').trim(), guidanceEditor=$('#room-guidance'), guidanceView=$('#room-student-guidance');
    if(guidanceEditor&&document.activeElement!==guidanceEditor)guidanceEditor.value=guidance;
    if(guidanceView){guidanceView.classList.toggle('hidden',!guidance);guidanceView.querySelector('p').textContent=guidance}
    const studentHomework=$('#room-student-homework');if(studentHomework){const homeworkText=String(state.outcome?.homework||'').trim();studentHomework.textContent=homeworkText||'Преподаватель зафиксирует итог и следующий шаг здесь.';}
    document.querySelectorAll('[data-duration]').forEach(i=>i.value=Math.max(1,Math.round(((state.phase_durations||{})[i.dataset.duration]||60)/60)));
    const followButton = $('#os-follow');
    if (followButton) {
      followButton.classList.toggle('room-action-primary', Boolean(state.follow_student));
      followButton.textContent = state.follow_student ? 'Веду ученика' : 'Вести ученика';
      followButton.setAttribute('aria-pressed', String(Boolean(state.follow_student)));
    }
    renderTasks();
    renderVideoDock();
  }

  function renderVideoDock(){
    const backupUrl = String(state.backup_call_url || '').trim();
    const backupBtn = $('#os-student-backup-btn'), backupNotice = $('#os-student-backup-notice');
    if(backupBtn && backupNotice){
      if(backupUrl){
        backupBtn.href = backupUrl;
        backupBtn.classList.remove('hidden');
        backupNotice.textContent = 'Преподаватель подготовил ссылку на звонок:';
      } else {
        backupBtn.href = '#';
        backupBtn.classList.add('hidden');
        backupNotice.textContent = 'Преподаватель пока не настроил резервную ссылку.';
      }
    }
    const backupInput = $('#os-backup-url-input');
    if(backupInput && document.activeElement !== backupInput && backupUrl){
      backupInput.value = backupUrl;
    }
    if(state.video_provider && !localUi.videoProviderUserChoice && typeof setProviderTab === 'function'){
      setProviderTab(state.video_provider, false);
    }
  }
  
  function taskStatusLabel(status){return ({pending:'Не начато',in_progress:'В работе',completed:'Готово',submitted:'На проверке'})[status]||'В очереди'}
  function renderTasks(){const box=$('#os-task-list');box.innerHTML='';$('#os-task-count').textContent=`${tasks.length} шт.`;if(!tasks.length){box.innerHTML='<div class="room-task-empty"><i class="ph-bold ph-list-checks"></i><strong>Заданий пока нет</strong><p>Преподаватель добавит их из генератора или урока.</p></div>';return}tasks.forEach((t,i)=>{const b=document.createElement('button');b.className=`room-task ${activeTask===t.lesson_task_id?'active':''}`;b.innerHTML=`<small>${i+1} · ${taskStatusLabel(t.status)}</small><b>${t.title}</b>`;b.onclick=()=>openTask(t.lesson_task_id);box.append(b)})}
  function setupEmptyTaskState() {
    activeTask = null;
    const titleEl = $('#os-task-title');
    const bodyEl = $('#os-task-body');
    const statusEl = $('#os-task-status');
    const counterText = $('#room-task-counter-text');
    const hintBody = $('#os-task-hint-body');

    if (titleEl) titleEl.textContent = 'Свободная практика';
    if (bodyEl) bodyEl.innerHTML = '<p>В этом уроке пока нет прикреплённых заданий.</p><p class="text-slate-500 mt-2">Вы можете писать, запускать и тестировать любой Python-код в редакторе прямо сейчас. Код синхронизируется в реальном времени.</p>';
    if (statusEl) statusEl.textContent = 'Редактор активен';
    if (counterText) counterText.textContent = 'Свободный режим';
    if (hintBody) hintBody.innerHTML = '<p class="text-slate-500 italic">Напишите код и нажмите Ctrl+Enter или кнопку «Запустить код».</p>';

    $('#room-task-prev')?.setAttribute('disabled', 'true');
    $('#room-task-next')?.setAttribute('disabled', 'true');
    $('#room-btn-prev-task')?.setAttribute('disabled', 'true');
    $('#room-btn-next-task')?.setAttribute('disabled', 'true');
    renderTasks();
    connectWorkspace(lessonId, 'lesson');
  }

  function openTask(id){
    const task=tasks.find(x=>String(x.lesson_task_id)===String(id));
    if(!task)return;
    activeTask=task.lesson_task_id;
    const taskIndex=tasks.findIndex(item=>String(item.lesson_task_id)===String(activeTask));
    $('#os-task-title').textContent=task.title;
    $('#os-task-body').innerHTML=safeTaskHtml(task.description)||'Условие отсутствует.';
    $('#os-task-status').textContent=taskStatusLabel(task.status);
    $('#room-mission-progress').textContent=`Шаг ${taskIndex+1} из ${tasks.length}`;
    $('#room-mission-badge').innerHTML=`<i class="ph-bold ph-sparkle"></i> ${task.status==='completed'?'Задача завершена':'Фокус: одна задача'}`;
    const counterText=$('#room-task-counter-text');if(counterText)counterText.textContent=`Задание ${taskIndex+1} из ${Math.max(1,tasks.length)}`;
    const hintBody=$('#os-task-hint-body');
    if(hintBody){
      const hints=task.hints||task.hint||(task.task&&(task.task.hints||task.task.hint));
      if(Array.isArray(hints)&&hints.length){hintBody.innerHTML=hints.map(h=>`<p>${codeEscape(h)}</p>`).join('');}
      else if(typeof hints==='string'&&hints.trim()){hintBody.innerHTML=`<p>${codeEscape(hints)}</p>`;}
      else{hintBody.innerHTML='<p class="text-slate-500 italic">Подсказок для этого задания нет. Попробуйте разбить решение на шаги.</p>';}
    }
    const hasPrev=taskIndex>0, hasNext=taskIndex<tasks.length-1;
    $('#room-task-prev')?.toggleAttribute('disabled',!hasPrev);
    $('#room-task-next')?.toggleAttribute('disabled',!hasNext);
    $('#room-btn-prev-task')?.toggleAttribute('disabled',!hasPrev);
    $('#room-btn-next-task')?.toggleAttribute('disabled',!hasNext);
    renderTasks();
    if(teacher)save({active_task_id:id});
    connectWorkspace(id, 'lesson_task');
  }
  
  function ctx(){return {context_type:workspace.kind||(workspace.id===lessonId?'lesson':'lesson_task'),context_id:workspace.id||lessonId,client_id:clientId}}
  const codeEscape=value=>String(value||'').replace(/[&<>]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[char]));
  function highlightPython(value){const source=String(value||''),tokens=/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|print|range|len|str|int|float|list|dict|set)\b)/g;let result='',cursor=0,match;while((match=tokens.exec(source))){result+=codeEscape(source.slice(cursor,match.index));const token=match[0],kind=token.startsWith('#')?'comment':token.startsWith('"')||token.startsWith("'")?'string':/^\d/.test(token)?'number':/^(print|range|len|str|int|float|list|dict|set)$/.test(token)?'builtin':'keyword';result+=`<span class="os-token-${kind}">${codeEscape(token)}</span>`;cursor=match.index+token.length}return result+codeEscape(source.slice(cursor));}
  function refreshCodeHighlight(){const editor=$('#os-code'),layer=$('#os-code-highlight');if(!editor||!layer)return;const val=editor.value||'';layer.innerHTML=highlightPython(val)+(val.endsWith('\n')?'\n ':'');layer.scrollTop=editor.scrollTop;layer.scrollLeft=editor.scrollLeft;}
  function refreshGutter(){const gutter=$('#os-code-gutter'),editor=$('#os-code');if(!gutter||!editor)return;const lines=(editor.value||'').split('\n').length||1;let html='';for(let i=1;i<=lines;i++){html+=`<span style="height:22px;line-height:22px;display:block;">${i}</span>`;}gutter.innerHTML=html;gutter.scrollTop=editor.scrollTop;}
  let typingTimer=null;
  function showTypingBanner(text){const banner=$('#os-typing-banner'),label=$('#os-typing-user-text');if(!banner||!label)return;label.textContent=text;banner.classList.remove('hidden');clearTimeout(typingTimer);typingTimer=setTimeout(()=>banner.classList.add('hidden'),2400);}
  function transformPositionThroughOp(pos, op) {
    const start = Math.max(0, Number(op?.start || 0));
    const end = Math.max(start, Number(op?.end || start));
    const inserted = String(op?.inserted || '');
    const delta = inserted.length - (end - start);
    if (pos <= start) return pos;
    if (pos >= end) return Math.max(0, pos + delta);
    return start + inserted.length;
  }

  function transformPatchThroughOps(patch, ops) {
    const next = {
      ...patch,
      start: Math.max(0, Number(patch.start || 0)),
      end: Math.max(0, Number(patch.end || patch.start || 0)),
    };
    (ops || []).forEach(op => {
      next.start = transformPositionThroughOp(next.start, op);
      next.end = transformPositionThroughOp(next.end, op);
      if (next.end < next.start) next.end = next.start;
    });
    return next;
  }

  function hasActiveLocalEdits() {
    if (workspace.pendingOps && workspace.pendingOps.length > 0) return true;
    const editor = $('#os-code');
    if (document.activeElement === editor && (Date.now() - (workspace.lastLocalEditAt || 0)) < 600) {
      return true;
    }
    return false;
  }

  function applyCodePatchToEditor(patch, options = {}) {
    const editor = $('#os-code');
    if (!editor) return;
    const start = Math.max(0, Number(patch.start || 0));
    const end = Math.max(start, Number(patch.end || start));
    const inserted = String(patch.inserted || '');
    const before = String(editor.value || '');
    const boundedStart = Math.min(start, before.length);
    const boundedEnd = Math.min(Math.max(boundedStart, end), before.length);
    const caretStart = editor.selectionStart || 0;
    const caretEnd = editor.selectionEnd || caretStart;
    const scrollT = editor.scrollTop, scrollL = editor.scrollLeft;

    const next = before.slice(0, boundedStart) + inserted + before.slice(boundedEnd);
    const delta = inserted.length - (boundedEnd - boundedStart);

    workspace.applying = true;
    editor.value = next;
    workspace.lastSentCode = next;

    const isFocused = document.activeElement === editor;
    if (isFocused || options.preserveSelection) {
      const mapCaret = (pos) => {
        if (pos > boundedEnd) return Math.max(0, pos + delta);
        if (pos >= boundedStart) return boundedStart + inserted.length;
        return pos;
      };
      const nStart = Math.max(0, Math.min(mapCaret(caretStart), next.length));
      const nEnd = Math.max(0, Math.min(mapCaret(caretEnd), next.length));
      editor.setSelectionRange(nStart, nEnd);
    }
    editor.scrollTop = scrollT;
    editor.scrollLeft = scrollL;
    refreshCodeHighlight();
    refreshGutter();
    workspace.applying = false;
  }

  function applyCanonicalCodeToEditor(nextCode, patch) {
    const editor = $('#os-code');
    if (!editor) return;
    if (editor.value === nextCode) {
      workspace.lastSentCode = nextCode;
      return;
    }
    const isFocused = document.activeElement === editor;
    const curStart = editor.selectionStart || 0, curEnd = editor.selectionEnd || curStart;
    const curScrollTop = editor.scrollTop, curScrollLeft = editor.scrollLeft;

    const start = Number.isFinite(patch?.start) ? patch.start : 0;
    const end = Number.isFinite(patch?.end) ? patch.end : start;
    const insertedLen = (patch?.inserted || '').length;
    const delta = insertedLen - (end - start);

    let newStart = curStart, newEnd = curEnd;
    if (curStart >= end) {
      newStart = curStart + delta;
    } else if (curStart > start) {
      newStart = start + insertedLen;
    }
    if (curEnd >= end) {
      newEnd = curEnd + delta;
    } else if (curEnd > start) {
      newEnd = start + insertedLen;
    }

    workspace.applying = true;
    editor.value = nextCode;
    workspace.lastSentCode = nextCode;
    if (isFocused) {
      editor.setSelectionRange(Math.max(0, Math.min(newStart, nextCode.length)), Math.max(0, Math.min(newEnd, nextCode.length)));
    }
    editor.scrollTop = curScrollTop;
    editor.scrollLeft = curScrollLeft;
    refreshCodeHighlight();
    refreshGutter();
    workspace.applying = false;
  }

  function connectWorkspace(id, kind='lesson_task'){
    workspace.id=id;
    workspace.kind=kind;
    $('#os-code').value='';
    $('#os-answer').value='';
    workspace.lastSentCode = '';
    workspace.pendingOps = [];
    refreshCodeHighlight();
    refreshGutter();
    $('#os-output').textContent='Подключаемся к совместному коду…';
    if(!workspace.socket){
      workspace.socket=io('/task-workspace');
      workspace.socket.on('connect',()=>workspace.socket.emit('join_workspace',ctx()));
      workspace.socket.on('workspace_snapshot',p=>applySnapshot(p.state));
      workspace.socket.on('workspace_patch',p=>{
        if (!p) return;
        const opId = String(p.op_id || '');
        if (p.client_id === clientId) {
          if (workspace.pendingOps && opId) {
            const idx = workspace.pendingOps.findIndex(op => op.op_id === opId);
            if (idx !== -1) workspace.pendingOps.splice(idx, 1);
          }
          if (opId) workspace.seenOpIds?.add(opId);
          if (p.version) workspace.version = Math.max(workspace.version, Number(p.version) || 0);
          return;
        }
        if (opId && workspace.seenOpIds?.has(opId)) return;
        if (opId) workspace.seenOpIds?.add(opId);
        if (p.version) workspace.version = Math.max(workspace.version, Number(p.version) || 0);

        const editor = $('#os-code');
        if (!editor) return;

        const hasCanonical = typeof p.code_after === 'string';
        const hasDeltas = Number.isFinite(p.start) && Number.isFinite(p.end) && typeof p.inserted === 'string';

        if (hasActiveLocalEdits() && hasDeltas) {
          const transformed = transformPatchThroughOps(p, workspace.pendingOps);
          applyCodePatchToEditor(transformed, { preserveSelection: true });
          (workspace.pendingOps || []).forEach(op => {
            op.start = transformPositionThroughOp(op.start, p);
            op.end = transformPositionThroughOp(op.end, p);
            if (op.end < op.start) op.end = op.start;
          });
        } else if (hasCanonical) {
          applyCanonicalCodeToEditor(p.code_after, p);
        } else if (hasDeltas) {
          applyCodePatchToEditor(p, { preserveSelection: true });
        }

        const peerRole = p.role === 'teacher' ? 'Преподаватель' : 'Ученик';
        const peerName = p.display_name || p.username || peerRole;
        showTypingBanner(`${peerName} печатает...`);
      });
      workspace.socket.on('workspace_cursor_update',p=>{
        if(!p || p.client_id===clientId)return;
        if (p.cursor?.is_typing) {
          const peerRole=p.role==='teacher'?'Преподаватель':'Ученик';
          const peerName=p.display_name||p.username||peerRole;
          showTypingBanner(`${peerName} печатает...`);
        }
      });
      workspace.socket.on('workspace_presence',p=>$('#os-presence').textContent=(p.participants||[]).map(x=>x.display_name||x.username).join(' · ')||'Онлайн');
    }else if(workspace.socket.connected){
      workspace.socket.emit('join_workspace',ctx());
    }
  }
  function applySnapshot(s){
    if(!s)return;
    workspace.applying=true;
    const editor=$('#os-code');
    if(editor) editor.value=s.code||'';
    workspace.lastSentCode = s.code||'';
    workspace.pendingOps = [];
    if($('#os-answer')) $('#os-answer').value=s.answer||'';
    refreshCodeHighlight();
    refreshGutter();
    workspace.applying=false;
    workspace.version=s.version||0;
    $('#os-presence').textContent='Совместный режим';
  }
  async function run(){
    const output=$('#os-output'), button=$('#os-run'), code=$('#os-code')?.value||'';
    const resultOutput=$('#os-result-output'), resultStatus=$('#os-result-status-tag');
    if(!workspace.id){
      if(tasks&&tasks.length>0){
        const selected=tasks.find(task=>String(task.lesson_task_id)===String(activeTask))||tasks[0];
        if(selected){
          openTask(selected.lesson_task_id);
        }
      }else{
        connectWorkspace(lessonId, 'lesson');
      }
    }
    if(!workspace.id){
      workspace.id=lessonId;
      workspace.kind='lesson';
    }
    if(!code.trim()){
      const emptyMsg='Напишите код перед запуском.';
      if(output)output.textContent=emptyMsg;
      if(resultOutput)resultOutput.textContent=emptyMsg;
      if(resultStatus)resultStatus.textContent='Код пустой';
      return toast('Код пока пустой.');
    }
    if(button){
      button.disabled=true;
      button.innerHTML='<i class="ph-bold ph-spinner animate-spin"></i><span>Запуск…</span>';
    }
    if(output)output.textContent='Запускаем код…';
    if(resultOutput)resultOutput.textContent='Запускаем код…';
    if(resultStatus)resultStatus.textContent='Выполняется…';
    try{
      const r=await post('/task-workspace/api/run',{...ctx(),code});
      if(!r.success){
        const errMsg=`Не удалось запустить код: ${r.error||'неизвестная ошибка'}`;
        if(output){ output.textContent=errMsg; output.classList.add('has-error'); }
        if(resultOutput)resultOutput.textContent=errMsg;
        if(resultStatus)resultStatus.textContent='Ошибка запуска';
        return toast(r.error||'Запуск кода не удался.');
      }
      const explanation=r.stderr_explained?.message||r.stderr_explained?.hint||'';
      const fullOut=[r.stdout,r.stderr,explanation].filter(Boolean).join('\n')||'Выполнено без вывода';
      if(output){
        output.textContent=fullOut;
        if(r.stderr){ output.classList.add('has-error'); } else { output.classList.remove('has-error'); }
      }
      if(resultOutput)resultOutput.textContent=fullOut;
      if(resultStatus)resultStatus.textContent=r.stderr?'Ошибка в коде':'Выполнено';
    }finally{
      if(button){
        button.disabled=false;
        button.innerHTML='<i class="ph-bold ph-play"></i><span>Запустить код</span>';
      }
    }
  }
  
  function computeDelta(before, after) {
    let prefix = 0;
    while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
      prefix++;
    }
    let suffix = 0;
    while (suffix < (before.length - prefix) && suffix < (after.length - prefix) && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) {
      suffix++;
    }
    return {
      start: prefix,
      end: before.length - suffix,
      inserted: after.slice(prefix, after.length - suffix)
    };
  }

  function bindWorkspace(){
    const codeEditor=$('#os-code');
    if (!codeEditor) return;

    let inputSnapshot = '';
    codeEditor.addEventListener('beforeinput', () => {
      inputSnapshot = codeEditor.value;
    });

    const emitCodeChange = () => {
      refreshCodeHighlight();
      refreshGutter();
      if (workspace.applying || !workspace.socket || !workspace.id) return;
      workspace.lastLocalEditAt = Date.now();
      const currentCode = codeEditor.value;
      const prevCode = workspace.lastSentCode !== undefined ? workspace.lastSentCode : (inputSnapshot || currentCode);
      if (prevCode === currentCode) return;
      const delta = computeDelta(prevCode, currentCode);
      workspace.lastSentCode = currentCode;
      const opId = crypto.randomUUID();
      const baseVersion = workspace.version;
      const op = {
        op_id: opId,
        base_version: baseVersion,
        start: delta.start,
        end: delta.end,
        inserted: delta.inserted
      };
      workspace.pendingOps.push(op);
      workspace.socket.emit('workspace_patch', {
        ...ctx(),
        base_version: baseVersion,
        start: delta.start,
        end: delta.end,
        inserted: delta.inserted,
        full_code: currentCode,
        next: currentCode,
        op_id: opId,
        updated_at: Date.now()
      });
    };

    codeEditor.addEventListener('input', () => {
      emitCodeChange();
    });

    codeEditor.addEventListener('mouseup', () => {
      refreshCodeHighlight();
    });

    codeEditor.addEventListener('scroll', () => {
      const layer = $('#os-code-highlight');
      if (layer) {
        layer.scrollTop = codeEditor.scrollTop;
        layer.scrollLeft = codeEditor.scrollLeft;
      }
      const gutter = $('#os-code-gutter');
      if (gutter) gutter.scrollTop = codeEditor.scrollTop;
    }, { passive: true });

    // Editor fullscreen button (#os-focus-toggle-btn)
    const focusBtn = $('#os-focus-toggle-btn');
    const outerCard = codeEditor.closest('.room-editor-outer-card') || $('.room-editor-outer-card');
    if (focusBtn && outerCard) {
      focusBtn.addEventListener('click', () => {
        const isFull = outerCard.classList.toggle('is-fullscreen');
        focusBtn.setAttribute('aria-pressed', String(isFull));
        focusBtn.setAttribute('title', isFull ? 'Свернуть редактор' : 'Развернуть редактор');
        focusBtn.innerHTML = isFull ? '<i class="ph-bold ph-corners-in text-base"></i>' : '<i class="ph-bold ph-corners-out text-base"></i>';
      });
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && outerCard.classList.contains('is-fullscreen')) {
          outerCard.classList.remove('is-fullscreen');
          focusBtn.setAttribute('aria-pressed', 'false');
          focusBtn.setAttribute('title', 'Развернуть редактор');
          focusBtn.innerHTML = '<i class="ph-bold ph-corners-out text-base"></i>';
        }
      });
    }

    codeEditor.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        run();
        return;
      }

      const val = codeEditor.value;
      const start = codeEditor.selectionStart;
      const end = codeEditor.selectionEnd;
      const hasSelection = start !== end;
      const selText = hasSelection ? val.substring(start, end) : '';

      // 1. Auto-closing pairs and selection wrap
      const pairs = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'" };
      const closingChars = [')', ']', '}', '"', "'"];

      if (pairs[e.key]) {
        e.preventDefault();
        const openChar = e.key;
        const closeChar = pairs[openChar];

        if (hasSelection) {
          codeEditor.value = val.substring(0, start) + openChar + selText + closeChar + val.substring(end);
          codeEditor.selectionStart = start + 1;
          codeEditor.selectionEnd = end + 1;
        } else {
          if ((openChar === '"' || openChar === "'") && val[start] === openChar) {
            codeEditor.selectionStart = codeEditor.selectionEnd = start + 1;
            return;
          }
          codeEditor.value = val.substring(0, start) + openChar + closeChar + val.substring(end);
          codeEditor.selectionStart = codeEditor.selectionEnd = start + 1;
        }
        emitCodeChange(false);
        return;
      }

      // 2. Overtype closing character
      if (closingChars.includes(e.key) && !hasSelection) {
        if (val[start] === e.key) {
          e.preventDefault();
          codeEditor.selectionStart = codeEditor.selectionEnd = start + 1;
          return;
        }
      }

      // 3. Smart Backspace: delete 4 spaces or empty pair
      if (e.key === 'Backspace' && !hasSelection && start > 0) {
        const lineStart = val.lastIndexOf('\n', start - 1) + 1;
        const lineBeforeCursor = val.substring(lineStart, start);
        if (/^ {2,}$/.test(lineBeforeCursor) && lineBeforeCursor.length % 4 === 0) {
          e.preventDefault();
          codeEditor.value = val.substring(0, start - 4) + val.substring(end);
          codeEditor.selectionStart = codeEditor.selectionEnd = start - 4;
          emitCodeChange(true);
          return;
        }
        const prev = val[start - 1];
        const next = val[start];
        if (
          (prev === '(' && next === ')') ||
          (prev === '[' && next === ']') ||
          (prev === '{' && next === '}') ||
          (prev === '"' && next === '"') ||
          (prev === "'" && next === "'")
        ) {
          e.preventDefault();
          codeEditor.value = val.substring(0, start - 1) + val.substring(start + 1);
          codeEditor.selectionStart = codeEditor.selectionEnd = start - 1;
          emitCodeChange(true);
          return;
        }
      }

      // 4. Smart Enter / Auto-indentation
      if (e.key === 'Enter') {
        e.preventDefault();
        const lineStart = val.lastIndexOf('\n', start - 1) + 1;
        const lineBeforeCursor = val.substring(lineStart, start);
        const indentMatch = lineBeforeCursor.match(/^[ \t]*/);
        let indent = indentMatch ? indentMatch[0] : '';

        const prevChar = val[start - 1];
        const nextChar = val[start];
        const isBetweenBrackets =
          (prevChar === '{' && nextChar === '}') ||
          (prevChar === '[' && nextChar === ']') ||
          (prevChar === '(' && nextChar === ')');

        if (isBetweenBrackets) {
          const extraIndent = indent + '    ';
          codeEditor.value = val.substring(0, start) + '\n' + extraIndent + '\n' + indent + val.substring(end);
          codeEditor.selectionStart = codeEditor.selectionEnd = start + 1 + extraIndent.length;
        } else {
          if (lineBeforeCursor.trimEnd().endsWith(':')) {
            indent += '    ';
          }
          codeEditor.value = val.substring(0, start) + '\n' + indent + val.substring(end);
          codeEditor.selectionStart = codeEditor.selectionEnd = start + 1 + indent.length;
        }
        emitCodeChange(true);
        return;
      }

      // 5. Tab and Shift+Tab (Indent / Outdent)
      if (e.key === 'Tab') {
        e.preventDefault();
        if (e.shiftKey) {
          if (hasSelection) {
            const firstLineStart = val.lastIndexOf('\n', start - 1) + 1;
            const lastLineEnd = val.indexOf('\n', end);
            const blockEnd = lastLineEnd === -1 ? val.length : lastLineEnd;
            const block = val.substring(firstLineStart, blockEnd);
            const lines = block.split('\n');
            const unindented = lines.map(line => line.replace(/^ {1,4}/, '')).join('\n');
            codeEditor.value = val.substring(0, firstLineStart) + unindented + val.substring(blockEnd);
            codeEditor.selectionStart = firstLineStart;
            codeEditor.selectionEnd = firstLineStart + unindented.length;
          } else {
            const lineStart = val.lastIndexOf('\n', start - 1) + 1;
            const line = val.substring(lineStart, start);
            const unindented = line.replace(/^ {1,4}/, '');
            const removed = line.length - unindented.length;
            codeEditor.value = val.substring(0, lineStart) + unindented + val.substring(start);
            codeEditor.selectionStart = codeEditor.selectionEnd = Math.max(lineStart, start - removed);
          }
        } else {
          if (hasSelection && selText.includes('\n')) {
            const firstLineStart = val.lastIndexOf('\n', start - 1) + 1;
            const lastLineEnd = val.indexOf('\n', end);
            const blockEnd = lastLineEnd === -1 ? val.length : lastLineEnd;
            const block = val.substring(firstLineStart, blockEnd);
            const lines = block.split('\n');
            const indented = lines.map(line => '    ' + line).join('\n');
            codeEditor.value = val.substring(0, firstLineStart) + indented + val.substring(blockEnd);
            codeEditor.selectionStart = firstLineStart;
            codeEditor.selectionEnd = firstLineStart + indented.length;
          } else {
            codeEditor.value = val.substring(0, start) + '    ' + val.substring(end);
            codeEditor.selectionStart = codeEditor.selectionEnd = start + 4;
          }
        }
        emitCodeChange(true);
        return;
      }
    });
    let cursorTimer=null;
    codeEditor.addEventListener('keyup',()=>{
      if(!workspace.socket||!workspace.id||workspace.applying)return;
      clearTimeout(cursorTimer);
      cursorTimer=setTimeout(()=>{
        workspace.socket.emit('workspace_cursor_update',{...ctx(),cursor:{selection_start:codeEditor.selectionStart,selection_end:codeEditor.selectionEnd,is_typing:false}});
      },120);
    });
    $('#os-save').onclick=async()=>{if(!workspace.id)return;const r=await post('/task-workspace/api/save',{...ctx(),code:codeEditor.value,answer:$('#os-answer').value});toast(r.success?'Сохранено':r.error||'Ошибка')};
    $('#os-run').onclick=run;
    $('#os-versions').onclick=async()=>{if(!workspace.id)return;const r=await fetch(`/task-workspace/api/versions?context_type=lesson_task&context_id=${workspace.id}`).then(x=>x.json());const items=r.versions?.items||[];const box=$('#os-versions-list');box.innerHTML='';if(!items.length){box.textContent='Версий пока нет.';return}items.forEach((item,index)=>{const b=document.createElement('button');b.className='os-version';b.textContent=`Версия ${items.length-index} · ${item.source||'сохранение'}`;b.onclick=async()=>{const restored=await post(`/task-workspace/api/versions/${item.version_id}/restore`,ctx());if(!restored.success)return toast(restored.error||'Не удалось восстановить');workspace.applying=true;codeEditor.value=restored.code||'';$('#os-answer').value=restored.answer||'';refreshCodeHighlight();refreshGutter();workspace.applying=false;toast('Версия восстановлена')};box.append(b)})};
  }
  
  function phaseChange(phase){if(!teacher)return;const previous=state.phase, timers={...(state.phase_timers||{}),[previous]:Math.max(0,Number(state.timer?.seconds)||0)},timer={...(state.timer||{}),seconds:timers[phase],running:false,completed_at:null};save({phase,phase_timers:timers,timer})}
  
  const BOARD_STROKE_CHUNK_SIZE=1000;
  function boardPoint(e){const c=$('#os-board'),r=c.getBoundingClientRect();return{x:(e.clientX-r.left-board.camera.x)/board.camera.z,y:(e.clientY-r.top-board.camera.y)/board.camera.z}}
  function appendBoardPoint(stroke,event){
    const point=boardPoint(event),last=stroke.points.at(-1);
    if(!Number.isFinite(point.x)||!Number.isFinite(point.y)||(last&&last.x===point.x&&last.y===point.y))return;
    stroke.points.push(point);
  }
  function splitBoardStrokeForRequest(stroke){
    if(stroke.points.length<=BOARD_STROKE_CHUNK_SIZE)return [stroke];
    const chunks=[];
    for(let start=0;start<stroke.points.length;){
      const end=Math.min(start+BOARD_STROKE_CHUNK_SIZE,stroke.points.length);
      chunks.push({...stroke,points:stroke.points.slice(start,end)});
      if(end===stroke.points.length)break;
      start=end-1;
    }
    return chunks;
  }
  function saveBoardStroke(stroke){
    if (lessonSocket?.connected) {
      lessonSocket.emit('board_stroke', {lesson_id: lessonId, stroke});
    }
    const chunks=splitBoardStrokeForRequest(stroke);
    return chunks.length===1
      ? post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:chunks[0]})
      : post(`/lesson/${lessonId}/studio/board`,{action:'append_batch',strokes:chunks});
  }
  const imgCache = {};
  function boardStrokeScale(stroke, canvas){
    return stroke.coordinate_space === 'relative' ? {x:canvas.width,y:canvas.height} : {x:1,y:1};
  }
  function strokePoint(point, scale){return{x:point.x*scale.x,y:point.y*scale.y}}
  function draw(s){const c=$('#os-board'),g=c.getContext('2d'),p=s.points;if(!p?.length)return;
    g.save(); g.translate(board.camera.x, board.camera.y); g.scale(board.camera.z, board.camera.z);
    const scale = boardStrokeScale(s,c);
    g.strokeStyle=s.color||'#312e81'; g.fillStyle=s.color||'#312e81'; g.lineWidth=s.width||4; g.lineCap='round'; g.lineJoin='round';
    if(s.tool==='eraser') g.globalCompositeOperation='destination-out';
    g.beginPath();
    if(s.tool==='text'){ const point=strokePoint(p[0],scale); g.font='28px sans-serif'; g.fillText(s.text, point.x, point.y); }
    else if(s.tool==='image'){
      const drawImg = (img) => {
          const point=strokePoint(p[0],scale);
          g.drawImage(img, point.x, point.y, (s.image_width||400)*scale.x, (s.image_height||400)*scale.y);
      };
      if (imgCache[s.url]) {
          if (imgCache[s.url].complete) drawImg(imgCache[s.url]);
      } else {
          const image=new Image();
          imgCache[s.url] = image;
          image.onload = () => renderBoard();
          image.src=s.url;
      }
    }
    else if(['line','rectangle','ellipse'].includes(s.tool)){
      const a=strokePoint(p[0],scale),b=strokePoint(p[p.length-1],scale),x=a.x,y=a.y,w=b.x-a.x,h=b.y-a.y;
      if(s.tool==='rectangle') g.strokeRect(x,y,w,h);
      else if(s.tool==='ellipse') { g.ellipse(x+w/2,y+h/2,Math.abs(w/2),Math.abs(h/2),0,0,Math.PI*2); g.stroke(); }
      else { g.moveTo(x,y); g.lineTo(x+w,y+h); g.stroke(); }
    } else {
      const first=strokePoint(p[0],scale);
      if(p.length===1){g.arc(first.x,first.y,Math.max(1,g.lineWidth/2),0,Math.PI*2);g.fill();}
      else {
        g.moveTo(first.x,first.y);
        for(let i=1;i<p.length-1;i++){const point=strokePoint(p[i],scale),next=strokePoint(p[i+1],scale);g.quadraticCurveTo(point.x,point.y,(point.x+next.x)/2,(point.y+next.y)/2)}
        const last=strokePoint(p[p.length-1],scale);g.lineTo(last.x,last.y);g.stroke();
      }
    }
    g.restore();
    if (board.selectedStrokeIndex !== undefined && state.board && state.board.strokes[board.selectedStrokeIndex] === s && s.tool === 'image') {
        const point=strokePoint(s.points[0],scale);
        const x = point.x * board.camera.z + board.camera.x;
        const y = point.y * board.camera.z + board.camera.y;
        const w = (s.image_width||400) * scale.x * board.camera.z;
        const h = (s.image_height||400) * scale.y * board.camera.z;
        const ctx=c.getContext('2d'); ctx.save();
        ctx.strokeStyle='#3b82f6'; ctx.lineWidth=2; ctx.setLineDash([5,5]);
        ctx.strokeRect(x, y, w, h);
        ctx.fillStyle='#3b82f6'; ctx.setLineDash([]);
        ctx.fillRect(x + w - 6, y + h - 6, 12, 12);
        ctx.restore();
    }
  }
  
  function renderBoard(){
    const c=$('#os-board'), viewport=$('#os-board-viewport'); if(!c || !viewport) return;
    if (c.width !== viewport.clientWidth || c.height !== viewport.clientHeight) { c.width = viewport.clientWidth; c.height = viewport.clientHeight; }
    const g=c.getContext('2d'); g.clearRect(0,0,c.width,c.height);
    viewport.style.backgroundPosition = `${board.camera.x}px ${board.camera.y}px`;
    viewport.style.backgroundSize = `${24 * board.camera.z}px ${24 * board.camera.z}px`;
    ((state.board||{}).strokes||[]).forEach(draw);
    if(board.drawing) draw(board.drawing);
  }
  
  function bindBoard(){
    const c=$('#os-board'), viewport=$('#os-board-viewport');
    const toolLabels={select:'Указатель',pen:'Ручка',eraser:'Ластик',line:'Линия',rectangle:'Прямоугольник',ellipse:'Круг',text:'Текст',hand:'Перемещение'};
    const updateBoardStatus=()=>{
      const target=$('#room-board-status'),canvas=$('#os-board'),toolbar=$('.room-board-toolbar');
      if(target)target.textContent=(toolLabels[board.tool]||'Инструмент')+' · '+board.width+' px';
      if(canvas)canvas.dataset.tool=board.tool;
      if(toolbar)toolbar.dataset.tool=board.tool;
      document.querySelectorAll('[data-board-context]').forEach(control=>{
        control.hidden=!control.dataset.boardContext.split(' ').includes(board.tool);
      });
      const widthValue=$('#os-board-width-value');if(widthValue)widthValue.textContent=board.width+' px';
      document.querySelectorAll('[data-board-width-mirror]').forEach(input=>{
        const minimum=Number(input.min)||0,maximum=Number(input.max)||board.width;
        input.value=Math.min(maximum,Math.max(minimum,board.width));
        const output=input.parentElement?.querySelector('output');if(output)output.textContent=input.value+' px';
      });
      const zoomValue=$('#os-board-zoom-value');if(zoomValue)zoomValue.textContent=Math.round(board.camera.z*100)+'%';
    };
    new ResizeObserver(() => renderBoard()).observe(viewport);
    
    document.addEventListener('keydown', e => {
        if (e.ctrlKey && e.code === 'KeyZ' && document.querySelector('.room-tab[data-view="board"]')?.classList.contains('active')) {
            e.preventDefault();
            if ((state.board?.strokes || []).length > 0) {
                if (lessonSocket?.connected) lessonSocket.emit('board_action', {lesson_id: lessonId, action: 'undo'});
                post(`/lesson/${lessonId}/studio/board`, {action: 'undo'}).then(r => {
                    if (r.success) { state.board = r.board; renderBoard(); }
                });
            }
        }
    });

    c.addEventListener('wheel', e => {
        e.preventDefault();
        const zoomAmount = e.deltaY > 0 ? 0.9 : 1.1;
        const rect = c.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const ptX = (mouseX - board.camera.x) / board.camera.z;
        const ptY = (mouseY - board.camera.y) / board.camera.z;
        board.camera.z = Math.min(Math.max(0.2, board.camera.z * zoomAmount), 5);
        board.camera.x = mouseX - ptX * board.camera.z;
        board.camera.y = mouseY - ptY * board.camera.z;
        const slider = $('#os-board-zoom');
        if (slider) slider.value = Math.round(board.camera.z * 100);
        updateBoardStatus();
        renderBoard();
    }, {passive: false});
    c.addEventListener('pointerdown',e=>{
      e.preventDefault();e.stopPropagation();
      if(e.button === 1 || board.tool==='hand'){ e.preventDefault(); board.drag={x:e.clientX,y:e.clientY,cx:board.camera.x,cy:board.camera.y}; c.setPointerCapture(e.pointerId); return; }
      if(e.button !== 0 && e.pointerType !== 'touch') return;
      if(board.tool==='select'){
          e.preventDefault();
          const bp = boardPoint(e);
          const strokes = state.board?.strokes || [];
          if (board.selectedStrokeIndex !== undefined) {
              const s = strokes[board.selectedStrokeIndex];
              if (s && s.tool === 'image') {
                  const iw = s.image_width||400; const ih = s.image_height||400;
                  const scale=boardStrokeScale(s,c),point=strokePoint(s.points[0],scale);
                  const bx = point.x, by = point.y;
                  const bw = iw * scale.x, bh = ih * scale.y;
                  if (Math.abs(bp.x - (bx + bw)) < 15 && Math.abs(bp.y - (by + bh)) < 15) {
                      board.resizing = { index: board.selectedStrokeIndex, startX: bp.x, startY: bp.y, startW: iw, startH: ih };
                      c.setPointerCapture(e.pointerId); return;
                  }
                  if (bp.x >= bx && bp.x <= bx + bw && bp.y >= by && bp.y <= by + bh) {
                      board.draggingImg = { index: board.selectedStrokeIndex, offsetX: bp.x - bx, offsetY: bp.y - by };
                      c.setPointerCapture(e.pointerId); return;
                  }
              }
          }
          board.selectedStrokeIndex = undefined;
          for(let i=strokes.length-1; i>=0; i--){
              const s=strokes[i];
              if(s.tool==='image'){
                  const iw = s.image_width||400; const ih = s.image_height||400;
                  const scale=boardStrokeScale(s,c),point=strokePoint(s.points[0],scale);
                  const bx = point.x, by = point.y;
                  if (bp.x >= bx && bp.x <= bx + iw*scale.x && bp.y >= by && bp.y <= by + ih*scale.y) {
                      board.selectedStrokeIndex = i; break;
                  }
              }
          }
          renderBoard();
          return;
      }
      board.selectedStrokeIndex = undefined;
      if(board.tool==='text'){ const text=$('#os-board-text').value.trim(); if(text) post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'text',text,color:board.color,width:board.width,coordinate_space:'canvas',points:[boardPoint(e)]}}).then(r=>{if(r.success){state.board=r.board;renderBoard()}}); return; }
      board.drawing={tool:board.tool,color:board.color,width:board.width,coordinate_space:'canvas',points:[boardPoint(e)]}; c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove',e=>{
      e.preventDefault();e.stopPropagation();
      if(board.drag){ board.camera.x = board.drag.cx + (e.clientX - board.drag.x); board.camera.y = board.drag.cy + (e.clientY - board.drag.y); if(!board.renderFrame){board.renderFrame=requestAnimationFrame(()=>{board.renderFrame=null;renderBoard()})} return; }
      const bp=boardPoint(e);
      if(board.resizing !== undefined) {
          const r = board.resizing; const s = state.board.strokes[r.index];
          const scale=boardStrokeScale(s,c);
          const dx = (bp.x - r.startX) / scale.x;
          const newW = Math.max(20, r.startW + dx);
          const ratio = r.startW / (r.startH || 1);
          s.image_width = newW;
          s.image_height = newW / ratio;
          renderBoard(); return;
      }
      if(board.draggingImg !== undefined) {
          const d = board.draggingImg; const s = state.board.strokes[d.index];
          const scale=boardStrokeScale(s,c);
          s.points[0] = { x: (bp.x - d.offsetX)/scale.x, y: (bp.y - d.offsetY)/scale.y };
          renderBoard(); return;
      }
      if(!board.drawing) return;
      const coalesced=typeof e.getCoalescedEvents === 'function' ? e.getCoalescedEvents() : null;
      const pointerEvents=coalesced?.length ? coalesced : [e];
      pointerEvents.forEach(pointerEvent=>appendBoardPoint(board.drawing,pointerEvent));
      if(!board.renderFrame){board.renderFrame=requestAnimationFrame(()=>{board.renderFrame=null;renderBoard()})}
    });
    c.addEventListener('pointerup',e=>{
      e.preventDefault();e.stopPropagation();
      if(board.drag){board.drag=null;c.releasePointerCapture(e.pointerId);return}
      if(board.resizing !== undefined || board.draggingImg !== undefined) {
          board.resizing = undefined; board.draggingImg = undefined; c.releasePointerCapture(e.pointerId);
          post(`/lesson/${lessonId}/studio/board`, {action: 'rewrite', strokes: state.board.strokes}).then(r=>{if(r.success){state.board=r.board;renderBoard()}});
          return;
      }
      if(board.drawing)appendBoardPoint(board.drawing,e);
      const s=board.drawing; board.drawing=null;
      if(!s) return; c.releasePointerCapture(e.pointerId);
      const minimumPoints=s.tool==='eraser'?1:2;
      if(s.points.length>=minimumPoints){
        const optimistic={...s,client_stroke_id:crypto.randomUUID()};
        state.board={...(state.board||{}),strokes:[...((state.board||{}).strokes||[]),optimistic]};
        renderBoard();
        saveBoardStroke(s).then(r=>{
          if(r.success){state.board=r.board;renderBoard();return}
          state.board={...(state.board||{}),strokes:((state.board||{}).strokes||[]).filter(stroke=>stroke.client_stroke_id!==optimistic.client_stroke_id)};
          renderBoard();toast(r.error||'Не удалось сохранить штрих');
        });
      }
    });
    c.addEventListener('pointercancel',e=>{e.preventDefault();e.stopPropagation();board.drawing=null;board.drag=null;board.resizing=undefined;board.draggingImg=undefined;renderBoard();});
    c.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();});
    viewport.addEventListener('click',e=>{if(e.target===viewport){e.preventDefault();e.stopPropagation();}});
    document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>{board.tool=b.dataset.tool;document.querySelectorAll('[data-tool]').forEach(x=>{const active=x===b;x.classList.toggle('active',active);x.setAttribute('aria-pressed',String(active));});updateBoardStatus()});
    document.querySelectorAll('[data-color]').forEach(b=>b.onclick=()=>{board.color=b.dataset.color;document.querySelectorAll('[data-color]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));updateBoardStatus()});
    $('#os-board-width').oninput=e=>{ board.width=Number(e.target.value);updateBoardStatus() };
    document.querySelectorAll('[data-board-width-mirror]').forEach(input=>input.oninput=e=>{board.width=Number(e.target.value);updateBoardStatus()});
    $('#os-board-zoom').oninput=e=>{ board.camera.z=Number(e.target.value)/100; updateBoardStatus();renderBoard(); };
    $('#os-board-image').onchange=async e=>{
      const file=e.target.files?.[0]; if(!file)return; const form=new FormData(); form.append('file',file);
      const r=await postForm(`/lesson/${lessonId}/studio/board/image`,form);
      if(!r.success) return toast(r.error||'Не удалось загрузить изображение');
      const cx = (-board.camera.x + c.width/2)/board.camera.z, cy = (-board.camera.y + c.height/2)/board.camera.z;
      const updated=await post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'image',url:r.url,image_width:400,image_height:400,coordinate_space:'canvas',points:[{x:cx,y:cy}]}});
      if(updated.success){state.board=updated.board;renderBoard()} e.target.value='';
    };
    $('#os-board-clear')?.addEventListener('click',()=>{
      if (lessonSocket?.connected) lessonSocket.emit('board_action', {lesson_id: lessonId, action: 'clear'});
      post(`/lesson/${lessonId}/studio/board`,{action:'clear'}).then(r=>{if(r.success){state.board=r.board;renderBoard()}});
    });
    $('#os-board-undo')?.addEventListener('click',()=>{
      if (lessonSocket?.connected) lessonSocket.emit('board_action', {lesson_id: lessonId, action: 'undo'});
      post(`/lesson/${lessonId}/studio/board`,{action:'undo'}).then(r=>{if(r.success){state.board=r.board;renderBoard()}else toast(r.error||'Не удалось отменить действие')});
    });
    updateBoardStatus();
    document.addEventListener('paste', async (e) => {
        if (document.querySelector('.room-tab[data-view="board"]')?.classList.contains('active')) {
            const items = e.clipboardData?.items;
            if (!items) return;
            for (const item of items) {
                if (item.type.indexOf('image') !== -1) {
                    const file = item.getAsFile();
                    const form = new FormData(); form.append('file', file);
                    toast('Загрузка изображения...');
                    const r = await postForm(`/lesson/${lessonId}/studio/board/image`,form);
                    if(!r.success) return toast(r.error||'Ошибка загрузки');
                    const c=$('#os-board'), cx = (-board.camera.x + c.width/2)/board.camera.z, cy = (-board.camera.y + c.height/2)/board.camera.z;
                    const updated=await post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'image',url:r.url,image_width:400,image_height:400,coordinate_space:'canvas',points:[{x:cx,y:cy}]}});
                    if(updated.success){state.board=updated.board;renderBoard()}
                    break;
                }
            }
        }
    });
  }
  
  function renderMaterials(){
    const box=$('#os-materials'), preview=$('#os-material-preview'), materials=data.materials||[];
    const escape=value=>String(value||'').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    const kind=item=>{const name=String(item.name||item.url||'').toLowerCase();return /\.(png|jpe?g|gif|webp|svg)$/.test(name)?'image':/\.pdf$/.test(name)?'pdf':/\.(txt|md|csv|json|py|js|html|css)$/.test(name)?'text':'file'};
    const inlineUrl=url=>`${url}${url.includes('?')?'&':'?'}inline=1`;
    const previewItem=async item=>{if(!preview)return;const type=kind(item),url=String(item.url||''),previewUrl=inlineUrl(url),name=escape(item.name||'Материал');if(type==='image')preview.innerHTML=`<img src="${escape(previewUrl)}" alt="${name}"><a class="room-action" target="_blank" rel="noopener noreferrer" href="${escape(previewUrl)}">Открыть отдельно</a>`;else if(type==='pdf')preview.innerHTML=`<iframe src="${escape(previewUrl)}#view=FitH" title="${name}"></iframe><a class="room-action" target="_blank" rel="noopener noreferrer" href="${escape(previewUrl)}">Открыть PDF отдельно</a>`;else if(type==='text'){preview.innerHTML='<div class="room-preview-loading">Загрузка текста…</div>';try{const response=await fetch(previewUrl);if(!response.ok)throw new Error('fetch');const content=await response.text();preview.innerHTML=`<div class="room-text-preview"><div><strong>${name}</strong><a class="room-action" target="_blank" rel="noopener noreferrer" href="${escape(previewUrl)}">Открыть отдельно</a></div><pre>${escape(content.slice(0,200000))}</pre></div>`}catch(_){preview.innerHTML=`<div><i class="ph-bold ph-file-text"></i><strong>${name}</strong><p>Не удалось загрузить текст для просмотра.</p><a class="room-action room-action-primary" target="_blank" rel="noopener noreferrer" href="${escape(url)}">Скачать файл</a></div>`}}else preview.innerHTML=`<div><i class="ph-bold ph-file-text"></i><strong>${name}</strong><p>Быстрый просмотр недоступен для этого формата.</p><a class="room-action room-action-primary" target="_blank" rel="noopener noreferrer" href="${escape(url)}">Скачать файл</a></div>`};
    if(!materials.length){box.innerHTML='<div class="room-empty-state"><i class="ph-bold ph-folder-open"></i><strong>Материалов пока нет</strong><p>Преподаватель может прикрепить файл для этого урока.</p></div>';return}
    const readableSize=size=>Number(size)>0?`${(Number(size)/1024/1024).toFixed(Number(size)>1024*1024?1:2)} МБ`:'';
    const readableDate=value=>{if(!value)return '';const date=new Date(value);return Number.isNaN(date.getTime())?'':date.toLocaleDateString('ru-RU',{day:'numeric',month:'short'})};
    box.innerHTML=materials.map((item,index)=>`<article class="os-material room-material-card" data-material-index="${index}"><button class="room-material-main" data-material-open="${index}"><i class="ph-bold ${kind(item)==='image'?'ph-image':kind(item)==='pdf'?'ph-file-pdf':kind(item)==='text'?'ph-file-text':'ph-file'}"></i><span>${escape(item.name||'Без названия')}</span><small>${[String(item.type||kind(item)).toUpperCase(),readableSize(item.size),readableDate(item.uploaded_at)].filter(Boolean).join(' · ')||'Файл урока'}</small></button><div class="room-material-actions"><a href="${escape(item.url)}" download title="Скачать" aria-label="Скачать ${escape(item.name||'файл')}"><i class="ph-bold ph-download-simple"></i></a>${teacher?`<button data-material-delete="${index}" title="Удалить" aria-label="Удалить ${escape(item.name||'файл')}"><i class="ph-bold ph-trash"></i></button>`:''}</div></article>`).join('');
    box.querySelectorAll('[data-material-open]').forEach(button=>button.addEventListener('click',()=>{const card=button.closest('.room-material-card');box.querySelectorAll('.room-material-card').forEach(item=>item.classList.toggle('active',item===card));previewItem(materials[Number(button.dataset.materialOpen)])}));
    box.querySelectorAll('[data-material-delete]').forEach(button=>button.addEventListener('click',async()=>{const item=materials[Number(button.dataset.materialDelete)];if(!item||!await confirmRoomAction('Удалить материал?',`Файл «${item.name||'материал'}» исчезнет из урока для всех участников.`))return;const r=await post(`/lesson/${lessonId}/material/delete`,{url:item.url});if(!r.success)return toast(r.error||'Не удалось удалить материал');data.materials=materials.filter(candidate=>candidate.url!==item.url);renderMaterials();toast('Материал удалён')}));
  }
  function renderTheory(){
    const box=$('#os-theory-list'),frame=$('#os-theory-frame'),empty=$('#os-theory-empty'),show=$('#os-theory-show-student'),search=$('#os-theory-search'),items=data.theory_items||[];
    if(!box||!frame)return;
    const escape=value=>String(value||'').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    const query=String(search?.value||'').trim().toLocaleLowerCase('ru-RU');
    const visible=query?items.filter(item=>`${item.title||''} ${item.task_number||''}`.toLocaleLowerCase('ru-RU').includes(query)):items;
    const displayedId=Number(state.active_theory_block_id)||Number(items[0]?.id)||0;
    box.innerHTML=visible.map(item=>`<button class="os-material ${displayedId===Number(item.id)?'active':''}" data-theory-id="${Number(item.id)}" data-theory-url="${escape(item.url)}"><small>${item.task_number ? `Тема ${Number(item.task_number)}` : 'Материал курса'}</small><span>${escape(item.title||'Без названия')}</span></button>`).join('')||'<p class="room-theory-empty-list">По этому запросу материалов нет.</p>';
    const select=id=>{
      const item=items.find(candidate=>Number(candidate.id)===Number(id));
      if(!item)return;
      state.active_theory_block_id=Number(item.id);
      const contentHtml = item.content_html || safeTaskHtml(item.content) || '<p>Материал пока не заполнен.</p>';
      frame.innerHTML=`<header><span class="room-eyebrow">${item.task_number ? `ТЕМА ${Number(item.task_number)}` : 'МАТЕРИАЛ КУРСА'}</span><h2>${escape(item.title||'Без названия')}</h2></header><div class="room-theory-prose theory-prose">${contentHtml}</div>`;
      frame.dataset.blockId=String(item.id);
      frame.classList.remove('hidden');
      empty?.classList.add('hidden');
      show?.classList.toggle('hidden',!teacher);
      renderTheory();
      if(teacher)save({active_theory_block_id:Number(item.id)});
    };
    box.querySelectorAll('[data-theory-id]').forEach(button=>button.onclick=()=>select(button.dataset.theoryId));
    const active=items.find(item=>Number(item.id)===Number(state.active_theory_block_id))||items[0];
    if(active){
      if(frame.dataset.blockId!==String(active.id)){
        const activeHtml = active.content_html || safeTaskHtml(active.content) || '<p>Материал пока не заполнен.</p>';
        frame.innerHTML=`<header><span class="room-eyebrow">${active.task_number ? `ТЕМА ${Number(active.task_number)}` : 'МАТЕРИАЛ КУРСА'}</span><h2>${escape(active.title||'Без названия')}</h2></header><div class="room-theory-prose theory-prose">${activeHtml}</div>`;
        frame.dataset.blockId=String(active.id);
      }
      frame.classList.remove('hidden');empty?.classList.add('hidden');show?.classList.toggle('hidden',!teacher);
    }else{frame.classList.add('hidden');empty?.classList.remove('hidden');show?.classList.add('hidden')}
  }
  
  function bindControls(){
    document.querySelectorAll('.room-tab[data-view]').forEach(b=>b.onclick=()=>activate(b.dataset.view));
    $('#os-theory-search')?.addEventListener('input',renderTheory);
    $('#os-theory-show-student')?.addEventListener('click',()=>{
      const activeId=Number(state.active_theory_block_id);
      if(!teacher||!activeId)return;
      save({active_pane:'theory',active_theory_block_id:activeId,follow_student:true}).then(result=>{
        if(result?.success)toast('Тема открыта у ученика.');
      });
    });
    document.querySelectorAll('[data-phase]').forEach(b=>b.onclick=()=>phaseChange(b.dataset.phase));
    $('#os-timer-toggle')?.addEventListener('click',()=>{const remaining = Math.max(0, state.timer.seconds - Math.floor((Date.now() - new Date(state.timer.updated_at).getTime()) / 1000)); save({timer:{...(state.timer||{}),seconds: state.timer.running ? remaining : state.timer.seconds, running:!state.timer?.running}});});
    document.querySelectorAll('[data-duration]').forEach(i=>i.onchange=()=>{const d={...(state.phase_durations||{})};d[i.dataset.duration]=Math.max(1,Number(i.value)||1)*60;save({phase_durations:d,phase_timers:{...(state.phase_timers||{}),[i.dataset.duration]:d[i.dataset.duration]}})});
    $('#os-follow')?.addEventListener('click',()=>{state.follow_student=!state.follow_student;save({follow_student:state.follow_student,active_pane:document.querySelector('.room-tab.active')?.dataset.view||'work'})});
    $('#os-laser')?.addEventListener('click',()=>{root.classList.toggle('laser-on');toast('Лазер включён: водите курсором по странице')});
    document.addEventListener('pointermove',e=>{if(!root.classList.contains('laser-on')||Date.now()-lastLaserAt<45)return;lastLaserAt=Date.now();post(`/lesson/${lessonId}/studio/pointer`,{kind:'laser',x:e.clientX/window.innerWidth,y:e.clientY/window.innerHeight})});
    $('#os-laser')?.addEventListener('click',()=>{
      const enabled = root.classList.contains('laser-on');
      const button = $('#os-laser');
      button.classList.toggle('os-primary', enabled);
      button.textContent = enabled ? 'Лазер: вкл.' : 'Лазер';
      button.setAttribute('aria-pressed', String(enabled));
    });
    let dailyFrame = null;
    let jitsiApi = null;
    let cachedJoinData = null;
    let dailyTimeoutTimer = null;
    let currentProvider = localUi.videoProvider || 'daily';
    let isCallActive = false;

    const videoDock = $('#room-video-dock');
    const statusDot = $('#os-video-status-dot');
    const activeWrap = $('#os-video-container');
    const placeholder = $('#os-meeting-placeholder');
    const failoverBanner = $('#os-video-failover-banner');
    const dailyContainer = $('#os-daily-container');
    const jitsiContainer = $('#os-jitsi-container');
    const activeLabel = $('#os-video-active-label');

    const setVideoOpen = open => {
      if (!videoDock) return;
      if (open) {
        videoDock.classList.remove('hidden');
        videoDock.style.display = 'flex';
      } else {
        videoDock.classList.add('hidden');
        videoDock.style.display = 'none';
      }
      const toggleBtn = $('#room-video-toggle');
      toggleBtn?.classList.toggle('active', Boolean(open));
      toggleBtn?.setAttribute('aria-pressed', String(Boolean(open)));
      localUi.videoOpen = Boolean(open);
      persistUi();
    };
    const setVideoLarge = large => {
      videoDock?.classList.toggle('is-large', large);
      localUi.videoLarge = large;
      persistUi();
      $('#room-video-size')?.setAttribute('aria-label', large ? 'Уменьшить видеозвонок' : 'Развернуть видеозвонок');
    };
    const setVideoFloating = (position, shouldPersist = true) => {
      if (!videoDock) return;
      const valid = position &&
        Number.isFinite(Number(position.left)) &&
        Number.isFinite(Number(position.top)) &&
        position.left >= 0 && position.left < (window.innerWidth - 80) &&
        position.top >= 0 && position.top < (window.innerHeight - 80);
      videoDock.classList.toggle('is-floating', Boolean(valid));
      videoDock.style.left = valid ? `${Math.round(Number(position.left))}px` : '';
      videoDock.style.top = valid ? `${Math.round(Number(position.top))}px` : '';
      localUi.videoPosition = valid ? { left: Number(position.left), top: Number(position.top) } : null;
      $('#room-video-dock-toggle')?.setAttribute('aria-label', valid ? 'Закрепить видеозвонок справа' : 'Окно закреплено справа');
      if (shouldPersist) persistUi();
    };
    const setVideoCompact = compact => {
      videoDock?.classList.toggle('is-compact', compact);
      localUi.videoCompact = compact;
      persistUi();
      const toggle = $('#room-video-compact-toggle');
      toggle?.classList.toggle('active', compact);
      toggle?.setAttribute('aria-pressed', String(compact));
    };

    function setProviderTab(provider, userTriggered = true) {
      currentProvider = provider;
      if (userTriggered) {
        localUi.videoProvider = provider;
        localUi.videoProviderUserChoice = true;
        persistUi();
        if (teacher) {
          save({ video_provider: provider });
        }
      }
      document.querySelectorAll('.room-video-provider-tab').forEach(tab => {
        const active = tab.dataset.provider === provider;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
      });
      $('#os-placeholder-daily')?.classList.toggle('hidden', provider !== 'daily');
      $('#os-placeholder-jitsi')?.classList.toggle('hidden', provider !== 'jitsi');
      $('#os-placeholder-external')?.classList.toggle('hidden', provider !== 'external');
    }

    document.querySelectorAll('.room-video-provider-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        setProviderTab(tab.dataset.provider, true);
      });
    });

    async function getJoinData(requestedProvider) {
      if (cachedJoinData && cachedJoinData[requestedProvider]) {
        return cachedJoinData[requestedProvider];
      }
      const r = await post(`/lesson/${lessonId}/studio/daily/join`, { provider: requestedProvider });
      if (r) {
        if (!cachedJoinData) cachedJoinData = {};
        cachedJoinData[requestedProvider] = r;
        if (r.jitsi_room) cachedJoinData['jitsi'] = r;
      }
      return r;
    }

    async function resetCalls() {
      if (dailyTimeoutTimer) {
        clearTimeout(dailyTimeoutTimer);
        dailyTimeoutTimer = null;
      }
      if (dailyFrame) {
        try { await dailyFrame.destroy(); } catch (_) {}
        dailyFrame = null;
      }
      if (jitsiApi) {
        try { jitsiApi.dispose(); } catch (_) {}
        jitsiApi = null;
      }
      if (dailyContainer) {
        dailyContainer.style.display = 'none';
        dailyContainer.innerHTML = '';
      }
      if (jitsiContainer) {
        jitsiContainer.style.display = 'none';
        jitsiContainer.innerHTML = '';
      }
      isCallActive = false;
      statusDot?.classList.remove('is-live');
      activeWrap?.classList.add('hidden');
      placeholder?.classList.remove('hidden');
      const dailyBtn = $('#os-meeting-join');
      if (dailyBtn) { dailyBtn.disabled = false; dailyBtn.textContent = 'Подключиться к Daily'; }
      const jitsiBtn = $('#os-meeting-join-jitsi');
      if (jitsiBtn) { jitsiBtn.disabled = false; jitsiBtn.textContent = 'Подключиться к Jitsi'; }
    }

    function showFailoverBanner(message) {
      if (!failoverBanner) return;
      if (message) {
        const textSpan = failoverBanner.querySelector('.room-video-failover-msg span');
        if (textSpan) textSpan.textContent = message;
      }
      failoverBanner.classList.remove('hidden');
    }

    async function connectDaily() {
      const btn = $('#os-meeting-join');
      if (btn) { btn.disabled = true; btn.textContent = 'Подключение...'; }
      await resetCalls();

      const r = await getJoinData('daily');
      if (!r || (!r.room_url && !r.success)) {
        if (btn) { btn.disabled = false; btn.textContent = 'Подключиться к Daily'; }
        toast(r?.error || 'Видеосервер Daily недоступен');
        showFailoverBanner('Daily недоступен на сервере.');
        return;
      }

      if (!window.DailyIframe) {
        if (btn) { btn.disabled = false; btn.textContent = 'Подключиться к Daily'; }
        toast('Видеомодуль Daily не загружен. Переключаем на Jitsi...');
        showFailoverBanner('Модуль Daily не загрузился.');
        setProviderTab('jitsi', true);
        connectJitsi();
        return;
      }

      placeholder?.classList.add('hidden');
      activeWrap?.classList.remove('hidden');
      dailyContainer.style.display = 'block';
      jitsiContainer.style.display = 'none';
      if (activeLabel) activeLabel.textContent = 'Подключение к Daily...';

      dailyTimeoutTimer = setTimeout(() => {
        if (!isCallActive) {
          console.warn('Daily connection timed out - Russian ISP DPI blocking');
          toast('Соединение с Daily сброшено провайдером (ERR_CONNECTION_RESET). Автоматически переключаем на Jitsi...');
          showFailoverBanner('Соединение с Daily сброшено вашим провайдером.');
          setProviderTab('jitsi', true);
          connectJitsi();
        }
      }, 12000);

      try {
        dailyFrame = DailyIframe.createFrame(dailyContainer, {
          showLeaveButton: true,
          iframeStyle: { width: '100%', height: '100%', border: '0' }
        });

        dailyFrame.on('joined-meeting', () => {
          if (dailyTimeoutTimer) { clearTimeout(dailyTimeoutTimer); dailyTimeoutTimer = null; }
          isCallActive = true;
          statusDot?.classList.add('is-live');
          if (activeLabel) activeLabel.textContent = 'В эфире (Daily)';
          failoverBanner?.classList.add('hidden');
        });

        dailyFrame.on('left-meeting', async () => {
          await resetCalls();
        });

        dailyFrame.on('error', async error => {
          console.error('Daily meeting error', error);
          if (dailyTimeoutTimer) { clearTimeout(dailyTimeoutTimer); dailyTimeoutTimer = null; }
          const errStr = String(error?.errorMsg || error?.message || error || '');
          await resetCalls();
          if (errStr.includes('timed out') || errStr.includes('network') || errStr.includes('load') || !errStr) {
            toast('Daily заблокирован провайдером. Автоматически переключаем на защищённый Jitsi...');
            showFailoverBanner('Daily сброшен провайдером.');
            setProviderTab('jitsi', true);
            connectJitsi();
          } else {
            toast('Ошибка камеры или микрофона. Проверьте разрешения в браузере.');
          }
        });

        await dailyFrame.join({ url: r.room_url, token: r.token });
      } catch (error) {
        console.error('Daily join failed', error);
        if (dailyTimeoutTimer) { clearTimeout(dailyTimeoutTimer); dailyTimeoutTimer = null; }
        await resetCalls();
        toast('Провайдер блокирует Daily (ERR_CONNECTION_RESET). Переключаем на Jitsi...');
        showFailoverBanner('Daily заблокирован вашим провайдером.');
        setProviderTab('jitsi', true);
        connectJitsi();
      }
    }

    async function loadJitsiScript() {
      if (window.JitsiMeetExternalAPI) return true;
      return new Promise(resolve => {
        const script = document.createElement('script');
        script.src = 'https://meet.jit.si/external_api.js';
        script.onload = () => resolve(true);
        script.onerror = () => resolve(false);
        document.head.appendChild(script);
      });
    }

    async function connectJitsi() {
      const btn = $('#os-meeting-join-jitsi');
      if (btn) { btn.disabled = true; btn.textContent = 'Подключение...'; }
      await resetCalls();

      const r = await getJoinData('jitsi');
      const roomName = r?.jitsi_room || r?.room_name || `boostudy-lesson-${lessonId}`;
      const domain = r?.jitsi_domain || 'meet.jit.si';
      const displayName = r?.user_name || (teacher ? 'Преподаватель' : 'Ученик');

      const loaded = await loadJitsiScript();
      if (!loaded || !window.JitsiMeetExternalAPI) {
        if (btn) { btn.disabled = false; btn.textContent = 'Подключиться к Jitsi'; }
        return toast('Не удалось загрузить модуль Jitsi Meet. Проверьте сеть.');
      }

      placeholder?.classList.add('hidden');
      activeWrap?.classList.remove('hidden');
      dailyContainer.style.display = 'none';
      jitsiContainer.style.display = 'block';
      if (activeLabel) activeLabel.textContent = 'Подключение к Jitsi (РФ)...';

      try {
        jitsiContainer.innerHTML = '';
        jitsiApi = new window.JitsiMeetExternalAPI(domain, {
          roomName: roomName,
          width: '100%',
          height: '100%',
          parentNode: jitsiContainer,
          userInfo: { displayName: displayName },
          configOverwrite: {
            startWithAudioMuted: false,
            startWithVideoMuted: false,
            prejoinPageEnabled: false,
            disableDeepLinking: true,
            enableWelcomePage: false,
            enableClosePage: false
          },
          interfaceConfigOverwrite: {
            SHOW_JITSI_WATERMARK: false,
            SHOW_WATERMARK_FOR_GUESTS: false,
            SHOW_BRAND_WATERMARK: false,
            TOOLBAR_BUTTONS: [
              'microphone', 'camera', 'desktop', 'chat', 'raisehand',
              'tileview', 'fullscreen', 'hangup'
            ]
          }
        });

        jitsiApi.addEventListener('videoConferenceJoined', () => {
          isCallActive = true;
          statusDot?.classList.add('is-live');
          if (activeLabel) activeLabel.textContent = 'В эфире (Jitsi РФ)';
          failoverBanner?.classList.add('hidden');
        });

        jitsiApi.addEventListener('videoConferenceLeft', async () => {
          await resetCalls();
        });

        jitsiApi.addEventListener('readyToClose', async () => {
          await resetCalls();
        });
      } catch (err) {
        console.error('Jitsi launch error', err);
        await resetCalls();
        toast('Не удалось инициализировать Jitsi Meet.');
      }
    }

    function openExternalTab() {
      if (currentProvider === 'jitsi') {
        const roomName = cachedJoinData?.jitsi?.jitsi_room || `boostudy-lesson-${lessonId}`;
        const domain = cachedJoinData?.jitsi?.jitsi_domain || 'meet.jit.si';
        window.open(`https://${domain}/${roomName}`, '_blank', 'noopener,noreferrer');
      } else if (currentProvider === 'external') {
        const url = String(state.backup_call_url || '').trim();
        if (url) {
          window.open(url, '_blank', 'noopener,noreferrer');
        } else {
          toast('Резервная ссылка ещё не настроена преподавателем.');
        }
      } else {
        if (cachedJoinData?.daily?.room_url) {
          const u = cachedJoinData.daily.room_url + (cachedJoinData.daily.token ? `?t=${cachedJoinData.daily.token}` : '');
          window.open(u, '_blank', 'noopener,noreferrer');
        } else {
          getJoinData('daily').then(r => {
            if (r?.room_url) {
              const u = r.room_url + (r.token ? `?t=${r.token}` : '');
              window.open(u, '_blank', 'noopener,noreferrer');
            } else {
              toast('Не удалось получить ссылку на звонок Daily');
            }
          });
        }
      }
    }

    $('#room-video-toggle')?.addEventListener('click', (e) => {
      e.preventDefault();
      const isClosed = !videoDock || videoDock.classList.contains('hidden') || videoDock.style.display === 'none';
      setVideoOpen(isClosed);
    });
    $('#room-video-close')?.addEventListener('click', () => setVideoOpen(false));
    $('#os-close-video')?.addEventListener('click', () => setVideoOpen(false));
    $('#room-video-size')?.addEventListener('click', () => setVideoLarge(!videoDock?.classList.contains('is-large')));
    $('#room-video-compact-toggle')?.addEventListener('click', () => setVideoCompact(!videoDock?.classList.contains('is-compact')));
    $('#room-video-dock-toggle')?.addEventListener('click', () => setVideoFloating(null));
    $('#room-video-external-win')?.addEventListener('click', openExternalTab);
    $('#os-meeting-join')?.addEventListener('click', connectDaily);
    $('#os-meeting-daily-tab')?.addEventListener('click', () => { currentProvider = 'daily'; openExternalTab(); });
    $('#os-meeting-join-jitsi')?.addEventListener('click', connectJitsi);
    $('#os-meeting-jitsi-tab')?.addEventListener('click', () => { currentProvider = 'jitsi'; openExternalTab(); });
    $('#os-video-failover-btn')?.addEventListener('click', () => { setProviderTab('jitsi', true); connectJitsi(); });
    $('#os-video-hangup')?.addEventListener('click', resetCalls);
    $('#os-video-switch-active-btn')?.addEventListener('click', async () => { await resetCalls(); });

    $('#os-backup-url-save')?.addEventListener('click', async () => {
      const input = $('#os-backup-url-input');
      const val = String(input?.value || '').trim();
      if (!val) return toast('Введите ссылку на видеовстречу');
      const r = await save({ backup_call_url: val });
      if (r && r.success) {
        toast('Резервная ссылка сохранена и отправлена ученику');
      }
    });

    const videoHead = $('#room-video-head');
    videoHead?.addEventListener('pointerdown', event => {
      if (event.target.closest('button')) return;
      const rect = videoDock?.getBoundingClientRect();
      if (!rect || !videoDock) return;
      const offsetX = event.clientX - rect.left, offsetY = event.clientY - rect.top;
      videoHead.setPointerCapture?.(event.pointerId);
      const move = moveEvent => {
        const width = videoDock.offsetWidth, height = videoDock.offsetHeight;
        setVideoFloating({
          left: Math.max(8, Math.min(window.innerWidth - width - 8, moveEvent.clientX - offsetX)),
          top: Math.max(8, Math.min(window.innerHeight - height - 8, moveEvent.clientY - offsetY))
        }, false);
      };
      const done = () => {
        persistUi();
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', done);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', done);
    });

    if (localUi.videoOpen === true) setVideoOpen(true);
    if (localUi.videoLarge === true) setVideoLarge(true);
    if (localUi.videoCompact === true) setVideoCompact(true);
    if (localUi.videoPosition) setVideoFloating(localUi.videoPosition);
    if (currentProvider) setProviderTab(currentProvider, false);
    const materialFile=$('#os-material-file'),materialUpload=$('#os-material-upload'),materialDropzone=$('#os-material-dropzone');
    const chooseMaterial=file=>{if(!file||!materialFile)return;const transfer=new DataTransfer();transfer.items.add(file);materialFile.files=transfer.files;materialUpload.disabled=false;materialDropzone?.classList.add('has-file');if(materialDropzone)materialDropzone.querySelector('span').textContent=file.name};
    $('#os-material-pick')?.addEventListener('click',()=>materialFile?.click());
    materialFile?.addEventListener('change',()=>chooseMaterial(materialFile.files?.[0]));
    materialDropzone?.addEventListener('click',()=>materialFile?.click());
    ['dragenter','dragover'].forEach(name=>materialDropzone?.addEventListener(name,event=>{event.preventDefault();materialDropzone.classList.add('is-dragging')}));
    ['dragleave','drop'].forEach(name=>materialDropzone?.addEventListener(name,event=>{event.preventDefault();materialDropzone.classList.remove('is-dragging')}));
    materialDropzone?.addEventListener('drop',event=>chooseMaterial(event.dataTransfer?.files?.[0]));
    materialUpload?.addEventListener('click',async()=>{const f=materialFile?.files?.[0];if(!f)return;materialUpload.disabled=true;materialUpload.textContent='Загрузка…';const form=new FormData();form.append('file',f);const r=await postForm(`/lesson/${lessonId}/upload`,form);materialUpload.textContent='Прикрепить';if(r.success){data.materials.push(r.material);materialFile.value='';materialUpload.disabled=true;if(materialDropzone){materialDropzone.classList.remove('has-file');materialDropzone.querySelector('span').textContent='Перетащите файл сюда'}renderMaterials();toast('Материал прикреплён')}else{materialUpload.disabled=false;toast(r.error||'Не удалось прикрепить материал')}});
    const panel=$('#room-col-sidebar') || $('#room-lesson-panel');
    const layout=$('#room-main-layout') || $('#room-canvas');
    const taskPanel=$('#room-col-task') || $('#room-task-panel');
    const isMobile=()=>window.matchMedia('(max-width: 820px)').matches;

    const setPanel=open=>{
      panel?.classList.toggle('is-collapsed',!open);
      layout?.classList.toggle('sidebar-collapsed',!open);
      const btn=$('#room-panel-toggle');
      btn?.setAttribute('aria-expanded',String(open));
      btn?.classList.toggle('active',open);
      localUi.lessonPanelOpen=open;
      persistUi();
    };
    $('#room-panel-toggle')?.addEventListener('click',()=>setPanel(panel?.classList.contains('is-collapsed')));
    $('#room-panel-close')?.addEventListener('click',()=>setPanel(false));
    if(localUi.lessonPanelOpen!==false)setPanel(true);else setPanel(false);

    const taskPanelIsOpen=()=>isMobile()?taskPanel?.classList.contains('is-open'):!taskPanel?.classList.contains('is-collapsed');
    const setTaskPanel=open=>{
      taskPanel?.classList.toggle('is-open',open);
      taskPanel?.classList.toggle('is-collapsed',!open);
      layout?.classList.toggle('tasks-collapsed',!open);
      const btn=$('#room-task-toggle');
      btn?.setAttribute('aria-expanded',String(open));
      btn?.classList.toggle('active',open);
      localUi.taskPanelOpen=open;
      persistUi();
    };
    $('#room-task-toggle')?.addEventListener('click',()=>setTaskPanel(!taskPanelIsOpen()));
    $('#room-task-close')?.addEventListener('click',()=>setTaskPanel(false));
    if(localUi.taskPanelOpen!==false)setTaskPanel(true);else setTaskPanel(false);
    const setFocusMode=enabled=>{
      root.classList.toggle('room-focus-mode',enabled);
      const icon = $('#os-focus-toggle i');
      if (icon) {
        icon.className = enabled ? 'ph-bold ph-corners-in text-base' : 'ph-bold ph-corners-out text-base';
      }
      $('#os-focus-toggle')?.setAttribute('aria-pressed',String(enabled));
      $('#os-focus-toggle')?.setAttribute('title',enabled?'Выйти из фокуса':'Сфокусироваться на задаче');
      localUi.focusMode=enabled;persistUi();
    };
    $('#os-focus-toggle')?.addEventListener('click',()=>setFocusMode(!root.classList.contains('room-focus-mode')));
    if(localUi.focusMode===true)setFocusMode(true);
    const setWidths=()=>{if(Number(localUi.leftWidth))root.style.setProperty('--room-left-width',`${localUi.leftWidth}px`);if(Number(localUi.rightWidth))root.style.setProperty('--room-right-width',`${localUi.rightWidth}px`)};
    setWidths();
    const resizePanel=(side,event)=>{if(window.innerWidth<=1180)return;event.preventDefault();const startX=event.clientX,start=side==='left'?(Number(localUi.leftWidth)||250):(Number(localUi.rightWidth)||320);const move=e=>{const delta=e.clientX-startX;const minimum=side==='left'?190:280;const width=Math.max(minimum,Math.min(420,side==='left'?start+delta:start-delta));localUi[side==='left'?'leftWidth':'rightWidth']=width;root.style.setProperty(side==='left'?'--room-left-width':'--room-right-width',`${width}px`)};const done=()=>{persistUi();window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',done)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',done)};
    taskPanel?.addEventListener('pointerdown',event=>{if(event.target.closest('button,a,input,textarea'))return;if(event.offsetX<taskPanel.clientWidth-12)return;resizePanel('left',event)});
    panel?.addEventListener('pointerdown',event=>{if(event.target.closest('button,a,input,textarea,select,summary,details,label'))return;if(event.offsetX>12)return;resizePanel('right',event)});
    const saveIndicator=$('#room-notes-save-indicator');
    const setSavingStatus=status=>{
      if(!saveIndicator)return;
      if(status==='saving'){
        saveIndicator.innerHTML='<i class="ph-bold ph-spinner animate-spin text-amber-500"></i> Сохранение...';
      }else if(status==='saved'){
        saveIndicator.innerHTML='<i class="ph-fill ph-check-circle text-emerald-500"></i> Сохранено автоматически';
      }else if(status==='error'){
        saveIndicator.innerHTML='<i class="ph-fill ph-warning-circle text-rose-500"></i> Ошибка сохранения';
      }
    };
    const note=$('#room-teacher-note');
    if(note){
      note.value=state.teacher_private_note||'';
      let noteTimer=null;
      note.addEventListener('input',()=>{
        setSavingStatus('saving');
        clearTimeout(noteTimer);
        noteTimer=setTimeout(async()=>{
          const r=await save({teacher_private_note:note.value});
          setSavingStatus(r?.success?'saved':'error');
        },800);
      });
      note.addEventListener('change',()=>save({teacher_private_note:note.value}));
    }
    const guidanceEditor=$('#room-guidance');if(guidanceEditor)guidanceEditor.addEventListener('change',()=>{state.guidance={...(state.guidance||{}),next_step:guidanceEditor.value};save({guidance:state.guidance})});
    const homework=$('#room-homework');if(homework){homework.value=state.outcome?.homework||'';homework.addEventListener('change',()=>{state.outcome={...(state.outcome||{}),homework:homework.value};if(teacher)save({outcome:state.outcome})})}
    const studentNotes=$('#room-student-notes');
    if(studentNotes){
      studentNotes.value=data.student_notes||'';
      let sNoteTimer=null;
      studentNotes.addEventListener('input',()=>{
        setSavingStatus('saving');
        clearTimeout(sNoteTimer);
        sNoteTimer=setTimeout(async()=>{
          const r=await post(`/lesson/${lessonId}/studio/student-notes`,{notes:studentNotes.value});
          if(r.success){
            data.student_notes=r.notes||studentNotes.value;
            setSavingStatus('saved');
          }else{
            setSavingStatus('error');
          }
        },800);
      });
      $('#room-student-notes-save')?.addEventListener('click',async()=>{
        setSavingStatus('saving');
        const r=await post(`/lesson/${lessonId}/studio/student-notes`,{notes:studentNotes.value});
        if(r.success){
          data.student_notes=r.notes||studentNotes.value;
          setSavingStatus('saved');
          toast('Личные заметки сохранены');
        }else{
          setSavingStatus('error');
          toast(r.error||'Не удалось сохранить заметки');
        }
      });
    }
    document.querySelectorAll('[data-student-signal]').forEach(button=>button.addEventListener('click',async()=>{if(button.disabled)return;const signal=button.dataset.studentSignal;button.disabled=true;const r=await post('/lesson/'+lessonId+'/studio/signal',{signal});button.disabled=false;if(r.success){state=r.state||state;render();toast(signalLabels[signal]+': преподаватель увидит это сразу')}else toast(r.error||'Не удалось отправить статус')}));
    $('#room-checkpoint-save')?.addEventListener('click',async()=>{const understanding=Number($('#room-checkpoint-understanding')?.value);if(!understanding)return toast('Оцените понимание темы');const r=await post(`/lesson/${lessonId}/studio/checkpoint`,{understanding,blocker:$('#room-checkpoint-blocker')?.value||''});if(r.success){state=r.state||state;toast('Самооценка отправлена');render()}else toast(r.error||'Не удалось отправить самооценку')});

    const goPrev=()=>{const idx=tasks.findIndex(item=>item.lesson_task_id===activeTask);if(idx>0)openTask(tasks[idx-1].lesson_task_id);};
    const goNext=()=>{const idx=tasks.findIndex(item=>item.lesson_task_id===activeTask);if(idx>=0&&idx<tasks.length-1)openTask(tasks[idx+1].lesson_task_id);};
    $('#room-task-prev')?.addEventListener('click',goPrev);
    $('#room-task-next')?.addEventListener('click',goNext);
    $('#room-btn-prev-task')?.addEventListener('click',goPrev);
    $('#room-btn-next-task')?.addEventListener('click',goNext);

    $('#os-reset-code')?.addEventListener('click',async()=>{
      const task=tasks.find(t=>t.lesson_task_id===activeTask);
      const defaultCode=(task&&(task.starter_code||(task.task&&task.task.starter_code)))||'';
      const ok=await confirmRoomAction('Сбросить код?','Код в редакторе будет сброшен к исходному шаблону задачи. Это действие синхронизируется у обоих участников.','Сбросить');
      if(!ok)return;
      const editor=$('#os-code');if(!editor)return;
      editor.value=defaultCode;
      workspace.lastSentCode=defaultCode;
      workspace.pendingOps=[];
      refreshCodeHighlight();
      refreshGutter();
      if(workspace.socket&&workspace.id){
        workspace.socket.emit('workspace_patch',{...ctx(),base_version:workspace.version,full_code:defaultCode,next:defaultCode,op_id:crypto.randomUUID(),updated_at:Date.now()});
      }
      toast('Код сброшен');
    });

    $('#os-copy-console')?.addEventListener('click',async()=>{
      const out=$('#os-output')?.textContent||'';
      if(!out.trim())return toast('Консоль пуста');
      try{await navigator.clipboard.writeText(out);toast('Вывод скопирован в буфер обмена');}catch(_){toast('Не удалось скопировать вывод');}
    });

    document.querySelectorAll('[data-editor-tab]').forEach(tab=>{
      tab.addEventListener('click',()=>{
        const target=tab.dataset.editorTab;
        document.querySelectorAll('[data-editor-tab]').forEach(t=>{
          const isActive = t.dataset.editorTab===target;
          t.classList.toggle('active',isActive);
          t.setAttribute('aria-selected', String(isActive));
        });
        const codeWrap=$('.room-code-surface-wrap');
        const resultPane=$('#os-result-pane');
        if(target==='result'){
          if(codeWrap)codeWrap.classList.add('hidden');
          if(resultPane)resultPane.classList.remove('hidden');
        }else{
          if(codeWrap)codeWrap.classList.remove('hidden');
          if(resultPane)resultPane.classList.add('hidden');
        }
      });
    });

    $('#os-finish-view')?.addEventListener('click',()=>{
      const outcome=state.outcome||{};
      const toLines=val=>Array.isArray(val)?val.join('\n'):String(val||'');
      const comp=toLines(outcome.completed), rep=toLines(outcome.repeat), hw=String(outcome.homework||'').trim();
      if(!comp&&!rep&&!hw)return toast('Преподаватель зафиксирует итоги в конце занятия');
      $('#os-outcome-completed').value=comp;
      $('#os-outcome-repeat').value=rep;
      $('#os-outcome-homework').value=hw;
      $('#os-outcome-private-note')?.closest('label')?.classList.add('hidden');
      $('#os-finish-confirm')?.classList.add('hidden');
      const finishTitle=$('#os-finish-title');if(finishTitle)finishTitle.textContent='Итоги урока';
      setModalVisible($('#os-finish-modal'),true,$('#os-finish-cancel'));
    });
    
    const lines=value=>Array.isArray(value)?value.join('\n'):'';
    $('#os-start-lesson')?.addEventListener('click', async () => {
      const btn = $('#os-start-lesson');
      if (btn) btn.disabled = true;
      try {
        const r = await post(`/lesson/${lessonId}/start`, {});
        if (r && r.success) {
          toast('Урок начался! Ученик теперь может войти в комнату');
          btn?.classList.add('hidden');
          $('#os-finish')?.classList.remove('hidden');
          const timerBtn = $('#os-timer-toggle');
          if (timerBtn && !state?.timer?.running) {
            timerBtn.click();
          }
        } else {
          toast(r?.error || 'Не удалось начать урок');
          if (btn) btn.disabled = false;
        }
      } catch (err) {
        toast('Ошибка соединения при старте урока');
        if (btn) btn.disabled = false;
      }
    });
    $('#os-finish')?.addEventListener('click', () => {const outcome=state.outcome||{};$('#os-outcome-completed').value=lines(outcome.completed);$('#os-outcome-repeat').value=lines(outcome.repeat);$('#os-outcome-homework').value=outcome.homework||$('#room-homework')?.value||'';$('#os-outcome-private-note').value=$('#room-teacher-note')?.value||state.teacher_private_note||'';setModalVisible($('#os-finish-modal'),true,$('#os-outcome-completed'))});
    $('#os-finish-cancel')?.addEventListener('click', () => setModalVisible($('#os-finish-modal'),false));
    $('#os-finish-confirm')?.addEventListener('click', async () => {
      setModalVisible($('#os-finish-modal'),false);
      const toList=value=>String(value||'').split(/\r?\n/).map(item=>item.trim()).filter(Boolean);
      const outcome={completed:toList($('#os-outcome-completed')?.value),repeat:toList($('#os-outcome-repeat')?.value),homework:$('#os-outcome-homework')?.value||''};
      const privateNote=$('#os-outcome-private-note')?.value||'';
      if(privateNote!==String(state.teacher_private_note||'')){const noteSave=await save({teacher_private_note:privateNote});if(!noteSave?.success)return;}
      const r = await post(`/lesson/${lessonId}/studio/finish`, {outcome});
      if(r.success){ toast('Урок завершён'); state = r.state || state; render(); }
      else toast(r.error || 'Не удалось завершить урок');
    });
    function bindAddTaskModal() {
      const modal = $('#room-add-task-modal');
      if (!modal) return;
      const openBtn = $('#room-open-add-task-modal');
      const closeBtn = $('#room-add-task-close');
      const tabBankBtn = $('#room-add-tab-bank-btn');
      const tabCustomBtn = $('#room-add-tab-custom-btn');
      const tabBank = $('#room-add-tab-bank');
      const tabCustom = $('#room-add-tab-custom');

      const openModal = () => setModalVisible(modal, true);
      const closeModal = () => setModalVisible(modal, false);

      openBtn?.addEventListener('click', openModal);
      closeBtn?.addEventListener('click', closeModal);

      const switchTab = toBank => {
        tabBank?.classList.toggle('hidden', !toBank);
        tabCustom?.classList.toggle('hidden', toBank);
        if (tabBankBtn) {
          tabBankBtn.className = toBank
            ? 'flex-1 py-1.5 px-3 text-xs font-bold rounded-lg transition-all border-0 bg-white text-indigo-600 shadow-xs cursor-pointer'
            : 'flex-1 py-1.5 px-3 text-xs font-bold rounded-lg transition-all border-0 bg-transparent text-slate-600 hover:text-slate-900 cursor-pointer';
        }
        if (tabCustomBtn) {
          tabCustomBtn.className = !toBank
            ? 'flex-1 py-1.5 px-3 text-xs font-bold rounded-lg transition-all border-0 bg-white text-indigo-600 shadow-xs cursor-pointer'
            : 'flex-1 py-1.5 px-3 text-xs font-bold rounded-lg transition-all border-0 bg-transparent text-slate-600 hover:text-slate-900 cursor-pointer';
        }
      };
      tabBankBtn?.addEventListener('click', () => switchTab(true));
      tabCustomBtn?.addEventListener('click', () => switchTab(false));

      // Bank search
      const numSelect = $('#room-task-search-num');
      const queryInput = $('#room-task-search-query');
      const searchBtn = $('#room-task-search-btn');
      const resultsContainer = $('#room-task-search-results');

      const performSearch = async () => {
        if (!resultsContainer) return;
        const taskNum = numSelect?.value || '';
        const query = queryInput?.value?.trim() || '';
        resultsContainer.innerHTML = '<p class="text-xs text-slate-500 text-center py-4"><i class="ph-bold ph-spinner animate-spin mr-1"></i> Поиск заданий...</p>';
        try {
          const resp = await fetch(`/lesson/${lessonId}/search-tasks?task_number=${encodeURIComponent(taskNum)}&query=${encodeURIComponent(query)}`);
          const json = await resp.json();
          if (!json.success || !json.tasks?.length) {
            resultsContainer.innerHTML = '<p class="text-xs text-slate-400 text-center py-6">Ничего не найдено. Попробуйте изменить фильтры.</p>';
            return;
          }
          resultsContainer.innerHTML = '';
          json.tasks.forEach(item => {
            const card = document.createElement('div');
            card.className = 'p-3 bg-slate-50 hover:bg-indigo-50/40 rounded-xl border border-slate-200/80 transition-all flex flex-col gap-2';
            card.innerHTML = `
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-black uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-100">
                  №${item.task_number} · ID #${item.id}
                </span>
                <span class="text-[11px] text-slate-400">${item.source || ''}</span>
              </div>
              <p class="text-xs text-slate-700 line-clamp-3 font-medium m-0 leading-relaxed">${codeEscape(item.preview)}</p>
              <div class="flex items-center justify-between pt-1 border-t border-slate-100">
                <span class="text-[11px] text-slate-500 font-mono">Ответ: <b>${codeEscape(item.answer || '—')}</b></span>
                <button type="button" class="room-action room-action-primary text-xs py-1 px-2.5 rounded-lg add-btn">
                  <i class="ph-bold ph-plus"></i> Добавить
                </button>
              </div>
            `;
            card.querySelector('.add-btn')?.addEventListener('click', async (e) => {
              const btn = e.currentTarget;
              btn.disabled = true;
              btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i>';
              try {
                const addResp = await post(`/lesson/${lessonId}/quick-add-task`, {task_id: item.id});
                if (addResp.success) {
                  closeModal();
                  toast('Задание добавлено в урок');
                  if (addResp.tasks) tasks = addResp.tasks;
                  else if (addResp.task) tasks.push(addResp.task);
                  if (addResp.task?.lesson_task_id) openTask(addResp.task.lesson_task_id);
                  else renderTasks();
                } else {
                  toast(addResp.error || 'Ошибка при добавлении задания');
                  btn.disabled = false;
                  btn.innerHTML = '<i class="ph-bold ph-plus"></i> Добавить';
                }
              } catch(err) {
                toast('Ошибка сети при добавлении');
                btn.disabled = false;
                btn.innerHTML = '<i class="ph-bold ph-plus"></i> Добавить';
              }
            });
            resultsContainer.appendChild(card);
          });
        } catch(err) {
          resultsContainer.innerHTML = '<p class="text-xs text-rose-500 text-center py-4">Ошибка запроса к банку задач</p>';
        }
      };

      searchBtn?.addEventListener('click', performSearch);
      queryInput?.addEventListener('keydown', e => { if (e.key === 'Enter') performSearch(); });
      numSelect?.addEventListener('change', performSearch);

      // Custom task creation
      const customNum = $('#room-custom-num');
      const customAnswer = $('#room-custom-answer');
      const customContent = $('#room-custom-content');
      const customCode = $('#room-custom-code');
      const customSubmit = $('#room-custom-submit');

      customSubmit?.addEventListener('click', async () => {
        const content = customContent?.value?.trim();
        if (!content) {
          toast('Пожалуйста, введите условие задания');
          customContent?.focus();
          return;
        }
        customSubmit.disabled = true;
        customSubmit.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i> Создание...';
        try {
          const payload = {
            custom: true,
            task_number: customNum?.value || 1,
            answer: customAnswer?.value?.trim() || '',
            content: content,
            code_template: customCode?.value || ''
          };
          const resp = await post(`/lesson/${lessonId}/quick-add-task`, payload);
          if (resp.success) {
            closeModal();
            toast('Собственное задание создано и добавлено');
            if (customContent) customContent.value = '';
            if (customAnswer) customAnswer.value = '';
            if (customCode) customCode.value = '';
            if (resp.tasks) tasks = resp.tasks;
            else if (resp.task) tasks.push(resp.task);
            if (resp.task?.lesson_task_id) openTask(resp.task.lesson_task_id);
            else renderTasks();
          } else {
            toast(resp.error || 'Ошибка при создании задания');
          }
        } catch(err) {
          toast('Ошибка сети при создании задания');
        } finally {
          customSubmit.disabled = false;
          customSubmit.innerHTML = '<i class="ph-bold ph-plus"></i> Добавить в урок';
        }
      });
    }

    bindAddTaskModal();
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){const finishModal=$('#os-finish-modal'),confirmModal=$('#room-confirm-modal'),addTaskModal=$('#room-add-task-modal');if(!finishModal?.classList.contains('hidden'))setModalVisible(finishModal,false);if(!confirmModal?.classList.contains('hidden'))$('#room-confirm-cancel')?.click();if(!addTaskModal?.classList.contains('hidden'))setModalVisible(addTaskModal,false);if(root.classList.contains('room-focus-mode'))$('#os-focus-toggle')?.click();return}const tag=document.activeElement?.tagName;if(['INPUT','TEXTAREA','SELECT'].includes(tag)||event.altKey||event.ctrlKey||event.metaKey)return;if(event.key==='1')activate('work');if(event.key==='2')activate('theory');if(event.key==='3')activate('board');if(event.key==='4')activate('materials');if(event.key.toLowerCase()==='v')setVideoOpen(!videoDock?.classList.contains('hidden'));if(event.key.toLowerCase()==='f'&&teacher)$('#os-follow')?.click()});
  }

  function handleLessonFinished(payload) {
    if (teacher) return;
    let overlay = $('#room-finished-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'room-finished-overlay';
      overlay.className = 'room-finished-backdrop';
      overlay.innerHTML = `
        <div class="room-finished-card">
          <div class="room-finished-icon-squircle">
            <i class="ph-fill ph-check-circle"></i>
          </div>
          <h2>Урок завершён!</h2>
          <p>${codeEscape(payload?.message || 'Преподаватель завершил данный урок. Отличная работа! Сейчас вы будете перенаправлены в расписание.')}</p>
          <div class="room-finished-actions">
            <a href="${payload?.redirect_url || '/schedule'}" class="room-action is-primary" id="room-finished-exit-btn">
              Перейти в расписание (<span id="room-finished-countdown">5</span>с)
            </a>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      let secondsLeft = 5;
      const countdownEl = overlay.querySelector('#room-finished-countdown');
      const timer = setInterval(() => {
        secondsLeft -= 1;
        if (countdownEl) countdownEl.textContent = String(secondsLeft);
        if (secondsLeft <= 0) {
          clearInterval(timer);
          window.location.href = payload?.redirect_url || '/schedule';
        }
      }, 1000);
    }
  }

  const lessonSocket=io('/lesson');
  lessonSocket.on('connect',()=>{setConnection('connected');lessonSocket.emit('join_lesson',{lesson_id:lessonId});refreshStudioState()});
  lessonSocket.on('disconnect',()=>setConnection('disconnected'));
  lessonSocket.on('connect_error',()=>setConnection('disconnected'));
  lessonSocket.io.on('reconnect_attempt',()=>setConnection('connecting'));
  lessonSocket.on('lesson_finished', handleLessonFinished);
  lessonSocket.on('board_stroke', p => {
    if (p.lesson_id !== lessonId || !p.stroke) return;
    if (!state.board) state.board = {strokes: []};
    if (!state.board.strokes) state.board.strokes = [];
    state.board.strokes.push(p.stroke);
    const canvas = $('#os-board');
    if (canvas && !canvas.closest('.hidden')) {
      draw(p.stroke);
    }
  });
  lessonSocket.on('board_action', p => {
    if (p.lesson_id !== lessonId) return;
    if (p.action === 'clear') {
      if (state.board) state.board.strokes = [];
      const canvas = $('#os-board');
      if (canvas && !canvas.closest('.hidden')) renderBoard();
    } else if (p.action === 'undo') {
      if (state.board?.strokes?.length) {
        state.board.strokes.pop();
        const canvas = $('#os-board');
        if (canvas && !canvas.closest('.hidden')) renderBoard();
      }
    }
  });
  lessonSocket.on('lesson_tasks_updated', p => {
    if (p.lesson_id !== lessonId) return;
    tasks = p.tasks || [];
    if (!tasks.length) {
      setupEmptyTaskState();
    } else {
      const currentExists = tasks.some(t => String(t.lesson_task_id) === String(activeTask));
      if (!currentExists) {
        openTask(tasks[tasks.length - 1].lesson_task_id);
      } else {
        renderTasks();
        const taskIndex = tasks.findIndex(item => String(item.lesson_task_id) === String(activeTask));
        const counterText = $('#room-task-counter-text');
        if (counterText) counterText.textContent = `Задание ${taskIndex + 1} из ${Math.max(1, tasks.length)}`;
      }
    }
  });
  lessonSocket.on('lesson_studio_updated',p=>{
    if(p.lesson_id!==lessonId)return;
    if(p.status === 'completed' || p.state?.status === 'completed') {
      handleLessonFinished(p);
    }
    const previousPane=state.active_pane,previousFollow=state.follow_student;
    state=teacher?{...state,...p.state}:p.state;
    render();
    if(!teacher && state.active_task_id && String(state.active_task_id) !== String(activeTask)){
      openTask(state.active_task_id);
    }
    if(!teacher&&state.follow_student&&(!hasExplicitWorkspaceChoice||state.active_pane!==previousPane||!previousFollow))activate(state.active_pane||'work',true);
  });
  lessonSocket.on('lesson_studio_pointer',p=>{
    if(p.lesson_id!==lessonId)return;
    let x=$('#os-pointer');
    if(!x){x=document.createElement('div');x.id='os-pointer';document.body.append(x);}
    x.dataset.author=p.pointer.name||p.pointer.author||'Участник';
    x.style.transform = `translate(${p.pointer.x * window.innerWidth}px, ${p.pointer.y * window.innerHeight}px)`;
    clearTimeout(x.t);x.t=setTimeout(()=>x.remove(),850);
  });
  
  function tick(){
    if(state.timer?.running){
        let elapsed = Math.floor((Date.now() - new Date(state.timer.updated_at).getTime()) / 1000);
        let remaining = Math.max(0, state.timer.seconds - elapsed);
        $('#os-timer').textContent = fmt(remaining);
        
        if (remaining === 0) {
            state.timer.running = false;
            if(teacher) save({timer:state.timer});
            toast('Время вышло!');
        }
    } else {
        const timerEl = $('#os-timer');
        if (timerEl) timerEl.textContent = fmt(getDisplayTimerSeconds());
    }
    setTimeout(tick, 1000);
}
  
  bindWorkspace();
  bindBoard();
  bindControls();
  if(tasks && tasks.length > 0){
    activeTask=state.active_task_id||tasks[0]?.lesson_task_id;
    render();
    if(activeTask) openTask(activeTask);
  } else {
    render();
    setupEmptyTaskState();
  }
  const requestedPane=new URLSearchParams(window.location.search).get('pane');
  if(requestedPane){hasExplicitWorkspaceChoice=true;localUi.activeWorkspace=requestedPane;persistUi()}
  activate(requestedPane||localUi.activeWorkspace||state.active_pane||'work',true);
  if (!teacher && (data.lesson_status === 'completed' || state.status === 'completed')) {
    handleLessonFinished();
  }
  tick();
})();
