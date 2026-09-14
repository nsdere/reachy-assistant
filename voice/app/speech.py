"""Whisper and Piper, both on the CPU, both fully local.

The only network this service ever needs is the one-time model download in
ensure_models(). After that it runs with the machine unplugged — which is what
makes the Saturn path's zero-egress claim true.
"""

import io
import subprocess
import sys
import wave
from pathlib import Path

from faster_whisper import WhisperModel
from piper import PiperVoice

from .config import settings

_whisper: WhisperModel | None = None
_piper: PiperVoice | None = None


def voice_path() -> Path:
    return Path(settings.models_dir) / f"{settings.piper_voice}.onnx"


def ensure_models() -> None:
    """Fetch the Piper voice once into the models volume."""
    models = Path(settings.models_dir)
    models.mkdir(parents=True, exist_ok=True)
    if voice_path().exists():
        return
    subprocess.run(
        [sys.executable, "-m", "piper.download_voices", settings.piper_voice],
        cwd=models,
        check=True,
    )


def _load_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type=settings.whisper_compute,
            download_root=settings.models_dir,
        )
    return _whisper


def _load_piper() -> PiperVoice:
    global _piper
    if _piper is None:
        ensure_models()
        _piper = PiperVoice.load(str(voice_path()))
    return _piper


def warm() -> None:
    """Load both models now so the first real question is not the slow one."""
    _load_whisper()
    _load_piper()


def transcribe(audio: bytes) -> str:
    segments, _info = _load_whisper().transcribe(
        io.BytesIO(audio),
        language=settings.whisper_language or None,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def speak(text: str) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        _load_piper().synthesize_wav(text, wav)
    return buffer.getvalue()
