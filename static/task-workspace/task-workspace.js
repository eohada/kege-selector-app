(function () {
    const root = document.querySelector('.tw-shell');
    if (!root) return;

    const ws = window.TASK_WORKSPACE || {};
    const CURRENT_USER_ID = Number(window.TASK_WORKSPACE_USER_ID || 0);
    const code = document.getElementById('tw-code');
    const highlight = document.getElementById('tw-highlight');
    const activeLine = document.getElementById('tw-active-line');
    const pairHl1 = document.getElementById('tw-pair-hl-1');
    const pairHl2 = document.getElementById('tw-pair-hl-2');
    const gutter = document.getElementById('tw-gutter');
    const answer = document.getElementById('tw-answer');
    const output = document.getElementById('tw-output');
    const runBtn = document.getElementById('tw-run');
    const saveBtn = document.getElementById('tw-save');
    const playbackStartBtn = document.getElementById('tw-playback-start');
    const playbackStepBackBtn = document.getElementById('tw-playback-step-back');
    const playbackPlayBtn = document.getElementById('tw-playback-play');
    const playbackStepForwardBtn = document.getElementById('tw-playback-step-forward');
    const playbackEndBtn = document.getElementById('tw-playback-end');
    const playbackSpeedSelect = document.getElementById('tw-playback-speed');
    const playbackRange = document.getElementById('tw-playback-range');
    const playbackCounter = document.getElementById('tw-playback-counter');
    const playbackAction = document.getElementById('tw-playback-action');
    const playbackList = document.getElementById('tw-playback-list');
    const versionList = document.getElementById('tw-version-list');
    const versionCount = document.getElementById('tw-version-count');
    const suggestions = document.getElementById('tw-suggestions');
    const suggestionToggle = document.getElementById('tw-toggle-suggestions');
    const importsToggle = document.getElementById('tw-imports-toggle');
    const importsMenu = document.getElementById('tw-imports-menu');
    const presence = document.getElementById('tw-presence');
    const remoteLayer = document.getElementById('tw-remote-layer');
    const statusText = document.getElementById('tw-status-text');
    const statusDot = document.getElementById('tw-status-dot');
    const turtle = document.getElementById('tw-turtle');
    const turtleEmpty = document.getElementById('tw-turtle-empty');
    const notes = document.getElementById('tw-notes');
    const storageKey = [
        'task-workspace',
        ws.context_type || 'demo',
        ws.context_id || 'none',
        ws.assignment_task_id || 'none',
        ws.task_id || 'task'
    ].join(':');
    const playback = {
        frames: Array.isArray(ws.playback?.frames) ? ws.playback.frames.slice() : [],
        index: 0,
        playing: false,
        timer: null,
        speed: 1,
    };
    const versionState = {
        items: Array.isArray(ws.versions?.items) ? ws.versions.items.slice() : [],
    };
    let isApplyingPlayback = false;
    let pendingInputMeta = null;
    let autosaveTimer = null;
    let dirtySinceAutosave = false;
    let suggestionsEnabled = true;
    let lastAppliedServerVersionId = null;
    let lastAppliedServerUpdatedAt = '';
    let liveSyncTimer = null;
    let liveSyncBusy = false;
    let workspaceSocket = null;
    let workspaceSocketReady = false;
    let workspaceDraftTimer = null;
    let workspaceLocalDraftTs = 0;
    let workspaceRemoteDraftTs = 0;
    let workspaceCursorTimer = null;
    const remoteParticipants = new Map();
    let inputSnapshot = '';

    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    function payload() {
        return {
            context_type: ws.context_type || 'demo',
            context_id: ws.context_id || null,
            assignment_task_id: ws.assignment_task_id || null,
            code: code.value,
            answer: answer.value,
            playback_frames: playback.frames,
        };
    }

    function stateFingerprint(state) {
        if (!state) return '';
        return [
            state.version_id || '',
            state.updated_at || '',
            state.code || '',
            state.answer || '',
        ].join('|');
    }

    function socketNamespace() {
        if (typeof io === 'undefined') return null;
        try {
            return io('/task-workspace', { path: '/socket.io', transports: ['websocket', 'polling'] });
        } catch (err) {
            return null;
        }
    }

    function lineInfoAtPosition(source, pos) {
        const text = String(source || '');
        const safePos = Math.max(0, Math.min(text.length, Number(pos) || 0));
        const before = text.slice(0, safePos);
        const line = before.split('\n').length;
        const lineStart = before.lastIndexOf('\n') + 1;
        return {
            line,
            column: safePos - lineStart + 1,
        };
    }

    function codeCharWidth() {
        const style = getComputedStyle(code);
        const font = `${style.fontWeight || '400'} ${style.fontSize || '15px'} ${style.fontFamily || 'monospace'}`;
        const canvas = codeCharWidth._canvas || (codeCharWidth._canvas = document.createElement('canvas'));
        const ctx = canvas.getContext('2d');
        if (!ctx) return 8;
        ctx.font = font;
        return Math.max(7, ctx.measureText('M').width);
    }

    function emitWorkspaceCursor(force = false) {
        if (!workspaceSocketReady || !workspaceSocket || ws.context_type === 'demo' || !code) return;
        if (!force) {
            if (workspaceCursorTimer) clearTimeout(workspaceCursorTimer);
            workspaceCursorTimer = setTimeout(() => emitWorkspaceCursor(true), 80);
            return;
        }
        const start = code.selectionStart || 0;
        const end = code.selectionEnd || 0;
        const info = lineInfoAtPosition(code.value || '', start);
        workspaceSocket.emit('workspace_cursor_update', {
            context_type: ws.context_type || 'demo',
            context_id: ws.context_id || null,
            assignment_task_id: ws.assignment_task_id || null,
            start,
            end,
            line: info.line,
            column: info.column,
            panel: document.querySelector('.tw-tab.is-active')?.dataset.tab || 'editor',
        });
    }

    function presenceLabel(participant) {
        const role = String(participant?.role || '').toLowerCase();
        if (role === 'creator') return 'Создатель';
        if (role === 'admin') return 'Админ';
        if (role === 'teacher') return 'Преподаватель';
        return 'Ученик';
    }

    function renderPresenceBar(participants) {
        if (!presence) return;
        const items = Array.isArray(participants) ? participants : [];
        if (!items.length) {
            presence.innerHTML = '<span class="tw-presence-empty">Ворскпейс пока открыт только у вас</span>';
            return;
        }
        presence.innerHTML = items.map((item) => {
            const mine = Number(item.user_id || 0) === Number(CURRENT_USER_ID || 0);
            const color = item.color || '#8b5cf6';
            const cursor = item.cursor || {};
            const status = cursor.panel === 'editor' ? `строка ${cursor.line || 0}, столбец ${cursor.column || 0}` : `панель ${cursor.panel || 'editor'}`;
            return `
                <span class="tw-presence-chip${mine ? ' is-self' : ''}" style="--chip-color:${escapeHtml(color)}">
                    <span class="tw-presence-dot"></span>
                    <span class="tw-presence-text">
                        <strong>${escapeHtml(item.display_name || item.username || 'user')}</strong>
                        <small>${escapeHtml(presenceLabel(item))} · ${escapeHtml(status)}</small>
                    </span>
                </span>
            `;
        }).join('');
    }

    function renderRemoteCursors() {
        if (!remoteLayer) return;
        const participants = Array.from(remoteParticipants.values())
            .filter((item) => Number(item.user_id || 0) !== Number(CURRENT_USER_ID || 0));
        if (!participants.length) {
            remoteLayer.innerHTML = '';
            return;
        }
        const metrics = editorMetrics();
        const lineHeight = metrics.lineHeight || 24;
        const paddingTop = metrics.paddingTop || 16;
        const paddingLeft = metrics.paddingLeft || 18;
        const charWidth = codeCharWidth();
        const layerTop = paddingTop - code.scrollTop;
        remoteLayer.innerHTML = participants.map((item) => {
            const cursor = item.cursor || {};
            const startLine = Math.max(1, Number(cursor.line || 1));
            const startCol = Math.max(1, Number(cursor.column || 1));
            const endInfo = lineInfoAtPosition(code.value || '', cursor.end || cursor.start || 0);
            const endLine = Math.max(startLine, Number(endInfo.line || startLine));
            const top = Math.max(0, (startLine - 1) * lineHeight + layerTop);
            const height = Math.max(lineHeight, (endLine - startLine + 1) * lineHeight);
            const left = paddingLeft + Math.max(0, startCol - 1) * charWidth - code.scrollLeft;
            const visible = top > -lineHeight && top < code.clientHeight + lineHeight * 2 && left > -40 && left < code.clientWidth + 120;
            if (!visible) return '';
            return `
                <div class="tw-remote-cursor" style="--cursor-color:${escapeHtml(item.color || '#8b5cf6')}; opacity:0.28; top:${top}px; height:${height}px; left:${left}px;">
                    <span class="tw-remote-cursor-label">${escapeHtml(item.display_name || item.username || 'user')} · ${escapeHtml(String(startLine))}:${escapeHtml(String(startCol))}</span>
                </div>
            `;
        }).join('');
    }

    function joinWorkspaceSocket() {
        if (workspaceSocket || workspaceSocketReady) return;
        workspaceSocket = socketNamespace();
        if (!workspaceSocket) return;

        const emitJoin = () => {
            if (!workspaceSocket || !ws.context_type) return;
            workspaceSocket.emit('join_workspace', {
                context_type: ws.context_type || 'demo',
                context_id: ws.context_id || null,
                assignment_task_id: ws.assignment_task_id || null,
            });
        };

        workspaceSocket.on('connect', () => {
            workspaceSocketReady = true;
            emitJoin();
        });
        workspaceSocket.on('disconnect', () => {
            workspaceSocketReady = false;
        });
        workspaceSocket.on('workspace_snapshot', (payload) => {
            const state = payload?.state || {};
            const snapshotTs = Date.now();
            if (payload?.saved_by && Number(payload.saved_by) === Number(CURRENT_USER_ID || 0)) return;
            workspaceRemoteDraftTs = Math.max(workspaceRemoteDraftTs, snapshotTs);
            if (state && typeof state === 'object') {
                applyRemoteState({
                    code: state.code || '',
                    answer: state.answer || state.plain_answer || '',
                    versions: state.versions || {},
                    playback: state.playback || {},
                    version_id: state.version_id || null,
                    updated_at: state.updated_at || '',
                }, 'Обновлено мгновенно');
            }
        });
        workspaceSocket.on('workspace_draft_updated', (payload) => {
            if (!payload) return;
            if (Number(payload.sender_id || 0) === Number(CURRENT_USER_ID || 0)) return;
            const remoteTs = Number(payload.updated_at || Date.now()) || Date.now();
            if (remoteTs < workspaceRemoteDraftTs) return;
            workspaceRemoteDraftTs = remoteTs;
            if (Array.isArray(payload.playback_frames)) {
                playback.frames = payload.playback_frames.map(sanitizeFrame);
                renderPlayback();
            }
        });
        workspaceSocket.on('workspace_patch', (payload) => {
            if (!payload) return;
            if (Number(payload.user_id || 0) === Number(CURRENT_USER_ID || 0)) return;
            const start = Math.max(0, Number(payload.start || 0));
            const end = Math.max(start, Number(payload.end || start));
            const inserted = String(payload.inserted || '');
            const before = String(code.value || '');
            const next = before.slice(0, start) + inserted + before.slice(end);
            const caret = code.selectionStart || 0;
            const delta = inserted.length - (end - start);
            code.value = next;
            if (document.activeElement === code) {
                if (caret > end) {
                    code.selectionStart = code.selectionEnd = Math.max(0, caret + delta);
                } else if (caret >= start) {
                    code.selectionStart = code.selectionEnd = start + inserted.length;
                }
            }
            updateEditorChrome();
            saveLocal();
            setStatus('Совместная правка обновлена', 'ok');
        });
        workspaceSocket.on('workspace_presence', (payload) => {
            if (!payload) return;
            const participants = Array.isArray(payload.participants) ? payload.participants : [];
            remoteParticipants.clear();
            participants.forEach((participant) => {
                if (!participant || participant.user_id == null) return;
                remoteParticipants.set(Number(participant.user_id), participant);
            });
            renderPresenceBar(participants);
            renderRemoteCursors();
        });
        workspaceSocket.on('workspace_cursor_update', (payload) => {
            if (!payload || payload.user_id == null) return;
            remoteParticipants.set(Number(payload.user_id), {
                ...(remoteParticipants.get(Number(payload.user_id)) || {}),
                ...payload,
            });
            renderPresenceBar(Array.from(remoteParticipants.values()));
            renderRemoteCursors();
        });
    }

    function emitWorkspaceDraft(force = false) {
        if (!workspaceSocketReady || !workspaceSocket || ws.context_type === 'demo') return;
        const now = Date.now();
        if (!force) {
            if (workspaceDraftTimer) clearTimeout(workspaceDraftTimer);
            workspaceDraftTimer = setTimeout(() => emitWorkspaceDraft(true), 120);
            return;
        }
        workspaceLocalDraftTs = now;
        workspaceSocket.emit('workspace_draft_update', {
            context_type: ws.context_type || 'demo',
            context_id: ws.context_id || null,
            assignment_task_id: ws.assignment_task_id || null,
            code: code.value,
            playback_frames: playback.frames,
            updated_at: now,
        });
    }

    function commonPrefix(a, b) {
        const limit = Math.min(a.length, b.length);
        let i = 0;
        while (i < limit && a[i] === b[i]) i += 1;
        return i;
    }

    function commonSuffix(a, b, prefixLimit) {
        let i = 0;
        while (a.length - 1 - i >= prefixLimit && b.length - 1 - i >= prefixLimit && a[a.length - 1 - i] === b[b.length - 1 - i]) {
            i += 1;
        }
        return i;
    }

    function emitWorkspacePatch(prevValue, nextValue) {
        if (!workspaceSocketReady || !workspaceSocket || ws.context_type === 'demo') return;
        const before = String(prevValue ?? '');
        const after = String(nextValue ?? '');
        if (before === after) return;
        if (!before.length && !after.length) return;
        const prefix = commonPrefix(before, after);
        const suffix = commonSuffix(before, after, prefix);
        workspaceSocket.emit('workspace_patch', {
            context_type: ws.context_type || 'demo',
            context_id: ws.context_id || null,
            assignment_task_id: ws.assignment_task_id || null,
            start: prefix,
            end: Math.max(prefix, before.length - suffix),
            inserted: after.slice(prefix, after.length - suffix),
            previous: before,
            next: after,
            updated_at: Date.now(),
        });
    }

    const pairs = {
        '(': ')',
        '[': ']',
        '{': '}',
        '"': '"',
        "'": "'"
    };
    const closingPairs = new Set(Object.values(pairs));
    const pyKeywords = new Set([
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class',
        'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global',
        'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return',
        'try', 'while', 'with', 'yield'
    ]);
    const builtins = new Set([
        'abs', 'all', 'any', 'bin', 'bool', 'dict', 'enumerate', 'filter', 'float', 'int', 'len',
        'list', 'map', 'max', 'min', 'open', 'pow', 'print', 'range', 'reversed', 'round', 'set',
        'sorted', 'str', 'sum', 'tuple', 'zip', 'input'
    ]);
    const suggestionBank = [
        { match: /for\s+\w+\s+in\s+range\s*\(/, title: 'Цикл for', text: 'Для перебора обычно нужны двоеточие и новый блок с отступом.', tone: 'accent' },
        { match: /if\s+.*:/, title: 'Условие if', text: 'После if/elif/else нужен блок с 4 пробелами.', tone: 'info' },
        { match: /def\s+\w+\s*\(/, title: 'Функция', text: 'Проверь, закрыты ли скобки и есть ли двоеточие после объявления.', tone: 'ok' },
        { match: /while\s+.*:/, title: 'Цикл while', text: 'После while почти всегда нужен отступ внутри цикла.', tone: 'warn' },
        { match: /print\s*\(/, title: 'print', text: 'Если печатаешь несколько значений, разделяй их запятыми или используй f-string.', tone: 'accent' },
        { match: /\bturtle\b/, title: 'turtle', text: 'Для turtle часто нужен квадратный холст, повороты и аккуратная индентация.', tone: 'info' },
    ];

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function highlightPython(source, focus) {
        const escaped = escapeHtml(source || ' ');
        const lines = escaped.split('\n');
        const currentLine = focus ? (escaped.slice(0, focus.start).match(/\n/g) || []).length : -1;
        const tokenRe = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#.*|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b|[()[\]{}.,:+\-*/%=<>!]+)/g;

        return lines.map((line, idx) => {
            const highlighted = line.replace(tokenRe, (token) => {
                if (token.startsWith('#')) return '<span class="tok-comment">' + token + '</span>';
                if (token.startsWith('"') || token.startsWith("'")) return '<span class="tok-string">' + token + '</span>';
                if (/^\d/.test(token)) return '<span class="tok-number">' + token + '</span>';
                if (pyKeywords.has(token)) return '<span class="tok-keyword">' + token + '</span>';
                if (builtins.has(token)) return '<span class="tok-builtin">' + token + '</span>';
                if (/^[()[\]{}.,:+\-*/%=<>!]+$/.test(token)) return '<span class="tok-op">' + token + '</span>';
                return token;
            });
            if (idx === currentLine) {
                return '<span class="tok-line">' + highlighted + '</span>';
            }
            return highlighted;
        }).join('\n');
    }

    function updateEditorChrome() {
        const value = code.value || '';
        const lines = Math.max(1, value.split('\n').length);
        gutter.innerHTML = Array.from({ length: lines }, (_, idx) => '<span>' + (idx + 1) + '</span>').join('');
        const focus = getCaretFocus();
        highlight.innerHTML = highlightPython(value, focus) + (value.endsWith('\n') ? '\n ' : '');
        highlight.scrollTop = code.scrollTop;
        highlight.scrollLeft = code.scrollLeft;
        gutter.scrollTop = code.scrollTop;
        suggestions.classList.toggle('is-hidden', !suggestionsEnabled);
        renderLineAndPairFocus();
        renderSuggestions();
        renderRemoteCursors();
    }

    function sanitizeFrame(frame) {
        return {
            ts: Number(frame?.ts || Date.now()),
            action: String(frame?.action || 'input'),
            detail: frame?.detail || {},
            code: String(frame?.code || ''),
            caret: Array.isArray(frame?.caret) ? [Number(frame.caret[0] || 0), Number(frame.caret[1] || 0)] : [0, 0],
        };
    }

    function getCaretFocus() {
        const start = code.selectionStart || 0;
        const end = code.selectionEnd || 0;
        const value = code.value || '';
        const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
        const lineEndIdx = value.indexOf('\n', start);
        const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx;
        return { start, end, value, lineStart, lineEnd };
    }

    function editorMetrics() {
        const styles = getComputedStyle(code);
        return {
            lineHeight: parseFloat(styles.lineHeight) || 24,
            paddingTop: parseFloat(styles.paddingTop) || 16,
            paddingLeft: parseFloat(styles.paddingLeft) || 18,
        };
    }

    function captureFrame(action, detail) {
        if (isApplyingPlayback) return;
        const frame = sanitizeFrame({
            ts: Date.now(),
            action,
            detail: detail || {},
            code: code.value,
            caret: [code.selectionStart || 0, code.selectionEnd || 0],
        });
        const last = playback.frames[playback.frames.length - 1];
        if (last && last.code === frame.code && last.caret[0] === frame.caret[0] && last.caret[1] === frame.caret[1] && last.action === frame.action) {
            return;
        }
        playback.frames.push(frame);
        playback.index = playback.frames.length - 1;
        renderPlayback();
        scheduleAutosave();
    }

    function setEditorFromFrame(frame) {
        if (!frame) return;
        isApplyingPlayback = true;
        code.value = frame.code || '';
        const caret = Array.isArray(frame.caret) ? frame.caret : [0, 0];
        code.selectionStart = Math.max(0, caret[0] || 0);
        code.selectionEnd = Math.max(0, caret[1] || 0);
        updateEditorChrome();
        renderPlayback();
        isApplyingPlayback = false;
        updateEditorChrome();
    }

    function renderPlayback() {
        const total = playback.frames.length;
        const index = total ? Math.min(playback.index, total - 1) : 0;
        playback.index = index;
        if (playbackRange) {
            playbackRange.max = String(Math.max(0, total - 1));
            playbackRange.value = String(index);
        }
        if (playbackCounter) {
            playbackCounter.textContent = total ? `${index + 1} / ${total}` : '0 / 0';
        }
        const current = total ? playback.frames[index] : null;
        if (playbackAction) {
            playbackAction.textContent = current
                ? `${current.action}${current.detail?.data ? `: ${String(current.detail.data).slice(0, 18)}` : ''}`
                : 'Запись не начата';
        }
        if (playbackPlayBtn) {
            playbackPlayBtn.textContent = playback.playing ? '⏸' : '▶';
        }
        if (playbackList) {
            playbackList.innerHTML = total
                ? playback.frames.map((frame, idx) => {
                    const active = idx === index ? ' is-active' : '';
                    const label = frame.action || 'input';
                    const snippet = (frame.code || '').replace(/\n/g, ' ↵ ').slice(0, 72);
                    return `<button type="button" class="tw-playback-item${active}" data-playback-index="${idx}"><div class="tw-playback-item-top"><span>#${idx + 1} ${escapeHtml(label)}</span><span>${new Date(frame.ts).toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span></div><small>${escapeHtml(snippet || '(пусто)')}</small></button>`;
                }).join('')
                : '<div class="tw-empty">Пока нет записанных шагов. Начни печатать код, и здесь появится лента.</div>';
            playbackList.querySelectorAll('[data-playback-index]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.playbackIndex || 0);
                    playback.index = idx;
                    setEditorFromFrame(playback.frames[idx]);
                });
            });
        }
    }

    function stopPlayback() {
        playback.playing = false;
        if (playback.timer) clearInterval(playback.timer);
        playback.timer = null;
        renderPlayback();
    }

    function stepPlayback(delta) {
        const total = playback.frames.length;
        if (!total) return;
        playback.index = Math.max(0, Math.min(total - 1, playback.index + delta));
        setEditorFromFrame(playback.frames[playback.index]);
    }

    function playPlayback() {
        if (!playback.frames.length) return;
        if (playback.playing) {
            stopPlayback();
            return;
        }
        playback.playing = true;
        renderPlayback();
        const tick = () => {
            if (!playback.playing) return;
            if (playback.index >= playback.frames.length - 1) {
                stopPlayback();
                return;
            }
            playback.index += 1;
            setEditorFromFrame(playback.frames[playback.index]);
        };
        playback.timer = setInterval(tick, Math.max(120, 900 / playback.speed));
    }

    function setStatus(text, kind) {
        if (statusText) statusText.textContent = text;
        if (statusDot) {
            statusDot.className = 'tw-status-dot';
            if (kind) statusDot.classList.add('is-' + kind);
        }
    }

    function scheduleAutosave() {
        dirtySinceAutosave = true;
        if (ws.context_type === 'demo') return;
        if (autosaveTimer) clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
            autosaveTimer = null;
            if (dirtySinceAutosave) {
                saveServer(true);
            }
        }, 2500);
    }

    function saveLocal() {
        try {
            localStorage.setItem(storageKey, JSON.stringify({
                code: code.value,
                answer: answer.value,
                notes: notes.value,
                playback_frames: playback.frames,
                updated_at: new Date().toISOString()
            }));
        } catch (err) {
            // localStorage can be disabled; server save still works.
        }
    }

    function applyRemoteState(state, reason) {
        if (!state) return false;
        const remoteCode = String(state.code || '');
        const remoteAnswer = String(state.answer || '');
        const currentCode = String(code.value || '');
        const currentAnswer = String(answer.value || '');
        const changed = remoteCode !== currentCode || remoteAnswer !== currentAnswer;
        if (!changed) {
            lastAppliedServerVersionId = state.version_id || lastAppliedServerVersionId;
            lastAppliedServerUpdatedAt = state.updated_at || lastAppliedServerUpdatedAt;
            return false;
        }

        code.value = remoteCode;
        answer.value = remoteAnswer;
        if (state.versions?.items) {
            versionState.items = state.versions.items.slice();
            renderVersions();
        }
        if (state.playback?.frames) {
            playback.frames = state.playback.frames.map(sanitizeFrame);
            renderPlayback();
        }
        updateEditorChrome();
        saveLocal();
        lastAppliedServerVersionId = state.version_id || null;
        lastAppliedServerUpdatedAt = state.updated_at || '';
        setStatus(reason || 'Синхронизировано', 'ok');
        return true;
    }

    async function pullServerState(force = false) {
        if (ws.context_type === 'demo') return;
        if (liveSyncBusy && !force) return;
        liveSyncBusy = true;
        try {
            const params = new URLSearchParams({
                context_type: ws.context_type || 'demo',
            });
            if (ws.context_id != null) params.set('context_id', String(ws.context_id));
            if (ws.assignment_task_id != null) params.set('assignment_task_id', String(ws.assignment_task_id));
            const resp = await fetch('/task-workspace/api/state?' + params.toString(), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !data.success || !data.state) return;
            const state = data.state;
            const fingerprint = stateFingerprint(state);
            const lastFingerprint = stateFingerprint({
                version_id: lastAppliedServerVersionId,
                updated_at: lastAppliedServerUpdatedAt,
                code: code.value,
                answer: answer.value,
            });
            if (fingerprint && fingerprint !== lastFingerprint) {
                const shouldPull = force || document.activeElement !== code || !dirtySinceAutosave;
                if (shouldPull) {
                    applyRemoteState(state, 'Обновлено у второго участника');
                }
            }
        } catch (err) {
            // transient sync errors are expected on poor connections
        } finally {
            liveSyncBusy = false;
        }
    }

    function restoreLocal() {
        try {
            const raw = localStorage.getItem(storageKey);
            if (!raw) return;
            const data = JSON.parse(raw);
            if (data.code && (!code.value || ws.context_type === 'demo')) code.value = data.code;
            if (data.answer && !answer.value) answer.value = data.answer;
            if (data.notes) notes.value = data.notes;
            if (Array.isArray(data.playback_frames) && data.playback_frames.length) {
                playback.frames = data.playback_frames.map(sanitizeFrame);
            }
            setStatus('Локальный черновик восстановлен', 'ok');
        } catch (err) {}
    }

    async function runCode() {
        setStatus('Запуск...', 'run');
        runBtn.disabled = true;
        output.textContent = 'Код выполняется...';
        turtle.hidden = true;
        turtleEmpty.hidden = false;
        try {
            const resp = await fetch('/task-workspace/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify(payload())
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) throw new Error(data.error || 'Не удалось запустить код');
            const chunks = [];
            if (data.stdout) chunks.push(data.stdout);
            if (data.stderr) {
                chunks.push('Ошибка Python:\n' + data.stderr);
                if (data.stderr_explained) chunks.push(data.stderr_explained);
            }
            if (!chunks.length) chunks.push('(код выполнился без вывода)');
            output.textContent = chunks.join('\n\n') + '\n\nВремя: ' + data.elapsed_ms + ' мс';
            if (data.turtle_image_b64) {
                turtle.src = 'data:' + (data.turtle_image_mime || 'image/png') + ';base64,' + data.turtle_image_b64;
                turtle.hidden = false;
                turtleEmpty.hidden = true;
                document.querySelector('[data-tab="canvas"]')?.click();
            }
            setStatus(data.status === 'error' ? 'Выполнено с ошибкой' : 'Выполнено', data.status === 'error' ? 'error' : 'ok');
        } catch (err) {
            output.textContent = String(err.message || err);
            setStatus('Ошибка запуска', 'error');
        } finally {
            runBtn.disabled = false;
        }
    }

    async function saveServer(isAutosave = false) {
        saveLocal();
        if (ws.context_type === 'demo') {
            setStatus('Сохранено локально', 'ok');
            return;
        }
        setStatus(isAutosave ? 'Автосохранение...' : 'Сохранение...', 'run');
        try {
            const resp = await fetch('/task-workspace/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify(payload())
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) throw new Error(data.error || 'Не удалось сохранить');
            dirtySinceAutosave = false;
            if (data.versions?.items) {
                versionState.items = data.versions.items.slice();
                renderVersions();
            }
            if (data.versions?.items?.length) {
                lastAppliedServerVersionId = data.versions.items[0]?.version_id || lastAppliedServerVersionId;
                lastAppliedServerUpdatedAt = data.versions.items[0]?.created_at || lastAppliedServerUpdatedAt;
            }
            setStatus(isAutosave ? 'Автосохранено' : 'Сохранено на сервере', 'ok');
        } catch (err) {
            setStatus(String(err.message || err), 'error');
        }
    }

    function insertText(text, selectionOffset, action, detail) {
        const start = code.selectionStart;
        const end = code.selectionEnd;
        code.value = code.value.slice(0, start) + text + code.value.slice(end);
        const pos = start + (typeof selectionOffset === 'number' ? selectionOffset : text.length);
        code.selectionStart = code.selectionEnd = pos;
        updateEditorChrome();
        saveLocal();
        captureFrame(action || 'insert', detail || { text, offset: selectionOffset });
    }

    function currentLineBeforeCursor() {
        const before = code.value.slice(0, code.selectionStart);
        return before.slice(before.lastIndexOf('\n') + 1);
    }

    function lineIndent(line) {
        return (line.match(/^\s*/) || [''])[0];
    }

    function repairPythonIndent(source) {
        const lines = String(source || '').replace(/\t/g, '    ').split('\n');
        let level = 0;
        const result = [];
        const dedentRe = /^(elif|else|except|finally)\b/;
        const indentAfterRe = /^(if|for|while|with|try|def|class|elif|else|except|finally)\b.*:\s*$/;
        const closingOnlyRe = /^[)\]}]+[,;]?$/;
        for (const rawLine of lines) {
            const trimmedRight = rawLine.replace(/[ \t]+$/g, '');
            const trimmed = trimmedRight.trim();
            if (!trimmed) {
                result.push('');
                continue;
            }
            if (dedentRe.test(trimmed) || closingOnlyRe.test(trimmed)) {
                level = Math.max(0, level - 1);
            }
            const normalized = normalizeInlineSpacing(trimmed);
            result.push('    '.repeat(level) + normalized);
            if (indentAfterRe.test(normalized)) {
                level += 1;
            }
        }
        return result.join('\n');
    }

    function normalizeInlineSpacing(text) {
        const src = String(text || '').trim();
        let out = '';
        let i = 0;
        let quote = null;
        let triple = false;
        let inComment = false;
        const pushSpaceIfNeeded = () => {
            if (out && !/\s$/.test(out)) out += ' ';
        };
        while (i < src.length) {
            const ch = src[i];
            const next = src.slice(i, i + 3);
            if (inComment) {
                out += src.slice(i);
                break;
            }
            if (quote) {
                out += ch;
                if (triple && next === quote + quote + quote) {
                    out += quote + quote;
                    i += 3;
                    quote = null;
                    triple = false;
                    continue;
                }
                if (!triple && ch === quote && src[i - 1] !== '\\') {
                    quote = null;
                }
                i += 1;
                continue;
            }
            if (ch === '#') {
                inComment = true;
                out += src.slice(i);
                break;
            }
            if ((next === '"""' || next === "'''") && !quote) {
                quote = ch;
                triple = true;
                out += next;
                i += 3;
                continue;
            }
            if (ch === '"' || ch === "'") {
                quote = ch;
                triple = false;
                out += ch;
                i += 1;
                continue;
            }
            if (ch === ',') {
                out = out.replace(/\s+$/g, '');
                out += ', ';
                i += 1;
                while (src[i] === ' ') i += 1;
                continue;
            }
            const op2 = src.slice(i, i + 2);
            const op3 = src.slice(i, i + 3);
            const operators = ['==', '!=', '<=', '>=', '//', '**', ':='];
            if (operators.includes(op2)) {
                out = out.replace(/\s+$/g, '');
                pushSpaceIfNeeded();
                out += op2;
                i += 2;
                while (src[i] === ' ') i += 1;
                if (i < src.length && src[i] !== ':' && src[i] !== ',' && src[i] !== ')' && src[i] !== ']' && src[i] !== '}') out += ' ';
                continue;
            }
            if (ch === '=' || ch === '+' || ch === '-' || ch === '*' || ch === '/' || ch === '%' || ch === '<' || ch === '>') {
                out = out.replace(/\s+$/g, '');
                if (out && !/\s$/.test(out)) out += ' ';
                out += ch;
                out += ' ';
                i += 1;
                while (src[i] === ' ') i += 1;
                continue;
            }
            if (ch === ':') {
                out = out.replace(/\s+$/g, '');
                out += ':';
                i += 1;
                continue;
            }
            if (ch === '(') {
                if (/\b(if|for|while|with|return|print|range|len|list|dict|set|tuple|int|str|float|bool|sum|max|min|sorted|input)\s*$/.test(out)) {
                    out = out.replace(/\s+$/g, '') + ' ';
                }
                out += '(';
                i += 1;
                while (src[i] === ' ') i += 1;
                continue;
            }
            if (ch === ')' || ch === ']' || ch === '}') {
                out = out.replace(/\s+$/g, '');
                out += ch;
                i += 1;
                continue;
            }
            if (ch === ' ') {
                if (out && !/\s$/.test(out)) out += ' ';
                i += 1;
                while (src[i] === ' ') i += 1;
                continue;
            }
            out += ch;
            i += 1;
        }
        return out.replace(/\s+$/g, '');
    }

    function formatCodeSmart(source) {
        const text = String(source || '').replace(/\r\n/g, '\n');
        const lines = text.split('\n');
        let level = 0;
        const result = [];
        const openers = /^(if|for|while|with|try|def|class|elif|else|except|finally)\b.*:\s*$/;
        const dedenters = /^(elif|else|except|finally)\b/;
        const closingOnly = /^[)\]}]+[,;]?$/;
        let inTriple = false;
        let tripleToken = '';
        for (let raw of lines) {
            const trimmedRight = raw.replace(/[ \t]+$/g, '');
            const stripped = trimmedRight.trim();
            if (!stripped) {
                result.push('');
                continue;
            }
            if (!inTriple && (dedenters.test(stripped) || closingOnly.test(stripped))) {
                level = Math.max(0, level - 1);
            }
            let normalized = normalizeInlineSpacing(stripped);
            if (normalized.includes("'''") || normalized.includes('"""')) {
                const token = normalized.includes("'''") ? "'''" : '"""';
                if (!inTriple) {
                    inTriple = true;
                    tripleToken = token;
                } else if (tripleToken === token) {
                    inTriple = false;
                    tripleToken = '';
                }
            }
            result.push('    '.repeat(level) + normalized);
            if (!inTriple && openers.test(normalized)) {
                level += 1;
            }
            if (!inTriple && /^(return|pass|break|continue|raise)\b/.test(normalized) && result.length > 1) {
                level = Math.max(0, level - 1);
            }
        }
        return result.join('\n').replace(/\n{3,}/g, '\n\n');
    }

    function getCurrentLineText() {
        const start = code.selectionStart || 0;
        const value = code.value || '';
        const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
        const lineEndIdx = value.indexOf('\n', start);
        const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx;
        return value.slice(lineStart, lineEnd);
    }

    function findMatchingPairAtCaret() {
        const value = code.value || '';
        const pos = code.selectionStart || 0;
        const before = value[pos - 1];
        const after = value[pos];
        const opens = '([{';
        const closes = ')]}';
        const pairMap = { '(': ')', '[': ']', '{': '}' };
        const reverseMap = { ')': '(', ']': '[', '}': '{' };
        const scanFrom = (index, openChar, closeChar, direction) => {
            let depth = 0;
            for (let i = index; i >= 0 && i < value.length; i += direction) {
                const ch = value[i];
                if (ch === openChar) depth += 1;
                if (ch === closeChar) {
                    depth -= 1;
                    if (depth === 0) return i;
                }
            }
            return -1;
        };
        if (opens.includes(before)) {
            return { left: pos - 1, right: scanFrom(pos, before, pairMap[before], 1) };
        }
        if (closes.includes(before)) {
            return { left: scanFrom(pos - 2, reverseMap[before], before, -1), right: pos - 1 };
        }
        if (opens.includes(after)) {
            return { left: pos, right: scanFrom(pos + 1, after, pairMap[after], 1) };
        }
        if (closes.includes(after)) {
            return { left: scanFrom(pos - 1, reverseMap[after], after, -1), right: pos };
        }
        return null;
    }

    function renderLineAndPairFocus() {
        const focus = getCaretFocus();
        const metrics = editorMetrics();
        const lineIndex = (code.value.slice(0, focus.start).match(/\n/g) || []).length;
        const lineTop = metrics.paddingTop + lineIndex * metrics.lineHeight - code.scrollTop;
        activeLine.style.top = lineTop + 'px';
        activeLine.style.height = metrics.lineHeight + 'px';
        activeLine.style.display = lineTop > -metrics.lineHeight && lineTop < code.clientHeight + metrics.lineHeight ? 'block' : 'none';

        const hints = lineContextHints();
        const hasRealHint = suggestionsEnabled && hints.length > 0 && !hints[0][0].includes('Старт') && !hints[0][0].includes('Начни с решения');
        activeLine.classList.toggle('is-hint', hasRealHint);

        const pair = findMatchingPairAtCaret();
        const renderBox = (el, index) => {
            el.style.top = (metrics.paddingTop + index * metrics.lineHeight - code.scrollTop) + 'px';
            el.style.height = metrics.lineHeight + 'px';
            el.style.display = 'block';
        };
        if (pair && pair.left >= 0 && pair.right >= 0) {
            const leftLine = (code.value.slice(0, pair.left).match(/\n/g) || []).length;
            const rightLine = (code.value.slice(0, pair.right).match(/\n/g) || []).length;
            renderBox(pairHl1, leftLine);
            renderBox(pairHl2, rightLine);
            pairHl2.classList.toggle('is-secondary', leftLine !== rightLine);
        } else {
            pairHl1.style.display = 'none';
            pairHl2.style.display = 'none';
            pairHl2.classList.remove('is-secondary');
        }
    }

    function lineContextHints() {
        const current = getCurrentLineText().trim();
        const codeText = code.value || '';
        const hints = [];
        if (!codeText.trim()) {
            hints.push(['Начни с решения', 'Добавь import, цикл или функцию — редактор подскажет отступы и скобки.', 'ok']);
            return hints;
        }
        const lastLine = current || codeText.split('\n').filter(Boolean).slice(-1)[0] || '';
        for (const item of suggestionBank) {
            if (item.match.test(codeText) || item.match.test(lastLine)) {
                hints.push([item.title, item.text, item.tone || 'accent']);
            }
        }
        if (/^for\s+.*range\s*\(\s*\)\s*:?\s*$/.test(lastLine) || /for\s+.*in\s+range\s*\(\s*$/.test(lastLine)) {
            hints.push(['Подсказка по range', 'В range() обычно нужен конец диапазона: range(n) или range(1, n).', 'info']);
        }
        if (/^\s*print\s*\(.*$/.test(lastLine) && !/\)\s*$/.test(lastLine)) {
            hints.push(['Незакрытая скобка', 'Проверь, закрыта ли скобка у print(...).', 'warn']);
        }
        if (/:\s*$/.test(lastLine) && !/\n\s{4}/.test(codeText.split('\n').slice(-1)[0] || '')) {
            hints.push(['Отступ', 'После двоеточия должен начаться новый блок с 4 пробелами.', 'accent']);
        }
        if (!hints.length) {
            hints.push(['Старт', 'Попробуй нажать Enter после двоеточия — редактор сам подставит отступ.', 'ok']);
        }
        return hints.slice(0, 4);
    }

    function renderSuggestions() {
        if (!suggestionsEnabled) {
            suggestions.innerHTML = '';
            return;
        }
        const hints = lineContextHints();
        suggestions.innerHTML = hints.map(([title, text, tone]) => (
            `<button type="button" class="tw-suggestion" data-tone="${escapeHtml(tone || 'accent')}" data-fill-suggestion="${escapeHtml(title)}"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text)}</small></button>`
        )).join('');
        suggestions.querySelectorAll('[data-fill-suggestion]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const title = btn.dataset.fillSuggestion || '';
                if (title.includes('Старт')) {
                    insertText('import turtle\n\nt = turtle.Turtle()\n', 0, 'suggestion', { title });
                } else if (title.includes('Подсказка по range')) {
                    insertText('range(1, 10)', 'range(1, 10)'.length, 'suggestion', { title });
                } else if (title.includes('Незакрытая скобка')) {
                    insertText(')', 1, 'suggestion', { title });
                } else {
                    const current = getCurrentLineText();
                    const replacement = formatCodeSmart(current || code.value);
                    if (current && current !== replacement) {
                        const start = code.selectionStart;
                        const value = code.value;
                        const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
                        const lineEndIdx = value.indexOf('\n', start);
                        const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx;
                        code.value = value.slice(0, lineStart) + replacement + value.slice(lineEnd);
                        code.selectionStart = code.selectionEnd = lineStart + replacement.length;
                        updateEditorChrome();
                        saveLocal();
                        captureFrame('suggestion', { title });
                    }
                }
            });
        });
    }

    function toggleSuggestions() {
        suggestionsEnabled = !suggestionsEnabled;
        if (suggestionToggle) {
            suggestionToggle.classList.toggle('tw-btn-primary', suggestionsEnabled);
            suggestionToggle.classList.toggle('tw-btn-ghost', !suggestionsEnabled);
            suggestionToggle.innerHTML = suggestionsEnabled ? '<i class="ph-bold ph-lightbulb"></i> Подсказки' : '<i class="ph-bold ph-lightbulb-slash"></i> Подсказки: выкл';
        }
        suggestions.classList.toggle('is-hidden', !suggestionsEnabled);
        updateEditorChrome();
    }

    function toggleImportsMenu(force) {
        if (!importsMenu) return;
        const open = typeof force === 'boolean' ? force : !importsMenu.classList.contains('is-open');
        importsMenu.classList.toggle('is-open', open);
    }

    function insertImportSnippet(snippet) {
        if (!snippet) return;
        const normalized = String(snippet).trim();
        const start = code.selectionStart || 0;
        const end = code.selectionEnd || 0;
        const before = code.value.slice(0, start);
        const after = code.value.slice(end);
        const needsNewline = before && !before.endsWith('\n') ? '\n' : '';
        const block = normalized + '\n';
        code.value = before + needsNewline + block + after;
        const pos = before.length + needsNewline.length + block.length;
        code.selectionStart = code.selectionEnd = pos;
        updateEditorChrome();
        saveLocal();
        captureFrame('import-snippet', { snippet: normalized });
    }

    function renderVersions() {
        const items = versionState.items || [];
        if (versionCount) {
            versionCount.textContent = String(items.length);
        }
        if (versionList) {
            versionList.innerHTML = items.length ? items.map((item) => {
                const preview = item.preview || item.code || '';
                return `<div class="tw-version-item">
                    <div class="tw-version-item-top">
                        <span>#${item.version_id} · ${escapeHtml(item.source || 'autosave')}</span>
                        <span>${item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : ''}</span>
                    </div>
                    <pre>${escapeHtml(preview.slice(0, 360) || '(пусто)')}</pre>
                    <div class="tw-version-actions">
                        <button type="button" class="tw-btn tw-btn-ghost" data-restore-version="${item.version_id}">Открыть</button>
                    </div>
                </div>`;
            }).join('') : '<div class="tw-empty">Пока нет серверных версий. Нажми сохранить или подожди автосохранение.</div>';
            versionList.querySelectorAll('[data-restore-version]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const id = Number(btn.dataset.restoreVersion || 0);
                    const item = items.find((x) => Number(x.version_id) === id);
                    if (!item) return;
                    code.value = item.code || '';
                    answer.value = item.answer || '';
                    updateEditorChrome();
                    saveLocal();
                    captureFrame('restore-version', { version_id: id });
                    setStatus('Версия открыта в редакторе', 'ok');
                });
            });
        }
    }

    code.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            event.preventDefault();
            runCode();
            return;
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
            event.preventDefault();
            saveServer();
            return;
        }
        if (event.key === 'Tab') {
            event.preventDefault();
            const start = code.selectionStart;
            const end = code.selectionEnd;
            const selected = code.value.slice(start, end);
            if (event.shiftKey) {
                const lineStart = code.value.lastIndexOf('\n', start - 1) + 1;
                const lineEnd = code.value.indexOf('\n', end);
                const actualEnd = lineEnd === -1 ? code.value.length : lineEnd;
                const block = code.value.slice(lineStart, actualEnd).replace(/^ {1,4}/gm, '');
                code.value = code.value.slice(0, lineStart) + block + code.value.slice(actualEnd);
                code.selectionStart = lineStart;
                code.selectionEnd = lineStart + block.length;
                captureFrame('outdent', { selected: selected.length });
            } else if (selected.includes('\n')) {
                const lineStart = code.value.lastIndexOf('\n', start - 1) + 1;
                const lineEnd = code.value.indexOf('\n', end);
                const actualEnd = lineEnd === -1 ? code.value.length : lineEnd;
                const block = code.value.slice(lineStart, actualEnd).replace(/^/gm, '    ');
                code.value = code.value.slice(0, lineStart) + block + code.value.slice(actualEnd);
                code.selectionStart = lineStart;
                code.selectionEnd = lineStart + block.length;
                captureFrame('indent', { selected: selected.length });
            } else {
                insertText('    ', 4, 'indent', { selected: 0 });
            }
            updateEditorChrome();
            saveLocal();
            return;
        }
        if (event.key === 'Enter') {
            event.preventDefault();
            const line = currentLineBeforeCursor();
            let indent = lineIndent(line);
            if (line.trim().endsWith(':')) indent += '    ';
            insertText('\n' + indent, 1 + indent.length, 'newline', { indent });
            return;
        }
        if (event.key === 'Escape') {
            pairHl1.style.display = 'none';
            pairHl2.style.display = 'none';
        }
        if (pairs[event.key] && !event.ctrlKey && !event.metaKey && !event.altKey) {
            const start = code.selectionStart;
            const end = code.selectionEnd;
            const selected = code.value.slice(start, end);
            if ((event.key === '"' || event.key === "'") && selected === '' && code.value[start] === event.key) {
                event.preventDefault();
                code.selectionStart = code.selectionEnd = start + 1;
                return;
            }
            event.preventDefault();
            insertText(event.key + selected + pairs[event.key], 1 + selected.length, 'pair', { key: event.key, selected });
            return;
        }
        if (closingPairs.has(event.key) && code.value[code.selectionStart] === event.key) {
            event.preventDefault();
            code.selectionStart = code.selectionEnd = code.selectionStart + 1;
            captureFrame('skip-close', { key: event.key });
            updateEditorChrome();
        }
        if (event.key === 'Backspace') {
            const start = code.selectionStart;
            const end = code.selectionEnd;
            if (start === end && start > 0 && pairs[code.value[start - 1]] === code.value[start]) {
                event.preventDefault();
                code.value = code.value.slice(0, start - 1) + code.value.slice(start + 1);
                code.selectionStart = code.selectionEnd = start - 1;
                updateEditorChrome();
                saveLocal();
                captureFrame('backspace-pair', {});
            }
        }
    });

    code.addEventListener('input', () => {
        const previous = inputSnapshot;
        saveLocal();
        updateEditorChrome();
        setStatus('Есть несохраненные изменения', 'run');
        scheduleAutosave();
        emitWorkspacePatch(previous, code.value);
        emitWorkspaceDraft(false);
        emitWorkspaceCursor(false);
        if (!isApplyingPlayback) {
            captureFrame(pendingInputMeta?.type || 'input', {
                data: pendingInputMeta?.data || '',
                length: code.value.length,
            });
        }
        pendingInputMeta = null;
    });
    code.addEventListener('keyup', () => {
        updateEditorChrome();
        emitWorkspaceCursor(false);
    });
    code.addEventListener('mouseup', () => {
        updateEditorChrome();
        emitWorkspaceCursor(false);
    });
    code.addEventListener('focus', () => emitWorkspaceCursor(false));
    code.addEventListener('blur', () => emitWorkspaceCursor(true));
    code.addEventListener('beforeinput', (event) => {
        inputSnapshot = code.value;
        pendingInputMeta = {
            type: event.inputType || 'input',
            data: event.data || '',
        };
    });
    code.addEventListener('scroll', () => {
        highlight.scrollTop = code.scrollTop;
        highlight.scrollLeft = code.scrollLeft;
        gutter.scrollTop = code.scrollTop;
        renderLineAndPairFocus();
        renderRemoteCursors();
    });
    answer.addEventListener('input', () => {
        saveLocal();
        emitWorkspaceDraft(false);
    });
    notes.addEventListener('input', saveLocal);

    document.querySelectorAll('.tw-tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tw-tab').forEach((item) => item.classList.remove('is-active'));
            document.querySelectorAll('.tw-tab-pane').forEach((item) => item.classList.remove('is-active'));
            tab.classList.add('is-active');
            document.querySelector('[data-pane="' + tab.dataset.tab + '"]')?.classList.add('is-active');
        });
    });

    document.querySelectorAll('[data-action]').forEach((button) => {
        button.addEventListener('click', () => {
            if (button.dataset.action === 'format') {
                const start = code.selectionStart;
                const end = code.selectionEnd;
                if (start !== end) {
                    const before = code.value.slice(0, start);
                    const selected = code.value.slice(start, end);
                    const after = code.value.slice(end);
                    const fixed = repairPythonIndent(selected);
                    code.value = before + fixed + after;
                    code.selectionStart = start;
                    code.selectionEnd = start + fixed.length;
                } else {
                    code.value = formatCodeSmart(code.value);
                }
                saveLocal();
                updateEditorChrome();
                setStatus('Отступы приведены к 4 пробелам', 'ok');
                captureFrame('format', { scope: start !== end ? 'selection' : 'document' });
            }
        });
    });

    if (suggestionToggle) {
        suggestionToggle.addEventListener('click', toggleSuggestions);
    }
    if (importsToggle) {
        importsToggle.addEventListener('click', (event) => {
            event.stopPropagation();
            toggleImportsMenu();
        });
    }
    if (importsMenu) {
        importsMenu.querySelectorAll('[data-import-snippet]').forEach((btn) => {
            btn.addEventListener('click', () => {
                insertImportSnippet(btn.dataset.importSnippet || '');
                toggleImportsMenu(false);
            });
        });
    }
    document.addEventListener('click', (event) => {
        if (!importsMenu) return;
        if (importsMenu.contains(event.target) || importsToggle?.contains(event.target)) return;
        toggleImportsMenu(false);
    });

    if (playbackStartBtn) {
        playbackStartBtn.addEventListener('click', () => { playback.index = 0; stopPlayback(); setEditorFromFrame(playback.frames[0]); });
    }
    if (playbackStepBackBtn) {
        playbackStepBackBtn.addEventListener('click', () => { stopPlayback(); stepPlayback(-1); });
    }
    if (playbackStepForwardBtn) {
        playbackStepForwardBtn.addEventListener('click', () => { stopPlayback(); stepPlayback(1); });
    }
    if (playbackEndBtn) {
        playbackEndBtn.addEventListener('click', () => {
            stopPlayback();
            if (playback.frames.length) {
                playback.index = playback.frames.length - 1;
                setEditorFromFrame(playback.frames[playback.index]);
            }
        });
    }
    if (playbackPlayBtn) {
        playbackPlayBtn.addEventListener('click', playPlayback);
    }
    if (playbackSpeedSelect) {
        playbackSpeedSelect.addEventListener('change', () => {
            playback.speed = Number(playbackSpeedSelect.value || 1);
            if (playback.playing) {
                stopPlayback();
                playPlayback();
            }
        });
    }
    if (playbackRange) {
        playbackRange.addEventListener('input', () => {
            stopPlayback();
            const idx = Number(playbackRange.value || 0);
            playback.index = idx;
            setEditorFromFrame(playback.frames[idx]);
        });
    }

    document.addEventListener('selectionchange', () => {
        if (document.activeElement === code) {
            emitWorkspaceCursor(false);
        }
    });

    // Свободная раскладка панелей (Floating Window Manager)
    const gridEl = document.getElementById('tw-workspace-grid');
    const taskPanel = document.getElementById('tw-task-panel');
    const editorPanel = document.getElementById('tw-editor-panel');
    const outputPanel = document.getElementById('tw-output-panel');

    const toggleTaskBtn = document.getElementById('tw-toggle-panel-task');
    const toggleOutputBtn = document.getElementById('tw-toggle-panel-output');
    const changeLayoutBtn = document.getElementById('tw-change-layout');

    let windowStates = {
        task: { left: 16, top: 16, width: 340, height: 718, visible: true },
        editor: { left: 372, top: 16, width: 780, height: 718, visible: true },
        output: { left: 1168, top: 16, width: 380, height: 718, visible: true }
    };

    const WINDOWS_STORAGE_KEY = 'kege_workspace_window_positions_v2';

    function resetWindowsToDefault() {
        if (!gridEl) return;
        const rect = gridEl.getBoundingClientRect();
        const w = rect.width || window.innerWidth - 80;
        const h = 750;
        
        const pad = 16;
        const availW = w - pad * 4;
        
        const taskW = Math.max(280, Math.floor(availW * 0.25));
        const outputW = Math.max(300, Math.floor(availW * 0.28));
        const editorW = Math.max(450, w - taskW - outputW - pad * 4);
        
        windowStates.task = { left: pad, top: pad, width: taskW, height: h - pad * 2, visible: true };
        windowStates.editor = { left: pad * 2 + taskW, top: pad, width: editorW, height: h - pad * 2, visible: true };
        windowStates.output = { left: pad * 3 + taskW + editorW, top: pad, width: outputW, height: h - pad * 2, visible: true };
        
        applyWindowStates();
        saveWindowStates();
    }

    function saveWindowStates() {
        try {
            localStorage.setItem(WINDOWS_STORAGE_KEY, JSON.stringify(windowStates));
        } catch(e) {}
    }

    function loadWindowStates() {
        try {
            const raw = localStorage.getItem(WINDOWS_STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && typeof parsed === 'object' && parsed.task && parsed.editor && parsed.output) {
                    windowStates = parsed;
                    return true;
                }
            }
        } catch(e) {}
        return false;
    }

    function clampWindowStatesToContainer() {
        if (!gridEl) return;
        const rect = gridEl.getBoundingClientRect();
        const w = rect.width || window.innerWidth - 80;
        const h = 750;
        
        ['task', 'editor', 'output'].forEach(name => {
            const state = windowStates[name];
            if (state) {
                const minW = name === 'editor' ? 400 : 250;
                const minH = 200;
                state.width = Math.max(minW, Math.min(w - 32, state.width));
                state.height = Math.max(minH, Math.min(h - 32, state.height));
                state.left = Math.max(0, Math.min(w - state.width, state.left));
                state.top = Math.max(0, Math.min(h - state.height, state.top));
            }
        });
    }

    function applyWindowStates() {
        clampWindowStatesToContainer();
        ['task', 'editor', 'output'].forEach(name => {
            const panel = document.getElementById(`tw-${name}-panel`);
            const state = windowStates[name];
            if (panel && state) {
                panel.style.left = state.left + 'px';
                panel.style.top = state.top + 'px';
                panel.style.width = state.width + 'px';
                panel.style.height = state.height + 'px';
                panel.style.display = state.visible ? 'flex' : 'none';
            }
        });

        // Обновляем визуальное состояние кнопок
        if (toggleTaskBtn && windowStates.task) {
            toggleTaskBtn.classList.toggle('tw-btn-primary', windowStates.task.visible);
            toggleTaskBtn.classList.toggle('tw-btn-ghost', !windowStates.task.visible);
        }
        if (toggleOutputBtn && windowStates.output) {
            toggleOutputBtn.classList.toggle('tw-btn-primary', windowStates.output.visible);
            toggleOutputBtn.classList.toggle('tw-btn-ghost', !windowStates.output.visible);
        }

        // Оповещаем BooCanvasOverlay о ресайзе
        setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
        }, 50);
    }

    function makeWindowInteractive(panel, name) {
        if (!panel) return;
        const head = panel.querySelector('.tw-panel-head');
        
        // Создаем ручки изменения размеров по правому краю (r), нижнему краю (b) и углу (se)
        const resizers = [
            { type: 'r', class: 'tw-panel-resizer-r', title: 'Растянуть по горизонтали' },
            { type: 'b', class: 'tw-panel-resizer-b', title: 'Растянуть по вертикали' },
            { type: 'se', class: 'tw-panel-resizer-se', title: 'Изменить размер' }
        ];

        resizers.forEach(r => {
            const handle = document.createElement('div');
            handle.className = `tw-panel-resizer ${r.class}`;
            handle.title = r.title;
            panel.appendChild(handle);

            handle.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                e.stopPropagation();

                panel.classList.add('is-active-window');

                const startX = e.clientX;
                const startY = e.clientY;
                const state = windowStates[name];
                const startW = state.width;
                const startH = state.height;

                const containerRect = gridEl.getBoundingClientRect();

                function onPointerMove(ev) {
                    const dx = ev.clientX - startX;
                    const dy = ev.clientY - startY;

                    const minW = name === 'editor' ? 400 : 250;
                    const minH = 200;
                    
                    const maxW = Math.max(minW, containerRect.width - state.left);
                    const maxH = Math.max(minH, containerRect.height - state.top);

                    let newW = state.width;
                    let newH = state.height;

                    if (r.type === 'r' || r.type === 'se') {
                        newW = Math.max(minW, Math.min(maxW, startW + dx));
                    }
                    if (r.type === 'b' || r.type === 'se') {
                        newH = Math.max(minH, Math.min(maxH, startH + dy));
                    }

                    state.width = newW;
                    state.height = newH;

                    panel.style.width = newW + 'px';
                    panel.style.height = newH + 'px';

                    window.dispatchEvent(new Event('resize'));
                }

                function onPointerUp() {
                    document.removeEventListener('pointermove', onPointerMove);
                    document.removeEventListener('pointerup', onPointerUp);
                    saveWindowStates();
                }

                document.addEventListener('pointermove', onPointerMove);
                document.addEventListener('pointerup', onPointerUp);
            });
        });

        // Подъем z-index активного окна
        panel.addEventListener('pointerdown', () => {
            document.querySelectorAll('.tw-panel').forEach(p => p.classList.remove('is-active-window'));
            panel.classList.add('is-active-window');
        });

        // Перетаскивание за шапку
        if (head) {
            head.addEventListener('pointerdown', (e) => {
                if (e.target.closest('.tw-editor-tools, button, a, select, input, details, summary')) return;
                e.preventDefault();

                panel.classList.add('is-active-window');

                const startX = e.clientX;
                const startY = e.clientY;
                const state = windowStates[name];
                const startLeft = state.left;
                const startTop = state.top;

                const containerRect = gridEl.getBoundingClientRect();
                
                function onPointerMove(ev) {
                    const dx = ev.clientX - startX;
                    const dy = ev.clientY - startY;

                    const maxLeft = Math.max(0, containerRect.width - state.width);
                    const maxTop = Math.max(0, containerRect.height - state.height);

                    const newLeft = Math.max(0, Math.min(maxLeft, startLeft + dx));
                    const newTop = Math.max(0, Math.min(maxTop, startTop + dy));

                    state.left = newLeft;
                    state.top = newTop;

                    panel.style.left = newLeft + 'px';
                    panel.style.top = newTop + 'px';
                }

                function onPointerUp() {
                    document.removeEventListener('pointermove', onPointerMove);
                    document.removeEventListener('pointerup', onPointerUp);
                    saveWindowStates();
                }

                document.addEventListener('pointermove', onPointerMove);
                document.addEventListener('pointerup', onPointerUp);
            });
        }
    }

    // Обработчики кнопок скрытия панелей
    if (toggleTaskBtn) {
        toggleTaskBtn.addEventListener('click', () => {
            if (windowStates.task) {
                windowStates.task.visible = !windowStates.task.visible;
                applyWindowStates();
                saveWindowStates();
            }
        });
    }

    if (toggleOutputBtn) {
        toggleOutputBtn.addEventListener('click', () => {
            if (windowStates.output) {
                windowStates.output.visible = !windowStates.output.visible;
                applyWindowStates();
                saveWindowStates();
            }
        });
    }

    if (changeLayoutBtn) {
        changeLayoutBtn.addEventListener('click', resetWindowsToDefault);
    }

    // Общий таймер выполнения сдачи
    const timerContainer = document.getElementById('tw-timer-container');
    const timerClock = document.getElementById('tw-timer-clock');
    let isTimerExpired = false;

    if (timerContainer && timerClock) {
        const initialSecondsLeft = parseInt(timerContainer.dataset.secondsLeft, 10) || 0;
        const startTime = Date.now();
        
        function formatDuration(totalSecs) {
            const hours = Math.floor(totalSecs / 3600);
            const minutes = Math.floor((totalSecs % 3600) / 60);
            const seconds = totalSecs % 60;
            return [hours, minutes, seconds].map(v => String(v).padStart(2, '0')).join(':');
        }
        
        function updateTimer() {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const secondsLeft = Math.max(0, initialSecondsLeft - elapsed);

            if (secondsLeft <= 0) {
                timerClock.textContent = '00:00:00';
                timerClock.style.color = '#ef4444';
                timerClock.classList.remove('tw-timer-blink');
                isTimerExpired = true;
                
                // Блокируем редактор
                code.readOnly = true;
                answer.disabled = true;
                runBtn.disabled = true;
                saveBtn.disabled = true;
                setStatus('Время вышло! Редактор заблокирован.', 'error');
                return;
            }
            timerClock.textContent = formatDuration(secondsLeft);
            if (secondsLeft < 300) { // Меньше 5 минут
                timerClock.style.color = '#ef4444';
                timerClock.classList.add('tw-timer-blink');
            } else if (secondsLeft < 900) { // Меньше 15 минут
                timerClock.style.color = '#f59e0b';
            }
        }
        
        updateTimer();
        setInterval(updateTimer, 1000);
    }

    // Накопление времени выполнения текущего задания в localStorage сдачи
    if (ws.context_type === 'submission_task' && ws.context_id && ws.assignment_task_id) {
        window.lastWorkspaceTimerTick = Date.now();
        const activeTimerTaskId = ws.assignment_task_id;
        
        function updateWorkspaceTaskTimer() {
            if (isTimerExpired) return;
            if (document.visibilityState !== 'visible') return; // Не накапливаем в фоновом режиме, чтобы не перезаписывать
            const key = 'kege_submission_task_timers_' + ws.context_id;
            try {
                const raw = localStorage.getItem(key);
                let data = raw ? JSON.parse(raw) : null;
                if (!data || typeof data !== 'object') {
                    data = { activeTaskId: activeTimerTaskId, savedAt: Date.now(), timers: {} };
                }
                data.activeTaskId = activeTimerTaskId;
                data.savedAt = Date.now();
                if (!data.timers) data.timers = {};
                if (!data.timers[activeTimerTaskId]) {
                    data.timers[activeTimerTaskId] = { elapsedMs: 0, runningSinceMs: null };
                }
                
                const now = Date.now();
                if (window.lastWorkspaceTimerTick) {
                    const delta = now - window.lastWorkspaceTimerTick;
                    data.timers[activeTimerTaskId].elapsedMs = (data.timers[activeTimerTaskId].elapsedMs || 0) + delta;
                }
                window.lastWorkspaceTimerTick = now;
                localStorage.setItem(key, JSON.stringify(data));
            } catch (e) {}
        }
        
        setInterval(updateWorkspaceTaskTimer, 1000);
        window.addEventListener('beforeunload', updateWorkspaceTaskTimer);
        
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                window.lastWorkspaceTimerTick = Date.now();
            } else {
                updateWorkspaceTaskTimer();
                window.lastWorkspaceTimerTick = null;
            }
        });
        window.addEventListener('focus', () => {
            window.lastWorkspaceTimerTick = Date.now();
        });
        window.addEventListener('blur', () => {
            updateWorkspaceTaskTimer();
            window.lastWorkspaceTimerTick = null;
        });
    }

    runBtn.addEventListener('click', runCode);
    saveBtn.addEventListener('click', saveServer);
    
    // Инициализация оконного менеджера
    restoreLocal();
    joinWorkspaceSocket();
    if (!loadWindowStates()) {
        resetWindowsToDefault();
    } else {
        applyWindowStates();
    }

    makeWindowInteractive(taskPanel, 'task');
    makeWindowInteractive(editorPanel, 'editor');
    makeWindowInteractive(outputPanel, 'output');

    if (!playback.frames.length) {
        playback.frames.push(sanitizeFrame({ ts: Date.now(), action: 'init', code: code.value, caret: [0, 0], detail: {} }));
    }
    renderPlayback();
    renderVersions();
    updateEditorChrome();
    scheduleAutosave();
    pullServerState(true);
    liveSyncTimer = setInterval(() => pullServerState(false), 5000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) pullServerState(true);
    });

    // Инициализация холста рисования
    if (window.BooCanvasOverlay && ws.task_id) {
        window.BooCanvasOverlay.setContext(ws.task_id, ws.context_type, ws.context_id);
    }
})();
