"""Isolated integration checks; never connects to the configured MySQL database."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.test-deps'))
sys.path.insert(0, str(ROOT))
import flask_sqlalchemy

# Override the URI before SQLAlchemy initializes the application.
original_init = flask_sqlalchemy.SQLAlchemy.init_app
def isolated_init(self, app):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    original_init(self, app)
flask_sqlalchemy.SQLAlchemy.init_app = isolated_init
import app as module
flask_sqlalchemy.SQLAlchemy.init_app = original_init

class IngredientInventoryTests(unittest.TestCase):
    def setUp(self):
        self.context = module.app.app_context()
        self.context.push()
        module.db.create_all()
        module.db.session.add_all([
            module.User(id=1, username='baker', password_hash='unused-test-hash', role='Baker'),
            module.User(id=2, username='cashier', password_hash='unused-test-hash', role='Cashier'),
            module.Ingredient(id=1, name='Flour', unit='kg'),
            module.Ingredient(id=2, name='Sugar', unit='kg'),
            module.Product(barcode='TEST', name='Sample pastry', category='Bread', price=10)
        ])
        module.db.session.commit()
        self.client = module.app.test_client()
        self.login(1)

    def tearDown(self):
        module.db.session.remove()
        module.db.drop_all()
        self.context.pop()

    def login(self, user_id):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    def test_counts_filters_and_role_separation(self):
        pastry_page = self.client.get('/inventory')
        self.assertEqual(pastry_page.status_code, 200)
        self.assertIn(b'Sample pastry', pastry_page.data)
        page = self.client.get('/ingredients')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'Sample pastry', page.data)
        self.assertIn(b'Needs first count', page.data)
        for count, status in [('0', 'out'), ('2.5', 'low'), ('5', 'low'), ('6', 'in')]:
            self.client.post('/ingredients/1/stock', data={'quantity': count, 'low_stock_level': '5'})
            page = self.client.get('/ingredients?status=' + status)
            self.assertIn(b'Flour', page.data)
            self.assertNotIn(b'<strong>Sugar</strong>', page.data)
        for invalid in ['-1', 'nan', 'inf', 'bad']:
            self.client.post('/ingredients/1/stock', data={'quantity': invalid, 'low_stock_level': '5'})
            self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 6)
        self.login(2)
        self.assertIn(b'Sample pastry', self.client.get('/inventory').data)

    def test_suggest_receive_once_and_permissions(self):
        self.client.post('/ingredients/1/stock', data={'quantity': '2.5', 'low_stock_level': '5'})
        for quantity in ['0', '-1', 'nan']:
            self.client.post('/ingredients/1/suggest', data={'quantity': quantity})
        self.assertEqual(module.IngredientPurchaseSuggestion.query.count(), 0)
        for _ in range(2):
            self.client.post('/ingredients/1/suggest', data={'quantity': '10.5', 'note': 'Tomorrow'})
        self.assertEqual(module.IngredientPurchaseSuggestion.query.count(), 1)
        self.client.post('/ingredients/suggestions/1/receive')
        self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 2.5)
        self.login(2)
        self.assertIn(b'Tomorrow', self.client.get('/ingredients').data)
        self.client.post('/ingredients/2/suggest', data={'quantity': '1'})
        self.assertEqual(module.IngredientPurchaseSuggestion.query.count(), 1)
        for _ in range(2):
            self.client.post('/ingredients/suggestions/1/receive')
        self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 13)
        self.assertEqual(module.db.session.get(module.IngredientPurchaseSuggestion, 1).status, 'Received')

    def test_production_deducts_scaled_combined_usage(self):
        self.client.post('/ingredients/1/stock', data={'quantity': '10', 'low_stock_level': '5'})
        page = self.client.get('/baker/production')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Ingredient stock levels', page.data)
        self.assertIn(b'Sugar', page.data)
        product = module.Product.query.first()
        payload = {'product_id': product.id, 'quantity': 100, 'ingredients': [
            {'ingredient_id': 1, 'quantity': 6, 'unit': 'kg'},
            {'ingredient_id': 1, 'quantity': 4, 'unit': 'kg'}]}
        result = self.client.post('/baker/complete', json=payload)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 5)
        self.assertEqual(product.stock, 100)
        self.assertEqual(module.ProductionBatch.query.count(), 1)
        # Exact remaining stock can be consumed.
        self.assertEqual(self.client.post('/baker/complete', json=payload).status_code, 200)
        self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 0)
        self.assertEqual(self.client.post('/baker/complete', json=payload).status_code, 400)
        self.assertEqual(product.stock, 200)

    def test_production_failure_is_atomic(self):
        self.client.post('/ingredients/1/stock', data={'quantity': '3', 'low_stock_level': '5'})
        for items in [
            [{'ingredient_id': 1, 'quantity': 2}, {'ingredient_id': 1, 'quantity': 2}],
            [{'ingredient_id': 1, 'quantity': 1}, {'ingredient_id': 2, 'quantity': 1}],
            [{'ingredient_id': 1, 'quantity': -1}],
            [{'ingredient_id': 1, 'quantity': 'nan'}],
            [{'ingredient_id': 999, 'quantity': 1}],
            [{'ingredient_id': 1, 'quantity': 1, 'unit': 'g'}],
        ]:
            result = self.client.post('/baker/complete', json={
                'custom_name': 'Should not be created', 'quantity': 200, 'ingredients': items})
            self.assertEqual(result.status_code, 400, result.data)
            self.assertEqual(module.db.session.get(module.IngredientStock, 1).quantity, 3)
            self.assertEqual(module.ProductionBatch.query.count(), 0)
            self.assertEqual(module.Product.query.count(), 1)

    def test_create_ingredient_and_authentication(self):
        data = {'name': 'Butter', 'unit': 'pack', 'quantity': '3.5', 'low_stock_level': '4', 'unit_cost': '100'}
        self.client.post('/ingredients', data=data)
        self.client.post('/ingredients', data=data)
        ingredient = module.Ingredient.query.filter_by(name='Butter').one()
        self.assertEqual(ingredient.inventory_stock.quantity, 3.5)
        self.client.get('/logout')
        self.assertEqual(self.client.get('/ingredients').status_code, 302)
        self.assertEqual(self.client.post('/ingredients/1/stock', data=data).status_code, 302)

if __name__ == '__main__':
    unittest.main()


