"""Validation and safe, idempotent import for Markdown math-course packages."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_MANIFEST_BYTES = 2_000_000
MAX_ARTICLE_BYTES = 500_000
MAX_PACKAGE_BYTES = 75_000_000
MAX_ASSET_BYTES = 15_000_000
MAX_COURSE_ARTICLES = 500
ASSET_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.svg'}
ASSET_REFERENCE_RE = re.compile(r'!\[([^\]]*)\]\(asset:([a-zA-Z0-9][a-zA-Z0-9._-]{0,63})\)')
MATH_DELIMITERS = ((r'\[', r'\]', True), (r'\(', r'\)', False), ('$$', '$$', True), ('$', '$', False))
SUPPORTED_INTERACTIVE_TYPES = {
    'input', 'choice', 'order', 'table', 'code', 'boolean', 'multi', 'match',
    'classify', 'fill', 'slider', 'hotspot', 'sequence', 'trace', 'regex',
    'binary', 'formula', 'predict', 'debug', 'explain', 'math',
}
PAIRED_MARKERS = (
    'LEVEL', 'CODE', 'CODE_RUNNER', 'CALLOUT', 'REMEMBER', 'IMPORTANT', 'NOTE',
    'WARNING', 'TIP', 'INFO', 'TRY', 'HOW_IT_WORKS', 'DEFINITION', 'THEOREM',
    'PROOF', 'EXAMPLE', 'SOLUTION', 'FORMULA', 'COMMON_MISTAKE', 'SUMMARY',
    'STEP_EXERCISE', 'FUNCTION_PLOT', 'GEOMETRY',
)


@dataclass
class ValidationReport:
    package_dir: str
    course_slug: str = ''
    course_title: str = ''
    groups: int = 0
    articles: int = 0
    assets: int = 0
    total_bytes: int = 0
    package_sha256: str = ''
    issues: list[dict[str, Any]] = field(default_factory=list)
    latex_checked: bool = False

    @property
    def valid(self) -> bool:
        return not any(issue.get('severity') == 'error' for issue in self.issues)

    def add(self, severity: str, file: str, line: int | None, message: str) -> None:
        self.issues.append({'severity': severity, 'file': file, 'line': line, 'message': message})

    def as_dict(self) -> dict[str, Any]:
        return {
            'valid': self.valid, 'package_dir': self.package_dir,
            'course_slug': self.course_slug, 'course_title': self.course_title,
            'groups': self.groups, 'articles': self.articles, 'assets': self.assets,
            'total_bytes': self.total_bytes, 'package_sha256': self.package_sha256,
            'latex_checked': self.latex_checked,
            'issues': self.issues,
        }


def content_hash(content: str) -> str:
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def package_tree_sha256(package_dir: str | Path) -> str:
    """Hash regular package files, treating text CRLF and LF as identical."""
    root = Path(package_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Путь пакета должен указывать на каталог.')
    digest = hashlib.sha256()
    total_bytes = 0
    text_suffixes = {'.csv', '.html', '.json', '.md', '.svg', '.txt', '.xml', '.yaml', '.yml'}
    for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f'Символические ссылки в пакете запрещены: {path.relative_to(root)}.')
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode('utf-8')
        source_size = path.stat().st_size
        total_bytes += source_size
        if total_bytes > MAX_PACKAGE_BYTES:
            raise ValueError(f'Объём пакета превышает {MAX_PACKAGE_BYTES} байт.')
        digest.update(len(relative).to_bytes(8, 'big'))
        digest.update(relative)
        if path.suffix.lower() in text_suffixes:
            content = path.read_bytes().replace(b'\r\n', b'\n')
            digest.update(len(content).to_bytes(8, 'big'))
            digest.update(content)
        else:
            digest.update(source_size.to_bytes(8, 'big'))
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
    return digest.hexdigest()


def _package_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError('Путь к файлу должен быть непустой строкой.')
    candidate = root / relative
    if any(part == '..' for part in Path(relative).parts):
        raise ValueError('Путь не может выходить за каталог пакета.')
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Символические ссылки в пакете запрещены.')
    resolved = candidate.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError('Файл должен находиться внутри пакета.')
    return resolved


def _read_utf8(path: Path, maximum: int) -> str:
    payload = path.read_bytes()
    if len(payload) > maximum:
        raise ValueError(f'Файл превышает лимит {maximum} байт.')
    return payload.decode('utf-8-sig')


def _remove_code_regions(text: str) -> str:
    text = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$', '', text)
    text = re.sub(r'(?is)\[CODE(?:_RUNNER)?\b[^\]]*\].*?\[/CODE(?:_RUNNER)?\]', '', text)
    text = re.sub(r'`+[^`]*`+', '', text)
    return text


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    index -= 1
    while index >= 0 and text[index] == '\\':
        count += 1
        index -= 1
    return count % 2 == 1


def _extract_math(text: str) -> tuple[list[tuple[str, bool, int]], list[int]]:
    formulas: list[tuple[str, bool, int]] = []
    unclosed: list[int] = []
    index = 0
    while index < len(text):
        opening = next((item for item in MATH_DELIMITERS if text.startswith(item[0], index)), None)
        if not opening or _is_escaped(text, index):
            index += 1
            continue
        left, right, display = opening
        if left == '$' and (text.startswith('$$', index) or index + 1 == len(text) or text[index + 1].isspace()):
            index += 1
            continue
        closing = text.find(right, index + len(left))
        while closing >= 0 and _is_escaped(text, closing):
            closing = text.find(right, closing + len(right))
        if closing < 0:
            unclosed.append(text.count('\n', 0, index) + 1)
            index += len(left)
            continue
        source = text[index + len(left):closing]
        if source.strip():
            formulas.append((source, display, text.count('\n', 0, index) + 1))
        index = closing + len(right)
    return formulas, unclosed


def _validate_latex(expressions: list[str], report: ValidationReport) -> None:
    if not expressions:
        report.latex_checked = True
        return
    script = (
        "const fs=require('fs');const katex=require('katex');"
        "const xs=JSON.parse(fs.readFileSync(0,'utf8'));let bad=[];"
        "xs.forEach((x,i)=>{try{katex.renderToString(x,{throwOnError:true,trust:false,maxSize:50,maxExpand:500});}"
        "catch(e){bad.push({index:i,message:String(e.message||e).slice(0,240)});}});"
        "process.stdout.write(JSON.stringify(bad));"
    )
    node = shutil.which('node')
    if not node:
        report.add('warning', 'manifest.json', None, 'Node.js не найден: синтаксис LaTeX проверен только на баланс разделителей.')
        return
    try:
        result = subprocess.run(
            [node, '-e', script], input=json.dumps(expressions, ensure_ascii=False),
            text=True, capture_output=True, timeout=15, check=False,
            cwd=Path(__file__).resolve().parents[2],
        )
    except subprocess.TimeoutExpired:
        report.add('error', 'manifest.json', None, 'Проверка формул через KaTeX превысила лимит 15 секунд.')
        return
    if result.returncode != 0:
        report.add('warning', 'manifest.json', None, 'Локальный пакет KaTeX недоступен; проверка синтаксиса формул не выполнена.')
        return
    report.latex_checked = True
    try:
        errors = json.loads(result.stdout or '[]')
    except json.JSONDecodeError:
        report.add('error', 'manifest.json', None, 'Проверка KaTeX вернула некорректный ответ.')
        return
    for item in errors:
        index = item.get('index', -1)
        if 0 <= index < len(expressions):
            report.add('error', 'LaTeX', None, f'Формула {index + 1}: {item.get("message", "ошибка KaTeX")}')


def validate_math_package(package_dir: str | Path) -> tuple[dict[str, Any] | None, ValidationReport]:
    root = Path(package_dir).resolve()
    report = ValidationReport(package_dir=str(root))
    try:
        report.package_sha256 = package_tree_sha256(root)
    except (OSError, ValueError) as exc:
        report.add('error', 'package', None, str(exc))
    try:
        manifest_file = _package_file(root, 'manifest.json')
        manifest_text = _read_utf8(manifest_file, MAX_MANIFEST_BYTES)
        report.total_bytes += manifest_file.stat().st_size
        manifest = json.loads(manifest_text)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        report.add('error', 'manifest.json', None, str(exc))
        return None, report
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        report.add('error', 'manifest.json', None, 'Ожидается JSON-объект schema_version=1.')
        return manifest, report
    course = manifest.get('course')
    groups = manifest.get('groups')
    if not isinstance(course, dict) or not isinstance(groups, list):
        report.add('error', 'manifest.json', None, 'Обязательны объекты course и groups[].')
        return manifest, report
    report.groups = len(groups)

    title, slug = course.get('title'), course.get('slug')
    report.course_slug = str(slug or '')
    report.course_title = str(title or '')
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        report.add('error', 'manifest.json', None, 'course.title обязателен и не длиннее 200 символов.')
    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,49}', slug):
        report.add('error', 'manifest.json', None, 'course.slug: 2–50 символов, строчные латинские буквы, цифры, дефис или подчёркивание.')

    package_assets: dict[str, tuple[str, Path]] = {}
    all_formulas: list[tuple[str, str, int]] = []
    seen_group_keys: set[str] = set()
    seen_group_positions: set[int] = set()
    seen_task_numbers: set[int] = set()
    seen_article_keys: set[str] = set()
    total_articles = 0
    for group_index, group in enumerate(groups):
        group_file = f'manifest.json#/groups/{group_index}'
        if not isinstance(group, dict):
            report.add('error', group_file, None, 'Группа должна быть JSON-объектом.')
            continue
        group_key, group_name = group.get('key'), group.get('name')
        if not isinstance(group_key, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', group_key) or group_key in seen_group_keys:
            report.add('error', group_file, None, 'group.key должен быть уникальным коротким стабильным ключом.')
        else:
            seen_group_keys.add(group_key)
        if not isinstance(group_name, str) or not group_name.strip() or len(group_name) > 200:
            report.add('error', group_file, None, 'group.name обязателен и не длиннее 200 символов.')
        if isinstance(group.get('position'), bool) or not isinstance(group.get('position'), int) or group['position'] < 1:
            report.add('error', group_file, None, 'group.position должен быть положительным целым числом.')
        elif group['position'] in seen_group_positions:
            report.add('error', group_file, None, 'group.position должен быть уникальным в рамках курса.')
        else:
            seen_group_positions.add(group['position'])
        if group.get('description') is not None and (not isinstance(group['description'], str) or len(group['description']) > 500):
            report.add('error', group_file, None, 'group.description не длиннее 500 символов.')
        assets = group.get('assets', [])
        if not isinstance(assets, list):
            report.add('error', group_file, None, 'group.assets должен быть массивом.')
            assets = []
        for asset_index, asset in enumerate(assets):
            try:
                if not isinstance(asset, dict): raise ValueError('Описание asset должно быть объектом.')
                key, relative = asset.get('key'), asset.get('path')
                if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}', key):
                    raise ValueError('asset.key имеет неверный формат.')
                if key in package_assets:
                    raise ValueError(f'Ключ изображения {key} повторяется в курсе.')
                path = _package_file(root, relative)
                if path.suffix.lower() not in ASSET_EXTENSIONS:
                    raise ValueError('Поддерживаются только PNG, JPG/JPEG, WebP и SVG.')
                size = path.stat().st_size
                if size <= 0 or size > MAX_ASSET_BYTES:
                    raise ValueError(f'Размер изображения должен быть от 1 байта до {MAX_ASSET_BYTES}.')
                payload = path.read_bytes()
                if path.suffix.lower() == '.png' and not payload.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('Файл с расширением PNG имеет неверную сигнатуру.')
                if path.suffix.lower() in {'.jpg', '.jpeg'} and not payload.startswith(b'\xff\xd8\xff'):
                    raise ValueError('Файл JPEG имеет неверную сигнатуру.')
                if path.suffix.lower() == '.webp' and not (payload.startswith(b'RIFF') and payload[8:12] == b'WEBP'):
                    raise ValueError('Файл WebP имеет неверную сигнатуру.')
                if path.suffix.lower() == '.svg':
                    _sanitize_svg(payload)
                package_assets[key] = (group_key, path)
                report.assets += 1
                report.total_bytes += size
            except (OSError, ValueError) as exc:
                report.add('error', f'{group_file}/assets/{asset_index}', None, str(exc))

        articles = group.get('articles')
        if not isinstance(articles, list):
            report.add('error', group_file, None, 'group.articles должен быть массивом.')
            continue
        seen_article_positions: set[int] = set()
        for article_index, article in enumerate(articles):
            total_articles += 1
            article_file = f'{group_file}/articles/{article_index}'
            if not isinstance(article, dict):
                report.add('error', article_file, None, 'Материал должен быть JSON-объектом.')
                continue
            key, task_number = article.get('key'), article.get('task_number')
            if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}', key) or key in seen_article_keys:
                report.add('error', article_file, None, 'article.key должен быть уникальным стабильным ключом.')
            else:
                seen_article_keys.add(key)
            if isinstance(task_number, bool) or not isinstance(task_number, int) or task_number < 1 or task_number in seen_task_numbers:
                report.add('error', article_file, None, 'task_number должен быть положительным и уникальным во всём курсе.')
            else:
                seen_task_numbers.add(task_number)
            for field_name, maximum, required in (('title', 200, True), ('description', 500, False)):
                value = article.get(field_name)
                if required and (not isinstance(value, str) or not value.strip()):
                    report.add('error', article_file, None, f'{field_name} обязателен.')
                elif value is not None and (not isinstance(value, str) or len(value) > maximum):
                    report.add('error', article_file, None, f'{field_name} превышает {maximum} символов.')
            minutes = article.get('read_minutes', 5)
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
                report.add('error', article_file, None, 'read_minutes должен быть целым числом от 1 до 180.')
            if isinstance(article.get('position'), bool) or not isinstance(article.get('position'), int) or article['position'] < 1:
                report.add('error', article_file, None, 'article.position должен быть положительным целым числом.')
            elif article['position'] in seen_article_positions:
                report.add('error', article_file, None, 'article.position должен быть уникальным внутри группы.')
            else:
                seen_article_positions.add(article['position'])
            if not isinstance(article.get('status', 'draft'), str) or article.get('status', 'draft') not in {'draft', 'published'}:
                report.add('error', article_file, None, 'status допускает draft или published; импорт всё равно сохраняет draft.')
            try:
                source_path = _package_file(root, article.get('source'))
                content = _read_utf8(source_path, MAX_ARTICLE_BYTES)
                report.total_bytes += source_path.stat().st_size
            except (OSError, ValueError, UnicodeError) as exc:
                report.add('error', article_file, None, str(exc))
                continue
            if not content.strip():
                report.add('error', str(article.get('source')), None, 'Файл статьи пуст.')
                continue
            image_refs = list(ASSET_REFERENCE_RE.finditer(content))
            for match in image_refs:
                asset = package_assets.get(match.group(2))
                if not match.group(1).strip():
                    report.add('error', str(article.get('source')), content.count('\n', 0, match.start()) + 1, 'У изображения обязателен alt-текст.')
                elif not asset:
                    report.add('error', str(article.get('source')), content.count('\n', 0, match.start()) + 1, f'Не найден asset с ключом {match.group(2)}.')
                elif asset[0] != group_key:
                    report.add('error', str(article.get('source')), content.count('\n', 0, match.start()) + 1, 'Изображение должно быть объявлено в своей тематической группе.')
            unknown_asset_refs = re.findall(r'!\[[^\]]*\]\(asset:([^\s)]+)\)', content)
            if len(unknown_asset_refs) != len(image_refs):
                report.add('error', str(article.get('source')), None, 'Ссылка asset: должна иметь форму ![alt](asset:key).')

            clean_for_structure = _remove_code_regions(content)
            for marker in PAIRED_MARKERS:
                open_count = len(re.findall(rf'\[{marker}(?:\s+[^\]]*)?\]', clean_for_structure, re.IGNORECASE))
                close_count = len(re.findall(rf'\[/{marker}\]', clean_for_structure, re.IGNORECASE))
                if open_count != close_count:
                    report.add('error', str(article.get('source')), None, f'У маркера {marker} не совпадают открывающие и закрывающие конструкции ({open_count}/{close_count}).')
            if re.search(r'<\s*/?\s*(?:script|iframe|svg|math-field|object|embed)\b|\bon[a-z]+\s*=', clean_for_structure, re.IGNORECASE):
                report.add('error', str(article.get('source')), None, 'В авторском Markdown найдена запрещённая HTML/JS-разметка.')
            marker_attr_pattern = r'\[(INTERACTIVE|STEP)\s+((?:[^"\]]|"(?:[^"\\]|\\.)*")+?)\]'
            attr_blocks = list(re.finditer(marker_attr_pattern, content, re.IGNORECASE | re.DOTALL))
            for attr_match in attr_blocks:
                attrs = {name.lower(): value for name, value in re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', attr_match.group(2))}
                marker = attr_match.group(1).upper()
                marker_line = content.count('\n', 0, attr_match.start()) + 1
                if marker == 'INTERACTIVE':
                    if not attrs.get('key') or not attrs.get('prompt') or not attrs.get('answer'):
                        report.add('error', str(article.get('source')), marker_line,
                                   'INTERACTIVE требует стабильные key, prompt и answer.')
                    elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', attrs['key']):
                        report.add('error', str(article.get('source')), marker_line,
                                   'INTERACTIVE key: латинские буквы, цифры, точка, дефис или подчёркивание; максимум 80 символов.')
                    if len(attrs.get('key', '')) > 80:
                        report.add('error', str(article.get('source')), marker_line,
                                   'INTERACTIVE key не длиннее 80 символов (лимит TheoryCheckpointAttempt).')
                    if len(attrs.get('answer', '')) > 500:
                        report.add('error', str(article.get('source')), marker_line,
                                   'INTERACTIVE answer не длиннее 500 символов.')
                    if len(attrs.get('prompt', '')) > 3000:
                        report.add('error', str(article.get('source')), marker_line,
                                   'INTERACTIVE prompt не длиннее 3000 символов.')
                else:
                    if not attrs.get('key') or not attrs.get('prompt') or not attrs.get('answer'):
                        report.add('error', str(article.get('source')), marker_line,
                                   'STEP требует стабильные key, prompt и answer.')
                    elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', attrs['key']):
                        report.add('error', str(article.get('source')), marker_line,
                                   'STEP key: латинские буквы, цифры, точка, дефис или подчёркивание; максимум 80 символов.')
                    if len(attrs.get('key', '')) > 80 or len(attrs.get('answer', '')) > 500:
                        report.add('error', str(article.get('source')), marker_line,
                                   'STEP key ограничен 80, answer — 500 символами.')
                    if len(attrs.get('prompt', '')) > 3000:
                        report.add('error', str(article.get('source')), marker_line,
                                   'STEP prompt не длиннее 3000 символов.')
                if 'type' in attrs and attrs['type'].lower() not in SUPPORTED_INTERACTIVE_TYPES:
                    report.add('error', str(article.get('source')), marker_line, f'Тип интерактива {attrs["type"]} не поддерживается.')
            for checkpoint_match in re.finditer(r'\[CHECKPOINT\s+((?:[^"\]]|"(?:[^"\\]|\\.)*")+?)\]', clean_for_structure, re.IGNORECASE | re.DOTALL):
                attrs = {name.lower(): value for name, value in re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', checkpoint_match.group(1))}
                marker_line = clean_for_structure.count('\n', 0, checkpoint_match.start()) + 1
                options = [item.strip() for item in attrs.get('options', '').split('|') if item.strip()]
                if not attrs.get('key') or not attrs.get('question') or not attrs.get('answer') or len(options) < 2:
                    report.add('error', str(article.get('source')), marker_line,
                               'CHECKPOINT требует key, question, минимум два options и answer.')
                elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', attrs['key']):
                    report.add('error', str(article.get('source')), marker_line,
                               'CHECKPOINT key: латинские буквы, цифры, точка, дефис или подчёркивание; максимум 80 символов.')
                if len(attrs.get('key', '')) > 80 or len(attrs.get('answer', '')) > 500:
                    report.add('error', str(article.get('source')), marker_line,
                               'CHECKPOINT key ограничен 80, answer — 500 символами.')
                if attrs.get('answer') not in options:
                    report.add('error', str(article.get('source')), marker_line,
                               'CHECKPOINT answer должен точно совпадать с одним options.')
                if len(attrs.get('question', '')) > 3000 or len(options) > 20 or any(len(option) > 500 for option in options):
                    report.add('error', str(article.get('source')), marker_line,
                               'CHECKPOINT ограничен вопросом 3000 символов, 20 вариантами по 500 символов.')
            for exercise_match in re.finditer(r'\[STEP_EXERCISE\s+([^\]]+)\](.*?)\[/STEP_EXERCISE\]', clean_for_structure, re.IGNORECASE | re.DOTALL):
                attrs = {name.lower(): value for name, value in re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', exercise_match.group(1))}
                marker_line = clean_for_structure.count('\n', 0, exercise_match.start()) + 1
                if not attrs.get('key'):
                    report.add('error', str(article.get('source')), marker_line,
                               'STEP_EXERCISE требует стабильный key.')
                elif len(attrs['key']) > 40:
                    report.add('error', str(article.get('source')), marker_line,
                               'STEP_EXERCISE key ограничен 40 символами для ключа сохранения шага.')
                steps = list(re.finditer(r'\[STEP\s+((?:[^"\]]|"(?:[^"\\]|\\.)*")+?)\]', exercise_match.group(2), re.IGNORECASE | re.DOTALL))
                if not steps:
                    report.add('error', str(article.get('source')), marker_line,
                               'STEP_EXERCISE должен содержать хотя бы один STEP.')
                for step_match in steps:
                    step_attrs = {name.lower(): value for name, value in re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', step_match.group(1))}
                    if attrs.get('key') and step_attrs.get('key') and len(attrs['key']) + 1 + len(step_attrs['key']) > 80:
                        report.add('error', str(article.get('source')), marker_line,
                                   'Составной ключ STEP_EXERCISE.key + STEP.key не должен превышать 80 символов.')
            formulas, unclosed_math = _extract_math(_remove_code_regions(content))
            for line in unclosed_math:
                report.add('error', str(article.get('source')), line, 'Незакрытый математический разделитель.')
            for expression, display, line in formulas:
                all_formulas.append((str(article.get('source')), expression, line))
            report.articles += 1

    if total_articles > MAX_COURSE_ARTICLES:
        report.add('error', 'manifest.json', None, f'Общий лимит курса: не более {MAX_COURSE_ARTICLES} статей.')
    expected = manifest.get('expected_structure')
    if expected is not None:
        if not isinstance(expected, dict):
            report.add('error', 'manifest.json', None, 'expected_structure должен быть JSON-объектом.')
        else:
            if expected.get('groups') is not None and expected.get('groups') != len(groups):
                report.add('error', 'manifest.json', None, f'Ожидалось групп: {expected.get("groups")}, найдено: {len(groups)}.')
            if expected.get('articles') is not None and expected.get('articles') != total_articles:
                report.add('error', 'manifest.json', None, f'Ожидалось статей: {expected.get("articles")}, найдено: {total_articles}.')
    if report.total_bytes > MAX_PACKAGE_BYTES:
        report.add('error', 'manifest.json', None, f'Объём пакета превышает {MAX_PACKAGE_BYTES} байт.')
    _validate_latex([formula for _, formula, _ in all_formulas], report)
    # Add source locations after KaTeX has reported expression indices.
    for issue in report.issues:
        if issue.get('file') == 'LaTeX' and issue.get('message', '').startswith('Формула '):
            index = int(re.match(r'Формула (\d+)', issue['message']).group(1)) - 1
            if 0 <= index < len(all_formulas):
                issue['file'], issue['line'] = all_formulas[index][0], all_formulas[index][2]

    # Validate the runtime parser contract (types, required attributes, and unique keys).
    if report.valid:
        from app.theory.routes import _parse_theory_checkpoints, _parse_theory_interactives
        from app.theory.math_validation import SUPPORTED_VALIDATORS, validate_math_answer
        key_by_source: dict[str, set[str]] = {}
        for group in groups:
            for article in group.get('articles', []) if isinstance(group, dict) else []:
                try:
                    source = _package_file(root, article['source'])
                    content = _read_utf8(source, MAX_ARTICLE_BYTES)
                except (KeyError, OSError, ValueError, UnicodeError):
                    continue
                all_items = _parse_theory_checkpoints(content)
                keys = [item['key'] for item in all_items]
                if len(keys) != len(set(keys)):
                    report.add('error', str(article['source']), None, 'Ключи CHECKPOINT/INTERACTIVE/STEP должны быть уникальными в статье.')
                interactives = _parse_theory_interactives(content)
                raw_interactive_count = len(re.findall(r'\[INTERACTIVE\s+', _remove_code_regions(content), re.IGNORECASE))
                raw_step_count = sum(
                    len(re.findall(r'\[STEP\s+', match.group(1), re.IGNORECASE))
                    for match in re.finditer(r'\[STEP_EXERCISE\s+[^\]]+\](.*?)\[/STEP_EXERCISE\]', content, re.IGNORECASE | re.DOTALL)
                )
                raw_checkpoint_count = len(re.findall(r'\[CHECKPOINT\s+', _remove_code_regions(content), re.IGNORECASE))
                if len(interactives) != raw_interactive_count + raw_step_count:
                    report.add('error', str(article['source']), None,
                               'Один или несколько INTERACTIVE/STEP не прошли runtime-парсер: проверьте type, key, prompt и answer.')
                if len(all_items) != raw_interactive_count + raw_step_count + raw_checkpoint_count:
                    report.add('error', str(article['source']), None,
                               'Один или несколько CHECKPOINT не прошли runtime-парсер.')
                for interactive in interactives:
                    if interactive['type'] in {'choice', 'multi', 'classify', 'order', 'sequence'} and not interactive.get('options'):
                        report.add('error', str(article['source']), None, f'Интерактив {interactive["key"]}: для типа {interactive["type"]} обязательны options.')
                    if interactive['type'] in {'choice', 'multi', 'classify', 'order', 'sequence'}:
                        options = [x.strip() for x in interactive.get('options', '').split('|') if x.strip()]
                        if len(options) > 20 or any(len(option) > 500 for option in options):
                            report.add('error', str(article['source']), None,
                                       f'Интерактив {interactive["key"]}: допускается до 20 вариантов длиной до 500 символов.')
                    configured_validator = (interactive.get('validator') or ('numeric' if interactive['type'] == 'math' else '')).strip().lower()
                    if configured_validator:
                        if configured_validator not in SUPPORTED_VALIDATORS:
                            report.add('error', str(article['source']), None,
                                       f'Интерактив {interactive["key"]}: неизвестный validator {configured_validator}.')
                            continue
                        answer_candidates = [x.strip() for x in interactive.get('valid_answers', '').split('|') if x.strip()]
                        answer_candidates = answer_candidates or [interactive['answer']]
                        for candidate in answer_candidates:
                            validation = validate_math_answer(
                                candidate, candidate,
                                validator=configured_validator,
                                absolute_tolerance=interactive.get('absolute_tolerance'),
                                relative_tolerance=interactive.get('relative_tolerance'),
                                domain=interactive.get('domain', ''),
                            )
                            if validation['status'] in {'invalid_format', 'unsupported'}:
                                report.add('error', str(article['source']), None,
                                           f'Интерактив {interactive["key"]}: answer/valid_answers не подходит для validator {configured_validator} ({validation["message"]}).')
                                break
    return manifest, report


def _sanitize_svg(payload: bytes) -> bytes:
    text = payload.decode('utf-8-sig')
    if len(payload) > 2_000_000 or re.search(r'<!DOCTYPE|<!ENTITY', text, re.IGNORECASE):
        raise ValueError('SVG слишком велик или содержит DTD/entity.')
    root = ET.fromstring(text)
    local = lambda tag: tag.rsplit('}', 1)[-1]
    if local(root.tag) != 'svg':
        raise ValueError('Корневым элементом SVG должен быть <svg>.')
    tags = {'svg', 'g', 'path', 'line', 'circle', 'ellipse', 'rect', 'polyline', 'polygon', 'text', 'tspan'}
    attrs = {'xmlns', 'viewBox', 'width', 'height', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'd', 'points', 'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'text-anchor', 'font-size', 'font-family', 'transform'}
    def clean(element: ET.Element) -> ET.Element | None:
        if local(element.tag) not in tags:
            return None
        safe = ET.Element(element.tag)
        for key, value in element.attrib.items():
            name = local(key)
            if name not in attrs or name.lower().startswith('on') or len(value) > 3000:
                continue
            if name in {'fill', 'stroke'} and not re.fullmatch(r'(?:#[0-9a-fA-F]{3,8}|none|currentColor|black|white|red|blue|green)', value):
                continue
            if name == 'transform' and not re.fullmatch(r'[A-Za-z0-9(),. +\-]{1,200}', value):
                continue
            safe.set(name, value)
        safe.text = (element.text or '')[:4000]
        safe.tail = (element.tail or '')[:1000]
        for child in element:
            sanitized = clean(child)
            if sanitized is not None:
                safe.append(sanitized)
        return safe
    sanitized_root = clean(root)
    if sanitized_root is None:
        raise ValueError('SVG не прошёл безопасную фильтрацию.')
    if 'viewBox' not in sanitized_root.attrib:
        sanitized_root.set('viewBox', '0 0 800 600')
    return ET.tostring(sanitized_root, encoding='utf-8', xml_declaration=True)


def _prepared_article_content(root: Path, group: dict[str, Any], article: dict[str, Any], course_slug: str, static_root: Path | None = None) -> tuple[str, dict[str, str]]:
    content = _read_utf8(_package_file(root, article['source']), MAX_ARTICLE_BYTES)
    group_key = group['key']
    staged_assets: dict[str, str] = {}
    for asset in group.get('assets', []):
        source = _package_file(root, asset['path'])
        payload = source.read_bytes()
        if source.suffix.lower() == '.svg':
            payload = _sanitize_svg(payload)
        digest = hashlib.sha256(payload).hexdigest()
        filename = f'{digest[:24]}{source.suffix.lower()}'
        relative = f'uploads/theory_math/{course_slug}/{group_key}/{filename}'
        if static_root is not None:
            destination = static_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                fd, temp_name = tempfile.mkstemp(prefix='.theory-', dir=destination.parent)
                try:
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, destination)
                finally:
                    if os.path.exists(temp_name): os.unlink(temp_name)
        staged_assets[asset['key']] = '/static/' + relative.replace(os.sep, '/')

    def replace_reference(match: re.Match[str]) -> str:
        key = match.group(2)
        url = staged_assets.get(key)
        if not url:
            raise ValueError(f'Не найдено изображение {key}.')
        return f'![{match.group(1)}]({url})'
    content = ASSET_REFERENCE_RE.sub(replace_reference, content)
    from app.theory.routes import _with_status_prefix
    return _with_status_prefix(content, 'draft'), staged_assets


def _strip_status(content: str) -> str:
    return re.sub(r'^<!--status:(?:draft|published)-->\s*', '', content or '').strip()


def build_import_plan(manifest: dict[str, Any], report: ValidationReport, course, *, overwrite: bool = False) -> dict[str, Any]:
    """Compare a validated package to existing rows without changing the database."""
    if not report.valid:
        raise ValueError('Пакет содержит ошибки; импорт запрещён.')
    from app.models import TheoryBlock, TheoryGroup
    entries = []
    conflicts = []
    metadata_conflicts: list[str] = []
    metadata_actions: list[dict[str, Any]] = []
    if course is None:
        metadata_actions.append({'scope': 'course', 'key': manifest['course']['slug'], 'action': 'create'})
    elif course.title != manifest['course']['title']:
        metadata_actions.append({'scope': 'course', 'key': manifest['course']['slug'], 'action': 'update' if overwrite else 'conflict'})
        if not overwrite:
            metadata_conflicts.append(f'course:{manifest["course"]["slug"]}')
    for group in manifest['groups']:
        db_group = TheoryGroup.query.filter_by(course_id=course.id, name=group['name']).first() if course else None
        if db_group is None:
            metadata_actions.append({'scope': 'group', 'key': group['key'], 'name': group['name'], 'action': 'create'})
        group_metadata_changed = bool(db_group and (
            db_group.position != group['position']
            or (db_group.description or '') != (group.get('description') or '')
        ))
        if db_group and group_metadata_changed:
            action = 'update' if overwrite else 'conflict'
            metadata_actions.append({'scope': 'group', 'key': group['key'], 'name': group['name'], 'action': action})
            if not overwrite:
                metadata_conflicts.append(f'group:{group["key"]}')
        for article in group['articles']:
            block = TheoryBlock.query.filter_by(course_id=course.id, task_number=article['task_number']).first() if course else None
            if not block:
                action = 'create'
            else:
                current_content = _strip_status(block.content or '')
                expected_status = 'published' if (block.content or '').startswith('<!--status:published-->') else 'draft'
                incoming, _assets = _prepared_article_content(
                    Path(report.package_dir), group, article,
                    course.slug if course else manifest['course']['slug'],
                )
                incoming = _strip_status(incoming)
                same_group = bool(db_group and block.group_id == db_group.id)
                if current_content == incoming and block.title == article['title'] and (block.description or '') == (article.get('description') or '') and block.position == article['position'] and same_group:
                    action = 'no-op'
                elif expected_status == 'published':
                    action = 'conflict-published'
                    conflicts.append(article['key'])
                elif overwrite:
                    action = 'update'
                else:
                    action = 'conflict'
                    conflicts.append(article['key'])
            entries.append({'group': group, 'group_exists': bool(db_group), 'article': article, 'block': block, 'action': action})
    return {'entries': entries, 'conflicts': conflicts, 'metadata_conflicts': metadata_conflicts, 'metadata_actions': metadata_actions}


def import_drafts(manifest: dict[str, Any], report: ValidationReport, *, author_id: int | None, overwrite: bool = False, db, Course, TheoryBlock, TheoryGroup, static_root: str | Path) -> dict[str, Any]:
    """Upsert only drafts in one database transaction; published content conflicts are never overwritten."""
    if not report.valid:
        raise ValueError('Пакет содержит ошибки; импорт запрещён.')
    course = Course.query.filter_by(slug=manifest['course']['slug']).first()
    if course and course.title != manifest['course']['title'] and not overwrite:
        raise ValueError('Название существующего курса отличается; требуется явная сверка метаданных.')
    plan = build_import_plan(manifest, report, course, overwrite=overwrite)
    if plan['conflicts'] or plan['metadata_conflicts']:
        details = []
        if plan['metadata_conflicts']:
            details.append('метаданные: ' + ', '.join(plan['metadata_conflicts']))
        if plan['conflicts']:
            details.append('статьи: ' + ', '.join(plan['conflicts']))
        raise ValueError('Конфликт статей или метаданных импорта — ' + '; '.join(details))
    root = Path(report.package_dir).resolve()
    static_path = Path(static_root).resolve()
    counters = {'course_created': False, 'groups_created': 0, 'articles_created': 0, 'articles_updated': 0, 'articles_unchanged': 0}
    try:
        if course is None:
            course = Course(title=manifest['course']['title'], slug=manifest['course']['slug'], is_active=False)
            db.session.add(course)
            db.session.flush()
            counters['course_created'] = True
        elif overwrite:
            course.title = manifest['course']['title']
        for group in manifest['groups']:
            db_group = TheoryGroup.query.filter_by(course_id=course.id, name=group['name']).first()
            if db_group is None:
                db_group = TheoryGroup(
                    course_id=course.id, name=group['name'], description=group.get('description'),
                    position=group['position'], created_by=author_id,
                )
                db.session.add(db_group)
                db.session.flush()
                counters['groups_created'] += 1
            elif overwrite:
                db_group.description = group.get('description')
                db_group.position = group['position']
            for article in group['articles']:
                block = TheoryBlock.query.filter_by(course_id=course.id, task_number=article['task_number']).first()
                expected_content, _assets = _prepared_article_content(root, group, article, course.slug)
                if block and _strip_status(block.content or '') == _strip_status(expected_content) and block.title == article['title'] and (block.description or '') == (article.get('description') or '') and block.position == article['position'] and block.group_id == db_group.id:
                    counters['articles_unchanged'] += 1
                    continue
                content, _assets = _prepared_article_content(root, group, article, course.slug, static_path)
                if block is None:
                    block = TheoryBlock(course_id=course.id, task_number=article['task_number'], author_id=author_id)
                    db.session.add(block)
                    counters['articles_created'] += 1
                else:
                    counters['articles_updated'] += 1
                block.group_id = db_group.id
                block.position = article['position']
                block.title = article['title']
                block.description = article.get('description')
                block.read_minutes = article.get('read_minutes', 5)
                block.content = content
                block.author_id = author_id
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {'course_id': course.id, **counters}


def publish_selected(manifest: dict[str, Any], report: ValidationReport, *, selected_keys: set[str], db, Course, TheoryBlock) -> dict[str, Any]:
    """Publish only explicitly selected package keys whose stored draft matches its source hash."""
    if not report.valid:
        raise ValueError('Пакет содержит ошибки; публикация запрещена.')
    if not selected_keys:
        raise ValueError('Для публикации укажите хотя бы один --article key.')
    known = {article['key'] for group in manifest['groups'] for article in group['articles']}
    unknown = selected_keys - known
    if unknown:
        raise ValueError('Неизвестные article key: ' + ', '.join(sorted(unknown)))
    course = Course.query.filter_by(slug=manifest['course']['slug']).first()
    if not course:
        raise ValueError('Курс не найден; сначала выполните import-draft.')
    root = Path(report.package_dir)
    targets = []
    for group in manifest['groups']:
        for article in group['articles']:
            if article['key'] not in selected_keys: continue
            block = TheoryBlock.query.filter_by(course_id=course.id, task_number=article['task_number']).first()
            if not block:
                raise ValueError(f'Статья {article["key"]} не импортирована.')
            source, _assets = _prepared_article_content(root, group, article, course.slug)
            if _strip_status(block.content or '') != _strip_status(source):
                raise ValueError(f'Статья {article["key"]} изменена после импорта или отличается от пакета.')
            targets.append(block)
    try:
        for block in targets:
            clean = _strip_status(block.content or '')
            block.content = '<!--status:published-->\n' + clean
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {'course_id': course.id, 'published': len(targets), 'task_numbers': [b.task_number for b in targets]}
