(() => {
  const root = document.getElementById('tutorCore3');
  const button = document.getElementById('seedTutorCore3');
  if (!root || !button) return;

  const feedback = document.getElementById('tc3Feedback');
  const csrf = root.dataset.csrf || '';

  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Создаём synthetic-only пример…';
    feedback.textContent = 'Подготавливаем Knowledge Base, версии навыков и отдельную копию курса.';

    try {
      const response = await fetch(root.dataset.seedUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
        },
        body: JSON.stringify({}),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.ok) {
        throw new Error(body.error || `Не удалось создать демо (HTTP ${response.status}).`);
      }
      feedback.textContent = body.created
        ? 'Демо создано. Открываем учебную цепочку.'
        : 'Демо уже существует; повторные данные не добавлены.';
      window.location.reload();
    } catch (error) {
      feedback.textContent = error instanceof Error ? error.message : 'Не удалось создать локальный пример.';
      button.disabled = false;
      button.textContent = 'Повторить создание';
    }
  });
})();
