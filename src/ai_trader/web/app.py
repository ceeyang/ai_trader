"""FastAPI 应用工厂与 uvicorn 入口。"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIST_DIR = REPO_ROOT / "frontend" / "dist"


def create_app(dist_dir: Optional[Path] = None) -> FastAPI:
    """创建应用。dist_dir 存在时在 / 托管构建好的前端（必须在 API 路由之后挂载）。"""
    app = FastAPI(title="AI Trader Web", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    static_dir = DEFAULT_DIST_DIR if dist_dir is None else dist_dir
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
    return app


def main() -> None:
    import uvicorn

    uvicorn.run("ai_trader.web.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)
