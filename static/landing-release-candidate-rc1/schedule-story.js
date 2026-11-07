(() => {
  const story = document.querySelector('[data-s37-story]');
  if (!story) return;
  const daysNode = story.querySelector('[data-s37-days]');
  const eventsNode = story.querySelector('[data-s37-events]');
  const workspace = story.querySelector('.s37-workspace');
  const dayTitle = story.querySelector('[data-s37-day-title]');
  const daySummary = story.querySelector('[data-s37-day-summary]');
  const weekLabel = story.querySelector('[data-s37-week-label]');
  const note = story.querySelector('[data-s37-note]');
  const copyBlocks = [...story.querySelectorAll('[data-s37-copy-block]')];
  const progressLabel = story.querySelector('[data-s37-progress-label]');
  const progressBar = story.querySelector('[data-s37-progress-bar]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (v, min=0, max=1) => Math.min(max, Math.max(min, v));
  const shortDays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
  const longDays = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
  const months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  const baseMonday = new Date(Date.UTC(2026,10,2));
  const data = [
    [{id:'lesson-mon',type:'lesson',lesson_id:27101,subject:'Информатика',title:'Информационный объём',start:'11:00',end:'12:00',status:'completed',badge:'Проведено',teacher:'Елена Морозова',notes:'Повтори перевод битов в байты перед следующим занятием.',materials:[{title:'Памятка: единицы информации',pages:'Конспект'}],action_label:'Материалы урока →'}],
    [{id:'homework-tue',type:'homework',assignment_id:48101,subject:'Информатика',title:'Кодирование изображений · практика',status:'IN_PROGRESS',badge:'В процессе',deadline:'20:00',tasks_count:6,action_label:'Продолжить выполнение →'}],
    [
      {id:'lesson-wed-a',type:'lesson',lesson_id:27102,subject:'Информатика',title:'Кодирование изображений',start:'16:00',end:'17:00',status:'planned',badge:'Занятие',teacher:'Мария Волкова',notes:'Подготовь пример изображения 4 × 4 и вспомни кодирование цвета RGB.',materials:[{title:'Кодирование растровых изображений',pages:'Материал к уроку'}],action_label:'Перейти к занятию →'},
      {id:'lesson-wed-b',type:'lesson',lesson_id:27103,subject:'Математика',title:'Разбор домашней работы',start:'18:00',end:'18:45',status:'planned',badge:'Занятие',teacher:'Алексей Громов',notes:'Отметь вопросы по задачам, которые хочется разобрать.',materials:[],action_label:'Перейти к занятию →'}
    ],
    [{id:'lesson-thu',type:'lesson',lesson_id:27104,subject:'Информатика',title:'Кодирование растрового изображения',start:'17:00',end:'18:00',status:'planned',badge:'Занятие',teacher:'Мария Волкова',notes:'Подготовь пример изображения 4 × 4 и вспомни кодирование цвета RGB.',materials:[{title:'Кодирование растровых изображений',pages:'Материал к уроку'}],action_label:'Перейти к занятию →'}],
    [{id:'homework-fri',type:'homework',assignment_id:48102,subject:'Информатика',title:'Логические выражения',status:'RETURNED',badge:'На доработке',deadline:'19:00',tasks_count:4,action_label:'Доработать задание →'}],
    [],[]
  ];
  const scenes = [
    {key:'week',copy:'week',side:'right',day:2,focus:null,label:'Неделя ученика'},
    {key:'day',copy:'day',side:'right',day:1,focus:null,label:'Выбор дня'},
    {key:'lesson',copy:'lesson',side:'left',day:3,focus:'lesson-thu',label:'Карточка занятия'},
    {key:'context',copy:'context',side:'right',day:3,focus:'lesson-thu',label:'Материалы и заметки'},
    {key:'homework',copy:'homework',side:'right',day:1,focus:'homework-tue',label:'Домашняя работа'},
    {key:'teachers',copy:'teachers',side:'left',day:2,focus:'group',label:'Занятия и преподаватели'},
    {key:'free',copy:'free',side:'right',day:6,focus:'free',label:'Свободный день'},
    {key:'overview',copy:'overview',side:'dominant',day:2,focus:null,label:'Твой учебный ритм'}
  ];
  let selectedDay = 2;
  let weekOffset = 0;
  let activeScene = null;
  let activeSceneLocal = 0;
  let staticMode = null;
  let pendingCopy = null;
  let lastProgress = 0;
  let manualOverride = false;
  let manualLockScene = null;
  let transitionRun = 0;
  let copyRevealRun = 0;
  let dayMarker = null;

  const dateFor = (i) => new Date(baseMonday.getTime() + (weekOffset*7+i)*86400000);
  const dateLabel = (d) => d.getUTCDate() + ' ' + months[d.getUTCMonth()];
  const escape = (value) => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;");

  function updateDayMarker() {
    const active = daysNode.querySelector('[data-s37-day="'+selectedDay+'"]');
    if (!active || !dayMarker) return;
    const navRect = daysNode.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    dayMarker.style.width = activeRect.width+'px';
    dayMarker.style.height = activeRect.height+'px';
    dayMarker.style.transform = 'translate3d('+(activeRect.left-navRect.left)+'px,'+(activeRect.top-navRect.top)+'px,0)';
    if (dayMarker.dataset.ready !== 'true') requestAnimationFrame(() => { dayMarker.dataset.ready='true'; });
  }

  function renderWeek(animate=true) {
    const start=dateFor(0), end=dateFor(6);
    const nextWeekLabel=start.getUTCMonth()===end.getUTCMonth()
      ? start.getUTCDate()+' — '+end.getUTCDate()+' '+months[end.getUTCMonth()]+' '+end.getUTCFullYear()
      : dateLabel(start)+' — '+dateLabel(end)+' '+end.getUTCFullYear();
    if (weekLabel.textContent !== nextWeekLabel) {
      weekLabel.textContent=nextWeekLabel;
      if (animate && !reduceMotion.matches) {
        weekLabel.getAnimations().forEach((animation)=>animation.cancel());
        weekLabel.animate([{opacity:.4,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:250,easing:'cubic-bezier(.2,.7,.2,1)'});
      }
    }
    if (!dayMarker) {
      dayMarker=document.createElement('span');
      dayMarker.className='s37-day-indicator';
      dayMarker.setAttribute('aria-hidden','true');
      dayMarker.dataset.ready='false';
      daysNode.appendChild(dayMarker);
    }
    shortDays.forEach((name,i)=>{
      const count=data[i].length, d=dateFor(i);
      let button=daysNode.querySelector('[data-s37-day="'+i+'"]');
      if (!button) {
        button=document.createElement('button');
        button.type='button';
        button.className='s37-day';
        button.dataset.s37Day=String(i);
        button.innerHTML='<span class="s37-day__name"></span><span class="s37-day__date"></span><span class="s37-day__events"></span>';
        daysNode.appendChild(button);
      }
      button.querySelector('.s37-day__name').textContent=name;
      button.querySelector('.s37-day__date').textContent=String(d.getUTCDate());
      button.querySelector('.s37-day__events').textContent=count?count+' '+(count===1?'событие':'события'):'Отдых';
      button.classList.toggle('is-active',i===selectedDay);
      button.setAttribute('aria-pressed',String(i===selectedDay));
      button.setAttribute('aria-label','Выбрать '+longDays[i]+', '+dateLabel(d));
    });
    updateDayMarker();
  }

  function statusClass(e) {
    if(e.type==='homework') return e.status==='RETURNED'||e.status==='IN_PROGRESS'?'s37-status--live':(['SUBMITTED','GRADED','ACCEPTED'].includes(e.status)?'s37-status--done':'');
    return e.status==='completed'?'s37-status--done':e.status==='in_progress'?'s37-status--live':e.status==='cancelled'?'s37-status--cancelled':'';
  }

  function renderLesson(e) {
    const initials=e.teacher.split(' ').map(x=>x[0]).slice(0,2).join('');
    const action=e.status==='cancelled'
      ? '<span class="s37-action s37-action--quiet">Занятие отменено</span>'
      : e.status==='completed'
        ? '<span class="s37-action s37-action--quiet">Занятие проведено</span><button class="s37-action s37-action--quiet" type="button" data-s37-action="theory">Открыть теорию</button>'
        : '<button class="s37-action" type="button" data-s37-action="lesson">'+escape(e.action_label)+'</button>';
    const materials=e.materials.length
      ? '<div class="s37-material-card"><strong>Материалы к занятию</strong><span>'+escape(e.materials[0].title)+'</span><br>'+escape(e.materials[0].pages)+'</div>'
      : '<div class="s37-material-card"><strong>Материалы к занятию</strong>Материалы не прикреплены.</div>';
    const context=e.notes||e.materials.length
      ? '<div class="s37-event-context" data-s37-context="'+e.id+'"><div class="s37-note-card"><strong>Заметка к уроку</strong>'+escape(e.notes||'Для этого занятия заметка не добавлена.')+'</div>'+materials+'</div>'
      : '';
    const subtitle=e.status==='completed'?'Занятие проведено':e.status==='cancelled'?'Занятие отменено':'Занятие по расписанию';
    const aside=e.status==='cancelled'?'Это занятие отменено.':'Тема, время и преподаватель собраны в карточке.';
    return '<article class="s37-event-card" data-s37-card="'+e.id+'"><div class="s37-event-main"><div class="s37-event-meta"><time class="s37-time">'+e.start+' – '+e.end+'</time><span class="s37-status '+statusClass(e)+'">'+e.badge+'</span></div><h5>'+escape(e.title)+'</h5><p>'+escape(e.subject)+' · '+subtitle+'</p><div class="s37-event-tutor"><span class="s37-avatar" aria-hidden="true">'+initials+'</span><span><strong>'+escape(e.teacher)+'</strong><small>Преподаватель курса</small></span></div></div><div class="s37-event-aside"><p>'+aside+'</p>'+action+'</div>'+context+'</article>';
  }

  function renderHomework(e) {
    const status=e.status==='RETURNED'?'На доработке':e.status==='IN_PROGRESS'?'В процессе':e.badge;
    const deadline=e.status==='RETURNED'?'Доработать до ':e.status==='IN_PROGRESS'?'Сдать до ':'Срок: ';
    return '<article class="s37-event-card s37-homework-card" data-s37-card="'+e.id+'"><div><div class="s37-event-meta"><span class="s37-status '+statusClass(e)+'">'+status+'</span><span class="s37-time">'+deadline+e.deadline+'</span></div><h5>'+escape(e.title)+'</h5><p>'+escape(e.subject)+' · '+e.tasks_count+' задания</p></div><button class="s37-action" type="button" data-s37-action="homework">'+escape(e.action_label)+'</button></article>';
  }

  function renderFree() {
    return '<article class="s37-free-card" data-s37-card="free"><img src="/static/landing-release-candidate-rc1/assets/hero-mascot-3d.webp" alt="Бу" width="1003" height="754" loading="lazy" decoding="async"><span class="s37-status s37-status--done">Отдых</span><h5>Свободный учебный день</h5><p>На сегодня обязательных уроков нет. Можно отдохнуть или вернуться к теории в удобном ритме.</p><div class="s37-free-links"><button class="s37-action s37-action--quiet" type="button" data-s37-action="theory">База знаний и теория</button></div></article>';
  }

  function applyFocus(focus) {
    eventsNode.removeAttribute('data-focus');
    workspace.toggleAttribute('data-has-focus', Boolean(focus));
    if(focus==='group') eventsNode.dataset.focus='teachers';
    else if(focus==='free'){eventsNode.dataset.focus='free';eventsNode.querySelector('[data-s37-card="free"]')?.classList.add('is-focused');}
    else if(focus){
      const card=eventsNode.querySelector('[data-s37-card="'+focus+'"]');
      if(card){eventsNode.dataset.focus=focus.indexOf('homework-')===0?'homework':activeScene==='context'?'context':'lesson';card.classList.add('is-focused');}
    }
    eventsNode.querySelectorAll('[data-s37-context]').forEach((el)=>el.classList.toggle('is-visible',activeScene==='context'&&activeSceneLocal>=.34));
  }

  function cardNode(markup) {
    const holder=document.createElement('div');
    holder.innerHTML=markup.trim();
    return holder.firstElementChild;
  }

  function renderEvents(items, direction=1) {
    const oldLive=[...eventsNode.children].filter((node)=>!node.hasAttribute('data-s37-exiting'));
    const oldById=new Map(oldLive.map((node)=>[node.dataset.s37Card,node]));
    const nextMarkup=items.length?items.map((e)=>e.type==='lesson'?renderLesson(e):renderHomework(e)):[renderFree()];
    const nextIds=items.length?items.map((e)=>e.id):['free'];
    const oldIds=oldLive.map((node)=>node.dataset.s37Card);
    const changed=oldIds.join('|')!==nextIds.join('|');
    if (!changed) return;

    const run=++transitionRun;
    eventsNode.querySelectorAll('[data-s37-exiting]').forEach((node)=>{node.getAnimations().forEach((animation)=>animation.cancel());node.remove();});
    const nextNodes=nextMarkup.map((markup,index)=>oldById.get(nextIds[index])||cardNode(markup));
    const nextSet=new Set(nextNodes);
    const shouldAnimate=oldLive.length>0&&!reduceMotion.matches;
    const parentRect=eventsNode.getBoundingClientRect();
    oldLive.filter((node)=>!nextSet.has(node)).forEach((node,index)=>{
      if (!shouldAnimate) { node.remove(); return; }
      const rect=node.getBoundingClientRect();
      node.dataset.s37Exiting='true';
      node.setAttribute('aria-hidden','true');
      node.inert=true;
      node.style.position='absolute';
      node.style.left=(rect.left-parentRect.left)+'px';
      node.style.top=(rect.top-parentRect.top)+'px';
      node.style.width=rect.width+'px';
      node.style.height=rect.height+'px';
      node.style.pointerEvents='none';
      const animation=node.animate([
        {opacity:1,transform:'translateX(0) scale(1)'},
        {opacity:0,transform:'translateX('+(direction*34)+'px) scale(.985)'}
      ],{duration:270,delay:index*22,easing:'cubic-bezier(.4,0,.8,.4)',fill:'forwards'});
      animation.finished.then(()=>{if(run===transitionRun&&node.isConnected)node.remove();}).catch(()=>{});
    });
    const fragment=document.createDocumentFragment();
    nextNodes.forEach((node)=>fragment.appendChild(node));
    eventsNode.insertBefore(fragment,eventsNode.querySelector('[data-s37-exiting]'));
    if (shouldAnimate) {
      nextNodes.filter((node)=>!oldLive.includes(node)).forEach((node,index)=>{
        node.animate([
          {opacity:0,transform:'translateX('+(-direction*26)+'px) scale(.99)'},
          {opacity:1,transform:'translateX(0) scale(1)'}
        ],{duration:330,delay:70+index*38,easing:'cubic-bezier(.2,.75,.2,1)',fill:'both'});
      });
    }
  }

  function renderDay(focus=null, message='', direction=1) {
    const d=dateFor(selectedDay), items=data[selectedDay];
    const nextTitle=longDays[selectedDay]+', '+dateLabel(d);
    const titleChanged=dayTitle.textContent!==nextTitle;
    dayTitle.textContent=nextTitle;
    if(titleChanged&&!reduceMotion.matches){
      dayTitle.getAnimations().forEach((animation)=>animation.cancel());
      dayTitle.animate([{opacity:.35,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
    daySummary.textContent=items.length?(items.length+' '+(items.length===1?'событие':'события')):'Свободный день';
    eventsNode.className='s37-events'+(items.length===1?' s37-events--single':items.length>1?' s37-events--multiple':' s37-events--free');
    renderEvents(items,direction);
    applyFocus(focus);
    note.textContent=message||'Синтетический пример · повторяющийся шаблон недели, переходы здесь не подключены';
  }

  function selectDay(index,focus=null,message='',direction=null) {
    if(index<0||index>6)return;
    const previous=selectedDay;
    selectedDay=index;
    renderWeek();
    renderDay(focus,message,direction!==null?direction:(previous===index?1:index>previous?1:-1));
  }

  function sceneAt(progress) {
    const index=Math.min(scenes.length-1,Math.floor(clamp(progress)*scenes.length));
    return {...scenes[index],local:clamp((clamp(progress)*scenes.length)-index)};
  }

  function activateScene(scene) {
    if(activeScene===scene.key)return;
    const revealRun=++copyRevealRun;
    activeScene=scene.key;
    story.dataset.s37Scene=scene.key;
    const sideChanged=story.dataset.s37Side!==scene.side;
    const copy=copyBlocks.find((block)=>block.dataset.s37CopyBlock===scene.copy);
    pendingCopy=sideChanged?scene.key:null;
    story.dataset.s37Side=scene.side;
    story.toggleAttribute('data-s37-moving',sideChanged);
    copyBlocks.forEach((block)=>{
      const active=block===copy;
      block.hidden=!active||sideChanged;
      block.setAttribute('aria-hidden',String(!active||sideChanged));
      block.dataset.copyState=active?'entering':'inactive';
    });
    if(sideChanged&&copy){
      window.setTimeout(()=>{
        if(revealRun!==copyRevealRun||pendingCopy!==scene.key||activeScene!==scene.key)return;
        copy.hidden=false;copy.setAttribute('aria-hidden','false');copy.dataset.copyState='readable';
        story.removeAttribute('data-s37-moving');pendingCopy=null;
      },440);
    }
    progressLabel.textContent=scene.label;
    selectDay(scene.day,null,'Синтетический пример · реконструкция ученического /schedule');
  }

  function setStatic(enabled) {
    if(staticMode===enabled)return;
    staticMode=enabled;story.toggleAttribute('data-s37-static',enabled);
    if(!enabled){activeScene=null;return;}
    activeScene='static';story.dataset.s37Side='right';story.dataset.s37Scene='static';story.removeAttribute('data-s37-moving');
    copyBlocks.forEach((block)=>{block.hidden=false;block.setAttribute('aria-hidden','false');block.dataset.copyState='readable';});
    workspace.dataset.attention='read';applyFocus(null);
    progressLabel.textContent='Ученическое расписание';progressBar.style.transform='scaleX(1)';
  }

  function update(progress) {
    const isStatic=reduceMotion.matches;
    setStatic(isStatic);
    if(isStatic||typeof progress!=='number')return;
    lastProgress=progress;
    const scene=sceneAt(progress);
    if(manualOverride&&scene.key===manualLockScene){progressBar.style.transform='scaleX('+progress+')';return;}
    if(manualOverride){manualOverride=false;manualLockScene=null;}
    activeSceneLocal=scene.local;activateScene(scene);
    const attention=scene.local<.2?'read':scene.local<.6?'watch':scene.local<.88?'understand':'move';
    workspace.dataset.attention=attention;
    applyFocus(scene.local<.2||scene.local>=.88?null:scene.focus);
    if(scene.key==='context'&&scene.local>=.34)applyFocus(scene.focus);
    progressBar.style.transform='scaleX('+progress+')';
  }

  function holdNarrativeForCurrentScene() {
    manualLockScene=sceneAt(lastProgress).key;
    manualOverride=true;
  }

  daysNode.addEventListener('click',(event)=>{
    const button=event.target.closest('[data-s37-day]');
    if(button){holdNarrativeForCurrentScene();selectDay(Number(button.dataset.s37Day),null,'День выбран вручную · выбор останется до следующего эпизода');}
  });
  story.querySelectorAll('[data-s37-week-step]').forEach((button)=>button.addEventListener('click',()=>{
    holdNarrativeForCurrentScene();
    const direction=Number(button.dataset.s37WeekStep);
    weekOffset+=direction;
    renderWeek();
    renderDay(null,'Неделя сдвинута в preview · пример повторяет синтетический шаблон',direction);
  }));
  story.querySelector('[data-s37-week-today]').addEventListener('click',()=>{
    holdNarrativeForCurrentScene();
    const direction=weekOffset===0?(selectedDay===0?1:-1):(weekOffset>0?-1:1);
    weekOffset=0;
    selectDay(0,null,'Сегодня · синтетический календарь начинается 2 ноября 2026 года',direction);
  });
  story.addEventListener('click',(event)=>{
    const action=event.target.closest('[data-s37-action]');
    if(action){event.preventDefault();note.textContent='Синтетический preview. В продукте действие открывает комнату занятия, страницу сдачи или раздел теории.';}
  });
  document.addEventListener('boostudy:story-progress',(event)=>{if(typeof event.detail.s37==='number')update(event.detail.s37);});
  reduceMotion.addEventListener?.('change',()=>update(0));
  window.addEventListener('resize',updateDayMarker,{passive:true});

  renderWeek(false);renderDay();update(0);
})();
