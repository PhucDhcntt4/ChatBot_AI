from pathlib import Path
import os

from dotenv import load_dotenv # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

PROMPT_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
PLANNER_PROMPT_PATH = PROMPT_DIR / "conversation_planner.txt"
PRESENTER_PROMPT_PATH = PROMPT_DIR / "conversation_presenter.txt"
CTA_TEMPLATE_PATH = PROMPT_DIR / "cta_templates.txt"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().casefold()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()

RECOMMENDATION_DEFAULT_COUNT = int(
    os.getenv("PRODUCT_RECOMMENDATION_DEFAULT_COUNT", "3")
)
RECOMMENDATION_MAX_COUNT = int(
    os.getenv("PRODUCT_RECOMMENDATION_MAX_COUNT", "5")
)
PRODUCT_ALBUM_IMAGE_LIMIT = int(
    os.getenv("PRODUCT_ALBUM_IMAGE_LIMIT", "4")
)
HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "12"))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


RAG_ENABLED = env_bool("RAG_ENABLED", False)
RAG_EMBEDDING_PROVIDER = os.getenv(
    "RAG_EMBEDDING_PROVIDER", "auto"
).strip().casefold()
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "").strip()
RAG_EMBEDDING_DIMENSION = int(os.getenv("RAG_EMBEDDING_DIMENSION", "768"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.45"))
RAG_MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "6000"))
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "180"))

# Product image recognition. V2 always reads the product catalog from DB.
PRODUCTS_PATH = PROJECT_ROOT / "products.json"
PRODUCT_CATALOG_SOURCE = "database"
PRODUCT_IMAGE_DIR = DATA_DIR / "product_images"
PRODUCT_IMAGE_MANIFEST_PATH = PRODUCT_IMAGE_DIR / "manifest.json"
IMAGE_INTENT_PROMPT_PATH = PROMPT_DIR / "image_intent.txt"
PRODUCT_RECOGNITION_PROMPT_PATH = PROMPT_DIR / "product_recognition.txt"
PRODUCT_REPLY_PROMPT_PATH = PROMPT_DIR / "product_reply.txt"
PRODUCT_VECTOR_SEARCH_ENABLED = env_bool("PRODUCT_VECTOR_SEARCH_ENABLED", True)
IMAGE_EMBEDDING_MODEL = os.getenv("IMAGE_EMBEDDING_MODEL", "ViT-B-32").strip()
IMAGE_EMBEDDING_PRETRAINED = os.getenv(
    "IMAGE_EMBEDDING_PRETRAINED", "laion2b_s34b_b79k"
).strip()
VECTOR_SEARCH_LIMIT = int(os.getenv("VECTOR_SEARCH_LIMIT", "30"))
VECTOR_MIN_SIMILARITY = float(os.getenv("VECTOR_MIN_SIMILARITY", "0.35"))
VECTOR_AUTO_ACCEPT_SIMILARITY = float(
    os.getenv("VECTOR_AUTO_ACCEPT_SIMILARITY", "0.96")
)
VECTOR_MIN_MARGIN = float(os.getenv("VECTOR_MIN_MARGIN", "0.08"))
VECTOR_MAX_CANDIDATES = int(os.getenv("VECTOR_MAX_CANDIDATES", "3"))

VECTOR_REFERENCES_PER_PRODUCT = int(
    os.getenv("VECTOR_REFERENCES_PER_PRODUCT", "2")
)
