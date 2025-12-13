# Реализация расписания - техническая документация

## Текущая реализация (финальная версия)

### Основные параметры

1. **Шаг слота**: `slot_minutes = 60` (только часовые слоты, xx:00)
2. **Визуальная высота слота**: `64px` (2 × 32px базовой единицы)
3. **Количество слотов**: `24` (от 00:00 до 23:00)
4. **Общая высота таблицы**: `1536px` (24 × 64px)

### Расчет позиций уроков

В `app.py` (строки 929-946):

```python
slot_height_px = 32  # высота базовой единицы в пикселях
visual_slot_height_px = slot_height_px * 2  # визуальная высота одного часового слота (64px)

# Расчет позиции сверху
offset_slots = start_minutes / slot_minutes  # перевод смещения в слоты (один слот = 60 минут)
event['top_px'] = offset_slots * visual_slot_height_px  # позиция сверху в пикселях (один слот = 64px)

# Расчет высоты карточки
duration_slots = duration_minutes / slot_minutes  # перевод длительности в слоты
event['height_px'] = max(duration_slots * visual_slot_height_px - 4, visual_slot_height_px * 0.75)  # высота карточки
```

### CSS стили

В `templates/schedule.html`:

```css
.time-cell { 
    height: calc(var(--slot-height) * 2);  /* 64px */
    min-height: calc(var(--slot-height) * 2);
}

.day-cell .slot-clickable { 
    height: calc(var(--slot-height) * 2);  /* 64px */
}

.day-cell { 
    background-image: repeating-linear-gradient(
        to bottom, 
        transparent 0, 
        transparent calc(var(--slot-height) * 2 - 1px), 
        rgba(100, 116, 139, 0.15) calc(var(--slot-height) * 2 - 1px), 
        rgba(100, 116, 139, 0.15) calc(var(--slot-height) * 2)
    );
}
```

### JavaScript расчет высоты

```javascript
const totalSlots = 24;  // количество часовых слотов
const slotHeight = 32;  // базовая единица
const totalHeight = totalSlots * slotHeight * 2;  // 24 × 32 × 2 = 1536px
```

### Создание уроков

- Можно создавать уроки только на целые часы (xx:00)
- Минимальная длительность: 60 минут
- Шаг длительности: 60 минут

### Важные моменты

1. **Не изменять размеры слотов** - они специально настроены для правильного отображения информации в карточках уроков
2. **Расчет позиций** использует `visual_slot_height_px = 64px`, а не базовый `slot_height_px = 32px`
3. **Последняя ячейка времени (23:00)** занимает полный слот (64px), как и остальные

## История изменений

- Изначально были слоты по 30 минут (xx:00 и xx:30)
- Изменено на часовые слоты (только xx:00) для упрощения и решения проблемы с обрезанием
- Размеры слотов сохранены (64px) для правильного отображения информации

