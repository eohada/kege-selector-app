(() => {
  const root = document.querySelector('#lesson-studio-os'); if (!root || !window.io) return;
  const raw = document.querySelector('#studio-os-data'); const data = raw ? JSON.parse(raw.textContent) : {};
  const lessonId = Number(root.dataset.lessonId), teacher = root.dataset.teacher === 'true', csrf = document.querySelector('meta[name="csrf-token"]')?.content || '', clientId = crypto.randomUUID();
  let state = data.state || {}, tasks = typeof data.tasks === 'string' ? JSON.parse(data.tasks) : (data.tasks || []), activeTask = null, workspace = {id:null, version:0, socket:null, applying:false}, board = {tool:'pen',color:'#312e81',width:4,drawing:null,drag:null,camera:{x:0,y:0,z:1}}, lastLaserAt = 0;
  const $ = s => document.querySelector(s), fmt=s=>`${String(Math.floor(Math.max(0,s||0)/60)).padStart(2,'0')}:${String(Math.max(0,s||0)%60).padStart(2,'0')}`;
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
  
  function toast(text){const n=document.createElement('div');n.className='os-toast';n.textContent=text;document.body.append(n);setTimeout(()=>n.remove(),2400)}
  async function save(patch){if(!teacher)return null;const r=await post(`/lesson/${lessonId}/studio/state`,patch);if(r.success){state=r.state;render()}else toast(r.error||'Не удалось сохранить');return r}
  function activate(view, remote=false){
    if(!['work','theory','board','meeting','materials'].includes(view)) view='work';
    document.querySelectorAll('.os-nav').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
    document.querySelectorAll('[data-view-panel]').forEach(x=>x.classList.toggle('hidden',x.dataset.viewPanel!==view));
    if(view==='board') renderBoard();
    if(view==='materials') renderMaterials();
    if(view==='theory') renderTheory();
    if (!remote) lessonSocket.emit('tab_changed', {lesson_id: lessonId, tab: view});
    if(!remote && teacher && state.follow_student) save({active_pane:view,follow_student:true});
  }
  
  function render(){
    const timer=state.timer||{}, phase=state.phase||'preparation';
    $('#os-timer').textContent=fmt(timer.seconds);
    const toggleBtn = $('#os-timer-toggle');
    if(toggleBtn) toggleBtn.innerHTML = timer.running ? '<i class="ph-bold ph-pause"></i>' : '<i class="ph-bold ph-play"></i>';
    document.querySelectorAll('#os-phases button').forEach(b=>b.classList.toggle('active',b.dataset.phase===phase));
    document.querySelectorAll('[data-duration]').forEach(i=>i.value=Math.max(1,Math.round(((state.phase_durations||{})[i.dataset.duration]||60)/60)));
    const followButton = $('#os-follow');
    if (followButton) {
      followButton.classList.toggle('os-primary', Boolean(state.follow_student));
      followButton.textContent = state.follow_student ? 'Веду ученика' : 'Вести ученика';
      followButton.setAttribute('aria-pressed', String(Boolean(state.follow_student)));
    }
    renderTasks();
  }
  
  function renderTasks(){const box=$('#os-task-list');box.innerHTML='';$('#os-task-count').textContent=`${tasks.length} шт.`;tasks.forEach((t,i)=>{const b=document.createElement('button');b.className=`os-task ${activeTask===t.lesson_task_id?'active':''}`;b.innerHTML=`<small>${i+1} · ${t.status||'pending'}</small><b>${t.title}</b>`;b.onclick=()=>openTask(t.lesson_task_id);box.append(b)})}
  function openTask(id){const task=tasks.find(x=>x.lesson_task_id===Number(id));if(!task)return;activeTask=task.lesson_task_id;$('#os-task-title').textContent=task.title;$('#os-task-body').innerHTML=task.description||'Условие отсутствует.';$('#os-task-status').textContent=task.status||'В очереди';renderTasks();if(teacher)save({active_task_id:id});connectWorkspace(id)}
  
  function ctx(){return {context_type:'lesson_task',context_id:workspace.id,client_id:clientId}}
  function connectWorkspace(id){workspace.id=id;$('#os-code').value='';$('#os-answer').value='';$('#os-output').textContent='Подключаемся к совместному коду…';if(!workspace.socket){workspace.socket=io('/task-workspace');workspace.socket.on('connect',()=>workspace.socket.emit('join_workspace',ctx()));workspace.socket.on('workspace_snapshot',p=>applySnapshot(p.state));workspace.socket.on('workspace_patch',p=>{if(p.client_id===clientId||!p.code_after)return;workspace.applying=true;$('#os-code').value=p.code_after;workspace.applying=false;workspace.version=p.version||workspace.version});workspace.socket.on('workspace_presence',p=>$('#os-presence').textContent=(p.participants||[]).map(x=>x.display_name||x.username).join(' · ')||'Нет участников')}else if(workspace.socket.connected)workspace.socket.emit('join_workspace',ctx());}
  function applySnapshot(s){if(!s)return;workspace.applying=true;$('#os-code').value=s.code||'';$('#os-answer').value=s.answer||'';workspace.applying=false;workspace.version=s.version||0;$('#os-presence').textContent='Совместный режим'}
  async function run(){if(!workspace.id)return;const r=await post('/task-workspace/api/run',{...ctx(),code:$('#os-code').value});$('#os-output').textContent=r.stderr||r.stdout||r.error||'Выполнено без вывода'}
  
  function bindWorkspace(){$('#os-code').addEventListener('input',()=>{if(workspace.applying||!workspace.socket||!workspace.id)return;workspace.socket.emit('workspace_patch',{...ctx(),base_version:workspace.version,full_code:$('#os-code').value,next:$('#os-code').value,op_id:crypto.randomUUID(),updated_at:Date.now()})});$('#os-save').onclick=async()=>{if(!workspace.id)return;const r=await post('/task-workspace/api/save',{...ctx(),code:$('#os-code').value,answer:$('#os-answer').value});toast(r.success?'Сохранено':r.error||'Ошибка')};$('#os-run').onclick=run;$('#os-versions').onclick=async()=>{if(!workspace.id)return;const r=await fetch(`/task-workspace/api/versions?context_type=lesson_task&context_id=${workspace.id}`).then(x=>x.json());const items=r.versions?.items||[];const box=$('#os-versions-list');box.innerHTML='';if(!items.length){box.textContent='Версий пока нет.';return}items.forEach((item,index)=>{const b=document.createElement('button');b.className='os-version';b.textContent=`Версия ${items.length-index} · ${item.source||'сохранение'}`;b.onclick=async()=>{const restored=await post(`/task-workspace/api/versions/${item.version_id}/restore`,ctx());if(!restored.success)return toast(restored.error||'Не удалось восстановить');workspace.applying=true;$('#os-code').value=restored.code||'';$('#os-answer').value=restored.answer||'';workspace.applying=false;toast('Версия восстановлена')};box.append(b)})}}
  
  function phaseChange(phase){if(!teacher)return;const previous=state.phase, timers={...(state.phase_timers||{}),[previous]:Math.max(0,Number(state.timer?.seconds)||0)},timer={...(state.timer||{}),seconds:timers[phase],running:false,completed_at:null};save({phase,phase_timers:timers,timer})}
  
  function boardPoint(e){const c=$('#os-board'),r=c.getBoundingClientRect();return{x:(e.clientX-r.left-board.camera.x)/board.camera.z,y:(e.clientY-r.top-board.camera.y)/board.camera.z}}
  const imgCache = {};
  function draw(s){const c=$('#os-board'),g=c.getContext('2d'),p=s.points;if(!p?.length)return;
    g.save(); g.translate(board.camera.x, board.camera.y); g.scale(board.camera.z, board.camera.z);
    const isLegacy = p[0].x <= 2;
    const scaleX = isLegacy ? 2400 : 1; const scaleY = isLegacy ? 1350 : 1;
    g.strokeStyle=s.color||'#312e81'; g.fillStyle=s.color||'#312e81'; g.lineWidth=s.width||4; g.lineCap='round';
    if(s.tool==='eraser') g.globalCompositeOperation='destination-out';
    g.beginPath();
    if(s.tool==='text'){ g.font='28px sans-serif'; g.fillText(s.text, p[0].x*scaleX, p[0].y*scaleY); }
    else if(s.tool==='image'){
      const drawImg = (img) => {
          g.drawImage(img, p[0].x*scaleX, p[0].y*scaleY, (s.image_width||400)*scaleX, (s.image_height||400)*scaleY);
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
      const a=p[0],b=p[p.length-1],x=a.x*scaleX,y=a.y*scaleY,w=(b.x-a.x)*scaleX,h=(b.y-a.y)*scaleY;
      if(s.tool==='rectangle') g.strokeRect(x,y,w,h);
      else if(s.tool==='ellipse') { g.ellipse(x+w/2,y+h/2,Math.abs(w/2),Math.abs(h/2),0,0,Math.PI*2); g.stroke(); }
      else { g.moveTo(x,y); g.lineTo(x+w,y+h); g.stroke(); }
    } else {
      g.moveTo(p[0].x*scaleX, p[0].y*scaleY);
      p.slice(1).forEach(q=>g.lineTo(q.x*scaleX, q.y*scaleY)); g.stroke();
    }
    g.restore();
    if (board.selectedStrokeIndex !== undefined && state.board && state.board.strokes[board.selectedStrokeIndex] === s && s.tool === 'image') {
        const x = s.points[0].x * scaleX * board.camera.z + board.camera.x;
        const y = s.points[0].y * scaleY * board.camera.z + board.camera.y;
        const w = (s.image_width||400) * scaleX * board.camera.z;
        const h = (s.image_height||400) * scaleY * board.camera.z;
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
    new ResizeObserver(() => renderBoard()).observe(viewport);
    
    document.addEventListener('keydown', e => {
        if (e.ctrlKey && e.code === 'KeyZ' && document.querySelector('.os-nav[data-view="board"]')?.classList.contains('active')) {
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
        renderBoard();
    }, {passive: false});
    c.addEventListener('pointerdown',e=>{
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
                  const isLegacy = s.points[0].x <= 2;
                  const scaleX = isLegacy ? 2400 : 1; const scaleY = isLegacy ? 1350 : 1;
                  const bx = s.points[0].x * scaleX, by = s.points[0].y * scaleY;
                  const bw = iw * scaleX, bh = ih * scaleY;
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
                  const isLegacy = s.points[0].x <= 2;
                  const scaleX = isLegacy ? 2400 : 1; const scaleY = isLegacy ? 1350 : 1;
                  const bx = s.points[0].x * scaleX, by = s.points[0].y * scaleY;
                  if (bp.x >= bx && bp.x <= bx + iw*scaleX && bp.y >= by && bp.y <= by + ih*scaleY) {
                      board.selectedStrokeIndex = i; break;
                  }
              }
          }
          renderBoard();
          return;
      }
      board.selectedStrokeIndex = undefined;
      if(board.tool==='text'){ const text=$('#os-board-text').value.trim(); if(text) post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'text',text,color:board.color,width:board.width,points:[boardPoint(e)]}}).then(r=>{if(r.success){state.board=r.board;renderBoard()}}); return; }
      board.drawing={tool:board.tool,color:board.color,width:board.width,points:[boardPoint(e)]}; c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove',e=>{
      if(board.drag){ board.camera.x = board.drag.cx + (e.clientX - board.drag.x); board.camera.y = board.drag.cy + (e.clientY - board.drag.y); renderBoard(); return; }
      const bp=boardPoint(e);
      if(board.resizing !== undefined) {
          const r = board.resizing; const s = state.board.strokes[r.index];
          const isLegacy = s.points[0].x <= 2;
          const scaleX = isLegacy ? 2400 : 1; const scaleY = isLegacy ? 1350 : 1;
          const dx = (bp.x - r.startX) / scaleX;
          const newW = Math.max(20, r.startW + dx);
          const ratio = r.startW / (r.startH || 1);
          s.image_width = newW;
          s.image_height = newW / ratio;
          renderBoard(); return;
      }
      if(board.draggingImg !== undefined) {
          const d = board.draggingImg; const s = state.board.strokes[d.index];
          const isLegacy = s.points[0].x <= 2;
          const scaleX = isLegacy ? 2400 : 1; const scaleY = isLegacy ? 1350 : 1;
          s.points[0] = { x: (bp.x - d.offsetX)/scaleX, y: (bp.y - d.offsetY)/scaleY };
          renderBoard(); return;
      }
      if(!board.drawing) return;
      board.drawing.points.push(bp);
      renderBoard();
    });
    c.addEventListener('pointerup',e=>{
      if(board.drag){board.drag=null;c.releasePointerCapture(e.pointerId);return}
      if(board.resizing !== undefined || board.draggingImg !== undefined) {
          board.resizing = undefined; board.draggingImg = undefined; c.releasePointerCapture(e.pointerId);
          post(`/lesson/${lessonId}/studio/board`, {action: 'rewrite', strokes: state.board.strokes}).then(r=>{if(r.success){state.board=r.board;renderBoard()}});
          return;
      }
      const s=board.drawing; board.drawing=null;
      if(!s) return; c.releasePointerCapture(e.pointerId);
      if(s.points.length>1) post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:s}).then(r=>{if(r.success){state.board=r.board;renderBoard()}});
    });
    document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>{board.tool=b.dataset.tool;document.querySelectorAll('[data-tool]').forEach(x=>x.classList.toggle('active',x===b))});
    document.querySelectorAll('[data-color]').forEach(b=>b.onclick=()=>board.color=b.dataset.color);
    $('#os-board-width').oninput=e=>{ board.width=Number(e.target.value); };
    $('#os-board-zoom').oninput=e=>{ board.camera.z=Number(e.target.value)/100; renderBoard(); };
    $('#os-board-image').onchange=async e=>{
      const file=e.target.files?.[0]; if(!file)return; const form=new FormData(); form.append('file',file);
      const r=await fetch(`/lesson/${lessonId}/studio/board/image`,{method:'POST',headers:{'X-CSRFToken':csrf},body:form}).then(x=>x.json());
      if(!r.success) return toast(r.error||'Не удалось загрузить изображение');
      const cx = (-board.camera.x + c.width/2)/board.camera.z, cy = (-board.camera.y + c.height/2)/board.camera.z;
      const updated=await post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'image',url:r.url,image_width:400,image_height:400,points:[{x:cx,y:cy}]}});
      if(updated.success){state.board=updated.board;renderBoard()} e.target.value='';
    };
    $('#os-board-clear')?.addEventListener('click',()=>post(`/lesson/${lessonId}/studio/board`,{action:'clear'}).then(r=>{if(r.success){state.board=r.board;renderBoard()}}));
    document.addEventListener('paste', async (e) => {
        if (document.querySelector('.os-nav[data-view="board"]')?.classList.contains('active')) {
            const items = e.clipboardData?.items;
            if (!items) return;
            for (const item of items) {
                if (item.type.indexOf('image') !== -1) {
                    const file = item.getAsFile();
                    const form = new FormData(); form.append('file', file);
                    toast('Загрузка изображения...');
                    const r = await fetch(`/lesson/${lessonId}/studio/board/image`,{method:'POST',headers:{'X-CSRFToken':csrf},body:form}).then(x=>x.json());
                    if(!r.success) return toast(r.error||'Ошибка загрузки');
                    const c=$('#os-board'), cx = (-board.camera.x + c.width/2)/board.camera.z, cy = (-board.camera.y + c.height/2)/board.camera.z;
                    const updated=await post(`/lesson/${lessonId}/studio/board`,{action:'append',stroke:{tool:'image',url:r.url,image_width:400,image_height:400,points:[{x:cx,y:cy}]}});
                    if(updated.success){state.board=updated.board;renderBoard()}
                    break;
                }
            }
        }
    });
  }
  
  function renderMaterials(){const box=$('#os-materials');box.innerHTML=(data.materials||[]).map(x=>`<a class="os-material" target="_blank" href="${x.url}">${x.name}</a>`).join('')||'Материалов пока нет.'}
  function renderTheory(){const box=$('#os-theory-list'), frame=$('#os-theory-frame'), items=data.theory_items||[];if(!box||!frame)return;box.innerHTML=items.map(item=>`<button class="os-material ${Number(state.active_theory_block_id)===Number(item.id)?'active':''}" data-theory-id="${item.id}" data-theory-url="${item.url}">№${item.task_number} · ${item.title}</button>`).join('')||'Для курса пока нет опубликованной теории.';box.querySelectorAll('[data-theory-id]').forEach(button=>button.onclick=()=>{const id=Number(button.dataset.theoryId);state.active_theory_block_id=id;frame.src=button.dataset.theoryUrl;frame.dataset.blockId=String(id);frame.classList.remove('hidden');renderTheory();if(teacher)save({active_pane:'theory',active_theory_block_id:id,follow_student:state.follow_student})});const active=items.find(item=>Number(item.id)===Number(state.active_theory_block_id));if(active){if(frame.dataset.blockId!==String(active.id)){frame.src=active.url;frame.dataset.blockId=String(active.id)}frame.classList.remove('hidden')}}
  
  function bindControls(){
    document.querySelectorAll('.os-nav').forEach(b=>b.onclick=()=>activate(b.dataset.view));
    document.querySelectorAll('[data-phase]').forEach(b=>b.onclick=()=>phaseChange(b.dataset.phase));
    $('#os-timer-toggle')?.addEventListener('click',()=>{const remaining = Math.max(0, state.timer.seconds - Math.floor((Date.now() - new Date(state.timer.updated_at).getTime()) / 1000)); save({timer:{...(state.timer||{}),seconds: state.timer.running ? remaining : state.timer.seconds, running:!state.timer?.running}});});
    document.querySelectorAll('[data-duration]').forEach(i=>i.onchange=()=>{const d={...(state.phase_durations||{})};d[i.dataset.duration]=Math.max(1,Number(i.value)||1)*60;save({phase_durations:d,phase_timers:{...(state.phase_timers||{}),[i.dataset.duration]:d[i.dataset.duration]}})});
    $('#os-follow')?.addEventListener('click',()=>{state.follow_student=!state.follow_student;save({follow_student:state.follow_student,active_pane:document.querySelector('.os-nav.active').dataset.view})});
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
        if (!dailyFrame) {
            dailyFrame = DailyIframe.createFrame(container, { showLeaveButton: true, iframeStyle: { width: '100%', height: '100%', border: '0' } });
            dailyFrame.on('left-meeting', () => {
                $('#os-meeting-placeholder').style.display = 'block';
                container.style.display = 'none';
                btn.disabled = false; btn.textContent = 'Подключиться';
            });
        }
        try {
          await dailyFrame.join({ url: r.room_url, token: r.token });
        } catch (error) {
          container.style.display = 'none';
          $('#os-meeting-placeholder').style.display = 'block';
          btn.disabled = false; btn.textContent = 'Подключиться';
          toast('Не удалось подключиться к встрече Daily. Повторите попытку.');
        }
    });
    $('#os-material-upload')?.addEventListener('click',async()=>{const f=$('#os-material-file').files?.[0];if(!f)return;const form=new FormData();form.append('file',f);const r=await fetch(`/lesson/${lessonId}/upload`,{method:'POST',headers:{'X-CSRFToken':csrf},body:form}).then(x=>x.json());if(r.success){data.materials.push(r.material);renderMaterials()}else toast(r.error||'Не удалось прикрепить материал')});
    
    $('#os-finish')?.addEventListener('click', () => $('#os-finish-modal').classList.remove('hidden'));
    $('#os-finish-cancel')?.addEventListener('click', () => $('#os-finish-modal').classList.add('hidden'));
    $('#os-finish-confirm')?.addEventListener('click', async () => {
      $('#os-finish-modal').classList.add('hidden');
      const r = await post(`/lesson/${lessonId}/studio/finish`, {outcome:state.outcome||{}});
      if(r.success){ toast('Урок завершён'); state = r.state || state; render(); }
      else toast(r.error || 'Не удалось завершить урок');
    });
  }
  
  const lessonSocket=io('/lesson');
  lessonSocket.on('connect',()=>lessonSocket.emit('join_lesson',{lesson_id:lessonId}));
  lessonSocket.on('lesson_studio_updated',p=>{if(p.lesson_id!==lessonId)return;state=teacher?{...state,...p.state}:p.state;render();if(!teacher&&state.follow_student)activate(state.active_pane||'work',true)});
  lessonSocket.on('lesson_studio_pointer',p=>{
    if(p.lesson_id!==lessonId)return;
    let x=$('#os-pointer');
    if(!x){x=document.createElement('div');x.id='os-pointer';document.body.append(x);}
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
  
  bindWorkspace();bindBoard();bindControls();activeTask=state.active_task_id||tasks[0]?.lesson_task_id;render();if(activeTask)openTask(activeTask);activate(state.active_pane||'work',true);tick();
})();
