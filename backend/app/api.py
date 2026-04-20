from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from app.agents.agent import LegalWorkflowAgent
from app.config import get_settings
from app.services.llm_service import get_llm


def _resolve_markdown_file() -> str:
    law_dir = Path(__file__).resolve().parents[2] / "law"
    preferred_files = [
        law_dir / "民法典_最终正确版.md",
        law_dir / "民法典_最终正确版(all).md",
    ]
    for path in preferred_files:
        if path.exists():
            return str(path)

    fallback = next(law_dir.glob("*.md"), None)
    if fallback is None:
        raise FileNotFoundError(f"未在 {law_dir} 找到任何 Markdown 法律知识库文件")
    return str(fallback)


def _log(stage: str, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[API][{timestamp}][{stage}] {message}")


settings = get_settings()
app = Flask(__name__)
agent = LegalWorkflowAgent(
    llm=get_llm(),
    markdown_file_path=_resolve_markdown_file(),
)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    allowed = settings.get_cors_origins_list()
    if origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
    elif "null" in allowed:
        response.headers["Access-Control-Allow-Origin"] = "null"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "llm_enabled": agent.llm is not None,
        }
    )


@app.route("/", methods=["GET"])
def frontend_index():
    return send_from_directory(FRONTEND_DIR, "analyze.html")


@app.route("/<path:filename>", methods=["GET"])
def frontend_assets(filename: str):
    if filename in {"analyze.css", "analyze.js"}:
        return send_from_directory(FRONTEND_DIR, filename)
    return ("Not Found", 404)


@app.route("/api/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    state = payload.get("state")
    # auto_load_kb = bool(payload.get("auto_load_kb", True))
    auto_load_kb = False
    if not text:
        return jsonify({"error": "text 不能为空"}), 400

    try:
        _log("analyze", f"收到请求, text={text[:80]}")
        result = agent.run(
            user_text=text,
            state=state,
            auto_load_kb=auto_load_kb,
            top_k=int(payload.get("top_k", 5)),
            enable_mqe=bool(payload.get("enable_mqe", True)),
            mqe_count=int(payload.get("mqe_count", 3)),
            enable_hyde=bool(payload.get("enable_hyde", True)),
        )
        _log("analyze", f"请求处理完成, status={result.get('status')}")
        return jsonify(result)
    except Exception as exc:
        _log("error", str(exc))
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
