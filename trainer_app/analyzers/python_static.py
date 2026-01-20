from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


_DANGEROUS_MODULES = {
    'os', 'sys', 'subprocess', 'socket', 'pathlib', 'shutil', 'importlib',
    'requests', 'urllib', 'http', 'ftplib', 'webbrowser',
}


@dataclass
class Issue:
    kind: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {'kind': self.kind, 'message': self.message}
        if self.line is not None:
            d['line'] = self.line
        return d


def analyze_python_code(code: str) -> dict[str, Any]:
    """
    Static analysis meant for tutoring:
    - syntax errors
    - imports overview + dangerous imports warnings
    - simple heuristics (reads input/file, prints output, etc.)
    """
    code = code or ''
    issues: list[Issue] = []
    hints: list[str] = []

    if not code.strip():
        return {'ok': False, 'issues': [Issue('empty', 'Код пустой.').to_dict()], 'hints': ['Начни с чтения данных и определения, что нужно посчитать.']}

    try:
        tree = ast.parse(code, filename='<student_code>')
    except SyntaxError as e:
        issues.append(Issue('syntax', f'Синтаксическая ошибка: {e.msg}', line=e.lineno))
        hints.append('Проверь скобки, двоеточия после if/for/while/def и отступы.')
        return {'ok': False, 'issues': [x.to_dict() for x in issues], 'hints': hints}
    except Exception as e:
        issues.append(Issue('syntax', f'Ошибка разбора кода: {e}'))
        return {'ok': False, 'issues': [x.to_dict() for x in issues], 'hints': hints}

    imports: set[str] = set()
    calls: set[str] = set()
    has_open = False
    has_input = False
    has_print = False

    class V(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for a in node.names:
                imports.add((a.name or '').split('.')[0])
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            nonlocal has_open, has_input, has_print
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name:
                calls.add(name)
                if name == 'open':
                    has_open = True
                if name == 'input':
                    has_input = True
                if name == 'print':
                    has_print = True
            self.generic_visit(node)

    V().visit(tree)

    # Warnings
    bad = sorted(m for m in imports if m in _DANGEROUS_MODULES)
    for m in bad:
        issues.append(Issue('security', f'Подозрительный импорт: {m}. В учебных задачах обычно не нужен.', line=None))

    # Heuristics
    if not has_open and not has_input:
        hints.append('Похоже, в коде нет чтения данных (нет open()/input()). Убедись, что ты берёшь входные данные.')
    if not has_print:
        hints.append('Похоже, нет вывода результата (print). В конце нужно вывести ответ.')

    # Style/helpful hints
    if 're' in imports and 'findall' in calls:
        hints.append('Регулярки могут быть ок, но проверь, что они не пропускают перекрывающиеся случаи (если это важно).')

    return {
        'ok': len([i for i in issues if i.kind == 'syntax']) == 0,
        'imports': sorted(imports),
        'signals': {'has_open': has_open, 'has_input': has_input, 'has_print': has_print},
        'issues': [x.to_dict() for x in issues],
        'hints': hints,
    }

