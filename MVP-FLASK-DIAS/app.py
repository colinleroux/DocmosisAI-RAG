import glob
import hashlib
import os
import re
import uuid
from typing import Any, Dict, List

import pdfplumber
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="/static")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "dolphin3:latest")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "dais_docs_v3")
DOCS_PATH = os.getenv("DOCS_PATH", "/data/docs")


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@app.errorhandler(AppError)
def handle_app_error(err: AppError):
    return jsonify({"detail": err.message}), err.status_code


@app.errorhandler(Exception)
def handle_unexpected_error(err: Exception):
    return jsonify({"detail": f"Unexpected server error: {err}"}), 500


def _http_request(method: str, url: str, timeout: int, json_body: Dict[str, Any] = None):
    try:
        response = requests.request(method=method, url=url, json=json_body, timeout=timeout)
        return response
    except requests.exceptions.RequestException as exc:
        raise AppError(f"Upstream request failed for {url}: {exc}", 502) from exc


def ollama_embed(text: str) -> List[float]:
    r = _http_request(
        "POST",
        f"{OLLAMA_BASE_URL}/api/embeddings",
        timeout=120,
        json_body={"model": EMBED_MODEL, "prompt": text},
    )
    if r.status_code != 200:
        raise AppError(f"Ollama embeddings failed: {r.text}", 500)
    data = r.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise AppError("Ollama embeddings response did not include an embedding vector.", 500)
    return embedding


def ollama_generate(prompt: str) -> str:
    r = _http_request(
        "POST",
        f"{OLLAMA_BASE_URL}/api/generate",
        timeout=300,
        json_body={"model": MODEL_NAME, "prompt": prompt, "stream": False},
    )
    if r.status_code != 200:
        raise AppError(f"Ollama generate failed: {r.text}", 500)
    return (r.json().get("response") or "").strip()


def ollama_pull_model(model_name: str) -> Dict[str, Any]:
    model_name = (model_name or "").strip()
    if not model_name:
        raise AppError("Model name is required for pull.", 400)

    r = _http_request(
        "POST",
        f"{OLLAMA_BASE_URL}/api/pull",
        timeout=1200,
        json_body={"name": model_name, "stream": False},
    )
    if r.status_code != 200:
        raise AppError(f"Ollama pull failed for {model_name}: {r.text}", 500)

    data = r.json() if r.text else {}
    return {"model": model_name, "status": data.get("status", "ok")}


def ensure_required_models() -> Dict[str, Any]:
    embed_result = ollama_pull_model(EMBED_MODEL)
    gen_result = ollama_pull_model(MODEL_NAME)
    return {"embedding": embed_result, "generation": gen_result}


def qdrant_collection_exists() -> bool:
    r = _http_request("GET", f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=30)
    return r.status_code == 200


def qdrant_create_collection(vector_size: int) -> None:
    payload = {"vectors": {"size": vector_size, "distance": "Cosine"}}
    r = _http_request("PUT", f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=60, json_body=payload)
    if r.status_code not in (200, 201):
        raise AppError(f"Create collection failed: {r.text}", 500)


def qdrant_upsert(points: List[Dict[str, Any]]) -> None:
    r = _http_request(
        "PUT",
        f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points?wait=true",
        timeout=300,
        json_body={"points": points},
    )
    if r.status_code != 200:
        raise AppError(f"Upsert failed: {r.text}", 500)


def qdrant_search(vector: List[float], limit: int) -> List[Dict[str, Any]]:
    payload = {"vector": vector, "limit": limit, "with_payload": True}
    r = _http_request(
        "POST",
        f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/search",
        timeout=60,
        json_body=payload,
    )
    if r.status_code != 200:
        raise AppError(f"Search failed: {r.text}", 500)
    return r.json().get("result", [])


def qdrant_scroll(limit: int = 256, with_payload: bool = True):
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": limit, "with_payload": with_payload}
        if offset is not None:
            body["offset"] = offset
        r = _http_request(
            "POST",
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/scroll",
            timeout=60,
            json_body=body,
        )
        if r.status_code != 200:
            raise AppError(f"Failed to query Qdrant scroll endpoint: {r.text}", 502)
        data = r.json().get("result", {})
        points = data.get("points", [])
        for p in points:
            yield p
        offset = data.get("next_page_offset")
        if offset is None:
            break


