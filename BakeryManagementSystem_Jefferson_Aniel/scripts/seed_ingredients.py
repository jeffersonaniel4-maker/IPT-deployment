import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, Ingredient

INGREDIENTS = [
    {'name': 'Flour', 'unit': 'kg', 'unit_cost': 60.00},
    {'name': 'Yeast', 'unit': 'pack', 'unit_cost': 18.00},
    {'name': 'Sugar', 'unit': 'kg', 'unit_cost': 85.00},
    {'name': 'Butter', 'unit': 'pack', 'unit_cost': 115.00},
    {'name': 'Egg', 'unit': 'pcs', 'unit_cost': 10.00},
    {'name': 'Milk', 'unit': 'L', 'unit_cost': 110.00},
    {'name': 'Cheese', 'unit': 'pack', 'unit_cost': 95.00},
    {'name': 'Mango Filling', 'unit': 'pack', 'unit_cost': 120.00},
    {'name': 'Salt', 'unit': 'kg', 'unit_cost': 25.00},
    {'name': 'Baking Powder', 'unit': 'pack', 'unit_cost': 45.00},
]

with app.app_context():
    count = 0
    for ing_data in INGREDIENTS:
        # Check if ingredient already exists
        if not Ingredient.query.filter_by(name=ing_data['name']).first():
            ing = Ingredient(
                name=ing_data['name'],
                unit=ing_data['unit'],
                unit_cost=ing_data['unit_cost']
            )
            db.session.add(ing)
            count += 1
    
    db.session.commit()
    print(f"Added {count} ingredients. Total ingredients: {Ingredient.query.count()}")
