## trainer_app (Streamlit)

Отдельный сервис-тренажёр, который встраивается в платформу через iframe и общается с Flask по `/internal/trainer/*`.

### Локальный запуск

1) Установи зависимости:

```bash
pip install -r trainer_app/requirements.txt
```

2) Задай переменные окружения:

- `PLATFORM_BASE_URL` — URL платформы (например `http://127.0.0.1:5000`)
- (опционально) `TRAINER_LLM_PROVIDER=groq|gemini`
- `GROQ_API_KEY` или `GEMINI_API_KEY`
- (опционально) `TRAINER_ENABLE_RUNNER=true` чтобы включить тест-раннер

3) Запусти:

```bash
streamlit run trainer_app/app.py
```

### Встраивание через платформу

В платформе должны быть заданы:

- `TRAINER_URL` — URL Streamlit сервиса (например `http://127.0.0.1:8501`)
- `TRAINER_SHARED_SECRET` — общий секрет для подписи токена (минимум 16 символов)

После этого открой `/trainer` в платформе — там будет iframe.

