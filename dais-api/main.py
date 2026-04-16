from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import os
import re
import glob
import hashlib
import requests
import uuid
import pdfplumber
from typing import List, Dict, Any, Optional, Literal

app = FastAPI(title="DaiS API")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "dolphin3:latest")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "dais_docs_v3")
DOCS_PATH = os.getenv("DOCS_PATH", "/data/docs")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# -----------------------------
# Models
# -----------------------------
class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False

class IngestResponse(BaseModel):
    files: int
    doc_units: int
    chunks: int
    collection: str

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    max_sources: int = Field(default=5, ge=1, le=12)
    strictness: Literal["balanced", "strict"] = "balanced"
    min_semantic_score: float = Field(default=0.35, ge=0.0, le=1.0)
    answer_style: Literal["auto", "concise", "detailed", "steps", "parameters"] = "auto"
    debug: bool = True

# -----------------------------
# Helpers: Ollama
# -----------------------------
def ollama_embed(text: str) -> List[float]:
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=120,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama embeddings endpoint: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Ollama embeddings failed: {r.text}")
    data = r.json()
    return data["embedding"]

def ollama_generate(prompt: str) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=300,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama generate endpoint: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Ollama generate failed: {r.text}")
    return r.json().get("response", "")

# -----------------------------
# Helpers: Qdrant (HTTP)
# -----------------------------
def qdrant_collection_exists() -> bool:
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=30)
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Qdrant collection endpoint: {exc}") from exc
    return r.status_code == 200

