#!/usr/bin/env python3
"""Talk to "Mando live". Streams mic audio to the orchestrator and plays the reply.

    pip install websockets numpy sounddevice
    ./scripts/live_client.py                    # server microphone
    ./scripts/live_client.py --source reachy    # Reachy Mini over the network

Ctrl-C ends the session. The orchestrator also closes it on silence or budget.

Everything below the AudioIO seam is hardware. Moving to the robot is the
--source flag, not a rewrite: both sides speak 16 kHz mono PCM16, which is
Reachy Mini's native rate, so no resampling happens here. The 16k <-> 24k
conversion GPT-Live needs lives on the server in app/audio.py.
"""

import argparse
import asyncio
import contextlib
import json
import signal
import sys

import numpy as np
import websockets

RATE = 16_000
CHUNK = 320  # 20 ms - small enough to feel live, large enough to not thrash


class LocalAudio:
    """The server's own sound card, for testing without the robot."""

    def __init__(self) -> None:
        import sounddevice as sd

        self.input = sd.RawInputStream(
            samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK
        )
        self.output = sd.RawOutputStream(
            samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK
        )

    def __enter__(self):
        self.input.start()
        self.output.start()
        return self

    def __exit__(self, *_) -> None:
        self.input.stop()
        self.output.stop()
        self.input.close()
        self.output.close()

    def read(self) -> bytes:
        data, _overflowed = self.input.read(CHUNK)
        return bytes(data)

    def write(self, pcm: bytes) -> None:
        self.output.write(pcm)


class ReachyAudio:
    """Reachy Mini's mic array and speaker, driven over the network.

    The robot works in float32 at 16 kHz and hands back two channels; the wire
    format is mono int16. Hardware echo cancellation is already applied on the
    robot, so the model does not hear itself through the mic.
    """

    def __init__(self, host: str | None = None, volume: float = 1.0) -> None:
        from reachy_mini import ReachyMini

        kwargs = {"media_backend": "webrtc"}
        if host:
            kwargs["host"] = host
            kwargs["connection_mode"] = "network"
        self.mini = ReachyMini(**kwargs)
        self.volume = volume

    def __enter__(self):
        self.mini.__enter__()
        self.mini.media.start_recording()
        self.mini.media.start_playing()
        return self

    def __exit__(self, *exc) -> None:
        self.mini.media.stop_recording()
        self.mini.media.stop_playing()
        self.mini.__exit__(*exc)

    def read(self) -> bytes:
        samples = self.mini.media.get_audio_sample()
        if samples is None or len(samples) == 0:
            return b""
        mono = samples.mean(axis=1) if samples.ndim > 1 else samples
        return (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    def write(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if self.volume != 1.0:
            samples = np.clip(samples * self.volume, -1.0, 1.0)
        self.mini.media.push_audio_sample(samples.reshape(-1, 1))


async def _microphone(ws, audio) -> None:
    loop = asyncio.get_running_loop()
    while True:
        chunk = await loop.run_in_executor(None, audio.read)
        if chunk:
            await ws.send(chunk)
        else:
            await asyncio.sleep(0.005)


async def _speaker(ws, audio) -> str:
    loop = asyncio.get_running_loop()
    async for message in ws:
        if isinstance(message, bytes):
            await loop.run_in_executor(None, audio.write, message)
            continue

        event = json.loads(message)
        kind = event.get("type")
        if kind == "started":
            print("connected - start talking")
        elif kind == "refused":
            return f"refused: {event.get('reason')}"
        elif kind == "ended":
            return (
                f"ended ({event.get('reason')}) after {event.get('seconds')}s, "
                f"${event.get('cost_usd')}, {event.get('searches')} document search(es)"
            )
    return "connection closed"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8000/live")
    parser.add_argument("--source", choices=("local", "reachy"), default="local")
    parser.add_argument("--robot-host", default=None, help="Reachy Mini address")
    parser.add_argument("--volume", type=float, default=6.0, help="Output gain multiplier for the robot speaker (e.g. 2.0 = louder)")
    args = parser.parse_args()

    audio = (
        LocalAudio()
        if args.source == "local"
        else ReachyAudio(args.robot_host, volume=args.volume)
    )

    stop = asyncio.Event()
    with contextlib.suppress(NotImplementedError):
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop.set)

    with audio:
        async with websockets.connect(args.url, max_size=None) as ws:
            mic = asyncio.create_task(_microphone(ws, audio))
            spk = asyncio.create_task(_speaker(ws, audio))
            halt = asyncio.create_task(stop.wait())

            done, pending = await asyncio.wait(
                [mic, spk, halt], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            if spk in done and not spk.cancelled():
                print(spk.result())
            else:
                print("stopped")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
