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
  const narrowViewport = window.matchMedia('(max-width: 900px)');
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

  const dateFor = (i) => new Date(baseMonday.getTime() + (weekOffset*7+i)*86400000);
  const dateLabel = (d) => d.getUTCDate() + ' ' + months[d.getUTCMonth()];
  const escape = (value) => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#39;");

  function renderWeek() {
    const start=dateFor(0), end=dateFor(6);
    weekLabel.textContent=start.getUTCMonth()===end.getUTCMonth()
      ? start.getUTCDate()+' — '+end.getUTCDate()+' '+months[end.getUTCMonth()]+' '+end.getUTCFullYear()
      : dateLabel(start)+' — '+dateLabel(end)+' '+end.getUTCFullYear();
    daysNode.innerHTML=shortDays.map((name,i)=>{
      const count=data[i].length, d=dateFor(i);
      return '<button type="button" class="s37-day'+(i===selectedDay?' is-active':'')+'" data-s37-day="'+i+'" aria-pressed="'+(i===selectedDay)+'" aria-label="Выбрать '+longDays[i]+', '+dateLabel(d)+'"><span class="s37-day__name">'+name+'</span><span class="s37-day__date">'+d.getUTCDate()+'</span><span class="s37-day__events">'+(count?count+' '+(count===1?'событие':'события'):'Отдых')+'</span></button>';
    }).join('');
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
    return '<article class="s37-free-card" data-s37-card="free"><img src="/static/images/schedule/hero_mascot_3d.png" alt="Бу"><span class="s37-status s37-status--done">Отдых</span><h5>Свободный учебный день</h5><p>На сегодня обязательных уроков нет. Можно отдохнуть или вернуться к теории в удобном ритме.</p><div class="s37-free-links"><button class="s37-action s37-action--quiet" type="button" data-s37-action="theory">База знаний и теория</button></div></article>';
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

  function renderDay(focus=null, message='') {
    const d=dateFor(selectedDay), items=data[selectedDay];
    dayTitle.textContent=longDays[selectedDay]+', '+dateLabel(d);
    daySummary.textContent=items.length?(items.length+' '+(items.length===1?'событие':'события')):'Свободный день';
    eventsNode.className='s37-events'+(items.length===1?' s37-events--single':items.length>1?' s37-events--multiple':' s37-events--free');
    eventsNode.innerHTML=items.length?items.map((e)=>e.type==='lesson'?renderLesson(e):renderHomework(e)).join(''):renderFree();
    applyFocus(focus);
    note.textContent=message||'Синтетический пример · записи учебные, переходы в комнаты здесь не подключены';
  }

  function selectDay(index,focus=null,message='') {
    if(index<0||index>6)return;
    selectedDay=index;renderWeek();renderDay(focus,message);
  }

  function sceneAt(progress) {
    const index=Math.min(scenes.length-1,Math.floor(clamp(progress)*scenes.length));
    return {...scenes[index],local:clamp((clamp(progress)*scenes.length)-index)};
  }

  function activateScene(scene) {
    if(activeScene===scene.key)return;
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
        if(pendingCopy!==scene.key)return;
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
    const isStatic=reduceMotion.matches||narrowViewport.matches;
    setStatic(isStatic);
    if(isStatic||typeof progress!=='number')return;
    const scene=sceneAt(progress);activeSceneLocal=scene.local;activateScene(scene);
    const attention=scene.local<.2?'read':scene.local<.6?'watch':scene.local<.88?'understand':'move';
    workspace.dataset.attention=attention;
    applyFocus(scene.local<.2||scene.local>=.88?null:scene.focus);
    if(scene.key==='context'&&scene.local>=.34)applyFocus(scene.focus);
    progressBar.style.transform='scaleX('+progress+')';
  }

  daysNode.addEventListener('click',(event)=>{
    const button=event.target.closest('[data-s37-day]');
    if(button){activeScene=null;selectDay(Number(button.dataset.s37Day),null,'День выбран вручную · список событий обновлён');}
  });
  story.querySelectorAll('[data-s37-week-step]').forEach((button)=>button.addEventListener('click',()=>{weekOffset+=Number(button.dataset.s37WeekStep);renderWeek();renderDay(null,'Неделя сдвинута в preview · записи синтетические');}));
  story.querySelector('[data-s37-week-today]').addEventListener('click',()=>{weekOffset=0;activeScene=null;selectDay(0,null,'Сегодня · примерная неделя начинается 2 ноября 2026 года');});
  story.addEventListener('click',(event)=>{
    const action=event.target.closest('[data-s37-action]');
    if(action){event.preventDefault();note.textContent='Синтетический preview. В продукте действие открывает комнату занятия, страницу сдачи или раздел теории.';}
  });
  document.addEventListener('boostudy:story-progress',(event)=>update(event.detail.s37));
  reduceMotion.addEventListener?.('change',()=>update(0));
  narrowViewport.addEventListener?.('change',()=>update(0));

  renderWeek();renderDay();update(0);
})();
