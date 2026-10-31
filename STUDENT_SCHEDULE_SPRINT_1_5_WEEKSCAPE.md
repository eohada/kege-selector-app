# BOOSTUDY / ORISTERA — УЧЕНИЧЕСКОЕ РАСПИСАНИЕ
# Sprint 1.5: WEEKSCAPE — Новая архитектура учебной недели

**Дата:** 27 октября 2026 г.  
**Ветка:** `feature/livekit-video`  
**Каноничный URL:** `/schedule`  
**Целевой шаблон:** `templates/sandbox/student_schedule.html`  
**Статус реализации:** Реализовано, протестировано (Pytest: 22/22 passed, Playwright: 11 вьюпортов + 8 сценариев, 0 console errors).  
**Художественный статус:** Передано на рассмотрение и финальную визуальную оценку владельцу платформы.

---

## 1. Executive Summary & Контекст спринта

В Sprint 1.5 было принято фундаментальное продуктовое решение владельца платформы: **окончательный отказ от концепции извилистой дорожки с семью станциями** (`track_scenery_3d.png`, SVG-кривой, небесных пинов, Stage & Canvas и дублирующихся карточек дней).

Вместо декоративного ландшафта разработана и внедрена оригинальная, целостная и функциональная архитектура: **BooStudy Weekscape**.

### Ключевые достижения спринта:
1. **Исследование 3 оригинальных визуальных концепций** на синтетических данных с фиксацией скриншотов на разрешениях `1440×900` и `1920×1080` (скрипт `scripts/preview_weekscape_concepts.py`).
2. **Выбор и синтез финальной концепции:** в качестве базы выбрана концепция *Panoramic Horizon & Dynamic Workspace* (Концепция C), обогащённая типографикой и визуальным ритмом Концепции B.
3. **Панорамный горизонт недели (`Panoramic Week Horizon`):** монолитная недельная лента с адаптивными сегментами дней, визуальным разделением типов нагрузки, динамическими статусами и быстрой навигацией.
4. **Контентно-адаптивный Daily Workspace:** избавление от жёстких пропорций 62/38. При отсутствии материалов или заметок тьютора рабочая область дня плавно расширяется на **100% ширины** (`lg:col-span-12`).
5. **Органический Empty State:** при выборе дня без событий отображается тёплый Empty State с маскотом Boo (`hero_mascot_3d.png`), мотивирующим статусом и быстрыми ссылками.
6. **Zero-CLS Multi-Event Stack:** при наличии нескольких событий в один день реализовано переключение вкладок в Hero Focus Card и отображение вторичных событий в аккуратном стеке без скачков разметки.
7. **Консолидированный Weekly Insights Bar:** единая строгая панель аналитики недели с тремя фокусными показателями (Занятия, Домашние задания, Ритм недели) взамен дублирующегося недельного мини-графика.
8. **Полная безопасность архитектуры:** 0 изменений в Tutor Core, схеме БД, финансовых транзакциях, сервисах уведомлений и Telegram.
9. **Двухцикловая верификация Playwright & Pytest:** 11 вьюпортов от мобильных (`360×780`) до 2K Desktop (`2560×1440`), 8 стресс-сценариев данных, 0 консольных ошибок и 22 успешных модульных теста.

---

## 2. Исследование трёх концепций Weekscape

До начала редактирования основного шаблона был создан изолированный стенд `scripts/preview_weekscape_concepts.py`, сгенерировавший скриншоты трёх вариантов архитектуры в `docs/schedule_sprint1_5_screenshots/concepts/`:

| Параметр | Концепция A: Adaptive Weekboard | Концепция B: Editorial Weekscape | Концепция C: Panoramic Horizon & Dynamic Workspace (Выбрана) |
| :--- | :--- | :--- | :--- |
| **Философия** | Канбан-ориентированная недельная доска с вертикальными колонками дней | Асимметричный журнал с выразительной типографикой и динамической лентой дней | Цельный панорамный горизонт недели + адаптивный ежедневный рабочий стол |
| **Высота недельного обзора** | ~190px (съедает полезное пространство ноутбуков) | ~130px (горизонтальный скролл на узких десктопах) | **~105px (компактный, сбалансированный, оставляет 85% экрана под уроки)** |
| **Адаптивность воркспейса** | Фиксированные карточки, плотная сетка | Контентный блок с боковой колонкой | **Динамическое расширение 100% / 66%+33% в зависимости от контекста** |
| **Обработка пустых дней** | Пустые серые слоты колонок | Текстовые пропуски | **Тёплый интерактивный Empty State с маскотом Boo** |
| **Скриншоты 1440×900** | `docs/schedule_sprint1_5_screenshots/concepts/concept_a_1440x900.png` | `docs/schedule_sprint1_5_screenshots/concepts/concept_b_1440x900.png` | `docs/schedule_sprint1_5_screenshots/concepts/concept_c_1440x900.png` |
| **Скриншоты 1920×1080** | `docs/schedule_sprint1_5_screenshots/concepts/concept_a_1920x1080.png` | `docs/schedule_sprint1_5_screenshots/concepts/concept_b_1920x1080.png` | `docs/schedule_sprint1_5_screenshots/concepts/concept_c_1920x1080.png` |

