# Эталонные прототипы заданий ЕГЭ

## Структура каталога

```
reference_prototypes/
├── prototype_schema.json      # JSON Schema — формальное описание формата
├── _template_example.json     # Шаблон-пример (задание №1, системы счисления)
├── README.md                  # Этот файл
└── task_XX/                   # Каталоги по номерам заданий (01–27)
    ├── easy/                  # Эталоны для лёгких задач (difficulty 1–3)
    │   ├── proto_001.json
    │   └── ...
    ├── medium/                # Эталоны для средних задач (difficulty 4–7)
    │   ├── proto_001.json
    │   └── ...
    └── hard/                  # Эталоны для сложных задач (difficulty 8–10)
        ├── proto_001.json
        └── ...
```

## Формат файлов

Каждый `.json` файл в каталоге задания — один эталонный прототип, строго
соответствующий `prototype_schema.json`.

### Обязательные поля

| Поле              | Тип      | Описание                                      |
|-------------------|----------|-----------------------------------------------|
| task_number       | int      | Номер задания ЕГЭ (1–27)                      |
| topic_code        | string   | Код узла знаний (KnowledgeNode.code)           |
| topic_name        | string   | Название темы                                  |
| difficulty_level  | int      | 1–10 (1–3=Easy, 4–7=Medium, 8–10=Hard)        |
| difficulty_label  | string   | "easy" / "medium" / "hard"                     |
| prototype         | object   | Текст задания, формат ввода/вывода             |
| solution          | object   | Пошаговое решение, альт. методы, ошибки        |
| answer            | string   | Правильный ответ                               |

### Рекомендуемые поля

| Поле              | Тип      | Описание                                      |
|-------------------|----------|-----------------------------------------------|
| hint_ladder       | array    | Лестница подсказок (5 уровней)                 |
| tags              | array    | Теги: fipi, kege-2025, math, programming       |
| source            | string   | Источник: fipi, kege.ru, manual, llm-generated |
| meta              | object   | Метаданные: автор, версия, дата                |

## Как добавлять новые прототипы

1. Скопируйте `_template_example.json` в `task_XX/<difficulty>/proto_NNN.json`
2. Заполните все обязательные поля
3. Валидируйте JSON против `prototype_schema.json`
4. Коммитьте

## Использование для обучения LLM

Прототипы используются для:
- **Fine-tuning** тренажёра: модель учится давать подсказки по hint_ladder
- **Генерации новых задач**: модель создаёт вариации по prototype + solution
- **Классификации сложности**: модель учится определять difficulty_level
- **Проверки ответов**: модель использует solution.steps для объяснений
