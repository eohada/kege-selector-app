import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules', 'venv', '.venv', 'legacy_backup'}
EXCLUDE_FILES = {'strip_all_comments.py'}

def strip_python(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    out = []
    for line in lines:
        s = line.rstrip('\n\r')
        if re.match(r'^\s*#', s):
            continue
        out.append(line)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.writelines(out)

def strip_html(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)

def strip_js_css(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    lines = []
    for line in content.splitlines():
        if '//' in line:
            in_str = False
            i = 0
            while i < len(line):
                if line[i] in '"\'':
                    q = line[i]
                    i += 1
                    while i < len(line) and (line[i] != q or line[i-1:i+1] == '\\' + q):
                        i += 1
                    if i < len(line):
                        i += 1
                    continue
                if i < len(line) - 1 and line[i:i+2] == '//':
                    line = line[:i].rstrip()
                    break
                i += 1
        lines.append(line)
    content = '\n'.join(lines)
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)

def main():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT)
            if rel.startswith('legacy_backup'):
                continue
            if fn.endswith('.py'):
                strip_python(path)
                print('PY', path)
            elif fn.endswith('.html'):
                strip_html(path)
                print('HTML', path)
            elif fn.endswith(('.js', '.css')) and 'node_modules' not in path:
                strip_js_css(path)
                print('JS/CSS', path)

if __name__ == '__main__':
    main()
