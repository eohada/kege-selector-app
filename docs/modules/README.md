# Modules

Этот раздел описывает крупные функциональные области репозитория и их ответственность.

## Файлы раздела

- [platform-modules.md](platform-modules.md) — основное Flask-приложение и его модули.
- [side-services.md](side-services.md) — trainer, Telegram-контуры, scraper.
- [scripts-and-tools.md](scripts-and-tools.md) — классификация скриптов и зоны риска.
- [data-and-runtime-artifacts.md](data-and-runtime-artifacts.md) — данные, build/output и runtime-артефакты.

## Как читать этот раздел

- если вы меняете web-функциональность, начинайте с `platform-modules.md`;
- если работаете с интеграциями, смотрите `side-services.md`;
- если нужен служебный script, сначала откройте `scripts-and-tools.md`;
- если вопрос упирается в файлы, экспорты, локальные БД или generated data, смотрите `data-and-runtime-artifacts.md`.
