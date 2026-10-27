#!/usr/bin/env python3
"""Always-on "Hey Mando" through Reachy Mini.

    ./scripts/mando_listen.py --robot-host 192.168.1.212

Listens continuously on the robot's mic, cuts the stream into utterances with
an energy threshold, and transcribes each one locally (voice service). Only a
transcript that starts with the wake phrase is sent on to /ask - everything
else is dropped on this box, so the cloud never hears the room, only the
questions you address to it.

    "Hey Mando, how tall is the Eiffel tower?"   -> answered
    "Hey Mando."  ...  "how tall is it?"          -> "Yes?" then answered
    within FOLLOWUP seconds of an answer          -> answered without the wake phrase

This stands in for the Phase 5 wake-word client until openWakeWord models are
trained: Whisper is the detector, which is slower than a dedicated model but
needs no training. Ctrl-C stops it.
"""

import argparse
import io
import re
import sys
import time
import wave
from math import gcd

import numpy as np
import requests
from reachy_mini import ReachyMini

ROBOT_RATE = 16_000

# Whisper spells the made-up word several ways ("Mendo", "Mondo", "Manda"), and
# a clipped "Hey" comes back as "y", "ayo" or "a" - so any one short word may
# lead. The prefix is optional so "Mando, what time is it" also counts.
WAKE = re.compile(
    r"^\W*(?:[a-z']{1,5}\W+)?"
    r"(?:mando|mendo|mondo|manda|mandu|mandoh|mandou|mendu|mando's)\b\W*",
    re.IGNORECASE,
)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Ears:
    """Turns the robot's continuous mic stream into one utterance at a time."""

    def __init__(self, mini, threshold: float, silence: float, max_seconds: float):
        self.mini = mini
        self.threshold = threshold
        self.silence = silence
        self.max_seconds = max_seconds

    def drain(self) -> None:
        """Drop audio buffered while the robot was talking or thinking."""
        while True:
            s = self.mini.media.get_audio_sample()
            if s is None or len(s) == 0:
                return

    def next_utterance(self, wait_seconds: float | None = None) -> np.ndarray | None:
        """Block until someone speaks and stops. None if wait_seconds pass in silence."""
        preroll: list[np.ndarray] = []  # keep ~0.6 s before onset so a soft "Hey" is whole
        chunks: list[np.ndarray] = []
        started = None
        last_voice = 0.0
        t0 = time.monotonic()

        while True:
            s = self.mini.media.get_audio_sample()
            if s is None or len(s) == 0:
                time.sleep(0.01)
                if started is None and wait_seconds and time.monotonic() - t0 > wait_seconds:
                    return None
                continue

            mono = s.mean(axis=1) if s.ndim > 1 else s
            loud = float(np.sqrt(np.mean(np.square(mono)))) > self.threshold
            now = time.monotonic()

            if started is None:
                preroll.append(mono)
                while sum(len(c) for c in preroll) > ROBOT_RATE * 0.6:
                    preroll.pop(0)
                if loud:
                    started, last_voice = now, now
                    chunks = preroll[:]
                elif wait_seconds and now - t0 > wait_seconds:
                    return None
                continue

            chunks.append(mono)
            if loud:
                last_voice = now
            if now - last_voice > self.silence or now - started > self.max_seconds:
                audio = np.concatenate(chunks)
                # A door slam or a cough: too short to be a question.
                return audio if len(audio) > ROBOT_RATE * 0.5 else None