def read_docs(docs_path: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []

    for ext in ("txt", "md"):
        pattern = os.path.join(docs_path, f"**/*.{ext}")
        for fp in glob.glob(pattern, recursive=True):
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    files.append({"path": fp, "text": f.read(), "kind": "text", "page": None})
            except Exception:
                continue

    pdf_pattern = os.path.join(docs_path, "**/*.pdf")
    for fp in glob.glob(pdf_pattern, recursive=True):
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
    chunks: List[str] = []
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


def stable_id(text: str) -> int:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(h[:15], 16)


def ensure_collection_ready() -> None:
    if qdrant_collection_exists():
        return
    vec = ollama_embed("dimension check")
    qdrant_create_collection(vector_size=len(vec))


def keyword_boost(payload: Dict[str, Any], question: str) -> int:
    text = (payload.get("text") or "").lower()
    terms = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", question)]

    score = 0
    for t in terms:
        if t in text:
            score += 50

    for t in terms:
        if len(t) >= 10 and (t[:6] in text or t[-6:] in text):
            score += 5

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

    if any(x in text for x in ("status service", "response body", "convertercount", "uptimeseconds", "/status", "/ping")):
        score -= 40

    return score


def rerank_score(hit: Dict[str, Any], question: str) -> float:
    semantic = float(hit.get("score", 0.0) or 0.0)
    lexical = float(keyword_boost(hit.get("payload", {}) or {}, question))
    return (semantic * 100.0) + lexical


def parse_chat_options(body: Dict[str, Any]) -> Dict[str, Any]:
    top_k = int(body.get("top_k", 5))
    if top_k < 1 or top_k > 20:
        raise AppError("top_k must be between 1 and 20.", 400)

    max_sources = int(body.get("max_sources", 5))
    if max_sources < 1 or max_sources > 12:
        raise AppError("max_sources must be between 1 and 12.", 400)

    min_semantic_score = float(body.get("min_semantic_score", 0.35))
    if min_semantic_score < 0 or min_semantic_score > 1:
        raise AppError("min_semantic_score must be between 0.0 and 1.0.", 400)

    strictness = str(body.get("strictness", "balanced"))
    if strictness not in ("balanced", "strict"):
        raise AppError("strictness must be 'balanced' or 'strict'.", 400)

    answer_style = str(body.get("answer_style", "auto"))
    if answer_style not in ("auto", "concise", "detailed", "steps", "parameters"):
        raise AppError("answer_style must be one of auto, concise, detailed, steps, parameters.", 400)

    reasoning_mode = str(body.get("reasoning_mode", "grounded"))
    if reasoning_mode not in ("grounded", "reasoned"):
        raise AppError("reasoning_mode must be 'grounded' or 'reasoned'.", 400)

    return {
        "top_k": top_k,
        "max_sources": max_sources,
        "min_semantic_score": min_semantic_score,
        "strictness": strictness,
        "answer_style": answer_style,
        "reasoning_mode": reasoning_mode,
        "debug": bool(body.get("debug", True)),
    }


def answer_question(
    question: str,
    top_k: int,
    debug: bool,
    strictness: str,
    min_semantic_score: float,
    max_sources: int,
    answer_style: str,
    reasoning_mode: str,
) -> Dict[str, Any]:
    ensure_collection_ready()

    qvec = ollama_embed(question)
    raw_hits = qdrant_search(qvec, limit=max(top_k * 10, 50))
    top_semantic = max((float(h.get("score", 0.0) or 0.0) for h in raw_hits), default=0.0)

    if strictness == "strict" and top_semantic < min_semantic_score:
        response = {
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
            response["retrieved"] = []
        return response

    raw_hits.sort(key=lambda h: rerank_score(h, question), reverse=True)
    hits = raw_hits[:top_k]

    context_blocks: List[str] = []
    citations: List[str] = []
    sources: List[Dict[str, Any]] = []
    debug_hits: List[Dict[str, Any]] = []
    seen = set()

    for h in hits:
        if len(citations) >= max_sources:
            break

        payload = h.get("payload", {}) or {}
        src = payload.get("source", "unknown")
        page = payload.get("page")
        idx = payload.get("chunk_index", 0)
        txt = (payload.get("text") or "")
        semantic_score = float(h.get("score", 0.0) or 0.0)

        if strictness == "strict" and semantic_score < min_semantic_score:
            continue

        cite = f"{src}#chunk:{idx}" if page is None else f"{src}#page:{page}:chunk:{idx}"
        if cite in seen:
            continue
        seen.add(cite)

        preview = (txt[:400] + "...") if len(txt) > 400 else txt
        citations.append(cite)
        context_blocks.append(f"[{cite}]\n{txt}")
        sources.append(
            {
                "citation": cite,
                "doc": src,
                "page": page,
                "chunk": idx,
                "semantic_score": round(semantic_score, 4),
                "label": f"{src} (p.{page})" if page is not None else src,
                "preview": preview,
            }
        )
        debug_hits.append({"citation": cite, "preview": preview})

    if strictness == "strict" and not context_blocks:
        response = {
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
            response["retrieved"] = []
        return response

    is_parameter_query = bool(
        re.search(r"\b(parameter|parameters|param|params|option|options|argument|arguments|names only)\b", question, flags=re.IGNORECASE)
    )

    reasoning_applied = reasoning_mode == "reasoned" and len(context_blocks) >= 2 and top_semantic >= max(min_semantic_score, 0.35)

    system_rules = (
        "You are DaiS (Docmosis AI Support), an internal support assistant.\n"
        "Answer using ONLY the documentation context provided.\n"
        "Do NOT use prior knowledge.\n"
        "If the answer is not supported by the provided context, say: 'Not found in provided documentation context.'.\n"
        "Use citations exactly as shown in the context labels, e.g. [file#page:X:chunk:Y].\n"
        "Every claim must include at least one citation in square brackets like [file#page:X:chunk:Y].\n"
        "Be concise and practical.\n"
    )

    if reasoning_applied:
        system_rules += (
            "You may infer practical conclusions only when they are strongly supported by multiple context snippets.\n"
            "Mark inferred statements with the prefix 'Inference:'.\n"
            "Each inferred statement must cite at least two sources.\n"
            "If evidence is insufficient, explicitly say there is not enough context rather than guessing.\n"
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
    response = {
        "answer": answer,
        "citations": citations,
        "sources": sources,
        "meta": {
            "strictness": strictness,
            "top_semantic_score": round(top_semantic, 4),
            "threshold": min_semantic_score,
            "answer_style": answer_style,
            "max_sources": max_sources,
            "reasoning_mode_requested": reasoning_mode,
            "reasoning_applied": reasoning_applied,
        },
    }
    if debug:
        response["retrieved"] = debug_hits
    return response


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "model": MODEL_NAME,
            "embed_model": EMBED_MODEL,
            "collection": COLLECTION_NAME,
            "framework": "flask",
        }
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/setup-models")
def setup_models():
    result = ensure_required_models()
    return jsonify(
        {
            "ok": True,
            "embed_model": EMBED_MODEL,
            "model_name": MODEL_NAME,
            "pulled": result,
        }
    )


@app.get("/ingested-docs")
def ingested_docs():
    if not qdrant_collection_exists():
        return jsonify({"collection": COLLECTION_NAME, "docs": [], "count": 0})

    docs_map: Dict[str, Dict[str, Any]] = {}
    for p in qdrant_scroll(limit=512, with_payload=True):
        payload = p.get("payload", {}) or {}
        source = payload.get("source")
        if not source:
            continue
        page = payload.get("page")
        entry = docs_map.setdefault(source, {"source": source, "chunks": 0, "pages": set()})
        entry["chunks"] += 1
        if isinstance(page, int):
            entry["pages"].add(page)

    docs = []
    for _, v in docs_map.items():
        pages = sorted(v["pages"])
        docs.append(
            {
                "source": v["source"],
                "chunks": v["chunks"],
                "pages": pages,
                "page_count": len(pages),
            }
        )

    docs.sort(key=lambda d: d["source"].lower())
    return jsonify({"collection": COLLECTION_NAME, "docs": docs, "count": len(docs)})


@app.post("/ingest")
def ingest():
    ensure_collection_ready()
    docs = read_docs(DOCS_PATH)
    if not docs:
        raise AppError(f"No .txt or .md or .pdf files found under {DOCS_PATH}.", 400)

    points: List[Dict[str, Any]] = []
    chunk_count = 0
    unique_sources = set()

    for d in docs:
        rel_path = d["path"].replace(DOCS_PATH, "").lstrip("/\\")
        unique_sources.add(rel_path)
        page_num = d.get("page")
        doc_type = d.get("kind", "text")

        for i, ch in enumerate(chunk_text(d["text"])):
            chunk_count += 1
            vec = ollama_embed(ch)
            pid = stable_id(f"{rel_path}:{i}:{ch[:50]}")
            points.append(
                {
                    "id": pid,
                    "vector": vec,
                    "payload": {
                        "source": rel_path,
                        "page": page_num,
                        "doc_type": doc_type,
                        "chunk_index": i,
                        "text": ch,
                    },
                }
            )

    for i in range(0, len(points), 64):
        qdrant_upsert(points[i : i + 64])

    return jsonify(
        {
            "files": len(unique_sources),
            "doc_units": len(docs),
            "chunks": chunk_count,
            "collection": COLLECTION_NAME,
        }
    )


@app.post("/ask")
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        raise AppError("question is required.", 400)

    opts = parse_chat_options(
        {
            "top_k": body.get("top_k", 5),
            "debug": body.get("debug", False),
            "strictness": body.get("strictness", "balanced"),
            "min_semantic_score": body.get("min_semantic_score", 0.35),
            "max_sources": body.get("max_sources", 5),
            "answer_style": body.get("answer_style", "auto"),
            "reasoning_mode": body.get("reasoning_mode", "grounded"),
        }
    )

    return jsonify(
        answer_question(
            question,
            opts["top_k"],
            opts["debug"],
            opts["strictness"],
            opts["min_semantic_score"],
            opts["max_sources"],
            opts["answer_style"],
            opts["reasoning_mode"],
        )
    )


@app.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        raise AppError("message is required.", 400)

    session_id = (body.get("session_id") or "").strip() or str(uuid.uuid4())
    opts = parse_chat_options(body)

    result = answer_question(
        message,
        opts["top_k"],
        opts["debug"],
        opts["strictness"],
        opts["min_semantic_score"],
        opts["max_sources"],
        opts["answer_style"],
        opts["reasoning_mode"],
    )
    result["session_id"] = session_id
    return jsonify(result)


@app.get("/find")
def find():
    ensure_collection_ready()

    query = (request.args.get("q") or "").strip()
    if not query:
        raise AppError("q is required.", 400)

    limit = int(request.args.get("limit", 20))
    if limit < 1:
        raise AppError("limit must be >= 1.", 400)

    ql = query.lower()
    matches: List[Dict[str, Any]] = []

    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 256, "with_payload": True}
        if offset is not None:
            body["offset"] = offset

        r = _http_request(
            "POST",
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/scroll",
            timeout=60,
            json_body=body,
        )
        if r.status_code != 200:
            raise AppError(f"Failed to query Qdrant scroll endpoint: {r.text}", 502)

        data = r.json().get("result", {})
        points = data.get("points", [])

        for p in points:
            payload = p.get("payload", {}) or {}
            txt = payload.get("text") or ""
            if ql in txt.lower():
                src = payload.get("source", "unknown")
                page = payload.get("page")
                idx = payload.get("chunk_index", 0)
                cite = f"{src}#chunk:{idx}" if page is None else f"{src}#page:{page}:chunk:{idx}"
                matches.append({"citation": cite, "preview": txt[:300]})
                if len(matches) >= limit:
                    return jsonify({"query": query, "matches": matches})

        offset = data.get("next_page_offset")
        if offset is None:
            break

    return jsonify({"query": query, "matches": matches})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=False)
