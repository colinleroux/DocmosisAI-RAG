import json
from pathlib import Path

from flask import Blueprint, current_app, render_template

web_bp = Blueprint("web", __name__)


def _read_manifest() -> dict:
    manifest_path = Path(current_app.static_folder) / "dist" / ".vite" / "manifest.json"
    if not manifest_path.exists():
        return {}

    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_assets() -> tuple[str, str]:
    manifest = _read_manifest()
    entry = manifest.get("src/main.js") or manifest.get("app") or {}

    js_file = entry.get("file", "app.js")
    css_files = entry.get("css") or []
    css_file = css_files[0] if css_files else "app.css"

    return f"dist/{css_file}", f"dist/{js_file}"


@web_bp.get("/")
def index():
    use_vite_dev = current_app.config.get("FRONTEND_USE_VITE_DEV", False)
    app_css, app_js = _resolve_assets()
    return render_template(
        "index.html",
        use_vite_dev=use_vite_dev,
        vite_dev_server=current_app.config.get("VITE_DEV_SERVER", "http://localhost:5173"),
        app_css=app_css,
        app_js=app_js,
    )
