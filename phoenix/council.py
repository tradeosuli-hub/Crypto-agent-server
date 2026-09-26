"""شورا — ققنوس اول؛ بدون SETUP ققنوس سیگنال نهایی نیست."""
from __future__ import annotations

from typing import Any

from phoenix.ghoghnoos import confirm


def council_vote(
    ghoghnoos: dict[str, Any],
    guardians: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    guardians: [{"name": str, "direction": "long|short|flat", "confidence": 0..1}]
    """
    guardians = guardians or []
    tagged = []
    for g in guardians:
        c = confirm(g.get("direction", "flat"), ghoghnoos)
        conf = float(g.get("confidence", 0.5)) * c["mult"]
        conf = min(1.0, conf)
        tagged.append({**g, "confirm": c, "confidence_adj": conf})

    final = ghoghnoos.get("verdict", "FLAT")
    if final != "SETUP":
        # SIGNAL نهایی بدون SETUP ققنوس صادر نمی‌شود
        action = "WATCH" if final == "WATCH" else final
    else:
        action = "SIGNAL"

    return {
        "action": action,
        "ghoghnoos": {
            "verdict": ghoghnoos.get("verdict"),
            "direction": ghoghnoos.get("direction"),
            "score": ghoghnoos.get("score"),
        },
        "guardians": tagged,
        "note_fa": "ققنوس حکم می‌دهد؛ شورا ارسال می‌کند. بدون SETUP ققنوس → WATCH.",
    }
