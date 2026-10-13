# BooStudy Demo Experience — Project Handoff

## 1. Статус проекта

- Snapshot date: 2026-10-05.
- Стадия: полный guided demo из 10 глав присутствует в рабочей копии; дальнейшая разработка намеренно заморожена.
- Причина паузы: команда переключается на другие части BooStudy.
- Это не удаление, не отмена и не запрос на упрощение демоверсии.
- Приблизительная готовность: функционально близка к демонстрационному release candidate, но production-ready не подтверждена из-за активных рисков в [DEMO_KNOWN_ISSUES.md](DEMO_KNOWN_ISSUES.md).
- Последний release verdict: **NO-GO / не подтверждено для production**. Full Playwright journey доходит до финального CTA, но в текущем окружении фиксирует 409 responses на `/demo/api/event`; mobile release не считается подтверждённым.

> Demo Experience development is intentionally paused. Existing implementation must be preserved.

Категории доказательств в этих документах:

- **CONFIRMED** — видно в текущем коде или подтверждено запуском/тестом.
- **REPORTED** — заявлено предыдущим аудитом, но в этом snapshot не перепроверено.
- **PLANNED** — описано как намерение, но не подтверждено реализацией.

## 2. Product Vision

BooStudy Demo Experience — не обычный onboarding и не статичный лендинг. Продуктовая идея — **интерактивное кино внутри настоящей образовательной платформы**.

Пользователь знакомится с Бу, выбирает контекст обучения, проходит сюжет из 10 глав, взаимодействует с реальными страницами BooStudy, решает демонстрационную задачу, читает теорию, исправляет ошибку, смотрит маршрут, аналитику, расписание и профиль, после чего приходит к CTA заявки на вводный урок.

Ключевые концепции:

- **Cinema Mode** — крупные сюжетные кадры, Бу, прогресс, карточка реплики и CTA.
- **Companion Mode** — Бу поверх реальной страницы платформы, короткие contextual reactions и подсветка следующего действия.
- **Experience Layer** — demo-only слой поверх shared платформенных страниц.
- Бу — персонаж-проводник, а не чат-бот свободного диалога.
- Demo dataset создаёт связного временного ученика: Student, уроки, работы, теорию, маршрут, статистику и достижения.
- Demo user изолирован через `is_demo_user`, Flask session и серверные проверки.
- Сценарий опирается на semantic events и монотонное состояние, а не на один локальный click counter.

## 3. История развития

По текущим артефактам и существующему сценарию развитие шло так:

1. **MVP**: главы 1–3, первый Boo Companion, первый Demo Engine и trial.
2. **Проблемы MVP**: зацикливание Chapter 2, зависимость от конкретных кликов, слабый mascot, пустой dashboard, навязчивый floating widget, преждевременный тарифный CTA.
3. **Следующая итерация**: semantic events, `STEP_RANKS`, enriched dataset, canonical `/dashboard`, реальные Boo assets, E2E и промежуточное success state.
4. **Experience 2.0**: cinematic Chapter 1, крупный Boo, интерактивные диалоги, имя/класс/цель, Experience Layer и переработанный dashboard.
5. **Последняя стадия**: текущий полный guided demo из 10 глав, включая библиотеку, работу над ошибками, маршрут, аналитику, расписание, профиль и финальный CTA.

Подробная последовательность и расхождения зафиксированы в [DEMO_SCENARIO_CANON.md](DEMO_SCENARIO_CANON.md).

## 4. Что подтверждено в текущей копии

- `app/demo/routes.py` содержит entry point и demo API.
- `app/demo/service.py` создаёт demo user/dataset, хранит состояние и проверяет ответ.
- `static/js/demo/demo_engine.js` содержит состояние, `STEP_RANKS`, переходы, semantic events и exit.
- `static/js/demo/demo_scenario.js` содержит декларативные 10 chapters.
- `static/js/demo/boo_companion.js` реализует Cinema/Companion/Experience behavior.
- `templates/sandbox/demo_welcome.html` — текущий cinematic Chapter 1.
- `templates/sandbox/components/_boo_companion.html` — Experience Layer markup.
- `tests/v2/test_demo_experience_v2.py` покрывает init, state, events, answer branching, retry, isolation и exit.
- `tests/e2e/demo-linear-release.spec.ts` описывает полный happy path до заявки.

## 5. Как запустить

Минимальный локальный запуск в текущем окружении:

```powershell
$env:BOOSTUDY_PYTHON='C:\Users\eohad\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:SECRET_KEY='boostudy-browser-release-secret'
$env:PORT='5001'
& $env:BOOSTUDY_PYTHON -c "from wsgi import app; app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)"
```

Открыть `/demo`. Readiness endpoint: `/ready`.

## 6. Как воспроизвести

Канонический путь и каждое действие описаны в [DEMO_SCENARIO_CANON.md](DEMO_SCENARIO_CANON.md). Для автоматизации использовать `tests/e2e/demo-linear-release.spec.ts`. Для быстрого director-перехода существует development endpoint `/demo/api/director`; он разрешён только demo user и не является пользовательским маршрутом.

## 7. Ограничения handoff

Не выполнять при паузе:

- новый UX или новый функционал;
- cleanup/refactor demo-кода;
- удаление legacy demo assets/tests/migrations;
- изменение production-конфигурации;
- `git reset`, `git clean`, checkout, rebase, stash, commit или push без отдельного запроса.
