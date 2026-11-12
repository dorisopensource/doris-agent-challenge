"""Fake Doris tool endpoints. Same envelope and identity-by-conversation_id as the real agent-proxy."""
import asyncio
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.search import search
from app.seed import persona_of

router = APIRouter(prefix="/tools")

LATENCY = {
    "search_by_text": (0.5, 1.0), "garment_creation": (3.0, 5.0), "tryon": (8.0, 12.0),
    "avatar": (0.0, 0.3), "looks": (0.0, 0.3), "wardrobe": (0.0, 0.3),
    "show_artifact": (0.0, 0.1),
}


class ToolError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def error_body(code: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


def _uuid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class Base(BaseModel):
    conversation_id: str


class SearchIn(Base):
    query: str
    limit: int = 6


class GarmentIn(Base):
    search_item_id: str
    type: str | None = None
    category: str | None = None


class TryonIn(Base):
    garment_ids: list[str]
    avatar_pose: Literal["NORMAL"] = "NORMAL"


class LooksIn(Base):
    limit: int = 20


class WardrobeIn(Base):
    garment_types: list[str] | None = None


class ShowIn(Base):
    type: Literal["PRODUCT", "GARMENT", "TRYON_CARD"]
    value: str


# ── garment resolution shared by tryon, fault matching and artifacts ───────────

def _wardrobe(st, user: str) -> dict[str, dict]:
    return {g["garment_id"]: g for g in st.seed.wardrobe.get(persona_of(user), [])}


def resolve_garment(st, user: str, garment_id: str) -> str | None:
    """Return the render key (catalog item id or wardrobe garment id) behind a garment id."""
    created = st.store.get_garment(user, garment_id)
    if created:
        return created["item_id"]
    return garment_id if garment_id in _wardrobe(st, user) else None


def _tags(st, user: str, key: str) -> list[str]:
    if key in st.seed.catalog:
        return list(st.seed.catalog[key]["tags"])
    return list(_wardrobe(st, user).get(key, {}).get("tags", []))


def _fault_fields(st, user: str, tool: str, req: dict) -> dict:
    if tool == "garment_creation":
        return {**req, "item_ids": [req["search_item_id"]]}
    if tool == "tryon":
        return {**req, "item_ids": [resolve_garment(st, user, g) or g for g in req["garment_ids"]]}
    return req


# ── runner: identity → faults → latency → handler → log ───────────────────────

async def run_tool(request: Request, tool: str, body: Base, handler: Callable) -> JSONResponse:
    st = request.app.state
    cid = body.conversation_id
    req = body.model_dump(exclude={"conversation_id"})
    t0 = time.monotonic()
    turn_id = st.store.active_turn(cid)  # the turn the call started in, even if it ends first
    user = st.store.user_of(cid)
    if user is None:
        status, payload = 404, error_body("conversation_not_found", f"conversa {cid} não encontrada")
    else:
        effect = st.faults.check(tool, _fault_fields(st, user, tool, req), cid)
        await asyncio.sleep(random.uniform(*LATENCY[tool]) * st.settings.latency_scale + effect.delay_ms / 1000)
        if effect.kind == "error":
            status, payload = effect.status, error_body(effect.code, "falha simulada no serviço", effect.retryable)
        else:
            try:
                status, payload = 200, handler(st, user, cid, req, effect.kind == "empty")
            except ToolError as e:
                status, payload = e.status, error_body(e.code, e.message, e.retryable)
    st.store.log_call(cid, turn_id, tool, req, status, payload,
                      int((time.monotonic() - t0) * 1000))
    return JSONResponse(payload, status_code=status)


def ok(data: dict) -> dict:
    return {"ok": True, "data": data}


# ── handlers ──────────────────────────────────────────────────────────────────

def h_search(st, user, cid, req, empty):
    if empty:
        return ok({"products": []})
    found = search(st.seed.catalog, req["query"], max(1, min(12, req["limit"])))
    keys = ("name", "store", "price", "currency_code", "currency_symbol", "url", "image_url", "description")
    return ok({"products": [{"search_item_id": p["id"], "order": i, **{k: p[k] for k in keys}}
                            for i, p in enumerate(found)]})


def h_garment(st, user, cid, req, empty):
    item = st.seed.catalog.get(req["search_item_id"])
    if item is None:
        raise ToolError(422, "not_found", f"item {req['search_item_id']} não encontrado")
    garment_id = _uuid(f"{user}:{item['id']}")
    st.store.add_garment(user, garment_id, item["id"])
    return ok({"garment_id": garment_id, "ghost_image_url": item["ghost_image_url"], "type": item["type"],
               "category": item["category"], "status": "PROCESSED", "metadata": {}})


def h_tryon(st, user, cid, req, empty):
    if len(req["garment_ids"]) != 1:
        raise ToolError(400, "unsupported_combination", "esta versão do try-on aceita exatamente uma peça")
    garment_id = req["garment_ids"][0]
    key = resolve_garment(st, user, garment_id)
    if key is None:
        raise ToolError(422, "not_found", f"peça {garment_id} não encontrada")
    persona = persona_of(user)
    tryon_id = _uuid(f"{user}:{garment_id}")
    record = {"tryon_id": tryon_id, "look_id": _uuid(f"look:{tryon_id}"), "garment_ids": [garment_id],
              "image_url": st.seed.renders[persona][key],
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    st.store.add_tryon(user, record)
    return ok({**record, "status": "PROCESSED", "avatar_id": f"avatar_{persona}", "avatar_pose": "NORMAL",
               "is_saved": False})


def h_avatar(st, user, cid, req, empty):
    persona = persona_of(user)
    return ok({"avatars": [{"avatar_id": f"avatar_{persona}", "lifecycle_status": "READY",
                            "poses": [{"pose": "NORMAL", "status": "PROCESSED",
                                       "image_url": st.seed.users[persona]["avatar_url"]}]}]})


def _name(st, user, key: str) -> str:
    if key in st.seed.catalog:
        return st.seed.catalog[key]["name"]
    return _wardrobe(st, user).get(key, {}).get("category", key)


def h_looks(st, user, cid, req, empty):
    created = [{"look_id": t["look_id"], "garment_ids": t["garment_ids"],
                "description": "Try-on: " + ", ".join(_name(st, user, resolve_garment(st, user, g) or g)
                                                      for g in t["garment_ids"]),
                "tryon_image_url": t["image_url"], "created_at": t["created_at"]}
               for t in st.store.tryons_of(user)]
    seeded = sorted(st.seed.looks.get(persona_of(user), []), key=lambda lk: lk["created_at"], reverse=True)
    return ok({"looks": (created + seeded)[:max(1, req["limit"])]})


def h_wardrobe(st, user, cid, req, empty):
    types = set(req["garment_types"] or [])
    garments = [{"garment_id": g["garment_id"], "type": g["type"], "category": g["category"],
                 "ghost_image_url": g["ghost_image_url"], "metadata": {**g["metadata"], "tags": g["tags"]}}
                for g in _wardrobe(st, user).values() if not types or g["type"] in types]
    return ok({"garments": garments})


def _artifact(st, user: str, kind: str, value: str) -> dict:
    if kind == "PRODUCT":
        p = st.seed.catalog.get(value)
        if p is None:
            raise ToolError(422, "not_found", f"produto {value} não encontrado")
        return {"kind": kind, "item_id": p["id"], "name": p["name"], "store": p["store"], "price": p["price"],
                "currency_symbol": p["currency_symbol"], "url": p["url"], "image_url": p["image_url"],
                "tags": list(p["tags"])}
    if kind == "GARMENT":
        key = resolve_garment(st, user, value)
        if key is None:
            raise ToolError(422, "not_found", f"peça {value} não encontrada")
        src = st.seed.catalog.get(key) or _wardrobe(st, user)[key]
        return {"kind": kind, "garment_id": value, "item_id": key, "image_url": src["ghost_image_url"],
                "type": src["type"], "category": src["category"], "tags": _tags(st, user, key)}
    # TRYON_CARD: a created try-on (by tryon_id or look_id) or a seeded look (by look_id)
    for t in st.store.tryons_of(user):
        if value in (t["tryon_id"], t["look_id"]):
            image, garments = t["image_url"], t["garment_ids"]
            break
    else:
        look = next((lk for lk in st.seed.looks.get(persona_of(user), []) if lk["look_id"] == value), None)
        if look is None:
            raise ToolError(422, "not_found", f"try-on {value} não encontrado")
        image, garments = look["tryon_image_url"], look["garment_ids"]
    keys = [resolve_garment(st, user, g) or g for g in garments]
    return {"kind": kind, "tryon_id": value, "image_url": image, "garment_ids": garments, "item_ids": keys,
            "tags": sorted({t for k in keys for t in _tags(st, user, k)})}


def h_show(st, user, cid, req, empty):
    st.bus.publish(cid, {"type": "artifact", "artifact": _artifact(st, user, req["type"], req["value"])})
    return {"ok": True}


# ── routes ────────────────────────────────────────────────────────────────────

@router.post("/search_by_text")
async def search_by_text(body: SearchIn, request: Request):
    return await run_tool(request, "search_by_text", body, h_search)


@router.post("/garment_creation")
async def garment_creation(body: GarmentIn, request: Request):
    return await run_tool(request, "garment_creation", body, h_garment)


@router.post("/tryon")
async def tryon(body: TryonIn, request: Request):
    return await run_tool(request, "tryon", body, h_tryon)


@router.post("/avatar")
async def avatar(body: Base, request: Request):
    return await run_tool(request, "avatar", body, h_avatar)


@router.post("/looks")
async def looks(body: LooksIn, request: Request):
    return await run_tool(request, "looks", body, h_looks)


@router.post("/wardrobe")
async def wardrobe(body: WardrobeIn, request: Request):
    return await run_tool(request, "wardrobe", body, h_wardrobe)


@router.post("/show_artifact")
async def show_artifact(body: ShowIn, request: Request):
    return await run_tool(request, "show_artifact", body, h_show)
