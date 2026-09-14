#!/usr/bin/env python3
"""Ingest a folder of notes (.md / .txt) into Qdrant. Safe to re-run."""

import sys
from pathlib import Path

from config import NOTES_DIR
from rag import chunk, embed, ensure_collection, replace_source

EXTENSIONS = {".md", ".txt"}


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else NOTES_DIR)
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    files = [
        p
        for p in root.rglob("*")
        if p.suffix.lower() in EXTENSIONS
        and p.is_file()
        and not any(part.startswith(".") for part in p.parts)
    ]
    if not files:
        sys.exit(f"No .md or .txt files found under {root}")

    print(f"Found {len(files)} files under {root}")
    total = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        chunks = chunk(text)
        vectors = embed(chunks)
        ensure_collection(len(vectors[0]))
        replace_source(str(path), chunks, vectors, {"type": "notes"})
        total += len(chunks)
        print(f"  {path.name}: {len(chunks)} chunks")

    print(f"\nDone. {total} chunks indexed.")


if __name__ == "__main__":
    main()
