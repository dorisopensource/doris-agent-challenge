"""Debug endpoints (and our evaluation). Agents must not call these (README rule)."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/admin")


@router.get("/log")
async def log(request: Request, conversation_id: str | None = None):
    return request.app.state.store.log(conversation_id)


@router.post("/reset")
async def reset(request: Request):
    request.app.state.store.reset()
    request.app.state.faults.reset()
    return {"ok": True}
