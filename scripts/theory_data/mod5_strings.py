# -*- coding: utf-8 -*-
"""
Модуль 5: Строки и методы текста (Темы 118-121).
Актуальные алгоритмы задания 12 ЕГЭ, подсказки к микро-проверкам и перемешанные ответы.
"""

MOD5_TOPICS = {
    118: {
        "title": "Строки в Python: создание, длина len(), конкатенация и обход",
        "description": "Неизменяемость строк, функция len(), конкатенация +, дублирование * и перебор символов.",
        "read_minutes": 18,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Строки лежат в основе двух ключевых экзаменационных задач:
- **Задание №12:** алгоритм работы с последовательностями символов (строки вида `'>' + '1' * 15 + '2' * 20`);
- **Задание №24:** поиск максимальной длины цепочки символов в текстовом файле объемом в миллион знаков.

## Синтаксис и наглядная визуальная схема
Строка (`str`) в Python — это **неизменяемая** (immutable) последовательность символов в одинарных или двойных кавычках.

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-textbox text-indigo-600 text-sm"></i> Базовые операции со строками
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span>Длина строки: <code class="font-bold text-indigo-700">len("ЕГЭ2026")</code></span>
      <span class="text-indigo-900 font-bold font-mono bg-indigo-50 px-2.5 py-1 rounded border border-indigo-200">➔ 7 символов</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span>Склейка (конкатенация): <code class="font-bold text-indigo-700">"ЕГЭ" + "_" + "Инф"</code></span>
      <span class="text-emerald-900 font-bold font-mono bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">➔ "ЕГЭ_Инф"</span>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <span>Дублирование: <code class="font-bold text-indigo-700">"AB" * 3</code></span>
      <span class="text-purple-900 font-bold font-mono bg-purple-50 px-2.5 py-1 rounded border border-purple-200">➔ "ABABAB"</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Создание стартовой строки и посимвольный обход:

[CODE_RUNNER title="Операции со строками" input="" output="Сгенерированная строка длины 15: 111111111122222\\nСимволы строки: E G E"]
# Генерация строки заданной структуры
s = "1" * 10 + "2" * 5
print(f"Сгенерированная строка длины {len(s)}: {s}")

# Посимвольный обход
word = "EGE"
letters = [ch for ch in word]
print("Символы строки:", " ".join(letters))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Неизменяемость строк (Immutability)</div>
      <p class="text-xs text-slate-600 leading-relaxed">Попытка изменить отдельный символ на месте s[0] = 'X' вызовет TypeError. Любая операция создает новую строку.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">s[0] = 'A' # TypeError!</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Сложение строки с числом</div>
      <p class="text-xs text-slate-600 leading-relaxed">Выражение "Балл: " + 100 вызовет TypeError. Используйте f-строку f"Балл: {100}" или str(100).</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">"Ответ: " + 42 # TypeError</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">f"Ответ: {42}"  # Верно</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p118-q1" question="Чему равна длина строки len('A' * 5 + 'B' * 3)?" options="15|8|2|TypeError" answer="8" hint="Посчитай количество символов: сколько букв 'A' и сколько букв 'B' сложится в результирующей строке?" explanation="5 символов 'A' плюс 3 символа 'B' дают строку из 8 символов."]
[CHECKPOINT key="p118-q2" question="Какая ошибка возникнет при попытке изменить символ строки по индексу:

s = 'hello'
s[0] = 'H'" options="ValueError|TypeError|IndexError|Синтаксическая ошибка" answer="TypeError" hint="Вспомните ключевое свойство строк: они неизменяемы (immutable). Какой тип ошибки возникает при обращении к неподдерживаемой операции изменения?" explanation="Строки в Python неизменяемы (immutable), поэтому прямая модификация символа по индексу вызывает ошибку TypeError: 'str' object does not support item assignment."]
"""
    },
    119: {
        "title": "Индексация и срезы строк [start:stop:step]",
        "description": "Положительные и отрицательные индексы, извлечение подстрок, шаг и быстрый разворот s[::-1].",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Срезы строк — один из самых мощных инструментов на экзамене:
- **В задании №14:** быстрое удаление префикса `0b`, `0o`, `0x` через `bin(n)[2:]`;
- **В задании №12:** получение фрагментов строки для проверок;
- **Проверка чисел и слов на палиндромы:** `s == s[::-1]`.

## Синтаксис и наглядная визуальная схема
Каждый символ строки имеет два индекса: положительный (слева направо с 0) и отрицательный (справа налево с -1).

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-ruler text-indigo-600 text-sm"></i> Двусторонняя координатная линейка индексов для строки "PYTHON"
  </div>
  <div class="grid grid-cols-6 gap-2 text-center text-xs">
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">0</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">P</span>
      <span class="text-[11px] font-bold text-purple-600 block">-6</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">1</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">Y</span>
      <span class="text-[11px] font-bold text-purple-600 block">-5</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">2</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">T</span>
      <span class="text-[11px] font-bold text-purple-600 block">-4</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">3</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">H</span>
      <span class="text-[11px] font-bold text-purple-600 block">-3</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">4</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">O</span>
      <span class="text-[11px] font-bold text-purple-600 block">-2</span>
    </div>
    <div class="p-2.5 rounded-xl bg-white border-2 border-indigo-200 shadow-sm">
      <span class="text-[11px] font-bold text-indigo-600 block">5</span>
      <span class="text-lg font-black text-slate-800 my-0.5 block font-mono">N</span>
      <span class="text-[11px] font-bold text-purple-600 block">-1</span>
    </div>
  </div>
</div>

### Синтаксис среза: s[start : stop : step]
- `s[start:stop]` — символы от индекса `start` до `stop - 1` (правый край не включается).
- `s[:3]` — первые 3 символа (индексы 0, 1, 2).
- `s[2:]` — от индекса 2 и до самого конца строки.
- `s[::-1]` — вся строка в обратном порядке (мгновенный разворот).

## Примеры кода и результат
Применение срезов для работы с двоичной записью и разворота:

[CODE_RUNNER title="Примеры срезов строк" input="" output="Чистые двоичные цифры: 101010\\nСрез с 1 по 4: YTH\\nРазворот строки: NOHTYP"]
# Срез префикса в задании 14
raw_bin = bin(42) # '0b101010'
clean_bin = raw_bin[2:]
print("Чистые двоичные цифры:", clean_bin)

s = "PYTHON"
print("Срез с 1 по 4:", s[1:4])
print("Разворот строки:", s[::-1])
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Индекс vs срез при выходе за границы</div>
      <p class="text-xs text-slate-600 leading-relaxed">Прямой индекс s[100] вызовет IndexError. Срез же s[100:200] никогда не упадет, а просто вернет пустую строку "".</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">s[100]     # IndexError!</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">s[100:200] # "" (безопасно)</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Правая граница не включается</div>
      <p class="text-xs text-slate-600 leading-relaxed">Срез s[0:3] берет 3 символа (0, 1, 2). Символ с индексом 3 не берется.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">s[:3] # ровно 3 первых символа</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p119-q1" question="Что вернёт выражение 'ИНФОРМАТИКА'[2:5]?" options="'НФО'|'ФОР'|'ФОРМ'|'НФОР'" answer="'ФОР'" hint="Посчитай индексы с 0: И(0), Н(1), Ф(2), О(3), Р(4), М(5). Символ с индексом 5 не входит в срез." explanation="Индексы: 0='И', 1='Н', 2='Ф', 3='О', 4='Р'. Индекс 5 не включается. Получаем подстроку 'ФОР'."]
[CHECKPOINT key="p119-q2" question="Как проще всего развернуть строку s задом наперед в Python?" options="reverse(s)|s[::-1]|s.reverse()|s[-1:0]" answer="s[::-1]" hint="Вспомните синтаксис среза с шагом: отрицательный шаг -1 без указания границ разворачивает всю строку от конца к началу." explanation="Срез со шагом -1 без указания начального и конечного индекса s[::-1] разворачивает всю строку за одну операцию."]
"""
    },
    120: {
        "title": "Методы поиска и подсчёта: .count(), .find(), .rfind(), оператор in",
        "description": "Поиск подстрок, различие find() и index(), непересекающиеся вхождения в .count() для задания №24.",
        "read_minutes": 20,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Анализ символов и поиск подстрок — это основа заданий №12, №14 и №24:
- **В задании №14:** «Сколько нулей в семеричной записи?» ➔ `s.count('0')`;
- **В задании №12:** проверка наличия подстроки ➔ `if '>1' in s:`;
- **В задании №24:** нахождение позиций маркеров и символов.

## Синтаксис и наглядная визуальная схема
Сводка методов поиска подстроки:

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-emerald-50/40 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-magnifying-glass text-emerald-600 text-sm"></i> Методы поиска и подсчета в строках
  </div>
  <div class="space-y-2.5 text-xs">
    <div class="p-3 rounded-xl bg-white border border-emerald-200 shadow-sm flex items-center justify-between">
      <div><span class="font-mono text-emerald-800 font-bold">s.count(sub)</span> — количество непересекающихся вхождений</div>
      <code class="text-emerald-700 font-bold bg-emerald-50 px-2.5 py-1 rounded border border-emerald-200">"1101".count("1") ➔ 3</code>
    </div>
    <div class="p-3 rounded-xl bg-white border border-indigo-200 shadow-sm flex items-center justify-between">
      <div><span class="font-mono text-indigo-800 font-bold">s.find(sub)</span> — индекс первого вхождения (или -1)</div>
      <code class="text-indigo-700 font-bold bg-indigo-50 px-2.5 py-1 rounded border border-indigo-200">"ЕГЭ2026".find("20") ➔ 3</code>
    </div>
    <div class="p-3 rounded-xl bg-white border border-purple-200 shadow-sm flex items-center justify-between">
      <div><span class="font-mono text-purple-800 font-bold">s.rfind(sub)</span> — индекс последнего вхождения с правого края</div>
      <code class="text-purple-700 font-bold bg-purple-50 px-2.5 py-1 rounded border border-purple-200">"AB_AB".rfind("AB") ➔ 3</code>
    </div>
    <div class="p-3 rounded-xl bg-white border border-amber-200 shadow-sm flex items-center justify-between">
      <div><span class="font-mono text-amber-800 font-bold">sub in s</span> — проверка наличия (True / False)</div>
      <code class="text-amber-800 font-bold bg-amber-50 px-2.5 py-1 rounded border border-amber-200">"А" in "ИНФ" ➔ False</code>
    </div>
  </div>
</div>

## Примеры кода и результат
Применение методов поиска в текстовых строках:

[CODE_RUNNER title="Поиск и подсчет в строках" input="" output="Количество единиц: 4\\nПервое вхождение '2026' на индексе: 4\\nПоиск '2027': -1 (не найдено)"]
s = "101101"
print("Количество единиц:", s.count("1"))

text = "ЕГЭ_2026_Информатика"
print("Первое вхождение '2026' на индексе:", text.find("2026"))
print("Поиск '2027':", text.find("2027"))
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">count() считает только непересекающиеся вхождения</div>
      <p class="text-xs text-slate-600 leading-relaxed">В строке "AAAA" вызов "AAAA".count("AA") вернет 2, а не 3! Первая пара берет первые два символа, вторая — оставшиеся.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">"AAAA".count("AA") ➔ 2</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-indigo-200 bg-white p-4 shadow-[0_3px_0_#C7D2FE] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-indigo-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Разница find() и index()</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если подстрока не найдена: find() возвращает -1 (безопасно), а index() падает с ошибкой ValueError.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">s.find("abc") ➔ -1 (безопасно)</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p120-q1" question="Чему равен результат выражения 'ЕГЭ_2026'.find('ИНФ')?" options="False|-1|0|ValueError" answer="-1" hint="Метод find() отличается от index() тем, что не падает с ошибкой, а возвращает специальный числовой маркер отсутствия подстроки." explanation="Метод find() при отсутствии искомой подстроки всегда возвращает число -1."]
[CHECKPOINT key="p120-q2" question="Сколько вхождений найдет вызов 'XXXXX'.count('XX')?" options="4|2|3|5" answer="2" hint="Метод count() учитывает только непересекающиеся вхождения: найдя первую пару 'XX', он продолжает поиск со следующего неиспользованного символа." explanation=".count() считает непересекающиеся пары: берутся символы с индексами 0-1 и 2-3 (всего 2 пары), а пятый символ 'X' остаётся без пары."]
"""
    },
    121: {
        "title": "Методы модификации строк: .replace(), .split(), .strip()",
        "description": "Замена подстрок в задании №12 (параметр count=1), очистка от пробелов и разбиение на слова.",
        "read_minutes": 22,
        "content": """<!--status:published-->
## Зачем это нужно в ЕГЭ
Метод `.replace()` — это программное воплощение команды `заменить(v, w)` из исполнителя «Редактор» (Задание №12).
Метод `.split()` разбивает строки файла на отдельные значения в заданиях №17, №24 и №26.
Метод `.strip()` убирает невидимые символы переноса строки `\\n` при чтении из файла.

## Синтаксис и наглядная визуальная схема
Синтаксис ключевого метода замены:
<div class="my-4 p-4 rounded-2xl bg-slate-900 border-2 border-slate-700 text-center font-mono text-sm sm:text-base font-bold text-amber-300 shadow-sm">
  s.replace(old, new, count)
</div>
- `old` : что заменяем;
- `new` : на что заменяем;
- `count` : сколько раз (если не указать — заменит **все** вхождения в строке!).

<div class="my-6 p-5 sm:p-6 rounded-2xl bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 border-2 border-indigo-100 shadow-[0_4px_0_#DAE1E9] text-slate-800 font-sans">
  <div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-3 flex items-center gap-2">
    <i class="ph-bold ph-pencil-simple-line text-indigo-600 text-sm"></i> Моделирование исполнителя «Редактор» (ЕГЭ №12)
  </div>
  <div class="p-4 rounded-xl bg-white border border-indigo-200 shadow-sm text-xs leading-relaxed">
    Команда исполнителя <i>«заменить(v, w)»</i> заменяет <b class="text-indigo-900">только первое слева</b> вхождение цепочки.<br>
    В Python это записывается строго с параметром <code>count=1</code>:
    <div class="mt-3 p-3 rounded-xl bg-indigo-50 border border-indigo-200 font-mono font-bold text-indigo-900">
      s = s.replace(">1", "22>", 1) <span class="text-indigo-500 text-[11px] font-normal"># обязательно переприсваивание s = и count=1!</span>
    </div>
  </div>
</div>

## Примеры кода и результат
Решение современного формата задания №12 с маркерной стрелкой `>`:

[CODE_RUNNER title="Моделирование задания №12 ЕГЭ" input="" output="Итоговая строка: 222222222222222222222222222222>\\nСумма цифр: 60"]
# В современных вариантах ЕГЭ строка формируется с маркером:
s = ">" + "1" * 15 + "2" * 20

while ">1" in s or ">2" in s or ">0" in s:
    if ">1" in s:
        # Заменяем строго первое вхождение (count=1)!
        s = s.replace(">1", "22>", 1)
    elif ">2" in s:
        s = s.replace(">2", "2>", 1)
    elif ">0" in s:
        s = s.replace(">0", "1>", 1)

print("Итоговая строка:", s)
# Подсчитываем сумму цифр в итоговой строке:
digit_sum = s.count("1") * 1 + s.count("2") * 2
print("Сумма цифр:", digit_sum)
[/CODE_RUNNER]

## Ловушки и частые ошибки на экзамене
<div class="my-6 grid grid-cols-1 md:grid-cols-2 gap-4 not-prose">
  <div class="rounded-2xl border-2 border-rose-200 bg-white p-4 shadow-[0_3px_0_#FECACA] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-rose-700 uppercase tracking-wider">Ловушка №1</span>
        <span class="w-6 h-6 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center text-xs font-black">✕</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытое переприсваивание s = s.replace(...)</div>
      <p class="text-xs text-slate-600 leading-relaxed">Строки неизменяемы! Вызов s.replace(...) сам по себе не меняет s. Без s = s.replace(...) цикл while зависнет навсегда!</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-bold">s.replace("1", "2", 1)     # Бесполезно</div>
      <div class="p-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 font-bold">s = s.replace("1", "2", 1) # Верно</div>
    </div>
  </div>

  <div class="rounded-2xl border-2 border-amber-200 bg-white p-4 shadow-[0_3px_0_#FDE68A] flex flex-col justify-between">
    <div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-black text-amber-700 uppercase tracking-wider">Ловушка №2</span>
        <span class="w-6 h-6 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-black">!</span>
      </div>
      <div class="text-xs font-black text-slate-800 mb-1">Забытый третий аргумент count=1</div>
      <p class="text-xs text-slate-600 leading-relaxed">Если не указать 1, заменятся сразу ВСЕ подстроки во всем тексте, что грубо исказит алгоритм пошагового автомата Редактора.</p>
    </div>
    <div class="mt-3 space-y-1.5 font-mono text-xs">
      <div class="p-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 font-bold">count=1 строго обязателен в №12</div>
    </div>
  </div>
</div>

## Микро-проверки
[CHECKPOINT key="p121-q1" question="Что произойдёт, если в задании №12 вызвать s.replace('>1', '2>') без третьего аргумента?" options="Заменится только первое вхождение|Заменятся сразу ВСЕ вхождения '>1' в строке|Ошибка синтаксиса|Ничего не заменится" answer="Заменятся сразу ВСЕ вхождения '>1' в строке" hint="По умолчанию метод replace() без третьего параметра заменяет абсолютно каждое вхождение по всей строке одновременно." explanation="По умолчанию метод replace() заменяет все найденные подстроки. Для моделирования пошаговой работы исполнителя 'Редактор' строго необходим параметр 1 (замена только первого вхождения)."]
[CHECKPOINT key="p121-q2" question="Что вернёт вызов '  123 456\\n  '.strip()?" options="'123456'|'123 456'|'123 456\\n'|Ошибку" answer="'123 456'" hint="Метод strip() удаляет невидимые пробельные символы и переносы строки только по внешним краям строки, не затрагивая пробелы между словами." explanation="strip() убирает пробелы и символы переноса строки только с внешних границ строки (пробел внутри между 123 и 456 сохраняется)."]
"""
    }
}
