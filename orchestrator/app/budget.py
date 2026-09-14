import json
from datetime import date
from pathlib import Path

from .config import settings


def _read() -> dict:
    path = Path(settings.budget_file)
    if not path.exists():
        return {"day": str(date.today()), "spent": 0.0}
    data = json.loads(path.read_text())
    if data["day"] != str(date.today()):
        return {"day": str(date.today()), "spent": 0.0}
    return data


def spent_today() -> float:
    return _read()["spent"]


def remaining() -> float:
    return max(0.0, settings.daily_budget_usd - spent_today())


def record(cost_usd: float) -> None:
    data = _read()
    data["spent"] += cost_usd
    path = Path(settings.budget_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
