import datetime
import os
import uuid
import secrets
import math
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- CONFIGURATION: Aiven MySQL + Vercel ---
# Add these values in Vercel -> Project -> Settings -> Environment Variables.
# For local development, optional .env loading is supported with python-dotenv.
from pathlib import Path
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
except ImportError:
    pass  # Vercel supplies environment variables directly.
else:
    load_dotenv(BASE_DIR / '.env')

REQUIRED_SETTINGS = (
    'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'SECRET_KEY'
)
missing = [name for name in REQUIRED_SETTINGS if not os.environ.get(name)]
if missing:
    raise RuntimeError(
        'Missing environment variables: ' + ', '.join(missing)
        + '. Set them in Vercel or in a private local .env file.'
    )

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ['3ebb19056223f93a61fb5b6c0e2be2b60aeefcdb4a21cbcede3f8be171944f24']
app.config['SQLALCHEMY_DATABASE_URI'] = URL.create(
    'mysql+pymysql',
    username=os.environ['avnadmin'],
    password=os.environ['AVNS__0SSWhvHtquUpKpq1vV'],
    host=os.environ['mysql-27534755-jeffersonaniel4-f4dd.g.aivencloud.com'],
    port=int(os.environ['15969']),
    database=os.environ['bakerymanagementsystem'],
)

CA_CERTIFICATE = BASE_DIR / 'ca.pem'
if not CA_CERTIFICATE.is_file():
    raise RuntimeError(
        'Missing ca.pem beside app.py. Download the CA certificate '
        'from your Aiven MySQL service.'
    )

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 240,
    'connect_args': {
        'ssl_ca': str(CA_CERTIFICATE),
        'ssl_verify_cert': True,
        'ssl_verify_identity': True,
        'connect_timeout': 10,
    },
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Uploaded files cannot persist in Vercel Functions' local filesystem.
# Existing files bundled in static/uploads still work for display.
UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
if not os.environ.get('VERCEL'):
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- DATABASE MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Cashier') # Admin, Cashier, Baker

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(255), default='/static/uploads/default_pastry.jpg')
    is_available = db.Column(db.Boolean, default=True)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='open')  # open, archived, voided
    customer = db.relationship('Customer', backref='sales')
    user = db.relationship('User', backref='sales')
    items = db.relationship('SaleItem', backref='sale', lazy=True)

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')

class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    unit = db.Column(db.String(20), default='pcs')
    unit_cost = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class ProductionBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    ingredient_cost = db.Column(db.Float, nullable=False, default=0.0)
    sales_value = db.Column(db.Float, nullable=False, default=0.0)
    profit = db.Column(db.Float, nullable=False, default=0.0)
    baked_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    product = db.relationship('Product', backref='production_batches')


class IngredientStock(db.Model):
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), primary_key=True)
    quantity = db.Column(db.Float, nullable=False, default=0)
    low_stock_level = db.Column(db.Float, nullable=False, default=5)
    ingredient = db.relationship('Ingredient', backref=db.backref('inventory_stock', uselist=False))


class IngredientPurchaseSuggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(500), nullable=False, default='')
    status = db.Column(db.String(20), nullable=False, default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    ingredient = db.relationship('Ingredient')
    user = db.relationship('User')


class InviteToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Baker')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    used = db.Column(db.Boolean, default=False)
    used_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

BAKER_RECIPE_LIBRARY = {
    'pandesal': [
        {'ingredient': 'Flour', 'unit_cost': 60.00, 'qty': 6.80, 'unit': 'kg'},
        {'ingredient': 'Yeast', 'unit_cost': 18.00, 'qty': 0.10, 'unit': 'pack'},
        {'ingredient': 'Sugar', 'unit_cost': 85.00, 'qty': 0.90, 'unit': 'kg'},
        {'ingredient': 'Butter', 'unit_cost': 115.00, 'qty': 0.30, 'unit': 'pack'},
        {'ingredient': 'Egg', 'unit_cost': 10.00, 'qty': 12.00, 'unit': 'pcs'},
        {'ingredient': 'Milk', 'unit_cost': 110.00, 'qty': 2.00, 'unit': 'L'}
    ],
    'ensaymada': [
        {'ingredient': 'Flour', 'unit_cost': 60.00, 'qty': 7.00, 'unit': 'kg'},
        {'ingredient': 'Butter', 'unit_cost': 115.00, 'qty': 1.20, 'unit': 'pack'},
        {'ingredient': 'Sugar', 'unit_cost': 85.00, 'qty': 1.10, 'unit': 'kg'},
        {'ingredient': 'Egg', 'unit_cost': 10.00, 'qty': 15.00, 'unit': 'pcs'},
        {'ingredient': 'Yeast', 'unit_cost': 18.00, 'qty': 0.12, 'unit': 'pack'},
        {'ingredient': 'Cheese', 'unit_cost': 95.00, 'qty': 0.80, 'unit': 'pack'}
    ],
    'hopia': [
        {'ingredient': 'Flour', 'unit_cost': 60.00, 'qty': 6.50, 'unit': 'kg'},
        {'ingredient': 'Mango Filling', 'unit_cost': 120.00, 'qty': 1.50, 'unit': 'pack'},
        {'ingredient': 'Sugar', 'unit_cost': 85.00, 'qty': 1.00, 'unit': 'kg'},
        {'ingredient': 'Butter', 'unit_cost': 115.00, 'qty': 0.50, 'unit': 'pack'},
        {'ingredient': 'Egg', 'unit_cost': 10.00, 'qty': 10.00, 'unit': 'pcs'},
        {'ingredient': 'Yeast', 'unit_cost': 18.00, 'qty': 0.10, 'unit': 'pack'}
    ],
    'spanishbread': [
        {'ingredient': 'Flour', 'unit_cost': 60.00, 'qty': 6.90, 'unit': 'kg'},
        {'ingredient': 'Butter', 'unit_cost': 115.00, 'qty': 1.00, 'unit': 'pack'},
        {'ingredient': 'Sugar', 'unit_cost': 85.00, 'qty': 1.20, 'unit': 'kg'},
        {'ingredient': 'Yeast', 'unit_cost': 18.00, 'qty': 0.12, 'unit': 'pack'},
        {'ingredient': 'Egg', 'unit_cost': 10.00, 'qty': 14.00, 'unit': 'pcs'},
        {'ingredient': 'Milk', 'unit_cost': 110.00, 'qty': 2.20, 'unit': 'L'}
    ],
    'default': [
        {'ingredient': 'Flour', 'unit_cost': 60.00, 'qty': 6.00, 'unit': 'kg'},
        {'ingredient': 'Sugar', 'unit_cost': 85.00, 'qty': 1.00, 'unit': 'kg'},
        {'ingredient': 'Butter', 'unit_cost': 115.00, 'qty': 0.50, 'unit': 'pack'},
        {'ingredient': 'Egg', 'unit_cost': 10.00, 'qty': 12.00, 'unit': 'pcs'},
        {'ingredient': 'Yeast', 'unit_cost': 18.00, 'qty': 0.10, 'unit': 'pack'},
        {'ingredient': 'Milk', 'unit_cost': 110.00, 'qty': 2.00, 'unit': 'L'}
    ]
}


def get_baker_recipe_for_product(product_name):
    normalized_name = (product_name or '').lower().replace(' ', '').replace('-', '')
    for key in BAKER_RECIPE_LIBRARY:
        if key == 'default':
            continue
        if key in normalized_name or normalized_name in key:
            return BAKER_RECIPE_LIBRARY[key]
    return BAKER_RECIPE_LIBRARY['default']


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def get_sale_profit(sale):
    total_cost = 0.0
    for item in sale.items:
        if item.product:
            total_cost += (item.quantity or 0) * (item.product.cost_price or 0.0)
    return (sale.total_amount or 0.0) - total_cost


ROLE_HOME = {
    'Admin': 'admin_dashboard',
    'Cashier': 'pos',
    'Baker': 'baker_home',
}


def role_required(*roles):
    """Enforce job separation on the server, not only in the navigation."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                flash('That workspace is not available for your account.', 'error')
                return redirect(url_for(ROLE_HOME.get(current_user.role, 'login')))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for(ROLE_HOME.get(current_user.role, 'login')))


@app.route('/admin')
@role_required('Admin')
def admin_dashboard():
    """Owner view: sales performance plus the ingredient actions requiring approval."""
    now = datetime.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_sales = Sale.query.filter(
        Sale.date >= month_start, Sale.status.in_(['open', 'archived'])
    ).order_by(Sale.date.desc()).all()
    revenue = sum(sale.total_amount or 0 for sale in month_sales)
    sales_cost = sum(
        (item.quantity or 0) * (item.product.cost_price or 0)
        for sale in month_sales for item in sale.items
    )

    inventory_rows = []
    for ingredient in Ingredient.query.order_by(Ingredient.name).all():
        stock = ingredient.inventory_stock
        state = ('unrecorded' if stock is None else 'out' if stock.quantity <= 0
                 else 'low' if stock.quantity <= stock.low_stock_level else 'in')
        if state != 'in':
            inventory_rows.append({'ingredient': ingredient, 'stock': stock, 'state': state})
    pending_suggestions = IngredientPurchaseSuggestion.query.filter_by(status='Pending').order_by(
        IngredientPurchaseSuggestion.created_at.desc()).all()
    recent_batches = ProductionBatch.query.order_by(ProductionBatch.baked_at.desc()).limit(5).all()
    return render_template(
        'admin_dashboard.html', month=now.strftime('%B %Y'), revenue=revenue,
        profit=revenue - sales_cost, order_count=len(month_sales), inventory_rows=inventory_rows,
        pending_suggestions=pending_suggestions, recent_batches=recent_batches
    )


@app.route('/baker')
@role_required('Baker')
def baker_home():
    batches = ProductionBatch.query.order_by(ProductionBatch.baked_at.desc()).limit(10).all()
    return render_template('baker_home.html', batches=batches)

@app.route('/baker/production')
@role_required('Baker')
def baker_production():
    products = Product.query.order_by(Product.name.asc()).all()
    product_data = [{'id': product.id, 'name': product.name, 'price': float(product.price)} for product in products]
    # provide known ingredients to the baker UI so they must select identified ingredients
    ingredients = Ingredient.query.order_by(Ingredient.name.asc()).all()
    ingredients_data = [{'id': ing.id, 'name': ing.name, 'unit': ing.unit, 'unit_cost': float(ing.unit_cost or 0), 'stock': ing.inventory_stock.quantity if ing.inventory_stock else None, 'low_stock_level': ing.inventory_stock.low_stock_level if ing.inventory_stock else 5} for ing in ingredients]
    return render_template(
        'baker_production.html',
        products=products,
        product_data=product_data,
        recipe_library=BAKER_RECIPE_LIBRARY,
        ingredients=ingredients_data
    )


@app.route('/baker/complete', methods=['POST'])
@role_required('Baker')
def complete_baker_batch():
    payload = request.get_json(silent=True) or {}
    try:
        if not isinstance(payload, dict):
            raise ValueError('Invalid batch data.')
        batch_size = float(payload.get('quantity', 0))
        base_batch = float(payload.get('base_batch', 200))
        if not math.isfinite(batch_size) or not batch_size.is_integer() or not 0 < batch_size <= 1000000000:
            raise ValueError('Enter a positive whole batch quantity.')
        if not math.isfinite(base_batch) or base_batch <= 0:
            raise ValueError('Enter a valid base batch quantity.')
        batch_quantity = int(batch_size)
        items = payload.get('ingredients')
        if not isinstance(items, list) or not items:
            raise ValueError('Please add at least one ingredient.')
        usage = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('Invalid ingredient.')
            ingredient = (db.session.get(Ingredient, int(item['ingredient_id'])) if item.get('ingredient_id')
                          else Ingredient.query.filter_by(name=item.get('name')).first())
            if ingredient is None:
                raise ValueError('Add the ingredient and record its stock in Ingredient Inventory first.')
            if item.get('unit') and item['unit'] != ingredient.unit:
                raise ValueError(f'Use {ingredient.unit} for {ingredient.name}.')
            quantity = float(item.get('quantity', 0)) * batch_quantity / base_batch
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError('Ingredient quantities must be finite and greater than zero.')
            usage[ingredient.id] = usage.get(ingredient.id, 0) + quantity
        # Lock in a consistent order. All checks and deductions share the product transaction.
        ingredient_total_cost = 0.0
        stocks = []
        for ingredient_id in sorted(usage):
            ingredient = db.session.get(Ingredient, ingredient_id)
            stock = IngredientStock.query.filter_by(ingredient_id=ingredient_id).with_for_update().populate_existing().first()
            required = usage[ingredient_id]
            if stock is None:
                raise ValueError(f'Record an initial stock count for {ingredient.name} first.')
            if not math.isfinite(required) or required > stock.quantity:
                raise ValueError(f'Insufficient {ingredient.name}: need {required:g} {ingredient.unit}, available {stock.quantity:g} {ingredient.unit}.')
            ingredient_total_cost += required * float(ingredient.unit_cost or 0)
            stocks.append((stock, required))
        if payload.get('product_id'):
            product = Product.query.filter_by(id=int(payload['product_id'])).with_for_update().populate_existing().first()
            if product is None:
                raise ValueError('Selected product not found.')
        else:
            name = str(payload.get('custom_name') or '').strip()
            price = float(payload.get('custom_price') or 0)
            if not name or len(name) > 100 or not math.isfinite(price) or price < 0:
                raise ValueError('Enter a valid pastry name and price.')
            product = Product(barcode=f'CUST-{secrets.token_hex(4)}', name=name, category='Custom',
                              price=price, stock=0, cost_price=0, is_available=True)
            db.session.add(product)
            db.session.flush()
        for stock, required in stocks:
            stock.quantity -= required
        product.stock = (product.stock or 0) + batch_quantity
        product.cost_price = ingredient_total_cost / batch_quantity
        sales_value = float(product.price or 0) * batch_quantity
        profit = sales_value - ingredient_total_cost
        db.session.add(ProductionBatch(product_id=product.id, quantity=batch_quantity,
                                      ingredient_cost=ingredient_total_cost, sales_value=sales_value, profit=profit))
        db.session.commit()
    except (ValueError, TypeError, OverflowError) as error:
        db.session.rollback()
        return jsonify(success=False, message=str(error)), 400
    return jsonify(success=True, message=f'{batch_quantity} {product.name} added to pastry inventory. Ingredients deducted.',
                   stock=product.stock, ingredient_cost=ingredient_total_cost, sales_value=sales_value,
                   profit=profit, unit_cost=product.cost_price)

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        selected_role = request.form.get('role', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if selected_role not in ROLE_HOME:
                flash('Please choose your employee role.', 'error')
                return redirect(url_for('login'))
            if user.role != selected_role:
                flash(f'This account is registered as {user.role}, not {selected_role}.', 'error')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for(ROLE_HOME.get(user.role, 'login')))

        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/baker/login', methods=['GET', 'POST'])
def baker_login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.role == 'Baker' and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('baker_home'))
        flash('Invalid baker username or password', 'error')
    return render_template('baker_login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@role_required('Cashier')
def pos():
    products = Product.query.filter_by(is_available=True).all()
    customers = Customer.query.all()
    return render_template('pos.html', products=products, customers=customers)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        requested_role = request.form.get('role', '').strip()
       

        if requested_role not in ('Cashier', 'Baker'):
            flash('Please choose a valid employee role.', 'error')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('register'))
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists.', 'error')
            return redirect(url_for('register'))

        
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=requested_role or 'Cashier'
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/api/search_products')
@role_required('Cashier')
def search_products():
    query_text = request.args.get('q', '').strip()
    if not query_text:
        return jsonify([])

    results = Product.query.filter(
        (Product.name.like(f'%{query_text}%')) |
        (Product.barcode.like(f'%{query_text}%')) |
        (Product.category.like(f'%{query_text}%'))
    ).limit(10).all()

    output = []
    for product in results:
        output.append({
            'id': product.id,
            'barcode': product.barcode,
            'name': product.name,
            'category': product.category,
            'price': product.price,
            'stock': product.stock,
            'image_url': product.image_url or '/static/uploads/default_pastry.jpg'
        })

    return jsonify(output)

@app.route('/api/checkout', methods=['POST'])
@role_required('Cashier')
def checkout():
    data = request.json or {}
    cart = data.get('cart', [])
    customer_id = data.get('customer_id') or None
    
    if not cart:
        return jsonify({'success': False, 'message': 'Cart is empty!'}), 400

    total = 0
    sale_items = []
    
    for item in cart:
        product = Product.query.get(item['id'])
        if not product or product.stock < item['qty']:
            return jsonify({'success': False, 'message': f'Insufficient stock for {product.name if product else "item"}'}), 400
        
        product.stock -= item['qty']
        subtotal = product.price * item['qty']
        total += subtotal
        sale_items.append(SaleItem(product_id=product.id, quantity=item['qty'], price=product.price))

    new_sale = Sale(customer_id=customer_id, user_id=current_user.id, total_amount=total, items=sale_items)
    db.session.add(new_sale)
    db.session.commit()

    return jsonify({'success': True, 'sale_id': new_sale.id})

# --- INVENTORY MODULE ROUTE (NEW) ---
@app.route('/inventory', methods=['GET'])
@role_required('Cashier', 'Baker')
def inventory():
    search = request.args.get('search', '')
    filter_status = request.args.get('status', 'all')
    
    query = Product.query
    
    if search:
        query = query.filter(Product.name.contains(search) | Product.barcode.contains(search) | Product.category.contains(search))
    
    if filter_status == 'low':
        query = query.filter(Product.stock <= 15, Product.stock > 0)
    elif filter_status == 'out':
        query = query.filter(Product.stock <= 0)

    products = query.order_by(Product.stock.asc()).all()
    
    # Inventory Summary Analytics
    total_items = Product.query.count()
    low_stock_count = Product.query.filter(Product.stock <= 15, Product.stock > 0).count()
    out_of_stock_count = Product.query.filter(Product.stock <= 0).count()
    
    return render_template('inventory.html', 
                           products=products, 
                           search=search, 
                           status=filter_status,
                           total_items=total_items, 
                           low_stock_count=low_stock_count, 
                           out_of_stock_count=out_of_stock_count)

@app.route('/inventory/update/<int:id>', methods=['POST'])
@role_required('Cashier')
def update_stock(id):
    product = Product.query.get_or_404(id)
    action = request.form.get('action')
    qty = int(request.form.get('quantity', 0))
    
    if action == 'add':
        product.stock += qty
    elif action == 'set':
        product.stock = qty
    elif action == 'deduct':
        product.stock = max(0, product.stock - qty)
        
    db.session.commit()
    flash(f'Stock updated successfully for {product.name}!', 'success')
    return redirect(url_for('inventory'))

# --- PRODUCTS MANAGEMENT ---
def inventory_number(field):
    value = float(request.form.get(field, ''))
    if not math.isfinite(value) or value < 0 or value > 1000000000:
        raise ValueError('Enter a valid non-negative quantity.')
    return value


@app.route('/ingredients', methods=['GET', 'POST'])
@role_required('Baker', 'Cashier', 'Admin')
def ingredient_inventory():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            unit = request.form.get('unit', '').strip()
            quantity = inventory_number('quantity')
            threshold = inventory_number('low_stock_level')
            if not name or len(name) > 100 or not unit or len(unit) > 20:
                raise ValueError('Enter an ingredient name and unit (up to 100 and 20 characters).')
            if Ingredient.query.filter(db.func.lower(Ingredient.name) == name.lower()).first():
                raise ValueError('This ingredient already exists. Update its stock below.')
            ingredient = Ingredient(name=name, unit=unit, unit_cost=inventory_number('unit_cost'))
            db.session.add(IngredientStock(ingredient=ingredient, quantity=quantity, low_stock_level=threshold))
            db.session.commit()
            flash('Ingredient added.', 'success')
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error), 'error')
        return redirect(url_for('ingredient_inventory'))

    search = request.args.get('search', '').strip()
    status = request.args.get('status', 'all')
    rows = []
    counts = {'all': 0, 'low': 0, 'out': 0, 'in': 0, 'unrecorded': 0}
    for ingredient in Ingredient.query.order_by(Ingredient.name).all():
        stock = ingredient.inventory_stock
        state = ('unrecorded' if stock is None else 'out' if stock.quantity <= 0
                 else 'low' if stock.quantity <= stock.low_stock_level else 'in')
        counts['all'] += 1
        counts[state] += 1
        if search.lower() in ingredient.name.lower() and status in ('all', state):
            rows.append({'ingredient': ingredient, 'stock': stock, 'state': state})
    suggestions = IngredientPurchaseSuggestion.query.order_by(IngredientPurchaseSuggestion.created_at.desc()).all()
    return render_template('ingredient_inventory.html', rows=rows, counts=counts,
                           search=search, status=status, suggestions=suggestions,
                           pending_ids={s.ingredient_id for s in suggestions if s.status == 'Pending'})


@app.route('/ingredients/<int:id>/stock', methods=['POST'])
@role_required('Baker', 'Cashier', 'Admin')
def ingredient_stock(id):
    ingredient = Ingredient.query.get_or_404(id)
    try:
        quantity = inventory_number('quantity')
        threshold = inventory_number('low_stock_level')
        stock = IngredientStock.query.filter_by(ingredient_id=id).with_for_update().populate_existing().first()
        stock = stock or IngredientStock(ingredient=ingredient)
        stock.quantity = quantity
        stock.low_stock_level = threshold
        db.session.add(stock)
        db.session.commit()
        flash(f'Stock count saved for {ingredient.name}.', 'success')
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Enter valid non-negative stock and low-stock quantities.', 'error')
    return redirect(url_for('ingredient_inventory'))


@app.route('/ingredients/<int:id>/suggest', methods=['POST'])
@role_required('Baker')
def suggest_ingredient_purchase(id):
    ingredient = Ingredient.query.get_or_404(id)
    # Serialize suggestions for the same ingredient to avoid duplicate pending requests.
    Ingredient.query.filter_by(id=id).with_for_update().first()
    try:
        quantity = inventory_number('quantity')
        note = request.form.get('note', '').strip()
        if quantity <= 0 or len(note) > 500:
            raise ValueError('Enter a purchase quantity greater than zero and a note up to 500 characters.')
        if IngredientPurchaseSuggestion.query.filter_by(ingredient_id=id, status='Pending').first():
            raise ValueError('This ingredient already has a pending purchase suggestion.')
        db.session.add(IngredientPurchaseSuggestion(ingredient_id=id, user_id=current_user.id,
                                                   quantity=quantity, note=note))
        db.session.commit()
        flash(f'Purchase suggestion saved for {ingredient.name}.', 'success')
    except (ValueError, TypeError) as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for('ingredient_inventory'))


@app.route('/ingredients/suggestions/<int:id>/receive', methods=['POST'])
@role_required('Cashier', 'Admin')
def receive_ingredient_purchase(id):
    suggestion = IngredientPurchaseSuggestion.query.filter_by(id=id).with_for_update().first_or_404()
    if suggestion.status != 'Pending':
        flash('This suggestion has already been received.', 'error')
        return redirect(url_for('ingredient_inventory'))
    Ingredient.query.filter_by(id=suggestion.ingredient_id).with_for_update().first()
    stock = IngredientStock.query.filter_by(ingredient_id=suggestion.ingredient_id).with_for_update().populate_existing().first()
    if stock is None:
        flash('Record the current ingredient stock count before receiving this purchase.', 'error')
        return redirect(url_for('ingredient_inventory'))
    stock.quantity += suggestion.quantity
    suggestion.status = 'Received'
    db.session.commit()
    flash('Purchase received and ingredient stock increased.', 'success')
    return redirect(url_for('ingredient_inventory'))


@app.route('/products', methods=['GET', 'POST'])
@role_required('Cashier')
def products():
    search = request.args.get('search', '')
    if request.method == 'POST':
        image_url = '/static/uploads/default_pastry.jpg'
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                if os.environ.get('VERCEL'):
                    flash('Online product image uploads need external storage. Add the product without an image for now.', 'error')
                    return redirect(url_for('products'))
                filename = secure_filename(file.filename)
                unique_filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                image_url = f"/static/uploads/{unique_filename}"

        product = Product(
            barcode=request.form['barcode'],
            name=request.form['name'],
            category=request.form['category'],
            price=float(request.form['price']),
            stock=int(request.form['stock']),
            cost_price=float(request.form.get('cost_price', 0)),
            image_url=image_url,
            is_available=True
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully!', 'success')
        return redirect(url_for('products'))

    query = Product.query
    if search:
        query = query.filter(Product.name.contains(search) | Product.barcode.contains(search) | Product.category.contains(search))
    return render_template('products.html', products=query.all(), search=search)

@app.route('/products/edit/<int:id>', methods=['POST'])
@role_required('Cashier')
def edit_product(id):
    product = Product.query.get_or_404(id)
    product.barcode = request.form['barcode']
    product.name = request.form['name']
    product.category = request.form['category']
    product.price = float(request.form['price'])
    product.stock = int(request.form['stock'])
    product.cost_price = float(request.form.get('cost_price', product.cost_price))
    
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            if os.environ.get('VERCEL'):
                flash('Online product image uploads need external storage. Other edits were not saved.', 'error')
                return redirect(url_for('products'))
            filename = secure_filename(file.filename)
            unique_filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            product.image_url = f"/static/uploads/{unique_filename}"

    db.session.commit()
    flash('Pastry updated successfully!', 'success')
    return redirect(url_for('products'))

@app.route('/products/delete/<int:id>', methods=['POST'])
@role_required('Cashier')
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Pastry deleted successfully!', 'success')
    return redirect(url_for('products'))

# --- SALES MANAGEMENT ---
@app.route('/sales')
@role_required('Cashier')
def sales():
    search = request.args.get('search', '')
    status_filter = request.args.get('status', 'open')
    query = Sale.query
    
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    if search:
        query = query.join(Customer, isouter=True).filter(
            (Sale.id == search) | (Customer.name.contains(search))
        )

    sales_list = query.order_by(Sale.date.desc()).all()
    sales_with_profit = []
    total_profit = 0.0

    for sale in sales_list:
        profit = get_sale_profit(sale)
        total_profit += profit
        sales_with_profit.append({
            'sale': sale,
            'profit': profit,
            'cost': sum((item.quantity or 0) * (item.product.cost_price or 0.0) for item in sale.items)
        })

    return render_template('sales.html', sales=sales_with_profit, total_profit=total_profit, search=search, status_filter=status_filter)

@app.route('/sales/cancel/<int:sale_id>', methods=['POST'])
@role_required('Cashier')
def cancel_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    
    if sale.status == 'voided':
        flash('This sale has already been voided.', 'warning')
        return redirect(url_for('sales'))
    
    # Restore stock for all items in this sale
    for item in sale.items:
        if item.product:
            item.product.stock += item.quantity
    
    # Mark sale as voided
    sale.status = 'voided'
    db.session.commit()
    
    flash(f'Sale #{sale.id} has been cancelled. Stock has been restored.', 'success')
    return redirect(url_for('sales'))

# --- CUSTOMER MANAGEMENT ---
@app.route('/customers', methods=['GET', 'POST'])
@role_required('Cashier')
def customers():
    search = request.args.get('search', '')
    if request.method == 'POST':
        customer = Customer(
            name=request.form['name'],
            phone=request.form['phone'],
            email=request.form['email']
        )
        db.session.add(customer)
        db.session.commit()
        flash('Customer saved successfully!', 'success')
        return redirect(url_for('customers'))

    query = Customer.query
    if search:
        query = query.filter(Customer.name.contains(search) | Customer.phone.contains(search))
    return render_template('customers.html', customers=query.all(), search=search)

# --- REPORTS ---
@app.route('/reports/sales')
@role_required('Cashier', 'Admin')
def sales_report():
    month = request.args.get('month', datetime.datetime.now().month, type=int)
    year = request.args.get('year', datetime.datetime.now().year, type=int)
    
    # Filter by month, year, and exclude voided sales
    sales_list = Sale.query.filter(
        db.extract('month', Sale.date) == month,
        db.extract('year', Sale.date) == year,
        Sale.status.in_(['open', 'archived'])
    ).order_by(Sale.date.desc()).all()
    
    now = datetime.datetime.utcnow()
    sales_summary = []
    total_revenue = 0.0
    total_production_cost = 0.0
    total_orders = 0
    today_revenue = 0.0
    today_profit = 0.0
    monthly_revenue = 0.0
    monthly_profit = 0.0
    product_sales = {}

    for sale in sales_list:
        sale_cost = sum((item.quantity or 0) * (item.product.cost_price or 0.0) for item in sale.items)
        sale_profit = (sale.total_amount or 0.0) - sale_cost
        total_revenue += sale.total_amount or 0.0
        total_production_cost += sale_cost
        total_orders += 1

        if sale.date and sale.date.date() == now.date():
            today_revenue += sale.total_amount or 0.0
            today_profit += sale_profit

        if sale.date and sale.date.year == now.year and sale.date.month == now.month:
            monthly_revenue += sale.total_amount or 0.0
            monthly_profit += sale_profit

        for item in sale.items:
            product_name = item.product.name if item.product else 'Unknown'
            if product_name not in product_sales:
                product_sales[product_name] = {'quantity': 0, 'revenue': 0.0}
            product_sales[product_name]['quantity'] += item.quantity or 0
            product_sales[product_name]['revenue'] += (item.quantity or 0) * (item.price or 0.0)

        sales_summary.append({
            'sale': sale,
            'cost': sale_cost,
            'profit': sale_profit,
        })

    total_profit = total_revenue - total_production_cost
    top_products = sorted(
        product_sales.items(),
        key=lambda item: item[1]['quantity'],
        reverse=True
    )[:5]

    return render_template(
        'report.html',
        sales=sales_summary,
        total_revenue=total_revenue,
        total_production_cost=total_production_cost,
        total_profit=total_profit,
        total_orders=total_orders,
        today_revenue=today_revenue,
        today_profit=today_profit,
        monthly_revenue=monthly_revenue,
        monthly_profit=monthly_profit,
        top_products=top_products,
        month=month,
        year=year,
        date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

@app.route('/reports/archive/<int:year>/<int:month>', methods=['POST'])
@role_required('Cashier', 'Admin')
def archive_month(year, month):
    # Mark all open sales from this month as archived
    affected = Sale.query.filter(
        db.extract('month', Sale.date) == month,
        db.extract('year', Sale.date) == year,
        Sale.status == 'open'
    ).update({'status': 'archived'})
    db.session.commit()
    
    flash(f'Archived {affected} sales from {month}/{year}. They can still be viewed in reports.', 'success')
    return redirect(url_for('sales_report', month=month, year=year))

# --- USER MANAGEMENT ---
@app.route('/users', methods=['GET', 'POST'])
@role_required('Cashier')
def users():
    if request.method == 'POST':
        user = User(
            username=request.form['username'],
            password_hash=generate_password_hash(request.form['password']),
            role=request.form['role']
        )
        db.session.add(user)
        db.session.commit()
        flash('User created successfully!', 'success')
        return redirect(url_for('users'))

    return render_template('users.html', users=User.query.all())

def init_db():
    with app.app_context():
        db.create_all()
        owner_user = User.query.filter_by(username='admin').first()
        if not owner_user:
            # Bootstrap only when explicitly provided with a secure password.
            # Imported Aiven databases should already have their Admin account.
            initial_password = os.environ.get('INITIAL_ADMIN_PASSWORD')
            if initial_password:
                if len(initial_password) < 12:
                    raise RuntimeError('INITIAL_ADMIN_PASSWORD must be at least 12 characters.')
                owner_user = User(
                    username='admin',
                    password_hash=generate_password_hash(initial_password),
                    role='Admin'
                )
                db.session.add(owner_user)
                db.session.commit()
        elif owner_user.role != 'Admin':
            owner_user.role = 'Admin'
            db.session.commit()

        # Do not seed a shared, guessable invitation token into production.


# --- CASHIER: Employee Invite Management ---
@app.route('/invites', methods=['GET', 'POST'])
@role_required('Cashier')
def invites():
    if request.method == 'POST':
        # create new token
        token_value = request.form.get('token') or secrets.token_urlsafe(6)
        role = request.form.get('role', 'Baker')
        if role not in ROLE_HOME:
            flash('Invalid employee role.', 'error')
            return redirect(url_for('invites'))
        # normalize token to simple string
        token_value = token_value.strip()
        if not token_value:
            flash('Invalid token value.', 'error')
            return redirect(url_for('invites'))

        if InviteToken.query.filter_by(token=token_value).first():
            flash('Token already exists.', 'error')
            return redirect(url_for('invites'))

        new_token = InviteToken(token=token_value, role=role, created_by=current_user.id)
        db.session.add(new_token)
        db.session.commit()
        flash('Invite token created.', 'success')
        return redirect(url_for('invites'))

    tokens = InviteToken.query.order_by(InviteToken.created_at.desc()).all()
    # resolve creator/used_by names
    users_map = {u.id: u.username for u in User.query.with_entities(User.id, User.username).all()}
    return render_template('invites.html', tokens=tokens, users_map=users_map)


@app.route('/invites/revoke/<int:token_id>', methods=['POST'])
@role_required('Cashier')
def revoke_invite(token_id):
    token = InviteToken.query.get_or_404(token_id)
    try:
        db.session.delete(token)
        db.session.commit()
        flash('Invite token revoked/deleted.', 'success')
    except Exception:
        db.session.rollback()
        flash('Failed to delete token.', 'error')
    return redirect(url_for('invites'))

if __name__ == '__main__':
    init_db()
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')


