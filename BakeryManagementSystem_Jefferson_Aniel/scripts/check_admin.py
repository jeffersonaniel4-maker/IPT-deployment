import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User
from werkzeug.security import check_password_hash

with app.app_context():
    u = User.query.filter_by(username='admin').first()
    if not u:
        print('ADMIN_NOT_FOUND')
    else:
        print('FOUND', u.username, 'role=', u.role)
        ok = check_password_hash(u.password_hash, 'admin123')
        print('PASSWORD_MATCHES_admin123=', ok)
