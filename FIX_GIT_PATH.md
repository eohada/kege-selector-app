# Исправление проблемы с Git в PowerShell

## Проблема
Git установлен, но не распознается в PowerShell (`git : Имя "git" не распознано...`)

## Решение

### Вариант 1: Временное решение (для текущей сессии)

Добавь Git в PATH для текущей сессии PowerShell:

```powershell
$env:PATH += ";C:\Program Files\Git\bin"
```

Затем проверь:
```powershell
git --version
```

### Вариант 2: Постоянное решение (рекомендуется)

Добавь Git в системный PATH:

1. Нажми `Win + R`, введи `sysdm.cpl` и нажми Enter
2. Перейди на вкладку **"Дополнительно"**
3. Нажми **"Переменные среды"**
4. В разделе **"Системные переменные"** найди переменную `Path`
5. Нажми **"Изменить"**
6. Нажми **"Создать"**
7. Добавь путь: `C:\Program Files\Git\bin`
8. Нажми **"ОК"** во всех окнах
9. **Перезапусти PowerShell** (закрой и открой заново)

### Вариант 3: Использование Git Bash

Если Git установлен, используй **Git Bash** вместо PowerShell:

1. Найди "Git Bash" в меню Пуск
2. Открой Git Bash
3. Перейди в папку проекта:
   ```bash
   cd /d/VSCode/kege_selector_app
   ```
4. Выполняй команды Git как обычно

### Вариант 4: Использование полного пути

Можно использовать полный путь к git.exe:

```powershell
& "C:\Program Files\Git\bin\git.exe" --version
& "C:\Program Files\Git\bin\git.exe" status
```

## Проверка установки Git

Проверь, где установлен Git:

```powershell
Test-Path "C:\Program Files\Git\bin\git.exe"
Test-Path "C:\Program Files (x86)\Git\bin\git.exe"
```

Если оба возвращают `False`, Git не установлен. Скачай и установи с [git-scm.com](https://git-scm.com/download/win)

## После исправления

После того как Git заработает, выполни:

```powershell
cd D:\VSCode\kege_selector_app
git init
git add .
git commit -m "Initial commit"
```

Затем следуй инструкции из `GITHUB_SETUP.md` для загрузки на GitHub.

