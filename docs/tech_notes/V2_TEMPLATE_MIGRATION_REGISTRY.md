# Реестр перевода живых шаблонов на каноничный V2

**Дата старта:** 2026-08-17  
**Правило:** legacy-шаблон не может быть назначен live-маршруту. Старый адрес допускается только как redirect на канонический V2-маршрут.

| Контур | Шаблон / маршрут | Статус | Следующее действие |
|---|---|---|---|
| Комната урока | `templates/sandbox/lesson_room.html`, `/lesson/<id>/room` | V2 | Поддерживать единый Studio-контракт; не заменять на legacy workspace. |
| Аналитика ученика | `templates/sandbox/analytics_canonical.html`, `/student/<id>/analytics` | V2 | Проверять только данные и регрессии. |
| Теория | `templates/sandbox/theory_*`, `/theory/*`, `/library` | V2 | Продолжать функциональную полировку без возврата к старым библиотечным страницам. |
| Группы | `/groups`, `/groups/<id>` | V2 | Старый `/teacher/group/<id>` оставлен только redirect-совместимостью. |
| Работа над ошибками | `templates/student_mistakes.html`, `/student/mistakes` | V2 | Переведено в шаге 12; контракт закреплён тестом. |
| Карточка ученика | `templates/student_info.html`, `/student/<id>/info` | V2 | Визуал и реальные данные переведены; поддерживать регрессию. |
| План обучения | `templates/student_learning_plan.html`, `/student/<id>/plan` | V2-оболочка | Интерактивная карта сохранена, визуал переведён безопасным изолированным слоем; плановая замена compatibility-классов после browser-smoke. |
| Журнал оценок | `templates/student_gradebook.html`, `/student/<id>/gradebook` | V2 | CRUD, экспорт и удаление работают в каноничном интерфейсе. |
| Проверка работы | `templates/submission_grade.html`, `/submissions/<id>/grade` | V2-оболочка | Teacher-actions сохранены и закреплены статической регрессией; полная DOM-декомпозиция возможна только после browser-smoke. |
| Старые статистика и домашние URL | `/student/<id>/statistics`, `/lesson/<id>/homework-tasks` | Совместимый redirect | Не рендерить устаревшие шаблоны; редирект должен вести на V2. |
| Отдельный workspace | `templates/task_workspace.html`, `/task-workspace` | Функциональный V2, UX-долг P2 | Не путать с legacy; улучшать как часть Studio, не разрывая Socket.IO/API. |

## Очередность

1. Повторный маршрутный аудит всех оставшихся live-renderов и добавление запретительных V2-регрессий.
2. Browser-smoke V2-оболочек `student_learning_plan.html` и `submission_grade.html` после восстановления тестового окружения.
3. Удаление недостижимых legacy-render веток, которые прикрыты redirect, чтобы исключить их будущую реактивацию.

## Критерии закрытия миграции

- Шаблон использует холст `max-w-[1400px] mx-auto`, светлые тактильные Bento-карточки и единый масштаб кнопок.
- В нём нет `glass-panel`, `neo-*` и других прежних визуальных оболочек.
- Сохранены Jinja-переменные, формы, CSRF, endpoint-адреса и права ролей.
- Есть статическая V2-регрессия на отсутствие отката или browser smoke-test после восстановления окружения.
