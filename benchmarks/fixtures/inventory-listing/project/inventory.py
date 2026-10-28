def available_products(products):
    return sorted(
        [product for product in products if product.get("stock", 0) > 0],
        key=lambda product: product.get("name", ""),
    )
