import uuid
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from app.services.graph_retriever import retriever_service
from app.core.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# STATE DEFINITION
# ============================================================

class KYCAgentState(TypedDict):
    # Investigation control
    question:            str
    investigation_depth: str          # "basic" | "deep"
    payment_status:      str          # "UNPAID" | "PAID"
    session_id:          Optional[str]
    doku_link:           Optional[str]
    invoice_number:      Optional[str]

    # Graph retrieval pipeline
    cypher_query:        Optional[str]
    graph_context:       Optional[str]
    answer:              Optional[str]
    query_decomposition: Optional[str]
    query_advice:        Optional[str]


# ============================================================
# PAYMENT GATEKEEPER NODE
# ============================================================

def payment_gatekeeper(state: KYCAgentState) -> KYCAgentState:
    """
    Paywall node — financial checkpoint before deep Neo4j extraction.

      depth == 'basic'         → free pass-through
      depth == 'deep' + PAID   → premium pass-through
      depth == 'deep' + UNPAID → create DOKU payment link, BLOCK graph
    """
    from app.services.doku_service import doku_service

    depth  = state.get("investigation_depth", "basic")
    status = state.get("payment_status", "UNPAID")

    logger.info(f"💳 Payment Gatekeeper | depth={depth} | status={status}")

    if depth == "deep" and status == "UNPAID":
        session_id = state.get("session_id") or str(uuid.uuid4())

        # Create a real DOKU payment link (falls back to mock on API error)
        result = doku_service.create_payment_link(
            session_id  = session_id,
            entity_name = state.get("question", "B2B Client")[:50],
        )

        doku_link      = result["url"]
        invoice_number = result["invoice_number"]

        logger.info(f"🔒 Blocked — DOKU link={doku_link} | invoice={invoice_number}")
        return {
            **state,
            "session_id":     session_id,
            "doku_link":      doku_link,
            "invoice_number": invoice_number,
            "payment_status": "UNPAID",
        }

    logger.info("✅ Gatekeeper PASSED — routing to Neo4j extraction.")
    return {**state, "doku_link": None}


def _route_after_payment(state: KYCAgentState) -> str:
    if state.get("investigation_depth") == "deep" and state.get("payment_status", "UNPAID") == "UNPAID":
        return "BLOCKED"
    return "PROCEED"


# ============================================================
# GRAPH BUILDER
# ============================================================

def build_kyc_graph():
    """
    KYC LangGraph:

      payment_gatekeeper
          ├─[BLOCKED]──► END           (returns doku_link)
          └─[PROCEED]──► planning
                            └── write_query
                                  └── run_query
                                        └── answer_user ──► END
    """
    workflow = StateGraph(KYCAgentState)

    workflow.add_node("payment_gatekeeper", payment_gatekeeper)
    workflow.add_node("planning",    retriever_service.query_decomposition)
    workflow.add_node("write_query", retriever_service.generate_cypher)
    workflow.add_node("run_query",   retriever_service.execute_query)
    workflow.add_node("answer_user", retriever_service.generate_answer)

    workflow.set_entry_point("payment_gatekeeper")

    workflow.add_conditional_edges(
        "payment_gatekeeper",
        _route_after_payment,
        {"BLOCKED": END, "PROCEED": "planning"},
    )

    workflow.add_edge("planning",    "write_query")
    workflow.add_edge("write_query", "run_query")
    workflow.add_edge("run_query",   "answer_user")
    workflow.add_edge("answer_user", END)

    return workflow.compile()


kyc_agent = build_kyc_graph()


def build_retriever_graph():
    return build_kyc_graph()
