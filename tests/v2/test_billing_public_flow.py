from app.models import db, PromoCode


def test_public_billing_page_renders_cleanly(client):
    res = client.get('/billing/plans/public')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Requisites verification
    assert '2200240286200924' in html
    assert 'Король Александр Евгеньевич' in html
    assert '89039530615' in html
    assert 'ВТБ' in html

    # CTA verification
    assert 't.me/eohada' in html
    assert 'Я оплатил(а)' in html

    # Maintenance mode must NOT be present
    assert 'Технические работы' not in html

    # Interactive slider and cart elements
    assert 'lessons-range' in html
    assert 'cart-items-container' in html
    assert 'promocode-input' in html


def test_public_promocode_validation(app, client):
    with app.app_context():
        promo = PromoCode.query.filter_by(code='TESTPROMO10').first()
        if not promo:
            promo = PromoCode(code='TESTPROMO10', discount_percent=10, is_active=True)
            db.session.add(promo)
            db.session.commit()

    # Empty code
    res = client.post('/billing/promocode/validate-public', json={'code': '', 'cart_total': 10000})
    assert res.status_code == 400
    assert res.get_json()['success'] is False

    # Non-existent code
    res = client.post('/billing/promocode/validate-public', json={'code': 'UNKNOWN_CODE_999', 'cart_total': 10000})
    assert res.status_code == 404
    assert res.get_json()['success'] is False

    # Valid active code
    res = client.post('/billing/promocode/validate-public', json={'code': 'TESTPROMO10', 'cart_total': 50000})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['code'] == 'TESTPROMO10'
    assert data['discount_percent'] == 10
    assert data['discount_amount'] == 5000
    assert data['final_total'] == 45000
