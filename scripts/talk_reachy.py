#!/usr/bin/env python3
"""Speak a question at Reachy Mini and hear the answer through its speaker.

Robot-audio equivalent of talk.sh (which uses the server's own sound card).
This is a Phase 3 test path pending the wake-word client in Phase 5, same as
talk.sh - it just swaps the hardware source.

    ./scripts/talk_reachy.py --robot-host 192.168.1.212               private mode
    ./scripts/talk_reachy.py --robot-host 192.168.1.212 --mode public
    ./scripts/talk_reachy.py --robot-host 192.168.1.212 --silence-seconds 1.5

Recording length is dynamic: it starts on the first loud-enough chunk and
stops --silence-seconds after the last one, capped at --max-seconds. This is
an energy-threshold VAD on the raw samples, not the robot'"'"'s hardware DoA -
get_DoA() needs direct USB access to the XMOS chip and returns None over a
network/WebRTC connection, so it is not usable from a remote client like this
one.
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


def record(
    mini,
    max_seconds: float,
    silence_seconds: float,
    speech_threshold: float,
) -> bytes:
    """Record from first loud-enough chunk until silence_seconds of quiet after it.

    Capped at max_seconds total even if speech never clearly starts or stops.
    """
    mini.media.start_recording()
    try:
        chunks = []
        t_start = time.monotonic()
        speech_started = False
        last_voice_time = t_start
        while time.monotonic() - t_start < max_seconds:
            samples = mini.media.get_audio_sample()
            if samples is None or len(samples) == 0:
                time.sleep(0.01)
                continue
            chunks.append(samples)

            mono = samples.mean(axis=1) if samples.ndim > 1 else samples
            rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
            now = time.monotonic()
            if rms > speech_threshold:
                speech_started = True
                last_voice_time = now
            if speech_started and (now - last_voice_time) > silence_seconds:
                break
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
    parser.add_argument("--max-seconds", type=float, default=15.0, help="Hard cap on recording length")
    parser.add_argument("--silence-seconds", type=float, default=1.0, help="Stop this long after the last loud chunk")
    parser.add_argument("--speech-threshold", type=float, default=0.01, help="RMS level (0-1) counted as speech, not silence")
    parser.add_argument("--volume", type=float, default=6.0)
    parser.add_argument("--orchestrator-url", default="http://localhost:8000")
    parser.add_argument("--voice-url", default="http://localhost:8001")
    args = parser.parse_args()

    endpoint = "private/ask" if args.mode == "private" else "ask"

    with ReachyMini(
        host=args.robot_host, connection_mode="network", media_backend="webrtc"
    ) as mini:
        print(f"[{args.mode}] listening (up to {args.max_seconds:.0f}s, stops {args.silence_seconds:.1f}s after you go quiet)...", flush=True)
        print("RECORDING_STARTED", flush=True)
        t_record0 = time.perf_counter()
        wav_bytes = record(mini, args.max_seconds, args.silence_seconds, args.speech_threshold)
        t_record = time.perf_counter() - t_record0
        print(f"heard {t_record:.1f}s of audio")
        if not wav_bytes:
            print("heard nothing - check the robot mic", file=sys.stderr)
            return 1

        t0 = time.perf_counter()
        r = requests.post(
            f"{args.voice_url}/transcribe",
            data=wav_bytes,
            headers={"content-type": "audio/wav"},
            timeout=180,
        )
        r.raise_for_status()
        t_transcribe = time.perf_counter() - t0
        question = r.json()["text"]
        if not question:
            print("heard nothing (empty transcript)", file=sys.stderr)
            return 1
        print(f"you:       {question}")

        t0 = time.perf_counter()
        r = requests.post(
            f"{args.orchestrator_url}/{endpoint}",
            json={"question": question},
            timeout=180,
        )
        r.raise_for_status()
        t_ask = time.perf_counter() - t0
        reply = r.json()
        print(f"{reply.get('source')}: {reply.get('answer')}")

        t0 = time.perf_counter()
        r = requests.post(
            f"{args.voice_url}/speak",
            json={"text": reply["answer"]},
            timeout=180,
        )
        r.raise_for_status()
        t_speak = time.perf_counter() - t0

        print("playing answer...")
        t0 = time.perf_counter()
        play(mini, r.content, args.volume)
        t_play = time.perf_counter() - t0
        print("done")

        print(
            f"\ntiming: record={t_record:.2f}s transcribe={t_transcribe:.2f}s "
            f"llm_ask={t_ask:.2f}s speak={t_speak:.2f}s playback={t_play:.2f}s "
            f"total={t_record + t_transcribe + t_ask + t_speak + t_play:.2f}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
