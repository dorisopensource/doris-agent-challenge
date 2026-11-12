import pytest

from app.store import Store, TurnInProgress


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "p.db"))


def test_claim_conversation(store):
    assert store.claim_conversation("c1", "u_ana") is True
    assert store.claim_conversation("c1", "u_ana") is True
    assert store.claim_conversation("c1", "u_bruno") is False
    assert store.user_of("c1") == "u_ana"
    assert store.user_of("nope") is None


def test_turn_in_progress(store):
    t = store.begin_turn("c1", "u_ana", "oi")
    assert store.active_turn("c1") == t
    with pytest.raises(TurnInProgress):
        store.begin_turn("c1", "u_ana", "de novo")
    store.end_turn(t, "done", "olá", 0)
    assert store.active_turn("c1") is None
    store.begin_turn("c1", "u_ana", "de novo")


def test_log_nests_calls_under_turns(store):
    store.claim_conversation("c1", "u_ana")
    t = store.begin_turn("c1", "u_ana", "oi")
    store.log_call("c1", t, "search_by_text", {"query": "camisa"}, 200, {"ok": True, "data": {"products": []}}, 5)
    store.log_call("c1", t, "tryon", {"garment_ids": ["g"]}, 503,
                   {"ok": False, "error": {"code": "upstream_timeout", "message": "x", "retryable": True}}, 7)
    store.log_call("c1", None, "profile", {}, 200, {"ok": True, "data": {}}, 1)
    store.end_turn(t, "done", "olá", 2)
    log = store.log("c1")
    turn = log["turns"][0]
    assert (turn["message"], turn["text"], turn["outcome"], turn["n_artifacts"]) == ("oi", "olá", "done", 2)
    assert [c["tool"] for c in turn["calls"]] == ["search_by_text", "tryon"]
    assert turn["calls"][0]["request"] == {"query": "camisa"}
    assert turn["calls"][1]["error_code"] == "upstream_timeout"
    assert turn["calls"][1]["response"]["error"]["retryable"] is True
    assert [c["tool"] for c in log["calls_outside_turns"]] == ["profile"]


def test_log_all_conversations(store):
    store.end_turn(store.begin_turn("c1", "u_ana", "a"), "done", "", 0)
    store.end_turn(store.begin_turn("c2", "u_bruno", "b"), "done", "", 0)
    assert len(store.log(None)["turns"]) == 2
    assert len(store.log("c2")["turns"]) == 1


def test_reset_clears_everything(store):
    store.claim_conversation("c1", "u_ana")
    store.begin_turn("c1", "u_ana", "oi")
    store.log_call("c1", None, "profile", {}, 200, {}, 1)
    store.add_garment("u_ana", "g1", "p01")
    store.add_tryon("u_ana", {"tryon_id": "t1", "look_id": "l1", "garment_ids": ["g1"], "image_url": "u", "created_at": "2026"})
    store.reset()
    assert store.user_of("c1") is None
    assert store.active_turn("c1") is None
    assert store.log(None) == {"turns": [], "calls_outside_turns": []}
    assert store.get_garment("u_ana", "g1") is None
    assert store.tryons_of("u_ana") == []


def test_garments_scoped_by_user(store):
    store.add_garment("u_ana__x", "g1", "p01")
    store.add_garment("u_ana__x", "g1", "p01")  # idempotent
    assert store.get_garment("u_ana__x", "g1") == {"garment_id": "g1", "item_id": "p01"}
    assert store.get_garment("u_ana__y", "g1") is None


def test_tryons_newest_first(store):
    for i in range(3):
        store.add_tryon("u_ana", {"tryon_id": f"t{i}", "look_id": f"l{i}", "garment_ids": ["g"],
                                  "image_url": "u", "created_at": f"2026-11-0{i + 1}"})
    assert [t["tryon_id"] for t in store.tryons_of("u_ana")] == ["t2", "t1", "t0"]
    assert store.get_tryon("u_ana", "t1")["garment_ids"] == ["g"]
    assert store.get_tryon("u_bruno", "t1") is None


def test_active_turns_not_persisted(tmp_path):
    path = str(tmp_path / "p.db")
    Store(path).begin_turn("c1", "u_ana", "oi")
    assert Store(path).active_turn("c1") is None


def test_tryon_readd_moves_to_newest_without_duplicate(store):
    rec = lambda i: {"tryon_id": f"t{i}", "look_id": f"l{i}", "garment_ids": ["g"], "image_url": "u", "created_at": "x"}
    store.add_tryon("u_ana", rec(0))
    store.add_tryon("u_ana", rec(1))
    store.add_tryon("u_ana", rec(0))
    assert [t["tryon_id"] for t in store.tryons_of("u_ana")] == ["t0", "t1"]


def test_conversations_without_content_are_not_listed(store):
    store.end_turn(store.begin_turn("empty", "u_ana", "oi"), "error", "", 0)  # no events stored
    store.end_turn(store.begin_turn("full", "u_ana", "oi"), "done", "olá", 0,
                   [{"type": "text", "delta": "olá"}, {"type": "done"}])
    store.begin_turn("open", "u_ana", "ainda respondendo")  # unfinished turn
    assert [c["conversation_id"] for c in store.conversations("u_ana")] == ["full"]
