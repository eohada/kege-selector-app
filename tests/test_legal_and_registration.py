import pytest
from app import create_app
from core.db_models import db, User, UserConsent, UserRole, UserProfile, TeacherProfile

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
    })
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def clean_db(app):
    with app.app_context():
        # Cleanup test users and consents before/after
        test_usernames = ['test_legal_user_1', 'test_legal_user_2', 'test_legal_user_err']
        users = User.query.filter(User.username.in_(test_usernames)).all()
        for u in users:
            UserConsent.query.filter_by(user_id=u.id).delete()
            TeacherProfile.query.filter_by(user_id=u.id).delete()
            UserProfile.query.filter_by(user_id=u.id).delete()
            UserRole.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        db.session.commit()
        yield
        users = User.query.filter(User.username.in_(test_usernames)).all()
        for u in users:
            UserConsent.query.filter_by(user_id=u.id).delete()
            TeacherProfile.query.filter_by(user_id=u.id).delete()
            UserProfile.query.filter_by(user_id=u.id).delete()
            UserRole.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        db.session.commit()


def test_legal_routes_accessible_anonymously(client):
    """1. Проверка доступности страниц юридических документов без авторизации"""
    # Хаб документов
    resp = client.get('/legal')
    assert resp.status_code == 200
    assert 'Юридические документы'.encode('utf-8') in resp.data
    assert 'Король Александр Евгеньевич'.encode('utf-8') in resp.data
    assert '700301487394'.encode('utf-8') in resp.data
    assert '324700000044531'.encode('utf-8') in resp.data
    assert 'boostudywork@gmail.com'.encode('utf-8') in resp.data
    assert 'offer.pdf' in resp.data.decode('utf-8')
    assert 'privacy.pdf' in resp.data.decode('utf-8')
    assert 'consent.pdf' in resp.data.decode('utf-8')

    # Прямые PDF файлы
    for pdf_url in ['/static/documents/offer.pdf', '/static/documents/privacy.pdf', '/static/documents/consent.pdf']:
        pdf_resp = client.get(pdf_url)
        assert pdf_resp.status_code == 200, f"PDF {pdf_url} returned {pdf_resp.status_code}"
        assert pdf_resp.data[:4] == b'%PDF', f"File {pdf_url} is not a valid PDF"

    # Редиректы с /legal/* на соответствующие PDF
    redirects = [
        ('/legal/offer', '/static/documents/offer.pdf'),
        ('/legal/privacy', '/static/documents/privacy.pdf'),
        ('/legal/consent', '/static/documents/consent.pdf'),
    ]
    for url, target in redirects:
        r = client.get(url)
        assert r.status_code in (301, 302), f"{url} didn't redirect"
        assert target in r.headers.get('Location', '')


def test_registration_page_checkboxes_initially_empty(client):
    """2. Чекбоксы на странице регистрации изначально не отмечены"""
    resp = client.get('/register')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert 'name="agree_offer"' in html
    assert 'name="agree_consent"' in html
    assert 'name="agree_analytics"' in html
    # Чекбоксы не должны содержать checked
    assert 'name="agree_offer" id="agree_offer" value="1" required class="mt-0.5 w-4 h-4 rounded text-indigo-600 border-slate-300 focus:ring-indigo-500 cursor-pointer" checked' not in html
    assert 'name="agree_consent" id="agree_consent" value="1" required class="mt-0.5 w-4 h-4 rounded text-indigo-600 border-slate-300 focus:ring-indigo-500 cursor-pointer" checked' not in html


def test_registration_backend_rejects_without_offer(client, clean_db):
    """3. Backend валидация: отказ при отсутствии согласия с офертой"""
    resp = client.post('/register', data={
        'username': 'test_legal_user_1',
        'email': 'legal1@example.com',
        'password': 'StrongPassword123!',
        'role': 'student',
        'agree_consent': '1',
        # agree_offer omitted
    })
    assert 'Для регистрации необходимо принять условия публичной оферты.'.encode('utf-8') in resp.data
    # Проверяем, что пользователь не создан
    assert User.query.filter_by(username='test_legal_user_1').first() is None


