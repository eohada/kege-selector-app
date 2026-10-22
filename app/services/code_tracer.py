"""
BooStudy Code Tracer Service (Бу Трассировщик)
Пошаговая визуальная трассировка выполнения Python-кода с фиксацией
состояний стека (Stack/Locals), кучи (Heap/Objects), ссылок и мутаций.
"""
from __future__ import annotations

import ast
import io
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple


FORBIDDEN_MODULES: Set[str] = {
    "os", "sys", "subprocess", "socket", "shutil", "pty",
    "ctypes", "multiprocessing", "threading", "importlib",
    "signal", "resource", "posix", "nt", "_winapi", "asyncio"
}

FORBIDDEN_CALLS: Set[str] = {
    "eval", "exec", "__import__", "compile", "breakpoint", "quit", "exit"
}

SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "chr": chr,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "ZeroDivisionError": ZeroDivisionError,
    "StopIteration": StopIteration,
    "AssertionError": AssertionError,
    "EOFError": EOFError,
    "True": True,
    "False": False,
    "None": None,
}


class WaitingForInputError(Exception):
    """Исключение при паузе для запроса пошагового ввода пользователя."""

    def __init__(self, prompt: str = "", line: int = 1):
        self.prompt = prompt
        self.line = line
        super().__init__(f"Waiting for input at line {line}: {prompt}")


class SimulatedInput:
    """Эмулятор стандартного ввода для безопасного пошагового выполнения input()."""

    def __init__(
        self,
        raw_input: Union[str, List[Any], None] = None,
        stdout_buffer: Optional[io.StringIO] = None,
        pause_on_input: bool = False,
    ):
        self.stdout_buffer = stdout_buffer
        self.pause_on_input = pause_on_input
        if isinstance(raw_input, list):
            self.lines = [str(x) for x in raw_input]
        elif isinstance(raw_input, str):
            self.lines = [line.rstrip("\r") for line in raw_input.splitlines()]
        else:
            self.lines = []
        self._counter = 0
        self.consumed: List[str] = []
        self.prompts: List[str] = []
        self.needed_more: bool = False

    def __call__(self, prompt: Any = "") -> str:
        prompt_str = str(prompt) if prompt is not None else ""
        self.prompts.append(prompt_str)
        if prompt_str and self.stdout_buffer:
            self.stdout_buffer.write(prompt_str)
        if self.lines:
            val = self.lines.pop(0)
            self.consumed.append(val)
            return val
        if self.pause_on_input:
            self.needed_more = True
            line_no = 1
            try:
                frame = sys._getframe(1)
                line_no = frame.f_lineno
            except Exception:
                pass
            raise WaitingForInputError(prompt=prompt_str, line=line_no)
        # Если входные данные закончились или не заданы, возвращаем безопасный "0",
        # чтобы int(input()), float(input()) или циклы чтения продолжали выполнение.
        self.needed_more = True
        self._counter += 1
        val = "0"
        self.consumed.append(val)
        return val


class SecurityCheckError(Exception):
    """Исключение при обнаружении небезопасного кода в AST."""
    pass


class StepLimitExceeded(Exception):
    """Превышение лимита шагов отладки."""
    pass


class TimeoutExceeded(Exception):
    """Превышение лимита времени выполнения."""
    pass


