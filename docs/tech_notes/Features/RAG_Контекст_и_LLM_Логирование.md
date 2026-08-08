---
status: untouched
domain: AI Тренажер
type: read-only
---
# RAG Контекст и LLM Логирование

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Сессия_AI_Тренажера]]

## 💻 Текущий бэкенд
- **Роуты:** `/trainer/logs`, `/api/v1/trainer/embeddings` (Файл: `app/trainer/routes.py`, `trainer_app/llm/rag.py`)
- **Таблицы БД:** `trainer_llm_logs`
- **Связанные макеты:** `templates/trainer/logs.html`

## 📝 План интеграции
Мониторинг расхода токенов LLM, точности RAG-выборки конспектов и качества ответов ассистента.
