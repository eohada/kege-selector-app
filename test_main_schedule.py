# test_main_schedule.py
from app import create_app
from app.models import User

app = create_app()

with app.app_context():
    creator = User.query.filter_by(role='creator').first() or User.query.first()
    user_id = str(creator.id) if creator else '1'

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = user_id

    res = client.get('/schedule')
    print(f"\n[TEST] GET /schedule Status Code: {res.status_code}")
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}!"
    print("[SUCCESS] SUCCESS: Main route http://127.0.0.1:5000/schedule returns 200 OK!\n")
