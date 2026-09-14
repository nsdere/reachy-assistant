"""The "Mando live" path: relay audio between the robot and GPT-Live-1.

The robot never talks to OpenAI directly. Everything goes through here because
three things have to live on this side of the wire: the API key, the budget
(a session bills by the minute, so nothing untrusted decides when one opens or
closes), and the document search — which is answered from the public collection
and no other.
"""

import asyncio
import base64
import contextlib
import json
import time

import websockets

from . import budget, vectors
from .audio import LIVE_RATE, from_live, to_live
from .config import settings

# --- wire protocol ----------------------------------------------------------
# These strings follow OpenAI's realtime event protocol, which GPT-Live shares.
# The model reference states GPT-Live-1 is served from v1/live rather than
# v1/realtime, so check these against the Live reference before the first billed
# run - LIVE_URL is already overridable from .env. Nothing else in this file
# depends on the exact spelling.
SESSION_UPDATE = "session.update"
AUDIO_APPEND = "input_audio_buffer.append"
AUDIO_DELTA = "response.output_audio.delta"
SPEECH_STARTED = "input_audio_buffer.speech_started"
FUNCTION_CALL_DONE = "response.function_call_arguments.done"
ITEM_CREATE = "conversation.item.create"
RESPONSE_CREATE = "response.create"
ERROR = "error"
# ---------------------------------------------------------------------------

INSTRUCTIONS = (
    "You are a home assistant speaking out loud. Keep answers to a sentence or "
    "two unless asked for detail. When the question is about the user's own "
    "notes, plans or documents, call search_public_docs before answering."
)

# Only the public collection is offered. search_private_docs is not registered
# and must never be: a live session has no function that reaches Saturn's data.
SEARCH_TOOL = {
    "type": "function",
    "name": "search_public_docs",
    "description": "Search the user's own notes and documents for relevant passages.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for"},
        },
        "required": ["query"],
    },
}


def _session_config() -> dict:
    return {
        "type": SESSION_UPDATE,
        "session": {
            "type": "realtime",
            "model": settings.live_model,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": LIVE_RATE},
                    "turn_detection": {"type": "semantic_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcm"},
                    "voice": settings.live_voice,
                },
            },
            "instructions": INSTRUCTIONS,
            "tools": [SEARCH_TOOL],
        },
    }


class Session:
    """One live conversation. Ends on silence, on budget, or when the client leaves."""

    def __init__(self, client) -> None:
        self.client = client
        self.started = time.monotonic()
        self.last_voice = time.monotonic()
        self.reason = "client left"
        self.searches = 0

    @property
    def minutes(self) -> float:
        return (time.monotonic() - self.started) / 60

    @property
    def cost(self) -> float:
        return self.minutes * settings.live_cost_per_minute

    def affordable(self) -> bool:
        return self.cost < budget.remaining()

    async def _client_to_live(self, live) -> None:
        while True:
            chunk = await self.client.receive_bytes()
            payload = base64.b64encode(to_live(chunk)).decode()
            await live.send(json.dumps({"type": AUDIO_APPEND, "audio": payload}))

    async def _live_to_client(self, live) -> None:
        async for raw in live:
            event = json.loads(raw)
            kind = event.get("type")

            if kind == AUDIO_DELTA:
                self.last_voice = time.monotonic()
                await self.client.send_bytes(from_live(base64.b64decode(event["delta"])))

            elif kind == SPEECH_STARTED:
                self.last_voice = time.monotonic()

            elif kind == FUNCTION_CALL_DONE:
                await self._answer_search(live, event)

            elif kind == ERROR:
                self.reason = f"api error: {event.get('error', {}).get('message', '?')}"
                return

    async def _answer_search(self, live, event: dict) -> None:
        if event.get("name") != SEARCH_TOOL["name"]:
            return
        query = json.loads(event.get("arguments") or "{}").get("query", "")
        passages = await vectors.search_public(query)
        self.searches += 1

        await live.send(
            json.dumps(
                {
                    "type": ITEM_CREATE,
                    "item": {
                        "type": "function_call_output",
                        "call_id": event.get("call_id"),
                        "output": json.dumps({"passages": passages}),
                    },
                }
            )
        )
        await live.send(json.dumps({"type": RESPONSE_CREATE}))

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(1)
            if time.monotonic() - self.last_voice > settings.live_idle_seconds:
                self.reason = "idle"
                return
            if not self.affordable():
                self.reason = "daily budget reached"
                return


async def run(client) -> dict:
    """Bridge one client socket to GPT-Live. Returns a summary of the session."""
    session = Session(client)
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    try:
        async with websockets.connect(
            settings.live_url, additional_headers=headers
        ) as live:
            await live.send(json.dumps(_session_config()))
            await client.send_json({"type": "started"})

            tasks = [
                asyncio.create_task(coro)
                for coro in (
                    session._client_to_live(live),
                    session._live_to_client(live),
                    session._watchdog(),
                )
            ]
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                if task.exception() and not isinstance(
                    task.exception(), websockets.ConnectionClosed
                ):
                    raise task.exception()
    finally:
        # Recorded whatever happened - a session that crashed still cost money.
        budget.record(session.cost)

    return {
        "type": "ended",
        "reason": session.reason,
        "seconds": round(session.minutes * 60, 1),
        "cost_usd": round(session.cost, 4),
        "searches": session.searches,
    }
