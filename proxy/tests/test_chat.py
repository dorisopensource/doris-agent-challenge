import asyncio
import json
import uuid

import httpx
from fastapi.responses import JSONResponse

from app.main import create_app
from testkit import make_settings, wire


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://proxy")


def events_of(resp):
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def body(user="u_ana", cid=None, message="oi", **extra):
    return {"user_id": user, "conversation_id": cid or str(uuid.uuid4()), "message": message, **extra}


async def say(*events, sleep=0.0):
    if sleep:
        await asyncio.sleep(sleep)
    for e in events:
        yield e


async def test_happy_turn(tmp_path):
    async def behavior(b, proxy):
        yield {"type": "text", "delta": "Ol"}
        await proxy.post("/tools/show_artifact", json={"conversation_id": b["metadata"]["conversation_id"], "type": "PRODUCT",
                                                        "value": "p01"})
        yield {"type": "text", "delta": "á"}
        yield {"type": "done"}

    app = wire(tmp_path, behavior)
    b = body()
    async with client_for(app) as c:
        r = await c.post("/chat", json=b)
        evs = events_of(r)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert [e["type"] for e in evs].count("artifact") == 1
        assert next(e for e in evs if e["type"] == "artifact")["artifact"]["item_id"] == "p01"
        assert "".join(e["delta"] for e in evs if e["type"] == "text") == "Olá"
        assert evs[-1] == {"type": "done"}
        turn = (await c.get("/admin/log", params={"conversation_id": b["conversation_id"]})).json()["turns"][0]
    assert (turn["outcome"], turn["text"], turn["n_artifacts"]) == ("done", "Olá", 1)
    assert [call["tool"] for call in turn["calls"]] == ["show_artifact"]


async def test_forwards_body(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}))
    b = body(images=["https://img/x.jpg"])
    async with client_for(app) as c:
        await c.post("/chat", json=b)
    assert app.state.fake_agent.state.received == [{
        "model": "doris-agent", "stream": True, "user": "u_ana",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"},
                                                  {"type": "image_url", "image_url": {"url": "https://img/x.jpg"}}]}],
        "metadata": {"conversation_id": b["conversation_id"],
                     "profile": {"name": "Ana", "gender": "FEMALE", "city": "São Paulo"}}}]


async def test_profile_injected_for_suffixed_user(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}))
    async with client_for(app) as c:
        await c.post("/chat", json=body(user="u_bruno__r1"))
    assert app.state.fake_agent.state.received[0]["metadata"]["profile"] == {"name": "Bruno", "gender": "MALE",
                                                                  "city": "Rio de Janeiro"}


async def test_feedback_passthrough(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "feedback", "id": "t1", "text": "Gerando try-on…", "state": "running"},
                                          {"type": "feedback", "id": "t1", "text": "Try-on pronto", "state": "done"},
                                          {"type": "done"}))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    fb = [e for e in evs if e["type"] == "feedback"]
    assert fb == [{"type": "feedback", "id": "t1", "text": "Gerando try-on…", "state": "running"},
                  {"type": "feedback", "id": "t1", "text": "Try-on pronto", "state": "done"}]


async def test_invalid_feedback_skipped(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "feedback", "text": "sem id"},
                                          {"type": "feedback", "id": "x", "text": "ok", "state": "weird"},
                                          {"type": "mystery"}, {"type": "done"}))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "feedback", "id": "x", "text": "ok", "state": "running"}, {"type": "done"}]


async def test_unknown_user_400(tmp_path):
    async with client_for(wire(tmp_path, lambda b, p: say({"type": "done"}))) as c:
        r = await c.post("/chat", json=body(user="u_zeca"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_user"


async def test_conversation_owned_409(tmp_path):
    async with client_for(wire(tmp_path, lambda b, p: say({"type": "done"}))) as c:
        cid = str(uuid.uuid4())
        await c.post("/chat", json=body(cid=cid))
        r = await c.post("/chat", json=body(user="u_bruno", cid=cid))
    assert r.status_code == 409 and r.json()["error"]["code"] == "conversation_owned"


async def test_concurrent_turn_rejected(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}, sleep=0.3))
    cid = str(uuid.uuid4())
    async with client_for(app) as c:
        first = asyncio.create_task(c.post("/chat", json=body(cid=cid)))
        await asyncio.sleep(0.05)
        second = await c.post("/chat", json=body(cid=cid))
        first = await first
    assert second.status_code == 409 and second.json()["error"]["code"] == "turn_in_progress"
    assert events_of(first)[-1] == {"type": "done"}


