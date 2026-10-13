# -*- coding: utf-8 -*-
"""
Модуль 6: Списки (массивы) и методы коллекций (Темы 122-126).
Понятное объяснение map(), zero jargon, подсказки к микро-проверкам и перемешанные ответы.
"""

MOD6_TOPICS = {
    122: {
        "title": "Списки в Python: создание, индексация, срезы и изменение элементов",
        "description": "Изменяемые коллекции mutable, хранение данных заданий 17, 24, 26 и ловушка поверхностного копирования.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Список (`list`) в Python заменяет собой массивы других языков программирования.
В ЕГЭ списки используются повсеместно:
- Загрузка числовых рядов из файлов в заданиях №17, №24, №26, №27;
- Накопление найденных решений и их сортировка;
- Динамические таблицы для поиска оптимальных цепочек.

## Синтаксис и наглядная визуальная схема
В отличие от строк, списки являются **изменяемыми** (mutable): элементы внутри списка можно заменять по их индексу напрямую.

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-emerald-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-4 flex items-center gap-2">
    <i class="ph-bold ph-pencil-simple text-emerald-600 text-sm"></i> Модификация элемента списка по индексу
  </div>
  <div class="flex flex-wrap items-center justify-around gap-4 text-xs">
    <div class="p-4 rounded-xl bg-white border-2 border-slate-200 text-center font-mono shadow-sm">
      <span class="text-slate-500 text-[11px] block font-sans mb-1">До изменения</span>
      <span class="text-indigo-900 font-bold text-sm">[10, 20, 30]</span>
    </div>
    <div class="text-emerald-700 font-black text-sm bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-xl shadow-xs">
      nums[1] = 99 ➔
    </div>
    <div class="p-4 rounded-xl bg-white border-2 border-emerald-300 text-center font-mono shadow-sm">
      <span class="text-emerald-800 text-[11px] block font-sans mb-1 font-bold">После: элемент заменён</span>
      <span class="text-emerald-700 font-bold text-sm">[10, 99, 30]</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Создание, индексация и срез списка:

[CODE_RUNNER title="Работа со списком" input="" output="Исходный список: [10, 20, 30, 40]\\nИзмененный список: [10, 99, 30, 40]\\nПервые два элемента: [10, 99]"]
nums = [10, 20, 30, 40]
print("Исходный список:", nums)

# Прямая замена элемента по индексу 1
nums[1] = 99
print("Измененный список:", nums)
print("Первые два элемента:", nums[:2])
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Копирование списков (Поверхностная ссылка)</div>
      <p class="text-xs text-slate-600 leading-relaxed">Запись b = a не создаёт копию, а даёт второе имя тому же списку! Для копии используйте срез b = a[:] или b = a.copy().</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">b = a     # Ссылка на оригинал</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">b = a[:]  # Настоящая копия</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">IndexError при добавлении</div>
      <p class="text-xs text-slate-600 leading-relaxed">Нельзя присвоить a[5] = 10, если в списке только 3 элемента. Новые элементы добавляются через append().</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">a.append(10) # Добавить в конец</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p122-q1" question="Что выведет следующий фрагмент программы?

a = [1, 2]
b = a
b[0] = 99
print(a[0])" options="1|99|IndexError|None" answer="99" hint="Вспомните: присваивание b = a копирует сам список или лишь создаёт второе имя для того же самого объекта в памяти?" explanation="Присваивание b = a создаёт ссылку на один и тот же список в памяти. Изменение b[0] изменяет тот же список, на который ссылается переменная a, поэтому a[0] станет 99."]
[CHECKPOINT key="p122-q2" question="Как создать независимую копию списка a?" options="b = a|b = a[:]|b = list + a|b = [a]" answer="b = a[:]" hint="Срез без указания начального и конечного индекса [:] создаёт новый независимый список-копию." explanation="Срез списка a[:] создает новый независимый объект списка с теми же элементами в памяти."]
"""
    },
    123: {
        "title": "Добавление и удаление элементов: .append(), .pop(), .remove(), .clear()",
        "description": "Динамическое наполнение списков результатов в задании 17, удаление элементов и методы коллекций.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В задачах №17, №24 и №25 число подходящих элементов неизвестно заранее.
Вы создаете пустой список `ans = []` и в процессе перебора пополняете его подходящими значениями через `.append()`. В конце ответ дадут `len(ans)` (количество) и `max(ans)` (максимум).

## Синтаксис и наглядная визуальная схема
Основные методы управления элементами списка:

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-stack-plus text-indigo-600 text-sm"></i> Методы добавления и удаления элементов
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <div><code class="text-emerald-800 font-bold font-mono">a.append(x)</code> — добавить элемент в конец списка</div>
      <span class="text-emerald-700 font-mono font-bold bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">[1, 2] ➔ [1, 2, x]</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-purple-200 shadow-sm flex items-center justify-between">
      <div><code class="text-purple-800 font-bold font-mono">a.pop()</code> — извлечь и вернуть последний элемент</div>
      <span class="text-purple-700 font-mono font-bold bg-purple-50 px-2.5 py-1 rounded border border-purple-200">[1, 2, 3] ➔ удалит 3</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-rose-200 shadow-sm flex items-center justify-between">
      <div><code class="text-rose-800 font-bold font-mono">a.remove(val)</code> — удалить первое значение val</div>
      <span class="text-rose-700 font-mono font-bold bg-rose-50 px-2.5 py-1 rounded border border-rose-200">Удаляет по значению</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Классический алгоритм накопления ответов для задания №17:

[CODE_RUNNER title="Накопление результатов через .append()" input="" output="Найденные результаты: [12, 24, 36]\\nКоличество: 3\\nМаксимум: 36"]
results = []

for x in range(10, 40):
    if x % 12 == 0:
        results.append(x)

print("Найденные результаты:", results)
print("Количество:", len(results))
print("Максимум:", max(results))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 p-4 rounded-xl bg-rose-50/70 border border-rose-200 text-xs text-rose-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-rose-800">
    <i class="ph-bold ph-warning"></i> Метод .append() изменяет список на месте и возвращает None:
  </div>
  Никогда не пишите <code>results = results.append(x)</code>! Метод вернет <code>None</code>, и переменная <code>results</code> превратится в <code>None</code>, уничтожив весь список! Пишите просто: <code>results.append(x)</code>.
</div>

## Микро-проверки
[CHECKPOINT key="p123-q1" question="Что произойдет в результате выполнения следующего фрагмента программы?

a = [1, 2]
a = a.append(3)" options="a станет [1, 2, 3]|a станет равно None|TypeError|a станет [3]" answer="a станет равно None" hint="Обратите внимание: метод .append() изменяет список на месте и ничего не возвращает (его возвращаемое значение — None)." explanation="Метод append() модифицирует список на месте и возвращает значение None. Поэтому ошибочное присваивание a = a.append(3) затирает список и превращает переменную a в None."]
[CHECKPOINT key="p123-q2" question="Какой метод удаляет и возвращает последний элемент списка?" options="remove()|pop()|delete()|clear()" answer="pop()" hint="Вспомните метод с коротким названием из трёх букв, который 'выталкивает' элемент с конца списка." explanation="pop() без аргументов удаляет последний элемент списка и возвращает его значение."]
"""
    },
    124: {
        "title": "Поиск и сортировка списков: .count(), .index(), .sort() против sorted()",
        "description": "Сортировка по возрастанию и убыванию reverse=True, жадные алгоритмы для задания №26.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Сортировка данных — ядро **Задания №26** (жадные алгоритмы: упаковка максимального числа грузов в архив, распределение свободных мест, посадка пассажиров).
Умение отсортировать сотни тысяч чисел за доли секунды гарантирует решение задачи 26.

## Синтаксис и наглядная визуальная схема
Различие между методом `.sort()` и функцией `sorted()`:

<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 font-sans">
  <div class="p-5 rounded-2xl bg-gradient-to-br from-indigo-50/80 via-white to-indigo-50/30 border-2 border-indigo-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-indigo-700 font-black text-sm uppercase">
      <i class="ph-bold ph-sort-ascending text-indigo-600 text-base"></i> Метод a.sort()
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• Сортирует исходный список <b class="text-indigo-900">на месте</b> (in-place).</div>
      <div>• Не расходует дополнительную память.</div>
      <div>• Возвращает <code>None</code>.</div>
      <div>• По убыванию: <code>a.sort(reverse=True)</code></div>
    </div>
  </div>

  <div class="p-5 rounded-2xl bg-gradient-to-br from-purple-50/80 via-white to-purple-50/30 border-2 border-purple-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-purple-700 font-black text-sm uppercase">
      <i class="ph-bold ph-arrows-down-up text-purple-600 text-base"></i> Функция sorted(a)
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• Создает и возвращает <b class="text-purple-900">новый отсортированный список</b>.</div>
      <div>• Исходный список <code>a</code> остаётся без изменений.</div>
      <div>• Работает с любыми коллекциями (строками, списками).</div>
    </div>
  </div>
</div>

## Примеры кода и результат
Жадный алгоритм упаковки грузов в архив (модель задания №26):

[CODE_RUNNER title="Сортировка и жадный алгоритм (ЕГЭ 26)" input="" output="Отсортированные веса грузов: [10, 15, 20, 25, 50]\\nПоместилось грузов: 3\\nСуммарный вес: 45 из 50"]
capacity = 50
weights = [25, 10, 50, 15, 20]

# Сортируем грузы по возрастанию для максимизации количества
weights.sort()
print("Отсортированные веса грузов:", weights)

packed = []
current_sum = 0
for w in weights:
    if current_sum + w <= capacity:
        packed.append(w)
        current_sum += w

print(f"Поместилось грузов: {len(packed)}")
print(f"Суммарный вес: {current_sum} из {capacity}")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">a = a.sort() затирает данные</div>
      <p class="text-xs text-slate-600 leading-relaxed">Метод .sort() возвращает None. Присваивание a = a.sort() превратит a в None! Пишите просто a.sort().</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">a.sort() # Правильно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Скорость</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">⚡</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Никаких ручных пузырьков</div>
      <p class="text-xs text-slate-600 leading-relaxed">Встроенная сортировка a.sort() работает на ультрабыстром алгоритме Timsort. Ручная сортировка на 100 000 чисел зависнет на 20 минут!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold">a.sort() выполняется за 0.05 с</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p124-q1" question="Как отсортировать список nums по убыванию на месте?" options="sorted(nums, reverse=True)|nums.sort(reverse=True)|nums.reverse()|nums.sort(-1)" answer="nums.sort(reverse=True)" hint="Чтобы отсортировать список на месте, вызывается метод .sort(), а для обратного порядка передаётся именованный аргумент reverse=True." explanation="Метод sort() с параметром reverse=True сортирует список по убыванию на месте."]
[CHECKPOINT key="p124-q2" question="Что возвращает вызов nums.sort()?" options="Новый отсортированный список|None|Количество элементов|Длину списка" answer="None" hint="Методы, которые изменяют объект на месте (in-place), в Python возвращают пустое значение None." explanation="Метод .sort() модифицирует список на месте и возвращает None."]
"""
    },
    125: {
        "title": "Функции len(), min(), max(), sum() и применение map() к спискам",
        "description": "Агрегация числовых списков, чтение данных через list(map(int, ...)) и мгновенные вычисления ответов.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Задание №17 ЕГЭ часто завершается фразой:
*«В ответе запишите количество найденных пар, затем максимальную из сумм элементов таких пар»*.
Вместо ручного отслеживания максимума в цикле вы сохраняете все подходящие суммы в список `pairs` и в конце выводите:
`print(len(pairs), max(pairs))`.

## Синтаксис и наглядная визуальная схема
Функция `map(функция, коллекция)` берет каждый элемент коллекции и применяет к нему указанную функцию (например, переводит строки в числа через `int`). Это избавляет от необходимости писать отдельный цикл `for`.

Каноничный шаблон для чтения чисел из строки:
<div class="my-4 p-4 rounded-2xl bg-slate-900 border-2 border-slate-700 text-center font-mono text-sm sm:text-base font-bold text-emerald-400 shadow-sm">
  nums = list(map(int, s.split()))
</div>

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-cyan-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-cyan-800 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-arrows-split text-cyan-600 text-sm"></i> Как работает связка list(map(int, s.split())):
  </div>
  <div class="space-y-2 text-xs">
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span>1. Строка текста: <code class="font-bold text-slate-700">"10 25 42"</code></span>
      <span class="text-slate-500">исходные данные</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span>2. s.split() ➔ <code class="font-bold text-indigo-700">['10', '25', '42']</code></span>
      <span class="text-indigo-600 font-bold">разбили на строки</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-slate-200 flex items-center justify-between">
      <span>3. map(int, ...) ➔ применяет int к каждому элементу</span>
      <span class="text-cyan-700 font-bold">перевели в числа</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border border-emerald-300 flex items-center justify-between bg-emerald-50/30">
      <span>4. list(...) ➔ <code class="font-bold text-emerald-700">[10, 25, 42]</code></span>
      <span class="text-emerald-700 font-black">готовый список чисел!</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Вычисление статистических параметров списка:

[CODE_RUNNER title="Агрегатные функции над списком" input="" output="Количество: 5\\nМинимум: -7, Максимум: 42\\nСумма элементов: 75\\nСреднее арифметическое: 15.0"]
nums = [10, 42, -7, 15, 15]

print("Количество:", len(nums))
print(f"Минимум: {min(nums)}, Максимум: {max(nums)}")
print("Сумма элементов:", sum(nums))
print("Среднее арифметическое:", sum(nums) / len(nums))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 p-4 rounded-xl bg-amber-50/70 border border-amber-200 text-xs text-amber-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-amber-800">
    <i class="ph-bold ph-warning"></i> map возвращает одноразовый объект-итератор:
  </div>
  Если написать <code>m = map(int, s.split())</code>, то после одного прохода генератор исчерпается. Чтобы получить список для многократного использования (нахождения min, max, len), обязательно оборачивайте результат в <code>list()</code>: <code>nums = list(map(int, s.split()))</code>.
</div>

## Микро-проверки
[CHECKPOINT key="p125-q1" question="Чему равно выражение sum([10, 20, 30]) // len([10, 20, 30])?" options="20.0|20|60|3" answer="20" hint="Сложите все числа: 10 + 20 + 30 = 60. Затем выполните целочисленное деление // на количество элементов (3)." explanation="sum равен 60, len равен 3. Целочисленное деление 60 // 3 дает целое число 20."]
[CHECKPOINT key="p125-q2" question="Что вернёт вызов type(map(int, ['1', '2']))?" options="<class 'list'>|<class 'map'>|<class 'int'>|TypeError" answer="<class 'map'>" hint="Функция map() возвращает итератор собственного типа map, который нужно явно обернуть в list() для превращения в обычный список." explanation="Функция map возвращает специальный объект-генератор map, требующий вызова list() для превращения в список."]
"""
    },
    126: {
        "title": "Генераторы списков (List Comprehensions) и фильтрация данных",
        "description": "Синтаксис [выражение for x in a if условие], сжатие циклов в 1 строку и скоростная обработка файлов.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Генераторы списков (List Comprehensions) позволяют писать лаконичный и быстрый код в одну строку:
- Чтение всех чисел из файла: `nums = [int(line) for line in open('17.txt')]`;
- Выделение всех четных элементов: `evens = [x for x in nums if x % 2 == 0]`;
- Получение квадратов чисел или длин строк.

## Синтаксис и наглядная визуальная схема
Базовая структура генератора списка:
<div class="my-4 p-4 rounded-2xl bg-slate-900 border-2 border-slate-700 text-center font-mono text-sm sm:text-base font-bold text-purple-300 shadow-sm">
  [выражение for x in коллекция if условие]
</div>

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-brackets-curly text-indigo-600 text-sm"></i> Анатомия генератора: [x**2 for x in nums if x > 0]
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="text-indigo-900 font-bold font-mono bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">1. for x in nums</span>
      <span class="text-slate-600 font-medium">Перебирает каждый элемент списка</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-purple-200 shadow-sm flex items-center justify-between">
      <span class="text-purple-900 font-bold font-mono bg-purple-50 px-2 py-0.5 rounded border border-purple-200">2. if x > 0</span>
      <span class="text-slate-600 font-medium">Фильтрует: оставляет только подходящие</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <span class="text-emerald-900 font-bold font-mono bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">3. x ** 2</span>
      <span class="text-slate-600 font-medium">Трансформирует: вычисляет значение для результата</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Фильтрация и трансформация данных генератором списков:

[CODE_RUNNER title="Генераторы списков" input="" output="Исходные данные: [-5, 12, 0, 7, -2, 14]\\nКвадраты четных положительных: [144, 196]\\nКоличество подходящих: 2"]
data = [-5, 12, 0, 7, -2, 14]

# Оставляем только четные положительные числа и возводим в квадрат
result = [x ** 2 for x in data if x > 0 and x % 2 == 0]

print("Исходные данные:", data)
print("Квадраты четных положительных:", result)
print("Количество подходящих:", len(result))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 p-4 rounded-xl bg-indigo-50/70 border border-indigo-200 text-xs text-indigo-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-indigo-800">
    <i class="ph-bold ph-warning"></i> Порядок if и for:
  </div>
  Если вы просто фильтруете элементы, <code>if</code> ставится в <b>самом конце</b>: <code>[x for x in a if x > 0]</code>.<br>
  Если вы используете тернарный оператор выбора значения (<code>if-else</code>), он ставится <b>в начале</b>: <code>[x if x > 0 else 0 for x in a]</code>.
</div>

## Микро-проверки
[CHECKPOINT key="p126-q1" question="Что сгенерирует выражение [x * 2 for x in range(4)]?" options="[2, 4, 6, 8]|[0, 2, 4, 6]|[0, 1, 2, 3]|[0, 2, 4]" answer="[0, 2, 4, 6]" hint="range(4) генерирует числа 0, 1, 2, 3. Умножьте каждое из них на 2." explanation="range(4) дает 0, 1, 2, 3. Умножение каждого числа на 2 дает [0, 2, 4, 6]."]
[CHECKPOINT key="p126-q2" question="Какое выражение оставит в списке только числа, оканчивающиеся на 5?" options="[x for x in nums if x % 5 == 0]|[x for x in nums if x % 10 == 5]|[x % 5 for x in nums]|[if x % 10 == 5 for x in nums]" answer="[x for x in nums if x % 10 == 5]" hint="Какая операция выделяет последнюю цифру числа и сравнивает её с 5?" explanation="x % 10 == 5 проверяет последнюю цифру с фильтрацией if в конце генератора списка."]
"""
    }
}
