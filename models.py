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


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(200), default="")
    name = db.Column(db.String(100), nullable=False)
    shelf_no = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    customer_name = db.Column(db.String(50), nullable=False)
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

    user = db.relationship("User", backref="orders")
    items = db.relationship("OrderItem", backref="order", lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False)

    product = db.relationship("Product", backref="order_items")
