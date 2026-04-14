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
  const textPreviewExtensions = new Set([
    'txt', 'csv', 'tsv', 'py', 'cpp', 'c', 'h', 'java', 'js',
    'json', 'xml', 'html', 'css', 'md', 'log', 'ini', 'cfg',
    'dat', 'in', 'out', 'ans',
  ]);
  const inlinePreviewExtensions = new Set([
    ...textPreviewExtensions,
    'xls', 'xlsx', 'xlsm',
  ]);

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

  function renderUnsupported(data) {
    const m = getModal();
    if (!m) return;
    const content = m.querySelector('.fv-content');
    const downloadUrl = data.download_url ? escHtml(data.download_url) : '';
    const message = escHtml(data.error || 'Предпросмотр для этого файла не поддерживается.');
    content.innerHTML = `
      <div style="padding:2rem; max-width:560px; margin:0 auto; text-align:center;">
        <div style="font-size:3rem; line-height:1; color:var(--text-muted, #94a3b8); margin-bottom:1rem;">
          <i class="ph-bold ph-file-arrow-down"></i>
        </div>
        <div style="font-size:1rem; font-weight:700; margin-bottom:0.5rem;">Предпросмотр недоступен</div>
        <div style="color:var(--text-muted, #64748b); margin-bottom:1.25rem;">${message}</div>
        ${downloadUrl ? `
          <a href="${downloadUrl}" target="_blank" rel="noopener noreferrer"
             style="display:inline-flex; align-items:center; gap:0.5rem; padding:0.75rem 1rem; border-radius:12px; text-decoration:none; background:var(--accent-1, #6366f1); color:#fff; font-weight:600;">
            <i class="ph-bold ph-download-simple"></i>
            <span>Открыть или скачать файл</span>
          </a>
        ` : ''}
      </div>
    `;
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

  function fileNameFromTaskMeta(fileMeta) {
    if (typeof fileMeta === 'string') {
      const raw = fileMeta.split('?')[0];
      return raw.split('/').pop() || 'file';
    }
    if (fileMeta && typeof fileMeta === 'object') {
      const named = fileMeta.name || fileMeta.filename;
      if (named) return String(named);
      const raw = String(fileMeta.path || fileMeta.url || 'file').split('?')[0];
      return raw.split('/').pop() || 'file';
    }
    return 'file';
  }

  function extOf(name) {
    const idx = String(name || '').lastIndexOf('.');
    return idx >= 0 ? String(name).slice(idx + 1).toLowerCase() : '';
  }

  function isInlinePreviewable(fileMeta) {
    const filename = fileNameFromTaskMeta(fileMeta);
    return inlinePreviewExtensions.has(extOf(filename));
  }

  function buildTaskDownloadUrl(taskId, fileMeta) {
    if (!fileMeta) return '';
    if (typeof fileMeta === 'string') {
      const raw = fileMeta.trim();
      const filename = fileNameFromTaskMeta(raw);
      if (/^https?:\/\//i.test(raw)) return raw;
      if (raw.startsWith('/attachments/task/')) return raw;
      if (raw.startsWith('/')) return raw;
      return `/attachments/task/${encodeURIComponent(taskId)}/${encodeURIComponent(filename)}`;
    }

    const path = String(fileMeta.path || '').trim();
    const url = String(fileMeta.url || '').trim();
    const filename = fileNameFromTaskMeta(fileMeta);

    if (url) return url;
    if (path.startsWith('/attachments/task/')) return path;
    if (path.startsWith('/')) return path;
    if (path) return `/attachments/task/${encodeURIComponent(taskId)}/${encodeURIComponent(filename)}`;
    return '';
  }

  function buildTaskFetchUrl(taskId, fileMeta) {
    if (!fileMeta) return '';
    if (typeof fileMeta === 'string') {
      const raw = fileMeta.trim();
      if (/^https?:\/\/kompege\.ru\//i.test(raw)) {
        return `/attachments/proxy?url=${encodeURIComponent(raw)}`;
      }
      return buildTaskDownloadUrl(taskId, raw);
    }

    const path = String(fileMeta.path || '').trim();
    const url = String(fileMeta.url || '').trim();
    if (/^https?:\/\/kompege\.ru\//i.test(url)) {
      return `/attachments/proxy?url=${encodeURIComponent(url)}`;
    }
    if (path) return buildTaskDownloadUrl(taskId, fileMeta);
    return url || '';
  }

  async function fetchTaskTextDirect(taskId, fileMeta) {
    const url = buildTaskFetchUrl(taskId, fileMeta);
    if (!url) throw new Error('No direct task file url');

    const res = await fetch(url, {
      credentials: 'same-origin',
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const filename = fileNameFromTaskMeta(fileMeta);
    const ext = extOf(filename);
    const text = await res.text();
    return {
      success: true,
      type: 'text',
      filename,
      content: text,
      mode: ({
        py: 'python',
        cpp: 'text/x-c++src',
        c: 'text/x-csrc',
        h: 'text/x-csrc',
        java: 'text/x-java',
        js: 'javascript',
        json: 'application/json',
        xml: 'xml',
        html: 'htmlmixed',
        css: 'css',
        md: 'markdown',
      })[ext] || 'text/plain',
    };
  }

  async function fetchAndRender(url) {
    show();
    setLoading(true);
    try {
      const res = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });

      let data = null;
      try {
        data = await res.json();
      } catch (_) {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        throw new Error('Invalid JSON response');
      }

      setLoading(false);
      if (!res.ok || !data.success) {
        setError(data.error || 'Ошибка загрузки');
        return null;
      }
      setTitle(data.filename || 'Файл');
      if (data.type === 'excel') {
        renderExcel(data);
      } else if (data.type === 'unsupported') {
        renderUnsupported(data);
      } else {
        renderText(data);
      }
      return data;
    } catch (e) {
      setLoading(false);
      setError('Не удалось загрузить файл. Попробуйте открыть его ещё раз или скачать напрямую.');
      return null;
    }
  }

  window.BooFileViewer = {
    openTaskFile(taskId, fileIndex, fileMeta) {
      const filename = fileNameFromTaskMeta(fileMeta);
      const ext = extOf(filename);

      if (fileMeta && textPreviewExtensions.has(ext)) {
        show();
        setTitle(filename || 'Файл');
        setLoading(true);
        fetchTaskTextDirect(taskId, fileMeta)
          .then((data) => {
            setLoading(false);
            renderText(data);
          })
          .catch(() => {
            setLoading(false);
            const directUrl = buildTaskFetchUrl(taskId, fileMeta) || buildTaskDownloadUrl(taskId, fileMeta);
            if (directUrl) {
              window.open(directUrl, '_blank', 'noopener');
              hide();
              return;
            }
            fetchAndRender(`/workspace/task-file-content?task_id=${taskId}&file_index=${fileIndex}`);
          });
        return;
      }

      if (fileMeta && !isInlinePreviewable(fileMeta)) {
        const directUrl = buildTaskDownloadUrl(taskId, fileMeta);
        if (directUrl) {
          window.open(directUrl, '_blank', 'noopener');
          return;
        }
      }
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
