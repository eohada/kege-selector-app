"""Bounded, non-evaluating mathematical answer validators for theory activities."""
from __future__ import annotations

import ast
import math
import re
from fractions import Fraction
from typing import Any


MAX_INPUT_LENGTH = 512
MAX_AST_NODES = 80
MAX_AST_DEPTH = 20
MAX_POLYNOMIAL_TERMS = 256
MAX_POLYNOMIAL_DEGREE = 16
MAX_INTEGER_POWER = 12
SUPPORTED_VALIDATORS = {'exact', 'numeric', 'numeric_tolerance', 'fraction', 'symbolic', 'set', 'interval'}


class MathAnswerError(ValueError):
    """Invalid student syntax or an author validation configuration error."""


class UnsupportedMathAnswer(MathAnswerError):
    """Input is valid text but outside the validator's documented grammar."""


def _read_group(source: str, start: int, left: str = '{', right: str = '}') -> tuple[str, int]:
    if start >= len(source) or source[start] != left:
        raise MathAnswerError('Ожидалась группа математического выражения.')
    depth = 1
    index = start + 1
    while index < len(source):
        if source[index] == left:
            depth += 1
        elif source[index] == right:
            depth -= 1
            if depth == 0:
                return source[start + 1:index], index + 1
        index += 1
    raise MathAnswerError('Не закрыта группа математического выражения.')


def _read_math_argument(source: str, start: int) -> tuple[str, int]:
    """Read one TeX atom, accepting MathLive's compact ``\\frac12`` form."""
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source):
        raise MathAnswerError('Для дроби не указан числитель или знаменатель.')
    if source[start] == '{':
        return _read_group(source, start)
    if source[start] == '\\':
        command = re.match(r'\\(?:[A-Za-z]+|.)', source[start:])
        if not command:
            raise UnsupportedMathAnswer('Неподдерживаемая TeX-команда.')
        return command.group(0), start + len(command.group(0))
    return source[start], start + 1


def latex_to_expression(value: str) -> str:
    """Translate the supported MathLive/TeX subset to a safe arithmetic string."""
    source = str(value or '').strip()
    if not source or len(source) > MAX_INPUT_LENGTH:
        raise MathAnswerError('Пустой или слишком длинный ответ.')
    source = source.replace('−', '-').replace('–', '-').replace('×', '*').replace('·', '*').replace('÷', '/')
    out: list[str] = []
    index = 0
    command_map = {
        'cdot': '*', 'times': '*', 'div': '/', 'pi': 'pi', 'infty': 'inf',
        'sin': 'sin', 'cos': 'cos', 'tan': 'tan', 'arcsin': 'arcsin',
        'arccos': 'arccos', 'arctan': 'arctan', 'ln': 'ln', 'log': 'log',
        'exp': 'exp', 'quad': ' ', 'qquad': ' ', 'enspace': ' ',
        'thinspace': ' ', 'medspace': ' ', '!': ' ', ',': ' ', ';': ' ', ':': ' ', ' ': ' ',
    }
    while index < len(source):
        char = source[index]
        if char == '\\':
            command_match = re.match(r'\\([A-Za-z]+|[,;:! ])', source[index:])
            if not command_match:
                raise UnsupportedMathAnswer('Неподдерживаемая TeX-команда.')
            command = command_match.group(1)
            index += len(command_match.group(0))
            if command in {'left', 'right'}:
                continue
            if command in {'frac', 'dfrac', 'tfrac'}:
                numerator, index = _read_math_argument(source, index)
                denominator, index = _read_math_argument(source, index)
                out.append(f'(({latex_to_expression(numerator)})/({latex_to_expression(denominator)}))')
                continue
            if command == 'sqrt':
                while index < len(source) and source[index].isspace():
                    index += 1
                degree = '2'
                if index < len(source) and source[index] == '[':
                    degree, index = _read_group(source, index, '[', ']')
                radicand, index = _read_group(source, index)
                radicand_expr = latex_to_expression(radicand)
                if degree.strip() == '2':
                    out.append(f'sqrt({radicand_expr})')
                else:
                    out.append(f'(({radicand_expr})**(1/({degree})))')
                continue
            if command in {'text', 'mathrm', 'mathbf', 'mathit', 'operatorname'}:
                raise UnsupportedMathAnswer(f'Команда \\{command} не используется в математическом ответе.')
            if command in command_map:
                out.append(command_map[command])
                continue
            if command in {'{', '}'}:
                out.append('(' if command == '{' else ')')
                continue
            raise UnsupportedMathAnswer(f'Команда \\{command} не поддерживается проверкой ответа.')
        elif char == '{':
            out.append('(')
            index += 1
        elif char == '}':
            out.append(')')
            index += 1
        elif char == '^':
            out.append('**')
            index += 1
        elif char == '_':
            raise UnsupportedMathAnswer('Индексы переменных не входят в поддерживаемую грамматику ответа.')
        else:
            out.append(char)
            index += 1
    expression = ''.join(out).strip()
    expression = re.sub(r'(?<=\d),(?=\d)', '.', expression)
    expression = re.sub(r'\s+', ' ', expression)
    return expression


