"""Agente inicial (stub). Substitua por completo — o contrato está no README da raiz.

Contrato: OpenAI Chat Completions em streaming (POST /v1/chat/completions, stream=true), com as extensões da Doris
(`metadata` na requisição e o campo `doris` para feedback de tools).
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def chunk(**fields) -> str:
    return f"data: {json.dumps({'object': 'chat.completion.chunk', **fields}, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()  # model, stream, user, messages (só a mensagem atual), metadata

    async def events():
        yield chunk(choices=[], doris={"type": "feedback", "id": "stub", "text": "Pensando…", "state": "running"})
        yield chunk(choices=[{"index": 0, "delta": {"content": "Ainda não fui implementado 🙂"}, "finish_reason": None}])
        yield chunk(choices=[], doris={"type": "feedback", "id": "stub", "text": "Pronto", "state": "done"})
        yield chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
