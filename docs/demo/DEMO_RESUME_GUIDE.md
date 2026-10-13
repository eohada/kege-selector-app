# BooStudy Demo Experience — Resume Guide

Если ты читаешь это после длительной паузы — не начинай разработку с нуля.

1. Прочитай `DEMO_EXPERIENCE_HANDOFF.md`.
2. Проверь `DEMO_GIT_SNAPSHOT.md` и сохрани dirty worktree.
3. Прочитай `DEMO_SCENARIO_CANON.md`.
4. Прочитай `DEMO_KNOWN_ISSUES.md`.
5. Подними окружение и проверь `/ready`.
6. Запусти backend pytest suite в чистом, совместимом runtime.
7. Запусти `/demo` вручную.
8. Пройди canonical happy path.
9. Проверь migration heads и merge state.
10. Только после этого вноси изменения.

## First tasks when development resumes

Не начинать с нового roadmap. Сначала закрыть реальные незавершённые пункты текущего состояния:

1. Разобрать подтверждённые 409 `/demo/api/event` в desktop/mobile canonical E2E.
2. Подтвердить retry route: CTA ведёт именно на editable retry submission, а не на исходную graded submission.
3. Пройти Chapter 5 вручную на desktop/mobile: dialogue, answer mode, visible input, pulse, submit, corrected state.
4. Получить чистый pytest/Playwright verdict в воспроизводимом окружении.
5. Проверить миграционный graph и единственный head.
6. Уточнить retention/cleanup demo users и конфигурацию access code.

Любое изменение shared workspace, schedule или platform routes требует regression tests для обычного ученика.