def _tokens_with_implicit_multiplication(expression: str) -> str:
    token_pattern = re.compile(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[A-Za-z]+|\*\*|[()+\-*/.,]')
    tokens = token_pattern.findall(expression.replace(' ', ''))
    if ''.join(tokens) != expression.replace(' ', ''):
        raise UnsupportedMathAnswer('Используйте числа, x/y, скобки и арифметические знаки.')
    known_functions = {'sqrt', 'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan', 'ln', 'log', 'exp'}
    known_names = known_functions | {'x', 'y', 'pi', 'e', 'inf'}
    normalized: list[str] = []
    for token in tokens:
        if token.isalpha() and token not in known_names:
            if set(token) <= {'x', 'y'} and len(token) > 1:
                normalized.extend(list(token))
            else:
                raise UnsupportedMathAnswer(f'Переменная или функция «{token}» не разрешена.')
        else:
            normalized.append(token)

    result: list[str] = []
    for index, token in enumerate(normalized):
        if result:
            previous = result[-1]
            previous_is_value = previous == ')' or previous[0].isdigit() or previous in {'x', 'y', 'pi', 'e', 'inf'}
            current_is_value = token == '(' or token[0].isdigit() or token in {'x', 'y', 'pi', 'e', 'inf'} or token in known_functions
            is_function_call = previous in known_functions and token == '('
            if previous_is_value and current_is_value and not is_function_call:
                result.append('*')
        result.append(token)
    return ''.join(result)


def _parse_expression(value: str) -> ast.Expression:
    expression = _tokens_with_implicit_multiplication(latex_to_expression(value))
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError) as exc:
        raise MathAnswerError('Проверьте запись выражения и скобки.') from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise UnsupportedMathAnswer('Выражение слишком сложное для проверки.')

    def depth(node: ast.AST, level: int = 0) -> int:
        if level > MAX_AST_DEPTH:
            return level
        return max((depth(child, level + 1) for child in ast.iter_child_nodes(node)), default=level)

    if depth(tree) > MAX_AST_DEPTH:
        raise UnsupportedMathAnswer('Слишком много уровней вложенности.')
    return tree


def _number_node(value: Any) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MathAnswerError('Ожидалось число.')
    return Fraction(str(value))


