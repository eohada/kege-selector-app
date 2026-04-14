/**
 * BooFileViewer — модальный просмотрщик файлов (текстовые через CodeMirror, Excel через таблицу).
 *
 * Глобальный API:
 *   window.BooFileViewer.openTaskFile(taskId, fileIndex)
 *   window.BooFileViewer.openWorkspaceFile(fileId, filename)
 *   window.BooFileViewer.openInEditor(fileId)
 *   window.BooFileViewer.close()
 */
(function () {
  'use strict';

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  let modal = null;
  let cmInstance = null;

  function getModal() {
    if (modal) return modal;
    modal = document.getElementById('boo-file-viewer-modal');
    return modal;
  }

  function show() {
    const m = getModal();
    if (m) {
      m.classList.remove('hidden');
      m.style.display = '';
      document.body.style.overflow = 'hidden';
    }
  }

  function hide() {
    const m = getModal();
    if (m) {
      m.classList.add('hidden');
      m.style.display = 'none';
      document.body.style.overflow = '';
    }
    if (cmInstance) {
      cmInstance.toTextArea();
      cmInstance = null;
    }
  }

  function setLoading(on) {
    const m = getModal();
    if (!m) return;
    const loader = m.querySelector('.fv-loader');
    const content = m.querySelector('.fv-content');
    if (loader) loader.style.display = on ? '' : 'none';
    if (content) content.style.display = on ? 'none' : '';
  }

  function setTitle(title) {
    const m = getModal();
    if (!m) return;
    const el = m.querySelector('.fv-title');
    if (el) el.textContent = title;
  }

  function setError(msg) {
    const m = getModal();
    if (!m) return;
    const content = m.querySelector('.fv-content');
    if (content) content.innerHTML = `<div class="fv-error">${msg}</div>`;
  }

  function renderText(data) {
    const m = getModal();
    if (!m) return;
    const content = m.querySelector('.fv-content');
    content.innerHTML = '<textarea class="fv-cm-textarea"></textarea>';
    const ta = content.querySelector('.fv-cm-textarea');
    ta.value = data.content || '';

    if (typeof CodeMirror !== 'undefined') {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      cmInstance = CodeMirror.fromTextArea(ta, {
        mode: data.mode || 'text/plain',
        theme: isDark ? 'dracula' : 'default',
        lineNumbers: true,
        readOnly: true,
        lineWrapping: true,
      });
      cmInstance.setSize(null, '100%');
    }
  }

  function renderExcel(data) {
    const m = getModal();
    if (!m) return;
    const content = m.querySelector('.fv-content');
    const sheets = data.sheets || [];
    if (!sheets.length) {
      content.innerHTML = '<div class="fv-error">Файл пуст</div>';
      return;
    }

    let html = '';
    if (sheets.length > 1) {
      html += '<div class="fv-sheet-tabs">';
      sheets.forEach((s, i) => {
        html += `<button class="fv-sheet-tab ${i === 0 ? 'active' : ''}" data-sheet="${i}">${escHtml(s.name)}</button>`;
      });
      html += '</div>';
    }

    sheets.forEach((s, i) => {
      html += `<div class="fv-sheet-content" data-sheet="${i}" style="${i > 0 ? 'display:none' : ''}">`;
      html += '<div class="fv-table-wrap"><table class="fv-excel-table">';
      (s.rows || []).forEach((row, ri) => {
        const tag = ri === 0 ? 'th' : 'td';
        html += '<tr>';
        row.forEach(cell => {
          html += `<${tag}>${escHtml(cell)}</${tag}>`;
        });
        html += '</tr>';
      });
      html += '</table></div></div>';
    });

    content.innerHTML = html;

    content.querySelectorAll('.fv-sheet-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = btn.dataset.sheet;
        content.querySelectorAll('.fv-sheet-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        content.querySelectorAll('.fv-sheet-content').forEach(c => {
          c.style.display = c.dataset.sheet === idx ? '' : 'none';
        });
      });
    });
  }

  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  async function fetchAndRender(url) {
    show();
    setLoading(true);
    try {
      const res = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await res.json();
      setLoading(false);
      if (!data.success) {
        setError(data.error || 'Ошибка загрузки');
        return null;
      }
      setTitle(data.filename || 'Файл');
      if (data.type === 'excel') {
        renderExcel(data);
      } else {
        renderText(data);
      }
      return data;
    } catch (e) {
      setLoading(false);
      setError('Ошибка сети');
      return null;
    }
  }

  window.BooFileViewer = {
    openTaskFile(taskId, fileIndex) {
      fetchAndRender(`/workspace/task-file-content?task_id=${taskId}&file_index=${fileIndex}`);
    },

    openWorkspaceFile(fileId, filename) {
      fetchAndRender(`/workspace/${fileId}/content`);
    },

    async openInEditor(fileId) {
      try {
        const res = await fetch(`/workspace/${fileId}/content`, {
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        const data = await res.json();
        if (data.success && data.type === 'text' && data.content != null) {
          const ev = new CustomEvent('boo:load-code', { detail: { content: data.content, filename: data.filename } });
          document.dispatchEvent(ev);
        }
      } catch (_) {}
    },

    close() {
      hide();
    },
  };

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hide();
  });
})();
