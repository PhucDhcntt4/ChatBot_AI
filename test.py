from app.services.product_cache_service import ProductCacheService


service = ProductCacheService()

product = service.get_product("G81S9")

if product:
    print("CODE:", product["product_code"])
    print("NAME:", product["product_name"])
else:
    print("Không tìm thấy sản phẩm")