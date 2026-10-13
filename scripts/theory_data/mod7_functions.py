# -*- coding: utf-8 -*-
"""
Модуль 7: Функции и подпрограммы (Темы 127-130).
Устранение опережающих ссылок, подсказки к микро-проверкам и перемешанные ответы.
"""

MOD7_TOPICS = {
    127: {
        "title": "Объявление функций: синтаксис def, параметры и аргументы",
        "description": "Ключевое слово def, параметры, передача аргументов и декомпозиция сложных задач ЕГЭ.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Функции позволяют разбить сложную экзаменационную задачу на простые и понятные части (декомпозиция).
Вместо того чтобы 10 раз копировать один и тот же алгоритм в разные части программы, вы один раз объявляете функцию и затем вызываете её одной строкой:
- Функция подсчета суммы цифр числа;
- Функция перевода в любую систему счисления;
- Функция проверки условий делимости в заданиях №17 и №25.

## Синтаксис и наглядная визуальная схема
Функция объявляется с помощью ключевого слова `def` (от англ. *define* — определить):

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-code text-indigo-600 text-sm"></i> Анатомия объявления функции: def calc(a, b):
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="text-purple-700 font-mono font-bold bg-purple-50 px-2 py-0.5 rounded border border-purple-200">def</span>
      <span class="text-slate-600 font-medium">Служебное слово объявления функции</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="text-emerald-700 font-mono font-bold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">calc</span>
      <span class="text-slate-600 font-medium">Имя функции (по правилам именования переменных)</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="text-amber-800 font-mono font-bold bg-amber-50 px-2 py-0.5 rounded border border-amber-200">(a, b):</span>
      <span class="text-slate-600 font-medium">Параметры функции в круглых скобках и двоеточие</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="text-indigo-900 font-mono font-bold bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200 ml-3">return a + b</span>
      <span class="text-slate-600 font-medium">Тело функции с отступом 4 пробела</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Создание и вызов функции суммы цифр:

[CODE_RUNNER title="Объявление и вызов функции" input="" output="Сумма цифр числа 458: 17\\nСумма цифр числа 1024: 7"]
def sum_digits(n):
    total = 0
    while n > 0:
        total += n % 10
        n //= 10
    return total

# Вызовы функции с разными аргументами
print("Сумма цифр числа 458:", sum_digits(458))
print("Сумма цифр числа 1024:", sum_digits(1024))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Вызов функции до её объявления</div>
      <p class="text-xs text-slate-600 leading-relaxed">Python читает файл сверху вниз. Если вызвать f() выше строчки def f():, программа упадет с ошибкой NameError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">f()      # NameError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">def f(): # Сначала объявление</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Значения аргументов по умолчанию</div>
      <p class="text-xs text-slate-600 leading-relaxed">Параметры со значениями по умолчанию def f(x, p=2) обязаны стоять строго в самом конце списка параметров.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">def f(x, p=2): # Верно</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p127-q1" question="Какое ключевое слово используется для создания функции в Python?" options="function|def|func|fn" answer="def" hint="Ключевое слово происходит от английского слова define (определить)." explanation="В Python функции объявляются служебным словом def."]
[CHECKPOINT key="p127-q2" question="Что произойдёт, если вызвать функцию выше места её объявления в коде программы?" options="Функция сработает корректно|Ошибка NameError|Ошибка TypeError|Предупреждение" answer="Ошибка NameError" hint="Интерпретатор Python читает код построчно сверху вниз. Если вызвать функцию до def, известно ли уже её имя?" explanation="Интерпретатор еще не встретил строку def, поэтому имя функции не определено в текущей области видимости, что вызывает NameError."]
"""
    },
    128: {
        "title": "Оператор return и возврат значения",
        "description": "Разница между return и print(), мгновенный выход из функции и возврат нескольких значений.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Частая ошибка начинающих — путать печать на экран (`print`) и возврат значения из функции (`return`).
Если функция только печатает ответ через `print()`, её результат нельзя сохранить в переменную, нельзя передать в `min()`, `max()` или использовать в условии `if`.

## Синтаксис и наглядная визуальная схема
Оператор `return` немедленно **завершает** работу функции и передает вычисленный результат обратно в точку вызова.

<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 font-sans">
  <div class="p-5 rounded-2xl bg-gradient-to-br from-rose-50/80 via-white to-rose-50/30 border-2 border-rose-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-rose-700 font-black text-sm uppercase">
      <i class="ph-bold ph-desktop text-rose-600 text-base"></i> print() — вывод на экран
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• Показывает символы в окне консоли.</div>
      <div>• Ничего не возвращает (результат равен <code>None</code>).</div>
      <div>• Значение нельзя сохранить: <code>x = print(5) ➔ x равен None</code>!</div>
    </div>
  </div>

  <div class="p-5 rounded-2xl bg-gradient-to-br from-emerald-50/80 via-white to-emerald-50/30 border-2 border-emerald-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-emerald-700 font-black text-sm uppercase">
      <i class="ph-bold ph-arrow-u-up-left text-emerald-600 text-base"></i> return — возврат значения
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• Передает результат вызывающей программе.</div>
      <div>• Результат можно сохранить: <code>res = func(5)</code>.</div>
      <div>• Немедленно завершает выполнение функции.</div>
    </div>
  </div>
</div>

## Примеры кода и результат
Демонстрация возврата значения и досрочного выхода:

[CODE_RUNNER title="Оператор return" input="" output="Вычисленный результат: 25\\nВозврат нескольких значений: частное=7 остаток=2"]
def square(x):
    return x * x

result = square(5)
print("Вычисленный результат:", result)

# Возврат двух значений через запятую
def divide(a, b):
    return a // b, a % b

q, r = divide(23, 3)
print(f"Возврат нескольких значений: частное={q} остаток={r}")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Мертвый код после return</div>
      <p class="text-xs text-slate-600 leading-relaxed">Любые команды внутри функции, написанные ниже строки с return, никогда не выполнятся.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">return x; print("Done") # Не дойдет</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытый return</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если в функции нет return, она возвращает None. Попытка сложить func() + 5 вызовет TypeError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">None + 5 ➔ TypeError</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p128-q1" question="Что вернет вызов функции: def f(x): print(x * 2)?" options="Число x * 2|None|Строку|0" answer="None" hint="Функция лишь выводит значение на экран через print, но не содержит оператора return. Какое специальное пустое значение возвращается по умолчанию?" explanation="Если в функции отсутствует оператор return, она неявно возвращает специальное значение None."]
[CHECKPOINT key="p128-q2" question="Что происходит при выполнении строки с оператором return в теле функции?" options="Функция выводит текст на экран|Функция немедленно завершает работу и отдает значение|Функция перезапускается|Ничего не происходит" answer="Функция немедленно завершает работу и отдает значение" hint="Оператор return передаёт вычисленное значение наружу и мгновенно выходит из тела функции." explanation="return прерывает выполнение функции и возвращает вычисленное значение вызывающей программе."]
"""
    },
    129: {
        "title": "Функции-предикаты: проверка свойств чисел в ЕГЭ (делители, простота)",
        "description": "Функции, возвращающие bool, алгоритм проверки простоты числа за O(√N) для задания №25.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
**Функция-предикат** — это функция, которая отвечает на вопрос «Да или Нет?», возвращая логическое значение `True` или `False`.
В заданиях №17 и №25 такие функции незаменимы:
- `is_prime(n)` : простое ли число?
- `check_mask(n)` : подходит ли число под маску?
- `is_palindrome(s)` : является ли строка палиндромом?

## Синтаксис и наглядная визуальная схема
Канонический скоростной алгоритм проверки простоты числа: перебирать делители нужно **не до N, а только до √N**!

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-emerald-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-lightning text-emerald-600 text-sm"></i> Оптимизация перебора делителей: до корня из N
  </div>
  <div class="text-xs text-slate-700 leading-relaxed p-3.5 bg-white rounded-xl border border-emerald-200 shadow-sm space-y-1.5">
    <div>• Все делители числа ходят парами: если число 100 делится на 4, то парный делитель 25.</div>
    <div>• Один из делителей пары <b class="text-emerald-900">всегда меньше или равен √N</b>.</div>
    <div>• Поэтому цикл <code>range(2, int(n**0.5) + 1)</code> делает всего 1 000 шагов для числа в 1 000 000 вместо миллиона шагов!</div>
  </div>
</div>

## Примеры кода и результат
Боевая функция проверки простоты числа для задания №25:

[CODE_RUNNER title="Функция-предикат is_prime" input="" output="Число 101 простое: True\\nЧисло 119 простое: False\\nПростые числа от 50 до 70: [53, 59, 61, 67]"]
def is_prime(n):
    if n < 2:
        return False
    # Перебор делителей только до квадратного корня!
    for d in range(2, int(n ** 0.5) + 1):
        if n % d == 0:
            return False
    return True

print("Число 101 простое:", is_prime(101))
print("Число 119 простое:", is_prime(119))

primes = [x for x in range(50, 71) if is_prime(x)]
print("Простые числа от 50 до 70:", primes)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Числа 0 и 1 не являются простыми</div>
      <p class="text-xs text-slate-600 leading-relaxed">Обязательно проверяйте if n < 2: return False. Простое число строго больше 1 и имеет ровно 2 делителя.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">if n < 2: return False</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Правая граница корня в range()</div>
      <p class="text-xs text-slate-600 leading-relaxed">Не забывайте писать int(n**0.5) + 1. Без + 1 для чисел 9, 25, 49 корень выпадет из проверки!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">range(2, int(n**0.5) + 1)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p129-q1" question="До какого значения достаточно перебирать возможные делители числа N для проверки его простоты?" options="До N // 2|До квадратного корня из N|До N - 1|До N / 10" answer="До квадратного корня из N" hint="Делители числа ходят парами: если один делитель больше квадратного корня, то парный ему обязательно меньше корня." explanation="Если у числа есть делитель больше корня, то парный ему делитель обязательно меньше корня. Поэтому достаточно проверить делители только до корня из N."]
