from pathlib import Path
import os

from dotenv import load_dotenv # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

PROMPT_DIR = PROJECT_ROOT / "prompts"
INTERNAL_PROMPT_DIR = PROJECT_ROOT / "app" / "ai" / "internal_prompts"
DATA_DIR = PROJECT_ROOT / "data"

CONVERSATION_INSTRUCTION_PATH = PROMPT_DIR / "instruction.txt"
CTA_TEMPLATE_PATH = PROMPT_DIR / "cta_templates.txt"
FAST_RESPONSE_PATH = PROMPT_DIR / "fast_responses.txt"
PROMOTION_RULES_PATH = PROMPT_DIR / "promotion_rules.txt"
PLANNER_CONTRACT_PATH = INTERNAL_PROMPT_DIR / "planner_contract.txt"
PRESENTER_CONTRACT_PATH = INTERNAL_PROMPT_DIR / "presenter_contract.txt"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().casefold()
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "").strip().casefold()
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
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "").strip().rstrip("/")
RAG_SERVICE_API_KEY = os.getenv("RAG_SERVICE_API_KEY", "").strip()
# Server-only credential for the bot's Knowledge administration page.
RAG_SERVICE_ADMIN_API_KEY = os.getenv("RAG_SERVICE_ADMIN_API_KEY", "").strip()
RAG_SERVICE_ADMIN_TIMEOUT_SECONDS = float(
    os.getenv("RAG_SERVICE_ADMIN_TIMEOUT_SECONDS", "180")
)
RAG_SERVICE_TIMEOUT_SECONDS = float(
    os.getenv("RAG_SERVICE_TIMEOUT_SECONDS", "40")
)
SHIPPING_POLICY_DOCUMENT_ID = int(
    os.getenv("SHIPPING_POLICY_DOCUMENT_ID", "0")
)
CHANNEL_PROVIDER = os.getenv("CHANNEL_PROVIDER", "web").strip().casefold()
CHANNEL_PROVIDERS = frozenset(
    provider.strip()
    for provider in CHANNEL_PROVIDER.split(",")
    if provider.strip()
)
SUPPORTED_CHANNEL_PROVIDERS = frozenset({"web", "telegram", "facebook"})
UNKNOWN_CHANNEL_PROVIDERS = CHANNEL_PROVIDERS - SUPPORTED_CHANNEL_PROVIDERS
if not CHANNEL_PROVIDERS:
    raise RuntimeError("CHANNEL_PROVIDER phải có ít nhất một channel.")
if UNKNOWN_CHANNEL_PROVIDERS:
    raise RuntimeError(
        "CHANNEL_PROVIDER chưa được hỗ trợ: "
        + ", ".join(sorted(UNKNOWN_CHANNEL_PROVIDERS))
    )
WEB_CHAT_CHANNEL = "web"
TELEGRAM_CHAT_CHANNEL = "telegram"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
FACEBOOK_CHAT_CHANNEL = "facebook"
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv(
    "FACEBOOK_PAGE_ACCESS_TOKEN", ""
).strip()
FACEBOOK_VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "").strip()
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "").strip()
FACEBOOK_GRAPH_API_VERSION = os.getenv(
    "FACEBOOK_GRAPH_API_VERSION", "v23.0"
).strip()

# Google Sheets order export. The integration is disabled by default so local
# development and tests never contact Google unless explicitly configured.
GOOGLE_SHEETS_ENABLED = env_bool("GOOGLE_SHEETS_ENABLED", False)
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv(
    "GOOGLE_SHEETS_SPREADSHEET_ID", ""
).strip()
GOOGLE_SHEETS_ORDERS_RANGE = os.getenv(
    "GOOGLE_SHEETS_ORDERS_RANGE", "Orders!A:V"
).strip()
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "secrets/google-sheets-service-account.json",
).strip()

# Product image recognition. V2 always reads the product catalog from DB.
PRODUCTS_PATH = PROJECT_ROOT / "products.json"
PRODUCT_CATALOG_SOURCE = "database"
PRODUCT_IMAGE_DIR = DATA_DIR / "product_images"
IMAGE_INTENT_PROMPT_PATH = PROMPT_DIR / "image_intent.txt"
PRODUCT_RECOGNITION_PROMPT_PATH = PROMPT_DIR / "product_recognition.txt"
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

#HUMAN

HUMAN_MODE_ENABLED = (
    os.getenv("HUMAN_MODE_ENABLED", "false")
    .strip()
    .casefold()
    in {"1", "true", "yes", "on"}
)

HUMAN_MODE_TTL_SECONDS = int(
    os.getenv("HUMAN_MODE_TTL_SECONDS", "86400")
)

# Admin authentication. Disabled by default so an existing local installation
# is not locked out before credentials are configured in .env.
ADMIN_AUTH_ENABLED = env_bool("ADMIN_AUTH_ENABLED", False)
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "").strip()
ADMIN_SESSION_TTL_SECONDS = int(
    os.getenv("ADMIN_SESSION_TTL_SECONDS", "43200")
)
ADMIN_REMEMBER_TTL_SECONDS = int(
    os.getenv("ADMIN_REMEMBER_TTL_SECONDS", "2592000")
)
ADMIN_COOKIE_SECURE = env_bool("ADMIN_COOKIE_SECURE", False)