def qdrant_create_collection(vector_size: int) -> None:
    payload = {
        "vectors": {
            "size": vector_size,
            "distance": "Cosine"
        }
    }
    try:
        r = requests.put(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", json=payload, timeout=60)
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Qdrant create-collection endpoint: {exc}") from exc
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Create collection failed: {r.text}")

def qdrant_upsert(points: List[Dict[str, Any]]) -> None:
    try:
        r = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points?wait=true",
            json={"points": points},
            timeout=300,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Qdrant upsert endpoint: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Upsert failed: {r.text}")

def qdrant_search(vector: List[float], limit: int) -> List[Dict[str, Any]]:
    payload = {
        "vector": vector,
        "limit": limit,
        "with_payload": True
    }
    try:
        r = requests.post(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/search",
            json=payload,
            timeout=60,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Qdrant search endpoint: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Search failed: {r.text}")
    return r.json().get("result", [])

# -----------------------------
# Helpers: Docs + Chunking
# -----------------------------
def read_docs(docs_path: str) -> List[Dict[str, str]]:
    files = []

    # txt + md as before
    for ext in ("txt", "md"):
        pat = os.path.join(docs_path, f"**/*.{ext}")
        for fp in glob.glob(pat, recursive=True):
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    files.append({"path": fp, "text": f.read(), "kind": "text", "page": None})
            except Exception:
                continue

    # PDF: emit one doc item per page (this is the important change)
    pat_pdf = os.path.join(docs_path, "**/*.pdf")
    for fp in glob.glob(pat_pdf, recursive=True):
        try:
            with pdfplumber.open(fp) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    txt = (page.extract_text() or "").strip()
                    if txt:
                        files.append({"path": fp, "text": txt, "kind": "pdf", "page": page_num})
        except Exception:
            continue
    
    return files


def chunk_text(text: str, chunk_chars: int = 1200, overlap: int = 200) -> List[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_chars, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

def stable_id(s: str) -> int:
    # stable deterministic ID for Qdrant point IDs (int)
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h[:15], 16)

def ensure_collection_ready() -> None:
    if qdrant_collection_exists():
        return
    # determine embedding size dynamically
    vec = ollama_embed("dimension check")
    qdrant_create_collection(vector_size=len(vec))


def keyword_boost(payload: dict, question: str) -> int:
    text = (payload.get("text") or "").lower()

    # Extract tokens from the question:
    # - camelCase, snake_case, long identifiers
    # - words >= 4 chars
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", question)
    terms = [t.lower() for t in terms]

    score = 0

    # --------------------------------------------------
    # 1) STRONG exact identifier matching (config keys)
    # --------------------------------------------------
    for t in terms:
        if t in text:
            score += 50  # exact hit -> very important

    # --------------------------------------------------
    # 2) Partial identifier matches (handles typos)
    # --------------------------------------------------
    for t in terms:
        if len(t) >= 10:
            if t[:6] in text or t[-6:] in text:
                score += 5

    # --------------------------------------------------
    # 3) Boost render-request parameter TABLES
    # --------------------------------------------------
    if "parameter description default" in text:
        score += 40
    if "mandatory parameters" in text:
        score += 30
    if "data parameters" in text:
        score += 30
    if "delivery options" in text:
        score += 25
    if "render request" in text or "/render" in text:
        score += 25

    # --------------------------------------------------
    # 4) Penalise non-request sections (very important)
    # --------------------------------------------------
    if (
        "status service" in text
        or "response body" in text
        or "convertercount" in text
        or "uptimeseconds" in text
        or "/status" in text
        or "/ping" in text
    ):
        score -= 40

    return score

def rerank_score(hit: Dict[str, Any], question: str) -> float:
    # Keep semantic relevance from Qdrant as the primary signal.
    semantic = float(hit.get("score", 0.0) or 0.0)
    payload = hit.get("payload", {}) or {}
    lexical = float(keyword_boost(payload, question))
    return (semantic * 100.0) + lexical

def answer_question(
    question: str,
    top_k: int,
    debug: bool = False,
    strictness: str = "balanced",
    min_semantic_score: float = 0.35,
    max_sources: int = 5,
    answer_style: str = "auto",
) -> Dict[str, Any]:
    ensure_collection_ready()

    qvec = ollama_embed(question)

    # Fetch more candidates than we'll use, then re-rank
    raw_hits = qdrant_search(qvec, limit=max(top_k * 10, 50))
    top_semantic = max((float(h.get("score", 0.0) or 0.0) for h in raw_hits), default=0.0)
    if strictness == "strict" and top_semantic < min_semantic_score:
        resp = {
            "answer": "Not found in provided documentation context.",
            "citations": [],
            "sources": [],
            "meta": {
                "strictness": strictness,
                "top_semantic_score": round(top_semantic, 4),
                "threshold": min_semantic_score,
            },
        }
        if debug:
            resp["retrieved"] = []
        return resp

    raw_hits.sort(key=lambda h: rerank_score(h, question), reverse=True)
    hits = raw_hits[:top_k]

    context_blocks = []
    citations = []
    debug_hits = []
    sources = []
    seen_citations = set()

    for h in hits:
        if len(citations) >= max_sources:
            break
        payload = h.get("payload", {}) or {}
        src = payload.get("source", "unknown")
        page = payload.get("page", None)
        idx = payload.get("chunk_index", 0)
        txt = payload.get("text", "") or ""
        semantic_score = float(h.get("score", 0.0) or 0.0)
        if strictness == "strict" and semantic_score < min_semantic_score:
            continue

        cite = f"{src}#chunk:{idx}" if page is None else f"{src}#page:{page}:chunk:{idx}"
        if cite in seen_citations:
            continue
        seen_citations.add(cite)
        citations.append(cite)
        context_blocks.append(f"[{cite}]\n{txt}")

        sources.append({
            "citation": cite,
            "doc": src,
            "page": page,
            "chunk": idx,
            "semantic_score": round(semantic_score, 4),
            "label": f"{src} (p.{page})" if page is not None else src,
            "preview": (txt[:400] + "...") if len(txt) > 400 else txt,
        })

        debug_hits.append({
            "citation": cite,
            "preview": (txt[:400] + "...") if len(txt) > 400 else txt
        })

    if strictness == "strict" and not context_blocks:
        resp = {
            "answer": "Not found in provided documentation context.",
            "citations": [],
            "sources": [],
            "meta": {
                "strictness": strictness,
                "top_semantic_score": round(top_semantic, 4),
                "threshold": min_semantic_score,
            },
        }
        if debug:
            resp["retrieved"] = []
        return resp

    is_parameter_query = bool(
        re.search(
            r"\b(parameter|parameters|param|params|option|options|argument|arguments|names only)\b",
            question,
            flags=re.IGNORECASE,
        )
    )

    system_rules = (
    "You are DaiS (Docmosis AI Support), an internal support assistant.\n"
    "Answer using ONLY the documentation context provided.\n"
    "Do NOT use prior knowledge.\n"
    "If the answer is not supported by the provided context, say: 'Not found in provided documentation context.'\n"
    "Use citations exactly as shown in the context labels, e.g. [file#page:X:chunk:Y]. Do not invent other citation formats.\n"
    "Copy parameter names exactly as written in the context (case-sensitive).\n"
    "Do NOT include response fields or status/service monitoring fields unless the question explicitly asks for them.\n"
    "If the question asks for parameters, list only parameters that appear verbatim in the provided context.\n"
    "Every claim must include at least one citation in square brackets like [file#page:X:chunk:Y].\n"
    "Be concise and practical.\n"
)

    if answer_style == "parameters" or (answer_style == "auto" and is_parameter_query):
        format_rules = (
        "Write the answer as:\n"
        "Parameters (extractive):\n"
        "- If the user asked for 'names only', output ONLY: <parameter> [citation]\n"
        "- Otherwise output: <parameter> - <meaning> [citation]\n"
        )
    elif answer_style == "steps":
        format_rules = (
        "Write the answer as:\n"
        "- Start with one short direct answer sentence.\n"
        "- Then provide a numbered step-by-step list.\n"
        "- End every step with one or more citations in square brackets.\n"
        )
    elif answer_style == "detailed":
        format_rules = (
        "Write the answer as:\n"
        "- Start with one short direct answer sentence.\n"
        "- Then up to 8 concise bullets with practical details.\n"
        "- End each bullet with one or more citations in square brackets.\n"
        )
    else:
        format_rules = (
        "Write the answer as:\n"
        "- Start with one short direct answer sentence.\n"
        "- Then up to 5 concise bullets with practical details.\n"
        "- End each bullet with one or more citations in square brackets.\n"
        "- Do not include the heading 'Parameters (extractive)' unless the user asked for parameters.\n"
        )

    prompt = (
    f"{system_rules}\n\n"
    f"QUESTION:\n{question}\n\n"
    f"DOCUMENTATION CONTEXT:\n\n"
    + "\n\n---\n\n".join(context_blocks)
    + "\n\n"
    + format_rules
    + "\n\nANSWER:\n"
)

    answer = ollama_generate(prompt)

    resp = {
        "answer": answer.strip(),
        "citations": citations,
        "sources": sources,
        "meta": {
            "strictness": strictness,
            "top_semantic_score": round(top_semantic, 4),
            "threshold": min_semantic_score,
            "answer_style": answer_style,
            "max_sources": max_sources,
        },
    }
    if debug:
        resp["retrieved"] = debug_hits
    return resp


# -----------------------------
# API
# -----------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "embed_model": EMBED_MODEL,
        "collection": COLLECTION_NAME,
    }

@app.get("/")
def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Chat UI not found. Add static/index.html.")
    return FileResponse(index_path)

@app.post("/ingest", response_model=IngestResponse)
def ingest():
    ensure_collection_ready()

    docs = read_docs(DOCS_PATH)
    if not docs:
        raise HTTPException(
            status_code=400,
            detail=f"No .txt or .md or pdf files found under {DOCS_PATH}."
        )

    points = []
    chunk_count = 0
    unique_sources = set()

    for d in docs:
        rel_path = d["path"].replace(DOCS_PATH, "").lstrip("/\\")
        unique_sources.add(rel_path)
        page_num = d.get("page")
        doc_type = d.get("kind", "text")
        chunks = chunk_text(d["text"])
        for i, ch in enumerate(chunks):
            chunk_count += 1
            vec = ollama_embed(ch)

            pid = stable_id(f"{rel_path}:{i}:{ch[:50]}")
            points.append({
                "id": pid,
                "vector": vec,
                "payload": {
                    "source": rel_path,
                    "page": page_num,
                    "doc_type": doc_type,
                    "chunk_index": i,
                    "text": ch
                }
            })

    # Upsert in batches to avoid huge payloads
    batch_size = 64
    for i in range(0, len(points), batch_size):
        qdrant_upsert(points[i:i+batch_size])

    return IngestResponse(
        files=len(unique_sources),
        doc_units=len(docs),
        chunks=chunk_count,
        collection=COLLECTION_NAME,
    )

@app.post("/ask")
def ask(req: AskRequest):
    return answer_question(req.question, req.top_k, req.debug)

@app.post("/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    result = answer_question(
        req.message,
        req.top_k,
        req.debug,
        req.strictness,
        req.min_semantic_score,
        req.max_sources,
        req.answer_style,
    )
    result["session_id"] = session_id
    return result

@app.get("/find")
def find(q: str, limit: int = 20):
    ensure_collection_ready()
    ql = q.lower()
    matches = []

    offset = None
    while True:
        body = {"limit": 256, "with_payload": True}
        if offset is not None:
            body["offset"] = offset

        try:
            r = requests.post(f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/scroll", json=body, timeout=60)
            r.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Failed to query Qdrant scroll endpoint: {exc}") from exc
        data = r.json().get("result", {})
        points = data.get("points", [])

        for p in points:
            payload = p.get("payload", {}) or {}
            txt = (payload.get("text") or "")
            if ql in txt.lower():
                src = payload.get("source", "unknown")
                page = payload.get("page", None)
                idx = payload.get("chunk_index", 0)
                cite = f"{src}#chunk:{idx}" if page is None else f"{src}#page:{page}:chunk:{idx}"
                matches.append({"citation": cite, "preview": txt[:300]})
                if len(matches) >= limit:
                    return {"query": q, "matches": matches}

        offset = data.get("next_page_offset")
        if offset is None:
            break

    return {"query": q, "matches": matches}

