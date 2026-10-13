# -*- coding: utf-8 -*-
"""
Модуль 1: Основы синтаксиса и первые шаги в Python (Темы 101-104).
Построен строго по педагогическому принципу «от простого к сложному, без забегания вперёд»:
- 101: Первая программа и вывод: функция print()
- 102: Переменные и базовая арифметика: Python как калькулятор (+, -, *, **)
- 103: Деление в Python: обычное (/), целочисленное (//) и остаток (%)
- 104: Типы данных (int, float, str, bool) и преобразование типов

Каждая тема содержит 5 подробных блоков:
1) Зачем это нужно в ЕГЭ (с точным списком номеров: 2, 5, 6, 8, 9, 12, 13, 14, 15, 16, 17, 19-21, 22, 23, 24, 25, 26, 27)
2) Синтаксис и наглядная визуальная схема
3) Примеры кода и результат
4) Ловушки и частые ошибки на экзамене
5) Микро-проверки (Checkpoints с чистым многострочным кодом)
"""

MOD1_TOPICS = {
    101: {
        "title": "Что такое программа и синтаксис Python: вывод через print()",
        "description": "Что такое программа, вывод чисел и текста через print, регистр букв и оформление первой строчки кода.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В ЕГЭ по информатике Python — это главное оружие для получения высоких баллов (80–100).
С помощью кода на Python можно решить или надёжно перепроверить **до 18–20 заданий из 27**:
номера **2, 5, 6, 8, 9, 12, 13, 14, 15, 16, 17, 19–21, 22, 23, 24, 25, 26 и 27**.

Любая написанная вами программа на экзамене должна выдать ответ на экран, чтобы вы могли перенести его в поле для ответа на компьютере. Главная команда для показа ответа — это встроенная функция `print()`.

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-target"></i><span>Задачи ЕГЭ</span>
    </div>
    <div class="my-2">
      <div class="text-2xl font-black text-slate-900">18+ из 27</div>
      <div class="text-xs font-semibold text-slate-500">решаются кодом на Python</div>
    </div>
    <div class="flex flex-wrap gap-1 mt-1">
      <span class="px-1.5 py-0.5 rounded-md bg-indigo-50 border border-indigo-200 text-[10px] font-black text-indigo-700">№2</span>
      <span class="px-1.5 py-0.5 rounded-md bg-indigo-50 border border-indigo-200 text-[10px] font-black text-indigo-700">№5</span>
      <span class="px-1.5 py-0.5 rounded-md bg-indigo-50 border border-indigo-200 text-[10px] font-black text-indigo-700">№8</span>
      <span class="px-1.5 py-0.5 rounded-md bg-indigo-50 border border-indigo-200 text-[10px] font-black text-indigo-700">№14</span>
      <span class="px-1.5 py-0.5 rounded-md bg-indigo-50 border border-indigo-200 text-[10px] font-black text-indigo-700">№24–27</span>
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-chart-line-up"></i><span>Главная роль</span>
    </div>
    <div class="my-2">
      <div class="text-2xl font-black text-emerald-700">Функция print()</div>
      <div class="text-xs font-semibold text-slate-500">выводит ответ на экран</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      Без неё результат невидим
    </div>
  </div>
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-rose-600 flex items-center gap-1.5">
      <i class="ph-bold ph-shield-warning"></i><span>Точность синтаксиса</span>
    </div>
    <div class="my-2">
      <div class="text-2xl font-black text-rose-700">0 баллов</div>
      <div class="text-xs font-semibold text-slate-500">при синтаксической ошибке</div>
    </div>
    <div class="text-[11px] font-bold text-rose-800 bg-rose-50 rounded-lg p-1.5 border border-rose-200">
      Регистр и скобки критичны
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
**Программа** — это набор инструкций, которые компьютер выполняет по очереди, сверху вниз.

Команда `print(...)` сообщает Python: *«Выведи то, что указано внутри круглых скобок, на экран»*.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-terminal"></i></span>
    <span>Как работает вызов print(): анатомия команды</span>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200 shadow-[0_2px_0_#C7D2FE]">
      <div class="text-xs font-black text-indigo-600 font-mono">print(42)</div>
      <div class="text-xs font-bold text-slate-700 mt-1">Вывод числа</div>
      <p class="text-[11px] text-slate-500 mt-1">Числа пишутся просто так, без кавычек.</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-purple-200 shadow-[0_2px_0_#E9D5FF]">
      <div class="text-xs font-black text-purple-600 font-mono">print("Ответ")</div>
      <div class="text-xs font-bold text-slate-700 mt-1">Вывод текста</div>
      <p class="text-[11px] text-slate-500 mt-1">Любой текст обязательно оборачивается в кавычки (одинарные или двойные).</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-emerald-200 shadow-[0_2px_0_#A7F3D0]">
      <div class="text-xs font-black text-emerald-600 font-mono">print("Ответ:", 42)</div>
      <div class="text-xs font-bold text-slate-700 mt-1">Несколько значений</div>
      <p class="text-[11px] text-slate-500 mt-1">Разделяются запятой. По умолчанию Python ставит между ними пробел.</p>
    </div>
  </div>
</div>

### Модель памяти и выполнение инструкций
Программа выполняется строго сверху вниз, строчка за строчкой. В оперативной памяти компьютера создаются значения (числа, строки текста), а функции вроде `print()` считывают их и отправляют в окно терминала. Если в какой-то строчке допущена синтаксическая ошибка, программа остановится ровно на этом месте, не выполнив последующие команды.

### Базовые правила языка Python
1. **Регистр символов имеет решающее значение:** в Python все стандартные команды пишутся **строчными (маленькими)** буквами. `print` — работает, а `Print` или `PRINT` вызовут ошибку `NameError`.
2. **Парные скобки и кавычки:** если открыли круглую скобку `(` или кавычку `"`, её обязательно нужно закрыть в конце.
3. **Каждый вызов `print()` по умолчанию начинает новую строку:** если написать два `print` друг за другом, второй результат появится на строчке ниже.

## Примеры кода и результат
Попробуйте запустить эти простые примеры и посмотреть, как формируется вывод:

[CODE_RUNNER title="Первые команды вывода" input="" output="Привет, ЕГЭ!\\n100\\nКоличество решений: 42"]
# 1. Выводим текст
print("Привет, ЕГЭ!")

# 2. Выводим число
print(100)

# 3. Выводим поясняющий текст и число через запятую
print("Количество решений:", 42)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Заглавная буква в print</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если написать Print() с большой буквы, Python не поймет команду.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">Print("Привет") # Ошибка</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print("Привет") # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытые кавычки у текста</div>
      <p class="text-xs text-slate-600 leading-relaxed">Без кавычек Python сочтёт текст именем переменной и выдаст ошибку NameError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">print(Привет)    # Ошибка</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print("Привет")  # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Русские буквы в коде</div>
      <p class="text-xs text-slate-600 leading-relaxed">Русская «р» или «с» визуально похожа на латинскую, но это разные символы.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">рrint(10) # русская «р»</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print(10) # латинская «p»</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p101-q1" question="Какая строчка кода вызовет ошибку при запуске?" options="print(2026)|Print('ЕГЭ')|print('Ответ:', 42)|print('Привет')" answer="Print('ЕГЭ')" explanation="Команды Python чувствительны к регистру: Print с большой буквы вызовет NameError, правильно писать print маленькими буквами." hint="Вспомните, как Python относится к регистру букв: чувствителен ли он к заглавным и строчным буквам в именах стандартных команд?"]
[CHECKPOINT key="p101-q2" question="Что выведет следующий фрагмент программы?

print(10)
print(20)" options="10 20 в одну строку через пробел|Число 10, а на следующей строке число 20|1020 слитно в одну строку|Число 30" answer="Число 10, а на следующей строке число 20" explanation="Каждый вызов функции print() по умолчанию завершается переводом строки, поэтому 20 выведется на новой строке." hint="Каждый отдельный вызов print() по умолчанию переводит курсор на новую строчку."]
"""
    },

    102: {
        "title": "Переменные и базовая арифметика: Python как калькулятор",
        "description": "Создание переменных, оператор присваивания =, базовая арифметика (+, -, *, **) и степени двойки в ЕГЭ.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В компьютерном ЕГЭ постоянные вычисления — это основа всех задач:
- **В задании №5** алгоритм производит вычисления над числом (удваивает, прибавляет, возводит в степень).
- **В задании №14** анализируются гигантские выражения со степенями: например 4²⁰²⁶ − 2¹⁰⁰⁰ + 15.
- **В заданиях №16 и №23** программы моделируют вычисления и шаги исполнителя.

Вам не нужно считать это на черновике: Python работает как сверхмощный и безошибочный калькулятор.

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-calculator"></i><span>Умный калькулятор</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">Python считает всё</div>
      <div class="text-xs font-semibold text-slate-500">без переполнения памяти</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      2 ** 100 посчитает мгновенно
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-brackets-curly"></i><span>Переменные</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">Именованные коробки</div>
      <div class="text-xs font-semibold text-slate-500">сохраняют промежуточный ответ</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      x = a + b сохраняет результат в x
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-amber-700 flex items-center gap-1.5">
      <i class="ph-bold ph-chart-bar"></i><span>Степени двойки</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-amber-800">Оператор **</div>
      <div class="text-xs font-semibold text-slate-500">возведение в степень</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-amber-900 bg-amber-50 rounded-lg p-1.5 border border-amber-200">
      2 ** 10 = 1024
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
### Что такое переменная и оператор присваивания `=`
Переменная — это имя, под которым в памяти компьютера хранится значение.
Знак `=` в программировании означает **присваивание**, а не знак математического равенства:
- Сначала компьютер вычисляет всё выражение, стоящее **справа** от `=`.
- Затем получившийся результат он сохраняет в переменную **слева** от `=`.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-arrows-left-right"></i></span>
    <span>Как работает присваивание: a = a + 5</span>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
    <div class="p-3.5 rounded-xl bg-white border-2 border-slate-200">
      <span class="font-bold text-slate-400">Шаг 1: Было значение</span>
      <div class="font-mono font-black text-indigo-700 text-base mt-1">a = 10</div>
      <p class="text-slate-500 mt-1">В переменной a лежит число 10.</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200">
      <span class="font-bold text-indigo-600">Шаг 2: Вычисляем справа</span>
      <div class="font-mono font-black text-indigo-700 text-base mt-1">a + 5 -> 15</div>
      <p class="text-slate-500 mt-1">Берём старое значение (10), прибавляем 5, получаем 15.</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-emerald-200">
      <span class="font-bold text-emerald-600">Шаг 3: Сохраняем слева</span>
      <div class="font-mono font-black text-emerald-700 text-base mt-1">a = 15</div>
      <p class="text-slate-500 mt-1">Новое значение 15 перезаписывает старое значение переменной.</p>
    </div>
  </div>
</div>

### Базовые арифметические операторы
| Оператор | Название | Пример | Результат | Пояснение для ЕГЭ |
|---|---|---|---|---|
| `+` | Сложение | `15 + 7` | `22` | Обычное математическое сложение |
| `-` | Вычитание | `15 - 7` | `8` | Обычное математическое вычитание |
| `*` | Умножение | `6 * 7` | `42` | Знак умножения — всегда звёздочка `*` |
| `**` | Возведение в степень | `2 ** 10` | `1024` | Два знака умножения подряд означают степень (2¹⁰) |
| `(...)` | Круглые скобки | `(2 + 3) * 4` | `20` | Меняют порядок действий, как в школьной математике |

## Примеры кода и результат
Посмотрите, как переменные хранят результаты и помогают решать практические задачи:

[CODE_RUNNER title="Базовая арифметика и переменные" input="" output="Сумма: 30\\nПроизведение: 200\\n2 в 10 степени: 1024\\nРезультат сложного выражения: 104"]
a = 10
b = 20

# Вычисляем сумму и произведение
sum_val = a + b
mult_val = a * b

print("Сумма:", sum_val)
print("Произведение:", mult_val)

# Возводим 2 в 10-ю степень (1 Кбайт = 1024 байт в задании №7 и №11)
power_val = 2 ** 10
print("2 в 10 степени:", power_val)

# Порядок действий со скобками
res = (a + 3) * 8
print("Результат сложного выражения:", res)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Пропуск знака умножения</div>
      <p class="text-xs text-slate-600 leading-relaxed">В математике пишут 2x. В Python пропуск знака * вызовет SyntaxError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">ans = 2x     # Ошибка!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">ans = 2 * x # Правильно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Степень — это **, а не ^</div>
      <p class="text-xs text-slate-600 leading-relaxed">Знак ^ в Python — это побитовое исключающее ИЛИ (XOR), а не степень!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">2 ^ 10   # Даст 8, а не 1024!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">2 ** 10  # Даст 1024</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытые скобки в приоритете</div>
      <p class="text-xs text-slate-600 leading-relaxed">Умножение и степень выполняются раньше сложения. Используйте скобки.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">2 + 3 * 4   # Будет 14</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">(2 + 3) * 4 # Будет 20</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p102-q1" question="Какое значение будет выведено на экран в результате выполнения программы?

x = 5
x = x + 3
x = x * 2
print(x)" options="10|16|11|13" answer="16" explanation="Сначала x = 5. Затем x = 5 + 3 = 8. Затем x = 8 * 2 = 16. На экран выведется 16." hint="Пройдите по шагам: сначала к 5 прибавьте 3, а затем полученный результат умножьте на 2."]
[CHECKPOINT key="p102-q2" question="Как на языке Python правильно записать математическое выражение 3 в степени 4?" options="3 ^ 4|3 * 4|3 ** 4|power(3, 4)" answer="3 ** 4" explanation="В Python для возведения в степень используется оператор из двух звёздочек **. Символ ^ означает побитовую операцию XOR." hint="Вспомните оператор возведения в степень: в Python он пишется как две звёздочки подряд."]
"""
    },

    103: {
        "title": "Деление в Python: обычное (/), целочисленное (//) и остаток (%)",
        "description": "Три вида деления в Python: обычное деление с точкой, деление нацело // и остаток %, ключевые для заданий 5, 14 и 25.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Деление — это самый важный математический инструмент в ЕГЭ:
- **В задании №5** алгоритм анализирует чётность числа (проверка `n % 2 == 0`) и делимость на 3.
- **В задании №14** перевод числа в любую систему счисления (двоичную, троичную, шестнадцатеричную) делается через деление столбиком: остаток `%` даёт последнюю цифру, а целочисленное деление `//` убирает её.
- **В задании №25** поиск делителей числа строится на проверке делимости без остатка: `n % d == 0`.

В Python есть **три разных оператора деления**, и каждый решает свою задачу.

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-divide"></i><span>Обычное деление: /</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">Всегда дробный ответ</div>
      <div class="text-xs font-semibold text-slate-500">даже если делится нацело</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      4 / 2 = 2.0 (число с точкой!)
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-arrows-split"></i><span>Деление нацело: //</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">Сколько целых раз</div>
      <div class="text-xs font-semibold text-slate-500">делитель поместился в число</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      17 // 5 = 3
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-amber-700 flex items-center gap-1.5">
      <i class="ph-bold ph-percent"></i><span>Остаток: %</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-amber-800">Что осталось после деления</div>
      <div class="text-xs font-semibold text-slate-500">основа перевода систем счисления</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-amber-900 bg-amber-50 rounded-lg p-1.5 border border-amber-200">
      17 % 5 = 2
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
Представьте школьное деление с уголком: делим **17 на 5**.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-math-operations"></i></span>
    <span>Деление уголком: 17 делим на 5</span>
  </div>
  <div class="flex flex-col sm:flex-row items-center justify-around gap-4 py-2 font-mono">
    <div class="p-4 rounded-2xl bg-white border-2 border-slate-200 text-center min-w-[120px]">
      <span class="text-[11px] font-sans font-bold text-slate-400 block mb-1">Делимое</span>
      <span class="text-2xl font-black text-slate-800">17</span>
    </div>
    <div class="text-xl font-black text-slate-400">:</div>
    <div class="p-4 rounded-2xl bg-white border-2 border-slate-200 text-center min-w-[120px]">
      <span class="text-[11px] font-sans font-bold text-slate-400 block mb-1">Делитель</span>
      <span class="text-2xl font-black text-slate-800">5</span>
    </div>
    <div class="text-xl font-black text-slate-400">=</div>
    <div class="p-4 rounded-2xl bg-white border-2 border-emerald-300 text-center min-w-[140px] shadow-[0_2px_0_#A7F3D0]">
      <span class="text-[11px] font-sans font-bold text-emerald-600 block mb-1">Целая часть (//)</span>
      <span class="text-2xl font-black text-emerald-700">3</span>
    </div>
    <div class="text-sm font-sans font-bold text-slate-400">и в остатке</div>
    <div class="p-4 rounded-2xl bg-white border-2 border-amber-300 text-center min-w-[140px] shadow-[0_2px_0_#FDE68A]">
      <span class="text-[11px] font-sans font-bold text-amber-600 block mb-1">Остаток (%)</span>
      <span class="text-2xl font-black text-amber-700">2</span>
    </div>
  </div>
</div>

### Главные свойства оператора остатка `%`
1. **Проверка на чётность:** если `x % 2 == 0`, то число чётное; если `x % 2 == 1`, то нечётное.
2. **Проверка делимости:** если `x % 3 == 0`, число делится на 3 без остатка.
3. **Последняя цифра числа:** 
   - В десятичной системе: `x % 10` даёт последнюю цифру числа (например, `247 % 10 = 7`).
   - В двоичной системе: `x % 2` даёт последнюю двоичную цифру.
4. **Удаление последней цифры:** `x // 10` отрезает последнюю цифру (например, `247 // 10 = 24`).

## Примеры кода и результат
Посмотрите, как деление работает на практике:

[CODE_RUNNER title="Три вида деления в Python" input="" output="Обычное деление 7 / 2 = 3.5\\nОбычное деление 4 / 2 = 2.0\\nЦелочисленное деление 17 // 5 = 3\\nОстаток от деления 17 % 5 = 2\\nПоследняя цифра 2026 % 10 = 6\\nЧисло без последней цифры 2026 // 10 = 202"]
# 1. Обычное деление (всегда дает дробное число с точкой)
print("Обычное деление 7 / 2 =", 7 / 2)
print("Обычное деление 4 / 2 =", 4 / 2)

# 2. Целочисленное деление (только целая часть)
print("Целочисленное деление 17 // 5 =", 17 // 5)

# 3. Остаток от деления
print("Остаток от деления 17 % 5 =", 17 % 5)

# 4. Работа с цифрами числа 2026
n = 2026
last_digit = n % 10
without_last = n // 10

print("Последняя цифра 2026 % 10 =", last_digit)
print("Число без последней цифры 2026 // 10 =", without_last)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Деление на ноль</div>
      <p class="text-xs text-slate-600 leading-relaxed">В Python деление на 0 (хоть /, хоть //, хоть %) вызовет фатальную ошибку ZeroDivisionError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">10 // 0 # ZeroDivisionError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">10 // 2 # 5</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Обычное деление дает float</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если в задаче требуется целое число, используйте //, иначе ответ выведется как 10.0.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">10 / 2  # 5.0 (дробь)</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">10 // 2 # 5 (целое число)</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Путаница // и %</div>
      <p class="text-xs text-slate-600 leading-relaxed">Запомните: // — это целая часть, а % — это то, что осталось (остаток).</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">14 // 4 = 3 (целое)</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">14 % 4 = 2 (остаток)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p103-q1" question="Чему равны результаты вычислений 19 // 4 и 19 % 4 в Python?" options="3 и 4|4 и 3|4.75 и 3|4 и 0" answer="4 и 3" explanation="19 делим на 4: делитель 4 помещается 4 раза (4 * 4 = 16), значит 19 // 4 = 4. Остаток: 19 - 16 = 3, значит 19 % 4 = 3." hint="Вспомните школьное деление с остатком: сколько целых четвёрок помещается в 19 (это //), и сколько остаётся в остатке (это %) ?"]
[CHECKPOINT key="p103-q2" question="Что выведет следующий фрагмент программы?

a = 20
b = 5
print(a / b)" options="4|5|4.0|Ошибка" answer="4.0" explanation="Обычное деление через один слэш / ВСЕГДА возвращает вещественное число (с плавающей точкой), поэтому результат будет 4.0, а не 4." hint="Обратите внимание на знак /: обычное деление в Python ВСЕГДА возвращает дробное число с точкой (тип float), даже если делится без остатка."]
"""
    },

    104: {
        "title": "Типы данных (int, float, str, bool) и преобразование типов",
        "description": "Четыре главных типа данных в ЕГЭ: целые int, дробные float, строки str, логические bool и явное приведение типов.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Компьютер должен точно понимать, с какими данными он работает. Если вы сложите числа `5 + 5`, получится `10`. Но если вы случайно сложите строки `"5" + "5"`, получится текст `"55"`.

Понимание типов данных спасает от самых обидных ошибок в ЕГЭ:
- **В задании №12** работа идёт со строками текста (`str`), где заменяются символы.
- **В задании №14** строки цифр переводятся в целые числа (`int`) через `int("1011", 2)`.
- **В задании №2** логические переменные принимают только значения истины или лжи (`bool`: `True` или `False`).
- **В задании №24** длинная текстовая цепочка анализируется посимвольно.

<div class="my-6 grid grid-cols-1 sm:grid-cols-4 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-indigo-600 font-mono">int</span>
      <div class="text-base font-black text-slate-800 mt-1">Целые числа</div>
      <p class="text-xs text-slate-500 mt-1">5, -12, 0, 1000000</p>
    </div>
    <div class="text-[11px] font-bold text-indigo-700 bg-indigo-50 rounded-lg p-1.5 mt-2 border border-indigo-200">
      Бесконечная точность
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-emerald-600 font-mono">float</span>
      <div class="text-base font-black text-slate-800 mt-1">Дробные числа</div>
      <p class="text-xs text-slate-500 mt-1">3.14, 0.5, -2.8, 4.0</p>
    </div>
    <div class="text-[11px] font-bold text-emerald-700 bg-emerald-50 rounded-lg p-1.5 mt-2 border border-emerald-200">
      Всегда с точкой
    </div>
  </div>
  <div class="rounded-2xl border-2 border-purple-200 bg-white p-4 shadow-[0_3px_0_#E9D5FF] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-purple-600 font-mono">str</span>
      <div class="text-base font-black text-slate-800 mt-1">Текстовые строки</div>
      <p class="text-xs text-slate-500 mt-1">"ЕГЭ", "123", "a"</p>
    </div>
    <div class="text-[11px] font-bold text-purple-700 bg-purple-50 rounded-lg p-1.5 mt-2 border border-purple-200">
      Всегда в кавычках
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-amber-600 font-mono">bool</span>
      <div class="text-base font-black text-slate-800 mt-1">Логический тип</div>
      <p class="text-xs text-slate-500 mt-1">True (да) или False (нет)</p>
    </div>
    <div class="text-[11px] font-bold text-amber-700 bg-amber-50 rounded-lg p-1.5 mt-2 border border-amber-200">
      Результат условий
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
### Четыре главных типа в Python
1. **`int` (integer, целое число):** не имеет дробной части. В Python у типа `int` **нет ограничения по размеру**: можно возвести 4²⁰²⁶ в степень, и Python сохранит все тысячи цифр без ошибок и потерь!
2. **`float` (вещественное, дробное число):** записывается с точкой (`3.14`). Обычное деление `/` всегда возвращает `float`.
3. **`str` (string, строка текста):** последовательность символов в кавычках. При сложении двух строк (`"ЕГЭ" + "2026"`) происходит склеивание: `"ЕГЭ2026"`.
4. **`bool` (boolean, логическое значение):** может принимать ровно два значения: `True` (истина, 1) или `False` (ложь, 0). Пишется с заглавной буквы!

### Преобразование типов (Type Casting)
Вы можете легко превращать один тип данных в другой с помощью одноимённых функций:
- `int("123")` превращает строку `"123"` в число `123`.
- `int("1011", 2)` переводит двоичную строку `"1011"` в десятичное число `11` (супер-приём для задания №14!).
- `str(42)` превращает число `42` в строку `"42"`.
- `float(5)` превращает целое число `5` в дробное `5.0`.
- `bool(1)` возвращает `True`, а `bool(0)` возвращает `False`.

### Как устроен перевод из систем счисления: математика и Python
В позиционных системах счисления значение цифры зависит от её позиции (разряда). Разряды нумеруются **справа налево, начиная с нуля**.
Каждый разряд имеет свой вес, равный основанию системы в соответствующей степени.

Для двоичной системы счисления (основание 2):
- Разряд 0 (крайний правый): вес 2⁰ = 1
- Разряд 1: вес 2¹ = 2
- Разряд 2: вес 2² = 4
- Разряд 3: вес 2³ = 8

Возьмём двоичное число `'1010'`:
<div class="my-4 p-4 rounded-2xl bg-indigo-50/70 border-2 border-indigo-200/80 text-center text-sm sm:text-base font-bold text-indigo-950 font-mono shadow-xs">
  1 · 2³ + 0 · 2² + 1 · 2¹ + 0 · 2⁰ = 1 · 8 + 0 · 4 + 1 · 2 + 0 · 1 = 8 + 2 = 10
</div>

Функция `int("1010", 2)` в точности выполняет этот расчёт автоматически!
Первый аргумент — это строка с записью числа, второй аргумент — основание системы счисления (2 для двоичной, 8 для восьмеричной, 16 для шестнадцатеричной).

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-swap"></i></span>
    <span>Примеры преобразования типов</span>
  </div>
  <div class="space-y-2 text-xs font-mono">
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">int("25") + 5</span>
      <span class="text-indigo-600 font-black">-> 30 (число)</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">str(25) + "5"</span>
      <span class="text-purple-600 font-black">-> "255" (строка)</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">int("1010", 2)</span>
      <span class="text-emerald-600 font-black">-> 10 (1*8 + 0*4 + 1*2 + 0*1)</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Попробуйте поработать с разными типами данных:

[CODE_RUNNER title="Типы данных и приведение типов" input="" output="Сложение чисел: 15\\nСклеивание строк: 105\\nДвоичное 1010 в десятичной: 10\\nТип переменной flag: <class 'bool'>"]
# 1. Разница между числами и строками
x = 10
y = 5
print("Сложение чисел:", x + y)

s1 = "10"
s2 = "5"
print("Склеивание строк:", s1 + s2)

# 2. Быстрый перевод из системы счисления для задания №14
binary_str = "1010"
decimal_num = int(binary_str, 2)
print("Двоичное 1010 в десятичной:", decimal_num)

# 3. Логический тип bool
flag = True
print("Тип переменной flag:", type(flag))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Сложение числа и строки</div>
      <p class="text-xs text-slate-600 leading-relaxed">В Python нельзя сложить число и текст: 5 + "10" вызовет ошибку TypeError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">ans = 5 + "10"   # TypeError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">ans = 5 + int("10") # 15</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">True и False с маленькой буквы</div>
      <p class="text-xs text-slate-600 leading-relaxed">В Python булевы константы пишутся строго с заглавной: True и False.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">flag = true   # NameError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">flag = True   # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Дробь внутри int()</div>
      <p class="text-xs text-slate-600 leading-relaxed">Вызов int("3.14") со строкой-дробью вызовет ValueError. Сначала float("3.14").</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">int("3.14")   # ValueError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">float("3.14") # 3.14</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p104-q1" question="Что выведет следующий фрагмент программы?

a = '20'
b = '26'
print(a + b)" options="46 (число)|'2026' (строка)|Ошибка TypeError|'20 26'" answer="'2026' (строка)" explanation="Переменные a и b содержат строки текста (в кавычках). Оператор + для строк выполняет конкатенацию (склеивание), поэтому получится '2026'." hint="Обратите внимание на кавычки вокруг значений: переменные хранят текст, а не числа. Что делает оператор + со строками текста?"]
[CHECKPOINT key="p104-q2" question="Какое десятичное число вернёт выражение int('1010', 2)?" options="8|10|1010|12" answer="10" explanation="Функция int('1010', 2) переводит двоичное число в десятичную систему: 1*8 + 0*4 + 1*2 + 0*1 = 10." hint="Разложите двоичное число 1010 по разрядам справа налево: 1*8 + 0*4 + 1*2 + 0*1. Чему равна сумма этих произведений?"]
"""
    }
}
