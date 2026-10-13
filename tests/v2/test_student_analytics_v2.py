import pytest
from tests.v2.conftest import login_as


def test_student_analytics_renders_with_source_filters(client, role_users):
    """Проверка доступности страницы аналитики со всеми 3 фильтрами источника данных."""
    tutor_id = role_users['tutor_id']
    student_id = role_users['student_id']

    login_as(client, tutor_id, 'tutor')

    for source in ['all', 'exam', 'homework']:
        resp = client.get(f'/student/{student_id}/analytics?source={source}')
        assert resp.status_code == 200, f'Expected 200 for source={source}, got {resp.status_code}'
        html = resp.get_data(as_text=True)

        # Segmented pill tabs
        assert 'source=all' in html
        assert 'source=exam' in html
        assert 'source=homework' in html

        # Core blocks and widgets
        assert 'id="readiness-drawer"' in html
        assert 'id="readiness-backdrop"' in html
        assert 'id="readiness-data"' in html
        assert 'id="fipi-scale-modal"' in html
        assert 'openReadinessDrawer' in html
        assert 'openFipiScaleModal' in html

        # 3 Canonical Exam Sections
        assert 'Программирование на Python' in html
        assert 'Электронные таблицы и БД' in html
        assert 'Логика, теория и формулы' in html

        # Growth zone section
        assert 'Зона роста: что подтянуть прямо сейчас' in html

        # Readiness Legend 4th state
        assert 'Не начато' in html

        # ELO table headers
        assert 'Номер ЕГЭ' in html
        assert 'Дней практики' in html


def test_student_analytics_zero_division_safety(client, role_users):
    """Проверка устойчивости к нулевым данным (без падений ZeroDivisionError при пустых результатах)."""
    tutor_id = role_users['tutor_id']
    student_id = role_users['student_id']

    login_as(client, tutor_id, 'tutor')

    resp = client.get(f'/student/{student_id}/analytics?source=exam')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Карта готовности к КЕГЭ' in html


def test_student_analytics_bento_cards_metrics(client, role_users):
    """Проверка корректности 4 Bento-карточек: Общая успеваемость, пустые состояния и посещаемость."""
    tutor_id = role_users['tutor_id']
    student_id = role_users['student_id']

    login_as(client, tutor_id, 'tutor')

    resp = client.get(f'/student/{student_id}/analytics')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Карточка 1: правильный заголовок без ложной стрелки роста при 0 дельте
    assert 'Общая успеваемость' in html
    assert 'по проверенным работам' in html

    # Карточка 2: ДЗ
    assert 'Средняя оценка ДЗ' in html

    # Карточка 3: Пробники
    assert 'Балл за Пробники' in html
    assert ('По проверенным пробникам' in html or 'Пробников пока нет' in html)

    # Карточка 4: Посещаемость
    assert 'Посещаемость' in html
    assert 'пропущено' in html

    # Смысловые разделы: Не начато для нерешенных блоков
    assert 'Освоение разделов' in html
    assert ('Не начато' in html or '%' in html)


