import sys
from app import create_app
from app.models import User

app = create_app()
app.testing = True

with app.app_context():
    client = app.test_client()
    user = User.query.filter_by(role='admin').first()
    if not user:
        user = User.query.first()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        
    print("Testing /qa/")
    resp = client.get('/qa/')
    if resp.status_code == 500:
        print("500 Error on /qa/")
    else:
        print(f"Status: {resp.status_code}")
