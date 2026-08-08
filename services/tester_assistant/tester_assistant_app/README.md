# Ассистент Тестировщика BooStudy QA

Кроссплатформенное приложение-инструмент для тестировщиков нашей платформы. Сочетает в себе адаптивный веб-интерфейс и готовую обертку для сборки в десктопное приложение (.EXE для Windows).

## Структура проекта

* `index.html` — основное Single Page Application на **React + Tailwind CSS**.
* `electron/` — файлы обертки Electron для сборки десктопной версии:
  * `main.js` — конфигурация окна и запуск Electron.
  * `package.json` — зависимости и скрипты сборки.
* `gdrive_service.py` — пример бэкенд-сервиса на Flask для сохранения скриншотов на ваш Google Диск по API.

---

## Как запустить веб-версию (Web / Mobile)

Самый быстрый способ — просто дважды кликнуть по файлу [index.html](file:///e:/projects/kege_selector_app_current/tester_assistant_app/index.html) на вашем компьютере. Приложение откроется прямо в браузере и будет полностью работать на встроенных mock-данных.

Также вы можете запустить его через локальный сервер:
```bash
python -m http.server 8000
```
После этого откройте в браузере: `http://localhost:8000/tester_assistant_app/index.html`

Для проверки мобильной адаптивности откройте режим разработчика в браузере (`F12`) и переключитесь в режим адаптивного просмотра (мобильная верстка).

---

## Как запустить и собрать Desktop-версию (.EXE)

Для сборки десктопного приложения вам понадобятся установленный **Node.js** и **NPM**.

1. Откройте консоль и перейдите в папку `electron`:
   ```bash
   cd tester_assistant_app/electron
   ```
2. Установите зависимости:
   ```bash
   npm install
   ```
3. Запустите приложение в режиме разработки:
   ```bash
   npm start
   ```
4. Соберите дистрибутив (.EXE для Windows):
   ```bash
   npm run package-win
   ```
   Собранное приложение появится в папке `tester_assistant_app/dist/`.

---

## Интеграция с Google Drive

В приложении симулируется процесс загрузки скриншотов багов на Google Диск. Для реальной отправки файлов вы можете использовать скрипт `gdrive_service.py`.

### Шаги для подключения реального Google Диска:
1. Зайдите в **Google Cloud Console**.
2. Создайте проект, включите **Google Drive API**.
3. Создайте **Service Account** (Сервисный аккаунт) во вкладке IAM & Admin -> Service Accounts.
4. Создайте для него JSON-ключ, скачайте его и сохраните в корне проекта под именем `google_creds.json`.
5. Скопируйте email этого сервисного аккаунта (будет похож на `your-account@project.iam.gserviceaccount.com`).
6. Создайте обычную папку на вашем Google Диске и предоставьте этому email-адресу доступ на редактирование.
7. Пропишите ID этой папки в переменную `GOOGLE_DRIVE_FOLDER_ID` внутри `gdrive_service.py`.
8. Установите зависимости Python и запустите бэкенд:
   ```bash
   pip install flask google-api-python-client google-auth-httplib2 google-auth-oauthlib
   python gdrive_service.py
   ```
