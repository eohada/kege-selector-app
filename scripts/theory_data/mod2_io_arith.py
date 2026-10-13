# -*- coding: utf-8 -*-
"""
Модуль 2: Ввод данных, вывод и логические сравнения (Темы 105-108).
- 105: Ввод данных: функция input() и чтение чисел
- 106: Продвинутый вывод print(): параметры sep и f-строки
- 107: Операторы сравнения и логические выражения (==, !=, >, <, >=, <=)
- 108: Встроенные функции: min(), max(), sum(), len()
"""

MOD2_TOPICS = {
    105: {
        "title": "Ввод данных: функция input() и чтение чисел",
        "description": "Как работает функция input(), почему она всегда возвращает текст str и как правильно считывать числа int(input()).",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
При решении задач и проверке алгоритмов программе часто требуется получить данные из внешнего источника:
- При отладке решений заданий **№5, №16, №23** вам нужно передать в программу начальное число и посмотреть, как отработает ваш код.
- При решении задач на обработку потока данных (**№17, №24, №26, №27**) программа получает строки или числа построчно.

Главный инструмент для приёма данных с клавиатуры или из входного потока — это функция `input()`.

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-keyboard"></i><span>Приём данных</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">Функция input()</div>
      <div class="text-xs font-semibold text-slate-500">ждёт ввода от пользователя</div>
    </div>
    <div class="text-[11px] font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      Останавливает программу до Enter
    </div>
  </div>
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-rose-600 flex items-center gap-1.5">
      <i class="ph-bold ph-warning-circle"></i><span>Главное правило</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-rose-700">Всегда строка (str)</div>
      <div class="text-xs font-semibold text-slate-500">даже если ввели 42</div>
    </div>
    <div class="text-[11px] font-bold text-rose-800 bg-rose-50 rounded-lg p-1.5 border border-rose-200">
      '42' — это текст, а не число!
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-check-circle"></i><span>Чтение чисел</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">int(input())</div>
      <div class="text-xs font-semibold text-slate-500">превращает ввод в число</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      Обязательный шаблон для ЕГЭ
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
Когда Python встречает команду `input()`, выполнение программы приостанавливается. Компьютер ждёт, пока пользователь наберёт данные и нажмёт клавишу **Enter**.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-terminal"></i></span>
    <span>Как правильно считывать число с клавиатуры</span>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs font-mono">
    <div class="p-3.5 rounded-xl bg-white border-2 border-slate-200">
      <span class="font-sans font-bold text-slate-400 block mb-1">1. input()</span>
      <div class="text-slate-800 font-bold">"15"</div>
      <p class="font-sans text-slate-500 mt-1">Пользователь ввёл 15, но Python видит это как строку текста.</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200">
      <span class="font-sans font-bold text-indigo-600 block mb-1">2. int(...)</span>
      <div class="text-indigo-700 font-bold">int("15") -> 15</div>
      <p class="font-sans text-slate-500 mt-1">Функция int() снимает кавычки и превращает текст в целое число.</p>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-emerald-200">
      <span class="font-sans font-bold text-emerald-600 block mb-1">3. Сохранение</span>
      <div class="text-emerald-700 font-bold">x = 15</div>
      <p class="font-sans text-slate-500 mt-1">В переменную x попадает настоящее математическое число.</p>
    </div>
  </div>
</div>

### Чтение двух чисел на разных строках
Если во входных данных числа записаны на разных строках, мы просто вызываем `int(input())` два раза подряд:
```python
a = int(input())
b = int(input())
print("Сумма:", a + b)
```

## Примеры кода и результат
Посмотрите, что происходит, если забыть функцию `int()` при вводе чисел:

[CODE_RUNNER title="Опасность сырого input() vs int(input())" input="" output="Сырой ввод (текст): 53\\nПравильный ввод (числа): 8"]
# Симулируем ввод строк '5' и '3'
s1 = "5"
s2 = "3"
print("Сырой ввод (текст):", s1 + s2)

# Превращаем в целые числа через int()
n1 = int(s1)
n2 = int(s2)
print("Правильный ввод (числа):", n1 + n2)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Склеивание вместо сложения</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если забыть int(), программа склеит строки: '10' + '20' = '1020', а не 30!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">x = input()      # строка</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">x = int(input()) # число</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Лишние подсказки внутри input()</div>
      <p class="text-xs text-slate-600 leading-relaxed">Не пишите input("Введите число: "). На экзамене вы запускаете код в IDE для себя, лишние фразы засоряют окно вывода.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">input("Введите x: ") # Лишнее</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">input()              # Чисто</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Случайный ввод пробелов или букв</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если в int() передать пустоту или буквы, программа упадет с ошибкой ValueError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">int("abc") # ValueError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">int("123") # 123</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p105-q1" question="Пользователь ввёл с клавиатуры число 7. Что вернёт вызов команды input()?" options="7 (целое число)|'7' (строку текста)|7.0 (дробное число)|True" answer="'7' (строку текста)" explanation="Функция input() ВСЕГДА возвращает строку текста (str), даже если пользователь набрал цифры. Чтобы получить число, нужно явно обернуть вызов в int(input())." hint="Вспомните главное правило: в каком типе данных функция input() всегда возвращает введённые символы?"]
[CHECKPOINT key="p105-q2" question="Что выведет следующая программа, если пользователь по очереди ввёл 4 и 6?

a = input()
b = input()
print(a + b)" options="10|46|24|Ошибка TypeError" answer="46" explanation="Так как вызовы input() не обёрнуты в int(), переменные a и b содержат строки '4' и '6'. Оператор + между строками склеивает их в '46'." hint="Обратите внимание: результат input() — это текст, а не число. Что сделает оператор + с двумя строками '4' и '6'?"]
"""
    },

    106: {
        "title": "Продвинутый вывод print(): параметры sep и f-строки",
        "description": "Управление разделителем sep, склеивание ответов без пробелов и удобный вывод результатов через современные f-строки.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
На экзамене нет автоматической тестирующей системы: вы сами запускаете написанную программу в IDE и сами переносите ответ в поле на компьютере.
- **В задании №2** нужно вывести таблицу истинности, где значения переменных часто выводятся подряд без пробелов (например, `1010`).
- **В задании №17 и №26** в ответе требуется записать два числа строго через один пробел: сначала количество, затем максимум.
- **В задании №27** нужно вывести пару чисел.

Функция `print()` позволяет точно настроить, как именно данные выводятся на экран.

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-dots-three"></i><span>Параметр sep</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">Разделитель</div>
      <div class="text-xs font-semibold text-slate-500">что ставить между элементами</div>
    </div>
    <div class="text-[11px] font-mono font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      sep="" убирает пробелы
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-text-t"></i><span>f-строки</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">f"...{x}..."</div>
      <div class="text-xs font-semibold text-slate-500">подстановка переменных в текст</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      Самый удобный способ вывода
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-amber-700 flex items-center gap-1.5">
      <i class="ph-bold ph-check-square"></i><span>Формат ЕГЭ</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-amber-800">Два числа в ответ</div>
      <div class="text-xs font-semibold text-slate-500">print(count, max_val)</div>
    </div>
    <div class="text-[11px] font-bold text-amber-900 bg-amber-50 rounded-lg p-1.5 border border-amber-200">
      Сразу даёт пробел между ними
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
### Как работает параметр `sep` (separator — разделитель)
По умолчанию функция `print(a, b, c)` разделяет выводимые значения **одним пробелом** (`sep=" "`).
Вы можете изменить этот разделитель на любой другой символ:
- `sep=""` (пустая строка): склеивает значения вплотную без пробелов.
- `sep="-"`: разделяет дефисом.
- `sep=", "`: разделяет запятой с пробелом.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-sliders"></i></span>
    <span>Сравнение вывода с разными значениями sep</span>
  </div>
  <div class="space-y-2 text-xs font-mono">
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">print(1, 0, 1)</span>
      <span class="text-indigo-600 font-black">-> 1 0 1 (по умолчанию через пробел)</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">print(1, 0, 1, sep="")</span>
      <span class="text-emerald-600 font-black">-> 101 (склеено вплотную, для №2!)</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">print(2026, 10, 15, sep="-")</span>
      <span class="text-purple-600 font-black">-> 2026-10-15</span>
    </div>
  </div>
</div>

### f-строки: современный формат вывода
Буква `f` перед кавычками сообщает Python: *«Подставь значения из фигурных скобок `{...}` прямо внутрь текста»*.
```python
ans = 42
print(f"Итоговый ответ: {ans}")
```
Это намного удобнее и нагляднее, чем писать `print("Итоговый ответ: " + str(ans))`.

## Примеры кода и результат
Попробуйте запустить эти примеры:

[CODE_RUNNER title="Управление выводом и f-строки" input="" output="По умолчанию: 1 2 3\\nСклеено: 123\\nЧерез дефис: 1-2-3\\nС ответом ЕГЭ: Задача 17 -> найдено 45 пар, максимум 980"]
# 1. Разные варианты sep
print("По умолчанию:", 1, 2, 3)
print("Склеено:", 1, 2, 3, sep="")
print("Через дефис:", 1, 2, 3, sep="-")

# 2. Удобная f-строка для проверки задачи
count = 45
max_sum = 980
print(f"С ответом ЕГЭ: Задача 17 -> найдено {count} пар, максимум {max_sum}")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытая буква f</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если забыть букву f перед строкой, Python напечатает текст {ans} буквально.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">print("{ans}")  # выведет {ans}</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print(f"{ans}") # выведет 42</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Опечатка в sep</div>
      <p class="text-xs text-slate-600 leading-relaxed">Параметр пишется строчными латинскими буквами: sep, а не Sep.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">print(a, b, Sep="") # TypeError</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print(a, b, sep="") # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Лишние пояснения в ответе ЕГЭ</div>
      <p class="text-xs text-slate-600 leading-relaxed">В поле ответа нужно вписать только число! Не вписывайте слова «Ответ:».</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">print("Ответ:", 42) # в бланк 42</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">print(42)          # чисто</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p106-q1" question="Что выведет следующий фрагмент программы?

print('A', 'B', 'C', sep='-')" options="A B C|A-B-C|ABC|'A-B-C'" answer="A-B-C" explanation="Параметр sep='-' заменяет стандартный пробел между элементами на дефис, поэтому выведется A-B-C." hint="Параметр sep задаёт строку-разделитель между элементами. Какой символ указан в sep='-'?"]
[CHECKPOINT key="p106-q2" question="Какая строчка кода выведет значение переменной x внутри текста 'Ответ: 15' с использованием f-строки?" options="print('Ответ: {x}')|print(f'Ответ: {x}')|print(f'Ответ: x')|print('Ответ: ' + x)" answer="print(f'Ответ: {x}')" explanation="В f-строках (с буквой f перед кавычками) имя переменной заключается в фигурные скобки {x}, и Python автоматически подставляет её значение в текст." hint="Вспомните синтаксис f-строк: перед открывающей кавычкой обязательно ставится буква f."]
"""
    },

    107: {
        "title": "Операторы сравнения и логические выражения (==, !=, >, <, >=, <=)",
        "description": "Сравнение чисел и строк в Python, шесть операторов сравнения, цепочки двойных неравенств и булев результат True/False.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В компьютерном ЕГЭ компьютер постоянно проверяет условия:
- **В задании №2** строится таблица истинности логического выражения.
- **В задании №5** алгоритм проверяет: «если остаток равен 0...».
- **В задании №17** проверяется: «хотя бы одно число пары больше 100».
- **В задании №24** проверяется: «символ равен 'A'».

Операторы сравнения — это язык, на котором мы задаём вопросы компьютеру. Ответом всегда является либо `True` (Да, верно), либо `False` (Нет, неверно).

<div class="my-6 grid grid-cols-1 sm:grid-cols-3 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600 flex items-center gap-1.5">
      <i class="ph-bold ph-scales"></i><span>Операторы проверки</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-slate-900">Шесть сравнений</div>
      <div class="text-xs font-semibold text-slate-500">==, !=, >, <, >=, <=</div>
    </div>
    <div class="text-[11px] font-bold text-indigo-800 bg-indigo-50 rounded-lg p-1.5 border border-indigo-200">
      == это сравнение, = это присвоить
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-emerald-600 flex items-center gap-1.5">
      <i class="ph-bold ph-toggle-left"></i><span>Результат</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-emerald-700">Тип bool</div>
      <div class="text-xs font-semibold text-slate-500">только True или False</div>
    </div>
    <div class="text-[11px] font-bold text-emerald-800 bg-emerald-50 rounded-lg p-1.5 border border-emerald-200">
      Основа для условий if
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div class="text-[11px] font-black uppercase tracking-wider text-amber-700 flex items-center gap-1.5">
      <i class="ph-bold ph-arrows-in-line-horizontal"></i><span>Двойные неравенства</span>
    </div>
    <div class="my-2">
      <div class="text-xl font-black text-amber-800">10 <= x <= 50</div>
      <div class="text-xs font-semibold text-slate-500">работают как в математике</div>
    </div>
    <div class="text-[11px] font-bold text-amber-900 bg-amber-50 rounded-lg p-1.5 border border-amber-200">
      Удобно для проверки диапазонов
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
В Python есть **шесть базовых операторов сравнения**:

| Оператор | Значение | Пример | Результат | Пояснение |
|---|---|---|---|---|
| `==` | Равно | `5 == 5` | `True` | Проверка на точное равенство |
| `!=` | Не равно | `5 != 3` | `True` | Проверка на неравенство |
| `>` | Больше | `10 > 7` | `True` | Строго больше |
| `<` | Меньше | `4 < 2` | `False` | Строго меньше |
| `>=` | Больше или равно | `5 >= 5` | `True` | Не меньше |
| `<=` | Меньше или равно | `7 <= 5` | `False` | Не больше |

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-brackets-curly"></i></span>
    <span>Двойные неравенства: проверка попадания в диапазон</span>
  </div>
  <p class="text-xs text-slate-600 mb-3">
    В отличие от многих других языков, в Python можно писать цепочки сравнений в точности как в математике:
  </p>
  <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200 font-mono text-xs font-bold text-indigo-900">
    100 <= x <= 999  # Проверка, что число x трехзначное!
  </div>
</div>

## Примеры кода и результат
Посмотрите, как логические выражения вычисляются в Python:

[CODE_RUNNER title="Примеры логических сравнений" input="" output="x равно 10? True\\nx больше 20? False\\nx четное? True\\nЧисло трехзначное? True"]
x = 10

# Проверки значений
print("x равно 10?", x == 10)
print("x больше 20?", x > 20)

# Проверка четности через остаток % 2
print("x четное?", x % 2 == 0)

# Проверка трехзначности
num = 245
print("Число трехзначное?", 100 <= num <= 999)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Путаница = и ==</div>
      <p class="text-xs text-slate-600 leading-relaxed">Одиночный = кладёт значение в переменную. Для проверки равенства всегда пишите два знака ==.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">x = 5  # Присваивание</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">x == 5 # Проверка равенства</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Неправильный порядок знаков</div>
      <p class="text-xs text-slate-600 leading-relaxed">Операторы >= и <= пишутся строго так. Написание => или =< вызовет ошибку.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">x => 10 # SyntaxError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">x >= 10 # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Сравнение числа со строкой</div>
      <p class="text-xs text-slate-600 leading-relaxed">Выражение 5 == "5" вернёт False, так как число никогда не равно строке!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">5 == "5" # False!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">5 == int("5") # True</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p107-q1" question="Какой результат вернёт выражение 15 % 2 == 0 в Python?" options="True|False|0|1" answer="False" explanation="15 делим на 2 с остатком: 15 % 2 = 1. Проверяем: 1 == 0 — это ложь (False). Значит число 15 нечётное." hint="Вычислите сначала остаток: 15 % 2 = 1. Затем сравните 1 == 0: истинно это или ложно?"]
[CHECKPOINT key="p107-q2" question="Какой оператор в Python проверяет равенство двух значений?" options="=|==|!=|is" answer="==" explanation="Для проверки равенства используется двойной знак равенства ==. Одиночный знак = используется для присваивания." hint="Не путайте присваивание и сравнение: для проверки равенства используется оператор из двух одинаковых знаков."]
"""
    },

    108: {
        "title": "Встроенные функции: min(), max(), sum(), len()",
        "description": "Поиск минимума и максимума, подсчёт сумм и определение длины наборов данных для заданий 8, 17 и 26.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В компьютерном ЕГЭ постоянными задачами являются:
- «Найти наибольшую сумму пары чисел» (задание №17).
- «Определить минимальную стоимость покупки» (задание №26).
- «Посчитать количество подходящих слов» (задание №8).
- «Найти длину строки» (задание №24).

Вам не нужно писать циклы вручную для таких простых операций: в Python встроены быстрые функции `min()`, `max()`, `sum()` и `len()`.

<div class="my-6 grid grid-cols-1 sm:grid-cols-4 gap-3.5 not-prose">
  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-indigo-600 font-mono">min(...)</span>
      <div class="text-base font-black text-slate-800 mt-1">Минимум</div>
      <p class="text-xs text-slate-500 mt-1">min(10, 5, 20) -> 5</p>
    </div>
    <div class="text-[11px] font-bold text-indigo-700 bg-indigo-50 rounded-lg p-1.5 mt-2 border border-indigo-200">
      Наименьшее значение
    </div>
  </div>
  <div class="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-[0_3px_0_#A7F3D0] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-emerald-600 font-mono">max(...)</span>
      <div class="text-base font-black text-slate-800 mt-1">Максимум</div>
      <p class="text-xs text-slate-500 mt-1">max(10, 5, 20) -> 20</p>
    </div>
    <div class="text-[11px] font-bold text-emerald-700 bg-emerald-50 rounded-lg p-1.5 mt-2 border border-emerald-200">
      Наибольшее значение
    </div>
  </div>
  <div class="rounded-2xl border-2 border-purple-200 bg-white p-4 shadow-[0_3px_0_#E9D5FF] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-purple-600 font-mono">sum(...)</span>
      <div class="text-base font-black text-slate-800 mt-1">Сумма</div>
      <p class="text-xs text-slate-500 mt-1">sum([1, 2, 3]) -> 6</p>
    </div>
    <div class="text-[11px] font-bold text-purple-700 bg-purple-50 rounded-lg p-1.5 mt-2 border border-purple-200">
      Суммирует набор чисел
    </div>
  </div>
  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <span class="text-xs font-black uppercase text-amber-600 font-mono">len(...)</span>
      <div class="text-base font-black text-slate-800 mt-1">Длина</div>
      <p class="text-xs text-slate-500 mt-1">len("ЕГЭ") -> 3</p>
    </div>
    <div class="text-[11px] font-bold text-amber-700 bg-amber-50 rounded-lg p-1.5 mt-2 border border-amber-200">
      Количество элементов
    </div>
  </div>
</div>

## Синтаксис и наглядная визуальная схема
Функции `min()` и `max()` могут принимать значения двумя способами:
1. **Отдельные переменные через запятую:** `max(a, b, c)` находит наибольшее из чисел `a`, `b` и `c`.
2. **Список значений:** `max([10, 25, 4, 18])` находит максимум среди элементов списка.

Функция `len()` (от английского *length* — длина) считает, сколько символов в строке или сколько элементов в списке:
`len("Python")` вернёт `6`.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-function"></i></span>
    <span>Примеры вызовов встроенных функций</span>
  </div>
  <div class="space-y-2 text-xs font-mono">
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">max(14, 82, 35)</span>
      <span class="text-indigo-600 font-black">-> 82</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">min(14, 82, 35)</span>
      <span class="text-emerald-600 font-black">-> 14</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span class="text-slate-700">len("Информатика")</span>
      <span class="text-purple-600 font-black">-> 11</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Посмотрите, как эти функции упрощают код:

[CODE_RUNNER title="Применение min, max и len" input="" output="Минимум из чисел: 12\\nМаксимум из чисел: 95\\nДлина слова: 6"]
a = 45
b = 12
c = 95

# Находим наименьшее и наибольшее число
minimum = min(a, b, c)
maximum = max(a, b, c)

print("Минимум из чисел:", minimum)
print("Максимум из чисел:", maximum)

# Длина текстовой строки
word = "Привет"
print("Длина слова:", len(word))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-3 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Переопределение встроенного имени</div>
      <p class="text-xs text-slate-600 leading-relaxed">Никогда не называйте переменные min, max, sum или len! Вы затрёте стандартную функцию.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">max = 100     # Опасно!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">max_val = 100 # Безопасно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">len() от числа вызывает ошибку</div>
      <p class="text-xs text-slate-600 leading-relaxed">Функция len() работает со строками и списками. Вызов len(2026) вызовет TypeError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">len(2026)      # TypeError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">len(str(2026)) # 4 (цифры)</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №3</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">?</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Пустой вызов функции</div>
      <p class="text-xs text-slate-600 leading-relaxed">Вызовы min() и max() без аргументов вызовут TypeError: expected at least 1 argument.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">max()        # TypeError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">max(a, b, c) # Верно</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p108-q1" question="Что выведет следующий фрагмент программы?

a = 15
b = 40
c = 8
print(min(a, b, c))" options="15|8|40|3" answer="8" hint="Функция min() ищет наименьшее число среди переданных аргументов: сравни числа 15, 40 и 8." explanation="Функция min(15, 40, 8) выбирает наименьшее из переданных чисел, то есть 8."]
[CHECKPOINT key="p108-q2" question="Какое значение вернёт вызов len('ЕГЭ-2026')?" options="9|8|7|4" answer="8" hint="Посчитай абсолютно все символы в строке по порядку, не забывая про дефис." explanation="Функция len() считает все символы в строке, включая дефис и цифры: 'Е', 'Г', 'Э', '-', '2', '0', '2', '6' — ровно 8 символов."]
"""
    }
}
