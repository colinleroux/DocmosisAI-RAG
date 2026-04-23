import uuid
import json

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from dais_app.errors import AppError
from dais_app.services.rag import (
    answer_question,
    ensure_required_models,
    find_in_docs,
    ingest_docs,
    iter_required_models_progress,
    list_ingested_docs,
    parse_chat_options,
)

api_bp = Blueprint("api", __name__)


def _cfg():
    return current_app.config


@api_bp.get("/health")
def health():
    cfg = _cfg()
    return jsonify(
        {
            "status": "ok",
            "model": cfg["MODEL_NAME"],
            "embed_model": cfg["EMBED_MODEL"],
            "collection": cfg["COLLECTION_NAME"],
            "framework": "flask",
        }
    )


@api_bp.post("/setup-models")
def setup_models():
    cfg = _cfg()
    result = ensure_required_models(cfg)
    return jsonify(
        {
            "ok": True,
            "embed_model": cfg["EMBED_MODEL"],
            "model_name": cfg["MODEL_NAME"],
            "pulled": result,
        }
    )


@api_bp.get("/setup-models/stream")
def setup_models_stream():
    cfg = _cfg()

    @stream_with_context
    def event_stream():
        yield "event: start\ndata: {\"ok\": true}\n\n"
        try:
            for update in iter_required_models_progress(cfg):
                yield f"event: progress\ndata: {json.dumps(update)}\n\n"
            done_payload = {
                "ok": True,
                "embed_model": cfg["EMBED_MODEL"],
                "model_name": cfg["MODEL_NAME"],
            }
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
        except AppError as exc:
            fail_payload = {"ok": False, "detail": exc.message}
            yield f"event: failed\ndata: {json.dumps(fail_payload)}\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_bp.get("/ingested-docs")
def ingested_docs():
    return jsonify(list_ingested_docs(_cfg()))


@api_bp.post("/ingest")
def ingest():
    return jsonify(ingest_docs(_cfg()))


@api_bp.post("/ask")
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
            _cfg(),
        )
    )


@api_bp.post("/chat")
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
        _cfg(),
    )
    result["session_id"] = session_id
    return jsonify(result)


@api_bp.get("/find")
def find():
    query = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 20)
    return jsonify(find_in_docs(query=query, limit=limit, cfg=_cfg()))
