"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --port 8000
In Docker the container serves the built frontend and the API on port 8000,
published on the host as APP_PORT (default 8080).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from .api import routes, ws
from .config import Settings, get_settings
from .runtime import Runtime


def create_app(env: Settings | None = None, *, configure_logs: bool = True) -> FastAPI:
    env = env or get_settings()
    runtime = Runtime(env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.startup(configure_logs=configure_logs)
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(title="Mission Mars — Lander Engineering Laboratory", version="1.0.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.include_router(routes.router)
    app.include_router(ws.router)

    static_dir = Path(env.static_dir)
    index = static_dir / "index.html"

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        # SPA fallback for non-API paths.
        if not request.url.path.startswith(("/api", "/ws")) and index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        detail = getattr(exc, "detail", "Not found")
        return JSONResponse({"detail": detail}, status_code=404)

    if static_dir.exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        async def root():
            if index.exists():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            return JSONResponse({"detail": "Frontend not built"}, status_code=404)

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
