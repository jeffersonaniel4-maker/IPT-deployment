Ingredient inventory
====================

Start the application normally with `python app.py`. Its existing init_db()
creates the new ingredient_stock and ingredient_purchase_suggestion tables
without changing existing ingredient or product tables. Deployments that import
the app through WSGI should run `python -c "from app import init_db; init_db()"`
once before serving the updated application.

Baker: open Ingredient Inventory, record the initial count and low-stock
threshold for each ingredient, and use Suggest to buy to save a quantity and note.
Cashier: open Ingredient inventory & purchase suggestions from Inventory,
then receive the full requested quantity when it arrives. Receiving adds that
quantity once and closes the suggestion. Record an initial stock count first.

Production automatically deducts the scaled ingredient quantities on completion. Record physical
counts when needed. Existing ingredients
without a stock record display Needs first count rather than an assumed zero.

Run isolated integration tests with:
    python scripts/test_ingredient_inventory.py
The tests use in-memory SQLite and do not connect to the production database.
They require Flask, Flask-SQLAlchemy, Flask-Login and PyMySQL.