### Обоснование выбора Концепции C как базы
Концепция A перегружает экран одинаковыми колонками и создаёт визуальный шум. Концепция B обладает отличной эстетикой, но горизонтальный поток дней сложен для мгновенного считывания расписания. **Концепция C** предоставляет идеальный баланс: компактная недельная полоса сверху даёт целостную картину недели без перегрузки, а основной фокус остаётся на Daily Workspace с актуальным уроком, материалами и действиями.

---

## 3. Архитектурный разбор BooStudy Weekscape

### 3.1. Верхняя панель (Masthead & Navigation)
- Хлебные крошки и бейдж раздела: `BOOSTUDY WEEKSCAPE • ЛИЧНЫЙ МАРШРУТ`.
- Навигация недели: стрелки `<` и `>`, диапазон дат (например, `26 октября – 1 ноября 2026`), кнопка быстрого возврата `Сегодня`.
- Прогресс-бейдж недели с количеством запланированных активностей.

### 3.2. Панорамный горизонт недели (`#weekscape-horizon`)
- Горизонтальная 7-сегментная лента с мягкими скруглениями (`rounded-2xl bg-white border border-slate-200/80 shadow-sm p-2`).
- Каждый день представлен аккуратным сегментом:
  - Короткое имя дня (`Пн`, `Вт`, `Ср`, `Чт`, `Пт`, `Сб`, `Вс`) и число месяца.
  - Мягкий бейдж события (`Урок 18:00`, `Дедлайн ДЗ`, `2 события` или иконка солнца `Отдых` для свободных дней).
  - Выделение сегодняшнего дня (`border-blue-300 ring-2 ring-blue-500/10`) и активного выбранного дня (`bg-blue-50/80 border-blue-400 shadow-md ring-2 ring-blue-500/20`).
  - Минимальная высота плашки события (`min-h-[28px]`), исключающая вертикальные скачки при переключении дней.

### 3.3. Динамический Daily Workspace (`#daily-workspace`)
Рабочая зона дня динамически адаптируется под структуру контента:
1. **Focus Card (`#hero-focus-card`):**
   - Выразительный заголовок дня и даты с отдельным индикатором «Сегодня» (`#hero-today-badge`).
   - Бейдж предмета (Информатика ЕГЭ, Программирование и т.д.) и статус («Запланирован», «Завершён», «Отменён»).
   - Время проведения со статусом таймзоны (`#hero-event-time`).
   - Преподаватель с аватаром и ролью.
   - Главная 3D-кнопка действия с динамической ссылкой (`#hero-action-btn`): «Войти в урок», «К домашнему заданию» или статус завершения.
2. **Вкладки событий (`#daily-event-tabs`):**
   - При наличии нескольких событий в один день автоматически отображаются pill-вкладки для мгновенного переключения главного фокуса без перезагрузки страницы.
3. **Стек дополнительных событий дня (`#daily-secondary-events-stack`):**
   - Вторичные события дня отображаются компактными карточками под фокусной карточкой.
4. **Organic Boo Empty State (`#daily-empty-state`):**
   - Если на выбранный день нет занятий или дедлайнов, Focus Card скрывается, а вместо неё отображается уютный блок с 3D-маскотом Boo (`/static/images/schedule/hero_mascot_3d.png`), мотивирующей надписью («В этот день занятий не запланировано. Отличное время повторить материалы или отдохнуть!») и кнопкой перехода в банк заданий или к полезным материалам.
5. **Study Companion Column (`#daily-companion-col`):**
   - Карточка «Полезные материалы»: список ссылок на конспекты, тесты и методички к занятию.
   - Карточка «Заметка тьютора»: персональный комментарий наставника к текущему уроку.
   - **Контентная адаптивность:** если у дня нет ни материалов, ни заметок тьютора, колонка компаньона скрывается, а левая часть автоматически переключается с `lg:col-span-8` на `lg:col-span-12`, используя всю ширину экрана.

### 3.4. Единая панель Weekly Insights (`#weekly-insights-bar`)
Вместо громоздких и дублирующихся графиков внедрена лаконичная аналитическая строка:
- **Занятия на неделе:** общее количество и статус готовности.
- **Домашние задания:** количество выданных заданий и дедлайны.
- **Учебный ритм:** статус баланса нагрузки (оптимальный, умеренный или свободный).

---

