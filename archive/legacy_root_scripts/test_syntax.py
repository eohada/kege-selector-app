import sys
import traceback
from app import create_app
from app.models import User

app = create_app()
app.testing = True

with app.app_context():
    client = app.test_client()
    user = User.query.filter_by(role='admin').first() or User.query.first()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        
    for route in ['/qa/', '/admin/qa/', '/dashboard']:
        try:
            resp = client.get(route)
            print(f"[{route}] HTTP {resp.status_code}")
        except Exception as e:
            print(f"[{route}] CRASH: {type(e).__name__}: {e}")
            traceback.print_exc()
