import json

import httpx

from testkit import wire


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://proxy")


async def say(*events):
    for e in events:
        yield e


async def chat(c, user, cid, message):
    r = await c.post("/chat", json={"user_id": user, "conversation_id": cid, "message": message})
    return [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]


async def test_conversations_listed_per_user_newest_first(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "text", "delta": "ok"}, {"type": "done"}))
    async with client_for(app) as c:
        await chat(c, "u_ana", "c-old", "Primeira conversa da Ana")
        await chat(c, "u_ana", "c-old", "segunda mensagem")
        await chat(c, "u_bruno", "c-bruno", "Oi")
        await chat(c, "u_ana", "c-new", "Conversa nova da Ana com um título bem comprido que passa de sessenta caracteres")
        convs = (await c.get("/conversations", params={"user_id": "u_ana"})).json()
    assert [x["conversation_id"] for x in convs] == ["c-new", "c-old"]
    assert convs[1]["title"] == "Primeira conversa da Ana" and convs[1]["turns"] == 2
    assert len(convs[0]["title"]) <= 61 and convs[0]["title"].endswith("…")


async def test_messages_replay_what_the_browser_saw(tmp_path):
    async def behavior(b, proxy):
        yield {"type": "feedback", "id": "s", "text": "Buscando…", "state": "running"}
        await proxy.post("/tools/show_artifact", json={"conversation_id": b["metadata"]["conversation_id"], "type": "PRODUCT",
                                                        "value": "p01"})
        yield {"type": "feedback", "id": "s", "text": "Pronto", "state": "done"}
        yield {"type": "text", "delta": "Achei esta."}
        yield {"type": "done"}

    app = wire(tmp_path, behavior)
    async with client_for(app) as c:
        seen = await chat(c, "u_ana", "c1", "camisa branca")
        page = (await c.get("/conversations/c1/messages")).json()
    assert page["user_id"] == "u_ana"
    turn = page["turns"][0]
    assert turn["message"] == "camisa branca" and turn["outcome"] == "done"
    assert turn["events"] == seen


async def test_messages_of_unknown_conversation_404(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "done"}))
    async with client_for(app) as c:
        r = await c.get("/conversations/nope/messages")
    assert r.status_code == 404 and r.json()["error"]["code"] == "conversation_not_found"


async def test_messages_keep_attached_images(tmp_path):
    app = wire(tmp_path, lambda b, p: say({"type": "text", "delta": "Bonito!"}, {"type": "done"}))
    img = "data:image/jpeg;base64,/9j/AAAA"
    async with client_for(app) as c:
        await c.post("/chat", json={"user_id": "u_carla", "conversation_id": "c-img", "message": "", "images": [img]})
        page = (await c.get("/conversations/c-img/messages")).json()
        convs = (await c.get("/conversations", params={"user_id": "u_carla"})).json()
    assert page["turns"][0]["images"] == [img]
    assert convs[0]["title"] == "📷 Imagem"
