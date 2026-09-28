-- Run only after the Qdrant v2 collection has been fully synchronized and tested.
-- RESTRICT intentionally stops the migration if another schema still uses pgvector.

BEGIN;

DROP TABLE IF EXISTS product_image_embeddings;
DROP TABLE IF EXISTS internal_knowledge_chunks;
DROP TABLE IF EXISTS internal_knowledge_documents;
DROP EXTENSION IF EXISTS vector RESTRICT;

COMMIT;
