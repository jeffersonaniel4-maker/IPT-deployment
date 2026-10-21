import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User
from werkzeug.security import generate_password_hash

USERNAME = 'admin'
NEW_PASS = 'admin123'

with app.app_context():
    u = User.query.filter_by(username=USERNAME).first()
    if not u:
        print('ADMIN_NOT_FOUND')
        sys.exit(1)
    u.password_hash = generate_password_hash(NEW_PASS)
    db.session.commit()
    print(f"Updated password for '{USERNAME}' to '{NEW_PASS}'")
