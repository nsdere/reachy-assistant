import httpx
from anthropic import AsyncAnthropic

from .config import settings

PROMPT = (
    "You are a home voice assistant. Answer in one or two short spoken sentences. "
    "No markdown, no lists. If context is given and does not cover the question, "
    "answer from your own knowledge."
)

_anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)


def _build(question: str, context: list[str]) -> str:
    if not context:
        return question
    joined = "\n\n".join(context)
    return f"Context:\n{joined}\n\nQuestion: {question}"


async def ask_cloud(
    question: str, context: list[str], history: list[dict]
) -> tuple[str, float]:
    """Returns (answer, cost_usd). Used by the 'Hey Mando' path.

    `history` must come from memory.cloud — never memory.local.
    """
    msg = await _anthropic.messages.create(
        model=settings.cloud_model,
        max_tokens=300,
        system=PROMPT,
        messages=[*history, {"role": "user", "content": _build(question, context)}],
    )
    cost = (msg.usage.input_tokens * 1e-6) + (msg.usage.output_tokens * 5e-6)
    return msg.content[0].text, cost


async def ask_local(question: str, context: list[str], history: list[dict]) -> str:
    """Fully local. Used by the 'Saturn' path — never touches the network."""
    async with httpx.AsyncClient(timeout=300) as http:
        r = await http.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.local_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    *history,
                    {"role": "user", "content": _build(question, context)},
                ],
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
