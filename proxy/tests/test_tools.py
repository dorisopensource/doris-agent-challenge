from conftest import conv


def post(client, tool, cid, **body):
    return client.post(f"/tools/{tool}", json={"conversation_id": cid, **body})


def make_garment(client, cid, item="p01"):
    r = post(client, "garment_creation", cid, search_item_id=item)
    assert r.status_code == 200, r.text
    return r.json()["data"]["garment_id"]


def test_unknown_conversation_404(client):
    r = post(client, "search_by_text", "nope", query="camisa")
    assert r.status_code == 404
    assert r.json() == {"ok": False, "error": {"code": "conversation_not_found", "message": r.json()["error"]["message"],
                                               "retryable": False}}


def test_search_shape_and_logged(client):
    cid = conv(client)
    r = post(client, "search_by_text", cid, query="camisa de linho branca", limit=3)
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    products = body["data"]["products"]
    assert len(products) == 3
    assert set(products[0]) >= {"search_item_id", "name", "store", "price", "currency_code", "currency_symbol",
                                "url", "image_url", "description"}
    assert {p["search_item_id"] for p in products[:2]} == {"p01", "p02"}
    calls = client.get("/admin/log", params={"conversation_id": cid}).json()["calls_outside_turns"]
    assert calls[0]["tool"] == "search_by_text" and calls[0]["request"]["query"] == "camisa de linho branca"
    assert "conversation_id" not in calls[0]["request"]


def test_search_limit_clamped(client):
    cid = conv(client)
    assert len(post(client, "search_by_text", cid, query="linho", limit=99).json()["data"]["products"]) <= 12


def test_garment_creation_deterministic(client):
    cid = conv(client)
    first = post(client, "garment_creation", cid, search_item_id="p01").json()["data"]
    second = post(client, "garment_creation", cid, search_item_id="p01").json()["data"]
    assert first["garment_id"] == second["garment_id"]
    assert first["status"] == "PROCESSED" and first["type"] == "TOP" and first["category"] == "shirt"
    assert first["ghost_image_url"].endswith("products/p01.jpg")


def test_garment_creation_unknown_item_422(client):
    r = post(client, "garment_creation", conv(client), search_item_id="p99")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_found" and r.json()["error"]["retryable"] is False


def test_garment_creation_missing_source_400(client):
    r = post(client, "garment_creation", conv(client))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_tryon_from_created_garment(client):
    cid = conv(client)
    gid = make_garment(client, cid, "p01")
    data = post(client, "tryon", cid, garment_ids=[gid]).json()["data"]
    assert data["image_url"] == client.app.state.seed.renders["u_ana"]["p01"]
    assert data["garment_ids"] == [gid] and data["status"] == "PROCESSED" and data["avatar_pose"] == "NORMAL"
    looks = post(client, "looks", cid).json()["data"]["looks"]
    assert looks[0]["look_id"] == data["look_id"]
    assert looks[0]["tryon_image_url"] == data["image_url"]
    assert looks[-1]["look_id"] == "look_ana_1"


def test_tryon_two_garments_400(client):
    cid = conv(client)
    r = post(client, "tryon", cid, garment_ids=[make_garment(client, cid, "p01"), make_garment(client, cid, "p06")])
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_combination"


def test_tryon_wardrobe_garment(client):
    cid = conv(client)
    data = post(client, "tryon", cid, garment_ids=["w_ana_2"]).json()["data"]
    assert data["image_url"] == client.app.state.seed.renders["u_ana"]["w_ana_2"]


