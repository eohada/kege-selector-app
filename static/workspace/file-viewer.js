/**
 * BooFileViewer — модальный просмотрщик файлов (текстовые через CodeMirror, Excel через таблицу).
 *
 * Глобальный API:
 *   window.BooFileViewer.openTaskFile(taskId, fileIndex, fileMeta)
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

  const TEXT_EXTENSIONS = new Set([
    'txt', 'csv', 'tsv', 'py', 'cpp', 'c', 'h', 'java', 'js',
    'json', 'xml', 'html', 'css', 'md', 'log', 'ini', 'cfg',
    'dat', 'in', 'out', 'ans',
  ]);

  const CODEMIRROR_MODES = {
    py: 'python', cpp: 'text/x-c++src', c: 'text/x-csrc', h: 'text/x-csrc',
    java: 'text/x-java', js: 'javascript', json: 'application/json',
    xml: 'xml', html: 'htmlmixed', css: 'css', md: 'markdown',
  };

  /* ---- DOM helpers ---- */

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
    if (content) content.innerHTML = '<div class="fv-error">' + escHtml(msg) + '</div>';
  }

  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /* ---- File metadata helpers ---- */

  function fileNameFromMeta(fileMeta) {
    if (typeof fileMeta === 'string') {
      return fileMeta.split('?')[0].split('/').pop() || 'file';
    }
    if (fileMeta && typeof fileMeta === 'object') {
      var named = fileMeta.name || fileMeta.filename;
      if (named) return String(named);
      return String(fileMeta.path || fileMeta.url || 'file').split('?')[0].split('/').pop() || 'file';
    }
    return 'file';
  }

  function extOf(name) {
    var idx = String(name || '').lastIndexOf('.');
    return idx >= 0 ? String(name).slice(idx + 1).toLowerCase() : '';
  }

  /**
   * Build a URL that the browser can fetch to get raw bytes of a task file.
   * Uses the existing /attachments/task/ route which handles local + proxy fallback.
   */
  function taskAttachmentUrl(taskId, fileMeta) {
    var filename = fileNameFromMeta(fileMeta);
    if (!filename || filename === 'file') {
      if (typeof fileMeta === 'string') {
        filename = fileMeta.split('?')[0].split('/').pop() || 'file';
      }
    }
    return '/attachments/task/' + encodeURIComponent(taskId) + '/' + encodeURIComponent(filename);
  }

  /* ---- Renderers ---- */

  function renderText(data) {
    var m = getModal();
    if (!m) return;
    var content = m.querySelector('.fv-content');
    content.innerHTML = '<textarea class="fv-cm-textarea"></textarea>';
    var ta = content.querySelector('.fv-cm-textarea');
    ta.value = data.content || '';

    if (typeof CodeMirror !== 'undefined') {
      var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
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
    var m = getModal();
    if (!m) return;
    var content = m.querySelector('.fv-content');
    var sheets = data.sheets || [];
    if (!sheets.length) {
      content.innerHTML = '<div class="fv-error">Файл пуст</div>';
      return;
    }

    var html = '';
    if (sheets.length > 1) {
      html += '<div class="fv-sheet-tabs">';
      sheets.forEach(function (s, i) {
        html += '<button class="fv-sheet-tab ' + (i === 0 ? 'active' : '') + '" data-sheet="' + i + '">' + escHtml(s.name) + '</button>';
      });
      html += '</div>';
    }

    sheets.forEach(function (s, i) {
      html += '<div class="fv-sheet-content" data-sheet="' + i + '" style="' + (i > 0 ? 'display:none' : '') + '">';
      html += '<div class="fv-table-wrap"><table class="fv-excel-table">';
      (s.rows || []).forEach(function (row, ri) {
        var tag = ri === 0 ? 'th' : 'td';
        html += '<tr>';
        row.forEach(function (cell) {
          html += '<' + tag + '>' + escHtml(cell) + '</' + tag + '>';
        });
        html += '</tr>';
      });
      html += '</table></div></div>';
    });

    content.innerHTML = html;

    content.querySelectorAll('.fv-sheet-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var idx = btn.dataset.sheet;
        content.querySelectorAll('.fv-sheet-tab').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        content.querySelectorAll('.fv-sheet-content').forEach(function (c) {
          c.style.display = c.dataset.sheet === idx ? '' : 'none';
        });
      });
    });
  }

  function renderUnsupported(data) {
    var m = getModal();
    if (!m) return;
    var content = m.querySelector('.fv-content');
    var downloadUrl = data.download_url ? escHtml(data.download_url) : '';
    var message = escHtml(data.error || 'Предпросмотр для этого файла не поддерживается.');
    content.innerHTML =
      '<div style="padding:2rem; max-width:560px; margin:0 auto; text-align:center;">' +
        '<div style="font-size:3rem; line-height:1; color:var(--text-muted, #94a3b8); margin-bottom:1rem;">' +
          '<i class="ph-bold ph-file-arrow-down"></i>' +
        '</div>' +
        '<div style="font-size:1rem; font-weight:700; margin-bottom:0.5rem;">Предпросмотр недоступен</div>' +
        '<div style="color:var(--text-muted, #64748b); margin-bottom:1.25rem;">' + message + '</div>' +
        (downloadUrl
          ? '<a href="' + downloadUrl + '" target="_blank" rel="noopener noreferrer"' +
            ' style="display:inline-flex; align-items:center; gap:0.5rem; padding:0.75rem 1rem; border-radius:12px;' +
            ' text-decoration:none; background:var(--accent-1, #6366f1); color:#fff; font-weight:600;">' +
            '<i class="ph-bold ph-download-simple"></i><span>Открыть или скачать файл</span></a>'
          : '') +
      '</div>';
  }

  /* ---- Core fetch-and-render via backend JSON endpoint ---- */

  async function fetchAndRender(url) {
    show();
    setLoading(true);
    try {
      var res = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });

      var data = null;
      try {
        data = await res.json();
      } catch (_) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
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
      setError('Не удалось загрузить файл. Попробуйте позже или скачайте напрямую.');
      return null;
    }
  }

  /* ---- Text fast-path: fetch raw bytes from /attachments/task/ ---- */

  async function fetchTextDirect(taskId, fileMeta) {
    var filename = fileNameFromMeta(fileMeta);
    var ext = extOf(filename);
    var url = taskAttachmentUrl(taskId, fileMeta);

    var res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('HTTP ' + res.status);

    var text = await res.text();
    return {
      success: true,
      type: 'text',
      filename: filename,
      content: text,
      mode: CODEMIRROR_MODES[ext] || 'text/plain',
    };
  }

  /* ---- Public API ---- */

  window.BooFileViewer = {
    /**
     * Preview a task's attached file.
     *
     * Strategy:
     *   1) Text files -> fetch raw from /attachments/task/ (fast, existing route)
     *      on failure -> fallback to backend /workspace/task-file-content
     *   2) Everything else -> backend /workspace/task-file-content (parses Excel, etc.)
     */
    openTaskFile: function (taskId, fileIndex, fileMeta) {
      var filename = fileNameFromMeta(fileMeta);
      var ext = extOf(filename);
      var backendUrl = '/workspace/task-file-content?task_id=' + encodeURIComponent(taskId) + '&file_index=' + encodeURIComponent(fileIndex);

      if (TEXT_EXTENSIONS.has(ext)) {
        show();
        setTitle(filename || 'Файл');
        setLoading(true);

        fetchTextDirect(taskId, fileMeta)
          .then(function (data) {
            setLoading(false);
            renderText(data);
          })
          .catch(function () {
            fetchAndRender(backendUrl);
          });
        return;
      }

      fetchAndRender(backendUrl);
    },

    openWorkspaceFile: function (fileId, filename) {
      fetchAndRender('/workspace/' + encodeURIComponent(fileId) + '/content');
    },

    openInEditor: async function (fileId) {
      try {
        var res = await fetch('/workspace/' + encodeURIComponent(fileId) + '/content', {
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        var data = await res.json();
        if (data.success && data.type === 'text' && data.content != null) {
          var ev = new CustomEvent('boo:load-code', { detail: { content: data.content, filename: data.filename } });
          document.dispatchEvent(ev);
        }
      } catch (_) { /* silent */ }
    },

    close: function () {
      hide();
    },
  };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') hide();
  });
})();
