from conftest import conv


def test_log_lists_calls(client):
    cid = conv(client)
    client.post("/tools/avatar", json={"conversation_id": cid})
    log = client.get("/admin/log", params={"conversation_id": cid}).json()
    assert [c["tool"] for c in log["calls_outside_turns"]] == ["avatar"]
    assert client.get("/admin/log").json()["calls_outside_turns"]


def test_reset_clears_log_and_fault_counters(client):
    cid = conv(client)
    gid = client.post("/tools/garment_creation", json={"conversation_id": cid, "search_item_id": "p03"}).json()["data"]["garment_id"]
    tryon = lambda: client.post("/tools/tryon", json={"conversation_id": cid, "garment_ids": [gid]})
    assert tryon().status_code == 503
    assert client.post("/admin/reset").json() == {"ok": True}
    assert client.get("/admin/log").json() == {"turns": [], "calls_outside_turns": []}
    assert client.app.state.store.claim_conversation(cid, "u_ana")  # same conversation id after reset
    client.post("/tools/garment_creation", json={"conversation_id": cid, "search_item_id": "p03"})
    assert tryon().status_code == 503  # fault budget was reset
    assert tryon().status_code == 200
