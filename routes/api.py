from flask import Blueprint, request, jsonify
from models import db, Product

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/products/", methods=["POST"])
def create_product():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    name = (data.get("name") or "").strip()
    sku = (data.get("sku") or data.get("shelf_no") or "").strip()
    price = data.get("price", 0)
    images = data.get("images", [])

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not sku:
        return jsonify({"error": "sku is required"}), 400

    # Take first image if provided
    image = ""
    if images and isinstance(images, list) and len(images) > 0:
        image = images[0]
        # Strip /uploads/ prefix if present (already in uploads folder)
        if image.startswith("/uploads/"):
            image = image[len("/uploads/"):]

    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0

    product = Product(
        name=name,
        shelf_no=sku,
        price=price,
        image=image,
    )
    db.session.add(product)
    db.session.commit()

    return jsonify({
        "id": product.id,
        "sku": product.shelf_no,
        "name": product.name,
        "price": product.price,
        "image": product.image,
    }), 201
