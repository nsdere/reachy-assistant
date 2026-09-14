"""The one-way memory rule. If this fails, private content can reach the cloud.

    docker compose run --rm orchestrator python -m tests.test_memory
"""

import os
import sqlite3
import tempfile
import time

os.environ["MEMORY_FILE"] = os.path.join(tempfile.mkdtemp(), "memory.db")

from app import memory  # noqa: E402


def main() -> None:
    memory.ensure_schema()

    memory.add(memory.LOCAL, "what did the doctor say about my results", "they are fine")
    memory.add(memory.CLOUD, "how tall is the eiffel tower", "about 330 meters")
    memory.add(memory.LIVE, "what is the weather", "sunny")

    cloud = " ".join(m["content"] for m in memory.recent_for_cloud()).lower()
    local = " ".join(m["content"] for m in memory.recent_for_local()).lower()

    assert "doctor" not in cloud, "LEAK: Saturn content reachable from the cloud path"
    assert "weather" not in cloud, "LEAK: live-session content reachable from cloud path"
    assert "eiffel" in cloud, "cloud lost its own thread"
    print("isolation   cloud sees only its own thread")

    assert all(word in local for word in ("doctor", "eiffel", "weather"))
    print("one-way     Saturn sees every thread")

    conn = sqlite3.connect(os.environ["MEMORY_FILE"])
    conn.execute(
        "INSERT INTO turns (mode, question, answer, at) VALUES (?, ?, ?, ?)",
        ("cloud", "ancient", "ancient", time.time() - memory.WINDOW_SECONDS - 60),
    )
    conn.commit()
    conn.close()
    assert "ancient" not in " ".join(m["content"] for m in memory.recent_for_cloud())
    print("window      stale turns drop out of context")

    for i in range(10):
        memory.add(memory.CLOUD, f"question {i}", f"answer {i}")
    assert len(memory.recent_for_cloud()) == memory.MAX_TURNS * 2
    print(f"cap         bounded to {memory.MAX_TURNS} turns")

    dropped = memory.forget_active()
    assert memory.recent_for_cloud() == [] and memory.recent_for_local() == []
    kept = sqlite3.connect(os.environ["MEMORY_FILE"]).execute(
        "SELECT COUNT(*) FROM turns"
    ).fetchone()[0]
    assert kept == 1, f"archived history should survive /forget, found {kept}"
    print(f"forget      dropped {dropped} active, kept {kept} archived")

    print("\nPASS - one-way memory rule holds")


if __name__ == "__main__":
    main()
