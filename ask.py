#!/usr/bin/env python3
"""Ask a question against your local documents. Nothing leaves this machine."""

import sys

import requests

from config import ANSWER_MODEL, OLLAMA_URL
from rag import search

PROMPT = """Answer the question using only the context below. If the context
does not contain the answer, say you don't know.

Context:
{context}

Question: {question}

Answer:"""


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        sys.exit('Usage: python ask.py "your question"')

    hits = search(question)
    if not hits:
        sys.exit("Nothing indexed yet — run ingest_notes.py first.")

    context = "\n\n---\n\n".join(h.payload["text"] for h in hits)
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": ANSWER_MODEL,
            "prompt": PROMPT.format(context=context, question=question),
            "stream": False,
        },
        timeout=600,
    )
    r.raise_for_status()

    print(r.json()["response"].strip())
    print("\nSources:")
    for h in hits:
        print(f"  [{h.score:.2f}] {h.payload['source']}")


if __name__ == "__main__":
    main()
