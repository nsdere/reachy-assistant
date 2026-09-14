import uuid

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .config import settings

PUBLIC = "public_docs"
PRIVATE = "private_docs"
DIM = 768

client = QdrantClient(url=settings.qdrant_url)


def ensure_collections() -> None:
    for name in (PUBLIC, PRIVATE):
        if not client.collection_exists(name):
            client.create_collection(
                name, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE)
            )


async def embed(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(
            f"{settings.ollama_url}/api/embed",
            json={"model": settings.embed_model, "input": texts},
        )
        r.raise_for_status()
        return r.json()["embeddings"]


def chunk(text: str, size: int = 800) -> list[str]:
    parts, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) > size and buf:
            parts.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        parts.append(buf.strip())
    return parts


async def _store(collection: str, text: str, source: str) -> int:
    chunks = chunk(text)
    vectors = await embed(chunks)
    client.upsert(
        collection,
        points=[
            PointStruct(
                id=str(uuid.uuid4()),
                vector=v,
                payload={"text": c, "source": source},
            )
            for c, v in zip(chunks, vectors)
        ],
    )
    return len(chunks)


async def _search(collection: str, query: str, limit: int) -> list[str]:
    vector = (await embed([query]))[0]
    hits = client.query_points(collection, query=vector, limit=limit).points
    return [h.payload["text"] for h in hits]


def _delete(collection: str, source: str) -> None:
    """Drops every chunk from one source so a re-ingest replaces rather than duplicates."""
    client.delete(
        collection,
        points_selector=Filter(
            must=[FieldCondition(key="source", match=MatchValue(value=source))]
        ),
    )


# The two collections are kept behind separate functions on purpose. Cloud-facing
# code imports only the `public_*` pair, so no bug in a cloud path can reach
# private vectors — the code path simply does not exist there.

async def store_public(text: str, source: str) -> int:
    return await _store(PUBLIC, text, source)


async def store_private(text: str, source: str) -> int:
    return await _store(PRIVATE, text, source)


async def search_public(query: str, limit: int = 5) -> list[str]:
    return await _search(PUBLIC, query, limit)


async def search_private(query: str, limit: int = 5) -> list[str]:
    return await _search(PRIVATE, query, limit)


def delete_public(source: str) -> None:
    _delete(PUBLIC, source)


def delete_private(source: str) -> None:
    _delete(PRIVATE, source)
