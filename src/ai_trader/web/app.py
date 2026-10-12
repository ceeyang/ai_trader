"""FastAPI 应用工厂与 uvicorn 入口。"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ai_trader.web.api import analysis, backtest, config, dca, market

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

    @app.exception_handler(ConnectionError)
    async def _connection_error(_: Request, exc: ConnectionError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(market.router)
    app.include_router(dca.router)
    app.include_router(analysis.router)
    app.include_router(backtest.router)
    app.include_router(config.router)

    static_dir = (DEFAULT_DIST_DIR if dist_dir is None else dist_dir).resolve()
    if static_dir.is_dir():
        index_file = static_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            """真实文件直接返回；其余路径（前端路由）回退到 index.html；/api/* 不回退。"""
            if path.startswith("api/") or path == "api":
                raise HTTPException(status_code=404)
            if not path:
                return FileResponse(index_file)
            candidate = (static_dir / path).resolve()
            if not candidate.is_relative_to(static_dir):
                raise HTTPException(status_code=404)
            if candidate.is_file():
                return FileResponse(candidate)
            if Path(path).suffix:  # 像文件的路径（/assets/x.js、/favicon.ico）缺失时 404，不回退
                raise HTTPException(status_code=404)
            return FileResponse(index_file)

    return app


def main() -> None:
    import uvicorn

    uvicorn.run("ai_trader.web.app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)
