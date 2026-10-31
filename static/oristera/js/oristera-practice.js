/**
 * PROJECT ORISTERA — PRACTICE RUNNER
 * Interactive Python execution & feedback
 */
(function() {
  'use strict';

  function initPractice() {
    const runBtn = document.getElementById('ori-run-code-btn');
    const editor = document.getElementById('ori-code-editor');
    const consoleOutput = document.getElementById('ori-console-output');

    if (!runBtn || !editor || !consoleOutput) return;

    // Avoid double attaching
    if (runBtn.dataset.bound === '1') return;
    runBtn.dataset.bound = '1';

    runBtn.addEventListener('click', async () => {
      const code = editor.value;
      if (!code.trim()) {
        consoleOutput.textContent = 'Введите Python-код для выполнения.';
        return;
      }

      runBtn.disabled = true;
      runBtn.textContent = 'Выполняется…';
      consoleOutput.textContent = 'Инициализация изолированной среды Python...\n';

      try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        const res = await fetch('/oristera/api/practice/run', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken || '',
          },
          body: JSON.stringify({ code: code, timeout: 5 }),
        });

        const data = await res.json();
        if (data.success) {
          const stdout = data.stdout || '';
          const stderr = data.stderr || '';
          consoleOutput.textContent = (stdout + (stderr ? '\n[Ошибки]:\n' + stderr : '')).trim() || '(Программа завершилась без вывода)';
        } else {
          consoleOutput.textContent = `Ошибка выполнения: ${data.error || 'Неизвестная ошибка'}`;
        }
      } catch (err) {
        consoleOutput.textContent = `Ошибка сети: ${err.message}`;
      } finally {
        runBtn.disabled = false;
        runBtn.textContent = 'Запустить код';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', initPractice);
  window.addEventListener('ori:space-entered', (e) => {
    if (e.detail && e.detail.path.includes('practice')) {
      initPractice();
    }
  });
})();
