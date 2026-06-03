from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Store(db.Model):
    """A store/shop belonging to a User. Each store has its own addresses and orders."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    store_name = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="stores")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(200), default="")
    name = db.Column(db.String(100), nullable=False)
    shelf_no = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    is_out_of_stock = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=True)
    # Legacy column — kept for migration compatibility; new code uses store_id
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    customer_name = db.Column(db.String(50), nullable=False)
    customer_phone = db.Column(db.String(20), default="")
    customer_address = db.Column(db.Text, nullable=False)
    payment_image = db.Column(db.String(200), default="")
    total_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="ordered")
    shipping_image = db.Column(db.String(200), default="")
    tracking_no = db.Column(db.String(100), default="")
    is_viewed = db.Column(db.Boolean, default=False)
    # After-sale fields
    after_sale_status = db.Column(db.String(20), default="")
    after_sale_reason = db.Column(db.Text, default="")
    after_sale_note = db.Column(db.Text, default="")
    after_sale_tracking = db.Column(db.String(100), default="")
    after_sale_created_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    store = db.relationship("Store", backref="orders")
    user = db.relationship("User", backref="orders")
    items = db.relationship("OrderItem", backref="order", lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)

    product = db.relationship("Product", backref="order_items")


class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=True)
    # Legacy column — kept for migration compatibility; new code uses store_id
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)

    store = db.relationship("Store", backref="addresses")
    user = db.relationship("User", backref="addresses")
