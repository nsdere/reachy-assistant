from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import budget, live, memory, vectors
from .llm import ask_cloud, ask_local


@asynccontextmanager
async def lifespan(app: FastAPI):
    vectors.ensure_collections()
    memory.ensure_schema()
    yield


app = FastAPI(title="reachy-assistant", lifespan=lifespan)


class Ingest(BaseModel):
    text: str
    source: str
    private: bool = True


class Query(BaseModel):
    query: str


class Question(BaseModel):
    question: str


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/budget")
async def budget_status():
    return {"spent_today": round(budget.spent_today(), 4),
            "remaining": round(budget.remaining(), 4)}


@app.post("/ingest")
async def ingest(body: Ingest):
    store = vectors.store_private if body.private else vectors.store_public
    count = await store(body.text, body.source)
    return {"chunks": count, "collection": "private" if body.private else "public"}


@app.post("/search")
async def search(body: Query):
    """Tool endpoint for GPT-Live. Public collection only — see vectors.py."""
    return {"results": await vectors.search_public(body.query)}


@app.post("/ask")
async def ask(body: Question):
    """The 'Hey Mando' path: local transcription already done, text goes to the cloud."""
    if budget.remaining() <= 0:
        # Budget exhaustion changes the model, never the data scope. A question
        # asked on the public path stays on public documents and the public
        # thread, or "Hey Mando" would start reading private files aloud to
        # whoever is in the room.
        context = await vectors.search_public(body.question)
        answer = await ask_local(body.question, context, memory.recent_for_cloud())
        memory.add(memory.CLOUD, body.question, answer)
        return {"answer": answer, "source": "local", "reason": "daily budget spent"}

    context = await vectors.search_public(body.question)
    answer, cost = await ask_cloud(body.question, context, memory.recent_for_cloud())
    memory.add(memory.CLOUD, body.question, answer)
    budget.record(cost)
    return {"answer": answer, "source": "cloud", "cost_usd": round(cost, 6)}


@app.post("/private/ask")
async def private_ask(body: Question):
    """The 'Saturn' path. Nothing here may touch the network."""
    context = await vectors.search_private(body.question)
    answer = await ask_local(body.question, context, memory.recent_for_local())
    memory.add(memory.LOCAL, body.question, answer)
    return {"answer": answer, "source": "local"}


@app.post("/forget")
async def forget():
    """Ends the current conversation. Wire this to 'Mando, forget that'."""
    return {"dropped": memory.forget_active()}


@app.websocket("/live")
async def live_session(ws: WebSocket):
    """The 'Mando live' path.

    Client sends 16 kHz mono PCM16 as binary frames and receives the model's
    audio back in the same format. JSON text frames carry status only.
    """
    await ws.accept()

    if budget.remaining() <= 0:
        await ws.send_json({"type": "refused", "reason": "daily budget spent"})
        await ws.close()
        return

    try:
        summary = await live.run(ws)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await ws.send_json({"type": "ended", "reason": f"{type(exc).__name__}: {exc}"})
        await ws.close()
        return

    await ws.send_json(summary)
    await ws.close()
