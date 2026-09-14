"""Sample-rate conversion between Reachy Mini (16 kHz) and GPT-Live (24 kHz).

    docker compose run --rm orchestrator python -m tests.test_audio
"""

import numpy as np

from app.audio import LIVE_RATE, ROBOT_RATE, from_live, to_live


def main() -> None:
    t = np.arange(ROBOT_RATE // 10) / ROBOT_RATE
    tone = (np.sin(2 * np.pi * 440 * t) * 20000).astype(np.int16).tobytes()

    up = to_live(tone)
    back = from_live(up)

    expected_up = len(tone) // 2 * LIVE_RATE // ROBOT_RATE
    assert len(up) // 2 == expected_up, f"upsample gave {len(up) // 2}, want {expected_up}"
    assert len(back) // 2 == len(tone) // 2, "round trip changed the sample count"
    print(f"rates       16k -> {len(up) // 2} samples at 24k -> back to {len(back) // 2}")

    original = np.frombuffer(tone, dtype=np.int16).astype(float)
    returned = np.frombuffer(back, dtype=np.int16).astype(float)
    # Edges ring on any resampler; the middle is what carries the speech.
    error = np.abs(original - returned)[80:-80].max() / 20000
    assert error < 0.05, f"round trip distorts the signal by {error:.1%}"
    print(f"fidelity    {error:.2%} distortion through the round trip")

    assert to_live(b"") == b"" and from_live(b"") == b""
    print("empty       silent chunks pass through")

    print("\nPASS - resampling")


if __name__ == "__main__":
    main()
