import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from testkit import make_settings


FAULTS = {"rules": [
    {"tool": "search_by_text", "match": {"query": "camisa\\s+xadrez"}, "effect": "empty"},
    {"tool": "tryon", "match": {"item_ids": "^p03$"},
     "effect": {"error": {"status": 503, "code": "upstream_timeout", "retryable": True}}, "times": 1},
]}


@pytest.fixture
def client(tmp_path):
    faults = tmp_path / "faults.json"
    faults.write_text(json.dumps(FAULTS))
    return TestClient(create_app(make_settings(tmp_path, faults_file=faults)))


def conv(client, user="u_ana") -> str:
    cid = str(uuid.uuid4())
    assert client.app.state.store.claim_conversation(cid, user)
    return cid
