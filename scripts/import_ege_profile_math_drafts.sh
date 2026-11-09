#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/boostudy"
COMPOSE_FILE="docker-compose.bluegreen.yml"
PACKAGE_ROOT="/app/content/theory/ege-profile-math-2027"
FIRST6_PACKAGE="first-6"
ARTICLES_07_12_PACKAGE="articles-07-12"

FIRST6_SHA256="${1:-}"
ARTICLES_07_12_SHA256="${2:-}"
if [[ ! "${FIRST6_SHA256}" =~ ^[a-f0-9]{64}$ || ! "${ARTICLES_07_12_SHA256}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Two validated package SHA-256 values are required." >&2
  exit 2
fi

cd "$APP_DIR"
ACTIVE_COLOR="$(tr -d '[:space:]' < .deploy/active_color)"
if [[ "$ACTIVE_COLOR" != blue && "$ACTIVE_COLOR" != green ]]; then
  echo "Unknown active web color: $ACTIVE_COLOR" >&2
  exit 2
fi
SERVICE="web_${ACTIVE_COLOR}"

math_cli() {
  local package="$1" mode="$2" digest="$3"
  docker compose -f "$COMPOSE_FILE" exec -T \
    -e BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 \
    -e BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 \
    -e BOOSTUDY_TRUST_PREVALIDATED_LATEX=1 \
    "$SERVICE" python /app/scripts/import_theory_math.py \
    --package "$PACKAGE_ROOT/$package" \
    --mode "$mode" \
    --prevalidated-latex-sha256 "$digest"
}

extract_cli_json() {
  python3 -c '
import json
import sys

text = sys.stdin.read()
decoder = json.JSONDecoder()
result = None
for index, character in enumerate(text):
    if character != "{":
        continue
    try:
        candidate, _ = decoder.raw_decode(text[index:])
    except json.JSONDecodeError:
        continue
    if isinstance(candidate, dict) and candidate.get("mode") in {"status", "preview", "import-draft"}:
        result = candidate
if result is None:
    raise SystemExit("Theory importer did not return a JSON result.")
print(json.dumps(result, ensure_ascii=False))
'
}

check_preview() {
  local expected_start="$1"
  local expected_end="$2"
  local output
  output="$(cat)"
  python3 - "$expected_start" "$expected_end" "$output" <<'PY'
import json
import sys

data = json.loads(sys.argv[3])
validation = data.get('validation') or {}
if validation.get('valid') is not True or validation.get('latex_checked') is not True or validation.get('issues') != []:
    raise SystemExit('Server-side package validation did not pass cleanly.')
if data.get('conflicts') or data.get('metadata_conflicts'):
    raise SystemExit('Production preview found a content or metadata conflict.')
entries = data.get('plan') or []
start, end = map(int, sys.argv[1:3])
expected = list(range(start, end + 1))
actual = sorted(item.get('task_number') for item in entries)
if actual != expected:
    raise SystemExit(f'Preview scope mismatch: expected {expected}, got {actual}.')
if any(item.get('action') not in {'create', 'no-op'} for item in entries):
    raise SystemExit('Preview includes an update or another action; import stopped.')
print(json.dumps({
    'course_slug': validation.get('course_slug'),
    'articles': actual,
    'actions': {action: sum(item.get('action') == action for item in entries) for action in ('create', 'no-op')},
}, ensure_ascii=False))
PY
}

check_import() {
  local start="$1" end="$2"
  local output
  output="$(cat)"
  python3 - "$start" "$end" "$output" <<'PY'
import json
import sys

data = json.loads(sys.argv[3])
validation = data.get('validation') or {}
if validation.get('valid') is not True or validation.get('latex_checked') is not True or validation.get('issues') != []:
    raise SystemExit('Import package validation did not pass cleanly.')
result = data.get('import') or {}
expected = int(sys.argv[2]) - int(sys.argv[1]) + 1
if result.get('articles_updated') != 0:
    raise SystemExit('Unexpected article update; expected create/no-op only.')
if result.get('articles_created', 0) + result.get('articles_unchanged', 0) != expected:
    raise SystemExit('Import count does not match the package article count.')
print(json.dumps(result, ensure_ascii=False))
PY
}

STATUS_BEFORE="$(math_cli "$FIRST6_PACKAGE" status "$FIRST6_SHA256" | extract_cli_json)"

FIRST6_PREVIEW="$(math_cli "$FIRST6_PACKAGE" preview "$FIRST6_SHA256" | extract_cli_json)"
check_preview 1 6 <<< "$FIRST6_PREVIEW"
ARTICLES_07_12_PREVIEW="$(math_cli "$ARTICLES_07_12_PACKAGE" preview "$ARTICLES_07_12_SHA256" | extract_cli_json)"
check_preview 7 12 <<< "$ARTICLES_07_12_PREVIEW"

FIRST6_IMPORT="$(math_cli "$FIRST6_PACKAGE" import-draft "$FIRST6_SHA256" | extract_cli_json)"
check_import 1 6 <<< "$FIRST6_IMPORT"
ARTICLES_07_12_IMPORT="$(math_cli "$ARTICLES_07_12_PACKAGE" import-draft "$ARTICLES_07_12_SHA256" | extract_cli_json)"
check_import 7 12 <<< "$ARTICLES_07_12_IMPORT"

STATUS_AFTER="$(math_cli "$FIRST6_PACKAGE" status "$FIRST6_SHA256" | extract_cli_json)"
EXPECTED_ARTICLES="$(python3 - "$APP_DIR/content/theory/ege-profile-math-2027" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
articles = []
asset_count = 0
for package in ('first-6', 'articles-07-12'):
    manifest = json.loads((root / package / 'manifest.json').read_text(encoding='utf-8'))
    for group in manifest['groups']:
        asset_count += len(group.get('assets', []))
        for article in group['articles']:
            articles.append({
                'task_number': article['task_number'],
                'title': article['title'],
                'position': article['position'],
            })
print(json.dumps({'articles': articles, 'asset_count': asset_count}, ensure_ascii=False))
PY
)"

python3 - "$STATUS_BEFORE" "$STATUS_AFTER" "$EXPECTED_ARTICLES" <<'PY'
import json
import sys

before, after, expected = [json.loads(value) for value in sys.argv[1:4]]
before_course = before.get('course')
course = after.get('course')
if not course or course.get('slug') != 'ege-profile-math-2027':
    raise SystemExit('Expected mathematics course is missing after import.')
if course.get('title') != 'ЕГЭ-2027: профильная математика':
    raise SystemExit('Course title does not match the approved package.')
if before_course is None:
    if course.get('is_active') is not False or course.get('student_enrollments') != 0:
        raise SystemExit('A newly created course must stay inactive and unassigned.')
else:
    if course.get('is_active') != before_course.get('is_active'):
        raise SystemExit('Import changed the course activation state.')
    if course.get('student_enrollments') != before_course.get('student_enrollments'):
        raise SystemExit('Import changed course assignments.')

before_by_id = {item['id']: item for item in before.get('articles', [])}
after_by_id = {item['id']: item for item in after.get('articles', [])}
for block_id, item in before_by_id.items():
    if after_by_id.get(block_id) != item:
        raise SystemExit(f'Existing article {block_id} changed during draft import.')

by_task = {item['task_number']: item for item in after.get('articles', [])}
for article in expected['articles']:
    row = by_task.get(article['task_number'])
    if row is None or row.get('title') != article['title'] or row.get('position') != article['position']:
        raise SystemExit(f'Article metadata mismatch for task {article["task_number"]}.')
    if article['task_number'] not in {item['task_number'] for item in before.get('articles', [])} and row.get('status') != 'draft':
        raise SystemExit(f'New article {article["task_number"]} was not imported as a draft.')

assets = after.get('assets') or {}
if assets.get('missing'):
    raise SystemExit('Some referenced theory illustrations are missing from the deployed image.')
if assets.get('referenced', 0) < expected['asset_count']:
    raise SystemExit(f'Expected at least {expected["asset_count"]} referenced assets, found {assets.get("referenced", 0)}.')

print(json.dumps({
    'course_id': course['id'],
    'course_slug': course['slug'],
    'is_active': course['is_active'],
    'student_enrollments': course['student_enrollments'],
    'foundation_articles': len(expected['articles']),
    'referenced_assets': assets['referenced'],
    'missing_assets': assets['missing'],
}, ensure_ascii=False))
PY
