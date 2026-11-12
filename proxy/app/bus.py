"""Per-conversation event queues: tool endpoints publish, the open chat stream consumes."""
import asyncio


class Bus:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, conversation_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[conversation_id] = q
        return q

    def unsubscribe(self, conversation_id: str) -> None:
        self._queues.pop(conversation_id, None)

    def publish(self, conversation_id: str, event: dict) -> None:
        q = self._queues.get(conversation_id)
        if q is not None:
            q.put_nowait(event)
