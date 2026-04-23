import glob
import hashlib
import json
import os
import re
from typing import Any, Dict, Iterator, List

import pdfplumber
import requests

from dais_app.errors import AppError


def _http_request(method: str, url: str, timeout: int, json_body: Dict[str, Any] = None):
    try:
        return requests.request(method=method, url=url, json=json_body, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise AppError(f"Upstream request failed for {url}: {exc}", 502) from exc


def _is_model_not_found_error(response_text: str, model_name: str) -> bool:
    text = (response_text or "").lower()
    model = (model_name or "").strip().lower()
    if not text or not model:
        return False
    return "not found" in text and model in text


def ollama_embed(text: str, cfg: Dict[str, Any]) -> List[float]:
    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/embeddings",
        timeout=120,
        json_body={"model": cfg["EMBED_MODEL"], "prompt": text},
    )
    if response.status_code != 200:
        if _is_model_not_found_error(response.text, cfg["EMBED_MODEL"]):
            ollama_pull_model(cfg["EMBED_MODEL"], cfg)
            retry = _http_request(
                "POST",
                f"{cfg['OLLAMA_BASE_URL']}/api/embeddings",
                timeout=120,
                json_body={"model": cfg["EMBED_MODEL"], "prompt": text},
            )
            if retry.status_code != 200:
                raise AppError(f"Ollama embeddings failed after auto-pull: {retry.text}", 500)
            response = retry
        else:
            raise AppError(f"Ollama embeddings failed: {response.text}", 500)

    data = response.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise AppError("Ollama embeddings response did not include an embedding vector.", 500)
    return embedding


def ollama_generate(prompt: str, cfg: Dict[str, Any]) -> str:
    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/generate",
        timeout=300,
        json_body={"model": cfg["MODEL_NAME"], "prompt": prompt, "stream": False},
    )
    if response.status_code != 200:
        if _is_model_not_found_error(response.text, cfg["MODEL_NAME"]):
            ollama_pull_model(cfg["MODEL_NAME"], cfg)
            retry = _http_request(
                "POST",
                f"{cfg['OLLAMA_BASE_URL']}/api/generate",
                timeout=300,
                json_body={"model": cfg["MODEL_NAME"], "prompt": prompt, "stream": False},
            )
            if retry.status_code != 200:
                raise AppError(f"Ollama generate failed after auto-pull: {retry.text}", 500)
            response = retry
        else:
            raise AppError(f"Ollama generate failed: {response.text}", 500)
    return (response.json().get("response") or "").strip()