async def test_turn_timeout(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}, sleep=2), turn_timeout_s=0.3)
    cid = str(uuid.uuid4())
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body(cid=cid)))
        assert evs[-1]["type"] == "error" and evs[-1]["code"] == "turn_timeout"
        log = (await c.get("/admin/log", params={"conversation_id": cid})).json()
        assert log["turns"][0]["outcome"] == "turn_timeout"
        assert app.state.store.active_turn(cid) is None


async def test_agent_500(tmp_path):
    async def behavior(b, p):
        return JSONResponse({"detail": "boom"}, status_code=500)

    async with client_for(wire(tmp_path, behavior)) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs[-1]["type"] == "error" and evs[-1]["code"] == "agent_error"


async def test_stream_without_done(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "text", "delta": "meio"}))
    cid = str(uuid.uuid4())
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body(cid=cid)))
        turn = (await c.get("/admin/log", params={"conversation_id": cid})).json()["turns"][0]
    assert evs[-1]["type"] == "error" and evs[-1]["code"] == "agent_error"
    assert [e["type"] for e in evs].count("done") == 0
    assert turn["outcome"] == "error" and turn["text"] == "meio"
    assert app.state.store.active_turn(cid) is None


async def test_agent_unreachable(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    app = create_app(make_settings(tmp_path), agent_transport=httpx.MockTransport(refuse))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "error", "code": "agent_unavailable", "message": evs[0]["message"]}]


async def test_agent_error_event_passthrough(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "error", "message": "modelo indisponível"}))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "error", "code": "agent_error", "message": "modelo indisponível"}]


async def test_malformed_line_skipped(tmp_path):
    app = wire(tmp_path, lambda b, p: say("data: {not json\n\n", ": comentário\n\n", {"type": "text", "delta": "ok"},
                                          {"type": "done"}))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "text", "delta": "ok"}, {"type": "done"}]


async def test_call_logged_under_turn_where_it_started(tmp_path):
    faults = tmp_path / "f.json"
    faults.write_text(json.dumps({"rules": [{"tool": "avatar", "match": {}, "effect": {"delay_ms": 300}}]}))
    app = wire(tmp_path, lambda b, p: say({"type": "done"}), faults_file=faults)
    cid = str(uuid.uuid4())
    store = app.state.store
    store.claim_conversation(cid, "u_ana")
    turn = store.begin_turn(cid, "u_ana", "oi")
    async with client_for(app) as c:
        slow = asyncio.create_task(c.post("/tools/avatar", json={"conversation_id": cid}))
        await asyncio.sleep(0.05)
        store.end_turn(turn, "turn_timeout", "", 0)
        await slow
        log = (await c.get("/admin/log", params={"conversation_id": cid})).json()
    assert [c["tool"] for c in log["turns"][0]["calls"]] == ["avatar"]
    assert log["calls_outside_turns"] == []


async def test_unexpected_agent_failure_is_agent_error(tmp_path):
    def broken(request):
        raise RuntimeError("boom")

    app = create_app(make_settings(tmp_path, turn_timeout_s=2), agent_transport=httpx.MockTransport(broken))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs[-1]["type"] == "error" and evs[-1]["code"] == "agent_error"


async def test_empty_ids_rejected(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}))
    async with client_for(app) as c:
        no_conv = await c.post("/chat", json={**body(), "conversation_id": ""})
        no_user = await c.post("/chat", json={**body(), "user_id": ""})
    assert no_conv.status_code == 400 and no_conv.json()["error"]["code"] == "invalid_request"
    assert no_user.status_code == 400


async def test_finish_reason_without_done_marker_still_ends_turn(tmp_path):
    finish = 'data: {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}\n\n'
    app = wire(tmp_path, lambda b, p: say({"type": "text", "delta": "oi"}, finish))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "text", "delta": "oi"}, {"type": "done"}]


async def test_done_marker_ends_turn(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "text", "delta": "a"}, "data: [DONE]\n\n", {"type": "text", "delta": "late"}))
    async with client_for(app) as c:
        evs = events_of(await c.post("/chat", json=body()))
    assert evs == [{"type": "text", "delta": "a"}, {"type": "done"}]


async def test_text_only_message_has_single_text_part(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}))
    async with client_for(app) as c:
        await c.post("/chat", json=body(message="só texto"))
    assert app.state.fake_agent.state.received[0]["messages"][0]["content"] == [{"type": "text", "text": "só texto"}]
