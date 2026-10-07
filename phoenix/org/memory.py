"""حافظهٔ دائمی سازمان — فایل‌های JSON ساده (در Actions روی شاخهٔ phoenix-memory ذخیره می‌شود)."""
from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_DIR = os.environ.get(
    "PHOENIX_MEMORY_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "memory")),
)

FILES = {
    "decisions": [],     # تصمیم‌های باز و بستهٔ اخیر
    "accuracy": {},      # dept -> regime -> {"acc": float, "n": int}
    "experience": [],    # درس‌های ریشه‌یابی‌شده
    "audits": [],        # ممیزی هر ۱۰/۱۰۰/۱۰۰۰
    "counters": {"signals": 0, "closed": 0, "tp": 0, "sl": 0, "expired": 0},
}

DECISIONS_KEEP = 400
EXPERIENCE_KEEP = 1000


class Memory:
    def __init__(self, root: str | None = None):
        self.root = root or DEFAULT_DIR
        os.makedirs(self.root, exist_ok=True)
        self.data: dict[str, Any] = {}
        for name, default in FILES.items():
            self.data[name] = self._load(name, default)

    def _path(self, name: str) -> str:
        return os.path.join(self.root, f"{name}.json")

    def _load(self, name: str, default: Any) -> Any:
        p = self._path(name)
        if not os.path.exists(p):
            return json.loads(json.dumps(default))
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return json.loads(json.dumps(default))

    def save(self) -> None:
        self.data["decisions"] = self._trim_decisions(self.data["decisions"])
        self.data["experience"] = self.data["experience"][-EXPERIENCE_KEEP:]
        for name in FILES:
            with open(self._path(name), "w", encoding="utf-8") as fh:
                json.dump(self.data[name], fh, ensure_ascii=False, indent=1, default=str)

    @staticmethod
    def _trim_decisions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        open_ = [d for d in items if d.get("status") == "open"]
        closed = [d for d in items if d.get("status") != "open"]
        return closed[-(DECISIONS_KEEP - len(open_)):] + open_ if len(items) > DECISIONS_KEEP else items

    # ---- accuracy (دقت غلتان هر دپارتمان در هر رژیم) ----
    def accuracy(self, dept: str, regime: str) -> float:
        node = self.data["accuracy"].get(dept, {}).get(regime)
        if not node:
            return 0.5
        return float(node.get("acc", 0.5))

    def update_accuracy(self, dept: str, regime: str, correct: bool, alpha: float = 0.15) -> None:
        bucket = self.data["accuracy"].setdefault(dept, {}).setdefault(regime, {"acc": 0.5, "n": 0})
        bucket["acc"] = round((1 - alpha) * float(bucket["acc"]) + alpha * (1.0 if correct else 0.0), 4)
        bucket["n"] = int(bucket.get("n", 0)) + 1

    # ---- decisions ----
    def open_decisions(self) -> list[dict[str, Any]]:
        return [d for d in self.data["decisions"] if d.get("status") == "open"]

    def has_open(self, symbol: str) -> bool:
        return any(d.get("symbol") == symbol for d in self.open_decisions())

    def add_decision(self, decision: dict[str, Any]) -> None:
        self.data["decisions"].append(decision)
        self.data["counters"]["signals"] = int(self.data["counters"].get("signals", 0)) + 1

    def find_decision(self, decision_id: str) -> dict[str, Any] | None:
        for d in self.data["decisions"]:
            if d.get("id") == decision_id:
                return d
        return None

    # ---- experience ----
    def add_experience(self, exp: dict[str, Any]) -> None:
        self.data["experience"].append(exp)

    def similar_experiences(
        self, symbol: str, regime: str, direction: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        same_sym = [
            e for e in self.data["experience"]
            if e.get("symbol") == symbol and e.get("regime") == regime and e.get("direction") == direction
        ]
        same_regime = [
            e for e in self.data["experience"]
            if e.get("regime") == regime and e.get("direction") == direction
        ]
        return (same_sym or same_regime)[-limit:]
