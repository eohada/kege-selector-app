# GigaChat: где и как дообучить модель подсказок

## Важно: fine-tuning через GigaChat API не существует

**Официальный GigaChat API** (developers.sber.ru) **не предоставляет публичный endpoint для fine-tuning**. В документации есть только:
- генерация ответов (Chat API),
- модели Embeddings для векторного поиска,
- передача файлов в запросе (attachments).

Ссылки:
- [Модели GigaChat](https://developers.sber.ru/docs/ru/gigachat/models/main)
- [API Chat](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat)

---

## Что можно сделать на GigaChat (без fine-tuning)

### Вариант 1: RAG — подсказки из эталонов через Embeddings (рекомендуется)

**Идея:** вместо дообучения модели индексируем наши подсказки (из `train_hints.jsonl` / эталонов) через GigaChat Embeddings. При запросе ученика ищем похожие примеры и подставляем их в prompt как few-shot.

**Шаги:**

1. **Подготовить данные**
   - Уже есть: `exports/train_hints.jsonl` (910 примеров)
   - Формат: `{user: "Задание: ...", assistant: "Подсказка..."}`

2. **Создать индекс**
   - Для каждого примера: `user` → эмбеддинг через `GigaChat.embeddings()` (модель `Embeddings` или `Embeddings-2`)
   - Сохранить в векторную БД (SQLite + sqlite-vec, или ChromaDB, или faiss)
   - Связь: эмбеддинг ↔ `{hint_text, level, task_number}`

3. **При запросе подсказки**
   - Текст запроса + условие задачи → эмбеддинг
   - Поиск top-K похожих примеров (cosine similarity)
   - Подставить в prompt: «Похожие подсказки из эталонов: [примеры]. Дай подсказку в таком же стиле, без готового решения.»

4. **Интеграция**
   - В `build_messages_for_help` или в роуте `/internal/trainer/llm/chat` перед вызовом GigaChat:
     - Получить `task_text`, `hint_level`
     - Запрос к RAG → 2–3 релевантных примера
     - Добавить в system: «Примеры подсказок: …»

**Плюсы:** не нужно обучать модель, работает сразу, использует GigaChat API.  
**Минусы:** нужна реализация индекса и поиска.

---

### Вариант 2: Open-source GigaChat на HuggingFace + локальный fine-tuning

Sber выложил **GigaChat-20B** на HuggingFace — можно дообучить самому.

**Шаги:**

1. **Модель**
   - [GigaChat на HuggingFace](https://huggingface.co/sberbank-ai/GigaChat)
   - Или `GigaChat-20B-A3B` (base/instruct)

2. **Окружение**
   - GPU с достаточным VRAM (20B — желательно 2×A100 или аналог)
   - Или LoRA/QLoRA — меньше VRAM

3. **Скрипт обучения**
   - Формат: `train_hints.jsonl` (уже в формате messages)
   - Инструменты: `transformers`, `peft` (LoRA), `datasets`
   - Пример: [HuggingFace SFT](https://huggingface.co/docs/trl/sft_trainer)

4. **После обучения**
   - Развернуть модель (свой сервер, RunPod, и т.п.)
   - Либо подключить к платформе как отдельный LLM endpoint (если добавить поддержку custom URL)

**Плюсы:** настоящий fine-tuning, модель подстроена под стиль подсказок.  
**Минусы:** нужен GPU, время, инфраструктура.

---

### Вариант 3: Усиленный prompt + знания (уже сделано)

Сейчас в `build_messages_for_help` уже передаётся:
- `hint_ladder` и `common_mistakes` из `trainer_knowledge`
- жёсткий системный промпт «не выдавать решение»

Если `trainer_knowledge` заполнен для всех заданий — модель получает достаточно контекста. Fine-tuning не обязателен для базовой работы.

---

## Практическая рекомендация

1. **Сейчас:** использовать Вариант 3 (уже реализован) + максимально заполнить `trainer_knowledge` и `Tasks.hints` в БД.
2. **Далее:** реализовать RAG (Вариант 1) — индексировать подсказки через Embeddings и подставлять похожие примеры в prompt.
3. **При необходимости:** при наличии GPU — fine-tuning Open-source GigaChat (Вариант 2).

---

## Краткий чек-лист по RAG (Вариант 1) ✅ Реализовано

| # | Действие | Статус |
|---|----------|--------|
| 1 | GigaChat Embeddings в `trainer_app/llm/embeddings_client.py` | ✅ |
| 2 | Скрипт `scripts/build_hints_rag_index.py`: train_hints.jsonl → ChromaDB | ✅ |
| 3 | Функция `retrieve_similar_hints()` в `trainer_app/llm/rag.py` | ✅ |
| 4 | Интеграция в `build_messages_for_help` — примеры в system prompt | ✅ |
| 5 | Протестировать с реальным индексом | ⬜ |

**Запуск:**
1. `python scripts/export_training_data.py --output-dir exports`
2. `python scripts/build_hints_rag_index.py` (нужен GIGACHAT_CREDENTIALS)
3. Индекс сохраняется в `data/rag_hints/`

**Зависимости:** `trainer_app/requirements.txt` — chromadb, gigachat.

---

## Ссылки

- [GigaChat API](https://developers.sber.ru/docs/ru/gigachat/api/overview)
- [GigaChat Embeddings](https://developers.sber.ru/docs/ru/gigachat/models/embeddings)
- [Python SDK GigaChat](https://pypi.org/project/gigachat/)
- [GigaChat на HuggingFace](https://huggingface.co/sberbank-ai) (если есть)
