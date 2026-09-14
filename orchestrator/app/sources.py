import re
from pathlib import Path

SUPPORTED = {".txt", ".md", ".pdf", ".docx"}

# Matches both export styles WhatsApp produces:
#   [12/03/2024, 14:23:11] Sinem: message      (iOS)
#   12/03/2024, 14:23 - Sinem: message         (Android)
WHATSAPP_LINE = re.compile(
    r"^\[?(\d{1,2}[./]\d{1,2}[./]\d{2,4}),?\s+"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap][.\s]?[Mm][.]?)?\]?\s*"
    r"[-–]?\s*([^:]{1,60}?):\s(.*)$"
)

# One message alone carries no context, so messages are grouped into blocks and
# the blocks are separated by a blank line. vectors.chunk() splits on exactly
# that, so a retrieved chunk is always a readable stretch of conversation.
MESSAGES_PER_BLOCK = 20


def looks_like_whatsapp(text: str) -> bool:
    head = text.splitlines()[:40]
    hits = sum(1 for line in head if WHATSAPP_LINE.match(line))
    return hits >= 3


def _whatsapp(text: str) -> str:
    messages: list[str] = []
    for line in text.splitlines():
        match = WHATSAPP_LINE.match(line)
        if match:
            day, sender, body = match.groups()
            messages.append(f"[{day}] {sender}: {body}")
        elif messages and line.strip():
            messages[-1] += " " + line.strip()

    blocks = [
        "\n".join(messages[i : i + MESSAGES_PER_BLOCK])
        for i in range(0, len(messages), MESSAGES_PER_BLOCK)
    ]
    return "\n\n".join(blocks)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _docx(path: Path) -> str:
    import docx

    paragraphs = [p.text.strip() for p in docx.Document(str(path)).paragraphs]
    return "\n\n".join(p for p in paragraphs if p)


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf(path)
    if suffix == ".docx":
        return _docx(path)

    text = path.read_text(encoding="utf-8", errors="replace")
    return _whatsapp(text) if looks_like_whatsapp(text) else text
