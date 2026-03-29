import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConversationTurn:
    speaker: str
    text: str


class ConversationMemory:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._initialize()

    def build_key(self, channel: str, thread_ts: str) -> str:
        return f"{channel}:{thread_ts}"

    def add(self, key: str, speaker: str, text: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_turns (conversation_key, speaker, text)
                VALUES (?, ?, ?)
                """,
                (key, speaker, text),
            )
            conn.commit()

    def has_context(self, key: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM conversation_turns
                WHERE conversation_key = ?
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        return row is not None

    def render_context(self, key: str) -> str:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT speaker, text
                FROM conversation_turns
                WHERE conversation_key = ?
                ORDER BY id ASC
                """,
                (key,),
            ).fetchall()

        if not rows:
            return ""

        turns = [ConversationTurn(speaker=row[0], text=row[1]) for row in rows]
        return "\n".join(f"{turn.speaker}: {turn.text}" for turn in turns)

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_key TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_key_id
                ON conversation_turns (conversation_key, id)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)
