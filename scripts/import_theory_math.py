"""Validate, preview and safely import a Markdown mathematics theory package."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.theory.math_curriculum import (
    _prepared_article_content,
    _strip_status,
    build_import_plan,
    content_hash,
    import_drafts,
    package_tree_sha256,
    publish_selected,
    validate_math_package,
)


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Импорт математического курса BooStudy из Markdown-пакета')
    parser.add_argument('--package', required=True, help='Каталог с manifest.json, статьями и assets')
    parser.add_argument('--mode', required=True, choices=('validate', 'preview', 'import-draft', 'publish', 'status'))
    parser.add_argument('--article', action='append', default=[], help='Стабильный article key; можно указать несколько раз для publish')
    parser.add_argument('--overwrite', action='store_true', help='Явно разрешить обновление только конфликтующих черновиков')
    parser.add_argument('--author-username', default=None, help='Username автора, который будет записан в TheoryBlock.author_id')
    parser.add_argument('--report', default=None, help='Сохранить JSON-отчёт по указанному локальному пути')
    parser.add_argument(
        '--prevalidated-latex-sha256', default=None,
        help='Разрешить импорт без локального Node только при совпадении SHA-256 пакета с CI-проверкой.',
    )
    args = parser.parse_args(argv)

    manifest, validation = validate_math_package(args.package)
    if args.prevalidated_latex_sha256:
        if args.mode == 'validate':
            print(_dump({'mode': args.mode, 'error': 'Attestation применяется только к DB-режимам.'}))
            return 2
        if os.environ.get('BOOSTUDY_TRUST_PREVALIDATED_LATEX', '').strip() != '1':
            print(_dump({'mode': args.mode, 'error': 'Для attestation требуется доверенный CI-контекст.'}))
            return 2
        expected_digest = args.prevalidated_latex_sha256.strip().lower()
        if not re.fullmatch(r'[a-f0-9]{64}', expected_digest) or not hmac.compare_digest(
            validation.package_sha256, expected_digest,
        ):
            print(_dump({'mode': args.mode, 'error': 'SHA-256 пакета не совпадает с проверенным CI-пакетом.'}))
            return 2
        if not validation.latex_checked:
            known_runtime_warnings = {
                'Node.js не найден: синтаксис LaTeX проверен только на баланс разделителей.',
                'Локальный пакет KaTeX недоступен; проверка синтаксиса формул не выполнена.',
            }
            unexpected_issues = [
                issue for issue in validation.issues
                if issue.get('severity') != 'warning' or issue.get('message') not in known_runtime_warnings
            ]
            if unexpected_issues:
                print(_dump({
                    'mode': args.mode,
                    'validation': validation.as_dict(),
                    'error': 'Валидация пакета на сервере нашла дополнительные проблемы.',
                }))
                return 2
            validation.issues = []
            validation.latex_checked = True
    result = {'mode': args.mode, 'validation': validation.as_dict()}
    if not validation.valid:
        print(_dump(result))
        return 2
    if args.mode == 'validate':
        print(_dump(result))
        return 0
    if not validation.latex_checked:
        result['error'] = 'Публикация и импорт заблокированы: KaTeX не удалось запустить для проверки формул.'
        print(_dump(result))
        return 2

    from app import create_app, db
    from app.models import Course, StudentCourseEnrollment, TheoryBlock, TheoryGroup, User
    app = create_app()
    try:
        with app.app_context():
            course = Course.query.filter_by(slug=manifest['course']['slug']).first()
            if args.mode == 'preview':
                plan = build_import_plan(manifest, validation, course, overwrite=args.overwrite)
                result['plan'] = []
                for item in plan['entries']:
                    incoming, _assets = _prepared_article_content(
                        Path(validation.package_dir), item['group'], item['article'],
                        manifest['course']['slug'],
                    )
                    current = _strip_status(item['block'].content or '') if item['block'] else None
                    result['plan'].append({
                        'group_key': item['group']['key'], 'group_name': item['group']['name'],
                        'article_key': item['article']['key'], 'task_number': item['article']['task_number'],
                        'title': item['article']['title'], 'action': item['action'],
                        'block_id': item['block'].id if item['block'] else None,
                        'incoming_hash': content_hash(_strip_status(incoming)),
                        'current_hash': content_hash(current) if current is not None else None,
                    })
                result['conflicts'] = plan['conflicts']
                result['metadata_actions'] = plan['metadata_actions']
                result['metadata_conflicts'] = plan['metadata_conflicts']
            elif args.mode == 'import-draft':
                author = User.query.filter_by(username=args.author_username).first() if args.author_username else None
                if args.author_username and not author:
                    raise ValueError(f'Пользователь {args.author_username} не найден.')
                result['import'] = import_drafts(
                    manifest, validation, author_id=author.id if author else None,
                    overwrite=args.overwrite, db=db, Course=Course,
                    TheoryBlock=TheoryBlock, TheoryGroup=TheoryGroup,
                    static_root=app.static_folder,
                )
            elif args.mode == 'publish':
                result['publish'] = publish_selected(
                    manifest, validation, selected_keys=set(args.article),
                    db=db, Course=Course, TheoryBlock=TheoryBlock,
                )
            elif args.mode == 'status':
                if not course:
                    result['course'] = None
                    result['articles'] = []
                else:
                    blocks = TheoryBlock.query.filter_by(course_id=course.id).order_by(
                        TheoryBlock.position, TheoryBlock.task_number, TheoryBlock.id,
                    ).all()
                    result['course'] = {
                        'id': course.id, 'slug': course.slug, 'title': course.title,
                        'is_active': course.is_active,
                        'student_enrollments': StudentCourseEnrollment.query.filter_by(course_id=course.id).count(),
                    }
                    result['articles'] = [
                        {
                            'id': block.id, 'task_number': block.task_number,
                            'group_id': block.group_id, 'title': block.title,
                            'position': block.position,
                            'status': 'published' if (block.content or '').startswith('<!--status:published-->') else 'draft',
                            'content_hash': content_hash(block.content or ''),
                        }
                        for block in blocks
                    ]
                    asset_urls = {
                        url for block in blocks
                        if 1 <= block.task_number <= 12
                        for url in re.findall(
                            r'!\[[^\]]*\]\((/static/uploads/theory_math/[^)\s]+)\)',
                            block.content or '',
                        )
                    }
                    missing_assets = [
                        url for url in sorted(asset_urls)
                        if not (Path(app.static_folder) / url.removeprefix('/static/')).is_file()
                    ]
                    result['assets'] = {
                        'referenced': len(asset_urls),
                        'missing': missing_assets,
                    }
            else:
                raise ValueError('Неизвестный режим.')
    except Exception as exc:
        result['error'] = str(exc)
        print(_dump(result))
        return 1

    rendered = _dump(result)
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
