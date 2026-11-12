"""Chat gateway: forwards the turn to the agent and streams back one SSE stream that merges the
agent's text/feedback events with artifact events from /tools/show_artifact. Cuts the turn at
TURN_TIMEOUT_S and always ends with exactly one `done` or `error`."""
import asyncio
import json

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.seed import persona_of
from app.store import TurnInProgress
from app.tools import error_body

router = APIRouter()
FEEDBACK_STATES = {"running", "done", "error"}


class ChatIn(BaseModel):
    user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    message: str
    images: list[str] = []


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _error(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}


def _from_openai(obj) -> list[dict]:
    """One OpenAI-compatible stream object → browser events. Text comes from choices[].delta.content, tool feedback
    from the Doris extension field `doris`, errors from the standard `error` object. Anything else is skipped."""
    if not isinstance(obj, dict):
        return []
    if isinstance(obj.get("error"), dict):
        return [_error("agent_error", str(obj["error"].get("message") or "erro no agente"))]
    out = []
    ext = obj.get("doris")
    if isinstance(ext, dict) and ext.get("type") == "feedback" and isinstance(ext.get("id"), str) \
            and isinstance(ext.get("text"), str):
        state = ext.get("state") if ext.get("state") in FEEDBACK_STATES else "running"
        out.append({"type": "feedback", "id": ext["id"], "text": ext["text"], "state": state})
    for choice in obj.get("choices") or []:
        content = (choice.get("delta") or {}).get("content") if isinstance(choice, dict) else None
        if isinstance(content, str) and content:
            out.append({"type": "text", "delta": content})
    return out


def _finished(obj) -> bool:
    return isinstance(obj, dict) and any(isinstance(c, dict) and c.get("finish_reason")
                                         for c in obj.get("choices") or [])


def openai_request(body: "ChatIn", profile: dict) -> dict:
    """What the agent receives: an OpenAI Chat Completions streaming request with only the current message."""
    content = [{"type": "text", "text": body.message}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in body.images]
    return {"model": "doris-agent", "stream": True, "user": body.user_id,
            "messages": [{"role": "user", "content": content}],
            "metadata": {"conversation_id": body.conversation_id, "profile": profile}}


async def _pump_agent(agent: httpx.AsyncClient, request: dict, out: asyncio.Queue) -> None:
    finished = False
    try:
        async with agent.stream("POST", "/v1/chat/completions", json=request) as r:
            if r.status_code != 200:
                out.put_nowait(_error("agent_error", f"o agente respondeu HTTP {r.status_code}"))
                return
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    out.put_nowait({"type": "done"})
                    return
                try:
                    obj = json.loads(payload)
                except ValueError:
                    continue
                for ev in _from_openai(obj):
                    out.put_nowait(ev)
                    if ev["type"] == "error":
                        return
                finished = finished or _finished(obj)
        if finished:  # tolerate agents that end with finish_reason but omit the [DONE] marker
            out.put_nowait({"type": "done"})
        else:
            out.put_nowait(_error("agent_error", "o agente encerrou a resposta sem finish_reason nem [DONE]"))
    except httpx.ConnectError as e:
        out.put_nowait(_error("agent_unavailable", f"não foi possível conectar ao agente: {e}"))
    except httpx.HTTPError as e:
        out.put_nowait(_error("agent_error", f"falha na conexão com o agente: {e}"))
    except Exception as e:  # noqa: BLE001 — never leave the client waiting for the turn cut
        out.put_nowait(_error("agent_error", f"erro inesperado ao falar com o agente: {e!r}"))


async def _stream(st, body: ChatIn, turn_id: int, out: asyncio.Queue):
    cid = body.conversation_id
    u = st.seed.users[persona_of(body.user_id)]
    profile = {"name": u["name"], "gender": u["gender"], "city": u["city"]}
    pump = asyncio.create_task(_pump_agent(st.agent, openai_request(body, profile), out))
    text: list[str] = []
    sent: list[dict] = []  # exactly what the browser receives, saved for the UI history
    n_artifacts, outcome = 0, "error"
    try:
        async with asyncio.timeout(st.settings.turn_timeout_s):
            while True:
                ev = await out.get()
                if ev["type"] == "text":
                    text.append(ev["delta"])
                elif ev["type"] == "artifact":
                    n_artifacts += 1
                elif ev["type"] == "done":
                    while not out.empty():  # artifacts published just before done
                        extra = out.get_nowait()
                        n_artifacts += extra["type"] == "artifact"
                        sent.append(extra)
                        yield _sse(extra)
                    outcome = "done"
                sent.append(ev)
                yield _sse(ev)
                if ev["type"] in ("done", "error"):
                    break
    except TimeoutError:
        outcome = "turn_timeout"
        timeout_event = _error("turn_timeout", f"o turno passou de {st.settings.turn_timeout_s:g}s e foi encerrado")
        sent.append(timeout_event)
        yield _sse(timeout_event)
    finally:
        pump.cancel()
        st.bus.unsubscribe(cid)
        st.store.end_turn(turn_id, outcome, "".join(text), n_artifacts, sent)


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    st = request.app.state
    if persona_of(body.user_id) not in st.seed.users:
        return JSONResponse(error_body("unknown_user", f"usuário {body.user_id} não existe"), status_code=400)
    if not st.store.claim_conversation(body.conversation_id, body.user_id):
        return JSONResponse(error_body("conversation_owned", "esta conversa pertence a outro usuário"), status_code=409)
    try:
        turn_id = st.store.begin_turn(body.conversation_id, body.user_id, body.message, body.images)
    except TurnInProgress:
        return JSONResponse(error_body("turn_in_progress", "já existe um turno em andamento nesta conversa", True),
                            status_code=409)
    out = st.bus.subscribe(body.conversation_id)
    return StreamingResponse(_stream(st, body, turn_id, out), media_type="text/event-stream")
