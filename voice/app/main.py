from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import speech


@asynccontextmanager
async def lifespan(app: FastAPI):
    speech.ensure_models()
    yield


app = FastAPI(title="reachy-voice", lifespan=lifespan)


class Say(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/warm")
def warm():
    """Load both models. Called by setup so the first question is not the slow one."""
    speech.warm()
    return {"ok": True}


# Whisper and Piper block for seconds at a time. The sync handlers below are run
# in a worker thread by FastAPI automatically; /transcribe has to be async to
# read the request body, so it hands the blocking part to a thread itself.
@app.post("/transcribe")
async def transcribe(request: Request):
    audio = await request.body()
    return {"text": await run_in_threadpool(speech.transcribe, audio)}


@app.post("/speak")
def say(body: Say):
    return Response(content=speech.speak(body.text), media_type="audio/wav")
