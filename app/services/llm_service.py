"""
LLM client for FinAgent — B2B KYC & Due Diligence platform.
Uses GPT-4o (OpenAI) as primary model.
"""

import os
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── B2B Due Diligence system prompt ─────────────────────────────────────────
B2B_SYSTEM_PROMPT = (
    "You are a highly advanced B2B Due Diligence AI specialising in corporate "
    "risk analysis for institutional and enterprise clients. "
    "You analyse company structures, executive relationships, beneficial ownership, "
    "and potential conflicts of interest with precision and formality. "
    "Basic summaries (entity Q&A over pre-loaded graph data) are provided free of charge. "
    "Deep investigations — including full multi-hop entity relationship mapping, "
    "shell-company detection, and beneficial ownership tracing across the Neo4j "
    "knowledge graph — require the user to pay for premium compute via the DOKU "
    "payment gateway. Always be concise, data-driven, and cite graph evidence."
)


class GroqClient:
    """
    LLM client — uses GPT-4o (OpenAI) as primary.
    Falls back to Groq llama if OpenAI key is unavailable.
    Class name kept as GroqClient for backward compatibility.
    """

    def __init__(self):
        self.llm = None

    def get_llm(self, model_name: str = "gpt-4o"):
        """Return a configured LLM instance (GPT-4o preferred)."""
        openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")

        if openai_key and not openai_key.startswith("sk-proj-CHANGE"):
            try:
                from langchain_openai import ChatOpenAI
                self.llm = ChatOpenAI(
                    model=model_name,
                    api_key=openai_key,
                    temperature=0.0,
                )
                logger.info(f"✅ Connected to OpenAI model: {model_name}")
                return self.llm
            except Exception as exc:
                logger.warning(f"OpenAI unavailable ({exc}), falling back to Groq")

        # Fallback: Groq
        try:
            from langchain_groq import ChatGroq
            self.llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=settings.GROQ_API_KEY,
                temperature=0.0,
            )
            logger.info("✅ Connected to Groq model: llama-3.3-70b-versatile (fallback)")
            return self.llm
        except Exception as exc:
            logger.error(f"[ERROR] All LLM backends failed: {exc}")
            raise

    def execute_model(self, query: str) -> dict | None:
        try:
            llm    = self.get_llm()
            result = llm.invoke(query)
            logger.info("✅ Model query executed successfully")
            return {"result": result, "model": getattr(llm, "model_name", "unknown")}
        except Exception as exc:
            logger.error(f"ERROR — Failed to execute model query: {exc}")
            return None
