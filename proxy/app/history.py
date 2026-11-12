"""UI-only endpoints: the conversation list and replay for the frontend sidebar. Agents must not call these."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.tools import error_body

router = APIRouter(prefix="/conversations")


@router.get("")
async def conversations(request: Request, user_id: str):
    return request.app.state.store.conversations(user_id)


@router.get("/{conversation_id}/messages")
async def messages(request: Request, conversation_id: str):
    store = request.app.state.store
    user_id = store.user_of(conversation_id)
    if user_id is None:
        return JSONResponse(error_body("conversation_not_found", f"conversa {conversation_id} não encontrada"),
                            status_code=404)
    return {"conversation_id": conversation_id, "user_id": user_id, "turns": store.messages(conversation_id)}
