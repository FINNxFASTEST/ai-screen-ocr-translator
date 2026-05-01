import sqlite3
import threading
from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).resolve().parents[1] / "memory.db"
_SIMILARITY_THRESHOLD = 0.72


class MemoryStore:
    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._model = None
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL UNIQUE,
                translation TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def _embed(self, text: str) -> np.ndarray:
        return self._get_model().encode(text, normalize_embeddings=True).astype(np.float32)

    def get_exact(self, source: str) -> str | None:
        row = self._conn.execute(
            "SELECT translation FROM translations WHERE source = ?", (source,)
        ).fetchone()
        return row[0] if row else None

    def search(self, text: str, top_k: int = 3) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT source, translation, embedding FROM translations"
        ).fetchall()
        if not rows:
            return []

        query_vec = self._embed(text)
        scored = []
        for source, translation, emb_blob in rows:
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            score = float(np.dot(query_vec, emb))
            if score > _SIMILARITY_THRESHOLD:
                scored.append((score, source, translation))

        scored.sort(reverse=True)
        return [(src, tr) for _, src, tr in scored[:top_k]]

    def save(self, source: str, translation: str) -> None:
        emb = self._embed(source)
        with self._lock:
            self._conn.execute(
                """INSERT INTO translations (source, translation, embedding)
                   VALUES (?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET translation=excluded.translation""",
                (source, translation, emb.tobytes()),
            )
            self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
