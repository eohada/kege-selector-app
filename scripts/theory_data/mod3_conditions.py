# -*- coding: utf-8 -*-
"""
Модуль 3: Условные конструкции и логика (Темы 109-112).
Полная переработка без опережающих ссылок на циклы и списки.
"""

MOD3_TOPICS = {
    109: {
        "title": "Операторы сравнения и ветвление if-else",
        "description": "Синтаксис if-else, 4-пробельные отступы, операторы сравнения и тернарный условный оператор в одну строку.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Ветвление `if-else` необходимо везде, где ход решения зависит от свойства данных:
- Чётное число или нечётное (задание №5);
- Подходит ли число под условия задачи (задание №17);
- Попадает ли координата или значение в допустимый отрезок.

Без условий программа умеет только выполнять команды строго сверху вниз. Ветвление даёт программе способность «принимать решения».

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-git-fork"></i><span>Ветвление</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">if condition:</div>
      <div class="text-xs font-semibold text-slate-500">выполнить при True</div>
    </div>
    <div class="text-[11px] font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      Отступ 4 пробела обязателен
    </div>
  </div>
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-rose-600 flex items-center gap-1.5">
      <i class="ph-bold ph-arrow-elbow-down-right"></i><span>Альтернатива</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">else:</div>
      <div class="text-xs font-semibold text-slate-500">выполнить при False</div>
    </div>
    <div class="text-[11px] font-bold text-rose-800 bg-rose-50 rounded-lg p-1.5 border border-rose-200">
      Срабатывает, если if не подошёл
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-lightning"></i><span>В одну строку</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">a if cond else b</div>
      <div class="text-xs font-semibold text-slate-500">тернарный оператор</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      Компактный выбор значения
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
Оператор `if` вычисляет логическое выражение. Если результат `True` (истина), выполняется тело условия с отступом в 4 пробела. Если результат `False` (ложь), управление сразу передаётся блоку `else`.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-git-fork"></i></span>
    <span>Блок-схема конструкции if-else</span>
  </div>
  <div class="flex flex-col items-center gap-3 text-xs pt-1">
    <div class="px-5 py-2.5 rounded-2xl bg-white border-2 border-indigo-200/80 shadow-[0_2px_0_#DAE1E9] font-mono font-black text-indigo-900 text-sm">
      Условие: n % 2 == 0 ?
    </div>
    <div class="flex items-center justify-between w-full max-w-sm px-4 text-xs font-black">
      <span class="text-emerald-600 flex items-center gap-1">ДА (True) ↙</span>
      <span class="text-rose-600 flex items-center gap-1">↘ НЕТ (False)</span>
    </div>
    <div class="flex items-center justify-between w-full max-w-md gap-4">
      <div class="flex-1 p-3 rounded-xl bg-white border-2 border-emerald-200/80 shadow-[0_2px_0_#D1FAE5] text-center font-mono font-bold text-emerald-800">
        print("Чётное")
      </div>
      <div class="flex-1 p-3 rounded-xl bg-white border-2 border-rose-200/80 shadow-[0_2px_0_#FEE2E2] text-center font-mono font-bold text-rose-800">
        print("Нечётное")
      </div>
    </div>
  </div>
</div>

### Операторы сравнения в Python
- `==` : Равно (не путайте с присваиванием `=`)
- `!=` : Не равно
- `<` и `>` : Строго меньше / строго больше
- `<=` и `>=` : Меньше либо равно / больше либо равно

### Тернарный условный оператор (условие в одну строку)
Иногда требуется выбрать значение переменной в зависимости от условия:
<div class="my-6 p-5 rounded-2xl border-2 border-emerald-100 bg-emerald-50/40">
  <div class="text-xs font-black uppercase text-emerald-800 mb-2">Сравнение классического if-else и тернарного оператора:</div>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
    <div class="p-3 bg-white rounded-xl border border-slate-200">
      <div class="text-slate-500 font-sans mb-1 font-bold">Обычный if-else (4 строки):</div>
      <pre class="text-slate-800">if a > b:
    max_val = a
else:
    max_val = b</pre>
    </div>
    <div class="p-3 bg-white rounded-xl border border-emerald-300">
      <div class="text-emerald-700 font-sans mb-1 font-bold">Тернарный оператор (1 строка):</div>
      <pre class="text-emerald-800 font-bold">max_val = a if a > b else b</pre>
    </div>
  </div>
  <p class="text-xs text-slate-600 mt-3 font-sans leading-relaxed">
    Схема чтения: <code>«взять значение A, ЕСЛИ (a > b), ИНАЧЕ взять значение B»</code>. Этот синтаксис часто встречается в коротких разборах заданий ЕГЭ.
  </p>
</div>

## Примеры кода и результат
Попробуйте запустить код и поменять значения переменных `n`, `a` и `b`:

[CODE_RUNNER title="Конструкция if-else и тернарный оператор" input="" output="Число 14 четное\\nБольшее число: 14"]
n = 14

# 1. Классическая проверка четности
if n % 2 == 0:
    print(f"Число {n} четное")
else:
    print(f"Число {n} нечетное")

# 2. Выбор максимума через тернарный оператор
a = 14
b = 9
max_val = a if a > b else b
print("Большее число:", max_val)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Одиночный знак = в условии</div>
      <p class="text-xs text-slate-600 leading-relaxed">Запись if x = 10 вызовет SyntaxError. Для проверки равенства всегда пишите два знака ==.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">if x = 10:  # Ошибка!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">if x == 10: # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытое двоеточие</div>
      <p class="text-xs text-slate-600 leading-relaxed">После строки с if condition и после else обязательно ставится знак двоеточия :.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">if x > 5   # Ошибка!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">if x > 5:  # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Сбой в отступах</div>
      <p class="text-xs text-slate-600 leading-relaxed">Весь код внутри ветки if или else должен иметь одинаковый отступ в 4 пробела.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">IndentationError</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">4 пробела от края</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p109-q1" question="Какой оператор проверяет два значения на неравенство в Python?" options="<>|!=|!==|not ==" answer="!=" hint="В Python знак неравенства состоит из восклицательного знака и знака равенства." explanation="В Python оператор проверки на неравенство записывается строго как !=."]
[CHECKPOINT key="p109-q2" question="Что произойдёт при исполнении строки кода: if x == 5 print(x)?" options="Код напечатает 5|SyntaxError (забыто двоеточие)|IndentationError|TypeError" answer="SyntaxError (забыто двоеточие)" hint="Посмотрите внимательно на конец строки заголовка if: какого обязательного знака там не хватает?" explanation="После условия в заголовке if обязательно требуется двоеточие : перед телом инструкции."]
"""
    },
    110: {
        "title": "Каскадные условия: конструкция if-elif-else",
        "description": "Последовательная проверка нескольких альтернатив сверху вниз до первого совпадения.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В заданиях ЕГЭ часто требуется распределить данные по 3 и более категориям:
- Анализ остатка при делении на 3 (остатки 0, 1 или 2 в задании №5);
- Проверка знака числа (положительное, отрицательное или ноль);
- Многоуровневые правила преобразования строк и чисел.

## Синтаксис и наглядная визуальная схема
Конструкция `if-elif-else` проверяет условия **строго сверху вниз**. Как только находится первое условие, давшее `True`, его блок выполняется, а **все остальные `elif` и `else` пропускаются**.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-purple-100 bg-gradient-to-br from-purple-50/60 via-white to-indigo-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-purple-700 mb-3 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-purple-100 text-purple-700 flex items-center justify-center text-xs"><i class="ph-bold ph-steps"></i></span>
    <span>Поток исполнения каскада if-elif-else</span>
  </div>
  <div class="space-y-2 text-xs pt-1">
    <div class="p-3 rounded-xl bg-white border-2 border-indigo-200/80 shadow-[0_2px_0_#DAE1E9] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="font-mono font-black text-indigo-700 text-sm">1. if n > 0:</span>
      <span class="text-slate-600 font-semibold">Проверяется первым</span>
    </div>
    <div class="p-3 rounded-xl bg-white border-2 border-purple-200/80 shadow-[0_2px_0_#E9D5FF] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="font-mono font-black text-purple-700 text-sm">2. elif n < 0:</span>
      <span class="text-slate-600 font-semibold">Проверяется только если первое условие дало False</span>
    </div>
    <div class="p-3 rounded-xl bg-white border-2 border-emerald-200/80 shadow-[0_2px_0_#D1FAE5] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="font-mono font-black text-emerald-700 text-sm">3. else:</span>
      <span class="text-slate-600 font-semibold">Срабатывает, если ВСЕ предыдущие проверки дали False</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Классификация числа по знаку:

[CODE_RUNNER title="Каскад if-elif-else" input="" output="Число 0 равно нулю\\nКатегория: Нулевая"]
n = 0

if n > 0:
    print(f"Число {n} положительное")
elif n < 0:
    print(f"Число {n} отрицательное")
else:
    print(f"Число {n} равно нулю")
    print("Категория: Нулевая")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Несколько независимых if вместо elif</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если написать три отдельных if, каждый из них выполнится независимо. При score=90 сработают сразу оба условия!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">if x > 5: ... if x > 8: ...</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">if x > 8: ... elif x > 5: ...</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Неверный порядок проверок</div>
      <p class="text-xs text-slate-600 leading-relaxed">Всегда ставьте более узкие (строгие) условия выше широких, иначе широкое условие перехватит все значения.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">if x > 0: ... elif x > 100: (мёртвый код)</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">if x > 100: ... elif x > 0: (верно)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p110-q1" question="Сколько блоков кода может выполниться максимум в одной непрерывной связке if-elif-else?" options="Все, условия которых верны|Ровно один|Минимум два|Зависит от числа elif" answer="Ровно один" hint="Вспомните главное свойство elif: что происходит с остальными ветками, как только одно условие дало True?" explanation="В конструкции if-elif-else выполняется максимум одна ветка — первая, условие которой оказалось True. Все последующие ветки игнорируются."]
[CHECKPOINT key="p110-q2" question="Что выведет следующий фрагмент программы?

x = 10
if x > 5:
    print('A')
elif x > 8:
    print('B')" options="B|A|A и B|Ничего" answer="A" hint="Проверьте условия по порядку сверху вниз: подошло ли первое условие x > 5 для числа 10?" explanation="Условие x > 5 истинно (10 > 5), поэтому сразу печатается 'A', а ветка elif x > 8 вообще не проверяется."]
"""
    },
    111: {
        "title": "Сложные логические связки: and, or, not и приоритет операций",
        "description": "Логическое И, ИЛИ, НЕ, приоритеты операций и вычисление логических функций для задания №2.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Задание №2 ЕГЭ целиком посвящено исследованию логических выражений от переменных x, y, z, w.
В заданиях №15 и №17 условия фильтрации состоят из нескольких частей:
- «Число делится на 3 И не делится на 7»;
- «Хотя бы одно из чисел пары положительно ИЛИ их сумма кратна 5».

Python позволяет объединять простые сравнения в сложные составные условия с помощью операторов `and`, `or`, `not`.

## Синтаксис и наглядная визуальная схема
<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-sky-100 bg-gradient-to-br from-sky-50/60 via-white to-indigo-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-sky-700 mb-3 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-sky-100 text-sky-700 flex items-center justify-center text-xs"><i class="ph-bold ph-brackets-curly"></i></span>
    <span>Таблица логических операций Python</span>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-3.5 text-xs pt-1">
    <div class="p-4 rounded-xl bg-white border-2 border-sky-200/80 shadow-[0_2px_0_#E0F2FE]">
      <span class="font-black text-sky-700 block mb-2 text-sm">not (Логическое НЕ)</span>
      <div class="space-y-1 text-slate-600">
        <div>Инвертирует значение:</div>
        <div>• <code>not True ➔ False</code></div>
        <div>• <code>not False ➔ True</code></div>
      </div>
    </div>
    <div class="p-4 rounded-xl bg-white border-2 border-indigo-200/80 shadow-[0_2px_0_#DAE1E9]">
      <span class="font-black text-indigo-700 block mb-2 text-sm">and (Логическое И)</span>
      <div class="space-y-1 text-slate-600">
        <div>Истинно, только если <b>оба</b> True:</div>
        <div>• <code>True and True ➔ True</code></div>
        <div>• <code>True and False ➔ False</code></div>
      </div>
    </div>
    <div class="p-4 rounded-xl bg-white border-2 border-purple-200/80 shadow-[0_2px_0_#E9D5FF]">
      <span class="font-black text-purple-700 block mb-2 text-sm">or (Логическое ИЛИ)</span>
      <div class="space-y-1 text-slate-600">
        <div>Истинно, если <b>хотя бы один</b> True:</div>
        <div>• <code>True or False ➔ True</code></div>
        <div>• <code>False or False ➔ False</code></div>
      </div>
    </div>
  </div>
</div>

### Порядок приоритета логических операций
1. Скобки `(...)` — наивысший приоритет
2. Операции сравнения (`==`, `!=`, `<`, `>`, `<=`, `>=`)
3. `not` (отрицание)
4. `and` (логическое умножение / конъюнкция)
5. `or` (логическое сложение / дизъюнкция — самый слабый приоритет)

<div class="my-6 p-4 rounded-xl bg-amber-50/70 border border-amber-200 text-xs text-amber-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-amber-800">
    <i class="ph-bold ph-lightning"></i> Ленивые вычисления (Short-circuit evaluation)
  </div>
  Если в выражении <code>A and B</code> условие <code>A</code> оказалось ложным (<code>False</code>), Python <b>вообще не вычисляет</b> выражение <code>B</code>, так как результат уже гарантированно <code>False</code>. Это позволяет безопасно писать защитные проверки: <code>if b != 0 and a / b > 2:</code> — деление на ноль никогда не произойдёт!
</div>

## Примеры кода и результат
Вычисление значения сложной логической функции для конкретных значений переменных:

[CODE_RUNNER title="Вычисление логических функций" input="" output="При x=1, y=0: f = 0\\nПри x=0, y=1: f = 1\\nПри x=1, y=1: f = 1"]
# Проверим формулу (x -> y), которая на языке Python записывается как: (not x) or y

# Набор 1: x = 1 (True), y = 0 (False)
x = 1
y = 0
f = (not x) or y
print(f"При x={x}, y={y}: f = {int(f)}")

# Набор 2: x = 0 (False), y = 1 (True)
x = 0
y = 1
f = (not x) or y
print(f"При x={x}, y={y}: f = {int(f)}")

# Набор 3: x = 1 (True), y = 1 (True)
x = 1
y = 1
f = (not x) or y
print(f"При x={x}, y={y}: f = {int(f)}")
[/CODE_RUNNER]

*(В следующем модуле после изучения циклов мы научимся перебирать все возможные комбинации x, y, z, w автоматически в 3 строчки кода!)*

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Импликация x → y</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center text-xs font-black">→</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Как записать стрелку в Python?</div>
      <p class="text-xs text-slate-600 leading-relaxed">В Python нет символа стрелки. Импликацию x → y записывают либо через (not x) or y, либо через компактное неравенство x <= y.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold">(not x) or y # Равносильность</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">x <= y       # Компактный трюк</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-purple-200 bg-white p-4 shadow-[0_3px_0_#E9D5FF] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-purple-700 uppercase tracking-wider">Эквивалентность x ≡ y</span>
        <span class="w-6 h-6 rounded-lg bg-purple-100 text-purple-600 flex items-center justify-center text-xs font-black">≡</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Тождественное равенство</div>
      <p class="text-xs text-slate-600 leading-relaxed">Эквивалентность двух логических выражений записывается обычным оператором проверки равенства ==.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-purple-50 border border-purple-200 text-purple-800 font-bold">x == y # Истинно при 0==0 и 1==1</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p111-q1" question="Какой приоритет выполнения у операторов not, and, or?" options="and, затем or, затем not|not, затем and, затем or|Слева направо|or, затем and, затем not" answer="not, затем and, затем or" hint="Отрицание (not) всегда выполняется первым, за ним идёт логическое умножение (and), а в конце — логическое сложение (or)." explanation="not имеет высший приоритет, затем выполняется and, и наименьший приоритет у оператора or."]
[CHECKPOINT key="p111-q2" question="Как компактнее всего записать импликацию x -> y на языке Python?" options="(not x) and y|x <= y|x == y|x or not y" answer="x <= y" hint="Вспомните таблицу истинности импликации: она ложна только при x=1, y=0. Какое арифметическое сравнение ложно при 1 и 0, но верно для всех остальных пар?" explanation="В булевой логике Python выражение x <= y даёт False только при x=1, y=0 (так как 1 <= 0 — ложь), что идеально совпадает с импликацией."]
"""
    },
    112: {
        "title": "Паттерны проверки условий в ЕГЭ (делимость, последняя цифра, интервалы)",
        "description": "Боевые шаблоны для задач 17 и 25: кратность, остатки, модуль отрицательных чисел и двойные неравенства.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В заданиях №17 и №25 формулировки условий повторяются из года в год:
- «Число делится на 3 или оканчивается на 7»;
- «Хотя бы одно число из пары положительно»;
- «Сумма пары кратна 5, но не кратна 10».

Понимание того, как каждая математическая фраза превращается в строчку на Python, позволяет писать условия безошибочно и быстро.

## Синтаксис и наглядная визуальная схема
Сводка канонических проверок условий для задач ЕГЭ:

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-emerald-100 bg-gradient-to-br from-emerald-50/60 via-white to-teal-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-700 mb-3 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center text-xs"><i class="ph-bold ph-check-circle"></i></span>
    <span>Каноничные шаблоны условий ЕГЭ</span>
  </div>
  <div class="space-y-2.5 text-xs pt-1">
    <div class="p-3.5 rounded-xl bg-white border-2 border-emerald-200/80 shadow-[0_2px_0_#D1FAE5] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="text-slate-700 font-bold">1. Число x делится на k нацело (кратно k):</span>
      <code class="text-emerald-700 font-black text-sm">x % k == 0</code>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200/80 shadow-[0_2px_0_#DAE1E9] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="text-slate-700 font-bold">2. Последняя цифра числа x равна d:</span>
      <code class="text-indigo-700 font-black text-sm">x % 10 == d</code>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-purple-200/80 shadow-[0_2px_0_#E9D5FF] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="text-slate-700 font-bold">3. Число x попадает в отрезок [a; b]:</span>
      <code class="text-purple-700 font-black text-sm">a <= x <= b</code>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-amber-200/80 shadow-[0_2px_0_#FEF3C7] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <span class="text-slate-700 font-bold">4. Ровно одно из двух условий выполняется (XOR):</span>
      <code class="text-amber-700 font-black text-sm">cond1 != cond2</code>
    </div>
  </div>
</div>

## Примеры кода и результат
Разберём подробный пошаговый пример проверки пары чисел по реальному критерию из задания №17:
*«Хотя бы одно из чисел оканчивается на 7, И сумма чисел пары делится на 3»*.

[CODE_RUNNER title="Пошаговая проверка пары чисел" input="" output="Условие 1 (хотя бы одно на 7): True\\nУсловие 2 (сумма кратна 3): True\\nПара (17, 28) подходит! Сумма пары: 45"]
# Возьмём для проверки два конкретных числа:
a = 17
b = 28

# Шаг 1. Проверяем последнюю цифру каждого числа
# 17 % 10 даёт 7, а 28 % 10 даёт 8:
c1_a = (a % 10 == 7)  # True
c1_b = (b % 10 == 7)  # False

# "Хотя бы одно" — это логическое ИЛИ (or):
condition1 = c1_a or c1_b

# Шаг 2. Проверяем кратность суммы на 3:
pair_sum = a + b  # 17 + 28 = 45
condition2 = (pair_sum % 3 == 0)  # 45 делится на 3 без остатка -> True

print("Условие 1 (хотя бы одно на 7):", condition1)
print("Условие 2 (сумма кратна 3):", condition2)

# Шаг 3. Итоговое решение: оба условия должны выполниться одновременно (and)
if condition1 and condition2:
    print(f"Пара ({a}, {b}) подходит! Сумма пары: {pair_sum}")
else:
    print(f"Пара ({a}, {b}) не подходит.")
[/CODE_RUNNER]

*(В реальном задании №17 таких пар в файле несколько тысяч. В следующем модуле мы изучим циклы, которые позволят проверить все тысячи пар за десятую долю секунды!)*

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Двойные неравенства</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center text-xs font-black">≤</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Естественная запись диапазонов</div>
      <p class="text-xs text-slate-600 leading-relaxed">В Python можно писать привычные математические двойные неравенства 100 <= x <= 999. Это намного нагляднее, чем писать x >= 100 and x <= 999.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">100 <= x <= 999 # Трёхзначное число</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ровно одно из двух</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!=</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Трюк с неравенством условий</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если в задании сказано «ровно одно из двух чисел делится на 5», просто сравните их через !=. Если оба True или оба False — результат False.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">(a % 5 == 0) != (b % 5 == 0)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p112-q1" question="Как в Python проще и надёжнее всего проверить, что натуральное число x является трёхзначным?" options="len(x) == 3|100 <= x <= 999|100 < x < 1000|x // 100 == 1" answer="100 <= x <= 999" hint="Вспомните: какое наименьшее и какое наибольшее трёхзначное натуральное число существует? Используйте двойное неравенство." explanation="Двойное неравенство 100 <= x <= 999 строго проверяет, что число лежит в диапазоне от 100 до 999 включительно. Запись len(x) вызовет ошибку, так как число x — это int, а не строка!"]
[CHECKPOINT key="p112-q2" question="Какое выражение вернёт True тогда и только тогда, когда ровно одно из чисел a или b чётно?" options="(a % 2 == 0) and (b % 2 == 0)|(a % 2 == 0) != (b % 2 == 0)|(a % 2 == 0) or (b % 2 == 0)|a % 2 != b % 2" answer="(a % 2 == 0) != (b % 2 == 0)" hint="Если ровно одно из двух условий истинно, значит их результаты True и False различны (не равны друг другу)." explanation="Сравнение на неравенство (c1 != c2) возвращает True, когда одно условие истинно, а второе ложно (True != False даёт True). Если оба чётны или оба нечётны, они равны, и вернётся False."]
"""
    }
}