[CHECKPOINT key="p129-q2" question="Является ли число 1 простым по математическому определению?" options="Да, оно делится только на себя|Нет, простые числа строго больше 1|Зависит от задачи|Да" answer="Нет, простые числа строго больше 1" hint="Вспомните определение: простое число имеет ровно два различных натуральных делителя: 1 и само себя. Сколько делителей у числа 1?" explanation="Число 1 имеет только один натуральный делитель (единицу), поэтому по математическому определению не является ни простым, ни составным."]
"""
    },
    130: {
        "title": "Область видимости переменных: локальные и глобальные переменные",
        "description": "Правило видимости Scope, изоляция локальных переменных функций и ключевое слово global.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Понимание области видимости (Scope) защищает от случайных затираний данных:
- Переменные циклов `i, j` внутри функций не должны портить переменные основной программы;
- В задании №16 (рекурсивные функции и сохранение промежуточных результатов) часто требуется накопление в глобальный список ответов.

## Синтаксис и наглядная визуальная схема
Переменные, созданные внутри функции, называются **локальными**. Они существуют только во время выполнения этой функции и уничтожаются после её завершения.

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-shield-check text-indigo-600 text-sm"></i> Изоляция памяти (Global Scope vs Local Scope)
  </div>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="font-bold text-indigo-900 block mb-1">Глобальная область (Вне функций)</span>
      <span class="text-slate-600">Переменная <code>x = 100</code> видна во всей программе для чтения.</span>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-purple-200 shadow-sm">
      <span class="font-bold text-purple-900 block mb-1">Локальная область (Внутри def)</span>
      <span class="text-slate-600">Переменная <code>x = 5</code> внутри функции изолирована и не меняет внешнее значение.</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Демонстрация независимости локальных переменных:

[CODE_RUNNER title="Локальные и глобальные переменные" input="" output="Внутри функции a = 99\\nВ основной программе a = 10 (не изменилась!)"]
a = 10

def modify():
    a = 99 # локальная переменная a!
    print("Внутри функции a =", a)

modify()
print("В основной программе a =", a, "(не изменилась!)")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Ошибка UnboundLocalError</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если внутри def вы читаете print(x), а строкой ниже делаете x = 20, Python посчитает x локальной во всей функции и выдаст ошибку!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">UnboundLocalError</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ключевое слово</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">★</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Как изменить глобальную переменную</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если внутри функции нужно изменить внешнюю переменную, объявите её через global x.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold">global x # Разрешить запись</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p130-q1" question="Что выведет следующий фрагмент программы?

x = 5

def f():
    x = 10

f()
print(x)" options="10|5|None|UnboundLocalError" answer="5" hint="Переменная x = 10 внутри функции f() является локальной. Влияет ли она на глобальную переменную x снаружи функции?" explanation="Присваивание x = 10 внутри функции f() создаёт локальную переменную x, которая никак не меняет внешнюю глобальную переменную x = 5."]
[CHECKPOINT key="p130-q2" question="Какое служебное слово разрешает функции изменять значение внешней (глобальной) переменной?" options="nonlocal|global|public|external" answer="global" hint="Вспомните служебное слово, означающее 'глобальный', которое указывает, что переменная относится ко всей программе." explanation="Инструкция global x объявляет переменную x глобальной внутри тела функции, разрешая её перезапись."]
"""
    }
}
