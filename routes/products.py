import os
import uuid
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from models import db, Product, OrderItem
from config import ALLOWED_EXTENSIONS

products_bp = Blueprint("products", __name__)


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
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin_products.html", products=products)


@products_bp.route("/product/add", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        shelf_no = request.form.get("shelf_no", "").strip()
        price = request.form.get("price", "").strip()
        if not name or not shelf_no or not price:
            return render_template("product_form.html", product=None, error="请填写完整信息")
        image = save_upload(request.files.get("image"))
        product = Product(name=name, shelf_no=shelf_no, price=float(price), image=image)
        db.session.add(product)
        db.session.commit()
        return redirect(url_for("products.index"))
    return render_template("product_form.html", product=None, error=None)


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
    return render_template("product_form.html", product=product, error=None)


@products_bp.route("/product/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete(product_id):
    product = Product.query.get_or_404(product_id)
    # Delete associated order items first to avoid FK constraint error
    OrderItem.query.filter_by(product_id=product.id).delete()
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("products.index"))
