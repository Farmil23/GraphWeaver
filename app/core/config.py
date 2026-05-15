import os
from dotenv import load_dotenv

load_dotenv()  # load .env into os.environ


class Settings:
    # ── Neo4j AuraDB ──────────────────────────────────────────────────────
    NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

    # ── LLM ───────────────────────────────────────────────────────────────
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY",   "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    # ── DOKU Payment Gateway ──────────────────────────────────────────────
    DOKU_CLIENT_ID  = os.getenv("DOKU_CLIENT_ID",  "demo-client-id")
    DOKU_SECRET_KEY = os.getenv("DOKU_SECRET_KEY", "demo-secret-key")
    DOKU_BASE_URL   = os.getenv("DOKU_BASE_URL",   "https://api-sandbox.doku.com")

    # ── Webhook / Tunnel ──────────────────────────────────────────────────
    NGROK_URL       = os.getenv("NGROK_URL",       "http://localhost:8000")

    # ── App ───────────────────────────────────────────────────────────────
    LOG_LEVEL       = os.getenv("LOG_LEVEL",       "INFO")
    PROJECT_NAME    = os.getenv("PROJECT_NAME",    "FinAgent")


settings = Settings()
