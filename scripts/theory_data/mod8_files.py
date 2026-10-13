# -*- coding: utf-8 -*-
"""
Модуль 8: Файлы и чтение наборов данных (Темы 131-133).
Эталонные паттерны ЕГЭ, подсказки к микро-проверкам и перемешанные ответы.
"""

MOD8_TOPICS = {
    131: {
        "title": "Открытие файлов: функция open() и менеджер контекста with",
        "description": "Безопасное открытие open(), гарантированное закрытие with open(...) и пути к файлам в ЕГЭ.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
В компьютерном ЕГЭ входные данные к заданиям №17, №24, №26 и №27 поставляются в виде отдельных текстовых файлов `.txt`.
В них содержатся тысячи, а иногда и миллионы строк. Вводить такие данные вручную невозможно — программа обязана самостоятельно открыть файл и считать информацию.

## Синтаксис и наглядная визуальная схема
Стандарт открытия файлов в Python — конструкция `with open(...)`:

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-emerald-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-file-text text-emerald-600 text-sm"></i> Анатомия конструкции: with open('17.txt') as f:
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <span class="font-mono text-emerald-800 font-bold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">open('17.txt')</span>
      <span class="text-slate-600 font-medium">Открывает файл для чтения из текущей папки</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span class="font-mono text-indigo-800 font-bold bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">as f:</span>
      <span class="text-slate-600 font-medium">Помещает файловый дескриптор в переменную <code>f</code></span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-purple-200 shadow-sm flex items-center justify-between">
      <span class="font-mono text-purple-800 font-bold bg-purple-50 px-2 py-0.5 rounded border border-purple-200">Блок with</span>
      <span class="text-slate-600 font-medium"><b class="text-purple-900">Гарантированно закрывает файл</b> при выходе из блока</span>
    </div>
  </div>
</div>

<div class="my-6 p-4 rounded-xl bg-indigo-50/70 border border-indigo-200 text-xs text-indigo-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-indigo-800">
    <i class="ph-bold ph-check-circle"></i> Автоматическое закрытие ресурсов:
  </div>
  Менеджер контекста <code>with open(...)</code> автоматически освобождает ресурсы операционной системы, даже если внутри блока произойдёт ошибка. Вам не нужно вручную вызывать <code>f.close()</code>.
</div>

## Примеры кода и результат
Безопасное открытие файла:

[CODE_RUNNER title="Контекстный менеджер with open" input="" output="Файл открыт в блоке with: False (закрыт?)\\nФайл после выхода из блока with: True (успешно закрыт!)"]
# Симуляция работы файлового объекта
class MockFile:
    def __init__(self): self.closed = False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True

with MockFile() as f:
    print("Файл открыт в блоке with:", f.closed, "(закрыт?)")

print("Файл после выхода из блока with:", f.closed, "(успешно закрыт!)")
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Ошибка FileNotFoundError</div>
      <p class="text-xs text-slate-600 leading-relaxed">Возникает, если файл лежит в «Загрузках», а скрипт сохранён в другой папке. Сохраняйте .py скрипт строго в ту же папку, где лежит файл!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">FileNotFoundError</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Имя файла</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Точное совпадение имени</div>
      <p class="text-xs text-slate-600 leading-relaxed">Имена файлов чувствительны к регистру и расширениям. Если файл называется 17_123.txt, пишите именно 17_123.txt.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">open('17_123.txt')</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p131-q1" question="В чем главное преимущество конструкции with open(...) as f над простым f = open(...)?" options="Файл открывается в два раза быстрее|Файл гарантированно закрывается автоматически при выходе из блока|Файл шифруется|Не требуется импортировать модуль sys" answer="Файл гарантированно закрывается автоматически при выходе из блока" hint="Конструкция with является менеджером контекста. Какое действие она выполняет гарантированно, даже если в коде возникнет ошибка?" explanation="Конструкция with гарантирует автоматический вызов close() при выходе из контекста, освобождая системные ресурсы."]
[CHECKPOINT key="p131-q2" question="Какая ошибка возникнет, если указать неверное имя файла или файл отсутствует в рабочей папке?" options="ValueError|FileNotFoundError|KeyError|SyntaxError" answer="FileNotFoundError" hint="Само название ошибки переводится с английского как 'Файл не найден'." explanation="При отсутствии файла по указанному пути Python бросает исключение FileNotFoundError."]
"""
    },
    132: {
        "title": "Методы чтения: .readline(), .readlines(), .read() и построчный обход",
        "description": "Разница между чтением одной строки, списка строк и поточным обходом for line in f без утечек памяти.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Файлы в ЕГЭ бывают двух видов:
1. **Служебная строка в начале:** Первое число — это количество строк $N$ или параметры задачи (задания №24, №26, №27). Чтобы прочитать первую строку отдельно, используют `f.readline()`.
2. **Однородные числа:** Файл содержит только числа (задание №17). Их считывают сразу генератором `[int(x) for x in f]`.

## Синтаксис и наглядная визуальная схема
Различие методов чтения файла:

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-book-open text-indigo-600 text-sm"></i> Сводка методов чтения файлового объекта f
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <div><code class="text-indigo-800 font-bold font-mono">f.readline()</code> — читает строго <b class="text-indigo-900">одну строку</b> как str</div>
      <span class="text-slate-500 text-[11px]">Для служебных N, K в первой строке</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-purple-200 shadow-sm flex items-center justify-between">
      <div><code class="text-purple-800 font-bold font-mono">f.read()</code> — читает <b class="text-purple-900">весь файл целиком</b> в одну строку</div>
      <span class="text-slate-500 text-[11px]">Для задания 24 (текст на миллион знаков)</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <div><code class="text-emerald-800 font-bold font-mono">for line in f:</code> — построчный поточный обход</div>
      <span class="text-slate-500 text-[11px]">Экономит память в заданиях 26 и 27</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Чтение служебного заголовка и последующих данных:

[CODE_RUNNER title="Методы чтения" input="" output="Служебная строка N: 3\\nСчитанные числа данных: [100, 250, 420]"]
# Симуляция строк файла
simulated_file_lines = ["3\\n", "100\\n", "250\\n", "420\\n"]

# Первое число — служебный заголовок N
n = int(simulated_file_lines[0].strip())
print("Служебная строка N:", n)

# Последующие числа
data = [int(line.strip()) for line in simulated_file_lines[1:]]
print("Считанные числа данных:", data)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 p-4 rounded-xl bg-indigo-50/70 border border-indigo-200 text-xs text-indigo-900 leading-relaxed">
  <div class="font-bold flex items-center gap-1.5 mb-1 text-indigo-800">
    <i class="ph-bold ph-warning"></i> Символ переноса строки \\n на конце:
  </div>
  Каждая строка, считанная через <code>.readline()</code> или <code>for line in f</code>, оканчивается невидимым символом переноса <code>'\\n'</code>.<br>
  Если вам нужна чистая строка символов (задание 24), всегда вызывайте метод очистки: <code>line.strip()</code>.<br>
  При вызове <code>int(line)</code> функция <code>int()</code> автоматически отбрасывает <code>\\n</code>, поэтому для чисел вызывать <code>.strip()</code> необязательно.
</div>

## Микро-проверки
[CHECKPOINT key="p132-q1" question="Какой метод считывает весь файл в одну большую строку текста (лучший выбор для задания №24)?" options="f.readline()|f.read()|f.readlines()|f.get()" answer="f.read()" hint="Для чтения всего файла целиком используется метод без суффикса line или lines." explanation="f.read() без параметров считывает всё содержимое файла целиком в одну большую строку str."]
[CHECKPOINT key="p132-q2" question="Что возвращает метод f.readline()?" options="Список строк|Одну строку текста|Число|Булево значение" answer="Одну строку текста" hint="Суффикс 'line' в единственном числе означает считывание ровно одной строки." explanation="Метод readline() считывает текущую строку файла в виде одного объекта str."]
"""
    },
    133: {
        "title": "Паттерны потоковой обработки данных для заданий 17, 24, 26, 27",
        "description": "Готовые эталонные шаблоны загрузки и решения задач 17 и 26 с файловым вводом.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
На экзамене у вас не будет времени изобретать алгоритм чтения с нуля.
Знание готовых эталонных 3-строчных шаблонов загрузки данных гарантирует, что вы сразу перейдете к решению математической сути задачи без ошибок на вводе.

## Синтаксис и наглядная визуальная схема
Два эталонных шаблона ЕГЭ:

<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 font-sans">
  <div class="p-5 rounded-2xl bg-gradient-to-br from-indigo-50/80 via-white to-indigo-50/30 border-2 border-indigo-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-2 flex items-center gap-2">
      <i class="ph-bold ph-list-numbers text-indigo-600 text-sm"></i> Шаблон задания №17 (Один ряд чисел)
    </div>
    <div class="p-3 rounded-xl bg-slate-900 font-mono text-[11px] text-indigo-200 leading-relaxed overflow-x-auto">
# Чтение всего файла в список чисел<br>
nums = [int(x) for x in open('17.txt')]<br><br>
# Поиск пар соседних элементов<br>
ans = []<br>
for i in range(len(nums) - 1):<br>
&nbsp;&nbsp;&nbsp;&nbsp;a, b = nums[i], nums[i + 1]<br>
&nbsp;&nbsp;&nbsp;&nbsp;if (a + b) % 2 == 0:<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ans.append(a + b)<br><br>
print(len(ans), max(ans))
    </div>
  </div>

  <div class="p-5 rounded-2xl bg-gradient-to-br from-purple-50/80 via-white to-purple-50/30 border-2 border-purple-200 shadow-[0_4px_0_#DAE1E9] text-slate-800">
    <div class="text-xs font-black uppercase tracking-wider text-purple-700 mb-2 flex items-center gap-2">
      <i class="ph-bold ph-table text-purple-600 text-sm"></i> Шаблон задания №26 (Служебная строка)
    </div>
    <div class="p-3 rounded-xl bg-slate-900 font-mono text-[11px] text-purple-200 leading-relaxed overflow-x-auto">
f = open('26.txt')<br>
# Чтение параметров S и N из первой строки<br>
s_cap, n = map(int, f.readline().split())<br><br>
# Чтение оставшихся чисел<br>
weights = sorted([int(x) for x in f])<br><br>
# Жадный набор элементов<br>
print("Готово к жадному перебору!")
    </div>
  </div>
</div>

## Примеры кода и результат
Полный рабочий пример решения задания №17 с имитацией данных:

[CODE_RUNNER title="Полное решение модели задания №17" input="" output="Количество подходящих пар: 3\\nМаксимальная сумма пары: 60"]
# Имитация списка чисел из файла 17.txt
nums = [10, 25, 35, 12, 18]

# Шаг 1. Нахождение максимального элемента файла, кратного 10
max_10 = max([x for x in nums if x % 10 == 0])

# Шаг 2. Поиск пар соседних чисел
pairs = []
for i in range(len(nums) - 1):
    a, b = nums[i], nums[i + 1]
    # Хотя бы одно кратно 10 И сумма пары <= max_10
    if (a % 10 == 0 or b % 10 == 0) and (a + b <= max_10):
        pairs.append(a + b)

# Ответ на экзамене: количество пар и максимум
print("Количество подходящих пар:", len(pairs))
print("Максимальная сумма пары:", max(pairs))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">IndexError при range(len(nums))</div>
      <p class="text-xs text-slate-600 leading-relaxed">При обращении к nums[i+1] диапазон обязан заканчиваться на len(nums) - 1, иначе на последнем шаге программа упадет!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">for i in range(len(nums) - 1):</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Постановка</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Соседние vs произвольные пары</div>
      <p class="text-xs text-slate-600 leading-relaxed">«Пара соседних элементов» — один цикл с i и i+1. «Пара любых элементов» — вложенный цикл с i и j > i.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-800 font-bold">Внимательно читайте условие №17!</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p133-q1" question="До какого индекса должен идти цикл for i in range(...), если в теле цикла проверяется пара соседних элементов nums[i] и nums[i+1]?" options="len(nums)|len(nums) - 1|len(nums) + 1|len(nums) - 2" answer="len(nums) - 1" hint="Чтобы при обращении к nums[i + 1] не выйти за границы списка, правую границу диапазона нужно уменьшить на 1." explanation="На последнем шаге i = len(nums)-2, и nums[i+1] обратится к последнему элементу списка под индексом len(nums)-1 без ошибки IndexError."]
[CHECKPOINT key="p133-q2" question="Какая однострочная конструкция надёжно загрузит все целые числа из файла 17.txt в список?" options="nums = open('17.txt').split()|nums = [int(x) for x in open('17.txt')]|nums = int(open('17.txt').read())|nums = list(open('17.txt'))" answer="nums = [int(x) for x in open('17.txt')]" hint="Генератор списка перебирает строки открытого файла и применяет функцию int() к каждой из них." explanation="Генератор [int(x) for x in open('17.txt')] считывает каждую строку и переводит её в int за одну строку."]
"""
    }
}
