# BooStudy UI Canon (Конституция дизайна BooStudy)

Этот документ является ЕДИНЫМ СТРОГИМ ИСТОЧНИКОМ ПРАВИЛ для пользовательского интерфейса платформы BooStudy.
Все AI-агенты и разработчики ОБЯЗАНЫ сверяться с этими классами и правилами при любой работе с UI.

---

## 🎨 1. Основные стили и компоненты

### 1.1 Стиль карточек (Tactile 3D Cards)
- **Запрещено:** Плоские тонкие рамки `border-[1.5px] border-slate-100`, жесткие серые заливки.
- **Обязательно:** Объемные тактильные карточки с выразительной нижней 3D-тенью.
- **Классы:**
  ```html
  bg-[#F4F7FA] border-2 border-slate-200 shadow-[0_4px_0_#DAE1E9] rounded-[2rem] p-6 sm:p-8
  ```
- **Для строк списков (компактные карточки):**
  ```html
  bg-[#F4F7FA] border-2 border-slate-200 shadow-[0_4px_0_#DAE1E9] rounded-[1.5rem] p-4 mb-4
  ```

---

### 1.2 Кнопки (Объемные 3D-Кнопки / Tactile 3D Buttons)
- **Запрещено:** `w-full` растяжка на всю ширину (если не выпадающий элемент модалки), плоские стили без нижнего бортика.
- **Обязательно:** Ширина по контенту (`w-auto` / `self-start`), объемный нижний бортик `border-b-[4px]`, сочная тень и анимация клика `active:translate-y`.
- **Классы (Главная фиолетовая):**
  ```html
  bg-indigo-600 hover:bg-indigo-500 text-white font-black px-6 py-3.5 rounded-xl border border-indigo-700 border-b-[4px] shadow-[0_4px_10px_rgba(79,70,229,0.2)] active:border-b-[1px] active:translate-y-[3px] transition-all self-start w-auto
  ```
- **Классы (Второстепенная белая):**
  ```html
  bg-white hover:bg-slate-50 text-slate-700 font-black px-6 py-3.5 rounded-xl border border-slate-200 border-b-[4px] shadow-[0_2px_5px_rgba(0,0,0,0.05)] active:border-b-[1px] active:translate-y-[3px] transition-all self-start w-auto
  ```

---

### 1.3 Метрики и фильтры (Pill-Tabs Controller)
- **Запрещено:** Использовать 4 гигантские цветные карточки с огромными цифрами для показтелей.
- **Обязательно:** Компактные сегментированные контроллеры (Pill-tabs) в шапке страницы.
- **Классы контейнера:**
  ```html
  flex items-center p-1.5 bg-[#F4F7FA] rounded-[1.25rem] border border-slate-200 shadow-[inset_0_2px_4px_rgba(0,0,0,0.03)] overflow-x-auto hide-scrollbar
  ```
- **Классы кнопок переключения:**
  ```html
  px-5 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 whitespace-nowrap
  ```
- **Бейджи-счетчики внутри табов:**
  ```html
  w-5 h-5 rounded-full bg-indigo-100 border border-indigo-200 text-indigo-700 flex justify-center items-center text-[10px] font-black
  ```

---

### 1.4 Теги и статусы (Pill-Badges)
- **Желтый тег (ДЗ):**
  ```html
  inline-flex items-center gap-1.5 px-3 py-1 bg-amber-100 text-amber-800 border border-amber-200 rounded-lg text-xs font-black uppercase tracking-widest shadow-xs
  ```
- **Красный тег (Просрочено / Внимание):**
  ```html
  inline-flex items-center gap-1.5 px-3 py-1 bg-rose-100 text-rose-800 border border-rose-200 rounded-lg text-xs font-black uppercase tracking-widest shadow-xs
  ```
- **Зеленый тег (Завершено / Готово):**
  ```html
  inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-100 text-emerald-800 border border-emerald-200 rounded-lg text-xs font-black uppercase tracking-widest shadow-xs
  ```

---

### 1.5 Прогресс-бары (Вогнутые / Concave Progress Bars)
- **Запрещено:** Плоские яркие полосы без рельефа.
- **Обязательно:** Вогнутая подложка с внутренней тенью `shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]`.
- **Классы подложки:**
  ```html
  w-full bg-slate-200 rounded-full h-3 border border-slate-300 overflow-hidden shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)] relative
  ```
- **Классы индикатора:**
  ```html
  bg-indigo-500 h-full rounded-full transition-all duration-500
  ```

---

## 📏 2. Глобальная сетка (Layout Standard)

- **Главный холст (Master Canvas Width):** Все главные белые холсты (Master Canvas) на всех страницах преподавателя и ученика (КРОМЕ Тренажера) ДОЛЖНЫ иметь строго единую максимальную ширину для предотвращения скачков интерфейса при навигации.
- **Абсолютный эталон ширины (из `student_dashboard.html` и `tasks.html`):**
  ```html
  max-w-[1400px] mx-auto
  ```
- **Запрещено:** Задавать выдуманные значения (`max-w-[1000px]`, `max-w-[1200px]`, `max-w-[1500px]`) для любых страниц платформы. Все макеты должны быть попиксельно идентичны.
- **Исключение:** Тренажер (`trainer.html`) сохраняет свою расширенную ширину для ведения вычислений.

---

## 🛡️ 3. Правила защиты от импровизаций
1. Никогда не перезаписывать `teacher_dashboard.html` и ученический `tasks.html`.
2. Не создавать новых «кислотных» градиентов или сплошных заливок.
3. Сохранять 100% Jinja2-переменных, циклов и модальных окон при рефакторинге шаблонов.
4. **⛔ СТРОГИЙ ЗАПРЕТ НА NATIVE BROWSER ALERTS (`alert()`, `confirm()`, `prompt()`):**
   - В JavaScript-коде веб-платформы и Telegram Mini App КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать стандартные браузерные окна `alert()`, `confirm()`, `prompt()`.
   - Любые уведомления об успехе, генерации кодов, копировании, ошибках и подтверждениях ОБЯЗАНЫ выводиться через стилизованные BooStudy Bento 3D-модалки (`#tg-code-modal`) или всплывающие тосты.
5. **⛔ ИММУНИТЕТ АККАУНТА CREATOR:**
   - Аккаунт с `username='creator'` неприкосновен. Запрещено его удаление, зануление или смена роли как в локальной базе данных, так и на сервере продакшена.