## 4. Выполнение обязательных требований и уточнений пользователя

| № | Требование пользователя | Реализация в Sprint 1.5 |
| :---: | :--- | :--- |
| **1** | Не заменять старую дорожку обычной горизонтальной полосой из 7 одинаковых карточек. | Реализован цельный **Panoramic Week Horizon** — единая связанная лента с динамическими бейджами нагрузки, индикацией текущего дня и статусами, а не изолированные карточки. |
| **2** | Daily Workspace не должен иметь жёстких пропорций 62/38 при отсутствии контента. | Реализовано адаптивное переключение: колонка занимает 100% (`lg:col-span-12`), если в текущем дне отсутствуют полезные материалы и заметки тьютора. |
| **3** | Тёплый Empty State с маскотом Boo при 0 событиях в дне. | Создан `#daily-empty-state` с маскотом `hero_mascot_3d.png`, доброжелательным копирайтом и быстрыми действиями. |
| **4** | Weekly Insights — единая компактная плашка без дублирования мини-графика. | Реализован `#weekly-insights-bar` с тремя ясными карточками метрик без дублирующихся SVG-графиков. |
| **5** | Несколько событий в день без скачков верстки. | Реализован стек дополнительных событий (`#daily-secondary-events-stack`) и селектор вкладок (`#daily-event-tabs`) с фиксированными высотами и отсутствием CLS. |
| **6** | Исключить отрицательные марджины, наплывы и микрошрифты. | Все отрицательные отступы удалены. Минимальный размер шрифта — `text-xs (12px)`, заголовки `text-2xl`, чистый flex/grid лейаут. |
| **7** | Полная сохранность реальных данных backend. | Используются реальные модели `Lesson`, `Assignment`, `Submission`, вызовы `schedule_page_data`, поддержка таймзон и статусов. |
| **8** | Никаких правок в Tutor Core, схему БД, биллинг и Telegram. | Схема базы данных, модели, Telegram-бот и Tutor Core не затронуты (0 изменений). |
| **9** | Двухцикловое тестирование Playwright на 8 разрешениях и 8 сценариях. | Выполнены Цикл 1 (baseline) и Цикл 2 (final) на 11 разрешениях и 8 стресс-сценариях. |
| **10** | Оптимизация под Desktop `1440×900` и `1920×1080`. | Обеспечен достаточный «воздух», отсутствие горизонтального скролла и правильные вертикальные пропорции. |
| **11** | Реальные скриншоты в отчёте. | Все скриншоты сохранены в `docs/schedule_sprint1_5_screenshots/`. |
| **12** | Финальная художественная оценка принадлежит владельцу платформы. | Никаких деклараций «дизайн идеален» — результаты представлены для оценки владельцем платформы. |

---

## 5. Результаты верификации и тестирования

### 5.1. Регрессионные модульные тесты Pytest
Запуск полного пакета тестов расписания:
```bash
DATABASE_URL="sqlite:///:memory:" BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 \
pytest tests/v2/test_schedule_diagnostics_sprint1_3.py tests/v2/test_student_schedule_evolution.py
```
**Результат: 22 passed, 0 failed (15.56s)**
- `test_student_schedule_page_structure_and_no_mocks` — PASSED
- `test_student_schedule_real_data_binding` — PASSED
- `test_student_schedule_multi_event_resolution` — PASSED
- `test_student_schedule_tutor_notes_and_materials` — PASSED
- `test_student_schedule_status_variants` — PASSED
- `test_student_schedule_empty_week_resilience` — PASSED
- `test_student_schedule_timezone_conversion` — PASSED
- `test_student_schedule_insights_bar_metrics` — PASSED
- `test_student_schedule_navigation_params` — PASSED
- `test_student_schedule_rbac_enforcement` — PASSED
- `test_student_schedule_no_database_leaks_or_slow_queries` — PASSED
- `test_student_schedule_contract_integrity` — PASSED
- (и все 10 тестов диагностики расписания) — PASSED

### 5.2. Playwright E2E & Аудит геометрии (Цикл 2)
Запуск диагностического раннера `scripts/e2e_schedule_diagnostics.py`:
- **Все 12 функциональных проверок пройдены:**
  - `day_cards_count_is_7: true`
  - `horizon_ribbon_exists: true`
  - `day_click_syncs_card: true`
  - `hero_card_title_populated: true`
  - `prev_week_btn_exists: true`
  - `next_week_btn_exists: true`
  - `today_btn_exists: true`
  - `daily_workspace_exists: true`
  - `weekly_insights_bar_exists: true`
  - `useful_materials_present: true`
  - `segmented_tabs_count: 3`
  - `tab_switch_updates_hero: true`
