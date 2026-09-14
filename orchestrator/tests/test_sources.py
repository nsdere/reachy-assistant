"""WhatsApp export parsing, across the formats WhatsApp actually produces.

    docker compose run --rm orchestrator python -m tests.test_sources
"""

from app.sources import MESSAGES_PER_BLOCK, _whatsapp, looks_like_whatsapp

IOS = """[12/03/2024, 14:23:11] Sinem: are you coming tonight
[12/03/2024, 14:24:02] Ada: yes around 8
[12/03/2024, 14:24:30] Sinem: bring the blue folder
it has the tax papers
[12/03/2024, 14:25:00] Ada: got it"""

ANDROID = """12/03/2024, 14:23 - Sinem: are you coming tonight
12/03/2024, 14:24 - Ada: yes around 8
12/03/2024, 14:25 - Sinem: bring the blue folder
12/03/2024, 14:26 - Ada: <Media omitted>"""

US_12_HOUR = """[3/12/24, 2:23:11 PM] Sinem: are you coming tonight
[3/12/24, 2:24:02 PM] Ada: yes around 8
[3/12/24, 2:25:00 PM] Sinem: bring the blue folder"""


def main() -> None:
    for name, sample in (("iOS", IOS), ("Android", ANDROID), ("US 12h", US_12_HOUR)):
        assert looks_like_whatsapp(sample), f"{name} export not detected"
        assert "Sinem: are you coming tonight" in _whatsapp(sample), f"{name} lost a message"
        print(f"{name:12} detected and parsed")

    assert "tax papers" in _whatsapp(IOS), "wrapped line was dropped"
    print("continuation folded into the message above it")

    prose = "Dear Ada,\n\nThe meeting is at 3pm on 12/03/2024.\n\nBest,\nSinem"
    assert not looks_like_whatsapp(prose), "a plain letter was misread as a chat export"
    print("plain prose  not mistaken for a chat")

    many = "\n".join(
        f"[12/03/2024, 14:{i:02d}:00] Sinem: message number {i}" for i in range(45)
    )
    blocks = _whatsapp(many).split("\n\n")
    assert len(blocks) == 3, f"expected 3 blocks, got {len(blocks)}"
    assert blocks[0].count("\n") + 1 == MESSAGES_PER_BLOCK
    print(f"grouping     45 messages -> {len(blocks)} blocks of {MESSAGES_PER_BLOCK}")

    print("\nPASS - WhatsApp parsing")


if __name__ == "__main__":
    main()
