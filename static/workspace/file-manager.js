/**
 * File Manager — Alpine.js компонент для мини-хранилища файлов ученика.
 *
 * Usage (inside an Alpine scope):
 *   <div x-data="fileManager({ taskId: 123, contextType: 'submission', contextId: 456, taskFiles: [...] })">
 */
document.addEventListener('alpine:init', () => {

  function csrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  async function api(url, opts = {}) {
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    if (opts.method && opts.method !== 'GET') {
      headers['X-CSRFToken'] = csrfToken();
    }
    if (opts.json) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const res = await fetch(url, { credentials: 'same-origin', headers, ...opts });
    return res.json();
  }

  Alpine.data('fileManager', (cfg) => ({
    taskId: cfg.taskId || null,
    contextType: cfg.contextType || 'submission',
    contextId: cfg.contextId || null,
    taskFiles: cfg.taskFiles || [],
    workspaceFiles: [],
    loading: false,
    open: false,
    dragOver: false,
    renamingId: null,
    renameValue: '',
    error: '',

    async init() {
      this.taskFiles = this.normalizeTaskFiles(this.taskFiles);
      this.open = this.taskFiles.length > 0;
      if (this.taskId) await this.loadFiles();
    },

    normalizeTaskFiles(raw) {
      if (!raw) return [];
      if (Array.isArray(raw)) return raw;
      if (typeof raw === 'string') {
        try {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) return parsed;
          if (parsed && typeof parsed === 'object') return [parsed];
        } catch (_) {
          return [];
        }
      }
      if (typeof raw === 'object') return [raw];
      return [];
    },

    async loadFiles() {
      this.loading = true;
      this.error = '';
      try {
        const params = new URLSearchParams({ task_id: this.taskId, context_type: this.contextType });
        if (this.contextId) params.set('context_id', this.contextId);
        const data = await api('/workspace/files?' + params.toString());
        if (data.success) this.workspaceFiles = data.files;
        else this.error = data.error || 'Ошибка загрузки';
      } catch (e) {
        this.error = 'Ошибка сети';
      }
      this.loading = false;
    },

    async copyFromTask(fileIndex) {
      this.error = '';
      const data = await api('/workspace/copy-from-task', {
        method: 'POST',
        json: {
          task_id: this.taskId,
          file_index: fileIndex,
          context_type: this.contextType,
          context_id: this.contextId,
        },
      });
      if (data.success) {
        await this.loadFiles();
      } else {
        this.error = data.error || 'Ошибка копирования';
      }
    },

    async uploadFile(e) {
      const files = e.target.files || e.dataTransfer?.files;
      if (!files || !files.length) return;
      this.dragOver = false;
      this.error = '';

      for (const file of files) {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('task_id', this.taskId);
        fd.append('context_type', this.contextType);
        if (this.contextId) fd.append('context_id', this.contextId);

        try {
          const res = await fetch('/workspace/upload', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'X-CSRFToken': csrfToken(),
              'X-Requested-With': 'XMLHttpRequest',
            },
            body: fd,
          });
          const data = await res.json();
          if (data.success) {
            await this.loadFiles();
          } else {
            this.error = data.error || 'Ошибка загрузки';
          }
        } catch (_) {
          this.error = 'Ошибка сети при загрузке';
        }
      }
      if (e.target && e.target.value) e.target.value = '';
    },

    startRename(file) {
      this.renamingId = file.id;
      this.renameValue = file.current_filename;
    },

    async submitRename(fileId) {
      if (!this.renameValue.trim()) return;
      this.error = '';
      const data = await api(`/workspace/${fileId}/rename`, {
        method: 'POST',
        json: { new_name: this.renameValue.trim() },
      });
      if (data.success) {
        const f = this.workspaceFiles.find(x => x.id === fileId);
        if (f) f.current_filename = data.file.current_filename;
      } else {
        this.error = data.error || 'Ошибка переименования';
      }
      this.renamingId = null;
    },

    async deleteFile(fileId) {
      if (!confirm('Удалить файл из хранилища?')) return;
      this.error = '';
      const data = await api(`/workspace/${fileId}`, { method: 'DELETE' });
      if (data.success) {
        this.workspaceFiles = this.workspaceFiles.filter(x => x.id !== fileId);
      } else {
        this.error = data.error || 'Ошибка удаления';
      }
    },

    showCreateDialog: false,
    newFileName: '',

    async createFile() {
      const name = (this.newFileName || '').trim();
      if (!name) return;
      this.error = '';
      this.showCreateDialog = false;
      const data = await api('/workspace/create', {
        method: 'POST',
        json: {
          task_id: this.taskId,
          filename: name,
          context_type: this.contextType,
          context_id: this.contextId,
        },
      });
      if (data.success) {
        this.newFileName = '';
        await this.loadFiles();
      } else {
        this.error = data.error || 'Ошибка создания файла';
      }
    },

    viewTaskFile(fileIndex) {
      if (window.BooFileViewer) {
        window.BooFileViewer.openTaskFile(this.taskId, fileIndex, this.taskFiles[fileIndex]);
      }
    },

    viewWorkspaceFile(file) {
      if (window.BooFileViewer) {
        window.BooFileViewer.openWorkspaceFile(file.id, file.current_filename);
      }
    },

    editWorkspaceFile(file) {
      if (window.BooFileViewer) {
        window.BooFileViewer.editWorkspaceFile(file.id, file.current_filename);
      }
    },

    openInEditor(file) {
      if (window.BooFileViewer) {
        window.BooFileViewer.openInEditor(file.id);
      }
    },

    fileIcon(filename) {
      const ext = (filename || '').split('.').pop().toLowerCase();
      const map = {
        py: 'ph-file-py', cpp: 'ph-file-cpp', c: 'ph-file-c', java: 'ph-file-code',
        js: 'ph-file-js', json: 'ph-file-code', html: 'ph-file-html', css: 'ph-file-css',
        xlsx: 'ph-file-xls', xls: 'ph-file-xls', xlsm: 'ph-file-xls', ods: 'ph-file-xls',
        csv: 'ph-file-csv', txt: 'ph-file-text', md: 'ph-file-text',
      };
      return map[ext] || 'ph-file';
    },

    isTextFile(filename) {
      const ext = (filename || '').split('.').pop().toLowerCase();
      return ['txt','csv','tsv','py','cpp','c','h','java','js','json','xml','html','css','md','log','ini','cfg','dat','in','out','ans'].includes(ext);
    },
  }));
});
