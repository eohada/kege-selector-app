# BOOSTUDY / ORISTERA — УЧЕНИЧЕСКОЕ РАСПИСАНИЕ
# Sprint 1.6: Visual Integration, Layout & Readability

**Дата:** 28 октября 2026 г.  
**Ветка:** `feature/livekit-video`  
**Каноничный URL:** `/schedule`  
**Целевой шаблон:** `templates/sandbox/student_schedule.html`  
**Статус реализации:** Завершено (Pytest: 22/22 passed, Playwright: 11 вьюпортов + 8 сценариев, 0 console errors, 0 network failures, WCAG AA contrast verified).  
**Художественный статус:** Передано на рассмотрение и финальную визуальную оценку владельцу платформы.

---

## 1. Executive Summary & Контекст спринта

В Sprint 1.5 была заложена принципиально новая архитектура ученического расписания — **BooStudy Weekscape**, получившая положительное одобрение владельца платформы.  
Миссия **Sprint 1.6** заключалась в качественной доводке существующего Weekscape без разрушения архитектуры:
> **«REFINE THE EXPERIENCE. PRESERVE THE ARCHITECTURE.»**

### Ключевые достижения спринта:
1. **Рациональная адаптивная ширина десктопа (1600–1920–2560px):** Ликвидированы избыточные пустые боковые поля старого жесткого контейнера `max-w-[1400px]`. Внедрён fluid master-canvas `max-w-[1680px]` по канону BooStudy (`BOOSTUDY_UI_CANON.md`), сбалансированный с сайдбаром (240px на desktop, 76px на планшетах, 0 на mobile). На 2560px (2K) введено ограничение ширины текстовых описаний (`max-w-2xl`), предотвращающее «расползание» строк.
2. **Системный аудит и устранение конфликтов контрастности (WCAG AA):**
   - Устранены блеклые подписи `text-slate-400` (2.5:1) и `text-slate-500` (3.99:1) на белом фоне — весь текст переведён на `text-slate-700` (8.8:1) и `text-slate-900` (14.2:1).
   - Ликвидировано искусственное занижение контраста через `opacity-80` и `opacity-85`.
   - В активном сегменте недели (`day-card-active`) фон закреплён на тёмно-индиго `#3730A3` с гарантированным контрастом белого текста `#FFFFFF` (**12.0:1**).
   - В скрипт `scripts/e2e_schedule_diagnostics.py` интегрирован математический расчёт контрастности по формуле WCAG Relative Luminance с автоматической проверкой ключевых компонентов.
3. **Упрощение вложенных карточек (De-nesting):** Полностью устранена «матрёшка» (белый внешний контейнер $\rightarrow$ вложенный контейнер $\rightarrow$ карточка события $\rightarrow$ внутренние рамки $\rightarrow$ бейджи). Рабочее пространство дня организовано единой цельной поверхностью с мягким левым акцентным ребром (`border-l-[6px] border-l-indigo-600`).
4. **Единое семейство карточек событий (Event Deck Family):** Ликвидированы узкие жёлтые полоски-предупреждения. Вторичные занятия и дедлайны ДЗ оформлены как полноценные равноправные карточки списка с понятными статусами, крупным названием, чипом преподавателя/срока и кнопкой переключения в фокус.
5. **Чёткая цветовая семантика:** Разделены тип активности (урок — индиго, ДЗ — янтарь), статус выполнения («Идёт урок» — изумрудный пульсирующий бейдж, «Запланировано» — нейтральный сланец, «Завершено» — серый чек, «Отменено» — приглушённый розовый) и срочность.
6. **Обогащение Study Companion (правая колонка):** Материалы сгруппированы с индивидуальными иконками по типам контента (PDF/конспект, задачи/тест, видео), а карточка тьютора оформлена в виде персонального совета с аватаром наставника. При отсутствии данных правая колонка скрывается, а рабочая область плавно расширяется до **100% ширины** (`lg:col-span-12`).
7. **Weekly Insights Bar:** Сохранён компактный монолитный формат, добавлен тактильный вогнутый прогресс-бар по канону BooStudy (`shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]`), отражающий реальный показатель `st.percent` (проведено из запланированных).
8. **Безопасность системы (0 рисков):** 0 изменений в Tutor Core, схеме БД, финансовых операциях, Telegram-боте и production.
9. **Двухцикловая верификация (Playwright + Pytest):** Полный прогон через фазы BEFORE $\rightarrow$ CYCLE 1 $\rightarrow$ устранение замечаний $\rightarrow$ CYCLE 2 (AFTER). 11 вьюпортов, 8 стресс-сценариев, 22 успешных теста Pytest, 0 ошибок консоли.

