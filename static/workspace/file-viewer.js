/**
 * BooFileViewer — модальный просмотрщик файлов (текстовые через CodeMirror, Excel через таблицу).
 *
 * Глобальный API:
 *   window.BooFileViewer.openTaskFile(taskId, fileIndex, fileMeta, contextType, contextId)
 *   window.BooFileViewer.openWorkspaceFile(fileId, filename)
 *   window.BooFileViewer.openInEditor(fileId)
 *   window.BooFileViewer.editWorkspaceFile(fileId, filename)
 *   window.BooFileViewer.close()
 */
(function () {
  'use strict';

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  var modal = null;
  var cmInstance = null;
  var _currentFileId = null;

  var TEXT_EXTENSIONS = new Set([
    'txt', 'csv', 'tsv', 'py', 'cpp', 'c', 'h', 'java', 'js',
    'json', 'xml', 'html', 'css', 'md', 'log', 'ini', 'cfg',
    'dat', 'in', 'out', 'ans',
  ]);

  var CODEMIRROR_MODES = {
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
    var m = getModal();
    if (m) {
      m.classList.remove('hidden');
      m.style.display = '';
      document.body.style.overflow = 'hidden';
    }
  }

  function hide() {
    var m = getModal();
    if (m) {
      m.classList.add('hidden');
      m.style.display = 'none';
      document.body.style.overflow = '';
    }
    if (cmInstance) {
      cmInstance.toTextArea();
      cmInstance = null;
    }
    _currentFileId = null;
    _updateHeaderButtons(null);
  }

  function setLoading(on) {
    var m = getModal();
    if (!m) return;
    var loader = m.querySelector('.fv-loader');
    var content = m.querySelector('.fv-content');
    if (loader) loader.style.display = on ? '' : 'none';
    if (content) content.style.display = on ? 'none' : '';
  }

  function setTitle(title) {
    var m = getModal();
    if (!m) return;
    var el = m.querySelector('.fv-title');
    if (el) el.textContent = title;
  }

  function setError(msg) {
    var m = getModal();
    if (!m) return;
    var content = m.querySelector('.fv-content');
    if (content) content.innerHTML = '<div class="fv-error">' + escHtml(msg) + '</div>';
  }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function _updateHeaderButtons(mode) {
    var m = getModal();
    if (!m) return;
    var editBtn = m.querySelector('.fv-btn-edit');
    var saveBtn = m.querySelector('.fv-btn-save');
    if (editBtn) editBtn.style.display = (mode === 'view') ? '' : 'none';
    if (saveBtn) saveBtn.style.display = (mode === 'edit') ? '' : 'none';
    if (_currentFileId) m.dataset.fileId = _currentFileId;
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

  function taskAttachmentUrl(taskId, fileMeta) {
    var filename = fileNameFromMeta(fileMeta);
    if (!filename || filename === 'file') {
      if (typeof fileMeta === 'string') {
        filename = fileMeta.split('?')[0].split('/').pop() || 'file';
      }
    }
    return '/attachments/task/' + encodeURIComponent(taskId) + '/' + encodeURIComponent(filename);
  }

  function colLetter(index) {
    var s = '';
    var n = index;
    while (n >= 0) {
      s = String.fromCharCode(65 + (n % 26)) + s;
      n = Math.floor(n / 26) - 1;
    }
    return s;
  }

  /* ---- Renderers ---- */

  function renderText(data, editable) {
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
        readOnly: editable ? false : true,
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
      var rows = s.rows || [];
      var maxCols = 0;
      rows.forEach(function (r) { if (r.length > maxCols) maxCols = r.length; });

      html += '<div class="fv-sheet-content" data-sheet="' + i + '" style="' + (i > 0 ? 'display:none' : '') + '">';
      html += '<div class="fv-table-wrap"><table class="fv-excel-table">';

      html += '<thead><tr><th class="fv-row-num fv-col-header"></th>';
      for (var ci = 0; ci < maxCols; ci++) {
        html += '<th class="fv-col-header">' + colLetter(ci) + '</th>';
      }
      html += '</tr></thead><tbody>';

      rows.forEach(function (row, ri) {
        html += '<tr><td class="fv-row-num">' + (ri + 1) + '</td>';
        for (var c = 0; c < maxCols; c++) {
          html += '<td>' + escHtml(c < row.length ? row[c] : '') + '</td>';
        }
        html += '</tr>';
      });

      html += '</tbody></table></div></div>';
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
            '<i class="ph-bold ph-download-simple"></i><span>Скачать файл</span></a>'
          : '') +
      '</div>';
  }

  /* ---- Core fetch-and-render via backend JSON endpoint ---- */

  async function fetchAndRender(url, opts) {
    opts = opts || {};
    show();
    setLoading(true);
    _updateHeaderButtons(null);
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
        var editable = opts.editable || false;
        renderText(data, editable);
        if (opts.fileId) {
          _currentFileId = opts.fileId;
          _updateHeaderButtons(editable ? 'edit' : 'view');
        }
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

  /* ---- Save content ---- */

  async function saveCurrentFile() {
    if (!_currentFileId || !cmInstance) return;
    var content = cmInstance.getValue();
    try {
      var res = await fetch('/workspace/' + encodeURIComponent(_currentFileId) + '/save-content', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ content: content }),
      });
      var data = await res.json();
      if (data.success) {
        if (typeof showToast === 'function') showToast('Файл сохранён', 'success');
      } else {
        if (typeof showToast === 'function') showToast(data.error || 'Ошибка сохранения', 'error');
      }
    } catch (_) {
      if (typeof showToast === 'function') showToast('Ошибка сети при сохранении', 'error');
    }
  }

  /* ---- Public API ---- */

  window.BooFileViewer = {
    openTaskFile: function (taskId, fileIndex, fileMeta, contextType, contextId) {
      var filename = fileNameFromMeta(fileMeta);
      var backendUrl = '/workspace/task-file-content?task_id=' + encodeURIComponent(taskId) + '&file_index=' + encodeURIComponent(fileIndex);
      if (contextType) backendUrl += '&context_type=' + encodeURIComponent(contextType);
      if (contextId) backendUrl += '&context_id=' + encodeURIComponent(contextId);

      fetchAndRender(backendUrl);
    },

    openWorkspaceFile: function (fileId, filename) {
      fetchAndRender('/workspace/' + encodeURIComponent(fileId) + '/content', { fileId: fileId });
    },

    editWorkspaceFile: function (fileId, filename) {
      fetchAndRender('/workspace/' + encodeURIComponent(fileId) + '/content', { fileId: fileId, editable: true });
    },

    openInEditor: async function (fileId) {
      try {
        var res = await fetch('/workspace/' + encodeURIComponent(fileId) + '/content', {
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        var data = await res.json();
        if (data.success && data.type === 'text' && data.content != null) {
          document.dispatchEvent(new CustomEvent('boo:load-code', { detail: { content: data.content, filename: data.filename } }));
        }
      } catch (_) { /* silent */ }
    },

    save: saveCurrentFile,

    close: function () {
      hide();
    },
  };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') hide();
    if ((e.ctrlKey || e.metaKey) && e.key === 's' && _currentFileId && cmInstance) {
      e.preventDefault();
      saveCurrentFile();
    }
  });
})();
