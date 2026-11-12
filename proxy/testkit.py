"""Test helpers for proxy/tests. Not used by the running app."""
from dataclasses import replace
from pathlib import Path

from app.settings import Settings


def make_settings(tmp_path: Path, **over) -> Settings:
    return replace(Settings(), db_path=str(tmp_path / "proxy.db"), latency_scale=0.0, **over)


import inspect
import json

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse


def oai_lines(ev) -> list[str]:
    """Translate a readable test event into what an OpenAI-compatible agent streams."""
    if isinstance(ev, str):
        return [ev]
    sse = lambda obj: f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
    chunk = lambda **kw: {"object": "chat.completion.chunk", **kw}
    kind = ev.get("type")
    if kind == "text":
        return [sse(chunk(choices=[{"index": 0, "delta": {"content": ev["delta"]}, "finish_reason": None}]))]
    if kind == "done":
        return [sse(chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])), "data: [DONE]\n\n"]
    if kind == "error":
        return [sse({"error": {"message": ev.get("message", ""), "type": "agent_error"}})]
    return [sse(chunk(choices=[], doris=ev))]  # feedback (and anything custom) rides in the `doris` field


def make_fake_agent(behavior) -> FastAPI:
    """A stand-in OpenAI-compatible agent. `behavior(body, proxy)` returns a Response, or an async iterator of
    readable events ({"type": "text"|"feedback"|"done"|"error", ...}, translated by `oai_lines`) and raw strings
    (sent verbatim)."""
    agent = FastAPI()
    agent.state.proxy = None
    agent.state.received = []

    @agent.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        agent.state.received.append(body)
        result = behavior(body, agent.state.proxy)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, Response):
            return result

        async def gen():
            async for ev in result:
                for line in oai_lines(ev):
                    yield line

        return StreamingResponse(gen(), media_type="text/event-stream")

    return agent


import asyncio


class StreamingASGITransport(httpx.AsyncBaseTransport):
    """Like httpx.ASGITransport, but streams the response body chunk by chunk (httpx's own
    transport buffers the whole body, which hides event ordering between agent and proxy)."""

    def __init__(self, app):
        self.app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        chunks: asyncio.Queue = asyncio.Queue()
        started, disconnected, head = asyncio.Event(), asyncio.Event(), {}
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                head.update(message)
                started.set()
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    await chunks.put(message["body"])
                if not message.get("more_body"):
                    await chunks.put(None)

        url = request.url
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": request.method,
                 "scheme": url.scheme, "path": url.path, "raw_path": url.raw_path.split(b"?")[0],
                 "query_string": url.query, "root_path": "", "client": ("127.0.0.1", 50000),
                 "server": (url.host, url.port or 80), "headers": [(k.lower(), v) for k, v in request.headers.raw]}
        task = asyncio.create_task(self.app(scope, receive, send))
        task.add_done_callback(lambda _: chunks.put_nowait(None))  # app crashed or ended: never leave a reader hanging
        waiter = asyncio.create_task(started.wait())
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if not started.is_set():
            waiter.cancel()
            task.result()  # re-raise the app's exception
            raise RuntimeError("app finished without a response")

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                while (chunk := await chunks.get()) is not None:
                    yield chunk

            async def aclose(self):
                disconnected.set()
                task.cancel()

        return httpx.Response(head["status"], headers=head.get("headers", []), stream=Body())


def wire(tmp_path: Path, behavior, **settings_over) -> FastAPI:
    """Proxy app whose agent is a fake agent that calls back into this same proxy."""
    from app.main import create_app

    agent = make_fake_agent(behavior)
    proxy = create_app(make_settings(tmp_path, **settings_over), agent_transport=StreamingASGITransport(agent))
    agent.state.proxy = httpx.AsyncClient(transport=httpx.ASGITransport(proxy), base_url="http://proxy")
    proxy.state.fake_agent = agent
    return proxy
