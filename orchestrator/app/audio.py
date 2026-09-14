"""Sample-rate glue between the robot and GPT-Live.

Reachy Mini works at 16 kHz; GPT-Live speaks 24 kHz PCM16. Both directions are
exact 3:2 ratios, so polyphase resampling is cheap and clean. Keeping this on
the server means the robot client never has to care.
"""

import numpy as np
from scipy.signal import resample_poly

ROBOT_RATE = 16_000
LIVE_RATE = 24_000


def _resample(pcm: bytes, up: int, down: int) -> bytes:
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return b""
    resampled = resample_poly(samples.astype(np.float32), up, down)
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


def to_live(pcm16_at_16k: bytes) -> bytes:
    return _resample(pcm16_at_16k, 3, 2)


def from_live(pcm16_at_24k: bytes) -> bytes:
    return _resample(pcm16_at_24k, 2, 3)
