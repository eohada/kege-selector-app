"""
Юнит-тесты для сервиса Бу Трассировщика (CodeTracer).
"""
import pytest
from app.services.code_tracer import CodeTracer, validate_code_ast, SecurityCheckError


def test_code_tracer_scalars():
    tracer = CodeTracer(max_steps=50, timeout_seconds=1.0)
    code = """a = 10
b = 20
c = a + b
"""
    result = tracer.trace(code)
    assert result["success"] is True
    assert result["total_steps"] >= 3
    assert result["error"] is None

    final_frame = result["frames"][-1]
    assert "c" in final_frame["locals"]
    assert final_frame["locals"]["c"]["value"] == 30
    assert final_frame["locals"]["c"]["type"] == "int"


def test_code_tracer_lists_and_aliasing():
    tracer = CodeTracer(max_steps=50, timeout_seconds=1.0)
    code = """x = [1, 2]
y = x
x.append(3)
"""
    result = tracer.trace(code)
    assert result["success"] is True
    final_frame = result["frames"][-1]

    # Проверяем, что x и y ссылаются на один и тот же target_id в Heap
    assert final_frame["locals"]["x"]["is_ref"] is True
    assert final_frame["locals"]["y"]["is_ref"] is True
    target_id_x = final_frame["locals"]["x"]["target_id"]
    target_id_y = final_frame["locals"]["y"]["target_id"]
    assert target_id_x == target_id_y

    # Проверяем структуру в Heap
    heap_obj = final_frame["heap"][target_id_x]
    assert heap_obj["type"] == "list"
    assert len(heap_obj["items"]) == 3
    assert heap_obj["items"][2]["value"] == 3


def test_code_tracer_loops_and_stdout():
    tracer = CodeTracer(max_steps=100, timeout_seconds=1.0)
    code = """total = 0
for i in range(3):
    total += i
    print(f"step {i}: {total}")
"""
    result = tracer.trace(code)
    assert result["success"] is True
    assert "step 2: 3" in result["stdout"]
    final_frame = result["frames"][-1]
    assert final_frame["locals"]["total"]["value"] == 3


def test_code_tracer_dict_and_mutations():
    tracer = CodeTracer(max_steps=50, timeout_seconds=1.0)
    code = """d = {"apple": 5}
d["banana"] = 10
"""
    result = tracer.trace(code)
    assert result["success"] is True
    final_frame = result["frames"][-1]
    dict_ref = final_frame["locals"]["d"]["target_id"]
    heap_dict = final_frame["heap"][dict_ref]
    assert heap_dict["type"] == "dict"
    assert len(heap_dict["entries"]) == 2


def test_code_tracer_security_blocks_os_import():
    tracer = CodeTracer(max_steps=50, timeout_seconds=1.0)
    code = """import os
os.listdir('.')
"""
    result = tracer.trace(code)
    assert result["success"] is False
    assert "запрещён" in result["error"]


def test_code_tracer_security_blocks_eval():
    tracer = CodeTracer(max_steps=50, timeout_seconds=1.0)
    code = """eval('1 + 1')"""
    result = tracer.trace(code)
    assert result["success"] is False
    assert "запрещён" in result["error"]


def test_code_tracer_step_limit():
    tracer = CodeTracer(max_steps=20, timeout_seconds=1.0)
    code = """count = 0
while True:
    count += 1
"""
    result = tracer.trace(code)
    assert result["success"] is True
    assert result["total_steps"] == 20
    assert "предел" in (result["error"] or "")


def test_code_tracer_handles_input_without_crash():
    tracer = CodeTracer(max_steps=100, timeout_seconds=1.0)
    code = """i = 10
a = int(input())
for x in range(3):
    print(x)
"""
    result = tracer.trace(code)
    assert result["success"] is True
    assert result["error"] is None
    assert result["total_steps"] >= 10
    final_frame = result["frames"][-1]
    assert final_frame["locals"]["i"]["value"] == 10
    assert final_frame["locals"]["a"]["value"] == 0
    assert "0\n1\n2\n" in result["stdout"]


def test_code_tracer_handles_provided_inputs():
    tracer = CodeTracer(max_steps=100, timeout_seconds=1.0)
    code = """a = int(input())
b = int(input())
res = a + b
"""
    result = tracer.trace(code, inputs=["15", "27"])
    assert result["success"] is True
    assert result["error"] is None
    assert result["inputs_used"] == ["15", "27"]
    final_frame = result["frames"][-1]
    assert final_frame["locals"]["res"]["value"] == 42


def test_code_tracer_pauses_on_interactive_input():
    tracer = CodeTracer(max_steps=100, timeout_seconds=1.0)
    code = """x = 10
val = int(input("Введите число: "))
y = x + val
"""
    # 1. Первый запуск без ввода -> останавливается на input(), возвращает waiting_input: True
    res1 = tracer.trace(code, pause_on_input=True)
    assert res1["success"] is True
    assert res1["waiting_input"] is True
    assert res1["input_prompt"] == "Введите число: "
    assert res1["input_line"] == 2
    assert res1["total_steps"] >= 1
    # Последний шаг должен быть перед строкой 2 или на строке 2
    assert res1["frames"][-1]["line"] == 2

    # 2. Повторный запуск с введённым значением -> выполняется до конца
    res2 = tracer.trace(code, inputs=["32"], pause_on_input=True)
    assert res2["success"] is True
    assert res2["waiting_input"] is False
    assert res2["total_steps"] > res1["total_steps"]
    final_frame = res2["frames"][-1]
    assert final_frame["locals"]["val"]["value"] == 32
    assert final_frame["locals"]["y"]["value"] == 42
