## Tailwind Standalone CLI (Windows)

Проект использует локально собранный `static/dist/boostudy.css`.

Чтобы **не тянуть Node.js/npm в репозиторий**, используем standalone-бинарник Tailwind.

### Быстрая установка

Скачай бинарник (Tailwind v3.x) в `tools/tailwindcss/tailwindcss.exe` командой:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/get_tailwind.ps1
```

### Сборка CSS

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1
```