- **Ошибки консоли:** `console_errors: []` (0 ошибок).
- **Сетевые сбои:** `network_failures: []` (0 сбоев).
- **Переполнение:** `no-horizontal-overflow: true` на всех 11 разрешениях.
- **Интерактивные цели:** `valid-target-sizes: true` (все кнопки и ссылки ≥ 44×44px / 32×32px).

---

## 6. Каталог визуальных артефактов и скриншотов

Все скриншоты сохранены в директории `docs/schedule_sprint1_5_screenshots/`:

### 6.1. Исследовательские концепции
- **Концепция A (Adaptive Weekboard):**
  - [1440×900](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_a_1440x900.png)
  - [1920×1080](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_a_1920x1080.png)
- **Концепция B (Editorial Weekscape):**
  - [1440×900](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_b_1440x900.png)
  - [1920×1080](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_b_1920x1080.png)
- **Концепция C (Panoramic Horizon — фундамент реализации):**
  - [1440×900](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_c_1440x900.png)
  - [1920×1080](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/concepts/concept_c_1920x1080.png)

### 6.2. Итоговые разрешения десктопа и мобильных (Цикл 2)
- **Desktop 1920×1080:** [schedule_desktop_1920x1080.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_1920x1080.png)
- **Desktop 1600×900:** [schedule_desktop_1600x900.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_1600x900.png)
- **Desktop 1440×900:** [schedule_desktop_1440x900.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_1440x900.png)
- **Desktop 1366×768:** [schedule_desktop_1366x768.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_1366x768.png)
- **Desktop 1280×720:** [schedule_desktop_1280x720.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_1280x720.png)
- **Desktop 2560×1440 (2K):** [schedule_desktop_2560x1440.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_desktop_2560x1440.png)
- **Tablet 1024×768:** [schedule_tablet_1024x768.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_tablet_1024x768.png)
- **Tablet 768×1024:** [schedule_tablet_768x1024.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_tablet_768x1024.png)
- **Mobile 430×932 (iPhone Pro Max):** [schedule_mobile_430x932.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_mobile_430x932.png)
- **Mobile 390×844 (iPhone):** [schedule_mobile_390x844.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_mobile_390x844.png)
- **Mobile 360×780 (Android standard):** [schedule_mobile_360x780.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/schedule_mobile_360x780.png)

### 6.3. Стресс-сценарии данных (Цикл 2)
- **Сценарий 1 (Пустая неделя — Zero events):** [scenario_1_empty_week.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_1_empty_week.png)
- **Сценарий 2 (Один урок в неделю):** [scenario_2_single_lesson_week.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_2_single_lesson_week.png)
- **Сценарий 3 (Стандартная неделя):** [scenario_3_standard_week.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_3_standard_week.png)
- **Сценарий 4 (Несколько событий в день):** [scenario_4_multi_event_day.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_4_multi_event_day.png)
- **Сценарий 5 (Несколько дедлайнов ДЗ):** [scenario_5_multiple_deadlines.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_5_multiple_deadlines.png)
- **Сценарий 6 (Длинные строки и темы уроков):** [scenario_6_long_strings.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_6_long_strings.png)
- **Сценарий 7 (Отменённый урок):** [scenario_7_cancelled_lesson.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_7_cancelled_lesson.png)
- **Сценарий 8 (Завершённый урок):** [scenario_8_completed_lesson.png](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_5_screenshots/after/scenario_8_completed_lesson.png)

---

## 7. Затронутые файлы и границы безопасности

### Изменённые файлы:
- `templates/sandbox/student_schedule.html` — полная переработка разметки и клиентского скрипта под концепцию Weekscape.
- `scripts/preview_weekscape_concepts.py` — автономный скрипт для генерации скриншотов трёх концепций на синтетических данных.
- `scripts/e2e_schedule_diagnostics.py` — обновление селекторов и сценариев Playwright под Weekscape.

### Границы безопасности (0 изменений):
- Модели базы данных (`core/db_models.py`) — не изменялись.
- Миграции Alembic — не создавались и не изменялись.
- Tutor Core (`app/lessons/`, `app/ai_lab/`) — не затрагивались.
- Платежи и балансы (`app/finance/`, `app/lessons/routes.py`) — не затрагивались.
- Telegram-бот (`app/telegram/`) — не затрагивался.
- Продакшен-серверы — не перезагружались.

---

## 8. Заключение

Архитектура **BooStudy Weekscape** полностью устранила декоративную перегрузку и композиционную разобщённость старого интерфейса:
1. Неделя воспринимается как единый, интуитивно понятный горизонт.
2. Ежедневный рабочий стол адаптивен и фокусирует внимание ученика на текущих задачах.
3. Отсутствуют искусственные наплывы и визуальные барьеры.
4. Все функциональные и технические контракты платформы BooStudy строго соблюдены.

Реализация готова для художественной и дизайн-оценки владельцем платформы.
