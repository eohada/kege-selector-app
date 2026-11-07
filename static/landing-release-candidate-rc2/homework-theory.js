(() => {
  const reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp=(value,min=0,max=1)=>Math.min(max,Math.max(min,value));

  const homework=document.querySelector('[data-s38-homework]');
  if(homework){
    const stepNames=['arrival','brief','tools','draft','handoff'];
    const labels=['Комната открыта','Условие рядом','Инструменты по задаче','Рабочий черновик','Перед отправкой'];
    const steps=[...homework.querySelectorAll('[data-homework-step]')];
    const copies=[...homework.querySelectorAll('[data-homework-copy-scene]')];
    const app=homework.querySelector('[data-homework-app]');
    const bar=homework.querySelector('[data-homework-progress-bar]');
    const label=homework.querySelector('[data-homework-progress-label]');
    let active=-1;
    let compactActive=false;

    function showHomework(index,progress){
      index=Math.max(0,Math.min(stepNames.length-1,index));
      const key=stepNames[index];
      if(active!==index){
        active=index;
        homework.dataset.s38Scene=key;
        app.dataset.focus=key;
        steps.forEach((step,i)=>step.setAttribute('aria-current',i===index?'step':'false'));
        homework.querySelectorAll('[data-homework-scene]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.homeworkScene===key)));
        copies.forEach((copy)=>{
          const visible=copy.dataset.homeworkCopyScene===key;
          copy.hidden=!visible;
          copy.setAttribute('aria-hidden',String(!visible));
        });
        label.textContent=labels[index];
      }
      bar.style.transform='scaleX('+clamp(progress)+')';
    }

    function setStatic(){
      const enabled=reduceMotion.matches;
      homework.toggleAttribute('data-s38-static',enabled);
      if(enabled){
        if(!compactActive){compactActive=true;showHomework(0,0);}
      } else compactActive=false;
      return enabled;
    }

    document.addEventListener('boostudy:story-progress',(event)=>{
      const progress=event.detail.s38homework;
      if(typeof progress!=='number'||setStatic())return;
      showHomework(Math.min(stepNames.length-1,Math.floor(progress*stepNames.length)),progress);
    });

    homework.querySelectorAll('[data-homework-view]').forEach((button)=>button.addEventListener('click',()=>{
      const view=button.dataset.homeworkView;
      app.dataset.view=view;
      app.dataset.focus=view==='task'?'brief':view==='code'?'tools':'draft';
      homework.querySelectorAll('[data-homework-view]').forEach((item)=>item.setAttribute('aria-pressed',String(item===button)));
    }));
    homework.querySelectorAll('[data-homework-scene]').forEach((button)=>button.addEventListener('click',()=>{
      const index=stepNames.indexOf(button.dataset.homeworkScene);
      showHomework(index,(index+1)/stepNames.length);
    }));
    homework.querySelector('[data-homework-run]')?.addEventListener('click',()=>{
      const output=homework.querySelector('.s38-terminal-window pre');
      const message=homework.querySelector('.s38-terminal-window small');
      output.textContent='3840000';
      message.textContent='Расчёт показан · демонстрационное состояние';
      app.dataset.focus='draft';
      app.dataset.view='code';
      homework.querySelectorAll('[data-homework-view]').forEach((item)=>item.setAttribute('aria-pressed',String(item.dataset.homeworkView==='code')));
    });

    setStatic();
  }

  const theory=document.querySelector('[data-s38-theory]');
  if(theory){
    const stepNames=['question','branch','boundary','logic','checkpoint'];
    const topics={question:'rule',branch:'rule',boundary:'bounds',logic:'logic',checkpoint:'logic'};
    const labels={question:'Открываем тему',branch:'Правило и пример',boundary:'Проверка границ',logic:'Связанные условия',checkpoint:'Короткая проверка'};
    const steps=[...theory.querySelectorAll('[data-theory-step]')];
    const copies=[...theory.querySelectorAll('[data-theory-copy-scene]')];
    const app=theory.querySelector('[data-theory-app]');
    const bar=theory.querySelector('[data-theory-progress-bar]');
    const label=theory.querySelector('[data-theory-progress-label]');
    const sectionLabel=theory.querySelector('[data-theory-section-label]');
    let active=-1;
    let activeTopic='rule';
    let manualOverride=false;
    let manualLockScene=null;
    let currentScene='question';
    let latestProgress=0;
    let compactActive=false;

    function showTopic(topic){
      activeTopic=topic;
      app.dataset.topic=topic;
      theory.querySelectorAll('[data-theory-topic]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.theoryTopic===topic)));
      theory.querySelectorAll('[data-theory-content]').forEach((section)=>{
        const visible=section.dataset.theoryContent===topic;
        section.hidden=!visible;
        section.setAttribute('aria-hidden',String(!visible));
      });
      sectionLabel.textContent=topic==='rule'?'Правило и пример':topic==='bounds'?'Границы и примеры':'and · or';
    }

    function showTheory(index,progress){
      index=Math.max(0,Math.min(stepNames.length-1,index));
      const key=stepNames[index];
      if(active!==index){
        active=index;
        currentScene=key;
        theory.dataset.s38Scene=key;
        app.dataset.scene=key;
        steps.forEach((step,i)=>step.setAttribute('aria-current',i===index?'step':'false'));
        theory.querySelectorAll('[data-theory-scene]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.theoryScene===key)));
        copies.forEach((copy)=>{
          const visible=copy.dataset.theoryCopyScene===key;
          copy.hidden=!visible;
          copy.setAttribute('aria-hidden',String(!visible));
        });
        showTopic(topics[key]);
        theory.querySelector('[data-theory-checkpoint]').hidden=key!=='checkpoint';
        label.textContent=labels[key];
      }
      bar.style.transform='scaleX('+clamp(progress)+')';
    }

    function setStatic(){
      const enabled=reduceMotion.matches;
      theory.toggleAttribute('data-s38-static',enabled);
      if(enabled){
        if(!compactActive){compactActive=true;showTheory(0,0);}
      } else compactActive=false;
      return enabled;
    }

    document.addEventListener('boostudy:story-progress',(event)=>{
      const progress=event.detail.s38theory;
      if(typeof progress!=='number'||setStatic())return;
      latestProgress=progress;
      const index=Math.min(stepNames.length-1,Math.floor(clamp(progress)*stepNames.length));
      const key=stepNames[index];
      if(manualOverride&&key===manualLockScene){bar.style.transform='scaleX('+clamp(progress)+')';return;}
      if(manualOverride){manualOverride=false;manualLockScene=null;}
      showTheory(index,progress);
    });

    theory.querySelectorAll('[data-theory-topic]').forEach((button)=>button.addEventListener('click',()=>{
      manualLockScene=currentScene;
      manualOverride=true;
      app.dataset.scene='reading';
      theory.querySelector('[data-theory-checkpoint]').hidden=true;
      showTopic(button.dataset.theoryTopic);
    }));
    theory.querySelectorAll('[data-theory-scene]').forEach((button)=>button.addEventListener('click',()=>{
      manualOverride=false;
      manualLockScene=null;
      const index=stepNames.indexOf(button.dataset.theoryScene);
      showTheory(index,(index+1)/stepNames.length);
    }));
    theory.querySelector('[data-theory-bookmark]')?.addEventListener('click',(event)=>{
      const button=event.currentTarget;
      const saved=button.getAttribute('aria-pressed')!=='true';
      button.setAttribute('aria-pressed',String(saved));
      button.textContent=saved?'★ В закладках':'☆ Закладка';
    });
    theory.querySelectorAll('[data-theory-answer]').forEach((button)=>button.addEventListener('click',()=>{
      const correct=button.dataset.theoryAnswer==='==';
      const feedback=theory.querySelector('[data-theory-feedback]');
      feedback.textContent=correct?'Верно: == проверяет равенство. Ответ показан только в preview.':'Попробуй ещё раз: = присваивает значение, а == сравнивает.';
      feedback.dataset.result=correct?'correct':'wrong';
    }));

    setStatic();
  }
})();
