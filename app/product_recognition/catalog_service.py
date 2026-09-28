import unicodedata
from typing import Any

from app.database.product_repository import ProductRepository
from app.database.product_repository_factory import create_product_repository


class ProductCatalogService:
    """Read the runtime product catalog from the configured repository."""

    def __init__(
        self,
        repository: ProductRepository | None = None,
    ) -> None:
        self.repository = (
            repository if repository is not None else create_product_repository()
        )

    def reference_products(
        self,
        product_type: str | None = None,
        limit: int = 5,
        images_per_product: int = 3,
    ) -> list[dict[str, Any]]:
        canonical_type = self.resolve_product_type(product_type)
        if (
            product_type
            and product_type != "unknown"
            and canonical_type is None
        ):
            return []
        return self.repository.reference_products(
            product_type=canonical_type,
            limit=limit,
            images_per_product=images_per_product,
        )

    def product_types(self, active_only: bool = True) -> list[str]:
        return self.repository.product_types(active_only)

    def resolve_product_type(
        self,
        value: str | None,
        active_only: bool = True,
    ) -> str | None:
        normalized_value = self._normalize_search_text(value or "").strip()
        if not normalized_value:
            return None
        valid_types = {
            self._normalize_search_text(item).strip(): item
            for item in self.product_types(active_only=active_only)
        }
        return valid_types.get(normalized_value)

    def public_info(self, product_code: str) -> dict[str, Any] | None:
        return self.repository.public_info(product_code)

    @staticmethod
    def _normalize_search_text(value: Any) -> str:
        normalized = unicodedata.normalize("NFD", str(value or "").casefold())
        without_accents = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        )
        return without_accents.replace("\u0111", "d")
