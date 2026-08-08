# Custom Instructions (AI Guidelines)

## Технологический стек
- **Backend:** Python 3, Flask, SQLAlchemy (ORM), Celery (Background Tasks), PostgreSQL.
- **Frontend:** HTML5 (Jinja2 templates), Tailwind CSS (через CLI или CDN), Vanilla JS (или минимальный React/Alpine).
- **Парсинг/Scraping:** Playwright, BeautifulSoup4.
- **База данных:** PostgreSQL, Redis (для Celery).

## Правила именования (Naming Conventions)
- **Python-код:**
  - Переменные и функции: `snake_case`
  - Классы (в т.ч. модели SQLAlchemy): `PascalCase`
  - Константы: `UPPER_SNAKE_CASE`
- **Файлы и директории:** 
  - Python-модули и скрипты: `snake_case` (например, `check_users.py`)
  - Шаблоны HTML: `snake_case` (например, `teacher_landing.html`)
- **CSS / Frontend:**
  - Использовать утилитарные классы Tailwind.
  - Кастомные цвета и темы в Tailwind использовать с префиксом (например, `boo-primary`, `boo-bg`).

## UI/UX Предпочтения (по эталонным образцам BooStudy 2.0)
Основано на файлах из папки `boostudy2.0_examples`.
- **Шрифты:** 
  - Основной текст: `Golos Text` (sans-serif)
  - Код и технические элементы: `JetBrains Mono` (monospace)
- **Иконки:** Phosphor Icons (использование классов `ph-fill`, `ph-bold` и т.д.).
- **Цветовая палитра (Кастомные Tailwind переменные):**
  - Background: `#F8FAFC` (`boo-bg`)
  - Surface: `#FFFFFF` (`boo-surface`)
  - Primary: `#7B5CFF` (`boo-primary`) - основной акцент
  - Secondary/Cyan: `#06B6D4` (`boo-cyan`)
  - Accent/Orange: `#FF9F1C` (`boo-accent`)
  - Текст: `#1E293B` (основной), `#64748B` (приглушенный)
- **Стилистика компонентов:**
  - Обильное использование скруглений: `rounded-xl`, `rounded-2xl`, `rounded-[32px]`.
  - Тактильные тени и глубина: кастомные тени `shadow-tactile` (`0 8px 24px -4px rgba(15, 23, 42, 0.06)`).
  - Эффекты стекла (Glassmorphism): использование `backdrop-blur` и полупрозрачных фонов.
  - Градиентный текст (`background-clip: text`) для заголовков.
- **Анимации и микроинтеракции:**
  - Hover-эффекты: поднятие карточек (`hover:-translate-y-1`), увеличение иконок (`group-hover:scale-110`).
  - Плавающие элементы: анимации `animate-float` для парящих виджетов.
  - Интерактивность: кнопки с эффектом нажатия (`active:translate-y-[2px]`, обнуление `border-b`).
- **Сетки и лейауты:**
  - Bento grids для вывода фич и блоков.

## Правила работы со структурой проекта (Best Practices)
- **Не засорять корень проекта!** 
  - Все временные JSON-дампы, логи и экспорты складывать в директории `data/`, `exports/`, `logs/` или `backups/`.
  - Все служебные скрипты (диагностика, миграции данных, парсеры) складывать в `scripts/` или `tools/`.
- Поддерживать модульность во Flask (использовать Blueprints).
