(() => {
  const root = document.querySelector('[data-theory-experience]');
  if (!root) return;
  const form = root.querySelector('form');
  const search = form ? form.querySelector('input[type="search"]') : null;
  const buttons = form ? [...form.querySelectorAll('[data-filter]')] : [];
  const items = [...root.querySelectorAll('[data-course], [data-topic]')];
  const params = new URLSearchParams(location.search);
  let filter = buttons.some(b => b.dataset.filter === params.get('filter')) ? params.get('filter') : 'all';
  if (search) search.value = params.get('q') || '';

  function apply(updateUrl = true) {
    const query = search ? search.value.trim().toLocaleLowerCase('ru') : '';
    let visible = 0;
    items.forEach(item => {
      const isMatchFilter = (filter === 'all') || (item.dataset[filter] === 'true');
      const isMatchQuery = !query || (item.dataset.title && item.dataset.title.includes(query));
      const matches = isMatchFilter && isMatchQuery;
      item.hidden = !matches;
      if (matches) visible++;
    });
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === filter)));
    const emptyMsg = root.querySelector('[data-no-results]');
    if (emptyMsg) emptyMsg.hidden = visible > 0;
    if (updateUrl) {
      const url = new URL(location.href);
      if (query) url.searchParams.set('q', search.value); else url.searchParams.delete('q');
      if (filter !== 'all') url.searchParams.set('filter', filter); else url.searchParams.delete('filter');
      history.replaceState(null, '', url);
    }
  }

  if (form) form.addEventListener('submit', event => event.preventDefault());
  if (search) search.addEventListener('input', () => apply());
  buttons.forEach(button => button.addEventListener('click', () => { filter = button.dataset.filter; apply(); }));

  // Bookmark toggle listener
  root.addEventListener('click', async event => {
    const btn = event.target.closest('.tx-bookmark-btn');
    if (!btn) return;
    event.preventDefault();
    event.stopPropagation();
    const topicId = Number(btn.dataset.topicId);
    if (!topicId) return;

    const article = btn.closest('[data-topic]');
    const currentlyBookmarked = btn.classList.contains('is-bookmarked');
    const nextVal = !currentlyBookmarked;

    // Optimistic UI update
    btn.classList.toggle('is-bookmarked', nextVal);
    btn.setAttribute('title', nextVal ? 'Удалить из закладок' : 'Добавить в закладки');
    const icon = btn.querySelector('i');
    if (icon) {
      icon.className = nextVal ? 'ph-fill text-amber-500 ph-bookmark-simple' : 'ph-bold text-slate-400 ph-bookmark-simple';
    }
    if (article) {
      article.dataset.bookmarked = nextVal ? 'true' : 'false';
    }

    try {
      const resp = await fetch('/theory/api/bookmark', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
        },
        body: JSON.stringify({ block_id: topicId, value: nextVal }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.success) throw new Error(data.error || 'Ошибка при обновлении закладки');

      if (window.BooNotify?.success) {
        window.BooNotify.success(data.bookmarked ? 'Тема сохранена в закладках' : 'Тема удалена из закладок');
      }
      if (filter === 'bookmarked') {
        apply(false);
      }
    } catch (e) {
      // Revert optimistic update
      btn.classList.toggle('is-bookmarked', currentlyBookmarked);
      btn.setAttribute('title', currentlyBookmarked ? 'Удалить из закладок' : 'Добавить в закладки');
      if (icon) {
        icon.className = currentlyBookmarked ? 'ph-fill text-amber-500 ph-bookmark-simple' : 'ph-bold text-slate-400 ph-bookmark-simple';
      }
      if (article) {
        article.dataset.bookmarked = currentlyBookmarked ? 'true' : 'false';
      }
      if (window.BooNotify?.error) {
        window.BooNotify.error(e.message || 'Не удалось обновить закладку');
      }
    }
  });

  apply(false);
})();
