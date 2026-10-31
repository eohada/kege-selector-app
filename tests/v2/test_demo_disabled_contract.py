"""
Тест-контракт: демоверсия полностью отключена в рантайме платформы
(сохранена исключительно как концепт).
"""
import pytest


def test_demo_routes_return_404(client):
    """Все маршруты демоверсии возвращают 404 (Not Found)."""
    # Точки входа
    assert client.get('/demo').status_code == 404
    assert client.get('/demo/').status_code == 404
    assert client.get('/demo/start').status_code == 404

    # API интерактивной демоверсии
    assert client.post('/demo/api/init', json={'student_name': 'Тест'}).status_code == 404
    assert client.get('/demo/api/state').status_code == 404
    assert client.post('/demo/api/verify-answer', json={'answer': '1'}).status_code == 404
    assert client.post('/demo/api/exit').status_code == 404


def test_login_page_has_no_demo_link(client):
    """Страница логина не содержит ссылок и кнопок перехода в демоверсию."""
    res = client.get('/login')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Попробовать демо без регистрации' not in html
    assert 'url_for(\'auth.demo_choose\')' not in html
    assert '/demo' not in html