def _eval_numeric(node: ast.AST, variables: dict[str, float | Fraction] | None = None) -> Fraction | float:
    if isinstance(node, ast.Expression):
        return _eval_numeric(node.body, variables)
    if isinstance(node, ast.Constant):
        return _number_node(node.value)
    if isinstance(node, ast.Name):
        if variables and node.id in variables:
            return variables[node.id]
        if node.id == 'pi': return math.pi
        if node.id == 'e': return math.e
        raise UnsupportedMathAnswer('В числовом ответе нельзя использовать переменные.')
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_numeric(node.operand, variables)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left = _eval_numeric(node.left, variables)
        right = _eval_numeric(node.right, variables)
        if isinstance(node.op, ast.Add): result = left + right
        elif isinstance(node.op, ast.Sub): result = left - right
        elif isinstance(node.op, ast.Mult): result = left * right
        elif isinstance(node.op, ast.Div):
            if right == 0: raise MathAnswerError('Деление на ноль.')
            result = left / right
        else:
            if not isinstance(right, Fraction) or abs(right.numerator) > MAX_INTEGER_POWER or right.denominator > MAX_INTEGER_POWER:
                raise UnsupportedMathAnswer('Показатель степени выходит за безопасный диапазон.')
            if left == 0 and right < 0: raise MathAnswerError('Ноль нельзя возводить в отрицательную степень.')
            if right.denominator == 1:
                result = left ** right.numerator
            else:
                base = float(left)
                if base < 0 and right.denominator % 2 == 0:
                    raise MathAnswerError('Корень чётной степени из отрицательного числа не является действительным.')
                magnitude = abs(base) ** float(right)
                result = -magnitude if base < 0 and right.numerator % 2 else magnitude
        if isinstance(result, float) and (not math.isfinite(result) or abs(result) > 1e100):
            raise UnsupportedMathAnswer('Результат выходит за безопасный диапазон.')
        return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords and len(node.args) == 1:
        functions = {
            'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'arcsin': math.asin, 'arccos': math.acos, 'arctan': math.atan,
            'ln': math.log, 'log': math.log10, 'exp': math.exp,
        }
        function = functions.get(node.func.id)
        if not function:
            raise UnsupportedMathAnswer('Эта функция не поддерживается.')
        argument = _eval_numeric(node.args[0], variables)
        try:
            result = function(float(argument))
        except (ValueError, OverflowError) as exc:
            raise MathAnswerError('Аргумент функции вне допустимой области.') from exc
        if not math.isfinite(result) or abs(result) > 1e100:
            raise UnsupportedMathAnswer('Результат выходит за безопасный диапазон.')
        return result
    raise UnsupportedMathAnswer('В выражении найдена неподдерживаемая операция.')


