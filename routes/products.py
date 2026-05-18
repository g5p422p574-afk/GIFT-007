import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from sqlalchemy import func
from models import db, Product, User, OrderItem, Order
from config import ALLOWED_EXTENSIONS

products_bp = Blueprint("products", __name__)


def get_admin_user():
    if session.get("admin_id"):
        return User.query.get(session["admin_id"])
    return None


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("home.admin_login"))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], fname))
        return fname
    return ""


@products_bp.route("/")
@admin_required
def index():
    q = request.args.get("q", "").strip()
    products = Product.query
    if q:
        products = products.filter(Product.name.contains(q) | Product.shelf_no.contains(q))
    products = products.order_by(Product.created_at.desc()).all()
    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template("admin_products.html", products=products, unviewed_count=unviewed, session_user=get_admin_user(), q=q)


@products_bp.route("/product/add", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        shelf_no = request.form.get("shelf_no", "").strip()
        price = request.form.get("price", "").strip()
        if not name or not shelf_no or not price:
            return render_template("product_form.html", product=None, error="请填写完整信息", unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())
        image = save_upload(request.files.get("image"))
        product = Product(name=name, shelf_no=shelf_no, price=float(price), image=image)
        db.session.add(product)
        db.session.commit()
        return redirect(url_for("products.index"))
    return render_template("product_form.html", product=None, error=None, unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())


@products_bp.route("/product/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.name = request.form.get("name", "").strip()
        product.shelf_no = request.form.get("shelf_no", "").strip()
        product.price = float(request.form.get("price", "").strip())
        img = save_upload(request.files.get("image"))
        if img:
            product.image = img
        db.session.commit()
        return redirect(url_for("products.index"))
    return render_template("product_form.html", product=product, error=None, unviewed_count=Order.query.filter_by(is_viewed=False).count(), session_user=get_admin_user())


@products_bp.route("/product/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete(product_id):
    product = Product.query.get_or_404(product_id)
    # Delete associated order items first to avoid FK constraint error
    OrderItem.query.filter_by(product_id=product.id).delete()
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("products.index"))


@products_bp.route("/product/<int:product_id>/toggle-stock", methods=["POST"])
@admin_required
def toggle_stock(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_out_of_stock = not product.is_out_of_stock
    db.session.commit()
    return redirect(url_for("products.index"))


@products_bp.route("/finance")
@admin_required
def finance():
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    store_q = request.args.get("store", "").strip()

    base = Order.query.filter(Order.status.in_(["ordered", "shipped"]))

    # Store name filter
    if store_q:
        base = base.filter(Order.user.has(User.store_name.contains(store_q)))

    # Date range filter
    if date_from:
        base = base.filter(Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        base = base.filter(Order.created_at <= datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

    # Summary stats
    total_revenue = base.with_entities(func.sum(Order.total_amount)).scalar() or 0
    total_orders = base.count()

    # Today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_revenue = base.filter(Order.created_at >= today_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    today_orders = base.filter(Order.created_at >= today_start).count()

    # This month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_revenue = base.filter(Order.created_at >= month_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    month_orders = base.filter(Order.created_at >= month_start).count()

    # This year
    year_start = datetime.utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    year_revenue = base.filter(Order.created_at >= year_start).with_entities(func.sum(Order.total_amount)).scalar() or 0
    year_orders = base.filter(Order.created_at >= year_start).count()

    # Per-store breakdown
    store_stats = base.with_entities(
        User.store_name, func.sum(Order.total_amount), func.count(Order.id)
    ).join(User, Order.user_id == User.id, isouter=True).group_by(
        User.store_name
    ).order_by(func.sum(Order.total_amount).desc()).all()

    # Daily breakdown (last 30 days) for chart-like table
    daily_stats = base.filter(
        Order.created_at >= datetime.utcnow() - timedelta(days=30)
    ).with_entities(
        func.date(Order.created_at), func.sum(Order.total_amount), func.count(Order.id)
    ).group_by(
        func.date(Order.created_at)
    ).order_by(func.date(Order.created_at).desc()).all()

    unviewed = Order.query.filter_by(is_viewed=False).count()

    return render_template(
        "finance.html",
        total_revenue=total_revenue, total_orders=total_orders,
        today_revenue=today_revenue, today_orders=today_orders,
        month_revenue=month_revenue, month_orders=month_orders,
        year_revenue=year_revenue, year_orders=year_orders,
        store_stats=store_stats, daily_stats=daily_stats,
        date_from=date_from, date_to=date_to, store_q=store_q,
        unviewed_count=unviewed,
        session_user=get_admin_user(),
    )


@products_bp.route("/after-sales")
@admin_required
def after_sales():
    q = request.args.get("q", "").strip()
    base = Order.query.filter(Order.after_sale_status.in_(["pending", "processing", "done"]))
    if q:
        base = base.filter(
            Order.customer_name.contains(q)
            | Order.after_sale_reason.contains(q)
            | Order.user.has(User.store_name.contains(q))
        )
    orders = base.order_by(Order.after_sale_created_at.desc()).all()
    unviewed = Order.query.filter_by(is_viewed=False).count()
    return render_template("after_sales.html", orders=orders, q=q, unviewed_count=unviewed, session_user=get_admin_user())


@products_bp.route("/after-sale/<int:order_id>/process", methods=["POST"])
@admin_required
def process_after_sale(order_id):
    order = Order.query.get_or_404(order_id)
    action = request.form.get("action", "")
    if action == "done":
        order.after_sale_status = "done"
        order.after_sale_note = request.form.get("note", "").strip()
        order.after_sale_tracking = request.form.get("tracking", "").strip()
    elif action == "processing":
        order.after_sale_status = "processing"
    db.session.commit()
    return redirect(url_for("products.after_sales"))
