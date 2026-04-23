import os


class Config:
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    MODEL_NAME = os.getenv("MODEL_NAME", "dolphin3:latest")
    EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

    QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "dais_docs_v3")
    DOCS_PATH = os.getenv("DOCS_PATH", "/data/docs")

    FRONTEND_USE_VITE_DEV = os.getenv("FRONTEND_USE_VITE_DEV", "false").lower() == "true"
    VITE_DEV_SERVER = os.getenv("VITE_DEV_SERVER", "http://localhost:5173")

    JSON_SORT_KEYS = False
