"""Add the two new short-answer prototypes from the official FIPI 2027 math demo."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE_URL = 'https://doc.fipi.ru/ege/demoversii-specifikacii-kodifikatory/2027/ma_11_2027.zip'

CARDS = {
    6: {
        'content': '''<p>Организаторы лотереи выпустили 10 000 билетов. Выигрыши распределены следующим образом.</p>
<table><thead><tr><th>Выигрыш, ₽</th><th>100</th><th>1 000</th><th>5 000</th><th>10 000</th><th>50 000</th></tr></thead>
<tbody><tr><th>Число выигрышных билетов</th><td>500</td><td>100</td><td>50</td><td>10</td><td>1</td></tr></tbody></table>
<p>Найдите математическое ожидание величины «выигрыш на один билет». Ответ дайте в рублях.</p>''',
        'answer': '55',
        'hint': 'У остальных билетов выигрыш равен нулю. Найдите сумму выигрышей и разделите на число всех билетов.',
        'solution': '(100·500 + 1 000·100 + 5 000·50 + 10 000·10 + 50 000·1) / 10 000 = 55 рублей.',
    },
    13: {
        'content': '''<p>В июле 2030 года планируется взять кредит 182 000 рублей в банке на три года. Условия его возврата таковы:</p>
<ul><li>каждый январь долг увеличивается на 20 % по сравнению с концом предыдущего года;</li>
<li>с февраля по июнь каждого года необходимо выплатить одним платежом часть долга.</li></ul>
<p>Сколько рублей составит общая сумма платежей после полного погашения кредита, если кредит будет полностью погашен тремя равными платежами?</p>''',
        'answer': '259200',
        'hint': 'Обозначьте каждый из трёх равных платежей через x. После третьего платежа остаток долга равен нулю.',
        'solution': 'Пусть каждый платёж равен x. Тогда 182 000·1,2³ − x·(1,2² + 1,2 + 1) = 0. Отсюда x = 86 400 рублей; общая сумма 3x = 259 200 рублей.',
    },
}


def main() -> None:
    from app import create_app
    from core.db_models import Course, TaskSolution, Tasks, db

    with create_app().app_context():
        course = Course.query.filter_by(slug='ege_math_profile').one()
        for number, card in CARDS.items():
            source_key = f'fipi-demo:ege-math-profile:2027:{number}'
            if Tasks.query.filter_by(source_key=source_key).first():
                print(f'{number}: already present')
                continue
            plain = ' '.join(BeautifulSoup(card['content'], 'html.parser').get_text(' ', strip=True).split()).casefold()
            task = Tasks(
                course_id=course.id, task_number=number,
                site_task_id=f'demo2027-{number}', source_url=SOURCE_URL,
                source_name='ФИПИ — демоверсия ЕГЭ 2027, профильная математика',
                source_year=2027, source_task_number=number, exam_year=2027,
                source_key=source_key,
                content_fingerprint=hashlib.sha256(plain.encode('utf-8')).hexdigest(),
                prototype_status='real', ingest_status='ready',
                content_html=card['content'], answer=card['answer'],
                attached_files='[]', bank_origin='imported',
                difficulty_level=2, max_score=1, is_active=True,
                answer_spec={'type': 'short_answer', 'source_answer_verified': True, 'answer_source_url': SOURCE_URL},
                hints=[{'title': 'Подсказка 1', 'text': card['hint']}],
            )
            db.session.add(task)
            db.session.flush()
            db.session.add(TaskSolution(
                task_id=task.task_id, solution_text=card['solution'],
                source='import', needs_manual_review=False,
            ))
            db.session.commit()
            print(f'{number}: inserted task {task.task_id}')


if __name__ == '__main__':
    main()
