"""
FinAgent — B2B KYC & Due Diligence API  (FastAPI + Jinja2)
"""

import os
import uuid
import threading
from typing import Optional

import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from werkzeug.utils import secure_filename

from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

# ── App setup ────────────────────────────────────────────────────────────────

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..")

app = FastAPI(
    title="FinAgent — B2B KYC & Due Diligence",
    description="AI-powered forensic knowledge graph investigator with DOKU payment paywall.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files + Jinja2 templates
_static_dir    = os.path.join(BASE_DIR, "app", "static")
_template_dir  = os.path.join(BASE_DIR, "app", "templates")

app.mount("/static", StaticFiles(directory=_static_dir), name="static")
templates = Jinja2Templates(directory=_template_dir)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Heavy services — lazy-loaded on first use to speed up startup
_extractor = None
_kyc_agent  = None


def _get_extractor():
    global _extractor
    if _extractor is None:
        from app.services.graph_extractor import GraphExtractorService
        _extractor = GraphExtractorService()
    return _extractor


def _get_kyc_agent():
    global _kyc_agent
    if _kyc_agent is None:
        from app.services.workflow import kyc_agent as _agent
        _kyc_agent = _agent
    return _kyc_agent

# ── Session store (file-backed for persistence across restarts) ──────────────
import json as _json

_SESSIONS_FILE  = os.path.join(BASE_DIR, "sessions.json")
_sessions:     dict = {}
_invoice_map:  dict = {}
_lock = threading.Lock()


def _load_sessions():
    global _sessions, _invoice_map
    try:
        if os.path.exists(_SESSIONS_FILE):
            with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            _sessions    = data.get("sessions", {})
            _invoice_map = data.get("invoice_map", {})
            logger.info(f"📂 Loaded {len(_sessions)} sessions from disk")
    except Exception as e:
        logger.warning(f"Could not load sessions file: {e}")


def _save_sessions():
    try:
        with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
            _json.dump({"sessions": _sessions, "invoice_map": _invoice_map}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Could not save sessions: {e}")


_load_sessions()


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    question:            str
    investigation_depth: str          = "basic"
    session_id:          Optional[str] = None
    payment_status:      Optional[str] = "UNPAID"


class DokuWebhookPayload(BaseModel):
    transaction_id:  Optional[str] = None
    status:          Optional[str] = None
    session_id:      Optional[str] = None
    invoice_number:  Optional[str] = None
    question:        Optional[str] = None   # sent by frontend as resurrection hint
    # DOKU v1 notification keys (case-sensitive as DOKU sends them)
    TRANSACTION_STATUS: Optional[str] = None
    INVOICE_NUMBER:     Optional[str] = None


class InvestigateResponse(BaseModel):
    status:         str
    answer:         Optional[str] = None
    doku_link:      Optional[str] = None
    session_id:     Optional[str] = None
    invoice_number: Optional[str] = None
    message:        Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _init_inputs(question, depth, payment_status, session_id) -> dict:
    return {
        "question":            question,
        "investigation_depth": depth,
        "payment_status":      payment_status,
        "session_id":          session_id,
        "doku_link":           None,
        "invoice_number":      None,
        "cypher_query":        None,
        "graph_context":       None,
        "answer":              None,
        "query_decomposition": "",
        "query_advice":        "",
    }


def _resume_investigation(session_id: str, question: str) -> None:
    logger.info(f"🚀 Resuming deep investigation for session {session_id}")
    try:
        result = _get_kyc_agent().invoke(
            _init_inputs(question, "deep", "PAID", session_id)
        )
        answer       = result.get("answer") or "Investigation complete — no answer generated."
        cypher       = result.get("cypher_query", "")
        ctx          = result.get("graph_context", "")
        decomp       = result.get("query_decomposition", "")
        row_count    = len(ctx.splitlines()) if ctx else 0
        with _lock:
            _sessions[session_id].update(
                answer=answer,
                cypher_used=cypher,
                raw_context=ctx,
                query_decomposition=decomp,
                row_count=row_count,
                status="COMPLETE",
            )
            _save_sessions()
        logger.info(f"✅ Deep investigation COMPLETE for session {session_id}")
    except Exception as exc:
        logger.error(f"❌ Background investigation failed [{session_id}]: {exc}")
        with _lock:
            _sessions[session_id].update(status="ERROR", answer=str(exc))


# ════════════════════════════════════════════════════════════════════════════
# FRONTEND ROUTES (HTML)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/payment-success", response_class=HTMLResponse, tags=["Frontend"])
async def payment_success(request: Request, session_id: str = ""):
    """DOKU redirects here after successful payment."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "auto_resume_session": session_id},
    )


@app.get("/payment-cancelled", response_class=HTMLResponse, tags=["Frontend"])
async def payment_cancelled(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ════════════════════════════════════════════════════════════════════════════
# API — DOCUMENT UPLOAD
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload", tags=["Documents"])
async def upload_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    logger.info(f"📄 Processing: {filename}")
    ok = _get_extractor().process_uploaded_file_from_api(filepath, filename)

    if ok:
        return {"status": "success", "message": f"{filename} ingested into Knowledge Graph!"}
    raise HTTPException(status_code=500, detail="Failed to extract text from document")


# ════════════════════════════════════════════════════════════════════════════
# API — DOCUMENT LIST + DOWNLOAD
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/documents", tags=["Documents"])
async def list_documents():
    """List all documents in the uploads folder with metadata."""
    docs = []
    try:
        for fname in sorted(os.listdir(UPLOAD_FOLDER)):
            if fname.startswith('.'):
                continue
            fpath = os.path.join(UPLOAD_FOLDER, fname)
            if not os.path.isfile(fpath):
                continue
            stat  = os.stat(fpath)
            size  = stat.st_size
            mtime = stat.st_mtime
            import datetime
            modified = datetime.datetime.fromtimestamp(mtime).strftime('%d %b %Y %H:%M')
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size // 1024} KB"
            else:
                size_str = f"{size // (1024*1024):.1f} MB"
            docs.append({"name": fname, "size": size_str, "modified": modified})
    except Exception as e:
        logger.warning(f"Could not list documents: {e}")
    return {"documents": docs}


@app.get("/api/documents/download/{filename}", tags=["Documents"])
async def download_document(filename: str):
    """Download an uploaded document by filename."""
    safe = secure_filename(filename)
    fpath = os.path.join(UPLOAD_FOLDER, safe)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath, media_type="application/octet-stream", filename=safe)


# ════════════════════════════════════════════════════════════════════════════
# API — INVESTIGATION
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/investigate", response_model=InvestigateResponse, tags=["Investigation"])
async def investigate(req: InvestigateRequest):
    """
    Core KYC investigation endpoint.
    - Basic: runs immediately, free.
    - Deep + UNPAID → returns DOKU payment link (real sandbox link).
    - Deep + PAID   → full Neo4j graph extraction.
    """
    session_id     = req.session_id or str(uuid.uuid4())
    payment_status = req.payment_status or "UNPAID"

    # Honour a previous webhook confirmation
    with _lock:
        stored = _sessions.get(session_id)
    if stored and stored.get("payment_status") == "PAID":
        payment_status = "PAID"

    logger.info(f"🔍 /investigate | depth={req.investigation_depth} | paid={payment_status} | sid={session_id}")

    try:
        result = _get_kyc_agent().invoke(
            _init_inputs(req.question, req.investigation_depth, payment_status, session_id)
        )
    except Exception as exc:
        logger.error(f"❌ Graph error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    # ── Payment wall triggered ───────────────────────────────────────────
    if result.get("payment_status") == "UNPAID" and result.get("doku_link"):
        doku_link  = result["doku_link"]
        inv_number = result.get("invoice_number", "")
        sid        = result["session_id"]

        with _lock:
            _sessions[sid] = {
                "question":       req.question,
                "depth":          req.investigation_depth,
                "payment_status": "UNPAID",
                "doku_link":      doku_link,
                "invoice_number": inv_number,
                "answer":         None,
                "status":         "AWAITING_PAYMENT",
            }
            if inv_number:
                _invoice_map[inv_number] = sid
            _save_sessions()

        return InvestigateResponse(
            status         = "PAYMENT_REQUIRED",
            doku_link      = doku_link,
            session_id     = sid,
            invoice_number = inv_number,
            message        = (
                f"Deep investigation requires payment (Rp 50,000). "
                f"Complete the DOKU checkout to unlock full Neo4j graph extraction."
            ),
        )

    # ── Successful investigation ─────────────────────────────────────────
    answer = result.get("answer") or "No answer generated."
    with _lock:
        _sessions[session_id] = {
            "question":       req.question,
            "depth":          req.investigation_depth,
            "payment_status": payment_status,
            "answer":         answer,
            "cypher_used":    result.get("cypher_query", ""),
            "raw_context":    result.get("graph_context", ""),
            "status":         "COMPLETE",
        }
    return InvestigateResponse(status="SUCCESS", answer=answer, session_id=session_id)


# ── Result polling ────────────────────────────────────────────────────────────

@app.get("/api/result/{session_id}", tags=["Investigation"])
async def get_result(session_id: str):
    with _lock:
        session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    status = session.get("status", "UNKNOWN")
    return {
        "status":              status,
        "session_id":          session_id,
        "answer":              session.get("answer"),
        "cypher_used":         session.get("cypher_used", ""),
        "query_decomposition": session.get("query_decomposition", ""),
        "row_count":           session.get("row_count", 0),
    }


# ════════════════════════════════════════════════════════════════════════════
# API — DOKU PAYMENT WEBHOOK
# ════════════════════════════════════════════════════════════════════════════

@app.post("/webhooks/doku-paid", tags=["Payments"])
async def doku_payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Accepts DOKU payment notifications in multiple formats:
    - Our simulate button: {"transaction_id":..., "status":"SUCCESS", "session_id":...}
    - DOKU v1 notification: {"INVOICE.NUMBER":..., "TRANSACTION.STATUS":"SUCCESS"}
    - DOKU v2 notification: {"order":{"invoice_number":...}, "transaction":{"status":"SUCCESS"}}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"📬 DOKU webhook received: {body}")

    # ── Resolve session_id ────────────────────────────────────────────────
    session_id     = body.get("session_id")
    invoice_number = (
        body.get("invoice_number")
        or body.get("INVOICE.NUMBER")
        or body.get("INVOICE_NUMBER")
        or (body.get("order") or {}).get("invoice_number")
    )
    tx_status = (
        body.get("status")
        or body.get("TRANSACTION.STATUS")
        or body.get("TRANSACTION_STATUS")
        or (body.get("transaction") or {}).get("status")
        or "SUCCESS"
    )

    if not session_id and invoice_number:
        with _lock:
            session_id = _invoice_map.get(invoice_number)

    if not session_id:
        raise HTTPException(
            status_code=404,
            detail="Cannot resolve session from webhook payload. Include session_id or invoice_number.",
        )

    if tx_status.upper() not in ("SUCCESS", "PAID", "00"):
        logger.info(f"ℹ️ Webhook status '{tx_status}' — not a success, ignoring.")
        return {"status": "ignored"}

    with _lock:
        session = _sessions.get(session_id)

    # ── Session resurrection (lost after hot-reload) ──────────────────────
    if not session:
        question_hint = body.get("question", "").strip()
        if not question_hint:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found and no question hint provided to resurrect it.",
            )
        logger.warning(f"⚡ Session '{session_id}' not in memory — resurrecting from question hint.")
        with _lock:
            _sessions[session_id] = {
                "question":       question_hint,
                "depth":          "deep",
                "payment_status": "PAID",
                "answer":         None,
                "status":         "PROCESSING",
            }
        session = _sessions[session_id]

    logger.info(f"✅ Payment confirmed for session {session_id}")
    with _lock:
        _sessions[session_id]["payment_status"] = "PAID"
        _sessions[session_id]["status"]         = "PROCESSING"
        _save_sessions()

    background_tasks.add_task(_resume_investigation, session_id, session["question"])

    return {
        "status":     "ACCEPTED",
        "session_id": session_id,
        "message":    "Payment confirmed. Deep investigation is now running.",
    }


# ════════════════════════════════════════════════════════════════════════════
# API — GRAPH VISUALIZATION
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/graph", tags=["Graph"])
async def get_graph(entity: str = ""):
    """Return Neo4j entities and relationships in vis.js Network format."""
    import asyncio
    try:
        from app.services.graph_retriever import retriever_service
        loop = asyncio.get_running_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, retriever_service.get_graph_visualization, entity),
            timeout=15.0
        )
        return data
    except asyncio.TimeoutError:
        return {"nodes": [], "edges": [], "error": "Graph query timed out"}
    except Exception as exc:
        logger.error(f"Graph viz error: {exc}")
        return {"nodes": [], "edges": [], "error": str(exc)}


def _fetch_graph_stats() -> dict:
    """Blocking Neo4j stats call — run in thread pool only."""
    from app.services.graph_retriever import retriever_service
    results = retriever_service.graph.query(
        "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count"
    )
    total_nodes = sum(r["count"] for r in results)
    rel_results = retriever_service.graph.query(
        "MATCH ()-[r]->() RETURN count(r) AS total"
    )
    total_rels = rel_results[0]["total"] if rel_results else 0
    breakdown  = {r["type"]: r["count"] for r in results if r.get("type")}
    return {
        "total_nodes":     total_nodes,
        "total_relations": total_rels,
        "breakdown":       breakdown,
    }


@app.get("/api/graph/stats", tags=["Graph"])
async def get_graph_stats():
    """Return high-level graph statistics (non-blocking, 12 s timeout)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_graph_stats),
            timeout=12.0
        )
        return data
    except asyncio.TimeoutError:
        return {"total_nodes": 0, "total_relations": 0, "breakdown": {}, "error": "Stats query timed out"}
    except Exception as exc:
        logger.error(f"Graph stats error: {exc}")
        return {"total_nodes": 0, "total_relations": 0, "breakdown": {}, "error": str(exc)}


# ════════════════════════════════════════════════════════════════════════════
# API — HEALTH
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/health", tags=["Health"])
async def health():
    return {
        "service": "FinAgent B2B KYC",
        "version": "2.0.0",
        "status":  "operational",
    }


# Legacy GET alias (backward compat)
@app.get("/get-data", tags=["Legacy"])
async def get_data_legacy(question: str):
    if not question:
        raise HTTPException(status_code=400, detail="'question' required")
    try:
        result = _get_kyc_agent().invoke(_init_inputs(question, "basic", "PAID", str(uuid.uuid4())))
        return {"status": "success", "answer": result.get("answer"), "cypher_used": result.get("cypher_query")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("app.api.v1.endpoints:app", host="0.0.0.0", port=8000, reload=False)
