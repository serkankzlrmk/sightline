"""
config.py — Merged configuration for the unified ReliefWeb + SITREP application.

Merges settings from:
  - reliefwebapi/config.py     (agent, SQLite, Flask)
  - sitrep_pipeline/config.py  (pipeline, ChromaDB, LLM roles)

All values can be overridden via .env file in this directory.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from this directory (override=True to ensure .env values take precedence)
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# ── .env Migration: auto-update model names ──────────────────────────────────
# This ensures production .env stays in sync with config.py defaults.
# Only updates keys that already exist in .env; does not add missing keys.
_MODEL_MIGRATIONS = {
    "google/gemini-2.5-flash": "google/gemma-4-31b-it",
}
_MODEL_KEYS = {"ACTIVE_MODEL", "LLM_MODEL", "OLLAMA_MODEL",
               "LLM_MODEL_QUESTIONS", "LLM_MODEL_FILTER", "LLM_MODEL_ANSWERS"}

def _migrate_env_model_names():
    """Auto-migrate .env model names. Called once at import time."""
    if not _ENV_PATH.exists():
        return False
    try:
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()
        changed = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key, value = key.strip(), value.strip()
            if key in _MODEL_KEYS and value in _MODEL_MIGRATIONS:
                lines[i] = f"{key}={_MODEL_MIGRATIONS[value]}"
                changed = True
        if changed:
            _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            # Re-load .env so the new values take effect for this process
            load_dotenv(dotenv_path=_ENV_PATH, override=True)
            logging.getLogger(__name__).info("_migrate_env_model_names: .env migrated, values reloaded")
        return changed
    except Exception as e:
        logging.getLogger(__name__).error(f"_migrate_env_model_names: Error: {e}")
        return False

_migrate_env_model_names()

# Suppress ONNX TensorRT noise early (missing nvinfer DLL on most machines)
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")


# ============================================================================
# PROJECT PATHS
# ============================================================================
PROJECT_ROOT = Path(__file__).parent
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", str(PROJECT_ROOT / "reliefweb_downloads")))
DB_PATH       = Path(os.getenv("DB_PATH",       str(PROJECT_ROOT / "reliefweb.db")))
CHATS_DB_PATH = Path(os.getenv("CHATS_DB_PATH", str(PROJECT_ROOT / "chats.db")))

# NOTE: DOWNLOADS_DIR is kept for backward compatibility but is no longer used
# by the ingest pipeline. Reports are now processed in-memory (ingest_from_api)
# and no files are written to disk. The directory is NOT auto-created anymore.

# ============================================================================
# VECTOR STORE BACKEND — 'chromadb' (default) or 'pgvector'
# ============================================================================
VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "chromadb")  # 'chromadb' or 'pgvector'

# ============================================================================
# CHROMA DB — shared by both the agent and the SITREP pipeline
# ============================================================================
CHROMA_DIR: str = os.getenv(
    "CHROMA_DIR",
    str(PROJECT_ROOT / "reliefweb_chroma"),
)
CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "reliefweb_chunks")

# ============================================================================
# SUPABASE / PGVECTOR — used when VECTOR_BACKEND=pgvector
# ============================================================================
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
# Direct PostgreSQL connection string (for pgvector operations)
# Format: postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
SUPABASE_DB_URL: str = os.getenv("SUPABASE_DB_URL", "")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))  # all-MiniLM-L6-v2

# ============================================================================
# HDX (Humanitarian Data Exchange) — direct API client
# ============================================================================
HDX_APP_IDENTIFIER: str = os.getenv("HDX_APP_IDENTIFIER", "")
HDX_BASE_URL: str = os.getenv("HDX_BASE_URL", "https://hapi.humdata.org/api/v2")
HDX_TIMEOUT: float = float(os.getenv("HDX_TIMEOUT", "30.0"))
HDX_RATE_LIMIT_REQUESTS: int = int(os.getenv("HDX_RATE_LIMIT_REQUESTS", "10"))
HDX_RATE_LIMIT_PERIOD: float = float(os.getenv("HDX_RATE_LIMIT_PERIOD", "60.0"))

# ============================================================================
# LLM PROVIDER
# ============================================================================
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openrouter")

# --- OpenRouter (default for public deployment) ---
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# --- Ollama (legacy, for local dev) ---
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_API_KEY:  str = os.getenv("OLLAMA_API_KEY",  "")
OLLAMA_TIMEOUT:  int = int(os.getenv("OLLAMA_TIMEOUT", "60"))

# --- Effective LLM settings (resolved based on LLM_PROVIDER) ---
_LLM_BASE_URL: str = OPENROUTER_BASE_URL if LLM_PROVIDER == "openrouter" else OLLAMA_BASE_URL
_LLM_API_KEY:  str  = OPENROUTER_API_KEY if LLM_PROVIDER == "openrouter" else OLLAMA_API_KEY

# ============================================================================
# ACTIVE MODEL
# ============================================================================
ACTIVE_MODEL: str = os.getenv("ACTIVE_MODEL", "google/gemma-4-31b-it")

# reliefwebapi agent uses OLLAMA_MODEL (also aliased to ACTIVE_MODEL)
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", ACTIVE_MODEL)

# sitrep_pipeline uses LLM_MODEL
LLM_MODEL: str = os.getenv("LLM_MODEL", ACTIVE_MODEL)

# ============================================================================
# MODEL PARAMETERS — reliefwebapi agent
# ============================================================================
MODEL_TEMPERATURE: float = float(os.getenv("MODEL_TEMPERATURE", "0.3"))
MODEL_MAX_TOKENS:  int   = int(os.getenv("MODEL_MAX_TOKENS",   "2048"))

# ============================================================================
# ROLE-BASED LLM SETTINGS — sitrep pipeline stages
# ============================================================================
LLM_TEMPERATURE: float = 0.0
LLM_MAX_TOKENS_DEFAULT: int = 1024
LLM_MAX_TOKENS_ANSWER:  int = 4096
LLM_MAX_TOKENS_SUMMARY: int = 4096
LLM_MAX_TOKENS_HEADLINE: int = 64
LLM_TIMEOUT:     int = int(os.getenv("LLM_TIMEOUT",     "180"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

# Question generation
LLM_MODEL_QUESTIONS:       str   = os.getenv("LLM_MODEL_QUESTIONS",       LLM_MODEL)
LLM_TEMPERATURE_QUESTIONS: float = float(os.getenv("LLM_TEMPERATURE_QUESTIONS", "0.7"))

# Question filtering
LLM_MODEL_FILTER:       str   = os.getenv("LLM_MODEL_FILTER",       LLM_MODEL)
LLM_TEMPERATURE_FILTER: float = float(os.getenv("LLM_TEMPERATURE_FILTER", "0.0"))

# RAG answers / summaries
LLM_MODEL_ANSWERS:       str   = os.getenv("LLM_MODEL_ANSWERS",       LLM_MODEL)
LLM_TEMPERATURE_ANSWERS: float = float(os.getenv("LLM_TEMPERATURE_ANSWERS", "0.0"))

# ============================================================================
# RETRIEVAL PARAMETERS — sitrep pipeline
# ============================================================================
RETRIEVAL_TOP_K:         int   = int(os.getenv("RETRIEVAL_TOP_K",   "10"))
RETRIEVAL_TOP_K_SUMMARY: int   = int(os.getenv("RETRIEVAL_TOP_K_SUMMARY", "20"))
RRF_K:                   int   = int(os.getenv("RRF_K",             "60"))
RRF_NUM_SUBQUERIES:      int   = int(os.getenv("RRF_NUM_SUBQUERIES", "3"))

# ============================================================================
# CLUSTERING PARAMETERS — sitrep pipeline
# ============================================================================
UMAP_N_COMPONENTS: int   = 10
UMAP_METRIC:       str   = "cosine"
UMAP_MIN_DIST:     float = 0.0

HDBSCAN_METRIC:                  str   = "euclidean"
HDBSCAN_CLUSTER_SELECTION_METHOD: str  = "eom"

HP_N_NEIGHBORS_RANGE:    tuple = (5, 30)
HP_MIN_CLUSTER_SIZE_RANGE: tuple = (10, 100)
HP_MIN_SAMPLES_RANGE:    tuple = (1, 10)
HP_EPSILON_OPTIONS:      tuple = (0.0, 0.05, 0.1, 0.2, 0.3)
HP_SEARCH_ITERATIONS:    int   = int(os.getenv("HP_SEARCH_ITERATIONS", "30"))
HP_MIN_CLUSTERS:         int   = int(os.getenv("HP_MIN_CLUSTERS",      "4"))

# ============================================================================
# QUESTION GENERATION PARAMETERS
# ============================================================================
QUESTION_RUNS_PER_CLUSTER:  int   = int(os.getenv("QUESTION_RUNS_PER_CLUSTER",  "2"))
QUESTION_DEDUP_THRESHOLD:   float = float(os.getenv("QUESTION_DEDUP_THRESHOLD", "0.7"))
MAX_QUESTIONS_PER_CLUSTER:  int   = int(os.getenv("MAX_QUESTIONS_PER_CLUSTER",  "4"))
MAX_TOTAL_QUESTIONS:        int   = int(os.getenv("MAX_TOTAL_QUESTIONS",        "120"))
MAX_CLUSTERS:              int   = int(os.getenv("MAX_CLUSTERS",              "30"))

# ============================================================================
# OUTPUT DIRECTORIES — sitrep pipeline
# ============================================================================
_BASE             = PROJECT_ROOT / "output"
OUTPUT_DIR        = _BASE
OUTPUT_CLUSTERS_DIR  = _BASE / "clusters"
OUTPUT_QUESTIONS_DIR = _BASE / "questions"
OUTPUT_ANSWERS_DIR   = _BASE / "answers"
OUTPUT_SUMMARIES_DIR = _BASE / "summaries"
OUTPUT_REPORTS_DIR   = _BASE / "reports"
OUTPUT_BULLETINS_DIR = _BASE / "bulletins"

for _d in [OUTPUT_DIR, OUTPUT_CLUSTERS_DIR, OUTPUT_QUESTIONS_DIR,
           OUTPUT_ANSWERS_DIR, OUTPUT_SUMMARIES_DIR, OUTPUT_REPORTS_DIR,
           OUTPUT_BULLETINS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ============================================================================
# RELIEFWEB API
# ============================================================================
RELIEFWEB_APPNAME: str = os.getenv("RELIEFWEB_APPNAME", "redagent_platform")

# ============================================================================
# FLASK / SERVER
# ============================================================================
SERVER_HOST:  str  = os.getenv("SERVER_HOST",  "0.0.0.0")
SERVER_PORT:  int  = int(os.getenv("SERVER_PORT", "5001"))
SERVER_DEBUG: bool = os.getenv("SERVER_DEBUG", "false").lower() == "true"
SERVER_API_KEY: str = os.getenv("SERVER_API_KEY", "")
CORS_ORIGINS:  str = os.getenv("CORS_ORIGINS", "*")

# SSL verification for outbound HTTP requests (ReliefWeb API, PDF downloads)
SSL_VERIFY: bool = os.getenv("SSL_VERIFY", "true").lower() == "true"
SSL_CA_BUNDLE: str = os.getenv("SSL_CA_BUNDLE", "")
SECRET_KEY:  str = os.getenv("SECRET_KEY", os.urandom(24).hex())

# Aliases for reliefwebapi compatibility
FLASK_PORT  = SERVER_PORT
FLASK_DEBUG = SERVER_DEBUG
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")

# ============================================================================
# RATE LIMITING — daily message limit per user (role-aware)
# ============================================================================
DAILY_MESSAGE_LIMIT: int = int(os.getenv("DAILY_MESSAGE_LIMIT", "10"))
PREMIUM_MESSAGE_LIMIT: int = int(os.getenv("PREMIUM_MESSAGE_LIMIT", "100"))
ADMIN_MESSAGE_LIMIT: int = 999  # effectively unlimited


# ============================================================================
# COMPATIBILITY — expose a config object for reliefwebapi's `from config import config`
# ============================================================================
class _Config:
    """Thin object wrapper so `from config import config; config.FLASK_PORT` works."""
    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(f"Config has no attribute '{name}'")

config = _Config()
