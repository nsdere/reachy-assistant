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
# GPT-Live is its own endpoint (v1/live/sessions), not the older Realtime API
# (v1/realtime) - the two do not share an event vocabulary. GPT-Live itself
# only does voice I/O; reasoning and tool calls are delegated to a backend
# Responses model (session.delegation.type = "responses"), whose function
# calls arrive wrapped in a response.event envelope. Confirm this against the
# current GPT-Live reference before the first billed run - model names and
# event shapes are the two things most likely to have moved since this was
# written. Nothing else in this file depends on the exact spelling.
SESSION_START = "session.start"
SESSION_STARTED = "session.started"
SESSION_CLOSED = "session.closed"
AUDIO_APPEND = "session.input_audio.append"
AUDIO_DELTA = "session.output_audio.delta"
INPUT_TRANSCRIPT_DELTA = "session.input_transcript.delta"
RESPONSE_EVENT = "response.event"
OUTPUT_ITEM_DONE = "response.output_item.done"
RESPONSE_ITEM_CREATE = "response.item.create"
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
        "type": SESSION_START,
        "session": {
            "model": settings.live_model,
            "instructions": INSTRUCTIONS,
            "audio": {
                "output": {"voice": settings.live_voice},
                "format": "pcm16",
            },
            # search_public_docs is declared on the backend Responses model,
            # not on the voice model itself - GPT-Live has no tools of its own.
            "delegation": {
                "type": "responses",
                "responses": {
                    "model": settings.live_delegate_model,
                    "instructions": INSTRUCTIONS,
                    "tools": [SEARCH_TOOL],
                    "tool_choice": "auto",
                },
            },
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

            elif kind == INPUT_TRANSCRIPT_DELTA:
                # No dedicated speech-start/VAD event is documented for
                # GPT-Live; a transcript fragment is the closest signal that
                # the user is actively talking, so the idle watchdog treats
                # it the same as outgoing audio.
                self.last_voice = time.monotonic()

            elif kind == RESPONSE_EVENT:
                await self._handle_response_event(live, event.get("event") or {})

            elif kind == SESSION_CLOSED:
                self.reason = event.get("reason") or self.reason
                return

            elif kind == ERROR:
                self.reason = f"api error: {event.get('error', {}).get('message', '?')}"
                return

    async def _handle_response_event(self, live, nested: dict) -> None:
        if nested.get("type") != OUTPUT_ITEM_DONE:
            return
        item = nested.get("item") or {}
        if item.get("type") != "function_call" or item.get("name") != SEARCH_TOOL["name"]:
            return
        await self._answer_search(live, item)

    async def _answer_search(self, live, item: dict) -> None:
        query = json.loads(item.get("arguments") or "{}").get("query", "")
        passages = await vectors.search_public(query)
        self.searches += 1

        await live.send(
            json.dumps(
                {
                    "type": RESPONSE_ITEM_CREATE,
                    "item": {
                        "type": "function_call_output",
                        "call_id": item.get("call_id"),
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

            # Wait for the server to confirm the session before telling the
            # local client it can start streaming audio.
            ack = json.loads(await live.recv())
            if ack.get("type") != SESSION_STARTED:
                reason = ack.get("error", {}).get("message") or ack.get("type") or "?"
                raise RuntimeError(f"session did not start: {reason}")

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
