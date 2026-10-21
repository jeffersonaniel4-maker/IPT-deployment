import sys
import os
# ensure project root is on sys.path so we can import app when running from scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User
from werkzeug.security import generate_password_hash

if len(sys.argv) < 2:
    print("Usage: python create_baker.py USERNAME [PASSWORD]")
    sys.exit(1)

username = sys.argv[1]
password = sys.argv[2] if len(sys.argv) > 2 else 'baker123'

with app.app_context():
    u = User.query.filter_by(username=username).first()
    if u:
        u.role = 'Baker'
        db.session.commit()
        print(f"Updated existing user '{username}' to role Baker.")
    else:
        new = User(username=username, password_hash=generate_password_hash(password), role='Baker')
        db.session.add(new)
        db.session.commit()
        print(f"Created new Baker user '{username}' with password '{password}'.")