def ollama_pull_model(model_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    model_name = (model_name or "").strip()
    if not model_name:
        raise AppError("Model name is required for pull.", 400)

    response = _http_request(
        "POST",
        f"{cfg['OLLAMA_BASE_URL']}/api/pull",
        timeout=1200,
        json_body={"name": model_name, "stream": False},
    )
    if response.status_code != 200:
        raise AppError(f"Ollama pull failed for {model_name}: {response.text}", 500)

    data = response.json() if response.text else {}
    return {"model": model_name, "status": data.get("status", "ok")}


def ensure_required_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    embed_result = ollama_pull_model(cfg["EMBED_MODEL"], cfg)
    gen_result = ollama_pull_model(cfg["MODEL_NAME"], cfg)
    return {"embedding": embed_result, "generation": gen_result}


def iter_model_pull_progress(model_name: str, cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    model_name = (model_name or "").strip()
    if not model_name:
        raise AppError("Model name is required for pull.", 400)

    url = f"{cfg['OLLAMA_BASE_URL']}/api/pull"
    try:
        response = requests.post(url, json={"name": model_name, "stream": True}, timeout=1800, stream=True)
    except requests.exceptions.RequestException as exc:
        raise AppError(f"Ollama pull failed for {model_name}: {exc}", 502) from exc

    if response.status_code != 200:
        raise AppError(f"Ollama pull failed for {model_name}: {response.text}", 500)

    last_percent = 0.0
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue

        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        completed = item.get("completed")
        total = item.get("total")
        percent = last_percent
        if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and total > 0:
            percent = max(0.0, min(100.0, (float(completed) / float(total)) * 100.0))
            last_percent = percent

        yield {
            "model": model_name,
            "status": item.get("status", "pulling"),
            "completed": completed,
            "total": total,
            "percent": round(percent, 1),
        }


def iter_required_models_progress(cfg: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    models = [
        ("embedding", cfg["EMBED_MODEL"]),
        ("generation", cfg["MODEL_NAME"]),
    ]
    total_models = len(models)

    for index, (kind, model_name) in enumerate(models):
        for update in iter_model_pull_progress(model_name, cfg):
            model_percent = float(update.get("percent", 0.0) or 0.0)
            overall_percent = ((index + (model_percent / 100.0)) / total_models) * 100.0
            yield {
                "model_type": kind,
                "model": model_name,
                "status": update.get("status", "pulling"),
                "completed": update.get("completed"),
                "total": update.get("total"),
                "model_percent": round(model_percent, 1),
                "overall_percent": round(overall_percent, 1),
            }

def qdrant_collection_exists(cfg: Dict[str, Any]) -> bool:
    response = _http_request("GET", f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}", timeout=30)
    return response.status_code == 200


def qdrant_create_collection(vector_size: int, cfg: Dict[str, Any]) -> None:
    payload = {"vectors": {"size": vector_size, "distance": "Cosine"}}
    response = _http_request(
        "PUT",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}",
        timeout=60,
        json_body=payload,
    )
    if response.status_code not in (200, 201):
        raise AppError(f"Create collection failed: {response.text}", 500)


def qdrant_upsert(points: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    response = _http_request(
        "PUT",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points?wait=true",
        timeout=300,
        json_body={"points": points},
    )
    if response.status_code != 200:
        raise AppError(f"Upsert failed: {response.text}", 500)


def qdrant_search(vector: List[float], limit: int, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = {"vector": vector, "limit": limit, "with_payload": True}
    response = _http_request(
        "POST",
        f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/search",
        timeout=60,
        json_body=payload,
    )
    if response.status_code != 200:
        raise AppError(f"Search failed: {response.text}", 500)
    return response.json().get("result", [])


def qdrant_scroll(cfg: Dict[str, Any], limit: int = 256, with_payload: bool = True) -> Iterator[Dict[str, Any]]:
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": limit, "with_payload": with_payload}
        if offset is not None:
            body["offset"] = offset

        response = _http_request(
            "POST",
            f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/scroll",
            timeout=60,
            json_body=body,
        )
        if response.status_code != 200:
            raise AppError(f"Failed to query Qdrant scroll endpoint: {response.text}", 502)

        data = response.json().get("result", {})
        for point in data.get("points", []):
            yield point

        offset = data.get("next_page_offset")
        if offset is None:
            break


def read_docs(docs_path: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []

    for ext in ("txt", "md"):
        pattern = os.path.join(docs_path, f"**/*.{ext}")
        for file_path in glob.glob(pattern, recursive=True):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    files.append({"path": file_path, "text": f.read(), "kind": "text", "page": None})
            except Exception:
                continue

    pdf_pattern = os.path.join(docs_path, "**/*.pdf")
    for file_path in glob.glob(pdf_pattern, recursive=True):
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    txt = (page.extract_text() or "").strip()
                    if txt:
                        files.append({"path": file_path, "text": txt, "kind": "pdf", "page": page_num})
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
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def ensure_collection_ready(cfg: Dict[str, Any]) -> None:
    if qdrant_collection_exists(cfg):
        return
    vec = ollama_embed("dimension check", cfg)
    qdrant_create_collection(vector_size=len(vec), cfg=cfg)


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


def _parse_int(raw: Any, field_name: str, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise AppError(f"{field_name} must be an integer.", 400)
    if value < min_value or value > max_value:
        raise AppError(f"{field_name} must be between {min_value} and {max_value}.", 400)
    return value


def _parse_float(raw: Any, field_name: str, min_value: float, max_value: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AppError(f"{field_name} must be a number.", 400)
    if value < min_value or value > max_value:
        raise AppError(f"{field_name} must be between {min_value} and {max_value}.", 400)
    return value


def parse_chat_options(body: Dict[str, Any]) -> Dict[str, Any]:
    top_k = _parse_int(body.get("top_k", 5), "top_k", 1, 20)
    max_sources = _parse_int(body.get("max_sources", 5), "max_sources", 1, 12)
    min_semantic_score = _parse_float(body.get("min_semantic_score", 0.35), "min_semantic_score", 0.0, 1.0)

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
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    ensure_collection_ready(cfg)

    qvec = ollama_embed(question, cfg)
    raw_hits = qdrant_search(qvec, limit=max(top_k * 10, 50), cfg=cfg)
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

    answer = ollama_generate(prompt, cfg)
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


def ingest_docs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    ensure_collection_ready(cfg)
    docs = read_docs(cfg["DOCS_PATH"])
    if not docs:
        raise AppError(f"No .txt or .md or .pdf files found under {cfg['DOCS_PATH']}.", 400)

    points: List[Dict[str, Any]] = []
    chunk_count = 0
    unique_sources = set()

    for d in docs:
        rel_path = d["path"].replace(cfg["DOCS_PATH"], "").lstrip("/\\")
        unique_sources.add(rel_path)
        page_num = d.get("page")
        doc_type = d.get("kind", "text")

        for i, ch in enumerate(chunk_text(d["text"])):
            chunk_count += 1
            vec = ollama_embed(ch, cfg)
            pid = stable_id(f"{rel_path}:{doc_type}:{page_num}:{i}:{hashlib.sha1(ch.encode('utf-8')).hexdigest()}")
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
        qdrant_upsert(points[i : i + 64], cfg)

    return {
        "files": len(unique_sources),
        "doc_units": len(docs),
        "chunks": chunk_count,
        "collection": cfg["COLLECTION_NAME"],
    }


def list_ingested_docs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not qdrant_collection_exists(cfg):
        return {"collection": cfg["COLLECTION_NAME"], "docs": [], "count": 0}

    docs_map: Dict[str, Dict[str, Any]] = {}
    for p in qdrant_scroll(cfg=cfg, limit=512, with_payload=True):
        payload = p.get("payload", {}) or {}
        source = payload.get("source")
        if not source:
            continue

        page = payload.get("page")
        entry = docs_map.setdefault(source, {"source": source, "chunks": 0, "pages": set()})
        entry["chunks"] += 1
        if isinstance(page, int):
            entry["pages"].add(page)

    docs: List[Dict[str, Any]] = []
    for _, val in docs_map.items():
        pages = sorted(val["pages"])
        docs.append(
            {
                "source": val["source"],
                "chunks": val["chunks"],
                "pages": pages,
                "page_count": len(pages),
            }
        )

    docs.sort(key=lambda d: d["source"].lower())
    return {"collection": cfg["COLLECTION_NAME"], "docs": docs, "count": len(docs)}


def find_in_docs(query: str, limit: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    ensure_collection_ready(cfg)

    if not query:
        raise AppError("q is required.", 400)

    safe_limit = _parse_int(limit, "limit", 1, 200)

    ql = query.lower()
    matches: List[Dict[str, Any]] = []

    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 256, "with_payload": True}
        if offset is not None:
            body["offset"] = offset

        response = _http_request(
            "POST",
            f"{cfg['QDRANT_URL']}/collections/{cfg['COLLECTION_NAME']}/points/scroll",
            timeout=60,
            json_body=body,
        )
        if response.status_code != 200:
            raise AppError(f"Failed to query Qdrant scroll endpoint: {response.text}", 502)

        data = response.json().get("result", {})
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
                if len(matches) >= safe_limit:
                    return {"query": query, "matches": matches}

        offset = data.get("next_page_offset")
        if offset is None:
            break

    return {"query": query, "matches": matches}