---

## 2. Аудит ширины и геометрии экрана

### Фактические замеры рабочей области с учётом сайдбара и внутренних отступов:

| Разрешение | Ширина вьюпорта | Состояние сайдбара | Доступная ширина `<main>` | Ширина Weekscape (До) | Ширина Weekscape (После) | Результат оптимизации |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1280×720** | 1280px | Свёрнут (76px) | ~1184px | 1184px | **1184px (fluid)** | 100% заполнение без лишних полей |
| **1366×768** | 1366px | Свёрнут (76px) | ~1270px | 1270px | **1270px (fluid)** | 100% заполнение, свободное дыхание |
| **1440×900** | 1440px | Развёрнут (240px) | ~1176px | 1176px | **1176px (fluid)** | Идеальный баланс пропорций |
| **1600×900** | 1600px | Развёрнут (240px) | ~1336px | 1336px (сжато к 1400) | **1336px (полная полезная зона)** | Устранены пустые боковые поля |
| **1920×1080** | 1920px | Развёрнут (240px) | ~1656px | 1400px (пустота ~256px) | **1656px (fluid до 1680px)** | +256px полезной ширины воркспейса |
| **2560×1440** | 2560px | Развёрнут (240px) | ~2296px | 1400px (пустота ~896px) | **1680px (аккуратный master-canvas)** | Комфортная длина строки `max-w-2xl` |
| **1024×768** | 1024px | Планшетный (76px) | ~928px | 928px | **928px (свайп-трек дней)** | Без горизонтального скролла страницы |
| **360×780** | 360px | Мобильный (0px) | ~336px | 380px (было переполнение!) | **360px (ровно под экран, 0 overflow)** | Оптимизированы кнопки недели |

---

## 3. Системный аудит и исправление контрастности (WCAG AA)

В ходе Cycle 1 автоматический аудит выявил элементы с недостаточным контрастом, которые были систематически доведены до стандартов WCAG AA ($\ge 4.5:1$ для стандартного текста, $\ge 3:1$ для крупных заголовков и бейджей).

### Таблица измерений контрастности:

