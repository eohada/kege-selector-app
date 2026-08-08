# d:\VSCode\kege_selector_app\templates\qa\_floating_widget.html

**Описание:** Глобальный QA-виджет: баг-репорт, пресеты, быстрые ссылки, имперсонация.

`
{% set _qa_is_elevated = (current_user.is_creator() or current_user.is_chief_tester() or current_user.is_admin() or current_user.is_chief_admin()) if current_user.is_authenticated else false %}
{% set _qa_is_pool = (current_user.is_qa_pool if current_user.is_qa_pool is defined else false) %}

<div class="fixed bottom-6 right-6 z-[10001]">
    <button id="qaFab" type="button" onclick="toggleQAWidget()" class="w-14 h-14 rounded-2xl bg-indigo-600 text-white shadow-lg border-b-[3px] border-b-indigo-900 active:translate-y-[2px] active:border-b-0 flex items-center justify-center hover:bg-indigo-700 transition-colors">
        <i class="ph-bold ph-shield-check text-2xl"></i>
    </button>
</div>

<div id="qaWidget" class="fixed bottom-24 right-6 z-[10000] hidden w-[360px] max-w-[92vw] max-h-[78vh]">
    <div class="bg-white rounded-2xl border border-slate-200 border-b-[4px] border-b-slate-300 shadow-2xl overflow-hidden flex flex-col">
        <div class="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div class="flex items-center gap-2">
                <div class="w-8 h-8 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center">
                    <i class="ph-fill ph-radar text-lg"></i>
                </div>
                <div class="leading-tight">
                    <div class="text-xs font-extrabold uppercase tracking-widest text-slate-500">QA</div>
                    <div class="text-sm font-black text-slate-900">Инструменты тестирования</div>
                </div>
            </div>
            <button type="button" class="text-slate-500 hover:text-slate-900" onclick="toggleQAWidget()">
                <i class="ph-bold ph-x text-xl"></i>
            </button>
        </div>

        <div class="p-4 border-b border-slate-100">
            <div class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Сессия</div>
            <div class="mt-1 flex items-center justify-between gap-2">
                <div class="min-w-0">
                    <div class="text-sm font-black text-slate-900 truncate">{{ current_user.username }}</div>
                    <div class="text-xs font-mono text-slate-400">#{{ current_user.id }}</div>
                </div>
                {% if session.get('impersonator_id') %}
                <form action="{{ url_for('qa.revert_impersonation') }}" method="POST" data-no-ajax class="shrink-0">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <button type="submit" class="px-3 py-2 rounded-xl bg-red-100 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-200">Выйти</button>
                </form>
                {% endif %}
            </div>
        </div>

        <div class="p-3 overflow-auto">
            <div class="space-y-2">
                <button type="button" onclick="openQABugModal()" class="w-full px-4 py-3 rounded-xl bg-indigo-600 text-white font-bold text-sm hover:bg-indigo-700 flex items-center justify-center gap-2">
                    <i class="ph-bold ph-bug"></i> Создать баг-репорт
                </button>

                <details class="rounded-xl border border-slate-200 bg-white">
                    <summary class="cursor-pointer select-none px-4 py-3 flex items-center justify-between">
                        <span class="text-xs font-extrabold uppercase tracking-widest text-slate-500">Быстрые ссылки</span>
                        <i class="ph-bold ph-caret-down text-slate-400"></i>
                    </summary>
                    <div class="px-4 pb-4 space-y-2">
                        {% if current_user.is_creator() or current_user.is_chief_tester() %}
                        <a class="block w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-sm font-bold text-slate-800 no-underline" href="{{ url_for('chief_tester.dashboard', tab='dashboard') }}">Кабинет главного тестировщика</a>
                        {% endif %}
                        <a class="block w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-sm font-bold text-slate-800 no-underline" href="{{ url_for('qa.board') }}">QA доска</a>
                        <a class="block w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-sm font-bold text-slate-800 no-underline" href="{{ url_for('qa.bug_reports') }}">Список багов</a>
                        <a class="block w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-sm font-bold text-slate-800 no-underline" href="{{ url_for('qa.pool') }}">Пул профилей</a>
                    </div>
                </details>

                {% if _qa_is_elevated %}
                <details class="rounded-xl border border-slate-200 bg-white">
                    <summary class="cursor-pointer select-none px-4 py-3 flex items-center justify-between">
                        <span class="text-xs font-extrabold uppercase tracking-widest text-slate-500">Имперсонация</span>
                        <i class="ph-bold ph-caret-down text-slate-400"></i>
                    </summary>
                    <div class="px-4 pb-4 space-y-2">
                        <form class="flex items-center gap-2" onsubmit="qaImpersonationSearch(event)">
                            <input id="qaImpersonateQ" type="text" class="flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="username / id" autocomplete="off">
                            <button type="submit" class="px-3 py-2 rounded-xl bg-slate-900 text-white text-sm font-bold">Поиск</button>
                        </form>
                        <div id="qaImpersonateResults" class="hidden rounded-xl border border-slate-200 bg-white shadow-sm p-2"></div>
                        <div class="grid grid-cols-2 gap-2 pt-1">
                            {% for un in ['qa_pool_student_1','qa_pool_student_2','qa_pool_student_3','qa_pool_tutor_1','qa_pool_tutor_2','qa_pool_tutor_3'] %}
                            <form action="{{ url_for('qa.impersonate_as_role') }}" method="POST" data-no-ajax>
                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                <input type="hidden" name="username" value="{{ un }}">
                                <button type="submit" class="w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 text-xs font-bold text-slate-800 text-left">{{ un }}</button>
                            </form>
                            {% endfor %}
                        </div>
                    </div>
                </details>
                {% endif %}

                {% if not _qa_is_pool %}
                <details class="rounded-xl border border-slate-200 bg-white" open>
                    <summary class="cursor-pointer select-none px-4 py-3 flex items-center justify-between">
                        <span class="text-xs font-extrabold uppercase tracking-widest text-slate-500">Пресеты 1–7</span>
                        <i class="ph-bold ph-caret-down text-slate-400"></i>
                    </summary>
                    <div class="px-4 pb-4 space-y-3">
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest">Group 1</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/perfectionist_student')">Perfectionist student</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/clean_slate_account')">Clean slate account</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 2</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/broken_work_10mb')">Broken work (10MB)</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/deadline_timer_5min')">Deadline timer (5min)</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 3</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/schedule_marathon_10x15')">Schedule marathon (10×15)</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/lesson_in_2030')">Lesson in 2030</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 4</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/subscription_end_yesterday')">Subscription end вчера</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/invite_generator_10')">Invite generator ×10</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 5</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/create_cluster_group')">Create cluster group</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/mass_homework_to_group')">Mass homework to group</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 6</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/stress_trainer_infinite_loop')">Stress trainer: infinite loop</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/reset_streak')">Reset streak</button>
                        </div>
                        <div class="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest pt-2">Group 7</div>
                        <div class="space-y-2">
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/system_cache_clear')">System cache clear</button>
                            <button type="button" class="qa-preset-btn" onclick="qaRunPreset('/qa/manipulate/maintenance_enable')">Maintenance enable</button>
                            <button type="button" class="qa-preset-btn !border-red-200 !bg-red-50 hover:!bg-red-100 !text-red-700" onclick="qaRunPreset('/qa/manipulate/nuke_test_data')">Nuke test data</button>
                        </div>
                    </div>
                </details>
                {% endif %}
            </div>
        </div>
    </div>
</div>

<div id="qaBugModal" class="fixed inset-0 z-[10002] hidden items-center justify-center bg-slate-900/50 px-4">
    <div class="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-xl font-black text-slate-900">Новый баг-репорт</h3>
            <button type="button" class="text-slate-500 hover:text-slate-900" onclick="closeQABugModal()"><i class="ph-bold ph-x text-xl"></i></button>
        </div>
        <form id="qaBugForm" class="space-y-3">
            <input type="hidden" name="context_url" id="qaBugContextUrl">
            <input type="hidden" name="screenshot" id="qaBugScreenshotData">
            <input type="hidden" name="logs_snapshot" id="qaBugLogsSnapshot">
            <input type="hidden" name="request_id" id="qaBugRequestId">

            <input type="text" name="title" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-900" placeholder="Краткая суть бага" required>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <select name="severity" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900">
                    <option value="medium">Severity: medium</option>
                    <option value="low">Severity: low</option>
                    <option value="high">Severity: high</option>
                    <option value="critical">Severity: critical</option>
                </select>
                <input type="text" name="environment" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Окружение (prod/sandbox/local + браузер)">
            </div>
            <textarea name="steps" rows="4" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Шаги воспроизведения (1..N)"></textarea>
            <textarea name="expected" rows="2" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Ожидаемое поведение"></textarea>
            <textarea name="actual" rows="2" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Фактическое поведение"></textarea>
            <textarea name="description" rows="2" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Доп. комментарии (необязательно)"></textarea>

            <div class="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3">
                <div class="text-xs font-bold text-slate-500 mb-2">Скриншот (авто):</div>
                <img id="qaBugScreenshotImg" class="max-h-48 rounded-lg border border-slate-200 hidden" alt="preview">
                <div id="qaBugScreenshotPlaceholder" class="text-xs text-slate-400">Готовим скриншот...</div>
            </div>

            <div class="flex gap-2 pt-2">
                <button type="submit" class="px-4 py-2 bg-indigo-600 text-white rounded-xl font-bold text-sm hover:bg-indigo-700">Отправить</button>
                <button type="button" class="px-4 py-2 bg-slate-100 text-slate-700 rounded-xl font-bold text-sm" onclick="closeQABugModal()">Отмена</button>
            </div>
        </form>
    </div>
</div>

<script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
<script>
function toggleQAWidget() {
    const w = document.getElementById('qaWidget');
    if (!w) return;
    w.classList.toggle('hidden');
}

function getCsrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

function toastOk(msg) {
    if (window.toast?.success) window.toast.success(msg);
    else alert(msg);
}
function toastErr(msg) {
    if (window.toast?.error) window.toast.error(msg);
    else alert(msg);
}

async function qaRunPreset(endpoint) {
    try {
        const res = await fetch(endpoint, { method: 'POST', headers: { 'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            toastErr(data?.error || data?.message || `Forbidden/Ошибка (${res.status})`);
            return;
        }
        if (data.status !== 'success') {
            toastErr(data?.error || data?.message || 'Ошибка выполнения пресета');
            return;
        }
        const msg = data.message || 'Готово';
        if (data.next && data.next.url) {
            if (window.showConfirmModal) {
                showConfirmModal({
                    title: 'Пресет выполнен',
                    message: `${msg}\n\nДальше: ${data.next.label || 'Открыть экран проверки'}`,
                    confirmText: 'Открыть',
                    cancelText: 'Остаться',
                    confirmClass: 'accent',
                    onConfirm: () => { window.location.href = data.next.url; }
                });
            } else {
                if (confirm(`${msg}\n\nОткрыть: ${data.next.label || 'экран проверки'}?`)) window.location.href = data.next.url;
            }
        } else {
            toastOk(msg);
            setTimeout(() => location.reload(), 600);
        }
    } catch (e) {
        toastErr('Ошибка сети');
    }
}

async function openQABugModal() {
    try { document.getElementById('qaBugRequestId').value = window.__last_request_id || localStorage.getItem('last_request_id') || ''; } catch (e) {}
    const modal = document.getElementById('qaBugModal');
    const placeholder = document.getElementById('qaBugScreenshotPlaceholder');
    const img = document.getElementById('qaBugScreenshotImg');
    if (!modal || !placeholder || !img) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('qaBugContextUrl').value = window.location.href;
    placeholder.textContent = 'Готовим скриншот...';
    img.classList.add('hidden');
    document.getElementById('qaBugLogsSnapshot').value = '';

    {% if current_user.is_creator() or current_user.is_chief_tester() %}
    try {
        fetch('/chief-tester/logs/feed?lines=80', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(r => r.json())
            .then(data => {
                const entries = Array.isArray(data.entries) ? data.entries : [];
                const text = entries.slice(-30).map(e => `[${e.ts}] RID=${e.request_id || '-'} | ${e.actor} | ${e.action} | ${e.page} | ${e.result}`).join('\n');
                document.getElementById('qaBugLogsSnapshot').value = text;
            })
            .catch(() => {});
    } catch (e) {}
    {% endif %}

    setTimeout(async () => {
        try {
            const canvas = await html2canvas(document.body, {
                scrollX: -window.scrollX,
                scrollY: -window.scrollY,
                windowWidth: document.documentElement.clientWidth,
                windowHeight: document.documentElement.clientHeight,
                useCORS: true,
                allowTaint: true
            });
            let dataUrl = '';
            try { dataUrl = canvas.toDataURL('image/jpeg', 0.75); } catch (e) { dataUrl = ''; }
            document.getElementById('qaBugScreenshotData').value = dataUrl;
            if (dataUrl) {
                img.src = dataUrl;
                img.classList.remove('hidden');
                placeholder.textContent = '';
            } else {
                placeholder.textContent = 'Скриншот недоступен.';
            }
        } catch (e) {
            placeholder.textContent = 'Скриншот недоступен.';
        }
    }, 200);
}

function closeQABugModal() {
    const modal = document.getElementById('qaBugModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

document.getElementById('qaBugForm')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    const form = e.currentTarget;
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Отправка...';

    const data = new FormData(form);
    const sev = (data.get('severity') || '').toString();
    const env = (data.get('environment') || '').toString();
    const steps = (data.get('steps') || '').toString();
    const expected = (data.get('expected') || '').toString();
    const actual = (data.get('actual') || '').toString();
    const notes = (data.get('description') || '').toString();
    const logs = (data.get('logs_snapshot') || '').toString();
    const rid = (data.get('request_id') || '').toString().trim();

    let body = '';
    if (rid) body += `RID: ${rid}\n`;
    if (sev) body += `Severity: ${sev}\n`;
    if (env) body += `Environment: ${env}\n`;
    if (steps) body += `\nSteps:\n${steps}\n`;
    if (expected) body += `\nExpected:\n${expected}\n`;
    if (actual) body += `\nActual:\n${actual}\n`;
    if (notes) body += `\nNotes:\n${notes}\n`;
    if (logs) body += `\n--- LOG SNAPSHOT ---\n${logs}\n`;
    data.set('description', body.trim());

    try {
        const res = await fetch('/qa/bug-report', { method: 'POST', body: data, headers: { 'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest' } });
        const json = await res.json().catch(() => ({}));
        if (res.ok && json.success) {
            toastOk('Баг-репорт отправлен');
            closeQABugModal();
            form.reset();
        } else {
            toastErr(json.error || 'Ошибка отправки');
        }
    } catch (e) {
        toastErr('Ошибка сети');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
});

async function qaImpersonationSearch(ev) {
    if (ev) ev.preventDefault();
    const q = document.getElementById('qaImpersonateQ')?.value?.trim() || '';
    const box = document.getElementById('qaImpersonateResults');
    if (!box) return;
    if (!q) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    try {
        const res = await fetch(`{{ url_for("chief_tester.users_search") }}?q=${encodeURIComponent(q)}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await res.json().catch(() => ({}));
        const items = Array.isArray(data.items) ? data.items : [];
        if (!items.length) {
            box.innerHTML = '<div class="px-3 py-2 text-xs text-slate-500">Ничего не найдено</div>';
            box.classList.remove('hidden');
            return;
        }
        box.innerHTML = items.map(i => `
            <form method="POST" action="/qa/impersonate/${i.id}" class="flex items-center justify-between gap-2 rounded-lg hover:bg-slate-50 px-2 py-2" data-no-ajax>
                <input type="hidden" name="csrf_token" value="${getCsrf()}">
                <div class="min-w-0">
                    <div class="text-xs font-bold text-slate-900 truncate">${i.username} <span class="text-slate-400">#${i.id}</span></div>
                    <div class="text-[11px] text-slate-500 truncate">${i.role}${i.student_name ? ` • ${i.student_name}` : ''}</div>
                </div>
                <button class="shrink-0 px-2 py-1 rounded-md border border-slate-200 text-[11px] font-bold text-slate-700" type="submit">Войти как</button>
            </form>
        `).join('');
        box.classList.remove('hidden');
    } catch (e) {
        box.innerHTML = '<div class="px-3 py-2 text-xs text-red-500">Ошибка поиска</div>';
        box.classList.remove('hidden');
    }
}
</script>

<style>
/* small helper for widget preset buttons */
.qa-preset-btn{width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgb(226 232 240);background:rgb(248 250 252);font-weight:700;font-size:13px;text-align:left;color:rgb(15 23 42);transition:background .15s}
.qa-preset-btn:hover{background:rgb(241 245 249)}
</style>

`
