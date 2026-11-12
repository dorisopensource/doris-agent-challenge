def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    for needle in ('id="user-select"', 'id="new-chat"', 'id="messages"', 'id="input"', 'id="attach"', 'id="send"',
                   "Nova conversa", 'class="typing"', 'id="history"', 'getRandomValues', 'toDataURL'):
        assert needle in r.text
