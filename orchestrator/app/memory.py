import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .config import settings

WINDOW_SECONDS = 180
MAX_TURNS = 4

CLOUD = "cloud"
LIVE = "live"
LOCAL = "local"

# Memory flows one way only. Saturn may read every thread, because a local answer
# never leaves the box. The cloud path may read nothing but its own, or private
# content would ride along on the next request to Anthropic.
_CLOUD_MAY_READ = (CLOUD,)
_LOCAL_MAY_READ = (CLOUD, LIVE, LOCAL)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(settings.memory_file)


def ensure_schema() -> None:
    Path(settings.memory_file).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS turns ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " mode TEXT NOT NULL,"
            " question TEXT NOT NULL,"
            " answer TEXT NOT NULL,"
            " at REAL NOT NULL)"
        )


def _recent(modes: tuple[str, ...]) -> list[dict]:
    placeholders = ",".join("?" for _ in modes)
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT question, answer FROM turns"
            f" WHERE at > ? AND mode IN ({placeholders})"
            " ORDER BY id DESC LIMIT ?",
            (time.time() - WINDOW_SECONDS, *modes, MAX_TURNS),
        ).fetchall()
    return [
        message
        for question, answer in reversed(rows)
        for message in (
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        )
    ]


def recent_for_cloud() -> list[dict]:
    """The only reader the cloud path may use. Never widen this."""
    return _recent(_CLOUD_MAY_READ)


def recent_for_local() -> list[dict]:
    """Saturn's reader — sees every mode, and its answers stay on the box."""
    return _recent(_LOCAL_MAY_READ)


def add(mode: str, question: str, answer: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO turns (mode, question, answer, at) VALUES (?, ?, ?, ?)",
            (mode, question, answer, time.time()),
        )


def forget_active() -> int:
    """Ends the current conversation. History older than the window survives."""
    with closing(_connect()) as conn, conn:
        return conn.execute(
            "DELETE FROM turns WHERE at > ?", (time.time() - WINDOW_SECONDS,)
        ).rowcount
