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
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='translations'"
        )
        exists = cur.fetchone() is not None
        if not exists:
            self._conn.execute("""
                CREATE TABLE translations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    translation TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    series_key TEXT NOT NULL DEFAULT 'default',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source, series_key)
                )
            """)
            self._conn.commit()
            return

        cols = [row[1] for row in self._conn.execute("PRAGMA table_info(translations)")]
        if "series_key" in cols:
            return

        self._conn.executescript("""
            CREATE TABLE translations_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                translation TEXT NOT NULL,
                embedding BLOB NOT NULL,
                series_key TEXT NOT NULL DEFAULT 'default',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, series_key)
            );
            INSERT INTO translations_new (source, translation, embedding, series_key)
                SELECT source, translation, embedding, 'default' FROM translations;
            DROP TABLE translations;
            ALTER TABLE translations_new RENAME TO translations;
        """)
        self._conn.commit()

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def _embed(self, text: str) -> np.ndarray:
        return self._get_model().encode(text, normalize_embeddings=True).astype(np.float32)

    def get_exact(self, source: str, series_key: str = "default") -> str | None:
        row = self._conn.execute(
            "SELECT translation FROM translations WHERE source = ? AND series_key = ?",
            (source, series_key),
        ).fetchone()
        return row[0] if row else None

    def search(self, text: str, top_k: int = 3, series_key: str = "default") -> list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT source, translation, embedding FROM translations WHERE series_key = ?",
            (series_key,),
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

    def save(self, source: str, translation: str, series_key: str = "default") -> None:
        emb = self._embed(source)
        with self._lock:
            self._conn.execute(
                """INSERT INTO translations (source, translation, embedding, series_key)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source, series_key) DO UPDATE SET
                     translation=excluded.translation,
                     embedding=excluded.embedding""",
                (source, translation, emb.tobytes(), series_key),
            )
            self._conn.commit()

    def count(self, series_key: str | None = None) -> int:
        if series_key is None:
            return self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM translations WHERE series_key = ?", (series_key,)
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()


def semantic_hints_for_translate(
    store: MemoryStore | None,
    source_text: str,
    series_key: str,
    *,
    top_k: int = 3,
    min_source_chars: int = 64,
) -> list[tuple[str, str]] | None:
    """Fuzzy recall rows above similarity threshold — skipped for short OCR (too many bad matches).

    Keeps unrelated long „past translations” out of short-bubble captions.
    """
    if store is None:
        return None
    s = source_text.strip()
    if not s or len(s) < max(16, min_source_chars):
        return None
    rows = store.search(s, top_k=top_k, series_key=series_key)
    return rows if rows else None
