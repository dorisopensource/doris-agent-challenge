from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import admin, chat, history, tools
from app.bus import Bus
from app.faults import Faults
from app.seed import load_seed
from app.settings import Settings
from app.store import Store

STATIC = Path(__file__).resolve().parents[1] / "static"


def create_app(settings: Settings, agent_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    app = FastAPI(title="Doris fake proxy")
    app.state.settings = settings
    app.state.seed = load_seed(settings.seed_dir, settings.image_base_url, settings.catalog_overrides_file)
    app.state.store = Store(settings.db_path)
    app.state.faults = Faults.load(settings.faults_file)
    app.state.bus = Bus()
    app.state.agent = httpx.AsyncClient(base_url=settings.agent_url, transport=agent_transport, timeout=None)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        payload = tools.error_body("invalid_request", str(exc.errors()))
        body = exc.body if isinstance(exc.body, dict) else {}
        cid = body.get("conversation_id")
        if request.url.path.startswith("/tools/") and isinstance(cid, str):
            store = app.state.store
            request_fields = {k: v for k, v in body.items() if k != "conversation_id"}
            store.log_call(cid, store.active_turn(cid), request.url.path.removeprefix("/tools/"), request_fields,
                           400, payload, 0)
        return JSONResponse(payload, status_code=400)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/users")
    async def users():
        return [{"user_id": u["user_id"], "name": u["name"]} for u in app.state.seed.users.values()]

    @app.get("/", include_in_schema=False)
    async def index():
        page = STATIC / "index.html"
        if not page.is_file():
            return JSONResponse(tools.error_body("not_found", "frontend ausente"), status_code=404)
        return FileResponse(page)

    app.include_router(tools.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(history.router)
    app.mount("/seed-images", StaticFiles(directory=settings.images_dir, check_dir=False), name="seed-images")
    return app


def build() -> FastAPI:
    return create_app(Settings.from_env())
