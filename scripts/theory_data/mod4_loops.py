# -*- coding: utf-8 -*-
"""
Модуль 4: Циклы и переборные алгоритмы (Темы 113-117).
Актуальные шаблоны ЕГЭ, подсказки к микро-проверкам и перемешанные варианты ответов.
"""

MOD4_TOPICS = {
    113: {
        "title": "Цикл for и функция range()",
        "description": "Параметры range (start, stop, step), не включение правой границы и обратный перебор.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Цикл `for` в связке с `range()` — это главный инструмент перебора в компьютерном ЕГЭ.
Он используется для:
- Перебора чисел диапазона в задании №25 (поиск делителей от 100 000 до 200 000);
- Перебора оснований систем счисления в задании №14;
- Перебора логических переменных x, y, z, w в задании №2;
- Обхода индексов и элементов в задании №17.

## Синтаксис и наглядная визуальная схема
Функция `range()` генерирует арифметическую прогрессию целых чисел.

<div class="my-6 p-5 sm:p-6 rounded-2xl border-2 border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 shadow-[0_4px_0_#DAE1E9]">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs"><i class="ph-bold ph-arrows-clockwise"></i></span>
    <span>Три формы вызова функции range()</span>
  </div>
  <div class="space-y-2.5 text-xs pt-1">
    <div class="p-3.5 rounded-xl bg-white border-2 border-indigo-200/80 shadow-[0_2px_0_#DAE1E9] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <div><span class="font-mono text-indigo-700 font-black text-sm">range(N)</span> — от 0 до N-1</div>
      <code class="text-indigo-900 font-bold bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">range(5) ➔ 0, 1, 2, 3, 4</code>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-purple-200/80 shadow-[0_2px_0_#E9D5FF] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <div><span class="font-mono text-purple-700 font-black text-sm">range(start, stop)</span> — [start; stop)</div>
      <code class="text-purple-900 font-bold bg-purple-50 px-2 py-0.5 rounded border border-purple-200">range(2, 6) ➔ 2, 3, 4, 5</code>
    </div>
    <div class="p-3.5 rounded-xl bg-white border-2 border-emerald-200/80 shadow-[0_2px_0_#D1FAE5] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
      <div><span class="font-mono text-emerald-700 font-black text-sm">range(start, stop, step)</span> — с шагом step</div>
      <code class="text-emerald-900 font-bold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">range(10, 0, -2) ➔ 10, 8, 6, 4, 2</code>
    </div>
  </div>
</div>

<div class="my-6 p-4 rounded-xl bg-indigo-50/70 border border-indigo-200 text-xs text-indigo-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-indigo-800">
    <i class="ph-bold ph-warning"></i> Главное правило правой границы:
  </div>
  Правая граница <code>stop</code> в <code>range()</code> <b>НИКОГДА не включается</b>! Чтобы перебрать числа от 1 до 100 включительно, обязательно пишите <code>range(1, 101)</code>.
</div>

## Примеры кода и результат
Прямой и обратный перебор с шагом:

[CODE_RUNNER title="Примеры работы цикла for" input="" output="Число: 2\nЧисло: 4\nЧисло: 6\nЧисло: 8\nОбратный отсчет: 3\nОбратный отсчет: 2\nОбратный отсчет: 1"]
# 1. Четные числа от 2 до 8 с шагом 2
for i in range(2, 10, 2):
    print("Число:", i)

# 2. Обратный перебор от 3 до 1 с шагом -1
for i in range(3, 0, -1):
    print("Обратный отсчет:", i)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Пустой диапазон при обратном счёте</div>
      <p class="text-xs text-slate-600 leading-relaxed">Запись range(10, 1) не сделает ни шага, так как шаг по умолчанию +1. Обязательно указывайте отрицательный шаг -1.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">range(10, 1)     # 0 итераций!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">range(10, 1, -1) # 10, 9, ..., 2</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Дробные числа в range()</div>
      <p class="text-xs text-slate-600 leading-relaxed">Все аргументы range обязаны быть целыми int. Передача float range(1.5, 10) вызовет TypeError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">range(1.5, 5) # TypeError</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p113-q1" question="Сколько итераций сделает цикл for i in range(1, 10)?" options="10|9|11|8" answer="9" hint="Помните, что правая граница в range() не включается: перебираются числа от 1 до 9." explanation="Числа от 1 до 9 включительно (10 не входит). Всего 10 - 1 = 9 чисел."]
[CHECKPOINT key="p113-q2" question="Какое выражение сгенерирует числа 10, 8, 6, 4, 2?" options="range(10, 2, -2)|range(10, 1, -2)|range(10, 0, 2)|range(2, 10, -2)" answer="range(10, 1, -2)" hint="При обратном счете правая граница stop также не включается. Чтобы число 2 вошло, stop должен быть строго меньше 2 (например, 1)." explanation="range(10, 1, -2) стартует с 10, идёт с шагом -2 и останавливается строго до 1 (последнее число 2)."]
"""
    },
    114: {
        "title": "Цикл while и динамические условия остановки",
        "description": "Цикл с предусловием, алгоритмы с неизвестным числом шагов и защита от зацикливания.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Когда количество повторений неизвестно заранее, цикл `for` неприменим.
В ЕГЭ цикл `while` необходим для:
- **Задания №12:** алгоритм исполнителя «Редактор» — `while ">1" in s or ">2" in s or ">0" in s:`;
- **Задания №14:** перевод чисел в другие системы счисления — `while n > 0:`;
- **Задания №15 и №23:** подбор неизвестных параметров до выполнения целевого условия.

## Синтаксис и наглядная визуальная схема
Цикл `while` проверяет условие перед каждым шагом. Если условие `True`, тело цикла выполняется. Как только условие становится `False`, цикл завершается.

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-4 flex items-center gap-2">
    <i class="ph-bold ph-git-branch text-indigo-600 text-sm"></i> Блок-схема работы цикла while
  </div>
  <div class="flex flex-col items-center gap-3 text-xs max-w-md mx-auto">
    <div class="px-5 py-2.5 rounded-xl bg-indigo-50 border-2 border-indigo-200 text-indigo-900 font-bold shadow-sm">
      Условие истинно?
    </div>
    <div class="flex items-center gap-4 text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-4 py-2 rounded-xl">
      <span>ДА ➔ Выполнить тело цикла ➔ Возврат к проверке</span>
    </div>
    <div class="text-rose-700 font-bold text-xs bg-rose-50 border border-rose-200 px-4 py-2 rounded-xl">
      НЕТ ➔ Выход из цикла и переход дальше
    </div>
  </div>
</div>

## Примеры кода и результат
Алгоритм деления числа на 2 до единицы с подсчетом шагов:

[CODE_RUNNER title="Цикл while" input="" output="Шаг 1: n = 32\\nШаг 2: n = 16\\nШаг 3: n = 8\\nШаг 4: n = 4\\nШаг 5: n = 2\\nШаг 6: n = 1\\nВсего шагов: 6"]
n = 64
steps = 0

while n > 1:
    n //= 2
    steps += 1
    print(f"Шаг {steps}: n = {n}")

print("Всего шагов:", steps)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Зацикливание (бесконечный цикл)</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если переменная условия не изменяется внутри цикла (например, забыли n //= 10), программа зависнет навсегда.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">while x > 0: print(x) # Зависнет</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">while x > 0: x -= 1   # Завершится</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Экзамен</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Как остановить зависшую программу</div>
      <p class="text-xs text-slate-600 leading-relaxed">В IDLE или PyCharm нажмите сочетание клавиш Ctrl + C в окне консоли или кнопку Stop (красный квадрат).</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold">Ctrl + C (KeyboardInterrupt)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p114-q1" question="Сколько раз выполнится тело следующего цикла?

x = 5
while x > 0:
    x -= 2" options="5 раз|3 раза|2 раза|Бесконечно" answer="3 раза" hint="Проследите за значением x по шагам: сначала x=5, затем x-=2 (становится 3), затем x-=2 (становится 1), затем x-=2 (становится -1). Сколько всего шагов?" explanation="Итерации цикла: 1) x становится 3, 2) x становится 1, 3) x становится -1. После этого условие x > 0 нарушается, и цикл завершается. Всего 3 шага."]
[CHECKPOINT key="p114-q2" question="Что произойдет, если в цикле while условие изначально ложно (False)?" options="Тело цикла выполнится ровно 1 раз|Тело цикла не выполнится ни разу|Ошибка выполнения|Случится зацикливание" answer="Тело цикла не выполнится ни разу" hint="В цикле while проверка условия выполняется ДО входа в тело (предусловие). Если оно сразу ложно, зайдет ли Python внутрь?" explanation="В цикле с предусловием проверка выполняется до первого захода в тело. Если условие False, цикл просто пропускается."]
"""
    },
    115: {
        "title": "Управление циклом: break и continue",
        "description": "Досрочное прерывание цикла break, пропуск итерации continue и оптимизация скорости работы в ЕГЭ.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Оператор `break` спасает программы от долгой работы и зависаний:
- **В задании №15:** при подборе параметра A, как только найдено хотя бы одно контр-значение, продолжать проверку бессмысленно — делаем `break`;
- **В задании №25:** при проверке простоты числа, если найден хотя бы один делитель кроме 1 и самого себя, число гарантированно составное — делаем `break`.

## Синтаксис и наглядная визуальная схема
Различие между `break` и `continue`:

<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 font-sans">
  <div class="p-5 rounded-2xl bg-gradient-to-br from-rose-50/80 via-white to-rose-50/30 border-2 border-rose-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-rose-700 font-black text-sm uppercase">
      <i class="ph-bold ph-stop-circle text-rose-600 text-base"></i> break
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• <b class="text-rose-900">Полностью прерывает</b> выполнение текущего цикла.</div>
      <div>• Управление мгновенно переходит на строку, следующую за циклом.</div>
      <div>• Все оставшиеся итерации отменяются.</div>
    </div>
  </div>

  <div class="p-5 rounded-2xl bg-gradient-to-br from-amber-50/80 via-white to-amber-50/30 border-2 border-amber-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="flex items-center gap-2 text-amber-700 font-black text-sm uppercase">
      <i class="ph-bold ph-arrow-bend-double-up-right text-amber-600 text-base"></i> continue
    </div>
    <div class="mt-3 text-xs text-slate-700 leading-relaxed space-y-1.5">
      <div>• Прерывает <b class="text-amber-900">только текущую итерацию</b>.</div>
      <div>• Немедленно переходит к следующему шагу цикла.</div>
      <div>• Сам цикл продолжает работу со следующим значением.</div>
    </div>
  </div>
</div>

## Примеры кода и результат
Проверка числа на простоту с досрочным выходом через `break`:

[CODE_RUNNER title="Операторы break и continue" input="" output="Число 91 делится на 7, дальше не проверяем!\\nНечетные числа: 1 3 5 7 9"]
n = 91
for d in range(2, 20):
    if n % d == 0:
        print(f"Число {n} делится на {d}, дальше не проверяем!")
        break

# Использование continue для пропуска четных чисел
odd_numbers = []
for i in range(1, 10):
    if i % 2 == 0:
        continue
    odd_numbers.append(str(i))
print("Нечетные числа:", " ".join(odd_numbers))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 p-4 rounded-xl bg-rose-50/70 border border-rose-200 text-xs text-rose-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-rose-800">
    <i class="ph-bold ph-warning"></i> break во вложенных циклах:
  </div>
  Оператор <code>break</code> прерывает <b>только тот один цикл, внутри которого он находится</b>! Если у вас двойной цикл <code>for x: for y:</code>, то <code>break</code> внутри <code>y</code> завершит только цикл по <code>y</code>, а цикл по <code>x</code> продолжит работу.
</div>

## Микро-проверки
[CHECKPOINT key="p115-q1" question="Что делает оператор continue внутри цикла for?" options="Полностью останавливает цикл|Пропускает оставшуюся часть текущей итерации и переходит к следующей|Возвращает значение из функции|Перезапускает цикл с самого начала" answer="Пропускает оставшуюся часть текущей итерации и переходит к следующей" hint="Не путайте continue с break: break намертво останавливает весь цикл, а continue лишь переходит к следующему шагу." explanation="continue завершает только текущую итерацию, переходя к следующему значению цикла."]
[CHECKPOINT key="p115-q2" question="Сколько чисел выведет на экран следующий фрагмент программы?

for i in range(10):
    if i == 3:
        break
    print(i)" options="4 числа (0, 1, 2, 3)|3 числа (0, 1, 2)|10 чисел|Ни одного" answer="3 числа (0, 1, 2)" hint="Обратите внимание, где стоит оператор break: при i == 3 цикл завершается ДО вызова print(i)." explanation="Код выведет 0, 1, 2. Когда i станет равно 3, сработает оператор break до вызова функции print, и цикл немедленно завершится."]
"""
    },
    116: {
        "title": "Разбор числа по цифрам в цикле while",
        "description": "Классический экзаменационный алгоритм выделения цифр через % 10 и // 10.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Выделение цифр числа — фундаментальный навык в ЕГЭ:
- Подсчет суммы цифр в задании №5;
- Проверка четных/нечетных цифр в задании №14 и №17;
- Перевод в любую систему счисления (разбор остатков `% base` и `// base`).

## Синтаксис и наглядная визуальная схема
Алгоритм пошагово «откусывает» последнюю цифру числа, пока число не превратится в 0:

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-emerald-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-calculator text-emerald-600 text-sm"></i> Пошаговый цикл разбора числа n = 358
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <span>Шаг 1: <code class="font-bold text-indigo-700">n % 10 ➔ 8</code> (последняя цифра)</span>
      <span class="text-emerald-700 font-mono font-bold bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">n //= 10 ➔ 35</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <span>Шаг 2: <code class="font-bold text-indigo-700">n % 10 ➔ 5</code> (следующая цифра)</span>
      <span class="text-emerald-700 font-mono font-bold bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">n //= 10 ➔ 3</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <span>Шаг 3: <code class="font-bold text-indigo-700">n % 10 ➔ 3</code> (первая цифра)</span>
      <span class="text-emerald-700 font-mono font-bold bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">n //= 10 ➔ 0 (стоп!)</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Вычисление суммы и количества четных цифр числа:

[CODE_RUNNER title="Разбор числа на цифры" input="" output="Число: 358\\nСумма цифр: 16\\nЧетных цифр: 1"]
n = 358
temp = n
digit_sum = 0
even_count = 0

while temp > 0:
    digit = temp % 10
    digit_sum += digit
    if digit % 2 == 0:
        even_count += 1
    temp //= 10

print(f"Число: {n}")
print("Сумма цифр:", digit_sum)
print("Четных цифр:", even_count)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Разрушение исходной переменной</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если написать while n > 0: ... n //= 10, число n станет равным 0. Всегда сохраняйте копию: temp = n.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">temp = n # Сохранили оригинал</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Число ноль</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если n = 0, цикл while temp > 0 не сделает ни одной итерации. Для 0 делайте отдельную проверку if n == 0.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">if n == 0: ... # Для нуля</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p116-q1" question="Какая операция получает последнюю цифру десятичного числа n?" options="n // 10|n % 10|n / 10|n ** 10" answer="n % 10" hint="Вспомните: какая арифметическая операция вычисляет остаток от деления на 10?" explanation="Остаток от деления на 10 всегда даёт последнюю цифру числа."]
[CHECKPOINT key="p116-q2" question="Какая операция удаляет последнюю цифру десятичного числа n?" options="n %= 10|n //= 10|n -= 10|n /= 10" answer="n //= 10" hint="Чтобы отбросить последнюю цифру, нужно поделить число нацело на 10." explanation="Деление нацело на 10 отбрасывает младший разряд числа."]
"""
    },
    117: {
        "title": "Вложенные циклы: перебор пар, троек и таблицы истинности",
        "description": "Конструкции for внутри for: перебор переменных в задании 2, перебор пар в задании 17 и сложность O(N²).",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Вложенные циклы — фундамент двух ключевых задач:
1. **Задание №2:** полный перебор наборов из 4 логических переменных x, y, z, w (2⁴ = 16 комбинаций);
2. **Задание №17:** перебор всех возможных пар элементов списка i и j (сложность O(N²)).

## Синтаксис и наглядная визуальная схема
Внешний цикл делает одну итерацию, а внутренний цикл проходит **все** свои итерации от начала до конца.

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-sky-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-grid-four text-indigo-600 text-sm"></i> Сетка обхода во вложенном цикле (2 строки × 3 столбца)
  </div>
  <div class="grid grid-cols-3 gap-2 text-center text-xs mt-3">
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 font-mono font-bold text-indigo-900 shadow-sm">(i=0, j=0)</div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 font-mono font-bold text-indigo-900 shadow-sm">(i=0, j=1)</div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 font-mono font-bold text-indigo-900 shadow-sm">(i=0, j=2)</div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-purple-200 font-mono font-bold text-purple-900 shadow-sm">(i=1, j=0)</div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-purple-200 font-mono font-bold text-purple-900 shadow-sm">(i=1, j=1)</div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-purple-200 font-mono font-bold text-purple-900 shadow-sm">(i=1, j=2)</div>
  </div>
</div>

## Примеры кода и результат
Каноничный шаблон для генерации таблицы истинности задания №2:

[CODE_RUNNER title="Генерация таблицы истинности (ЕГЭ №2)" input="" output="x y z w | F\\n0 0 0 0 | 1\\n0 0 0 1 | 0\\n0 0 1 0 | 1"]
print("x y z w | F")
# Перебор всех 16 логических комбинаций
count = 0
for x in [0, 1]:
    for y in [0, 1]:
        for z in [0, 1]:
            for w in [0, 1]:
                f = (x <= y) and (y <= z) or w
                if count < 3:
                    print(f"{x} {y} {z} {w} | {int(f)}")
                    count += 1
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Одинаковые имена переменных</div>
      <p class="text-xs text-slate-600 leading-relaxed">Повторное использование for i in ...: for i in ...: перезапишет счетчик внешнего цикла! Всегда давайте уникальные имена: i, j или x, y, z, w.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">for x in ...: for y in ...: # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Квадратичная сложность O(N²)</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если список содержит 100 000 элементов (задание 27), двойной цикл сделает 10 миллиардов операций и зависнет на часы!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">В №27 двойной перебор запрещён</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p117-q1" question="Сколько строк напечатает следующий код: for i in range(3): for j in range(4): print(i, j)?" options="7|12|9|16" answer="12" hint="Для каждого из 3 шагов внешнего цикла внутренний цикл выполняется ровно 4 раза. Сколько будет 3 * 4?" explanation="Внешний цикл выполняется 3 раза, на каждом шаге внутренний цикл выполняется 4 раза: 3 * 4 = 12 строк."]
[CHECKPOINT key="p117-q2" question="Сколько всего комбинаций перебирает четверной вложенный цикл для x, y, z, w по значениям (0, 1)?" options="8|16|4|32" answer="16" hint="Каждая из 4 переменных может принимать 2 значения (0 или 1). Сколько будет 2 в 4-й степени?" explanation="2 в 4-й степени = 2 * 2 * 2 * 2 = 16 комбинаций."]
"""
    }
}
