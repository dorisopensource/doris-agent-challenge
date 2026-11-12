import json

from app.faults import Faults

ERR = {"error": {"status": 503, "code": "upstream_timeout", "retryable": True}}


def make(tmp_path, rules):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"rules": rules}))
    return Faults.load(p)


def test_faults_load_none():
    assert Faults.load(None).check("tryon", {"item_ids": ["p03"]}, "c1").kind is None


def test_fault_empty_regex_case_insensitive(tmp_path):
    f = make(tmp_path, [{"tool": "search_by_text", "match": {"query": "camisa\\s+xadrez"}, "effect": "empty"}])
    assert f.check("search_by_text", {"query": "Tem CAMISA  Xadrez?"}, "c1").kind == "empty"
    assert f.check("search_by_text", {"query": "camisa lisa"}, "c1").kind is None
    assert f.check("tryon", {"query": "camisa xadrez"}, "c1").kind is None


def test_fault_times_then_normal(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {"item_ids": "^p03$"}, "effect": ERR, "times": 1}])
    e = f.check("tryon", {"item_ids": ["p03"]}, "c1")
    assert (e.kind, e.status, e.code, e.retryable) == ("error", 503, "upstream_timeout", True)
    assert f.check("tryon", {"item_ids": ["p03"]}, "c1").kind is None


def test_fault_counters_per_conversation(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {"item_ids": "p03"}, "effect": ERR, "times": 1}])
    assert f.check("tryon", {"item_ids": ["p03"]}, "c1").kind == "error"
    assert f.check("tryon", {"item_ids": ["p03"]}, "c2").kind == "error"
    assert f.check("tryon", {"item_ids": ["p03"]}, "c1").kind is None


def test_fault_non_matching_calls_do_not_consume_budget(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {"item_ids": "p03"}, "effect": ERR, "times": 1}])
    assert f.check("tryon", {"item_ids": ["p01"]}, "c1").kind is None
    assert f.check("tryon", {"item_ids": ["p03"]}, "c1").kind == "error"


def test_fault_list_field_joined(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {"item_ids": "p01,p03"}, "effect": "empty"}])
    assert f.check("tryon", {"item_ids": ["p01", "p03"]}, "c1").kind == "empty"


def test_fault_missing_field_does_not_match(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {"item_ids": "p03"}, "effect": "empty"}])
    assert f.check("tryon", {}, "c1").kind is None


def test_fault_delays_add(tmp_path):
    f = make(tmp_path, [
        {"tool": "tryon", "match": {}, "effect": {"delay_ms": 1000}},
        {"tool": "tryon", "match": {}, "effect": {"delay_ms": 500}},
        {"tool": "tryon", "match": {}, "effect": ERR},
        {"tool": "tryon", "match": {}, "effect": "empty"},
    ])
    e = f.check("tryon", {}, "c1")
    assert (e.delay_ms, e.kind, e.code) == (1500, "error", "upstream_timeout")


def test_fault_reset(tmp_path):
    f = make(tmp_path, [{"tool": "tryon", "match": {}, "effect": ERR, "times": 1}])
    assert f.check("tryon", {}, "c1").kind == "error"
    f.reset()
    assert f.check("tryon", {}, "c1").kind == "error"