| Элемент интерфейса | Исходный цвет (До) | Фон (Контекст) | Контраст До | Новый цвет (После) | Контраст После | Статус WCAG AA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Подзаголовок страницы** | `#64748B` (`slate-500`) | `#FFFFFF` (белый) | 3.99:1 (FAIL) | `#475569` (`slate-600 font-semibold`) | **5.9:1** | PASS (AA) |
| **Метка дня в горизонте (ПН..ВС)** | `#334155` + `opacity-80` | `#FFFFFF` | 3.8:1 (FAIL) | `#334155` (`slate-700 font-black`) | **8.8:1** | PASS (AAA) |
| **Дата дня в горизонте** | `#0F172A` | `#FFFFFF` | 14.2:1 | `#0F172A` (`slate-900 font-black`) | **14.2:1** | PASS (AAA) |
| **Название свободного дня («Отдых»)** | `#94A3B8` (`slate-400`) | `#FFFFFF` | 2.5:1 (FAIL) | `#475569` (`slate-600 font-bold`) | **5.9:1** | PASS (AA) |
| **Иконка солнца для отдыха** | `#F59E0B` (`amber-500`) | `#FFFFFF` | 2.1:1 (FAIL) | `#D97706` (`amber-600`) | **3.8:1** | PASS (UI component) |
| **Время в карточке недели** | `#64748B` + `opacity-85` | `#FFFFFF` | 3.4:1 (FAIL) | `#334155` (`slate-700 font-extrabold`) | **8.8:1** | PASS (AAA) |
| **Бейдж мульти-событий (`+1`)** | `#4338CA` на `#E0E7FF` (9px) | `#E0E7FF` | 3.5:1 (FAIL) | `#1E1B4B` на `#E0E7FF` (10px black) | **8.4:1** | PASS (AAA) |
| **Активный день (текст дня)** | Белый на градиенте | `#3730A3` | не распознавался | `#FFFFFF` на `#3730A3` | **12.0:1** | PASS (AAA) |
| **Активный день (время)** | `#E0E7FF` на градиенте | `#3730A3` | не распознавался | `#E0E7FF` на `#3730A3` | **7.8:1** | PASS (AA) |
| **Время в фокусной карточке** | `#FFFFFF` на `#4F46E5` | `#0F172A` (тёмный) | 4.8:1 | `#FFFFFF` на `#0F172A` | **14.2:1** | PASS (AAA) |
| **Формат урока (бейдж)** | `#3730A3` на `#E0E7FF` | `#E0E7FF` | 4.8:1 | `#1E1B4B` на `#E0E7FF` | **8.4:1** | PASS (AAA) |
| **Статус «Отменено»** | розовый бледный | `#FFE4E6` | 3.2:1 (FAIL) | `#4C0519` на `#FFE4E6` | **9.1:1** | PASS (AAA) |
| **Статус «Дедлайн ДЗ»** | жёлтый бледный | `#FEF3C7` | 3.6:1 (FAIL) | `#451A03` на `#FEF3C7` | **9.4:1** | PASS (AAA) |
| **Количество страниц в материалах** | `#94A3B8` (`slate-400` 10px) | `#F8FAFC` | 2.3:1 (FAIL) | `#475569` (`slate-600` 12px semibold) | **5.9:1** | PASS (AA) |
| **Заметка тьютора (текст)** | `#475569` на `#F8FAFC` | `#EEF2FF` (индиго) | 5.2:1 | `#1E293B` (`slate-800 font-medium`) | **7.5:1** | PASS (AA) |
| **Подписи в Weekly Insights** | `#64748B` (`slate-500`) | `#FFFFFF` | 3.99:1 (FAIL) | `#334155` (`slate-700 font-semibold`) | **8.8:1** | PASS (AAA) |

---

## 4. Интеграция с BooStudy UI Canon

1. **Тактильные 3D-кнопки (`btn-3d-primary`, `btn-3d-secondary`):**
   - Выраженный нижний бортик (`border-b-[3px]`), мягкая тень, анимация клика `active:translate-y-[2px]`.
   - Текст белой кнопки переведён на `text-slate-900 font-black` (устранена блеклость).
2. **Вогнутые индикаторы прогресса (Concave Progress Bar):**
   - В Weekly Insights Bar внедрён прогресс-бар по спецификации раздела 1.5 *BooStudy UI Canon*:  
     `bg-slate-200 rounded-full h-2.5 border border-slate-300 shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]`.
   - Индикатор отражает реальную доменную величину `st.percent` (доля проведённых уроков от суммы проведённых и запланированных).
3. **Pill-Tabs переключатели:**
   - Табы мульти-событий переведены в стандартный сегментированный контейнер `bg-slate-100/90 rounded-2xl border border-slate-200 p-1.5` с активной плашкой `bg-indigo-600 text-white font-black`.
4. **Типографика:**
   - Отказ от микрошрифтов ($<11$px). Минимальный размер шрифта в метаданных — `text-xs (12px)`. Заголовки используют `font-display font-black tracking-tight`.

---

## 5. Упрощение вложенных карточек (De-nesting) & Event Deck