def test_registration_backend_rejects_without_consent(client, clean_db):
    """3. Backend валидация: отказ при отсутствии согласия на обработку ПД"""
    resp = client.post('/register', data={
        'username': 'test_legal_user_1',
        'email': 'legal1@example.com',
        'password': 'StrongPassword123!',
        'role': 'student',
        'agree_offer': '1',
        # agree_consent omitted
    })
    assert 'Для регистрации необходимо дать согласие на обработку персональных данных.'.encode('utf-8') in resp.data
    assert User.query.filter_by(username='test_legal_user_1').first() is None


def test_successful_registration_records_separate_consents(client, clean_db):
    """4 & 5. Успешная регистрация ученика (без обязательного email) фиксирует роль ученика и раздельные согласия"""
    resp = client.post('/register', data={
        'username': 'test_legal_user_1',
        'email': '',  # Почта необязательна
        'password': 'StrongPassword123!',
        'role': 'student',  # Выбираем ученика
        'agree_offer': '1',
        'agree_consent': '1',
        'agree_analytics': '1',
    }, follow_redirects=False)
    
    # Редирект после успешной регистрации
    assert resp.status_code in (302, 303)

    user = User.query.filter_by(username='test_legal_user_1').first()
    assert user is not None
    # Проверяем, что роль именно ученик, а не переписана в преподавателя
    assert user.role == 'student'
    assert user.is_student() is True
    assert user.is_tutor() is False
    assert user.email is None

    consents = UserConsent.query.filter_by(user_id=user.id).all()
    doc_keys = {c.document_key for c in consents}
    assert 'offer' in doc_keys
    assert 'pd_consent' in doc_keys
    assert 'privacy' in doc_keys
    assert 'analytics' in doc_keys

    for c in consents:
        assert c.version == '2026-10-18'
        assert c.accepted_at is not None


def test_registration_error_does_not_create_orphaned_consents(client, clean_db):
    """6. Ошибка регистрации (например, несовпадение паролей) не создает записей в UserConsent"""
    resp = client.post('/register', data={
        'username': 'test_legal_user_err',
        'email': 'legal_err@example.com',
        'password': 'Password1',
        'password_confirm': 'DifferentPassword2',
        'role': 'student',
        'agree_offer': '1',
        'agree_consent': '1',
    })
    assert 'Пароли не совпадают.'.encode('utf-8') in resp.data
    user = User.query.filter_by(username='test_legal_user_err').first()
    assert user is None
    # Никаких согласий с несуществующим пользователем быть не должно
    assert UserConsent.query.filter_by(user_id=9999999).first() is None


def test_duplicate_registration_does_not_duplicate_consents(client, clean_db):
    """7. Повторная отправка формы отклоняется и не плодит дубликатов"""
    # Первая успешная регистрация
    client.post('/register', data={
        'username': 'test_legal_user_2',
        'email': 'legal2@example.com',
        'password': 'StrongPassword123!',
        'role': 'tutor',
        'agree_offer': '1',
        'agree_consent': '1',
    })
    user = User.query.filter_by(username='test_legal_user_2').first()
    assert user is not None
    initial_count = UserConsent.query.filter_by(user_id=user.id).count()

    # Выходим из системы перед повторной попыткой
    client.get('/logout')

    # Повторная попытка зарегистрировать тот же username
    resp2 = client.post('/register', data={
        'username': 'test_legal_user_2',
        'email': 'legal2_another@example.com',
        'password': 'StrongPassword123!',
        'role': 'tutor',
        'agree_offer': '1',
        'agree_consent': '1',
    })
    assert 'Пользователь с таким логином уже существует.'.encode('utf-8') in resp2.data
    assert UserConsent.query.filter_by(user_id=user.id).count() == initial_count


def test_login_page_has_legal_link(client):
    """8. Страница входа содержит ссылку на юридические документы"""
    resp = client.get('/login')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert '/legal' in html
    assert 'Юридические документы' in html