def _eval_fraction(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Expression): return _eval_fraction(node.body)
    if isinstance(node, ast.Constant): return _number_node(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_fraction(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left, right = _eval_fraction(node.left), _eval_fraction(node.right)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div):
            if right == 0: raise MathAnswerError('Деление на ноль.')
            return left / right
        if right.denominator != 1 or abs(right.numerator) > MAX_INTEGER_POWER:
            raise UnsupportedMathAnswer('Для дробной проверки показатель степени должен быть небольшим целым.')
        if left == 0 and right < 0: raise MathAnswerError('Ноль нельзя возводить в отрицательную степень.')
        return left ** right.numerator
    raise UnsupportedMathAnswer('Дробная проверка поддерживает только рациональную арифметику.')


def evaluate_numeric_expression(expression: str, variables: dict[str, float | Fraction] | None = None) -> float:
    """Evaluate a bounded real expression for server-generated plots only."""
    result = float(_eval_numeric(_parse_expression(expression), variables))
    if not math.isfinite(result) or abs(result) > 1e100:
        raise UnsupportedMathAnswer('Значение выходит за безопасный диапазон.')
    return result


Polynomial = dict[tuple[tuple[str, int], ...], Fraction]


def _poly_clean(poly: Polynomial) -> Polynomial:
    result = {term: value for term, value in poly.items() if value}
    if len(result) > MAX_POLYNOMIAL_TERMS:
        raise UnsupportedMathAnswer('Слишком много слагаемых для безопасной проверки.')
    if any(sum(power for _, power in term) > MAX_POLYNOMIAL_DEGREE for term in result):
        raise UnsupportedMathAnswer('Степень многочлена слишком велика для проверки.')
    return result


def _poly_add(left: Polynomial, right: Polynomial, factor: int = 1) -> Polynomial:
    output = dict(left)
    for term, value in right.items(): output[term] = output.get(term, Fraction(0)) + factor * value
    return _poly_clean(output)


def _poly_mul(left: Polynomial, right: Polynomial) -> Polynomial:
    output: Polynomial = {}
    for left_term, left_value in left.items():
        for right_term, right_value in right.items():
            powers: dict[str, int] = {}
            for name, power in (*left_term, *right_term): powers[name] = powers.get(name, 0) + power
            term = tuple(sorted((name, power) for name, power in powers.items() if power))
            output[term] = output.get(term, Fraction(0)) + left_value * right_value
            if len(output) > MAX_POLYNOMIAL_TERMS:
                raise UnsupportedMathAnswer('Слишком много слагаемых для безопасной проверки.')
    return _poly_clean(output)


def _poly_eval(node: ast.AST) -> Polynomial:
    if isinstance(node, ast.Expression): return _poly_eval(node.body)
    if isinstance(node, ast.Constant): return {(): _number_node(node.value)}
    if isinstance(node, ast.Name) and node.id in {'x', 'y'}: return {((node.id, 1),): Fraction(1)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        poly = _poly_eval(node.operand)
        return poly if isinstance(node.op, ast.UAdd) else {term: -value for term, value in poly.items()}
    if isinstance(node, ast.BinOp):
        left, right = _poly_eval(node.left), _poly_eval(node.right)
        if isinstance(node.op, ast.Add): return _poly_add(left, right)
        if isinstance(node.op, ast.Sub): return _poly_add(left, right, -1)
        if isinstance(node.op, ast.Mult): return _poly_mul(left, right)
        if isinstance(node.op, ast.Div):
            denominator = right.get(())
            if denominator is None or len(right) != 1 or denominator == 0:
                raise UnsupportedMathAnswer('Символьная проверка разрешает деление только на ненулевую константу; так сохраняется область определения.')
            return _poly_clean({term: coefficient / denominator for term, coefficient in left.items()})
        if isinstance(node.op, ast.Pow):
            exponent = right.get(())
            if exponent is None or len(right) != 1 or exponent.denominator != 1 or not 0 <= exponent.numerator <= MAX_INTEGER_POWER:
                raise UnsupportedMathAnswer('В многочлене показатель должен быть целым от 0 до 12.')
            result: Polynomial = {(): Fraction(1)}
            for _ in range(exponent.numerator): result = _poly_mul(result, left)
            return result
    raise UnsupportedMathAnswer('Символьная проверка поддерживает только многочлены от x и y.')


def _symbolic_equal(selected: str, expected: str) -> bool:
    def parse_polynomial(source: str) -> Polynomial:
        if source.count('=') > 1:
            raise MathAnswerError('В ответе допускается одно равенство.')
        if '=' in source:
            left, right = source.split('=', 1)
            return _poly_add(_poly_eval(_parse_expression(left)), _poly_eval(_parse_expression(right)), -1)
        return _poly_eval(_parse_expression(source))
    return parse_polynomial(selected) == parse_polynomial(expected)


def _parse_rational_endpoint(value: str) -> Fraction | float:
    value = value.strip().lower().replace('∞', 'inf')
    if value in {'inf', '+inf', 'infinity', '+infinity'}: return math.inf
    if value in {'-inf', '-infinity'}: return -math.inf
    return _eval_fraction(_parse_expression(value))


def _parse_interval(value: str) -> tuple[Fraction | float, Fraction | float, bool, bool]:
    text = (value or '').strip()
    if len(text) < 5 or text[0] not in '[(' or text[-1] not in ')]':
        raise MathAnswerError('Интервал задаётся как (a; b), [a; b], (a; b] или [a; b).')
    body = text[1:-1]
    if ';' not in body:
        raise MathAnswerError('Разделяйте границы интервала точкой с запятой.')
    left_text, right_text = body.split(';', 1)
    left, right = _parse_rational_endpoint(left_text), _parse_rational_endpoint(right_text)
    left_closed, right_closed = text[0] == '[', text[-1] == ']'
    if left == math.inf or right == -math.inf or left > right:
        raise MathAnswerError('Границы интервала заданы в неверном порядке.')
    if left == -math.inf and left_closed or right == math.inf and right_closed:
        raise MathAnswerError('Бесконечную границу нельзя включать в интервал.')
    return left, right, left_closed, right_closed


def _parse_finite_set(value: str) -> set[Fraction]:
    text = (value or '').strip()
    if len(text) < 2 or text[0] != '{' or text[-1] != '}':
        raise MathAnswerError('Множество задаётся в фигурных скобках, например {−1; 2}.')
    body = text[1:-1].strip()
    if not body: return set()
    if ',' in body and ';' not in body:
        body = re.sub(r'(?<=\d),(?=\d)', '.', body)
        parts = body.split(',') if ', ' in body else [body]
    else:
        parts = body.split(';')
    return {_eval_fraction(_parse_expression(part)) for part in parts if part.strip()}


def _parse_tolerance(value: str | None, name: str, max_value: Fraction) -> Fraction:
    if not value: return Fraction(0)
    try:
        number = Fraction(value.strip().replace(',', '.'))
    except (ValueError, ZeroDivisionError) as exc:
        raise MathAnswerError(f'Некорректная настройка {name}.') from exc
    if number < 0 or number > max_value:
        raise MathAnswerError(f'Настройка {name} вне допустимого диапазона.')
    return number


def _math_equal(selected: str, expected: str, validator: str, absolute_tolerance: str | None, relative_tolerance: str | None) -> bool:
    if validator == 'numeric':
        return _eval_numeric(_parse_expression(selected)) == _eval_numeric(_parse_expression(expected))
    if validator == 'numeric_tolerance':
        left = float(_eval_numeric(_parse_expression(selected)))
        right = float(_eval_numeric(_parse_expression(expected)))
        abs_tol = float(_parse_tolerance(absolute_tolerance, 'absolute_tolerance', Fraction(1_000_000)))
        rel_tol = float(_parse_tolerance(relative_tolerance, 'relative_tolerance', Fraction(1)))
        if abs_tol == 0 and rel_tol == 0:
            raise MathAnswerError('Для numeric_tolerance задайте ненулевую абсолютную или относительную погрешность.')
        return math.isclose(left, right, abs_tol=abs_tol, rel_tol=rel_tol)
    if validator == 'fraction': return _eval_fraction(_parse_expression(selected)) == _eval_fraction(_parse_expression(expected))
    if validator == 'symbolic': return _symbolic_equal(selected, expected)
    if validator == 'set': return _parse_finite_set(selected) == _parse_finite_set(expected)
    if validator == 'interval': return _parse_interval(selected) == _parse_interval(expected)
    raise UnsupportedMathAnswer('Неизвестный математический validator.')


def validate_math_answer(
    selected: str,
    expected: str,
    *,
    validator: str = 'numeric',
    absolute_tolerance: str | None = None,
    relative_tolerance: str | None = None,
    valid_answers: str = '',
    domain: str = '',
) -> dict[str, Any]:
    """Compare an answer within a strict grammar and return safe feedback status."""
    selected = str(selected or '').strip()
    if len(selected) > MAX_INPUT_LENGTH:
        return {'correct': False, 'status': 'invalid_format', 'message': 'Ответ слишком длинный.'}
    validator = (validator or 'numeric').strip().lower()
    if validator not in SUPPORTED_VALIDATORS:
        return {'correct': False, 'status': 'unsupported', 'message': 'Этот тип математической проверки не поддерживается.'}
    if domain.strip() and domain.strip().lower() not in {'real', 'reals', 'ℝ'}:
        return {'correct': False, 'status': 'unsupported', 'message': 'Для этой проверки поддерживается только область действительных чисел.'}
    candidates = [item.strip() for item in (valid_answers or '').split('|') if item.strip()]
    candidates = candidates or [str(expected or '').strip()]
    if not selected:
        return {'correct': False, 'status': 'invalid_format', 'message': 'Введите математический ответ.'}
    if validator == 'exact':
        correct = selected.strip().casefold() in {candidate.strip().casefold() for candidate in candidates}
        return {'correct': correct, 'status': 'correct' if correct else 'incorrect', 'message': ''}
    try:
        correct = any(_math_equal(selected, candidate, validator, absolute_tolerance, relative_tolerance) for candidate in candidates)
    except UnsupportedMathAnswer as exc:
        return {'correct': False, 'status': 'unsupported', 'message': str(exc)}
    except (MathAnswerError, ArithmeticError, OverflowError, ValueError) as exc:
        return {'correct': False, 'status': 'invalid_format', 'message': str(exc) or 'Проверьте формат ответа.'}
    return {'correct': bool(correct), 'status': 'correct' if correct else 'incorrect', 'message': ''}
