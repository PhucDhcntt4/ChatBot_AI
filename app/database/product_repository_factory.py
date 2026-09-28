from app.database.qdrant_catalog_repository import QdrantCatalogRepository


def create_product_repository():
    repository = QdrantCatalogRepository()
    repository.ready()
    return repository
