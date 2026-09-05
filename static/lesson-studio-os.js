(() => {
  const root = document.querySelector('#lesson-studio-os'); if (!root || !window.io) return;
  const raw = document.querySelector('#studio-os-data'); const data = raw ? JSON.parse(raw.textContent) : {};
  const lessonId = Number(root.dataset.lessonId), teacher = root.dataset.teacher === 'true', csrf = document.querySelector('meta[name="csrf-token"]')?.content || '', clientId = crypto.randomUUID();
  let state = data.state || {}, tasks = typeof data.tasks === 'string' ? JSON.parse(data.tasks) : (data.tasks || []), activeTask = null, workspace = {id:null, version:0, socket:null, applying:false}, board = {tool:'pen',color:'#312e81',width:4,drawing:null,drag:null,camera:{x:0,y:0,z:1}}, lastLaserAt = 0;
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
    if(!remote && teacher && state.follow_student) save({active_pane:view,follow_student:true});
  }
  
  function render(){
    const timer=state.timer||{}, phase=state.phase||'preparation';
    $('#os-timer').textContent=fmt(timer.seconds);
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
    const agendaBox=$('#room-agenda');if(agendaBox){const agenda=Array.isArray(state.agenda)?state.agenda:[];agendaBox.innerHTML=agenda.map((item,index)=>`<label><input type="checkbox" data-agenda-index="${index}" ${item.done?'checked':''} ${teacher?'':'disabled'}><span>${String(item.title||'Шаг урока').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]))}</span></label>`).join('')||'<p>План пока не задан.</p>';agendaBox.querySelectorAll('[data-agenda-index]').forEach(input=>input.addEventListener('change',()=>{if(!teacher)return;const agenda=(state.agenda||[]).map((item,index)=>({...item,done:index===Number(input.dataset.agendaIndex)?input.checked:Boolean(item.done)}));save({agenda})}))}
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
  }
  
  function renderTasks(){const box=$('#os-task-list');box.innerHTML='';$('#os-task-count').textContent=`${tasks.length} шт.`;if(!tasks.length){box.innerHTML='<div class="room-task-empty"><i class="ph-bold ph-list-checks"></i><strong>Заданий пока нет</strong><p>Преподаватель добавит их из генератора или урока.</p></div>';return}tasks.forEach((t,i)=>{const b=document.createElement('button');b.className=`room-task ${activeTask===t.lesson_task_id?'active':''}`;b.innerHTML=`<small>${i+1} · ${t.status||'pending'}</small><b>${t.title}</b>`;b.onclick=()=>openTask(t.lesson_task_id);box.append(b)})}
  function openTask(id){const task=tasks.find(x=>x.lesson_task_id===Number(id));if(!task)return;activeTask=task.lesson_task_id;const taskIndex=tasks.findIndex(item=>item.lesson_task_id===activeTask);$('#os-task-title').textContent=task.title;$('#os-task-body').innerHTML=safeTaskHtml(task.description)||'Условие отсутствует.';$('#os-task-status').textContent=task.status||'В очереди';$('#room-mission-progress').textContent=`Шаг ${taskIndex+1} из ${tasks.length}`;$('#room-mission-badge').innerHTML=`<i class="ph-bold ph-sparkle"></i> ${task.status==='completed'?'Задача завершена':'Фокус: одна задача'}`;renderTasks();if(teacher)save({active_task_id:id});connectWorkspace(id)}
  
  function ctx(){return {context_type:'lesson_task',context_id:workspace.id,client_id:clientId}}
  const codeEscape=value=>String(value||'').replace(/[&<>]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[char]));
  function highlightPython(value){const source=String(value||''),tokens=/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|print|range|len|str|int|float|list|dict|set)\b)/g;let result='',cursor=0,match;while((match=tokens.exec(source))){result+=codeEscape(source.slice(cursor,match.index));const token=match[0],kind=token.startsWith('#')?'comment':token.startsWith('"')||token.startsWith("'")?'string':/^\d/.test(token)?'number':/^(print|range|len|str|int|float|list|dict|set)$/.test(token)?'builtin':'keyword';result+=`<span class="os-token-${kind}">${codeEscape(token)}</span>`;cursor=match.index+token.length}return result+codeEscape(source.slice(cursor));}
  function refreshCodeHighlight(){const editor=$('#os-code'),layer=$('#os-code-highlight');if(!editor||!layer)return;layer.innerHTML=`<code>${highlightPython(editor.value)}\n</code>`;layer.scrollTop=editor.scrollTop;layer.scrollLeft=editor.scrollLeft;}
  function connectWorkspace(id){workspace.id=id;$('#os-code').value='';$('#os-answer').value='';refreshCodeHighlight();$('#os-output').textContent='Подключаемся к совместному коду…';if(!workspace.socket){workspace.socket=io('/task-workspace');workspace.socket.on('connect',()=>workspace.socket.emit('join_workspace',ctx()));workspace.socket.on('workspace_snapshot',p=>applySnapshot(p.state));workspace.socket.on('workspace_patch',p=>{if(p.client_id===clientId||!p.code_after)return;workspace.applying=true;$('#os-code').value=p.code_after;refreshCodeHighlight();workspace.applying=false;workspace.version=p.version||workspace.version});workspace.socket.on('workspace_presence',p=>$('#os-presence').textContent=(p.participants||[]).map(x=>x.display_name||x.username).join(' · ')||'Нет участников')}else if(workspace.socket.connected)workspace.socket.emit('join_workspace',ctx());}
  function applySnapshot(s){if(!s)return;workspace.applying=true;$('#os-code').value=s.code||'';$('#os-answer').value=s.answer||'';refreshCodeHighlight();workspace.applying=false;workspace.version=s.version||0;$('#os-presence').textContent='Совместный режим'}
  async function run(){
    const output=$('#os-output'), button=$('#os-run'), code=$('#os-code')?.value||'';
    if(!workspace.id){
      const selected=tasks.find(task=>task.lesson_task_id===activeTask)||tasks[0];
      if(!selected){
        output.textContent='Сначала преподаватель должен добавить задачу в урок.';
        return toast('Для запуска нужен выбранный материал задачи.');
      }
      openTask(selected.lesson_task_id);
    }
    if(!workspace.id){
      output.textContent='Не удалось подключить рабочее пространство задачи.';
      return toast('Не удалось открыть рабочее пространство. Выберите задачу ещё раз.');
    }
    if(!code.trim()){
      output.textContent='Напишите код перед запуском.';
      return toast('Код пока пустой.');
    }
    if(button){button.disabled=true;button.textContent='Запуск…'}
    output.textContent='Запускаем код…';
    try{
      const r=await post('/task-workspace/api/run',{...ctx(),code});
      if(!r.success){
        output.textContent=`Не удалось запустить код: ${r.error||'неизвестная ошибка'}`;
        return toast(r.error||'Запуск кода не удался.');
      }
      const explanation=r.stderr_explained?.message||r.stderr_explained?.hint||'';
      output.textContent=[r.stdout,r.stderr,explanation].filter(Boolean).join('\n')||'Выполнено без вывода';
    }finally{
      if(button){button.disabled=false;button.textContent='Запустить'}
    }
  }
  
  function bindWorkspace(){const codeEditor=$('#os-code');codeEditor.addEventListener('input',()=>{refreshCodeHighlight();if(workspace.applying||!workspace.socket||!workspace.id)return;workspace.socket.emit('workspace_patch',{...ctx(),base_version:workspace.version,full_code:codeEditor.value,next:codeEditor.value,op_id:crypto.randomUUID(),updated_at:Date.now()})});codeEditor.addEventListener('scroll',refreshCodeHighlight);$('#os-save').onclick=async()=>{if(!workspace.id)return;const r=await post('/task-workspace/api/save',{...ctx(),code:codeEditor.value,answer:$('#os-answer').value});toast(r.success?'Сохранено':r.error||'Ошибка')};$('#os-run').onclick=run;$('#os-versions').onclick=async()=>{if(!workspace.id)return;const r=await fetch(`/task-workspace/api/versions?context_type=lesson_task&context_id=${workspace.id}`).then(x=>x.json());const items=r.versions?.items||[];const box=$('#os-versions-list');box.innerHTML='';if(!items.length){box.textContent='Версий пока нет.';return}items.forEach((item,index)=>{const b=document.createElement('button');b.className='os-version';b.textContent=`Версия ${items.length-index} · ${item.source||'сохранение'}`;b.onclick=async()=>{const restored=await post(`/task-workspace/api/versions/${item.version_id}/restore`,ctx());if(!restored.success)return toast(restored.error||'Не удалось восстановить');workspace.applying=true;codeEditor.value=restored.code||'';$('#os-answer').value=restored.answer||'';refreshCodeHighlight();workspace.applying=false;toast('Версия восстановлена')};box.append(b)})}}
  
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
    $('#os-board-clear')?.addEventListener('click',()=>post(`/lesson/${lessonId}/studio/board`,{action:'clear'}).then(r=>{if(r.success){state.board=r.board;renderBoard()}}));
    $('#os-board-undo')?.addEventListener('click',()=>post(`/lesson/${lessonId}/studio/board`,{action:'undo'}).then(r=>{if(r.success){state.board=r.board;renderBoard()}else toast(r.error||'Не удалось отменить действие')}));
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
  function renderTheory(){const box=$('#os-theory-list'), frame=$('#os-theory-frame'), items=data.theory_items||[];if(!box||!frame)return;box.innerHTML=items.map(item=>`<button class="os-material ${Number(state.active_theory_block_id)===Number(item.id)?'active':''}" data-theory-id="${item.id}" data-theory-url="${item.url}">№${item.task_number} · ${item.title}</button>`).join('')||'Для курса пока нет опубликованной теории.';box.querySelectorAll('[data-theory-id]').forEach(button=>button.onclick=()=>{const id=Number(button.dataset.theoryId);state.active_theory_block_id=id;frame.src=button.dataset.theoryUrl;frame.dataset.blockId=String(id);frame.classList.remove('hidden');renderTheory();if(teacher)save({active_pane:'theory',active_theory_block_id:id,follow_student:state.follow_student})});const active=items.find(item=>Number(item.id)===Number(state.active_theory_block_id));if(active){if(frame.dataset.blockId!==String(active.id)){frame.src=active.url;frame.dataset.blockId=String(active.id)}frame.classList.remove('hidden')}}
  
  function bindControls(){
    document.querySelectorAll('.room-tab[data-view]').forEach(b=>b.onclick=()=>activate(b.dataset.view));
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
    const videoDock=$('#room-video-dock');
    const setVideoOpen=open=>{videoDock?.classList.toggle('hidden',!open);localUi.videoOpen=open;persistUi()};
    const setVideoLarge=large=>{videoDock?.classList.toggle('is-large',large);localUi.videoLarge=large;persistUi();$('#room-video-size')?.setAttribute('aria-label',large?'Уменьшить видеозвонок':'Развернуть видеозвонок')};
    const setVideoFloating=(position, shouldPersist=true)=>{
      if(!videoDock)return;
      const valid=position&&Number.isFinite(Number(position.left))&&Number.isFinite(Number(position.top));
      videoDock.classList.toggle('is-floating',valid);
      videoDock.style.left=valid?`${Math.round(Number(position.left))}px`:'';
      videoDock.style.top=valid?`${Math.round(Number(position.top))}px`:'';
      localUi.videoPosition=valid?{left:Number(position.left),top:Number(position.top)}:null;
      $('#room-video-dock-toggle')?.setAttribute('aria-label',valid?'Закрепить видеозвонок справа':'Окно закреплено справа');
      if(shouldPersist)persistUi();
    };
    $('#room-video-toggle')?.addEventListener('click',()=>setVideoOpen(true));
    $('#room-video-close')?.addEventListener('click',()=>setVideoOpen(false));
    $('#room-video-size')?.addEventListener('click',()=>setVideoLarge(!videoDock?.classList.contains('is-large')));
    $('#room-video-dock-toggle')?.addEventListener('click',()=>setVideoFloating(null));
    const videoHead=$('#room-video-head');
    videoHead?.addEventListener('pointerdown',event=>{
      if(event.target.closest('button'))return;
      const rect=videoDock?.getBoundingClientRect(); if(!rect||!videoDock)return;
      const offsetX=event.clientX-rect.left,offsetY=event.clientY-rect.top;
      videoHead.setPointerCapture?.(event.pointerId);
      const move=moveEvent=>{
        const width=videoDock.offsetWidth,height=videoDock.offsetHeight;
        setVideoFloating({left:Math.max(8,Math.min(window.innerWidth-width-8,moveEvent.clientX-offsetX)),top:Math.max(8,Math.min(window.innerHeight-height-8,moveEvent.clientY-offsetY))},false);
      };
      const done=()=>{persistUi();window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',done)};
      window.addEventListener('pointermove',move);window.addEventListener('pointerup',done);
    });
    if(localUi.videoOpen===true)setVideoOpen(true);if(localUi.videoLarge===true)setVideoLarge(true);if(localUi.videoPosition)setVideoFloating(localUi.videoPosition);
    $('#os-meeting-join')?.addEventListener('click', async () => {
        const btn = $('#os-meeting-join');
        btn.disabled = true; btn.textContent = 'Подключение...';
        const r = await post(`/lesson/${lessonId}/studio/daily/join`, {});
        if (!r.success) {
            btn.disabled = false; btn.textContent = 'Попробовать снова';
            return toast(r.error || 'Не удалось подключиться к встрече');
        }
        $('#os-meeting-placeholder').style.display = 'none';
        const container = $('#os-daily-container');
        container.style.display = 'block';
        if (!window.DailyIframe) {
            container.style.display = 'none';
            $('#os-meeting-placeholder').style.display = 'block';
            btn.disabled = false; btn.textContent = 'Подключиться';
            return toast('Не удалось загрузить видеомодуль Daily. Обновите страницу или проверьте сеть.');
        }
        try {
          if (!dailyFrame) {
            dailyFrame = DailyIframe.createFrame(container, { showLeaveButton: true, iframeStyle: { width: '100%', height: '100%', border: '0' } });
            dailyFrame.on('left-meeting', () => {
              $('#os-meeting-placeholder').style.display = 'block';
              container.style.display = 'none';
              btn.disabled = false; btn.textContent = 'Подключиться';
            });
          }
          await dailyFrame.join({ url: r.room_url, token: r.token });
        } catch (error) {
          console.error('Daily connection failed', error);
          try { await dailyFrame?.destroy(); } catch (_) {}
          dailyFrame = null;
          container.style.display = 'none';
          $('#os-meeting-placeholder').style.display = 'block';
          btn.disabled = false; btn.textContent = 'Подключиться';
          toast('Не удалось подключиться к встрече Daily. Повторите попытку.');
        }
    });
    const materialFile=$('#os-material-file'),materialUpload=$('#os-material-upload'),materialDropzone=$('#os-material-dropzone');
    const chooseMaterial=file=>{if(!file||!materialFile)return;const transfer=new DataTransfer();transfer.items.add(file);materialFile.files=transfer.files;materialUpload.disabled=false;materialDropzone?.classList.add('has-file');if(materialDropzone)materialDropzone.querySelector('span').textContent=file.name};
    $('#os-material-pick')?.addEventListener('click',()=>materialFile?.click());
    materialFile?.addEventListener('change',()=>chooseMaterial(materialFile.files?.[0]));
    materialDropzone?.addEventListener('click',()=>materialFile?.click());
    ['dragenter','dragover'].forEach(name=>materialDropzone?.addEventListener(name,event=>{event.preventDefault();materialDropzone.classList.add('is-dragging')}));
    ['dragleave','drop'].forEach(name=>materialDropzone?.addEventListener(name,event=>{event.preventDefault();materialDropzone.classList.remove('is-dragging')}));
    materialDropzone?.addEventListener('drop',event=>chooseMaterial(event.dataTransfer?.files?.[0]));
    materialUpload?.addEventListener('click',async()=>{const f=materialFile?.files?.[0];if(!f)return;materialUpload.disabled=true;materialUpload.textContent='Загрузка…';const form=new FormData();form.append('file',f);const r=await postForm(`/lesson/${lessonId}/upload`,form);materialUpload.textContent='Прикрепить';if(r.success){data.materials.push(r.material);materialFile.value='';materialUpload.disabled=true;if(materialDropzone){materialDropzone.classList.remove('has-file');materialDropzone.querySelector('span').textContent='Перетащите файл сюда'}renderMaterials();toast('Материал прикреплён')}else{materialUpload.disabled=false;toast(r.error||'Не удалось прикрепить материал')}});
    const panel=$('#room-lesson-panel'),canvas=$('#room-canvas'),taskPanel=$('#room-task-panel'),isMobile=()=>window.matchMedia('(max-width: 820px)').matches;
    const setPanel=open=>{panel?.classList.toggle('is-collapsed',!open);canvas?.classList.toggle('panel-collapsed',!open);$('#room-panel-toggle')?.setAttribute('aria-expanded',String(open));localUi.lessonPanelOpen=open;persistUi()};
    $('#room-panel-toggle')?.addEventListener('click',()=>setPanel(panel?.classList.contains('is-collapsed')));
    $('#room-panel-close')?.addEventListener('click',()=>setPanel(false));
    if(localUi.lessonPanelOpen!==true)setPanel(false);
    const taskPanelIsOpen=()=>isMobile()?taskPanel?.classList.contains('is-open'):!taskPanel?.classList.contains('is-collapsed');
    const setTaskPanel=open=>{taskPanel?.classList.toggle('is-open',open);taskPanel?.classList.toggle('is-collapsed',!open);canvas?.classList.toggle('tasks-collapsed',!open);$('#room-task-toggle')?.setAttribute('aria-expanded',String(open));localUi.taskPanelOpen=open;persistUi()};
    $('#room-task-toggle')?.addEventListener('click',()=>setTaskPanel(!taskPanelIsOpen()));
    $('#room-task-close')?.addEventListener('click',()=>setTaskPanel(false));
    if(localUi.taskPanelOpen===true)setTaskPanel(true);else setTaskPanel(false);
    const setWidths=()=>{if(Number(localUi.leftWidth))root.style.setProperty('--room-left-width',`${localUi.leftWidth}px`);if(Number(localUi.rightWidth))root.style.setProperty('--room-right-width',`${localUi.rightWidth}px`)};
    setWidths();
    const resizePanel=(side,event)=>{if(window.innerWidth<=1180)return;event.preventDefault();const startX=event.clientX,start=side==='left'?(Number(localUi.leftWidth)||250):(Number(localUi.rightWidth)||320);const move=e=>{const delta=e.clientX-startX;const minimum=side==='left'?190:280;const width=Math.max(minimum,Math.min(420,side==='left'?start+delta:start-delta));localUi[side==='left'?'leftWidth':'rightWidth']=width;root.style.setProperty(side==='left'?'--room-left-width':'--room-right-width',`${width}px`)};const done=()=>{persistUi();window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',done)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',done)};
    taskPanel?.addEventListener('pointerdown',event=>{if(event.target.closest('button,a,input,textarea'))return;if(event.offsetX<taskPanel.clientWidth-12)return;resizePanel('left',event)});
    panel?.addEventListener('pointerdown',event=>{if(event.target.closest('button,a,input,textarea,select,summary,details,label'))return;if(event.offsetX>12)return;resizePanel('right',event)});
    const note=$('#room-teacher-note');if(note){note.value=state.teacher_private_note||'';note.addEventListener('change',()=>save({teacher_private_note:note.value}))}
    const guidanceEditor=$('#room-guidance');if(guidanceEditor)guidanceEditor.addEventListener('change',()=>{state.guidance={...(state.guidance||{}),next_step:guidanceEditor.value};save({guidance:state.guidance})});
    const homework=$('#room-homework');if(homework){homework.value=state.outcome?.homework||'';homework.addEventListener('change',()=>{state.outcome={...(state.outcome||{}),homework:homework.value};if(teacher)save({outcome:state.outcome})})}
    const studentNotes=$('#room-student-notes');if(studentNotes){studentNotes.value=data.student_notes||'';$('#room-student-notes-save')?.addEventListener('click',async()=>{const r=await post(`/lesson/${lessonId}/studio/student-notes`,{notes:studentNotes.value});if(r.success){data.student_notes=r.notes||studentNotes.value;toast('Личные заметки сохранены')}else toast(r.error||'Не удалось сохранить заметки')})}
    document.querySelectorAll('[data-student-signal]').forEach(button=>button.addEventListener('click',async()=>{if(button.disabled)return;const signal=button.dataset.studentSignal;button.disabled=true;const r=await post('/lesson/'+lessonId+'/studio/signal',{signal});button.disabled=false;if(r.success){state=r.state||state;render();toast(signalLabels[signal]+': преподаватель увидит это сразу')}else toast(r.error||'Не удалось отправить статус')}));
    $('#room-checkpoint-save')?.addEventListener('click',async()=>{const understanding=Number($('#room-checkpoint-understanding')?.value);if(!understanding)return toast('Оцените понимание темы');const r=await post(`/lesson/${lessonId}/studio/checkpoint`,{understanding,blocker:$('#room-checkpoint-blocker')?.value||''});if(r.success){state=r.state||state;toast('Самооценка отправлена');render()}else toast(r.error||'Не удалось отправить самооценку')});
    
    const lines=value=>Array.isArray(value)?value.join('\n'):'';
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
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){const finishModal=$('#os-finish-modal'),confirmModal=$('#room-confirm-modal');if(!finishModal?.classList.contains('hidden'))setModalVisible(finishModal,false);if(!confirmModal?.classList.contains('hidden'))$('#room-confirm-cancel')?.click();return}const tag=document.activeElement?.tagName;if(['INPUT','TEXTAREA','SELECT'].includes(tag)||event.altKey||event.ctrlKey||event.metaKey)return;if(event.key==='1')activate('work');if(event.key==='2')activate('theory');if(event.key==='3')activate('board');if(event.key==='4')activate('materials');if(event.key.toLowerCase()==='v')setVideoOpen(!videoDock?.classList.contains('hidden'));if(event.key.toLowerCase()==='f'&&teacher)$('#os-follow')?.click()});
  }
  
  const lessonSocket=io('/lesson');
  lessonSocket.on('connect',()=>{setConnection('connected');lessonSocket.emit('join_lesson',{lesson_id:lessonId});refreshStudioState()});
  lessonSocket.on('disconnect',()=>setConnection('disconnected'));
  lessonSocket.on('connect_error',()=>setConnection('disconnected'));
  lessonSocket.io.on('reconnect_attempt',()=>setConnection('connecting'));
  lessonSocket.on('lesson_studio_updated',p=>{if(p.lesson_id!==lessonId)return;const previousPane=state.active_pane,previousFollow=state.follow_student;state=teacher?{...state,...p.state}:p.state;render();if(!teacher&&state.follow_student&&(!hasExplicitWorkspaceChoice||state.active_pane!==previousPane||!previousFollow))activate(state.active_pane||'work',true)});
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
        $('#os-timer').textContent = fmt(state.timer?.seconds || 0);
    }
    setTimeout(tick, 1000);
}
  
  bindWorkspace();bindBoard();bindControls();activeTask=state.active_task_id||tasks[0]?.lesson_task_id;render();if(activeTask)openTask(activeTask);const requestedPane=new URLSearchParams(window.location.search).get('pane');if(requestedPane){hasExplicitWorkspaceChoice=true;localUi.activeWorkspace=requestedPane;persistUi()}activate(requestedPane||localUi.activeWorkspace||state.active_pane||'work',true);tick();
})();
