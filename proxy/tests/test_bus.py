from app.bus import Bus


def test_bus_publish_without_subscriber():
    Bus().publish("c1", {"type": "artifact"})


def test_bus_delivers():
    bus = Bus()
    q = bus.subscribe("c1")
    bus.publish("c1", {"type": "artifact", "n": 1})
    bus.publish("c2", {"type": "artifact", "n": 2})
    assert q.get_nowait() == {"type": "artifact", "n": 1}
    assert q.empty()
    bus.unsubscribe("c1")
    bus.publish("c1", {"type": "artifact"})
    assert q.empty()
