(function () {
  'use strict';

  var hero = document.querySelector('.boo-hero img');
  if (hero) hero.src = '/static/images/demo/boo-onboarding-hero-v2.png';
  var scenes = ['scene-dialogue', 'scene-name', 'scene-goal'];
  function show(id) {
    scenes.forEach(function (scene) {
      document.getElementById(scene).classList.toggle('active', scene === id);
    });
    document.querySelector('.panel').scrollIntoView({
      block: 'start',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
    });
  }
  document.querySelectorAll('.choice').forEach(function (choice) {
    choice.addEventListener('click', function () {
      document.querySelectorAll('.choice').forEach(function (item) { item.classList.remove('selected'); });
      choice.classList.add('selected');
      document.getElementById('reaction').textContent = choice.dataset.reaction;
      document.getElementById('continue').disabled = false;
    });
  });
  var gradeSelect = document.getElementById('grade');
  var gradeTrigger = document.getElementById('grade-trigger');
  var gradeMenu = document.getElementById('grade-menu');
  var gradeLabel = document.getElementById('grade-label');
  if (gradeSelect && gradeTrigger && gradeMenu && gradeLabel) {
    function closeGradeMenu() {
      gradeMenu.hidden = true;
      gradeTrigger.setAttribute('aria-expanded', 'false');
    }
    gradeTrigger.addEventListener('click', function () {
      var isOpen = !gradeMenu.hidden;
      gradeMenu.hidden = isOpen;
      gradeTrigger.setAttribute('aria-expanded', String(!isOpen));
    });
    gradeMenu.querySelectorAll('[data-value]').forEach(function (option) {
      option.addEventListener('click', function () {
        gradeSelect.value = option.dataset.value;
        gradeLabel.textContent = option.textContent;
        gradeMenu.querySelectorAll('[data-value]').forEach(function (item) {
          var selected = item === option;
          item.classList.toggle('is-selected', selected);
          item.setAttribute('aria-selected', String(selected));
        });
        closeGradeMenu();
        gradeTrigger.focus();
      });
    });
    document.addEventListener('click', function (event) {
      if (!event.target.closest('[data-grade-select]')) closeGradeMenu();
    });
    gradeTrigger.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeGradeMenu();
    });
  }
  document.getElementById('continue').onclick = function () { show('scene-name'); };
  document.getElementById('to-goal').onclick = function () {
    if (!document.getElementById('name').value.trim()) { document.getElementById('name').focus(); return; }
    show('scene-goal');
  };
  function start(mode, button) {
    var status = document.getElementById('status');
    var name = document.getElementById('name').value.trim() || 'Демо-ученик';
    var grade = document.getElementById('grade').value;
    var goal = document.querySelector('input[name="goal"]:checked').value;
    var csrf = document.querySelector('meta[name="csrf-token"]').content || '';
    button.disabled = true;
    status.textContent = 'Открываю демо…';
    fetch('/demo/api/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ student_name: name, grade: grade, exam: goal.indexOf('oge') === 0 ? 'oge' : 'ege', goal: goal, mode: mode, start_at_dashboard: true })
    }).then(function (response) {
      return response.json().then(function (data) { if (!response.ok || !data.success) throw new Error(); return data; });
    }).then(function (data) {
      window.BooDemoEngine.init(data.state);
      sessionStorage.setItem('boo-cinematic-boot', 'chapter2');
      window.location.assign(data.dashboard_url || '/dashboard');
    }).catch(function () {
      button.disabled = false;
      status.textContent = 'Не удалось открыть демо-кабинет. Попробуй ещё раз.';
    });
  }
  document.getElementById('start').onclick = function () { start('guided', this); };
}());