def validate_code_ast(code: str) -> None:
    """Проверяет AST кода на отсутствие запрещённых импортов и вызовов."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SecurityCheckError(f"Синтаксическая ошибка (строка {e.lineno}): {e.msg}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_name = alias.name.split(".")[0]
                if mod_name in FORBIDDEN_MODULES:
                    raise SecurityCheckError(f"Импорт модуля '{alias.name}' запрещён в Бу Трассировщике.")
        elif isinstance(node, ast.ImportFrom):
            mod_name = (node.module or "").split(".")[0]
            if mod_name in FORBIDDEN_MODULES:
                raise SecurityCheckError(f"Импорт из модуля '{node.module}' запрещён в Бу Трассировщике.")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise SecurityCheckError(f"Вызов функции '{node.func.id}()' запрещён в безопасном режиме.")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "spawn"}:
                raise SecurityCheckError(f"Вызов метода '{node.func.attr}()' запрещён.")


class CodeTracer:
    """Серверный исполнитель и захватчик кадров памяти для Бу Трассировщика."""

    def __init__(self, max_steps: int = 1000, timeout_seconds: float = 2.5):
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.frames: List[Dict[str, Any]] = []
        self.stdout_buffer = io.StringIO()
        self.simulated_input: Optional[SimulatedInput] = None
        self._prev_frame_snapshot: Optional[Dict[str, Any]] = None
        self._step_count = 0
        self._timed_out = False
        self._start_time = 0.0

    def trace(
        self,
        code: str,
        file_name: str = "main.py",
        inputs: Union[str, List[Any], None] = None,
        pause_on_input: bool = False,
    ) -> Dict[str, Any]:
        """Трассирует выполнение Python-кода и возвращает кадры исполнения."""
        try:
            validate_code_ast(code)
        except SecurityCheckError as err:
            return {
                "success": False,
                "error": str(err),
                "total_steps": 0,
                "frames": [],
                "file_name": file_name,
            }

        compiled_code = compile(code, file_name, "exec")
        self.frames = []
        self.stdout_buffer = io.StringIO()
        self._prev_frame_snapshot = None
        self._step_count = 0
        self._timed_out = False
        self._start_time = time.monotonic()

        execution_error: Optional[str] = None
        old_stdout = sys.stdout
        sys.stdout = self.stdout_buffer

        self.simulated_input = SimulatedInput(inputs, stdout_buffer=self.stdout_buffer, pause_on_input=pause_on_input)
        sim_input = self.simulated_input
        builtins_dict = dict(SAFE_BUILTINS)
        builtins_dict["input"] = sim_input

        sandbox_globals: Dict[str, Any] = {
            "__builtins__": builtins_dict,
            "__name__": "__main__",
            "__file__": file_name,
            "__doc__": None,
            "input": sim_input,
        }

        # Кастомная функция print для записи в stdout_buffer
        def _safe_print(*args: Any, sep: str = " ", end: str = "\n", **kwargs: Any) -> None:
            text = sep.join(str(arg) for arg in args) + end
            self.stdout_buffer.write(text)

        sandbox_globals["print"] = _safe_print

        def trace_dispatch(frame, event, arg):
            if self._timed_out or (time.monotonic() - self._start_time > self.timeout_seconds):
                self._timed_out = True
                raise TimeoutExceeded(f"Превышено максимальное время выполнения ({self.timeout_seconds} сек)")

            if self._step_count >= self.max_steps:
                raise StepLimitExceeded(f"Достигнут предел в {self.max_steps} шагов отладки")

            # Фильтруем системные вызовы вне нашего файла
            if frame.f_code.co_filename != file_name:
                return trace_dispatch

            if event == "exception" and arg and arg[0] is WaitingForInputError:
                return trace_dispatch

            if event in {"line", "call", "return", "exception"}:
                self._record_step(frame, event, arg, file_name)

            return trace_dispatch

        try:
            sys.settrace(trace_dispatch)
            exec(compiled_code, sandbox_globals)
        except WaitingForInputError as wait_err:
            sys.settrace(None)
            while self.frames and self.frames[-1].get("event") in {"exception", "return"}:
                self.frames.pop()
            final_stdout = self.stdout_buffer.getvalue()
            return {
                "success": True,
                "error": None,
                "waiting_input": True,
                "input_prompt": wait_err.prompt,
                "input_line": wait_err.line,
                "total_steps": len(self.frames),
                "frames": self.frames,
                "file_name": file_name,
                "stdout": final_stdout,
                "inputs_used": getattr(self.simulated_input, "consumed", []),
                "input_prompts": getattr(self.simulated_input, "prompts", []),
                "needed_more_inputs": True,
            }
        except (StepLimitExceeded, TimeoutExceeded) as limit_err:
            execution_error = str(limit_err)
        except Exception as exc:
            execution_error = f"{type(exc).__name__}: {exc}"
            # Добавим финальный кадр ошибки, если есть куда привязать
            if self.frames:
                self.frames[-1]["is_error"] = True
                self.frames[-1]["error_message"] = execution_error
        finally:
            sys.settrace(None)
            sys.stdout = old_stdout

        # Вычисляем финальный вывод
        final_stdout = self.stdout_buffer.getvalue()

        return {
            "success": True,
            "error": execution_error,
            "waiting_input": False,
            "input_prompt": "",
            "input_line": None,
            "total_steps": len(self.frames),
            "frames": self.frames,
            "file_name": file_name,
            "stdout": final_stdout,
            "inputs_used": getattr(self.simulated_input, "consumed", []),
            "input_prompts": getattr(self.simulated_input, "prompts", []),
            "needed_more_inputs": getattr(self.simulated_input, "needed_more", False),
        }

    def _record_step(self, frame: Any, event: str, arg: Any, file_name: str) -> None:
        """Фиксирует снимок переменных и структур памяти на текущем шаге."""
        self._step_count += 1
        lineno = frame.f_lineno
        func_name = frame.f_code.co_name

        # Стек вызовов
        call_stack = []
        curr = frame
        while curr:
            if curr.f_code.co_filename == file_name:
                call_stack.append(curr.f_code.co_name)
            curr = curr.f_back
        call_stack.reverse()

        # Захват локальных переменных и объектов кучи
        heap_objects: Dict[str, Dict[str, Any]] = {}
        locals_repr: Dict[str, Dict[str, Any]] = {}

        raw_locals = frame.f_locals
        for var_name, var_val in raw_locals.items():
            if var_name.startswith("__") and var_name.endswith("__"):
                continue
            if callable(var_val) and not isinstance(var_val, (list, dict, set, tuple)):
                continue

            var_info = self._inspect_value(var_val, heap_objects)
            locals_repr[var_name] = var_info

        # Детекция мутаций по сравнению с предыдущим кадром
        mutated_vars = []
        mutated_heap_ids = []

        if self._prev_frame_snapshot:
            prev_locals = self._prev_frame_snapshot.get("locals", {})
            for k, v in locals_repr.items():
                if k not in prev_locals or prev_locals[k] != v:
                    mutated_vars.append(k)

            prev_heap = self._prev_frame_snapshot.get("heap", {})
            for hid, hobj in heap_objects.items():
                if hid not in prev_heap or prev_heap[hid] != hobj:
                    mutated_heap_ids.append(hid)

        current_stdout = self.stdout_buffer.getvalue()

        step_record = {
            "step": self._step_count - 1,
            "line": lineno,
            "event": event,
            "func_name": func_name,
            "stack": call_stack,
            "locals": locals_repr,
            "heap": heap_objects,
            "stdout": current_stdout,
            "mutated_vars": mutated_vars,
            "mutated_heap_ids": mutated_heap_ids,
            "is_error": False,
        }

        if event == "exception" and arg:
            exc_type, exc_val, _ = arg
            step_record["is_error"] = True
            step_record["error_message"] = f"{exc_type.__name__}: {exc_val}"

        self.frames.append(step_record)
        self._prev_frame_snapshot = step_record

    def _inspect_value(self, val: Any, heap_objects: Dict[str, Dict[str, Any]], depth: int = 0) -> Dict[str, Any]:
        """Инспектирует значение: скаляры возвращаются по значению, структуры помещаются в Heap с id."""
        val_type = type(val).__name__

        # Скалярные типы: числа, строки, bool, None
        if val is None or isinstance(val, (int, float, str, bool)):
            return {
                "type": val_type,
                "value": val,
                "is_ref": False,
            }

        # Сложные структуры данных: List, Dict, Set, Tuple
        obj_id = str(id(val))

        if isinstance(val, list):
            if obj_id not in heap_objects and depth < 5:
                # Регистрируем список в куче
                heap_objects[obj_id] = {
                    "id": obj_id,
                    "type": "list",
                    "length": len(val),
                    "items": [self._inspect_value(item, heap_objects, depth + 1) for item in val[:100]],
                }
            return {
                "type": "list",
                "is_ref": True,
                "target_id": obj_id,
                "preview": f"list[{len(val)}]",
            }

        elif isinstance(val, dict):
            if obj_id not in heap_objects and depth < 5:
                entries = []
                for k, v in list(val.items())[:100]:
                    entries.append({
                        "key": str(k),
                        "value": self._inspect_value(v, heap_objects, depth + 1),
                    })
                heap_objects[obj_id] = {
                    "id": obj_id,
                    "type": "dict",
                    "length": len(val),
                    "entries": entries,
                }
            return {
                "type": "dict",
                "is_ref": True,
                "target_id": obj_id,
                "preview": f"dict[{len(val)}]",
            }

        elif isinstance(val, tuple):
            if obj_id not in heap_objects and depth < 5:
                heap_objects[obj_id] = {
                    "id": obj_id,
                    "type": "tuple",
                    "length": len(val),
                    "items": [self._inspect_value(item, heap_objects, depth + 1) for item in val[:100]],
                }
            return {
                "type": "tuple",
                "is_ref": True,
                "target_id": obj_id,
                "preview": f"tuple[{len(val)}]",
            }

        elif isinstance(val, set):
            if obj_id not in heap_objects and depth < 5:
                heap_objects[obj_id] = {
                    "id": obj_id,
                    "type": "set",
                    "length": len(val),
                    "items": [self._inspect_value(item, heap_objects, depth + 1) for item in list(val)[:100]],
                }
            return {
                "type": "set",
                "is_ref": True,
                "target_id": obj_id,
                "preview": f"set[{len(val)}]",
            }

        # Прочие объекты
        return {
            "type": val_type,
            "value": str(val)[:120],
            "is_ref": False,
        }