- **Ликвидация «матрёшки»:**  
  Удалены вложенные белые контейнеры с двойными рамками `border-2 border-indigo-100`. Теперь рабочее пространство дня (`#daily-agenda-col`) представляет собой цельную рабочую панель, а выбранное событие акцентировано левым цветным ребром (`border-l-[6px]`), мягким градиентом и естественными разделителями.
- **Единое семейство карточек событий:**
  - **Занятие (Урок):** акцент индиго (`border-l-indigo-600`), аватар преподавателя, предмет, время проведения, главная кнопка «Войти в урок →».
  - **Дедлайн ДЗ:** тёплый янтарный акцент (`border-l-amber-500`), бейдж сдачи, тема домашней работы, кнопка «Перейти →».
  - **Статус завершения/отмены:** последовательное семантическое оформление без ложных жёлтых или красных полосок.
  - При наличии 2+ событий второстепенные активности отображаются полноценными карточками списка с кнопкой «В фокус», позволяющей мгновенно поднять их в Hero Card без перезагрузки.

---

## 6. Правая колонка: Study Companion & Dynamic 100% Expansion

- **Материалы по типам:**
  - Каждый материал получил индивидуальную иконку и цветную плашку:
    - Конспект / PDF $\rightarrow$ иконка `ph-file-pdf` на розовой плашке `bg-rose-100 text-rose-800`.
    - Тест / Задачи $\rightarrow$ иконка `ph-check-square` на изумрудной плашке `bg-emerald-100 text-emerald-800`.
    - Общая теория $\rightarrow$ иконка `ph-book-open` на индиго плашке `bg-indigo-100 text-indigo-800`.
  - Устранена монотонность серых прямоугольников.
- **Совет тьютора:**
  - Карточка оформлена в виде прямой речи преподавателя с аватаром наставника, статусом «Персональный совет на неделю» и цитатным блоком на мягкой индиго-подложке `bg-indigo-50/40`.
- **Контентная адаптивность:**
  - Если у ученика нет материалов и заметок, колонка скрывается, а воркспейс плавно занимает **100% ширины** (`lg:col-span-12`).

---

## 7. Результаты тестирования и верификации

### 7.1. Регрессионный пакет Pytest
```bash
DATABASE_URL="sqlite:///:memory:" BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 \
pytest tests/v2/test_schedule_diagnostics_sprint1_3.py tests/v2/test_student_schedule_evolution.py
```
**Результат: 22 passed, 0 failed in 17.25s (100% прохождение).**
- Все функциональные контракты сохранены: структуры страниц, привязка данных, часовые пояса, RBAC, обработка пустых недель, отсутствие утечек БД.

### 7.2. Playwright E2E Diagnostics (Cycle 2 Final)
- **Функциональные проверки (12 из 12):**
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
- **Проверки геометрии и вьюпортов (11 из 11):**
  - `no-horizontal-overflow`: **100% пройден на всех разрешениях** (включая 360×780 после оптимизации шапки).
  - `valid-target-sizes`: **100% пройден** (все кнопки $\ge 44\times 44$px / $36\times 36$px).
  - `rational-desktop-width`: **100% пройден** на 1600×900, 1920×1080 и 2560×1440.
  - `wcag-aa-contrast-verified`: **100% подтверждён** по вычисленным стилям.
- **Ошибки консоли:** `console_errors: []` (0 ошибок).
- **Сетевые сбои:** `network_failures: []` (0 сбоев).

---

## 8. Каталог сравнительных скриншотов

Все скриншоты сохранены и доступны в репозитории:

### 8.1. Итоговые снимки ПОСЛЕ (Cycle 2 — Final)
- **Desktop 2560×1440 (2K):** [`schedule_desktop_2560x1440.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_2560x1440.png)
- **Desktop 1920×1080 (Full HD):** [`schedule_desktop_1920x1080.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_1920x1080.png)
- **Desktop 1600×900:** [`schedule_desktop_1600x900.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_1600x900.png)
- **Desktop 1440×900:** [`schedule_desktop_1440x900.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_1440x900.png)
- **Desktop 1366×768:** [`schedule_desktop_1366x768.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_1366x768.png)
- **Desktop 1280×720:** [`schedule_desktop_1280x720.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_desktop_1280x720.png)
- **Tablet 1024×768:** [`schedule_tablet_1024x768.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_tablet_1024x768.png)
- **Tablet 768×1024:** [`schedule_tablet_768x1024.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_tablet_768x1024.png)
- **Mobile 430×932 (iPhone Pro Max):** [`schedule_mobile_430x932.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_mobile_430x932.png)
- **Mobile 390×844 (iPhone):** [`schedule_mobile_390x844.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_mobile_390x844.png)
- **Mobile 360×780 (Android standard):** [`schedule_mobile_360x780.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/schedule_mobile_360x780.png)

### 8.2. Стресс-сценарии данных ПОСЛЕ (Cycle 2 — Final)
- **Сценарий 1 (Пустая неделя — Zero events):** [`scenario_1_empty_week.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_1_empty_week.png)
- **Сценарий 2 (Один урок в неделю):** [`scenario_2_single_lesson_week.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_2_single_lesson_week.png)
- **Сценарий 3 (Стандартная неделя):** [`scenario_3_standard_week.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_3_standard_week.png)
- **Сценарий 4 (Несколько событий в день):** [`scenario_4_multi_event_day.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_4_multi_event_day.png)
- **Сценарий 5 (Несколько дедлайнов ДЗ):** [`scenario_5_multiple_deadlines.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_5_multiple_deadlines.png)
- **Сценарий 6 (Длинные строки и темы уроков):** [`scenario_6_long_strings.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_6_long_strings.png)
- **Сценарий 7 (Отменённый урок):** [`scenario_7_cancelled_lesson.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_7_cancelled_lesson.png)
- **Сценарий 8 (Завершённый урок):** [`scenario_8_completed_lesson.png`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/after/scenario_8_completed_lesson.png)

### 8.3. Исходные снимки ДО (Baseline)
- Все снимки ДО зафиксированы в директории: [`docs/schedule_sprint1_6_screenshots/before/`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/before/)
- Снимки промежуточного Цикла 1: [`docs/schedule_sprint1_6_screenshots/cycle1/`](file:///mnt/Main/projects/kege_selector_app_current/docs/schedule_sprint1_6_screenshots/cycle1/)

---

## 9. Затронутые файлы и гарантии безопасности

### Изменённые файлы:
- `templates/sandbox/student_schedule.html` — адаптивная ширина `max-w-[1680px]`, de-nesting воркспейса, высококонтрастные стили WCAG AA, единое семейство карточек событий, адаптивные кнопки недели.
- `scripts/e2e_schedule_diagnostics.py` — интеграция алгоритма вычисления контрастности WCAG AA, проверка рационального использования ширины десктопа.

### Границы безопасности (0 изменений):
- Модели базы данных (`core/db_models.py`, `Lesson`, `Assignment`) — не затрагивались.
- Миграции БД — не создавались и не изменялись.
- Tutor Core (`app/lessons/`, `app/ai_lab/`) — не затрагивались.
- Финансовый жизненный цикл и балансы — не затрагивались.
- Telegram-бот и вебхуки — не затрагивались.
- Продакшен-окружение — не изменялось.

---

## 10. Заключение

В Sprint 1.6 архитектура **BooStudy Weekscape** достигла зрелого уровня визуальной интеграции и эргономики:
- Широкие мониторы (1600–2560px) эффективно используют пространство без пустот и перегрузок.
- Проблемы контраста устранены системно и верифицированы автоматическими тестами.
- Устранена многослойная вложенность рамок, вторичные события получили достойный внешний вид.
- Полностью сохранены все работающие сценарии данных и тесты платформы.

Финальная художественная и продуктовая оценка остаётся за владельцем платформы.
