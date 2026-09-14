import uuid

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import COLLECTION, EMBED_MODEL, OLLAMA_URL, QDRANT_URL

client = QdrantClient(url=QDRANT_URL)


def embed(texts):
    r = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["embeddings"]


def ensure_collection(dim):
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def chunk(text, size=900, overlap=150):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 2 <= size:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = (current[-overlap:] + "\n\n" + p) if current else p
    if current:
        chunks.append(current)
    return chunks


def replace_source(source, chunks, vectors, extra_payload=None):
    """Upsert one file's chunks, dropping any chunks it had before."""
    client.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="source", match=MatchValue(value=source))]
        ),
    )
    points = [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}#{i}")),
            vector=vec,
            payload={"source": source, "text": text, **(extra_payload or {})},
        )
        for i, (text, vec) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection_name=COLLECTION, points=points)


def search(question, limit=5, source_type=None):
    vector = embed([question])[0]
    query_filter = None
    if source_type:
        query_filter = Filter(
            must=[FieldCondition(key="type", match=MatchValue(value=source_type))]
        )
    result = client.query_points(
        collection_name=COLLECTION,
        query=vector,
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
    )
    return result.points
