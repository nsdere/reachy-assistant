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


def _cost(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * settings.cloud_input_per_mtok
        + output_tokens * settings.cloud_output_per_mtok
    ) / 1e6


async def ask_cloud(
    question: str, context: list[str], history: list[dict]
) -> tuple[str, float]:
    """Returns (answer, cost_usd). Used by the 'Hey Mando' path.

    `history` must come from memory.cloud — never memory.local.
    """
    messages = [*history, {"role": "user", "content": _build(question, context)}]
    if settings.cloud_provider == "openai":
        return await _ask_openai(messages)
    return await _ask_anthropic(messages)


async def _ask_anthropic(messages: list[dict]) -> tuple[str, float]:
    msg = await _anthropic.messages.create(
        model=settings.cloud_model,
        max_tokens=300,
        system=PROMPT,
        messages=messages,
    )
    return msg.content[0].text, _cost(msg.usage.input_tokens, msg.usage.output_tokens)


async def _ask_openai(messages: list[dict]) -> tuple[str, float]:
    # Responses API: the gpt-6 family is not offered on Chat Completions.
    # max_output_tokens covers reasoning tokens too, so it is set well above
    # what a two-sentence answer needs.
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.cloud_model,
                "instructions": PROMPT,
                "input": messages,
                "reasoning": {"effort": settings.cloud_reasoning_effort},
                "max_output_tokens": 2000,
                "store": False,
            },
        )
        r.raise_for_status()
        data = r.json()

    answer = " ".join(
        part["text"]
        for item in data.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ).strip()
    usage = data.get("usage") or {}
    return answer, _cost(usage.get("input_tokens", 0), usage.get("output_tokens", 0))


async def ask_local(question: str, context: list[str], history: list[dict]) -> str:
    """Fully local. Used by the 'Saturn' path — never touches the network."""
    async with httpx.AsyncClient(timeout=300) as http:
        r = await http.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.local_model,
                "stream": False,
                "think": False,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    *history,
                    {"role": "user", "content": _build(question, context)},
                ],
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
