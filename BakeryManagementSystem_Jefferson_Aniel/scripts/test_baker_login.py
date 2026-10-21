import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

with app.test_client() as client:
    # Attempt baker login
    resp = client.post('/baker/login', data={'username':'jeffer', 'password':'baker123'}, follow_redirects=False)
    print('status_code:', resp.status_code)
    print('headers:', resp.headers)
    if resp.status_code in (301, 302):
        loc = resp.headers.get('Location')
        print('redirect_to:', loc)
        print('success:', '/baker' in loc)
    else:
        # If not redirect, print response data for debugging
        data = resp.get_data(as_text=True)
        print('response_body:', data[:1000])
