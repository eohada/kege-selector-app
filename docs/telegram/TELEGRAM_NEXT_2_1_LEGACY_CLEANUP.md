# BooStudy Telegram Next 2.1 — Legacy Cleanup & Modernization Report

## 1. Обзор проведённой инвентаризации

В ходе ревизии 46 демонстрационных уведомлений Telegram Next был выявлен ряд устаревших артефактов, несоответствующих архитектуре BooStudy 2026 года:
1. **Несуществующий журнал оценок:** Метод `notify_new_gradebook_entry` ссылался на отдельный журнал, отсутствующий в актуальной платформе.
2. **Устаревшая подписочная модель:** Метод `notify_subscription_expiring` отправлял предупреждения об истечении срока подписки, тогда как BooStudy перешла на пакетный баланс занятий.
3. **Упоминания сторонних сервисов:** В шаблонах системных ошибок фигурировал видеосервис Daily.co вместо собственного кластера `LiveKit WebRTC Server`, а также несуществующие платёжные шлюзы вместо внутреннего процессинга.
4. **Разрозненное форматирование:** Ряд уведомлений в `app/telegram/notifications.py` формировался сырыми строками в обход канонического шаблонизатора `notification_templates.py`.

---

## 2. Результаты очистки и актуализации

### 1. Вывод из эксплуатации (Decommissioned / Retired)
- `notify_new_gradebook_entry`: Метод официально переведён в статус `retired` с безопасным логированием и отказом от создания сообщений. Оценки отображаются непосредственно в карточках проверенных домашних заданий (`homework_checked`).
- `notify_subscription_expiring`: Метод переведён в статус `retired`. Вместо него работают события баланса уроков: `lesson_balance_changed`, `low_lessons` и `package_exhausted`.

### 2. Актуализация инфраструктурных сервисов
- **Видеосвязь:** Все системные алерты и ссылки обновлены на собственный WebRTC-сервер BooStudy (`LiveKit WebRTC Server`, `app/services/livekit_service.py`).
- **Баланс и абонементы:** Внедрены канонические карточки изменения остатка занятий с указанием дельты (`+8`, `-1`), остатка уроков и причины операции.
- **Хранилище и очереди:** Оповещения мониторинга приведены в соответствие с реальными сервисами (Outbox Dispatcher, воркеры Celery, хранилище PostgreSQL/SQLite).

### 3. Унификация шаблонов
Все ad-hoc вызовы переведены на единый движок `render_telegram_notification` в `app/telegram/notification_templates.py`:
- `notify_lesson_started_for_lesson` формирует карточку `lesson_started` с кнопкой запроса ссылки.
- `notify_lesson_finished_for_teacher` формирует карточку `lesson_finished` с кнопкой заметки ДЗ.
- `notify_teacher_homework_note_reminder` формирует карточку `teacher_hw_note_reminder`.
- `notify_lesson_balance_changed` формирует карточки `lesson_balance_changed`, `low_lessons` и `package_exhausted`.
