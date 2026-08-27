import json

from app.database.product_repository import ProductRepository
from app.services.redis_service import redis_service


class ProductCacheService:
    def __init__(self):
        self.repository = ProductRepository()

    def get_product(self, product_code: str):
        code = product_code.strip().upper()
        key = f"product:{code}"

        cached = redis_service.get(key)

        if cached:
            print(f"REDIS CACHE HIT product={code}")
            return json.loads(cached)

        print(f"REDIS CACHE MISS product={code}")

        product = self.repository.public_info(code)

        if product is None:
            return None

        redis_service.set(
            key,
            json.dumps(
                product,
                ensure_ascii=False,
            ),
        )

        return product