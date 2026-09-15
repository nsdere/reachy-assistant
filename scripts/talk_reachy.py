#!/usr/bin/env python3
"""Speak a question at Reachy Mini and hear the answer through its speaker.

Robot-audio equivalent of talk.sh (which uses the server's own sound card).
This is a Phase 3 test path pending the wake-word client in Phase 5, same as
talk.sh - it just swaps the hardware source.

    ./scripts/talk_reachy.py --robot-host 192.168.1.212               private mode, 6s
    ./scripts/talk_reachy.py --robot-host 192.168.1.212 --mode public
    ./scripts/talk_reachy.py --robot-host 192.168.1.212 --seconds 10
"""

import argparse
import io
import sys
import time
import wave
from math import gcd

import numpy as np
import requests
from reachy_mini import ReachyMini

ROBOT_RATE = 16_000


def record(mini, seconds: float) -> bytes:
    mini.media.start_recording()
    try:
        chunks = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds:
            samples = mini.media.get_audio_sample()
            if samples is not None and len(samples) > 0:
                chunks.append(samples)
            else:
                time.sleep(0.01)
    finally:
        mini.media.stop_recording()

    if not chunks:
        return b""
    audio = np.concatenate(chunks, axis=0)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    pcm16 = np.clip(mono, -1.0, 1.0) * 32767
    pcm16 = pcm16.astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(ROBOT_RATE)
        wav_out.writeframes(pcm16.tobytes())
    return buf.getvalue()


def play(mini, wav_bytes: bytes, volume: float) -> None:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_in:
        rate = wav_in.getframerate()
        raw = wav_in.readframes(wav_in.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if rate != ROBOT_RATE:
        from scipy.signal import resample_poly

        g = gcd(rate, ROBOT_RATE)
        samples = resample_poly(samples, ROBOT_RATE // g, rate // g)

    samples = np.clip(samples * volume, -1.0, 1.0).astype(np.float32)

    mini.media.start_playing()
    try:
        mini.media.push_audio_sample(samples.reshape(-1, 1))
        time.sleep(len(samples) / ROBOT_RATE + 0.3)
    finally:
        mini.media.stop_playing()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-host", required=True, help="Reachy Mini address")
    parser.add_argument("--mode", choices=("private", "public"), default="private")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--volume", type=float, default=6.0)
    parser.add_argument("--orchestrator-url", default="http://localhost:8000")
    parser.add_argument("--voice-url", default="http://localhost:8001")
    args = parser.parse_args()

    endpoint = "private/ask" if args.mode == "private" else "ask"

    with ReachyMini(
        host=args.robot_host, connection_mode="network", media_backend="webrtc"
    ) as mini:
        print(f"[{args.mode}] listening for {args.seconds}s...")
        wav_bytes = record(mini, args.seconds)
        if not wav_bytes:
            print("heard nothing - check the robot mic", file=sys.stderr)
            return 1

        r = requests.post(
            f"{args.voice_url}/transcribe",
            data=wav_bytes,
            headers={"content-type": "audio/wav"},
            timeout=180,
        )
        r.raise_for_status()
        question = r.json()["text"]
        if not question:
            print("heard nothing (empty transcript)", file=sys.stderr)
            return 1
        print(f"you:       {question}")

        r = requests.post(
            f"{args.orchestrator_url}/{endpoint}",
            json={"question": question},
            timeout=180,
        )
        r.raise_for_status()
        reply = r.json()
        print(f"{reply.get('source')}: {reply.get('answer')}")

        r = requests.post(
            f"{args.voice_url}/speak",
            json={"text": reply["answer"]},
            timeout=180,
        )
        r.raise_for_status()

        print("playing answer...")
        play(mini, r.content, args.volume)
        print("done")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
