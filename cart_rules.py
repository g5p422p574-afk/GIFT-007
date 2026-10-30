MIXED_DELIVERY_MESSAGE = "厂家直发和公司直发商品不允许同时加入购物车下单，请先清空购物车"


def has_mixed_delivery(products):
    """Return True when products contain both factory and company delivery."""
    return len({product.delivery_type for product in products if product}) > 1


def cart_allows_product(products, product):
    """Return whether product can be placed alongside the current cart products."""
    delivery_types = {item.delivery_type for item in products if item}
    return not delivery_types or delivery_types == {product.delivery_type}