def to_wav(mono: np.ndarray) -> bytes:
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(ROBOT_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def play(mini, wav_bytes: bytes, volume: float) -> None:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != ROBOT_RATE:
        from scipy.signal import resample_poly

        g = gcd(rate, ROBOT_RATE)
        samples = resample_poly(samples, ROBOT_RATE // g, rate // g)
    samples = np.clip(samples * volume, -1.0, 1.0).astype(np.float32)

    mini.media.start_playing()
    try:
        mini.media.push_audio_sample(samples.reshape(-1, 1))
        # push_audio_sample is non-blocking - wait out the clip or it gets cut off.
        time.sleep(len(samples) / ROBOT_RATE + 0.3)
    finally:
        mini.media.stop_playing()


class Mando:
    def __init__(self, mini, args):
        self.mini = mini
        self.args = args
        self.ears = Ears(mini, args.speech_threshold, args.silence_seconds, args.max_seconds)

    def transcribe(self, audio: np.ndarray) -> str:
        r = requests.post(
            f"{self.args.voice_url}/transcribe",
            data=to_wav(audio),
            headers={"content-type": "audio/wav"},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["text"].strip()

    def say(self, text: str) -> None:
        r = requests.post(f"{self.args.voice_url}/speak", json={"text": text}, timeout=180)
        r.raise_for_status()
        play(self.mini, r.content, self.args.volume)
        self.ears.drain()

    def answer(self, question: str) -> None:
        log(f"you:   {question}")
        try:
            r = requests.post(
                f"{self.args.orchestrator_url}/ask", json={"question": question}, timeout=120
            )
            r.raise_for_status()
            reply = r.json()
        except requests.RequestException as e:
            log(f"ask failed: {e}")
            self.say("Sorry, I couldn't get an answer just now.")
            return
        cost = f" ${reply['cost_usd']}" if "cost_usd" in reply else ""
        log(f"mando: {reply['answer']}  [{reply.get('source')}{cost}]")
        self.say(reply["answer"])

    def listen_for_question(self, wait: float) -> str | None:
        audio = self.ears.next_utterance(wait_seconds=wait)
        if audio is None:
            return None
        text = self.transcribe(audio)
        return text or None

    def run(self) -> None:
        log("listening - say \"Hey Mando, ...\"  (Ctrl-C to stop)")
        while True:
            audio = self.ears.next_utterance()
            if audio is None:
                continue
            text = self.transcribe(audio)
            match = WAKE.match(text)
            if not match:
                if text and self.args.verbose:
                    log(f"(ignored: {text})")
                continue

            log(f"heard: {text}")
            question = text[match.end():].strip()
            if len(question) < 3:
                # People pause after the wake phrase, so the question is often
                # already on its way. Take it if it is; only prompt if not, since
                # say() drops whatever is spoken over it.
                question = self.listen_for_question(1.5)
            if not question or len(question) < 3:
                self.say("Yes?")
                question = self.listen_for_question(self.args.followup_seconds + 3)
                if not question:
                    log("(no question after wake phrase)")
                    continue
            self.answer(question)

            # Follow-up window: keep answering without the wake phrase until
            # the room goes quiet for FOLLOWUP seconds.
            while True:
                follow = self.listen_for_question(self.args.followup_seconds)
                if not follow:
                    break
                # Saying the wake phrase again inside the window is fine too.
                m = WAKE.match(follow)
                follow = follow[m.end():].strip() if m else follow
                if len(follow) >= 3:
                    self.answer(follow)
            log("listening - say \"Hey Mando, ...\"")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--robot-host", required=True, help="Reachy Mini address")
    p.add_argument("--speech-threshold", type=float, default=0.01, help="RMS (0-1) counted as speech")
    p.add_argument("--silence-seconds", type=float, default=1.0, help="Quiet that ends an utterance")
    p.add_argument("--max-seconds", type=float, default=15.0, help="Longest single utterance")
    p.add_argument("--followup-seconds", type=float, default=6.0, help="Window for follow-ups without the wake phrase")
    p.add_argument("--volume", type=float, default=6.0)
    p.add_argument("--orchestrator-url", default="http://localhost:8000")
    p.add_argument("--voice-url", default="http://localhost:8001")
    p.add_argument("--verbose", action="store_true", help="Print what was heard and ignored")
    args = p.parse_args()

    with ReachyMini(host=args.robot_host, connection_mode="network", media_backend="webrtc") as mini:
        mini.media.start_recording()
        try:
            Mando(mini, args).run()
        except KeyboardInterrupt:
            log("stopped")
        finally:
            mini.media.stop_recording()
    return 0


if __name__ == "__main__":
    sys.exit(main())
