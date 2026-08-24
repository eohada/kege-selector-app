from __future__ import annotations

import re


def explain_python_error(stderr: str) -> str:
    """Short Russian explanations for common student Python mistakes."""
    text = (stderr or "").strip()
    if not text:
        return ""

    hints: list[str] = []

    def add(title: str, body: str) -> None:
        hints.append(f"{title}: {body}")

    if "SyntaxError" in text:
        add("SyntaxError", "Python не смог разобрать строку. Часто это пропущенная скобка, кавычка, двоеточие после if/for/while/def или лишний символ.")
    if "IndentationError" in text:
        add("IndentationError", "Проблема с отступами. После строки с двоеточием нужен одинаковый отступ, обычно 4 пробела. Не смешивай табы и пробелы.")
    if "NameError" in text:
        m = re.search(r"name '([^']+)' is not defined", text)
        name = m.group(1) if m else "переменная/функция"
        add("NameError", f"{name} используется до создания или написан с опечаткой. Проверь регистр букв: n и N для Python разные имена.")
    if "TypeError" in text:
        if "unsupported operand type" in text:
            add("TypeError", "Ты применяешь операцию к несовместимым типам. Например, нельзя напрямую сложить строку и число: сначала сделай int(...) или str(...).")
        elif "object is not callable" in text:
            add("TypeError", "Ты пытаешься вызвать как функцию то, что функцией не является. Часто причина в лишних скобках или переменной с именем print/list/sum.")
        else:
            add("TypeError", "Операция применена к неподходящему типу данных. Частый случай: складываешь строку и число, забыв int(...), или вызываешь функцию с неправильным числом аргументов.")
    if "ValueError" in text:
        if "invalid literal for int" in text:
            add("ValueError", "int(...) получил не чистое целое число. Проверь, что в строке нет букв, пробелов, запятых вместо точки или пустого значения.")
        else:
            add("ValueError", "Значение не подходит для операции. Частый случай в ЕГЭ: int(...) пытается превратить в число строку, где есть пробелы, буквы или пустое значение.")
    if "IndexError" in text:
        add("IndexError", "Обращение к элементу списка/строки по индексу, которого нет. Проверь границы цикла и длину через len(...).")
    if "KeyError" in text:
        add("KeyError", "В словаре нет такого ключа. Проверь, что ключ был добавлен, или используй dict.get(...).")
    if "ZeroDivisionError" in text:
        add("ZeroDivisionError", "Деление на ноль. Проверь знаменатель перед делением или условие в цикле.")
    if "RecursionError" in text:
        add("RecursionError", "Слишком глубокая рекурсия. Для задач ЕГЭ чаще проще заменить рекурсию циклом или проверить условие выхода.")
    if "AttributeError" in text:
        add("AttributeError", "У объекта нет такого свойства или метода. Проверь название метода и тип переменной перед точкой.")
    if "EOFError" in text:
        add("EOFError", "Программа ждала input(), но входных данных нет. Для проверки в редакторе лучше временно заменить input() на конкретное значение.")
    if "FileNotFoundError" in text:
        add("FileNotFoundError", "Файл не найден. Проверь точное имя файла и расширение. В песочнице доступны только файлы, прикреплённые к задаче.")
    if "ImportError" in text or "ModuleNotFoundError" in text:
        add("ImportError", "Этот модуль недоступен в песочнице. Для ЕГЭ-раздела разрешены только базовые библиотеки из подсказки редактора.")
    if "PermissionError" in text:
        add("PermissionError", "Песочница не разрешает это действие. Нельзя записывать файлы или читать файлы вне папки задания.")
    if "Timeout" in text or "Превышено время" in text:
        add("Timeout", "Код выполнялся слишком долго. Обычно причина в бесконечном цикле или слишком большом переборе.")
    if "turtle" in text.lower() and ("tk" in text.lower() or "xvfb" in text.lower()):
        add("turtle", "В BooStudy Turtle рисует в безопасный SVG внутри результата. Системное окно не требуется.")

    if not hints:
        add("Подсказка", "Посмотри на последнюю строку ошибки: там обычно указан тип ошибки и место, где Python остановился.")

    return "Понятно по-русски:\n" + "\n".join(f"• {item}" for item in hints)
