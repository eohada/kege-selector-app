# BooStudy Visual Engineering System

## Source of truth

`Golden Dashboard` → design tokens → UI primitives → pages.

Golden references describe composition, hierarchy and interaction character. They are not pixel-perfect image-tracing instructions. Product data, Jinja variables and existing business flows remain the source of truth for behaviour.

## For humans

Новый visual reference получает статус `APPROVED` только после human review. До approval изображение является направлением, но не screenshot baseline.

## For agents

Для любой frontend/UI-задачи использовать `.codex/skills/boostudy-ui/SKILL.md`. Для отдельной визуальной проверки использовать `.codex/skills/boostudy-visual-qa/SKILL.md`.

Не создавать новый shell, произвольные цвета, radius или shadow, если нужное решение уже есть в tokens/primitives. Existing production logic and Jinja context must be preserved.

## Visual QA

```text
npm run visual:dashboard
npm run visual:ui
npm run visual:all
```

Screenshots are written to `artifacts/visual/` and are intentionally not baselines until a human approves the implemented page. The dashboard test uses `BOOSTUDY_E2E_BASE_URL` and an optional Playwright `storageState` configured in `BOOSTUDY_VISUAL_STORAGE_STATE`.

For a local browser session outside Playwright, expose the showcase explicitly with `BOOSTUDY_UI_DEV=1`.

Для dashboard visual auth запусти локальный server, затем создай state без хранения credentials в коде:

```powershell
$env:BOOSTUDY_VISUAL_USERNAME = 'your-local-user'
$env:BOOSTUDY_VISUAL_PASSWORD = 'your-local-password'
npm run visual:auth
$env:BOOSTUDY_VISUAL_STORAGE_STATE = 'artifacts/visual/storage-state.json'
npm run visual:dashboard
```

В canonical dashboard search пока UI-ready: полноценного global search backend в текущем scope нет, поэтому control не имитирует результаты и не отправляет фиктивный запрос.

## Adding a component

1. Check existing sandbox/shared components.
2. Add or reuse a token-backed primitive.
3. Document rest, hover, active, focus, disabled and loading states.
4. Add the component to `/dev/ui`.
5. Run geometry and responsive checks.

## Changing a token

Change the semantic token and its documentation together. Avoid page-local hard-coded values. If the change affects the Golden Dashboard grammar, update the reference docs and request human review before updating any baseline.

## Adding a page

Use the canonical AppShell, PageContainer and BentoGrid grammar. Follow the workflow in `boostudy-ui`: reference → implementation → screenshots at four viewports → geometry audit → human review.

## Reference gallery

Only the dashboard reference is approved today. Other folders contain explicit placeholders and must not be treated as visual truth.
