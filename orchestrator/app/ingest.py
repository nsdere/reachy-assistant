"""Scan the inbox folders and load anything new into Qdrant.

    docker compose run --rm orchestrator python -m app.ingest

Files stay where you put them. Each one is tracked by content hash, so re-running
is free and editing a file replaces its chunks instead of duplicating them.
"""

import asyncio
import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from . import vectors
from .config import settings
from .sources import SUPPORTED, extract


def _ensure_schema() -> None:
    Path(settings.ingest_file).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(settings.ingest_file)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ingested ("
            " source TEXT PRIMARY KEY,"
            " digest TEXT NOT NULL,"
            " chunks INTEGER NOT NULL)"
        )


def _seen_digest(source: str) -> str | None:
    with closing(sqlite3.connect(settings.ingest_file)) as conn:
        row = conn.execute(
            "SELECT digest FROM ingested WHERE source = ?", (source,)
        ).fetchone()
    return row[0] if row else None


def _record(source: str, digest: str, chunks: int) -> None:
    with closing(sqlite3.connect(settings.ingest_file)) as conn, conn:
        conn.execute(
            "INSERT INTO ingested (source, digest, chunks) VALUES (?, ?, ?)"
            " ON CONFLICT(source) DO UPDATE SET digest = excluded.digest,"
            " chunks = excluded.chunks",
            (source, digest, chunks),
        )


def _files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED
    )


async def _ingest_folder(folder: Path, private: bool) -> tuple[int, int]:
    label = "private" if private else "public"
    store = vectors.store_private if private else vectors.store_public
    drop = vectors.delete_private if private else vectors.delete_public

    loaded = skipped = 0
    for path in _files(folder):
        source = f"{label}:{path.relative_to(folder)}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        if _seen_digest(source) == digest:
            skipped += 1
            continue

        text = extract(path).strip()
        if not text:
            print(f"  empty, skipped   {path.name}")
            continue

        drop(source)
        chunks = await store(text, source)
        _record(source, digest, chunks)
        loaded += 1
        print(f"  {chunks:4d} chunks     {path.name}")

    return loaded, skipped


async def main() -> int:
    inbox = Path(settings.inbox_dir)
    private_dir, public_dir = inbox / "private", inbox / "public"
    for folder in (private_dir, public_dir):
        folder.mkdir(parents=True, exist_ok=True)

    _ensure_schema()
    vectors.ensure_collections()

    print("private  (Saturn only — never sent to any cloud provider)")
    private_loaded, private_skipped = await _ingest_folder(private_dir, private=True)
    print("public   (reachable by Hey Mando and Mando live)")
    public_loaded, public_skipped = await _ingest_folder(public_dir, private=False)

    loaded = private_loaded + public_loaded
    skipped = private_skipped + public_skipped
    print(f"\n{loaded} file(s) loaded, {skipped} unchanged")
    if not loaded and not skipped:
        print(f"Nothing found. Put files in {private_dir} or {public_dir}")
        print(f"Supported: {', '.join(sorted(SUPPORTED))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
