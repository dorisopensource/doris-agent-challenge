"""SQLite log of conversations, turns and tool calls, plus garments/try-ons created at runtime.

Active turns live in memory only, so a proxy restart never locks a conversation.
ponytail: one connection, single process; add a lock if the proxy ever runs several workers.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (conversation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, conversation_id TEXT, user_id TEXT, message TEXT,
    text TEXT, outcome TEXT, n_artifacts INTEGER, started_at TEXT, duration_ms INTEGER, t0 REAL);
CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, conversation_id TEXT, turn_id INTEGER, tool TEXT,
    request_json TEXT, status INTEGER, error_code TEXT, response_json TEXT, latency_ms INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS garments (user_id TEXT, garment_id TEXT, item_id TEXT, PRIMARY KEY (user_id, garment_id));
CREATE TABLE IF NOT EXISTS tryons (user_id TEXT, tryon_id TEXT, look_id TEXT, garment_ids_json TEXT,
    image_url TEXT, created_at TEXT, seq INTEGER PRIMARY KEY);
"""


class TurnInProgress(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Store:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for column in ("events_json", "images_json"):  # databases created before the UI history existed
            try:
                self.db.execute(f"ALTER TABLE turns ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                pass
        self._active: dict[str, int] = {}

    def claim_conversation(self, conversation_id: str, user_id: str) -> bool:
        self.db.execute("INSERT OR IGNORE INTO conversations VALUES (?, ?)", (conversation_id, user_id))
        return self.user_of(conversation_id) == user_id

    def user_of(self, conversation_id: str) -> str | None:
        row = self.db.execute("SELECT user_id FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
        return row["user_id"] if row else None

    def begin_turn(self, conversation_id: str, user_id: str, message: str, images: list[str] | None = None) -> int:
        if conversation_id in self._active:
            raise TurnInProgress(conversation_id)
        cur = self.db.execute(
            "INSERT INTO turns (conversation_id, user_id, message, started_at, t0, images_json) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, user_id, message, _now(), time.monotonic(), _dumps(images or [])))
        self._active[conversation_id] = cur.lastrowid
        return cur.lastrowid

    def active_turn(self, conversation_id: str) -> int | None:
        return self._active.get(conversation_id)

    def end_turn(self, turn_id: int, outcome: str, text: str, n_artifacts: int, events: list[dict] | None = None) -> None:
        row = self.db.execute("SELECT conversation_id, t0 FROM turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            return
        self.db.execute("UPDATE turns SET outcome = ?, text = ?, n_artifacts = ?, duration_ms = ?, events_json = ?"
                        " WHERE id = ?", (outcome, text, n_artifacts, int((time.monotonic() - row["t0"]) * 1000),
                                          _dumps(events or []), turn_id))
        if self._active.get(row["conversation_id"]) == turn_id:
            del self._active[row["conversation_id"]]

    def log_call(self, conversation_id: str, turn_id: int | None, tool: str, request: dict, status: int,
                 response: dict, latency_ms: int) -> None:
        error = response.get("error") if isinstance(response, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        self.db.execute(
            "INSERT INTO calls (conversation_id, turn_id, tool, request_json, status, error_code, response_json,"
            " latency_ms, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, turn_id, tool, _dumps(request), status, code, _dumps(response), latency_ms, _now()))

    def add_garment(self, user_id: str, garment_id: str, item_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO garments VALUES (?, ?, ?)", (user_id, garment_id, item_id))

    def get_garment(self, user_id: str, garment_id: str) -> dict | None:
        row = self.db.execute("SELECT garment_id, item_id FROM garments WHERE user_id = ? AND garment_id = ?",
                              (user_id, garment_id)).fetchone()
        return dict(row) if row else None

    def add_tryon(self, user_id: str, record: dict) -> None:
        self.db.execute("DELETE FROM tryons WHERE user_id = ? AND tryon_id = ?", (user_id, record["tryon_id"]))
        self.db.execute(
            "INSERT INTO tryons (user_id, tryon_id, look_id, garment_ids_json, image_url, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, record["tryon_id"], record["look_id"], _dumps(record["garment_ids"]), record["image_url"],
             record["created_at"]))

    def _tryon(self, row) -> dict:
        return {"tryon_id": row["tryon_id"], "look_id": row["look_id"],
                "garment_ids": json.loads(row["garment_ids_json"]), "image_url": row["image_url"],
                "created_at": row["created_at"]}

    def get_tryon(self, user_id: str, tryon_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM tryons WHERE user_id = ? AND tryon_id = ? ORDER BY seq DESC",
                              (user_id, tryon_id)).fetchone()
        return self._tryon(row) if row else None

    def tryons_of(self, user_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM tryons WHERE user_id = ? ORDER BY seq DESC", (user_id,)).fetchall()
        return [self._tryon(r) for r in rows]

    def log(self, conversation_id: str | None) -> dict:
        where, args = ("WHERE conversation_id = ?", (conversation_id,)) if conversation_id else ("", ())
        calls = [{"turn_id": r["turn_id"], "conversation_id": r["conversation_id"], "tool": r["tool"],
                  "request": json.loads(r["request_json"]), "status": r["status"], "error_code": r["error_code"],
                  "response": json.loads(r["response_json"]), "latency_ms": r["latency_ms"], "ts": r["ts"]}
                 for r in self.db.execute(f"SELECT * FROM calls {where} ORDER BY id", args)]
        turns = []
        for r in self.db.execute(f"SELECT * FROM turns {where} ORDER BY id", args):
            turn = {k: r[k] for k in ("id", "conversation_id", "user_id", "message", "text", "outcome",
                                      "n_artifacts", "started_at", "duration_ms")}
            turn["calls"] = [c for c in calls if c["turn_id"] == r["id"]]
            turns.append(turn)
        return {"turns": turns, "calls_outside_turns": [c for c in calls if c["turn_id"] is None]}

    def conversations(self, user_id: str) -> list[dict]:
        """A user's conversations for the UI sidebar, most recently active first."""
        rows = self.db.execute(
            "SELECT conversation_id, MIN(started_at) AS started_at, MAX(started_at) AS updated_at, COUNT(*) AS turns,"
            " (SELECT message FROM turns t2 WHERE t2.conversation_id = t.conversation_id ORDER BY id LIMIT 1) AS first"
            " FROM turns t WHERE user_id = ? AND events_json IS NOT NULL AND events_json != '[]'"  # only replayable turns
            " GROUP BY conversation_id ORDER BY MAX(id) DESC", (user_id,)).fetchall()
        title = lambda m: "📷 Imagem" if not m else m if len(m) <= 60 else m[:60].rstrip() + "…"
        return [{"conversation_id": r["conversation_id"], "title": title(r["first"] or ""), "turns": r["turns"],
                 "started_at": r["started_at"], "updated_at": r["updated_at"]} for r in rows]

    def messages(self, conversation_id: str) -> list[dict]:
        """Every finished turn of a conversation with the exact events the browser received, for replay."""
        rows = self.db.execute("SELECT id, message, outcome, started_at, events_json, images_json FROM turns"
                               " WHERE conversation_id = ? AND outcome IS NOT NULL ORDER BY id", (conversation_id,))
        return [{"turn_id": r["id"], "message": r["message"], "outcome": r["outcome"], "started_at": r["started_at"],
                 "images": json.loads(r["images_json"] or "[]"), "events": json.loads(r["events_json"] or "[]")}
                for r in rows]

    def reset(self) -> None:
        for table in ("conversations", "turns", "calls", "garments", "tryons"):
            self.db.execute(f"DELETE FROM {table}")
        self._active.clear()