def test_tryon_unknown_garment_422(client):
    r = post(client, "tryon", conv(client), garment_ids=["g-nope"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_found"


def test_suffix_users_share_persona_not_state(client):
    cx, cy = conv(client, "u_ana__x"), conv(client, "u_ana__y")
    wardrobe = post(client, "wardrobe", cx).json()["data"]["garments"]
    assert [g["garment_id"] for g in wardrobe] == ["w_ana_1", "w_ana_2", "w_ana_3", "w_ana_4", "w_ana_5"]
    gid = make_garment(client, cx, "p01")
    assert post(client, "tryon", cy, garment_ids=[gid]).status_code == 422


def test_wardrobe_filter_by_type(client):
    cid = conv(client)
    garments = post(client, "wardrobe", cid, garment_types=["TOP"]).json()["data"]["garments"]
    assert [g["garment_id"] for g in garments] == ["w_ana_2", "w_ana_3", "w_ana_4"]


def test_fault_tryon_fails_once(client):
    cid = conv(client)
    gid = make_garment(client, cid, "p03")
    first = post(client, "tryon", cid, garment_ids=[gid])
    assert first.status_code == 503
    assert first.json()["error"]["code"] == "upstream_timeout" and first.json()["error"]["retryable"] is True
    assert post(client, "tryon", cid, garment_ids=[gid]).status_code == 200


def test_fault_search_empty(client):
    r = post(client, "search_by_text", conv(client), query="camisa xadrez")
    assert r.status_code == 200 and r.json()["data"]["products"] == []


def test_show_artifact_publishes_resolved_card(client):
    cid = conv(client)
    tryon = post(client, "tryon", cid, garment_ids=[make_garment(client, cid, "p01")]).json()["data"]
    q = client.app.state.bus.subscribe(cid)
    r = post(client, "show_artifact", cid, type="TRYON_CARD", value=tryon["tryon_id"])
    assert r.status_code == 200 and r.json() == {"ok": True}
    event = q.get_nowait()
    assert event["type"] == "artifact"
    card = event["artifact"]
    assert card["kind"] == "TRYON_CARD" and card["image_url"] == tryon["image_url"]
    assert card["item_ids"] == ["p01"] and "linho" in card["tags"]


def test_show_artifact_product_and_garment(client):
    cid = conv(client)
    gid = make_garment(client, cid, "p04")
    q = client.app.state.bus.subscribe(cid)
    post(client, "show_artifact", cid, type="PRODUCT", value="p04")
    post(client, "show_artifact", cid, type="GARMENT", value=gid)
    product, garment = q.get_nowait()["artifact"], q.get_nowait()["artifact"]
    assert product["kind"] == "PRODUCT" and product["price"] == 299.0 and "amarelo" in product["tags"]
    assert garment["kind"] == "GARMENT" and garment["item_id"] == "p04"


def test_show_artifact_unknown_422(client):
    r = post(client, "show_artifact", conv(client), type="TRYON_CARD", value="nope")
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_found"


def test_no_proxy_progress_events(client):
    cid = conv(client)
    q = client.app.state.bus.subscribe(cid)
    post(client, "search_by_text", cid, query="camisa")
    post(client, "tryon", cid, garment_ids=["w_ana_1"])
    assert q.empty()


def test_avatar_shape(client):
    avatars = post(client, "avatar", conv(client)).json()["data"]["avatars"]
    assert avatars[0]["lifecycle_status"] == "READY"
    assert avatars[0]["poses"][0]["pose"] == "NORMAL" and avatars[0]["poses"][0]["image_url"].endswith("u_ana.jpg")


def test_profile_tool_removed(client):
    assert post(client, "profile", conv(client, "u_bruno")).status_code == 404


def test_users_and_health(client):
    assert client.get("/health").json() == {"ok": True}
    assert [u["user_id"] for u in client.get("/users").json()] == ["u_ana", "u_bruno", "u_carla"]


def test_seed_images_served(client):
    assert client.get("/seed-images/products/p01.jpg").status_code == 200


def test_invalid_tool_body_is_logged(client):
    cid = conv(client)
    r = client.post("/tools/tryon", json={"conversation_id": cid, "garment_id": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    calls = client.get("/admin/log", params={"conversation_id": cid}).json()["calls_outside_turns"]
    assert [(c["tool"], c["status"], c["request"]) for c in calls] == [("tryon", 400, {"garment_id": "x"})]


def test_invalid_body_without_conversation_not_logged(client):
    assert client.post("/tools/tryon", json={"garment_id": "x"}).status_code == 400
    assert client.get("/admin/log").json() == {"turns": [], "calls_outside_turns": []}


def test_no_faults_without_rules_file(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from testkit import make_settings
    c = TestClient(create_app(make_settings(tmp_path)))
    cid = conv(c)
    gid = make_garment(c, cid, "p03")
    assert post(c, "tryon", cid, garment_ids=[gid]).status_code == 200
